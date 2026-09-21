#!/usr/bin/env python3
"""Read-only audit of the frozen confirmatory archive; imports no project code."""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/results/confirmatory/episodes.json"
SPLIT = ROOT / "tasks/confirmatory/split.json"
OUT = ROOT / "artifacts/verification/recompute-results.json"


def mean(values: list[float]) -> float:
    return statistics.fmean(values)


def quantile_ci(values: list[float], level: float = 0.95) -> tuple[float, float]:
    values.sort()
    alpha = (1.0 - level) / 2.0
    return values[int(alpha * len(values))], values[
        min(len(values) - 1, int((1 - alpha) * len(values)))
    ]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    archive_bytes = ARCHIVE.read_bytes()
    split_bytes = SPLIT.read_bytes()
    episodes = json.loads(archive_bytes)
    split = json.loads(split_bytes)
    shifted_ids = {c["task_id"] for c in split["cases"]}
    expected = {
        (case, condition, repeat)
        for case in [f"T-C-{i:04d}" for i in range(1, 21)] + sorted(shifted_ids)
        for condition in ("surface", "frozen_discovery", "live_discovery")
        for repeat in range(1, 4)
    }
    observed = set()
    duplicate_ids = 0
    for e in episodes:
        eid = e["episode_id"]
        repeat = int(eid.rsplit("r", 1)[1])
        key = (e["case_id"], e["condition"], repeat)
        if key in observed:
            duplicate_ids += 1
        observed.add(key)

    by_parent_side_condition: dict[tuple[str, bool, str], list[float]] = defaultdict(list)
    for e in episodes:
        if e["provider_error"] is None:
            by_parent_side_condition[
                (e["parent_task_id"], e["case_id"] in shifted_ids, e["condition"])
            ].append(float(e["verdict"]["csts"]))
    dids: dict[str, float] = {}
    for parent in sorted({e["parent_task_id"] for e in episodes}):
        try:
            c1b = mean(by_parent_side_condition[(parent, False, "frozen_discovery")])
            c2b = mean(by_parent_side_condition[(parent, False, "live_discovery")])
            c1s = mean(by_parent_side_condition[(parent, True, "frozen_discovery")])
            c2s = mean(by_parent_side_condition[(parent, True, "live_discovery")])
        except KeyError:
            continue
        dids[parent] = (c2s - c1s) - (c2b - c1b)
    rng = random.Random(20260825)
    keys = sorted(dids)
    boot = [mean([dids[keys[rng.randrange(len(keys))]] for _ in keys]) for _ in range(10_000)]
    ci = quantile_ci(boot)

    c2_failures = [
        e
        for e in episodes
        if e["condition"] == "live_discovery"
        and not e["verdict"]["csts"]
        and e["provider_error"] is None
    ]
    h5 = Counter()
    closure_sizes: Counter[int] = Counter()
    for e in c2_failures:
        r = e["retrieval"]
        closure = set(r["causal_closure_rule_ids"])
        returned = set(r["returned_rule_ids"])
        inspected = set(r["inspected_rule_ids"])
        closure_sizes[len(closure)] += 1
        h5["any_returned"] += bool(closure & returned)
        h5["any_inspected"] += bool(closure & inspected)
        h5["all_returned"] += bool(closure) and closure <= returned
        h5["all_inspected"] += bool(closure) and closure <= inspected
        h5["empty_closure"] += not closure
        h5["closure_not_covered_by_returned"] += bool(closure - returned)
        h5["closure_not_covered_by_inspected"] += bool(closure - inspected)

    silent_by_condition: dict[str, Counter[str]] = defaultdict(Counter)
    silent_examples: list[dict[str, object]] = []
    for e in episodes:
        if not e["silent_violation"]:
            continue
        verdict = e["verdict"]
        key = (
            "goal_and_hard_failed"
            if not verdict["goal_satisfied"] and not verdict["hard_constraints_satisfied"]
            else "goal_failed_hard_passed"
            if not verdict["goal_satisfied"]
            else "goal_passed_hard_failed"
        )
        silent_by_condition[e["condition"]][key] += 1
        summaries = [
            c["args"].get("summary", "") for c in e["tool_calls"] if c["tool"] == "finish_task"
        ]
        if not verdict["goal_satisfied"] and summaries:
            silent_examples.append(
                {
                    "episode_id": e["episode_id"],
                    "condition": e["condition"],
                    "summary": summaries[0],
                }
            )

    nonrule_ops = {
        "change_numeric_threshold",
        "change_application_risk",
        "change_required_clearance",
        "add_conflict_pair",
        "remove_conflict_pair",
        "change_role_entitlement",
    }
    nonrule_cases = [c for c in split["cases"] if c["shift_params"]["kind"] in nonrule_ops]

    shift_counts = Counter(e["case_id"] in shifted_ids for e in episodes)
    condition_counts = Counter(e["condition"] for e in episodes)
    family_counts = Counter(e["family"] for e in episodes)
    result = {
        "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "split_sha256": hashlib.sha256(split_bytes).hexdigest(),
        "archive_episode_count": len(episodes),
        "matrix": {
            "expected_cells": len(expected),
            "observed_unique_cells": len(observed),
            "missing_cells": sorted(expected - observed),
            "unexpected_cells": sorted(observed - expected),
            "duplicate_cells": duplicate_ids,
            "condition_counts": dict(sorted(condition_counts.items())),
            "baseline_episode_count": shift_counts[False],
            "shifted_episode_count": shift_counts[True],
            "parents": len({e["parent_task_id"] for e in episodes}),
            "families": dict(sorted(family_counts.items())),
        },
        "primary_recomputed": {
            "per_parent_did": dids,
            "point": mean(list(dids.values())),
            "bootstrap_seed": 20260825,
            "resamples": 10000,
            "percentile_95_ci": list(ci),
        },
        "h5_failure_retrieval_diagnostic": {
            "c2_failures": len(c2_failures),
            "closure_size_distribution": {str(k): closure_sizes[k] for k in sorted(closure_sizes)},
            **dict(h5),
        },
        "silent_violation_semantics": {
            "definition_in_archive": "finish_task_called AND CSTS_false",
            "by_condition": {k: dict(v) for k, v in sorted(silent_by_condition.items())},
            "goal_failure_examples": silent_examples,
        },
        "discovery_manipulation_coverage": {
            "basis": "DiscoveryTools receives only rules. The listed shift operators leave the rules tuple unchanged.",
            "nonrule_shift_cases": [
                {
                    "case_id": c["task_id"],
                    "parent_task_id": c["parent_task_id"],
                    "plan_effect": c["plan_effect"],
                    "operator": c["shift_params"]["kind"],
                }
                for c in nonrule_cases
            ],
            "nonrule_shift_case_count": len(nonrule_cases),
            "nonrule_invalidating_count": sum(
                c["plan_effect"] == "plan_invalidating" for c in nonrule_cases
            ),
            "nonrule_preserving_count": sum(
                c["plan_effect"] == "plan_preserving" for c in nonrule_cases
            ),
        },
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    expected_ci = [-0.016666666666666677, 0.20833333333333334]
    if not (
        result["archive_sha256"]
        == "dac63b8996899726315f1f04cc5967b08b3358382a7c6b6f38261a963f1b5f4a"
        and result["archive_episode_count"] == 450
        and result["matrix"]["expected_cells"] == result["matrix"]["observed_unique_cells"] == 450
        and not result["matrix"]["missing_cells"]
        and not result["matrix"]["unexpected_cells"]
        and result["matrix"]["duplicate_cells"] == 0
        and abs(result["primary_recomputed"]["point"] - 0.09166666666666666) < 1e-12
        and result["primary_recomputed"]["percentile_95_ci"] == expected_ci
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
