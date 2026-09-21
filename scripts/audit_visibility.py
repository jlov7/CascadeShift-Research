#!/usr/bin/env python3
"""Check whether the C1 and C2 discovery backends differ for every shifted case.

This audit uses no model client. It compares the byte strings returned by the
frozen discovery implementation for all rule inspections, all schema classes,
and every archived discovery request made for the case.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from cascadeshift.engine.world_io import load_world
from cascadeshift.retrieval.tools import DiscoveryTools

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/results/confirmatory/episodes.json"
SPLIT = ROOT / "tasks/confirmatory/split.json"
BASELINE = ROOT / "worlds/baseline/world.yaml"
OUT = ROOT / "artifacts/verification/audit-visibility.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    baseline = load_world(BASELINE)
    c1 = DiscoveryTools(baseline.rules)
    split_bytes = SPLIT.read_bytes()
    archive_bytes = ARCHIVE.read_bytes()
    split = json.loads(split_bytes)
    episodes = json.loads(archive_bytes)
    manifest = json.loads((ROOT / "protocol/freeze_manifest.json").read_bytes())
    source_paths = (
        "src/cascadeshift/agents/conditions.py",
        "src/cascadeshift/retrieval/tools.py",
        "src/cascadeshift/retrieval/index.py",
        "src/cascadeshift/shifts/operators.py",
    )
    source_hashes = {p: sha256(ROOT / p) for p in source_paths}
    source_hash_match = {p: source_hashes[p] == manifest["files"].get(p) for p in source_paths}
    if not all(source_hash_match.values()):
        raise RuntimeError("discovery implementation bytes do not match freeze manifest")
    requests: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for e in episodes:
        if e["case_id"].startswith("S-"):
            for call in e["tool_calls"]:
                if call["kind"] == "discovery":
                    requests[e["case_id"]].add(
                        (
                            call["tool"],
                            json.dumps(call["args"], sort_keys=True, separators=(",", ":")),
                        )
                    )
    structural_requests = [
        *(("inspect_rule", {"rule_id": r.rule_id}) for r in baseline.rules),
        *(
            ("inspect_schema", {"entity_type": x})
            for x in ("application", "role", "employee", "policy")
        ),
    ]
    rows: list[dict[str, Any]] = []
    for case in split["cases"]:
        case_id = case["task_id"]
        world = load_world(ROOT / f"worlds/generated/20260822-{int(case_id[-4:]):04d}.yaml")
        c2 = DiscoveryTools(world.rules)
        checked: list[tuple[str, dict[str, object]]] = list(structural_requests)
        checked.extend((name, json.loads(args)) for name, args in sorted(requests[case_id]))
        differences = []
        for name, args in checked:
            before, after = c1.call(name, args), c2.call(name, args)
            if before != after:
                differences.append({"tool": name, "args": args})
        rows.append(
            {
                "case_id": case_id,
                "plan_effect": case["plan_effect"],
                "operator": case["shift_params"]["kind"],
                "rules_tuple_sha256_baseline": hashlib.sha256(
                    "\n".join(r.model_dump_json() for r in baseline.rules).encode()
                ).hexdigest(),
                "rules_tuple_sha256_shifted": hashlib.sha256(
                    "\n".join(r.model_dump_json() for r in world.rules).encode()
                ).hexdigest(),
                "rules_equal": baseline.rules == world.rules,
                "requests_checked": len(checked),
                "response_differences": len(differences),
                "difference_examples": differences[:5],
            }
        )
    invisible = [r for r in rows if r["response_differences"] == 0]
    case_by_id = {r["case_id"]: r for r in rows}
    outcome_by_group: dict[str, dict[str, int]] = {
        "identical_backend": {"c1_success": 0, "c2_success": 0, "n_per_condition": 0},
        "changed_backend": {"c1_success": 0, "c2_success": 0, "n_per_condition": 0},
    }
    for e in episodes:
        if e["case_id"] not in case_by_id or e["condition"] not in {
            "frozen_discovery",
            "live_discovery",
        }:
            continue
        group = (
            "identical_backend"
            if case_by_id[e["case_id"]]["response_differences"] == 0
            else "changed_backend"
        )
        if e["condition"] == "frozen_discovery":
            outcome_by_group[group]["n_per_condition"] += 1
            outcome_by_group[group]["c1_success"] += int(e["verdict"]["csts"])
        else:
            outcome_by_group[group]["c2_success"] += int(e["verdict"]["csts"])
    baseline = [e for e in episodes if e["case_id"].startswith("T-C-")]
    baseline_counts = {
        "c1_success": sum(
            e["condition"] == "frozen_discovery" and e["verdict"]["csts"] for e in baseline
        ),
        "c2_success": sum(
            e["condition"] == "live_discovery" and e["verdict"]["csts"] for e in baseline
        ),
        "n_per_condition": sum(e["condition"] == "frozen_discovery" for e in baseline),
    }
    result = {
        "freeze_hash_matched_source_files": source_hashes,
        "freeze_hash_match": source_hash_match,
        "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "split_sha256": hashlib.sha256(split_bytes).hexdigest(),
        "cases": rows,
        "no_observable_discovery_difference": len(invisible),
        "no_observable_discovery_difference_invalidating": sum(
            r["plan_effect"] == "plan_invalidating" for r in invisible
        ),
        "no_observable_discovery_difference_preserving": sum(
            r["plan_effect"] == "plan_preserving" for r in invisible
        ),
        "invisible_case_ids": [r["case_id"] for r in invisible],
        "post_hoc_descriptive_c1_c2_outcomes_by_discovery_visibility": outcome_by_group,
        "baseline_raw_c1_c2_outcomes": baseline_counts,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not (
        result["archive_sha256"]
        == "dac63b8996899726315f1f04cc5967b08b3358382a7c6b6f38261a963f1b5f4a"
        and result["no_observable_discovery_difference"] == 14
        and result["no_observable_discovery_difference_invalidating"] == 9
        and len(result["cases"]) == 30
        and all(result["freeze_hash_match"].values())
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
