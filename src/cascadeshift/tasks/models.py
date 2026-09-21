"""Task model: anchors, shifted cases, families, verifier entry point."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from cascadeshift.domain.constraints import TerminalConstraint
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.world import WorldSpec

TaskFamily = Literal[
    "F1_grant_preserve",
    "F2_role_change_retention",
    "F3_conflict_before_high_risk",
    "F4_escalation_free_onboarding",
    "F5_offboard_shared_service",
    "F6_negative_control",
]


class _TaskBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    family: TaskFamily
    title: str
    description: str
    visible_goal: tuple[TerminalConstraint, ...] = ()
    hard_constraints: tuple[TerminalConstraint, ...] = ()


class TaskSpec(_TaskBase):
    task_id: str
    parent_task_id: None = None


class ShiftedCase(_TaskBase):
    task_id: str
    parent_task_id: str
    shift_id: str
    shift_class: str | None = None
    plan_effect: Literal["plan_preserving", "plan_invalidating"] | None = None
    baseline_world_hash: str | None = None
    baseline_plan_hash: str | None = None
    shifted_world_hash: str | None = None
    alternative_plan_hash: str | None = None
    shift_params: dict[str, object] | None = None

    @model_validator(mode="after")
    def _parent_required(self) -> ShiftedCase:
        if not self.parent_task_id:
            raise ValueError("shifted case must reference a parent_task_id")
        return self


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_satisfied: bool
    hard_constraints_satisfied: bool
    violated_codes: tuple[str, ...]
    csts: bool


_CONSTRAINT_ADAPTER: TypeAdapter[list[TerminalConstraint]] = TypeAdapter(list[TerminalConstraint])


def _eval_constraints(
    constraints: tuple[TerminalConstraint, ...],
    world: WorldSpec,
    state: WorldState,
) -> tuple[bool, list[str]]:
    violated: list[str] = []
    apps = {a.application_id: a for a in world.applications}
    for c in constraints:
        ok = c.evaluate(state, apps, world.conflict_set())
        if not ok:
            violated.append(c.stable_code())
    return (len(violated) == 0), violated


def evaluate_task(world: WorldSpec, state: WorldState, task: TaskSpec) -> Verdict:
    apps = {a.application_id: a for a in world.applications}
    goal_ok, goal_violated = _eval_constraints(task.visible_goal, world, state)
    del apps
    hard_ok, hard_violated = _eval_constraints(task.hard_constraints, world, state)
    return Verdict(
        goal_satisfied=goal_ok,
        hard_constraints_satisfied=hard_ok,
        violated_codes=tuple(goal_violated + hard_violated),
        csts=goal_ok and hard_ok,
    )


def parse_constraints(
    payloads: list[dict[str, object]],
) -> tuple[TerminalConstraint, ...]:
    return tuple(_CONSTRAINT_ADAPTER.validate_python(list(payloads)))
