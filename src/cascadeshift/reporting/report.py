"""Self-contained HTML research report (RP-01, RP-02).

No CDN, no JS dependencies; charts are inline SVG. Null and adverse results
are rendered unconditionally. The illustrative trajectory is chosen only by
the predeclared rule from protocol/preregistration.md.
"""

from __future__ import annotations

import html
import json
from typing import Any

from cascadeshift.agents.protocol import (
    EpisodeRecord,
    EvidenceSource,
    LiveArchiveBinding,
    live_archive_binding,
)

CONDITIONS = ("surface", "frozen_discovery", "live_discovery")
EVIDENCE_SOURCES = frozenset({"scripted_validation", "live_model", "unverified_live_archive"})


def validate_report_inputs(
    *,
    episodes: list[EpisodeRecord],
    stats: dict[str, Any],
    evidence_source: EvidenceSource | str,
    split_label: str,
    canonical_live_bindings: frozenset[LiveArchiveBinding] | None = None,
) -> None:
    """Reject reports whose evidence label or canonical provenance is invalid."""
    if evidence_source not in EVIDENCE_SOURCES:
        raise ValueError("unknown evidence source")
    if not episodes:
        raise ValueError("report requires at least one episode")
    modes = {episode.execution_mode for episode in episodes}
    if len(modes) != 1:
        raise ValueError("report episodes must have one homogeneous execution_mode")
    mode = next(iter(modes), None)
    if evidence_source == "scripted_validation":
        if mode != "scripted":
            raise ValueError("scripted_validation requires scripted episode records")
    elif evidence_source == "live_model":
        if mode != "live":
            raise ValueError(f"{evidence_source} requires live episode records")
        if not any(
            episode.provider_error is None and episode.provider_model is not None
            for episode in episodes
        ):
            raise ValueError("live model evidence requires a successful provider response")
    elif mode != "live":
        raise ValueError("unverified_live_archive requires live episode records")
    if evidence_source == "live_model":
        if canonical_live_bindings is None:
            raise ValueError("live_model requires canonical archive bindings")
        actual = frozenset(live_archive_binding(episode) for episode in episodes)
        if len(actual) != len(episodes) or actual != canonical_live_bindings:
            raise ValueError("live archive does not match the canonical episode matrix")
        for episode in episodes:
            if not isinstance(episode.seed_supported, bool):
                raise ValueError("live archive has unknown provider seed capability")
            expected_seed = live_archive_binding(episode).provider_seed
            if episode.seed_supported and episode.requested_provider_seed != expected_seed:
                raise ValueError(
                    "seed-supporting live record has an invalid requested provider seed"
                )
            if not episode.seed_supported and episode.requested_provider_seed is not None:
                raise ValueError("seed-unsupported live record includes a requested provider seed")
    if "confirmatory" not in split_label.lower():
        return
    ids = [episode.episode_id for episode in episodes]
    if len(episodes) != 450 or len(set(ids)) != 450:
        raise ValueError("confirmatory report requires exactly 450 unique episodes")
    by_task_world: dict[tuple[str, str], list[EpisodeRecord]] = {}
    for episode in episodes:
        by_task_world.setdefault((episode.case_id, episode.world_id), []).append(episode)
    if len(by_task_world) != 50:
        raise ValueError("confirmatory report requires 50 task-world groups")
    for group in by_task_world.values():
        by_condition = {
            condition: [episode for episode in group if episode.condition == condition]
            for condition in CONDITIONS
        }
        if any(len(by_condition[condition]) != 3 for condition in CONDITIONS):
            raise ValueError("confirmatory report requires 3 conditions x 3 repeats per task-world")
        seed_sets = [
            {episode.rollout_seed_id for episode in by_condition[condition]}
            for condition in CONDITIONS
        ]
        if (
            any(len(seeds) != 3 for seeds in seed_sets)
            or len({frozenset(seeds) for seeds in seed_sets}) != 1
        ):
            raise ValueError("confirmatory repeats must be matched across conditions")
    primary = stats.get("primary", {})
    if primary.get("n_clusters") != 20:
        raise ValueError("confirmatory report requires all 20 primary DiD parent clusters")


