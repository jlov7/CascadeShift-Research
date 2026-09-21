"""Deliberately broken fixtures: the system must REJECT each one (E-06).

Each test mutates a golden fixture in a specific, realistic way and asserts
that validation, the engine, or the verifier catches it. A green run here
means the guardrails are real, not decorative.
"""

import pytest
from pydantic import ValidationError

from cascadeshift.domain.actions import GrantApplicationAccess
from cascadeshift.domain.constraints import GoalEntitlementPresent
from cascadeshift.domain.entities import Application
from cascadeshift.engine.events import Event, FieldChange
from cascadeshift.engine.integrity import validate_transition_integrity
from cascadeshift.engine.transition import TransitionResult, apply_action
from cascadeshift.engine.world_io import load_world
from cascadeshift.shifts.operators import parse_op
from cascadeshift.shifts.validation import validate_world
from cascadeshift.tasks.models import TaskSpec
from cascadeshift.tasks.oracle import solve

W = "worlds/baseline/world.yaml"


def _baseline():
    return load_world(W)


def test_broken_rule_dangling_application_reference_rejected():
    w = _baseline()
    rules = list(w.rules)
    rules[0] = rules[0].model_copy(deep=True)
    broken = rules[0].model_dump()
    broken["conditions"] = [{"kind": "employee_has_entitlement", "application_id": "APP-GHOST"}]
    from cascadeshift.domain.rules import parse_rule

    rules[0] = parse_rule(broken)
    bad = w.model_copy(update={"rules": tuple(rules)})
    report = validate_world(bad)
    assert not report.ok
    assert any("APP-GHOST" in e for e in report.errors)


def test_broken_catalog_cardinality_127_rejected_for_confirmatory_use():
    w = _baseline()
    trimmed = w.model_copy(update={"rules": w.rules[:-1]})
    report = validate_world(trimmed, expected_rule_count=128)
    assert not report.ok


def test_duplicate_rule_ids_rejected_at_schema_level():
    w = _baseline()
    doubled = (*w.rules, w.rules[0])
    payload = w.model_dump()
    payload["rules"] = [r.model_dump() for r in doubled]
    with pytest.raises(ValidationError):
        type(w).model_validate(payload)


def test_answer_encoding_snake_case_description_rejected_by_prose_policy():
    w = _baseline()
    rule = next(iter(w.rules)).model_copy(
        update={
            "description": "Revokes payroll after clearance drops "
            "(revoke_payroll_after_clearance_drop)."
        }
    )
    bad = w.model_copy(update={"rules": (rule, *w.rules[1:])})
    report = validate_world(bad)
    assert not report.ok
    assert any("answer-encoding snake_case prose" in error for error in report.errors)


def test_enable_rule_targeting_active_rule_rejected():
    from cascadeshift.shifts.operators import apply_op

    w = _baseline()
    active_id = next(r.rule_id for r in w.rules if r.status == "active")
    with pytest.raises(ValueError):
        apply_op(w, parse_op({"kind": "enable_rule", "rule_id": active_id}))


def test_unsolvable_task_rejected_by_oracle_admission():
    w = _baseline()
    impossible = TaskSpec(
        task_id="T-BROKEN",
        parent_task_id=None,
        family="F1_grant_preserve",
        title="broken anchor",
        description="requires an entitlement to a nonexistent application",
        visible_goal=(GoalEntitlementPresent(employee_id="E-001", application_id="APP-NOPE"),),
        hard_constraints=(),
    )
    res = solve(w, impossible)
    assert res.status in {"unsolvable", "budget_exhausted"}


def test_mutation_without_event_is_detected():
    """A hand-forged result whose state moved without events must be caught."""
    w = _baseline()
    s0 = w.initial_state()
    res = apply_action(w, s0, GrantApplicationAccess(employee_id="E-001", application_id="APP-CRM"))
    assert isinstance(res, TransitionResult)

    def explained(result: TransitionResult) -> set[tuple[str, str]]:
        return {(c.entity_id, c.field) for e in result.events for c in e.changes}

    forged_state = res.state.model_copy(deep=True)
    emp = forged_state.employee("E-003")
    tampered = emp.with_entitlement("APP-VIP")
    forged_state = res.state.__class__(
        employees=tuple(tampered if e.employee_id == "E-003" else e for e in res.state.employees)
    )
    forged = res.model_copy(update={"state": forged_state})
    assert validate_transition_integrity(w, s0, res) == ()
    errors = validate_transition_integrity(w, s0, forged)
    assert "unexplained state mutation: E-003.entitlements" in errors
    assert "transition result diverges from deterministic replay" in errors


