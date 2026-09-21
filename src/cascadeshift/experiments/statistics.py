"""Episode aggregation and parent-task-clustered statistics (ST-01, M-01)."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cascadeshift.agents.protocol import EpisodeRecord

BOOTSTRAP_SEED = 20260825
B_RESAMPLES = 10000


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def condition_csts(
    episodes: list[EpisodeRecord], condition: str, world_hash: str | None = None
) -> tuple[int, int, float | None]:
    """(numerator, denominator, rate) of CSTS for one condition slice."""
    sel = [
        e
        for e in episodes
        if e.condition == condition
        and e.provider_error is None
        and (world_hash is None or e.world_hash == world_hash)
    ]
    n = len(sel)
    k = sum(1 for e in sel if e.verdict.csts)
    return k, n, (k / n if n else None)


def episode_csts(episodes: list[EpisodeRecord]) -> tuple[int, int, int, float | None]:
    """CSTS count, eligible count, provider failures, and rate for an episode set."""
    eligible = [episode for episode in episodes if episode.provider_error is None]
    passed = sum(1 for episode in eligible if episode.verdict.csts)
    failures = len(episodes) - len(eligible)
    rate = passed / len(eligible) if eligible else None
    return passed, len(eligible), failures, rate


def silent_violation_rate(
    episodes: list[EpisodeRecord], condition: str
) -> tuple[int, int, float | None]:
    sel = [e for e in episodes if e.condition == condition and e.provider_error is None]
    n = len(sel)
    k = sum(1 for e in sel if e.silent_violation)
    return k, n, (k / n if n else None)


class ParentCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_task_id: str
    csts: dict[str, float] = Field(default_factory=dict)  # condition -> mean


def within_parent_means(episodes: list[EpisodeRecord]) -> dict[str, ParentCell]:
    """Mean CSTS per condition within each parent task (nested repeats)."""
    out: dict[str, dict[str, list[int]]] = {}
    for e in episodes:
        if e.provider_error is not None:
            continue
        out.setdefault(e.parent_task_id, {}).setdefault(e.condition, [])
        bucket = out[e.parent_task_id][e.condition]
        bucket.append(1 if e.verdict.csts else 0)
    cells: dict[str, ParentCell] = {}
    for pid, by_cond in out.items():
        cells[pid] = ParentCell(
            parent_task_id=pid,
            csts={c: _mean([float(x) for x in v]) for c, v in by_cond.items()},
        )
    return cells


def freshness_interaction_cells(
    episodes: list[EpisodeRecord],
    shifted_hashes: set[str] | None = None,
) -> dict[str, list[float]]:
    """Per-parent DiD contributions: (C2-C1)_shifted - (C2-C1)_baseline.

    Episodes on worlds whose hash is in `shifted_hashes` count as shifted;
    everything else counts as baseline side.
    """
    hashes = shifted_hashes if shifted_hashes is not None else set()
    dids: dict[str, list[float]] = {}

    def cond_mean(pid: str, cond: str, shifted: bool) -> float | None:
        # Re-derive from raw episodes to separate baseline/shifted sides.
        sel = [
            e
            for e in episodes
            if e.parent_task_id == pid
            and e.condition == cond
            and e.provider_error is None
            and ((e.world_hash in hashes) == shifted)
        ]
        if not sel:
            return None
        return _mean([1.0 if e.verdict.csts else 0.0 for e in sel])

    pids = sorted({e.parent_task_id for e in episodes})
    for pid in pids:
        c1b = cond_mean(pid, "frozen_discovery", False)
        c2b = cond_mean(pid, "live_discovery", False)
        c1s = cond_mean(pid, "frozen_discovery", True)
        c2s = cond_mean(pid, "live_discovery", True)
        if c1b is None or c2b is None or c1s is None or c2s is None:
            continue
        dids[pid] = [(c2s - c1s) - (c2b - c1b)]
    return dids


def cluster_bootstrap_ci(
    values_by_cluster: dict[str, list[float]],
    b: int = B_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    level: float = 0.95,
) -> dict[str, float | int | None]:
    """Percentile bootstrap over clusters (parent tasks)."""
    rng = random.Random(seed)
    clusters = [k for k, v in values_by_cluster.items() if v]
    if not clusters:
        return {
            "n_clusters": 0,
            "point": None,
            "mean": None,
            "lo": None,
            "hi": None,
            "b": b,
            "seed": seed,
            "confidence_level": level,
            "estimable": False,
        }
    means = []
    all_vals = [x for k in clusters for x in values_by_cluster[k]]
    point = _mean(all_vals)
    for _ in range(b):
        sample = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        vals = [x for k in sample for x in values_by_cluster[k]]
        means.append(_mean(vals))
    means.sort()
    alpha = (1 - level) / 2
    lo = means[max(0, int(alpha * len(means)))]
    hi = means[min(len(means) - 1, int((1 - alpha) * len(means)) - 1 + 1)]
    return {
        "n_clusters": len(clusters),
        "point": round(point, 6),
        "mean": round(point, 6),
        "lo": round(lo, 6),
        "hi": round(hi, 6),
        "b": b,
        "seed": seed,
        "confidence_level": level,
        "estimable": True,
    }


def stratum_did(
    episodes: list[EpisodeRecord],
    effect: str,
    case_effect: dict[str, str],
    shifted_hashes: set[str],
) -> dict[str, Any]:
    """C2-C1 DiD restricted to shifted cases with the given plan_effect.

    Baseline-side episodes of the same parents are included so the
    difference-in-differences is well-defined.
    """
    wanted_cases = {cid for cid, eff in case_effect.items() if eff == effect}
    wanted_parents = {e.parent_task_id for e in episodes if e.case_id in wanted_cases}
    sub = [
        e
        for e in episodes
        if (
            e.world_hash in shifted_hashes
            and e.case_id in wanted_cases
            or e.world_hash not in shifted_hashes
            and e.parent_task_id in wanted_parents
        )
    ]
    dids = freshness_interaction_cells(sub, shifted_hashes=shifted_hashes)
    ci = cluster_bootstrap_ci(dids, level=0.90)
    return {"effect": effect, "parents": len(dids), **ci}


def stale_harm_on_invalidating(
    episodes: list[EpisodeRecord],
    case_effect: dict[str, str],
) -> dict[str, Any]:
    """CSTS_C1 - CSTS_C0 over plan-invalidating shifts."""
    wanted = {cid for cid, eff in case_effect.items() if eff == "plan_invalidating"}
    sub = [e for e in episodes if e.case_id in wanted]
    by_parent: dict[str, list[float]] = {}
    pids = sorted({e.parent_task_id for e in sub})

    def cm(pid: str, cond: str) -> float | None:
        sel = [
            e
            for e in sub
            if e.parent_task_id == pid and e.condition == cond and e.provider_error is None
        ]
        if not sel:
            return None
        return _mean([1.0 if e.verdict.csts else 0.0 for e in sel])

    for pid in pids:
        c0 = cm(pid, "surface")
        c1 = cm(pid, "frozen_discovery")
        if c0 is not None and c1 is not None:
            by_parent[pid] = [c1 - c0]
    return {
        "metric": "CSTS_C1-CSTS_C0 on plan_invalidating",
        **cluster_bootstrap_ci(by_parent, level=0.90),
    }


def digest(obj: object) -> str:
    from cascadeshift.domain.rules import canonical_json

    payload = canonical_json(obj)
    return hashlib.sha256(payload.encode()).hexdigest()