def select_trajectory(
    episodes: list[EpisodeRecord],
    case_effect: dict[str, str],
    cascade_depths: dict[str, int],
) -> dict[str, Any] | None:
    """Predeclared rule:

    1. candidates = confirmatory cases where C1 majority-fails and C2
       majority-passes (>=2 of 3 repeats);
    2. median cascade depth, defined as the LOWER median
       (element at index (n-1)//2 of the ascending depth list);
    3. ties -> lexicographically smallest shift_id/case_id;
    4. fallback: largest |C2-C1| CSTS difference, same tie-break.
    """

    def counts(case: str, cond: str) -> tuple[int, int]:
        sel = [
            e
            for e in episodes
            if e.case_id == case and e.condition == cond and e.provider_error is None
        ]
        return sum(1 for e in sel if e.verdict.csts), len(sel)

    candidates = []
    cases = sorted(case_effect)
    for case in cases:
        c1_pass, c1_n = counts(case, "frozen_discovery")
        c2_pass, c2_n = counts(case, "live_discovery")
        if c1_n != 3 or c2_n != 3:
            continue
        if c1_pass > 1:
            continue
        if c2_pass < 2:
            continue
        depth = cascade_depths.get(case, 0)
        candidates.append((depth, case))
    if candidates:
        depths = sorted(d for d, _ in candidates)
        mid = depths[(len(depths) - 1) // 2]  # lower median
        best = min((c for c in candidates if c[0] == mid), key=lambda t: t[1])
        return {
            "case_id": best[1],
            "rule": "C1-majority-fail/C2-majority-pass",
            "cascade_depth": best[0],
        }
    # Fallback: largest absolute C2-C1 difference.
    diffs: list[tuple[float, str]] = []
    for case in cases:
        c1p, c1n = counts(case, "frozen_discovery")
        c2p, c2n = counts(case, "live_discovery")
        if c1n and c2n:
            diffs.append((abs(c2p / c2n - c1p / c1n), case))
    if not diffs:
        return None
    top = max(d for d, _ in diffs)
    case = min(c for d, c in diffs if d == top)
    return {
        "case_id": case,
        "rule": "fallback largest |C2-C1|",
        "cascade_depth": cascade_depths.get(case, 0),
    }


def _svg_bars(items: list[tuple[str, float]], width: int = 420, height: int | None = None) -> str:
    if height is None:
        height = 30 + 34 * max(len(items), 1)
    bar_w = width - 180
    rows = []
    y = 10
    for label, v in items:
        v = max(0.0, min(1.0, v))
        rows.append(
            f'<text x="0" y="{y + 16}" font-size="13" fill="#ddd">{html.escape(label)}</text>'
            f'<rect x="170" y="{y}" width="{bar_w}" height="20" fill="#233"/>'
            f'<rect x="170" y="{y}" width="{int(bar_w * v)}" height="20" fill="#5ad"/>'
            f'<text x="{172 + int(bar_w * v)}" y="{y + 15}" font-size="12" '
            f'fill="#fff">{v:.2f}</text>'
        )
        y += 34
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" role="img">{"".join(rows)}</svg>'
    )


CONDITION_TITLES = {
    "surface": "C0 surface-only",
    "frozen_discovery": "C1 discovery (baseline snapshot)",
    "live_discovery": "C2 discovery (active snapshot)",
}


def _safe_json(value: Any) -> str:
    return html.escape(json.dumps(value, indent=2, sort_keys=True, default=str))


def _percentage_points(value: object) -> str:
    if not isinstance(value, (float, int)):
        return "unavailable"
    return f"{100 * value:+.1f} percentage points"