def test_non_ok_transition_cannot_hide_mutated_state_or_events():
    w = _baseline()
    before = w.initial_state()
    successful = apply_action(
        w, before, GrantApplicationAccess(employee_id="E-001", application_id="APP-CRM")
    )
    forged = successful.model_copy(update={"status": "rejected"})

    assert validate_transition_integrity(w, before, forged) == (
        "non-ok transition changed state",
        "non-ok transition emitted events",
        "non-ok transition fired rules",
    )


def test_transition_integrity_accepts_request_review_and_rule_override_changes():
    from cascadeshift.domain.rules import Rule
    from cascadeshift.engine.world import WorldSpec

    provenance = {"owner": "test", "effective_date": "2026-01-01", "source": "TEST"}
    review_rule = Rule(
        rule_id="R-0040",
        title="Review flag",
        description="Marks high-risk access for approval.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "require_security_review"}],
        priority=20,
        status="inactive",
        provenance=provenance,
    )
    override_rule = Rule(
        rule_id="R-0041",
        title="Enable slot",
        description="Activates a dormant peer.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[
            {"kind": "enable_rule", "rule_id": "R-0040"},
            {"kind": "enable_rule", "rule_id": "R-0042"},
        ],
        priority=30,
        status="active",
        provenance=provenance,
    )
    dormant_rule = Rule(
        rule_id="R-0042",
        title="Dormant peer",
        description="Applies after activation.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "set_clearance", "level": 2}],
        priority=10,
        status="inactive",
        provenance=provenance,
    )
    world = WorldSpec.for_testing(rules=(review_rule, override_rule, dormant_rule))
    initial = world.initial_state()
    before = initial.with_employee(
        initial.employee("E-001").model_copy(update={"status": "active"})
    )
    reviewed = apply_action(
        world,
        before,
        GrantApplicationAccess(employee_id="E-001", application_id="APP-CRM"),
    )
    assert ("E-001", "APP-CRM") in reviewed.state.review_required
    assert dict(reviewed.state.rule_status_overrides)["R-0042"] == "active"
    assert validate_transition_integrity(world, before, reviewed) == ()

    request_before = before.model_copy(update={"review_required": (("E-001", "APP-VIP"),)})
    requested = apply_action(
        world,
        request_before,
        GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP"),
    )
    assert requested.state.requests[-1].status == "pending"
    assert validate_transition_integrity(world, request_before, requested) == ()


def test_transition_integrity_rejects_forged_rule_provenance_and_extra_event():
    w = _baseline()
    before = w.initial_state()
    result = apply_action(
        w, before, GrantApplicationAccess(employee_id="E-001", application_id="APP-CRM")
    )
    rule_event = next(event for event in result.events if event.cause == "rule")
    bad_origin = result.model_copy(
        update={
            "events": tuple(
                event.model_copy(update={"origin_seq": event.seq}) if event is rule_event else event
                for event in result.events
            )
        }
    )
    assert "invalid rule provenance" in "\n".join(
        validate_transition_integrity(w, before, bad_origin)
    )

    forged_extra = result.model_copy(
        update={
            "events": (
                *result.events,
                Event(
                    seq=len(result.events),
                    cause="rule",
                    rule_id="R-9999",
                    origin_seq=0,
                    depth=1,
                ),
            ),
        }
    )
    errors = validate_transition_integrity(w, before, forged_extra)
    assert f"event {len(result.events)} has no state changes" in errors
    assert "fired rule ids do not match rule events" in errors

    wrong_trigger_id = next(rule.rule_id for rule in w.rules if rule.trigger != "access_granted")
    trigger_mismatch = result.model_copy(
        update={
            "events": tuple(
                event.model_copy(update={"rule_id": wrong_trigger_id})
                if event is rule_event
                else event
                for event in result.events
            ),
            "fired_rule_ids": tuple(
                wrong_trigger_id if rule_id == rule_event.rule_id else rule_id
                for rule_id in result.fired_rule_ids
            ),
        }
    )
    assert "invalid rule provenance" in "\n".join(
        validate_transition_integrity(w, before, trigger_mismatch)
    )

    same_trigger_id = next(
        rule.rule_id
        for rule in w.rules
        if rule.trigger == "access_granted" and rule.rule_id != rule_event.rule_id
    )
    same_trigger_substitution = result.model_copy(
        update={
            "events": tuple(
                event.model_copy(
                    update={
                        "rule_id": same_trigger_id,
                        "rule_content_hash": w.rule_map()[same_trigger_id].content_hash(),
                    }
                )
                if event is rule_event
                else event
                for event in result.events
            ),
            "fired_rule_ids": tuple(
                same_trigger_id if rule_id == rule_event.rule_id else rule_id
                for rule_id in result.fired_rule_ids
            ),
        }
    )
    same_trigger_errors = validate_transition_integrity(w, before, same_trigger_substitution)
    assert "invalid rule provenance" not in "\n".join(same_trigger_errors)
    assert "transition result diverges from deterministic replay" in same_trigger_errors


