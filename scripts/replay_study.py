#!/usr/bin/env python3
"""Replay archived business traces through the frozen-hash transition/scoring code.

Run only with PYTHONPATH=src and the local virtual environment.  This script
does not create model clients or call model inference.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from cascadeshift.domain.actions import parse_action
from cascadeshift.engine.transition import apply_action
from cascadeshift.engine.world_io import load_world
from cascadeshift.tasks.models import ShiftedCase, TaskSpec, evaluate_task

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/results/confirmatory/episodes.json"
ANCHORS = ROOT / "tasks/confirmatory/anchors.json"
SPLIT = ROOT / "tasks/confirmatory/split.json"
MANIFEST = ROOT / "protocol/freeze_manifest.json"
BASELINE = ROOT / "worlds/baseline/world.yaml"
OUT = ROOT / "artifacts/verification/replay-study.json"


def load_tasks(anchors_bytes: bytes, split: dict[str, object]) -> dict[str, TaskSpec | ShiftedCase]:
    anchors = json.loads(anchors_bytes)["anchors"]
    cases = split["cases"]
    return {
        **{item["task_id"]: TaskSpec.model_validate(item) for item in anchors},
        **{item["task_id"]: ShiftedCase.model_validate(item) for item in cases},
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    archive_bytes = ARCHIVE.read_bytes()
    split_bytes = SPLIT.read_bytes()
    anchors_bytes = ANCHORS.read_bytes()
    manifest = json.loads(MANIFEST.read_bytes())
    split = json.loads(split_bytes)
    frozen_modules = (
        "src/cascadeshift/engine/transition.py",
        "src/cascadeshift/tasks/models.py",
    )
    module_hashes = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in frozen_modules
    }
    module_hash_match = {
        path: module_hashes[path] == manifest["files"].get(path) for path in frozen_modules
    }
    if not all(module_hash_match.values()):
        raise RuntimeError("replay module bytes do not match freeze manifest")
    tasks = load_tasks(anchors_bytes, split)
    baseline = load_world(BASELINE)
    worlds = {f"T-C-{i:04d}": baseline for i in range(1, 21)}
    worlds.update(
        {
            f"S-{i:04d}": load_world(ROOT / f"worlds/generated/20260822-{i:04d}.yaml")
            for i in range(1, 31)
        }
    )
    episodes = json.loads(archive_bytes)
    mismatches: list[dict[str, object]] = []
    action_statuses: Counter[str] = Counter()
    for episode in episodes:
        world = worlds[episode["case_id"]]
        task = tasks[episode["case_id"]]
        if world.content_hash() != episode["world_hash"]:
            mismatches.append({"episode_id": episode["episode_id"], "problem": "world_hash"})
            continue
        state = world.initial_state()
        for call in episode["tool_calls"]:
            if call["kind"] != "business":
                continue
            try:
                action = parse_action({"kind": call["tool"], **call["args"]})
            except Exception:
                action_statuses["invalid_action"] += 1
                continue
            result = apply_action(world, state, action)
            action_statuses[result.status] += 1
            if result.status == "ok":
                state = result.state
        verdict = evaluate_task(world, state, task)  # type: ignore[arg-type]
        archived = episode["verdict"]
        replayed = verdict.model_dump(mode="json")
        if replayed != archived:
            mismatches.append(
                {
                    "episode_id": episode["episode_id"],
                    "problem": "verdict",
                    "archived": archived,
                    "replayed": replayed,
                }
            )
    result = {
        "episodes_replayed": len(episodes),
        "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "split_sha256": hashlib.sha256(split_bytes).hexdigest(),
        "mismatches": mismatches,
        "mismatch_count": len(mismatches),
        "business_action_statuses": dict(sorted(action_statuses.items())),
        "frozen_hash_matched_modules": module_hashes,
        "frozen_hash_match": module_hash_match,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if (
        mismatches
        or result["archive_sha256"]
        != "dac63b8996899726315f1f04cc5967b08b3358382a7c6b6f38261a963f1b5f4a"
        or result["episodes_replayed"] != 450
        or sum(action_statuses.values()) != 587
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