def _primary_summary(primary: dict[str, Any]) -> str:
    if not primary.get("estimable", primary.get("point") is not None):
        return (
            "<p>The primary freshness comparison could not be estimated because the "
            "required paired cells were incomplete.</p>"
        )
    point = _percentage_points(primary.get("point"))
    low = _percentage_points(primary.get("lo"))
    high = _percentage_points(primary.get("hi"))
    clusters = html.escape(str(primary.get("n_clusters", "unavailable")))
    resamples = html.escape(str(primary.get("b", "unavailable")))
    confidence = primary.get("confidence_level", 0.95)
    shown_confidence = f"{100 * confidence:.0f}%" if isinstance(confidence, (float, int)) else "95%"
    return (
        f"<p><strong>Estimated freshness interaction: {point}.</strong> "
        f"The preregistered {shown_confidence} parent-cluster bootstrap interval is "
        f"{low} to {high}, "
        f"using {clusters} parent tasks and {resamples} resamples.</p>"
        "<p>This comparison asks whether the C2-versus-C1 gap is larger after a "
        "configuration shift than it is at baseline. Positive values favor access to "
        "the active snapshot within this harness; an interval spanning zero does not "
        "resolve the directional hypothesis.</p>"
    )


def _secondary_summary(
    record: dict[str, Any], *, label: str, definition: str, direction: str
) -> str:
    escaped_label = html.escape(label)
    if not record.get("estimable", record.get("point") is not None):
        summary = f"<p><strong>{escaped_label}:</strong> not estimable from these episodes.</p>"
    else:
        confidence = record.get("confidence_level", 0.90)
        shown_confidence = (
            f"{100 * confidence:.0f}%" if isinstance(confidence, (float, int)) else "90%"
        )
        summary = (
            f"<p><strong>{escaped_label}: {_percentage_points(record.get('point'))}.</strong> "
            f"The {shown_confidence} parent-cluster bootstrap interval is "
            f"{_percentage_points(record.get('lo'))} to "
            f"{_percentage_points(record.get('hi'))}. "
            f"{html.escape(direction)}</p>"
        )
    return (
        f"<p>{html.escape(definition)}</p>{summary}"
        "<details><summary>Machine-readable statistic</summary>"
        f"<pre>{_safe_json(record)}</pre></details>"
    )


