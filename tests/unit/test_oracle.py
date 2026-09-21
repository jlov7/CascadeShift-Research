"""Bounded deterministic oracle planner (ledger O-01..O-04)."""

import pytest

from cascadeshift.tasks.models import TaskSpec
from cascadeshift.tasks.oracle import OracleResult, solve, verify_plan
from tests.unit.test_engine import build_cascade_world


def _grant_task(task_id="T-DEV-0001", app="APP-CRM", keep=("APP-PAY",)):
    return TaskSpec(
        task_id=task_id,
        parent_task_id=None,
        family="F1_grant_preserve",
        title="Grant CRM access",
        description="Grant CRM while keeping Payroll.",
        visible_goal=[
            {"kind": "goal_entitlement_present", "employee_id": "E-001", "application_id": app},
        ],
        hard_constraints=(
            {
                "kind": "retains_all_mandatory",
                "employee_id": "E-001",
                "mandatory_applications": list(keep),
            },
        ),
    )


def test_oracle_solves_simple_grant():
    w = build_cascade_world()
    t = _grant_task()
    res = solve(w, t)
    assert isinstance(res, OracleResult)
    assert res.status == "solved"
    assert len(res.plan) >= 1
    assert verify_plan(w, t, res.plan).csts is True


def test_oracle_is_deterministic_bytes():
    w = build_cascade_world()
    t = _grant_task()
    a = solve(w, t)
    b = solve(w, t)
    assert [x.model_dump_json() for x in a.plan] == [x.model_dump_json() for x in b.plan]


def test_oracle_rejects_impossible_within_bound():
    w = build_cascade_world()
    # Goal requires granting APP-VIP; conflict pair PAY+VIP means PAY must be
    # revoked, but the hard constraint forbids losing PAY -> unsolvable.
    t = TaskSpec(
        task_id="T-IMP-0001",
        parent_task_id=None,
        family="F1_grant_preserve",
        title="impossible",
        description="conflict with retention",
        visible_goal=[
            {
                "kind": "goal_entitlement_present",
                "employee_id": "E-001",
                "application_id": "APP-VIP",
            }
        ],
        hard_constraints=(
            {
                "kind": "retains_all_mandatory",
                "employee_id": "E-001",
                "mandatory_applications": ["APP-PAY"],
            },
        ),
    )
    res = solve(w, t)
    # Either proof of unsolvability or bound exhaustion rejects the pair.
    assert res.status in {"unsolvable", "budget_exhausted"}
    assert res.plan == ()


def test_verify_plan_preserves_result_when_shift_does_not_touch_plan():
    w = build_cascade_world()
    t = _grant_task()
    base_plan = solve(w, t).plan
    assert base_plan
    # This policy edit does not affect a CRM grant in the fixture.
    from cascadeshift.domain.entities import Policy

    w2 = w.model_copy(
        update={
            "policy": Policy(
                risk_threshold=30, clearance_floor=2, approval_mode=w.policy.approval_mode
            )
        }
    )
    v = verify_plan(w2, t, base_plan)
    assert v.csts is True


def test_oracle_respects_node_budget_and_reports():
    w = build_cascade_world()
    t = _grant_task()
    res = solve(w, t, node_budget=1)
    assert res.status in {"budget_exhausted", "unsolvable"}
    assert res.expanded_nodes <= 1


def test_oracle_zero_budget_does_not_expand_a_successor():
    res = solve(build_cascade_world(), _grant_task(), node_budget=0)
    assert res.status == "budget_exhausted"
    assert res.expanded_nodes == 0


def test_oracle_rejects_negative_node_budget():
    with pytest.raises(ValueError, match="non-negative"):
        solve(build_cascade_world(), _grant_task(), node_budget=-1)
