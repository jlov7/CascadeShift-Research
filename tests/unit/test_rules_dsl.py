"""Closed typed rule DSL (ledger D-03, H-02 naming)."""

import pytest
from pydantic import ValidationError

from cascadeshift.domain.rules import (
    AdjustRiskLoad,
    DisableRule,
    EmployeeFieldAtLeast,
    EmployeeHasEntitlement,
    EmployeeIsContractor,
    EmployeeLacksEntitlement,
    EnableRule,
    EventApplicationRiskAbove,
    GrantEntitlement,
    Provenance,
    RequireSecurityReview,
    RevokeEntitlement,
    RevokeEntitlementGlobally,
    Rule,
    SetClearance,
    parse_rule,
)


def _rule(**kw):
    base = dict(
        rule_id="R-0001",
        title="Risk accounting",
        description="Adjusts cumulative risk load after an access grant.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "adjust_risk_load", "source": "event_app_risk", "value": 0}],
        priority=50,
        status="active",
        provenance={
            "owner": "iam-platform",
            "effective_date": "2026-01-01",
            "source": "SEC-POL-100",
        },
    )
    base.update(kw)
    return Rule(**base)


def test_rule_schema_accepts_valid_rule():
    r = _rule()
    assert r.rule_id == "R-0001"
    assert r.conditions[0].kind == "always"


def test_rule_rejects_unknown_fields_and_bad_ids():
    with pytest.raises(ValidationError):
        _rule(rule_id="RULE_SEVENTEEN")
    with pytest.raises(ValidationError):
        _rule(bogus=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        _rule(trigger="something_happened")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _rule(status="kind_of_active")  # type: ignore[arg-type]


def test_condition_union_is_closed():
    from pydantic import TypeAdapter

    from cascadeshift.domain.rules import Condition as ConditionT

    ta = TypeAdapter(ConditionT)
    valid = [
        {"kind": "always"},
        {"kind": "employee_field_at_least", "field": "clearance", "value": 3},
        {"kind": "employee_field_below", "field": "risk_load", "value": 80},
        {"kind": "employee_has_entitlement", "application_id": "APP-01"},
        {"kind": "employee_lacks_entitlement", "application_id": "APP-01"},
        {"kind": "event_application_risk_above", "value": 50},
        {"kind": "employee_is_contractor"},
    ]
    for c in valid:
        ta.validate_python(c)
    with pytest.raises(ValidationError):
        ta.validate_python({"kind": "moon_is_full"})


def test_effect_union_is_closed():
    from pydantic import TypeAdapter

    from cascadeshift.domain.rules import Effect as EffectT

    ta = TypeAdapter(EffectT)
    valid = [
        {"kind": "adjust_risk_load", "source": "static", "value": 5},
        {"kind": "set_clearance", "level": 2},
        {"kind": "revoke_entitlement", "application_id": "APP-01"},
        {"kind": "revoke_entitlement_globally", "application_id": "APP-01"},
        {"kind": "grant_entitlement", "application_id": "APP-01"},
        {"kind": "require_security_review"},
        {"kind": "enable_rule", "rule_id": "R-0009"},
        {"kind": "disable_rule", "rule_id": "R-0009"},
    ]
    for e in valid:
        ta.validate_python(e)
    with pytest.raises(ValidationError):
        ta.validate_python({"kind": "email_the_ceo"})


def test_parse_rule_roundtrip_and_provenance_required():
    r = _rule()
    assert parse_rule(r.model_dump()) == r
    with pytest.raises(ValidationError):
        _rule(provenance=None)  # type: ignore[arg-type]


def test_effects_types_exist_for_all_operators():
    assert AdjustRiskLoad(source="static", value=1).kind == "adjust_risk_load"
    assert SetClearance(level=1).kind == "set_clearance"
    assert RevokeEntitlement(application_id="APP-1").kind == "revoke_entitlement"
    assert RevokeEntitlementGlobally(application_id="APP-1").kind == ("revoke_entitlement_globally")
    assert GrantEntitlement(application_id="APP-1").kind == "grant_entitlement"
    assert RequireSecurityReview().kind == "require_security_review"
    assert EnableRule(rule_id="R-0002").kind == "enable_rule"
    assert DisableRule(rule_id="R-0002").kind == "disable_rule"
    assert EmployeeIsContractor().kind == "employee_is_contractor"
    assert EventApplicationRiskAbove(value=1).kind == "event_application_risk_above"
    assert EmployeeFieldAtLeast(field="clearance", value=1).kind == ("employee_field_at_least")
    assert EmployeeHasEntitlement(application_id="APP-1").kind == ("employee_has_entitlement")
    assert EmployeeLacksEntitlement(application_id="APP-1").kind == ("employee_lacks_entitlement")
    assert isinstance(Provenance(owner="o", effective_date="2026-01-01", source="s"), Provenance)
