"""World validator + baseline-plan replay classification (ledger S-02, O-03)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cascadeshift.domain.actions import GrantApplicationAccess
from cascadeshift.engine.world import WorldSpec
from cascadeshift.engine.world_io import load_world
from cascadeshift.shifts.validation import (
    classify_plan_effect,
    validate_world,
)
from cascadeshift.tasks.models import TaskSpec
from tests.unit.test_engine import build_cascade_world


def _task(app="APP-CRM", keep=("APP-PAY",)):
    return TaskSpec(
        task_id="T-X",
        parent_task_id=None,
        family="F1_grant_preserve",
        title="t",
        description="d",
        visible_goal=[
            {"kind": "goal_entitlement_present", "employee_id": "E-001", "application_id": app}
        ],
        hard_constraints=(
            {
                "kind": "retains_all_mandatory",
                "employee_id": "E-001",
                "mandatory_applications": list(keep),
            },
        ),
    )


def test_validate_world_accepts_clean_fixture():
    report = validate_world(build_cascade_world())
    assert report.ok and report.errors == ()


def test_validate_world_rejects_dangling_reference():
    from cascadeshift.domain.entities import Application

    w = build_cascade_world()
    bad = w.model_copy(
        update={
            "applications": (
                Application(
                    application_id="APP-PAY",
                    name="x",
                    risk_score=10,
                    requires_security_review=False,
                ),
            )
        }
    )
    report = validate_world(bad)
    assert not report.ok
    assert any("APP-CRM" in e or "APP-VIP" in e for e in report.errors)


def test_validate_world_rejects_unknown_role_reference():
    w = build_cascade_world()
    from cascadeshift.domain.entities import Employee

    orphan = Employee(
        employee_id="E-002",
        name="Ben Contractor",
        role_id="RL-GHOST",
        status="active",
        is_contractor=True,
        clearance=2,
        risk_load=0,
        entitlements=(),
    )
    swapped = tuple(orphan if e.employee_id == "E-002" else e for e in w.employees)
    report = validate_world(w.model_copy(update={"employees": swapped}))
    assert not report.ok


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("applications", "duplicate application ids"),
        ("roles", "duplicate role ids"),
        ("employees", "duplicate employee ids"),
        ("conflict_pairs", "duplicate conflict pairs"),
    ],
)
def test_world_schema_rejects_duplicate_state_identities(field, message):
    world = build_cascade_world()
    payload = world.model_dump()
    payload[field] = [*payload[field], payload[field][0]]

    with pytest.raises(ValidationError, match=message):
        WorldSpec.model_validate(payload)


def test_frozen_worlds_remain_valid_under_identity_checks():
    paths = [
        Path("worlds/baseline/world.yaml"),
        *sorted(Path("worlds/generated").glob("20260822-*.yaml")),
    ]
    assert len(paths) == 31
    for path in paths:
        assert validate_world(load_world(path), expected_rule_count=128).ok, path


def test_validate_world_rejects_answer_encoding_and_forbidden_prose():
    w = build_cascade_world()
    poisoned = w.rules[0].model_copy(
        update={
            "title": "Live routing hint",
            "description": "revoke_payroll_after_clearance_drop",
        }
    )
    bad = w.model_copy(update={"rules": (poisoned, *w.rules[1:])})
    report = validate_world(bad)
    assert not report.ok
    assert "forbidden prose token 'live'" in "\n".join(report.errors)
    assert "answer-encoding snake_case prose 'revoke_payroll_after_clearance_drop'" in "\n".join(
        report.errors
    )


def test_classify_preserving_vs_invalidating():
    from cascadeshift.domain.entities import Policy

    w = build_cascade_world()
    t = _task()
    plan = (GrantApplicationAccess(employee_id="E-001", application_id="APP-CRM"),)

    same = classify_plan_effect(w, w, t, plan)
    assert same.effect == "plan_preserving"

    # Policy-coupled fixture: threshold gate and payroll floor now key off
    # policy/role config, so lowering them invalidates the same grant plan.
    from cascadeshift.domain.rules import Rule

    prov = {"owner": "t", "effective_date": "2026-01-01", "source": "T"}
    r2 = Rule(
        rule_id="R-0002",
        title="gate",
        description="policy-coupled gate",
        trigger="access_granted",
        conditions=[{"kind": "risk_load_at_least_threshold"}],
        effects=[{"kind": "set_clearance", "level": 2}],
        priority=80,
        status="active",
        provenance=prov,
    )
    r3 = Rule(
        rule_id="R-0003",
        title="floor",
        description="payroll floor",
        trigger="access_granted",
        conditions=[
            {"kind": "clearance_below_role_required"},
            {"kind": "employee_has_entitlement", "application_id": "APP-PAY"},
        ],
        effects=[{"kind": "revoke_entitlement", "application_id": "APP-PAY"}],
        priority=70,
        status="active",
        provenance=prov,
    )
    rules = {r.rule_id: r for r in w.rules}
    rules.update({"R-0002": r2, "R-0003": r3})
    w3_base = w.model_copy(update={"rules": tuple(rules.values())})
    w2 = w3_base.model_copy(
        update={
            "policy": Policy(risk_threshold=30, clearance_floor=2, approval_mode="auto"),
            "roles": tuple(
                r.model_copy(update={"clearance_required": 3}) if r.role_id == "RL-02" else r
                for r in w.roles
            ),
        }
    )
    # Sanity: the shifted world must actually break the baseline replay.
    assert not classify_plan_effect(w, w2, t, plan).baseline_plan_csts
    # No alternative plan can keep PAY under these rules.
    out = classify_plan_effect(w, w2, t, plan, alternative_status="unsolvable")
    assert out.effect == "inadmissible"
    assert not out.baseline_plan_csts
    # With an oracle-valid alternative the label becomes plan_invalidating.
    out2 = classify_plan_effect(w, w2, t, plan, alternative_status="solved")
    assert out2.effect == "plan_invalidating"


def test_classify_requires_alternative_for_invalidation():
    """Admissibility rule: invalidating shifts must leave an oracle-valid plan."""
    from cascadeshift.domain.rules import EmployeeFieldAtLeast
    from cascadeshift.tasks.oracle import solve

    w = build_cascade_world()
    t = _task()
    base = solve(w, t).plan
    assert base

    clearance_gate = w.rules[1].model_copy(
        update={"conditions": (EmployeeFieldAtLeast(field="risk_load", value=0),)}
    )
    w2 = w.model_copy(update={"rules": (w.rules[0], clearance_gate, w.rules[2])})
    alt = solve(w2, t)
    assert alt.status == "unsolvable"
    res = classify_plan_effect(w, w2, t, base, alternative_status=alt.status)
    assert res.effect != "plan_invalidating"
    assert res.effect == "inadmissible"
    assert res.alternative_status == alt.status


def test_validator_reports_catalog_cardinality():
    w: WorldSpec = build_cascade_world()
    trimmed = w.model_copy(update={"rules": w.rules[:-1]})
    report = validate_world(trimmed, expected_rule_count=None)
    assert report.ok  # fixture worlds are exempt from the 128 requirement
