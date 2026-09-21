"""Verify the historical v1 scientific artifact subset retained by this prototype."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/results/confirmatory/episodes.json"
RETAINED_SOURCE = (
    "src/cascadeshift/agents/conditions.py",
    "src/cascadeshift/domain/actions.py",
    "src/cascadeshift/domain/constraints.py",
    "src/cascadeshift/domain/entities.py",
    "src/cascadeshift/domain/rules.py",
    "src/cascadeshift/domain/state.py",
    "src/cascadeshift/engine/transition.py",
    "src/cascadeshift/retrieval/index.py",
    "src/cascadeshift/retrieval/relevance.py",
    "src/cascadeshift/retrieval/tools.py",
    "src/cascadeshift/shifts/operators.py",
    "src/cascadeshift/tasks/models.py",
)
RETAINED_INPUTS = {
    "protocol/preregistration.md": "b2ed8bec3ced445e8560a14f5ca98d5ef5d510185a021a57ede6bc5bd9aebcae",
    "tasks/confirmatory/anchors.json": "fb483d412f3baa64a9c2d1bf1d8f3790df13a2cc1d77b9b38561c7794153b2f3",
    "tasks/confirmatory/split.json": "a8d25ac8b3620559e3abda2e11b17749eebf0cd812c3d5f37a027a7d05d866f6",
    "worlds/baseline/world.yaml": "158823c85909a6ed36b0a028c11f1c2f96263557f29d8e7a966156d716a2d6a7",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest_path = ROOT / "protocol/freeze_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes)
    archive_hash = sha256(ARCHIVE)
    source = {name: sha256(ROOT / name) for name in RETAINED_SOURCE}
    mismatches = [name for name, digest in source.items() if manifest["files"].get(name) != digest]
    inputs = {name: sha256(ROOT / name) for name in RETAINED_INPUTS}
    input_mismatches = [name for name, digest in inputs.items() if RETAINED_INPUTS[name] != digest]
    assembly_exceptions = {
        "src/cascadeshift/engine/world.py": "0c11765cceca326e99964d217b180793109b81bfeccb59a280e65763a0320c3c",
        "src/cascadeshift/engine/world_io.py": "9e0644b7b11337d20a3b3db1bd74ce3e1d1f2419fd8d634aa109dca808c8c938",
        "src/cascadeshift/tasks/oracle.py": "10b2e84d18714de4d471c7482a6081e15984b6bdbcb6d9a5c6568ed8ece82268",
    }
    actual_exceptions = {name: sha256(ROOT / name) for name in assembly_exceptions}
    exception_mismatches = [
        name for name, digest in actual_exceptions.items() if assembly_exceptions[name] != digest
    ]
    result = {
        "archive_sha256": archive_hash,
        "historical_manifest_sha256": manifest_hash,
        "retained_source_hashes": source,
        "mismatches_against_historical_v1_manifest": mismatches,
        "retained_input_hashes": inputs,
        "input_mismatches": input_mismatches,
        "source_assembly_exceptions": {
            "paths": actual_exceptions,
            "mismatches_against_expected_source_assembly": exception_mismatches,
            "scope": "world.py, world_io.py, and oracle.py are source-assembly bytes, not freeze-verified. Replay independently validates all archived world hashes, transitions, and verdicts.",
        },
        "generated_world_scope": "Replay verifies each generated world against archived canonical world hashes.",
        "scope": "Historical v1 archive and selected scientific source only; not the modified prototype.",
    }
    out = ROOT / "artifacts/verification/artifact-integrity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if (
        manifest_hash != "3d8d55b366c210be6eada170046731d31daddd8e4b53638376390e3eeb0de3e0"
        or archive_hash != "dac63b8996899726315f1f04cc5967b08b3358382a7c6b6f38261a963f1b5f4a"
        or mismatches
        or input_mismatches
        or exception_mismatches
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