def _plan_strata_summary(plan_strata: object) -> str:
    if not isinstance(plan_strata, dict) or not plan_strata:
        return "<p>Plan-stratum counts were unavailable.</p>"
    rows: list[str] = []
    for key, label in (
        ("plan_preserving", "Plan-preserving"),
        ("plan_invalidating", "Plan-invalidating"),
    ):
        record = plan_strata.get(key)
        if not isinstance(record, dict):
            continue
        rows.append(
            "<tr>"
            f"<th>{label}</th>"
            f"<td>{html.escape(str(record.get('cases', 'unavailable')))}</td>"
            f"<td>{html.escape(str(record.get('episodes', 'unavailable')))}</td>"
            f"<td>{html.escape(str(record.get('provider_failures', 'unavailable')))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>Plan-stratum counts were unavailable.</p>"
    return (
        "<table><thead><tr><th>Shift type</th><th>Cases</th><th>Episodes</th>"
        "<th>Provider failures</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _rate_rows(episodes: list[EpisodeRecord]) -> tuple[list[tuple[str, float]], list[str]]:
    bars: list[tuple[str, float]] = []
    rows: list[str] = []
    for condition in CONDITIONS:
        selected = [episode for episode in episodes if episode.condition == condition]
        eligible = [episode for episode in selected if episode.provider_error is None]
        passed = sum(episode.verdict.csts for episode in eligible)
        failures = len(selected) - len(eligible)
        if eligible:
            rate = passed / len(eligible)
            bars.append((CONDITION_TITLES[condition], rate))
            shown = f"{rate:.2f} ({passed}/{len(eligible)})"
        else:
            shown = "unavailable (0 eligible episodes)"
        rows.append(
            "<tr>"
            f"<th>{html.escape(CONDITION_TITLES[condition])}</th>"
            f"<td>{shown}</td><td>{failures}</td>"
            "</tr>"
        )
    return bars, rows


def _raw_summary(stats: dict[str, Any]) -> str:
    raw = stats.get("raw")
    if not isinstance(raw, dict) or not raw:
        return "<p>Raw numerators, denominators, and usage were unavailable.</p>"
    rows: list[str] = []
    for condition in CONDITIONS:
        record = raw.get(condition)
        if not isinstance(record, dict):
            continue
        for side in ("baseline", "shifted"):
            summary = record.get(side)
            if not isinstance(summary, dict):
                continue
            csts = summary.get("csts", {})
            silent = summary.get("silent_violations", {})
            usage = summary.get("usage", {})
            provider_failures = summary.get("provider_failures", "unavailable")
            rows.append(
                "<tr>"
                f"<th>{html.escape(CONDITION_TITLES[condition])}</th>"
                f"<td>{html.escape(side)}</td>"
                f"<td>{html.escape(str(csts.get('numerator', 'unavailable')))}"
                f"/{html.escape(str(csts.get('denominator', 'unavailable')))}</td>"
                f"<td>{html.escape(str(silent.get('numerator', 'unavailable')))}"
                f"/{html.escape(str(silent.get('denominator', 'unavailable')))}</td>"
                f"<td>{html.escape(str(provider_failures))}</td>"
                f"<td>{html.escape(str(usage.get('mean_total_tokens', 'unavailable')))}</td>"
                f"<td>{html.escape(str(usage.get('mean_total_tool_calls', 'unavailable')))}</td>"
                "</tr>"
            )
    if not rows:
        return "<p>Raw numerators, denominators, and usage were unavailable.</p>"
    return (
        "<table><thead><tr><th>Condition</th><th>World side</th>"
        "<th>CSTS (n/d)</th><th>Silent violations (n/d)</th>"
        "<th>Provider failures excluded</th><th>Mean tokens</th>"
        "<th>Mean tool calls</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _retrieval_summary(stats: dict[str, Any]) -> str:
    raw = stats.get("raw")
    retrieval = raw.get("retrieval") if isinstance(raw, dict) else None
    if not isinstance(retrieval, dict):
        return "<p>Retrieval metrics were unavailable.</p>"

    def mean(record: object, field: str) -> str:
        if not isinstance(record, dict):
            return "unavailable"
        value = record.get(field)
        if not isinstance(value, dict):
            return "unavailable"
        average = value.get("mean")
        defined = value.get("defined_episodes", 0)
        if not isinstance(average, (int, float)):
            return f"undefined (n={html.escape(str(defined))})"
        return f"{average:.3f} (n={html.escape(str(defined))})"

    rows: list[str] = []
    for condition in CONDITIONS:
        condition_record = retrieval.get(condition)
        if not isinstance(condition_record, dict):
            continue
        for side in ("baseline", "shifted"):
            record = condition_record.get(side)
            rows.append(
                "<tr>"
                f"<th>{html.escape(CONDITION_TITLES[condition])}</th>"
                f"<td>{html.escape(side)}</td>"
                f"<td>{mean(record, 'causal_closure_size')}</td>"
                f"<td>{mean(record, 'returned_rule_precision')}</td>"
                f"<td>{mean(record, 'returned_rule_recall')}</td>"
                f"<td>{mean(record, 'inspected_rule_precision')}</td>"
                f"<td>{mean(record, 'inspected_rule_recall')}</td>"
                f"<td>{mean(record, 'first_relevant_returned_discovery_call')}</td>"
                f"<td>{mean(record, 'first_relevant_inspected_discovery_call')}</td>"
                "</tr>"
            )
    if not rows:
        return "<p>Retrieval metrics were unavailable.</p>"
    return (
        "<p>Means are shown with the number of episodes having a defined denominator. "
        "Undefined cells remain explicit.</p>"
        "<table><thead><tr><th>Condition</th><th>World side</th>"
        "<th>Closure size</th><th>Returned precision</th><th>Returned recall</th>"
        "<th>Inspected precision</th><th>Inspected recall</th>"
        "<th>First relevant return call</th><th>First relevant inspect call</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def build_report_html(
    *,
    episodes: list[EpisodeRecord],
    stats: dict[str, Any],
    evidence_source: EvidenceSource | str,
    split_label: str,
    anchor_locator: str,
    reproduce_command: str,
    canonical_live_bindings: frozenset[LiveArchiveBinding] | None = None,
    source_archive_sha256: str | None = None,
    custody_receipt_sha256: str | None = None,
) -> str:
    validate_report_inputs(
        episodes=episodes,
        stats=stats,
        evidence_source=evidence_source,
        split_label=split_label,
        canonical_live_bindings=canonical_live_bindings,
    )
    if evidence_source == "live_model" and (
        source_archive_sha256 is None or custody_receipt_sha256 is None
    ):
        raise ValueError("live_model report requires archive and custody receipt digests")
    for label, digest in (
        ("archive", source_archive_sha256),
        ("custody receipt", custody_receipt_sha256),
    ):
        if digest is not None and (
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"invalid {label} digest")
    by_cond: dict[str, list[EpisodeRecord]] = {}
    for e in episodes:
        by_cond.setdefault(e.condition, []).append(e)

    silent_rates: list[tuple[str, float]] = []
    headline_rates, headline_rows = _rate_rows(episodes)
    for cond in CONDITIONS:
        sel = by_cond.get(cond, [])
        eligible = [episode for episode in sel if episode.provider_error is None]
        if eligible:
            silent_rates.append(
                (CONDITION_TITLES[cond], sum(e.silent_violation for e in eligible) / len(eligible))
            )

    primary = stats.get("primary", {})
    strat_pres = stats.get("stratum_plan_preserving", {})
    strat_inv = stats.get("stratum_plan_invalidating", {})
    stale = stats.get("stale_harm", {})

    nulls = []
    if not primary.get("estimable", primary.get("n_clusters", 0) > 0):
        nulls.append(
            "Primary estimand not computable from provided episodes (missing paired cells)."
        )
    if isinstance(primary.get("point"), (float, int)) and primary["point"] <= 0:
        nulls.append(
            "Freshness interaction is zero or negative: no live-"
            "discovery advantage detected in this data."
        )
    if silent_rates and all(v == 0 for _, v in silent_rates):
        nulls.append("No silent constraint violations observed.")

    trajectory = stats.get("trajectory")

    parts: list[str] = []
    parts.append(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>CascadeShift research report</title>"
    )
    if source_archive_sha256 is not None:
        parts.append(f"<meta name='cascadeshift-archive-sha256' content='{source_archive_sha256}'>")
    if custody_receipt_sha256 is not None:
        parts.append(
            f"<meta name='cascadeshift-receipt-sha256' content='{custody_receipt_sha256}'>"
        )
    parts.append(
        "<style>body{background:#111;color:#eee;font-family:"
        "-apple-system,Segoe UI,sans-serif;margin:40px auto;"
        "max-width:960px;line-height:1.5}h1{font-weight:600}"
        "h2{border-bottom:1px solid #333;padding-bottom:6px;"
        "margin-top:44px}code{background:#1d1d1d;padding:2px 5px;"
        "border-radius:4px}.muted{color:#999}table{border-collapse:"
        "collapse}td,th{border:1px solid #333;padding:6px 10px;"
        "font-size:14px;text-align:left}.warning{border:1px solid #f5a623;"
        "background:#3b2d08;color:#ffe0a3;padding:12px}.status{border-left:4px solid "
        "#5ad;padding:10px 14px;background:#18232d}</style></head><body>"
    )
    parts.append("<h1>CascadeShift research report</h1>")
    if evidence_source == "scripted_validation":
        parts.append(
            "<p class='warning'><strong>SCRIPTED VALIDATION, NOT A MODEL "
            "EVALUATION.</strong> These episodes were produced by deterministic scripted "
            "agents to test the harness end to end. Do not interpret the rates below as "
            "evidence about any model.</p>"
        )
    if evidence_source == "unverified_live_archive":
        parts.append(
            "<p class='warning'><b>UNVERIFIED LIVE ARCHIVE.</b> This archive contains "
            "live-mode records but does not meet the signed and anchored confirmatory custody "
            "gate. Do not use it for confirmatory or authoritative claims.</p>"
        )
    parts.append(
        f"<p class='muted'>Evidence source: <b>{html.escape(evidence_source)}"
        f"</b> &middot; Split: {html.escape(split_label)} &middot; "
        f"Protocol anchor: {html.escape(anchor_locator)}</p>"
    )
    parts.append(
        "<div class='status'><strong>How to read this report.</strong> Constraint-Safe "
        "Task Success (CSTS) counts an episode only when the requested goal is achieved "
        "and every hard final-state constraint still holds. Provider failures are "
        "retained in the archive but excluded from the eligible CSTS denominator and "
        "shown separately.</div>"
    )
    parts.append("<h2>Outcome summary</h2>")
    parts.append(
        "<table><thead><tr><th>Condition</th><th>CSTS</th>"
        "<th>Provider failures excluded</th></tr></thead><tbody>"
    )
    parts.extend(headline_rows)
    parts.append("</tbody></table>")
    parts.append("<h2>CSTS by condition</h2>" + _svg_bars(headline_rates))
    parts.append(
        "<h2>Silent constraint violation rate</h2>"
        + (
            _svg_bars(silent_rates)
            if any(v for _, v in silent_rates)
            else "<p>No silent violations observed.</p>"
        )
    )
    parts.append(
        "<h2>Primary freshness comparison</h2>"
        + _primary_summary(primary)
        + "<details><summary>Machine-readable statistic</summary>"
        + f"<pre>{_safe_json(primary)}</pre></details>"
    )
    parts.append("<h2>Results by plan effect</h2>")
    parts.append(
        _secondary_summary(
            strat_pres,
            label="Plan-preserving freshness interaction",
            definition=(
                "A plan-preserving shift leaves the original valid plan usable. This "
                "comparison measures C2 versus C1 after adjusting for their baseline gap."
            ),
            direction="Positive values favor access to the active snapshot in this stratum.",
        )
    )
    parts.append(
        _secondary_summary(
            strat_inv,
            label="Plan-invalidating freshness interaction",
            definition=(
                "A plan-invalidating shift keeps the task solvable but requires a different "
                "plan. This comparison measures C2 versus C1 after adjusting for baseline."
            ),
            direction="Positive values favor access to the active snapshot in this stratum.",
        )
    )
    parts.append("<h2>Stale-context harm compared with C0</h2>")
    parts.append(
        _secondary_summary(
            stale,
            label="C1 minus C0 on plan-invalidating shifts",
            definition=(
                "This secondary comparison asks whether stale rule discovery performed "
                "better or worse than having no discovery on shifts that require a new plan."
            ),
            direction="Negative values mean stale discovery performed worse than C0.",
        )
    )
    parts.append("<h2>Raw counts and usage</h2>" + _raw_summary(stats))
    parts.append(
        "<h2>Rule discovery and causal coverage</h2>"
        "<p>Causal closure is the set of rules and dependencies that can explain the "
        "recorded consequence chain. Precision shows how much retrieved material was "
        "relevant; recall shows how much of that relevant set the agent found.</p>"
        + _retrieval_summary(stats)
    )
    plan_strata = (
        stats.get("raw", {}).get("plan_strata", {}) if isinstance(stats.get("raw"), dict) else {}
    )
    parts.append("<h2>Plan-stratum counts</h2>" + _plan_strata_summary(plan_strata))
    parts.append("<h2>Illustrative episode selected by the protocol</h2>")
    if trajectory:
        parts.append(
            f"<p>Selected post-run by the predeclared algorithm "
            f"({html.escape(str(trajectory.get('rule')))}): "
            f"<code>{html.escape(str(trajectory.get('case_id')))}</code>, "
            f"cascade depth {html.escape(str(trajectory.get('cascade_depth')))}. "
            f"This is illustrative, not additional statistical evidence.</p>"
        )
    else:
        parts.append("<p>No candidate satisfied the predeclared rule.</p>")
    parts.append("<h2>Negative and null findings</h2>")
    if nulls:
        parts.append("<ul>" + "".join(f"<li>{html.escape(n)}</li>" for n in nulls) + "</ul>")
    else:
        parts.append("<p>None beyond those visible above.</p>")
    parts.append(
        "<h2>Reproduction</h2>"
        f"<p>Exact command: <code>{html.escape(reproduce_command)}</code></p>"
        "<p class='muted'>Claims discipline: this bounded synthetic result "
        "does not establish production failure rates, novelty, or that "
        "enterprise agents generally require live rule access. Kill criteria "
        "and permitted claims are enforced by scripts/verify_claims.py.</p></body></html>"
    )
    return "".join(parts)


def _key(label: str) -> str:
    for k, v in CONDITION_TITLES.items():
        if v == label:
            return k
    raise KeyError(label)
