"""Bounded deterministic oracle planner (uniform-cost BFS).

Protocol constants: unit action costs, lexicographic successor order by
(action name, canonical args), MAX_PLAN_DEPTH=8, default node budget 20000.
The oracle is total and deterministic; it never runs through agent tools.
"""

from __future__ import annotations

import hashlib
from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cascadeshift.domain.actions import (
    Action,
    ApproveRequest,
    AssignRole,
    CompleteOnboarding,
    GrantApplicationAccess,
    OffboardEmployee,
    RevokeApplicationAccess,
)
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.transition import TransitionResult, apply_action
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec, Verdict, evaluate_task

MAX_PLAN_DEPTH = 8
DEFAULT_NODE_BUDGET = 20000

Plan = tuple[Action, ...]


class OracleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["solved", "unsolvable", "budget_exhausted"]
    plan: Plan = ()
    expanded_nodes: int = 0


def _successors(world: WorldSpec, state: WorldState) -> list[Action]:
    """Enumerate candidate actions in deterministic order."""
    out: list[Action] = []
    app_ids = sorted(a.application_id for a in world.applications)
    role_ids = sorted(r.role_id for r in world.roles)
    for emp in state.employees:
        for a in app_ids:
            out.append(GrantApplicationAccess(employee_id=emp.employee_id, application_id=a))
            out.append(RevokeApplicationAccess(employee_id=emp.employee_id, application_id=a))
        for rid in role_ids:
            out.append(AssignRole(employee_id=emp.employee_id, role_id=rid))
        out.append(CompleteOnboarding(employee_id=emp.employee_id))
        out.append(OffboardEmployee(employee_id=emp.employee_id))
    for req in state.requests:
        if req.status == "pending":
            out.append(ApproveRequest(request_id=req.request_id))

    def key(a: Action) -> tuple[str, str]:
        return (a.action_name(), _canon_action(a))

    return sorted(out, key=key)


def _canon_action(a: Action) -> str:
    d = a.model_dump()
    return "|".join(f"{k}={d[k]}" for k in sorted(d))


def solve(world: WorldSpec, task: TaskSpec, node_budget: int = DEFAULT_NODE_BUDGET) -> OracleResult:
    if node_budget < 0:
        raise ValueError("node_budget must be non-negative")
    start = world.initial_state()
    v0 = evaluate_task(world, start, task)
    if v0.csts:
        return OracleResult(status="solved", plan=(), expanded_nodes=0)

    frontier: deque[tuple[WorldState, list[Action]]] = deque()
    frontier.append((start, []))
    seen: set[str] = {_state_hash(start)}
    expanded = 0

    while frontier:
        state, path = frontier.popleft()
        if len(path) >= MAX_PLAN_DEPTH:
            continue
        for action in _successors(world, state):
            res = apply_action(world, state, action)
            if res.status != "ok" or res.note in {
                "already_held",
                "not_held",
                "already_role",
                "already_approved",
            }:
                continue
            nxt = res.state
            h = _state_hash(nxt)
            if h in seen:
                continue
            if expanded >= node_budget:
                return OracleResult(status="budget_exhausted", expanded_nodes=expanded)
            seen.add(h)
            new_path = [*path, action]
            verdict = evaluate_task(world, nxt, task)
            expanded += 1
            if verdict.csts:
                return OracleResult(status="solved", plan=tuple(new_path), expanded_nodes=expanded)
            if len(new_path) < MAX_PLAN_DEPTH:
                frontier.append((nxt, new_path))
    return OracleResult(status="unsolvable", expanded_nodes=expanded)


def verify_plan(world: WorldSpec, task: TaskSpec, plan: Plan) -> Verdict:
    """Replay an action sequence through the full engine; evaluate terminal state."""
    state = world.initial_state()
    for action in plan:
        res: TransitionResult = apply_action(world, state, action)
        if res.status != "ok":
            return Verdict(
                goal_satisfied=False,
                hard_constraints_satisfied=False,
                violated_codes=(f"plan_rejected:{res.error}",),
                csts=False,
            )
        state = res.state
    return evaluate_task(world, state, task)


def plan_hash(plan: Plan) -> str:
    payload = ";".join(_canon_action(a) for a in plan)
    return hashlib.sha256(payload.encode()).hexdigest()


def _state_hash(state: WorldState) -> str:
    return state.model_dump_json()
