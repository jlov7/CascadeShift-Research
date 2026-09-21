"""Confirmatory split generation: thin, gated wrapper over build_paired_cases."""

from __future__ import annotations

from cascadeshift.engine.world import WorldSpec
from cascadeshift.shifts.validation import validate_world
from cascadeshift.tasks.corpus import build_paired_cases
from cascadeshift.tasks.models import ShiftedCase, TaskSpec


def generate_confirmatory_split(
    baseline_world: WorldSpec,
    anchors: list[TaskSpec],
    *,
    seed: int,
    n_preserving: int = 15,
    n_invalidating: int = 15,
) -> tuple[list[ShiftedCase], list[WorldSpec], dict[str, TaskSpec]]:
    if len(anchors) != 20:
        raise RuntimeError(f"confirmatory requires 20 anchors, got {len(anchors)}")
    for a in anchors:
        del a
        report = validate_world(baseline_world, expected_rule_count=128)
        if not report.ok:
            raise RuntimeError(f"baseline world invalid: {report.errors}")
        del report
        break
    return build_paired_cases(
        baseline_world,
        anchors,
        n_preserving=n_preserving,
        n_invalidating=n_invalidating,
        max_per_parent=2,
        seed=seed,
        require_all_parents=True,
    )
