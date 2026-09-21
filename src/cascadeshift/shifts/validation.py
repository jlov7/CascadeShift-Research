"""World validation and baseline-plan replay classification."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cascadeshift.domain.actions import (
    Action,
    GrantApplicationAccess,
    RevokeApplicationAccess,
)
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.transition import _hard_invariants, apply_action
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec
from cascadeshift.tasks.oracle import Plan, solve

PROBE_ACTIONS_BOUND = 64
FORBIDDEN_RULE_PROSE = frozenset(
    {
        "frozen",
        "stale",
        "live",
        "fresh",
        "shift",
        "baseline",
        "confirmatory",
        "condition",
        "c0",
        "c1",
        "c2",
        "oracle",
        "verifier",
        "cascade_depth",
        "plan_preserving",
        "plan_invalidating",
    }
)
_PROSE_TOKEN = re.compile(r"[a-z0-9_]+")


def _rule_prose_errors(rule_id: str, title: str, description: str) -> list[str]:
    """Reject model-facing labels that disclose outcomes or study conditions."""
    tokens = _PROSE_TOKEN.findall(f"{title} {description}".lower())
    errors = [
        f"{rule_id}: forbidden prose token {token!r}"
        for token in tokens
        if token in FORBIDDEN_RULE_PROSE
    ]
    errors.extend(
        f"{rule_id}: answer-encoding snake_case prose {token!r}"
        for token in tokens
        if "_" in token and token.replace("_", "").isalnum()
    )
    return errors


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    errors: tuple[str, ...] = ()


def validate_world(
    world: WorldSpec,
    expected_rule_count: int | None = None,
) -> ValidationReport:
    errors: list[str] = []
    if expected_rule_count is not None and len(world.rules) != expected_rule_count:
        errors.append(f"catalog cardinality {len(world.rules)} != {expected_rule_count}")
    apps = set(world.app_map())
    roles = set(world.role_map())
    for r in world.rules:
        errors.extend(_rule_prose_errors(r.rule_id, r.title, r.description))
        blob = r.model_dump(mode="json")
        for e in blob.get("effects", []):
            if isinstance(e, dict):
                aid = e.get("application_id")
                if isinstance(aid, str) and "APP-" in aid and aid not in apps:
                    errors.append(f"{r.rule_id}: unknown application {aid}")
        for c in blob.get("conditions", []):
            if isinstance(c, dict):
                aid = c.get("application_id")
                if isinstance(aid, str) and "APP-" in aid and aid not in apps:
                    errors.append(f"{r.rule_id}: unknown application {aid}")
    for cp in world.conflict_pairs:
        for a in cp.pair:
            if a not in apps:
                errors.append(f"conflict pair references unknown application {a}")
    for role in world.roles:
        for m in role.mandatory_applications:
            if m not in apps:
                errors.append(f"role {role.role_id} mandatory app {m} unknown")
    for emp in world.employees:
        if emp.role_id not in roles:
            errors.append(f"employee {emp.employee_id} references unknown role {emp.role_id}")

    # Reset-state hard invariants.
    state = world.initial_state()
    inv = _hard_invariants(state, world)
    if inv is not None:
        errors.append(f"reset invariant: {inv}")
    else:
        # Probe: engine must terminate cleanly on a standard grant/revoke cycle.

        probe_count = 0
        cur = state
        for emp in world.employees:
            for app_id in sorted(apps)[:4]:
                if probe_count >= PROBE_ACTIONS_BOUND:
                    break
                res1 = apply_action(
                    world,
                    cur,
                    GrantApplicationAccess(employee_id=emp.employee_id, application_id=app_id),
                )
                res2 = apply_action(
                    world,
                    res1.state,
                    RevokeApplicationAccess(employee_id=emp.employee_id, application_id=app_id),
                )
                if res2.status == "invariant_failed" or res1.status == "invariant_failed":
                    errors.append("probe cascade exceeded bound")
                    break
                cur = res2.state
                probe_count += 1

    return ValidationReport(ok=not errors, errors=tuple(errors))


class PlanEffectClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    effect: Literal["plan_preserving", "plan_invalidating", "inadmissible"]
    baseline_plan_csts: bool
    alternative_status: str | None = None


def classify_plan_effect(
    baseline_world: WorldSpec,
    shifted_world: WorldSpec,
    task: TaskSpec,
    baseline_plan: Plan,
    alternative_status: str | None = None,
) -> PlanEffectClassification:
    """Replay the unchanged baseline plan against the shifted world.

    plan_preserving   p0 satisfies goal AND every hard constraint on W_shift
    plan_invalidating p0 fails while an alternative oracle-valid plan exists
    inadmissible      p0 fails and no alternative oracle-valid plan exists
    """
    state: WorldState = shifted_world.initial_state()
    ok = True
    for action in baseline_plan:
        res = apply_action(shifted_world, state, action)
        if res.status != "ok":
            ok = False
            break
        state = res.state
    if ok:
        from cascadeshift.tasks.models import evaluate_task

        verdict = evaluate_task(shifted_world, state, task)
        ok = verdict.csts
    if ok:
        return PlanEffectClassification(effect="plan_preserving", baseline_plan_csts=True)
    if alternative_status is None:
        alternative_status = solve(shifted_world, task).status
    if alternative_status == "solved":
        return PlanEffectClassification(
            effect="plan_invalidating", baseline_plan_csts=False, alternative_status="solved"
        )
    return PlanEffectClassification(
        effect="inadmissible", baseline_plan_csts=False, alternative_status=alternative_status
    )


def unused_action_guard(actions: tuple[Action, ...]) -> bool:  # pragma: no cover
    return all(a.action_name() != "" for a in actions)