def test_transition_integrity_rejects_reversible_forged_unknown_rules():
    from cascadeshift.engine.world import WorldSpec

    world = WorldSpec.for_testing(rules=())
    before = world.initial_state()
    result = apply_action(
        world, before, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )
    forged = result.model_copy(
        update={
            "events": (
                *result.events,
                Event(
                    seq=1,
                    cause="rule",
                    rule_id="R-9998",
                    origin_seq=0,
                    depth=1,
                    changes=(
                        FieldChange(entity_id="E-001", field="clearance", before="4", after="1"),
                    ),
                ),
                Event(
                    seq=2,
                    cause="rule",
                    rule_id="R-9999",
                    origin_seq=0,
                    depth=1,
                    changes=(
                        FieldChange(entity_id="E-001", field="clearance", before="1", after="4"),
                    ),
                ),
            ),
            "fired_rule_ids": ("R-9998", "R-9999"),
        }
    )

    errors = validate_transition_integrity(world, before, forged)
    assert errors.count("invalid rule provenance at event 1") == 1
    assert errors.count("invalid rule provenance at event 2") == 1


def test_transition_integrity_accepts_genuine_revert_to_original_state():
    from cascadeshift.domain.rules import Rule
    from cascadeshift.engine.world import WorldSpec

    provenance = {"owner": "test", "effective_date": "2026-01-01", "source": "TEST"}
    lower = Rule(
        rule_id="R-0100",
        title="Lower clearance",
        description="Temporarily lowers clearance.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "set_clearance", "level": 1}],
        priority=20,
        status="active",
        provenance=provenance,
    )
    restore = Rule(
        rule_id="R-0101",
        title="Restore clearance",
        description="Restores clearance before completion.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "set_clearance", "level": 4}],
        priority=10,
        status="active",
        provenance=provenance,
    )
    world = WorldSpec.for_testing(rules=(lower, restore))
    before = world.initial_state()
    result = apply_action(
        world, before, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )

    assert result.state.employee("E-001").clearance == before.employee("E-001").clearance
    assert validate_transition_integrity(world, before, result) == ()


def test_unknown_shift_operator_payload_rejected():
    from pydantic import ValidationError as VE

    with pytest.raises(VE):
        parse_op({"kind": "rewrite_history"})


def test_broken_task_missing_parent_on_shifted_case_rejected():
    from cascadeshift.tasks.models import ShiftedCase

    with pytest.raises(ValidationError):
        ShiftedCase(
            task_id="S-BROKEN",
            parent_task_id="",
            family="F6_negative_control",
            title="t",
            description="d",
            shift_id="SH-X",
        )


def test_engine_rejects_action_referencing_unknown_role():
    from cascadeshift.domain.actions import AssignRole

    w = _baseline()
    res = apply_action(w, w.initial_state(), AssignRole(employee_id="E-001", role_id="RL-GHOST"))
    assert res.status == "rejected"


def test_application_with_out_of_range_risk_rejected():
    with pytest.raises(ValidationError):
        Application(
            application_id="APP-X", name="x", risk_score=101, requires_security_review=False
        )
