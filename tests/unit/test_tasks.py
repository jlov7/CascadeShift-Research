"""TaskSpec model and deterministic terminal verifier (ledger T-01, T-02)."""

import pytest
from pydantic import ValidationError

from cascadeshift.domain.constraints import (
    ClearanceAtLeast,
    EntitlementAbsent,
    GoalEntitlementPresent,
    RetainsAllMandatory,
)
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskFamily, TaskSpec, evaluate_task
from tests.unit.test_engine import build_cascade_world


def _task(**kw):
    base = dict(
        task_id="T-DEV-0001",
        parent_task_id=None,
        family="F1_grant_preserve",
        title="Grant CRM access",
        description=("Grant Ada Onboarding access to CRM Lite while she keeps Payroll Hub."),
        visible_goal=[
            {
                "kind": "goal_entitlement_present",
                "employee_id": "E-001",
                "application_id": "APP-CRM",
            },
        ],
        hard_constraints=[
            {
                "kind": "retains_all_mandatory",
                "employee_id": "E-001",
                "mandatory_applications": ["APP-PAY"],
            },
        ],
    )
    base.update(kw)
    return TaskSpec(**base)


def test_task_spec_validates_and_family_enum_has_six_members():
    import typing

    t = _task()
    assert t.family == "F1_grant_preserve"
    assert len(typing.get_args(TaskFamily)) == 6
    with pytest.raises(ValidationError):
        _task(family="F7_browse_memes")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _task(budget_overrides={})  # type: ignore[call-arg]


def test_shifted_case_requires_parent():
    from cascadeshift.tasks.models import ShiftedCase

    with pytest.raises(ValidationError):
        ShiftedCase(
            task_id="S-1",
            parent_task_id=None,
            family="F1_grant_preserve",
            title="t",
            description="d",
            visible_goal=[],
            hard_constraints=[],
            shift_id="SH-1",
        )
    sc = ShiftedCase(
        task_id="S-1",
        parent_task_id="T-C-0007",
        family="F1_grant_preserve",
        title="t",
        description="d",
        visible_goal=[],
        hard_constraints=[],
        shift_id="SH-1",
    )
    assert sc.parent_task_id == "T-C-0007"


def test_verifier_separates_goal_from_hard_constraints():
    w = build_cascade_world()
    t = _task(
        visible_goal=[
            {
                "kind": "goal_entitlement_present",
                "employee_id": "E-001",
                "application_id": "APP-VIP",
            },
        ],
    )
    # State where goal holds but hard constraint (keep PAY) is violated:
    # granting VIP crosses the risk threshold and cascades a payroll revoke.
    res = __import__("cascadeshift.engine.transition", fromlist=["apply_action"]).apply_action(
        w,
        w.initial_state(),
        __import__(
            "cascadeshift.domain.actions", fromlist=["GrantApplicationAccess"]
        ).GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP"),
    )
    v = evaluate_task(w, res.state, t)
    assert v.goal_satisfied is True
    assert v.hard_constraints_satisfied is False
    assert v.csts is False
    assert len(v.violated_codes) == 1


def test_verifier_full_success_on_safe_state():
    from cascadeshift.domain.state import WorldState

    w = build_cascade_world()
    t = _task(hard_constraints=[])
    st = WorldState.model_validate_json(
        w.initial_state()
        .model_copy(
            update={
                "employees": (
                    w.initial_state().employee("E-001").with_entitlement("APP-CRM"),
                    w.initial_state().employee("E-002"),
                )
            }
        )
        .model_dump_json()
    )
    v = evaluate_task(w, st, t)
    assert v.csts is True and v.violated_codes == ()


def test_constraint_kinds_cover_verifier_needs():
    for kind in [
        ClearanceAtLeast(employee_id="E", level=1),
        EntitlementAbsent(employee_id="E", application_id="A"),
        GoalEntitlementPresent(employee_id="E", application_id="A"),
        RetainsAllMandatory(employee_id="E", mandatory_applications=("A",)),
    ]:
        assert isinstance(kind.stable_code(), str)


def test_world_fixture_type_available():
    assert isinstance(build_cascade_world(), WorldSpec)
