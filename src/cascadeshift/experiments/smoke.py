"""Smoke evaluation: six prepared scenarios, one rollout each (X-01)."""

from __future__ import annotations

from cascadeshift.agents.protocol import EpisodeRecord
from cascadeshift.agents.runner import EpisodeRunner
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec

FAMILY_SCENARIO: tuple[str, ...] = (
    "F1_grant_preserve",
    "F2_role_change_retention",
    "F3_conflict_before_high_risk",
    "F4_escalation_free_onboarding",
    "F5_offboard_shared_service",
    "F6_negative_control",
)


def six_scenarios() -> list[TaskSpec]:
    from cascadeshift.tasks.corpus import generate_confirmatory_anchors

    anchors = list(generate_confirmatory_anchors())
    out: list[TaskSpec] = []
    for fam in FAMILY_SCENARIO:
        match = next(a for a in anchors if a.family == fam)
        out.append(match)
    return out


def run_smoke_scripted(baseline_world: WorldSpec) -> list[EpisodeRecord]:
    runner = EpisodeRunner(baseline_world)
    records: list[EpisodeRecord] = []
    for task in six_scenarios():
        rec = runner.run_scripted(
            split="smoke",
            case_id=task.task_id,
            parent_task_id=task.task_id,
            task=task,
            world=baseline_world,
            condition="live_discovery",
            repeat=1,
        )
        records.append(rec)
    return records
