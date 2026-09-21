"""Typed domain state requirements (ledger D-01, D-02, D-03)."""

import pytest
from pydantic import ValidationError

from cascadeshift.domain.actions import (
    ApproveRequest,
    AssignRole,
    CompleteOnboarding,
    FinishTask,
    GrantApplicationAccess,
    OffboardEmployee,
    RevokeApplicationAccess,
    parse_action,
)
from cascadeshift.domain.constraints import (
    ClearanceAtLeast,
    EntitlementAbsent,
    GoalEntitlementPresent,
    NoConflictingPair,
    RetainsAllMandatory,
    RiskLoadBelow,
    RoleIs,
    StatusIs,
)
from cascadeshift.domain.entities import (
    Application,
    ConflictPair,
    Employee,
    Policy,
    Role,
)


def test_employee_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Employee(
            employee_id="E-001",
            name="x",
            role_id="RL-01",
            status="active",
            is_contractor=False,
            clearance=3,
            risk_load=10,
            entitlements=["APP-01"],
            bogus="nope",  # type: ignore[call-arg]
        )


def test_employee_entitlements_normalized_sorted_unique():
    e = Employee(
        employee_id="E-002",
        name="y",
        role_id="RL-01",
        status="onboarding",
        is_contractor=True,
        clearance=2,
        risk_load=5,
        entitlements=["APP-03", "APP-01", "APP-01"],
    )
    assert e.entitlements == ("APP-01", "APP-03")


def test_application_and_role_and_policy_validate_ranges():
    app = Application(
        application_id="APP-01", name="Payroll", risk_score=20, requires_security_review=False
    )
    role = Role(
        role_id="RL-01", title="Engineer", mandatory_applications=("APP-01",), clearance_required=2
    )
    Policy(risk_threshold=80, clearance_floor=1, approval_mode="auto")
    assert app.risk_score == 20 and role.clearance_required == 2
    with pytest.raises(ValidationError):
        Application(
            application_id="APP-01", name="Payroll", risk_score=-1, requires_security_review=False
        )
    with pytest.raises(ValidationError):
        Policy(risk_threshold=999, clearance_floor=1, approval_mode="auto")
    with pytest.raises(ValidationError):
        Policy(risk_threshold=80, clearance_floor=1, approval_mode="yolo")


def test_conflict_pair_sorted_canonical():
    cp = ConflictPair(application_a="APP-09", application_b="APP-02")
    assert cp.pair == ("APP-02", "APP-09")


def test_action_union_is_closed_to_seven_members():
    actions = [
        GrantApplicationAccess(employee_id="E-001", application_id="APP-01"),
        RevokeApplicationAccess(employee_id="E-001", application_id="APP-01"),
        AssignRole(employee_id="E-001", role_id="RL-02"),
        CompleteOnboarding(employee_id="E-001"),
        OffboardEmployee(employee_id="E-001"),
        ApproveRequest(request_id="REQ-0001"),
        FinishTask(summary="done"),
    ]
    for a in actions:
        assert parse_action(a.model_dump()) == a
        assert a.action_name() == type(a).__name__
    with pytest.raises(ValidationError):
        parse_action({"kind": "DeployToProd"})


def test_terminal_constraint_predicates_evaluate_and_hash_stably():
    from cascadeshift.domain.state import WorldState

    emp = Employee(
        employee_id="E-001",
        name="n",
        role_id="RL-01",
        status="active",
        is_contractor=False,
        clearance=3,
        risk_load=10,
        entitlements=("APP-01", "APP-02"),
    )
    st = WorldState(employees=(emp,), requests=())
    world_apps = {"APP-01": None, "APP-02": None}
    conflicts = frozenset({("APP-01", "APP-02")})

    checks = [
        (GoalEntitlementPresent(employee_id="E-001", application_id="APP-01"), True),
        (GoalEntitlementPresent(employee_id="E-001", application_id="APP-99"), False),
        (EntitlementAbsent(employee_id="E-001", application_id="APP-99"), True),
        (ClearanceAtLeast(employee_id="E-001", level=3), True),
        (ClearanceAtLeast(employee_id="E-001", level=4), False),
        (RiskLoadBelow(employee_id="E-001", value=50), True),
        (RoleIs(employee_id="E-001", role_id="RL-01"), True),
        (StatusIs(employee_id="E-001", status="active"), True),
        (NoConflictingPair(employee_id="E-001"), False),
        (
            RetainsAllMandatory(employee_id="E-001", mandatory_applications=("APP-01", "APP-02")),
            True,
        ),
    ]
    for c, expected in checks:
        assert c.evaluate(st, world_apps, conflicts) is expected  # type: ignore[attr-defined]
        assert isinstance(c.stable_code(), str) and len(c.stable_code()) > 0
