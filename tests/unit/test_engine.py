"""Transition engine: events, atomicity, bounds, deterministic order, replay."""

import pytest
from pydantic import ValidationError

from cascadeshift.domain.actions import (
    ApproveRequest,
    GrantApplicationAccess,
    OffboardEmployee,
    RevokeApplicationAccess,
)
from cascadeshift.domain.rules import Rule
from cascadeshift.engine.integrity import validate_transition_integrity
from cascadeshift.engine.transition import MAX_FIRINGS, apply_action
from cascadeshift.engine.world import WorldSpec


def _inactive_trigger_rules(count: int) -> tuple[Rule, ...]:
    provenance = {"owner": "test", "effective_date": "2026-01-01", "source": "TEST"}
    return tuple(
        Rule(
            rule_id=f"R-{1000 + index:04d}",
            title=f"Inactive trigger {index}",
            description="Does not execute.",
            trigger="access_granted",
            conditions=[{"kind": "always"}],
            effects=[{"kind": "set_clearance", "level": 1}],
            priority=1,
            status="inactive",
            provenance=provenance,
        )
        for index in range(count)
    )


def build_cascade_world() -> WorldSpec:
    """World reproducing the design's section-6 hidden cascade."""
    rules = [
        Rule(
            rule_id="R-0001",
            title="Cumulative risk accounting",
            description="Adds the granted application risk score to the employee load.",
            trigger="access_granted",
            conditions=[{"kind": "always"}],
            effects=[{"kind": "adjust_risk_load", "source": "event_app_risk", "value": 0}],
            priority=90,
            status="active",
            provenance={
                "owner": "iam-platform",
                "effective_date": "2026-01-01",
                "source": "SEC-POL-100",
            },
        ),
        Rule(
            rule_id="R-0002",
            title="Clearance compliance gate",
            description="Downgrades clearance when cumulative load crosses the threshold.",
            trigger="access_granted",
            conditions=[
                {"kind": "employee_field_at_least", "field": "risk_load", "value": 80},
            ],
            effects=[{"kind": "set_clearance", "level": 2}],
            priority=80,
            status="active",
            provenance={
                "owner": "security",
                "effective_date": "2026-01-01",
                "source": "SEC-POL-114",
            },
        ),
        Rule(
            rule_id="R-0003",
            title="Payroll entitlement integrity",
            description="Revokes payroll when clearance falls below the payroll floor.",
            trigger="access_granted",
            conditions=[
                {"kind": "employee_field_below", "field": "clearance", "value": 3},
                {"kind": "employee_has_entitlement", "application_id": "APP-PAY"},
            ],
            effects=[{"kind": "revoke_entitlement", "application_id": "APP-PAY"}],
            priority=70,
            status="active",
            provenance={
                "owner": "payroll",
                "effective_date": "2026-02-01",
                "source": "FIN-POL-020",
            },
        ),
    ]
    return WorldSpec.for_testing(rules=rules)


def test_grant_produces_events_for_every_mutation():
    w = build_cascade_world()
    res = apply_action(
        w, w.initial_state(), GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )
    assert res.status == "ok"
    kinds = [(e.cause, e.rule_id) for e in res.events]
    # Single-pass semantics: one firing per rule, priority desc order.
    assert kinds == [
        ("action", None),
        ("rule", "R-0001"),
        ("rule", "R-0002"),
        ("rule", "R-0003"),
    ]
    emp = res.state.employee("E-001")
    assert emp.entitlements == ("APP-VIP",)  # payroll revoked by cascade
    assert emp.clearance == 2 and emp.risk_load == 80


def test_tool_success_but_terminal_state_changed_is_visible_in_trace():
    """Design section 6: grant tool returns success while a cascade revokes payroll."""
    w = build_cascade_world()
    res = apply_action(
        w, w.initial_state(), GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )
    grant_event = next(e for e in res.events if e.cause == "action")
    assert grant_event.note == "granted"
    revoked = [
        c
        for e in res.events
        for c in e.changes
        if c.field == "entitlements" and c.before == "APP-PAY,APP-VIP" and c.after == "APP-VIP"
    ]
    assert revoked, "cascade revocation must be traceable"


def test_rejected_action_mutates_nothing_and_emits_no_event():
    w = build_cascade_world()
    before = w.initial_state()
    res = apply_action(
        w, before, GrantApplicationAccess(employee_id="E-GHOST", application_id="APP-VIP")
    )
    assert res.status == "rejected"
    assert res.events == ()
    assert res.state == before


def test_atomic_rollback_on_loop_bound(monkeypatch):
    import cascadeshift.engine.transition as transition

    w = build_cascade_world()
    # Oscillator fixture: two rules alternate clearance. Under the single
    # pass each fires once, so we force the guard low to prove the bound
    # trips atomically when exceeded.
    prov = {"owner": "t", "effective_date": "2026-01-01", "source": "T"}
    osc_a = Rule(
        rule_id="R-0063",
        title="OscA",
        description="clearance flip high",
        trigger="employee_offboarded",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "set_clearance", "level": 5}],
        priority=99,
        status="active",
        provenance=prov,
    )
    osc_b = Rule(
        rule_id="R-0064",
        title="OscB",
        description="clearance flip low",
        trigger="employee_offboarded",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "set_clearance", "level": 2}],
        priority=98,
        status="active",
        provenance=prov,
    )
    w2 = w.model_copy(update={"rules": (*w.rules, osc_a, osc_b)})
    from cascadeshift.domain.actions import OffboardEmployee

    monkeypatch.setattr(transition, "MAX_FIRINGS", 1)
    res = transition.apply_action(w2, w2.initial_state(), OffboardEmployee(employee_id="E-002"))
    assert res.status == "invariant_failed"
    assert res.state == w2.initial_state()
    assert res.error is not None and "bound" in res.error


def test_scheduler_orders_by_priority_desc_then_rule_id_asc():
    w = build_cascade_world()
    res = apply_action(
        w, w.initial_state(), GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )
    rule_seq = [e.rule_id for e in res.events if e.cause == "rule"]
    assert rule_seq == ["R-0001", "R-0002", "R-0003"]


def test_replay_determinism_snapshot_restore():
    w = build_cascade_world()
    s0 = w.initial_state()
    r1 = apply_action(w, s0, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP"))
    r2 = apply_action(w, s0, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP"))
    assert r1.state.model_dump_json() == r2.state.model_dump_json()
    assert [e.model_dump_json() for e in r1.events] == [e.model_dump_json() for e in r2.events]

    mid = r1.state
    r3a = apply_action(
        w, mid, RevokeApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )
    restored = WorldState_from_snapshot(mid.model_dump_json())
    r3b = apply_action(
        w, restored, RevokeApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )
    assert r3a.state.model_dump_json() == r3b.state.model_dump_json()


def WorldState_from_snapshot(snapshot: str):
    from cascadeshift.domain.state import WorldState

    return WorldState.model_validate_json(snapshot)


def test_security_review_flow_creates_pending_request_then_approval_grants():
    w = build_cascade_world()
    s0 = w.initial_state().model_copy(update={"review_required": (("E-001", "APP-VIP"),)})
    res = apply_action(w, s0, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP"))
    assert res.status == "ok"
    assert "APP-VIP" not in res.state.employee("E-001").entitlements
    req = res.state.requests[-1]
    assert req.status == "pending"
    res2 = apply_action(w, res.state, ApproveRequest(request_id=req.request_id))
    assert res2.status == "ok"
    assert res2.state.requests[-1].status == "approved"
    assert res2.events[0].action_name == "ApproveRequest"
    assert res2.fired_rule_ids == ("R-0001", "R-0002", "R-0003")
    emp = res2.state.employee("E-001")
    assert emp.entitlements == ("APP-VIP",)
    assert emp.clearance == 2 and emp.risk_load == 80


def test_approval_cascade_precedes_access_granted_cascade():
    """Approval effects run first; a later access rule can deliberately supersede them."""
    provenance = {"owner": "test", "effective_date": "2026-01-01", "source": "TEST"}
    approval_revoke = Rule(
        rule_id="R-1114",
        title="Approval settlement penalty",
        description="Approved high-risk requests revoke payroll first.",
        trigger="approval_granted",
        conditions=[{"kind": "risk_load_at_least_threshold"}],
        effects=[{"kind": "revoke_entitlement", "application_id": "APP-PAY"}],
        priority=95,
        status="active",
        provenance=provenance,
    )
    grant_restore = Rule(
        rule_id="R-1115",
        title="Access entitlement rule",
        description="The access-granted pass restores payroll after the approval pass.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "grant_entitlement", "application_id": "APP-PAY"}],
        priority=90,
        status="active",
        provenance=provenance,
    )
    world = WorldSpec.for_testing(rules=(approval_revoke, grant_restore))
    initial = world.initial_state()
    before = initial.with_employee(
        initial.employee("E-001").model_copy(update={"risk_load": 80})
    ).model_copy(update={"review_required": (("E-001", "APP-VIP"),)})
    requested = apply_action(
        world, before, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )

    approved = apply_action(
        world, requested.state, ApproveRequest(request_id=requested.state.requests[-1].request_id)
    )

    assert approved.status == "ok"
    assert approved.fired_rule_ids == ("R-1114", "R-1115")
    assert validate_transition_integrity(world, requested.state, approved) == ()
    assert [(event.seq, event.rule_id, event.origin_seq) for event in approved.events] == [
        (0, None, 0),
        (1, "R-1114", 0),
        (2, None, 2),
        (3, "R-1115", 2),
    ]
    approval_revoke_event = approved.events[1]
    assert approval_revoke_event.changes[0].entity_id == "E-001"
    assert approval_revoke_event.changes[0].before == "APP-PAY"
    assert approval_revoke_event.changes[0].after == ""
    assert approved.state.employee("E-001").entitlements == ("APP-PAY", "APP-VIP")


def test_offboarding_cancels_pending_requests_and_blocks_future_provisioning():
    w = build_cascade_world()
    s0 = w.initial_state().model_copy(update={"review_required": (("E-001", "APP-VIP"),)})
    requested = apply_action(
        w, s0, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )
    request_id = requested.state.requests[-1].request_id

    offboarded = apply_action(w, requested.state, OffboardEmployee(employee_id="E-001"))
    assert offboarded.status == "ok"
    assert offboarded.state.employee("E-001").entitlements == ()
    assert offboarded.state.requests[-1].status == "cancelled"
    assert any(
        c.entity_id == request_id and c.before == "pending" and c.after == "cancelled"
        for e in offboarded.events
        for c in e.changes
    )

    grant = apply_action(
        w, offboarded.state, GrantApplicationAccess(employee_id="E-001", application_id="APP-CRM")
    )
    approval = apply_action(w, offboarded.state, ApproveRequest(request_id=request_id))
    assert grant.status == approval.status == "rejected"
    assert grant.error == approval.error == "inactive_employee"
    assert grant.state == approval.state == offboarded.state


def test_rule_enabled_earlier_in_a_pass_can_fire_later():
    provenance = {"owner": "test", "effective_date": "2026-01-01", "source": "TEST"}
    enabler = Rule(
        rule_id="R-0004",
        title="Enable peer",
        description="Activates a later rule in the same pass.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "enable_rule", "rule_id": "R-0005"}],
        priority=20,
        status="active",
        provenance=provenance,
    )
    enabled = Rule(
        rule_id="R-0005",
        title="Enabled peer",
        description="Runs after activation.",
        trigger="access_granted",
        conditions=[{"kind": "always"}],
        effects=[{"kind": "set_clearance", "level": 1}],
        priority=10,
        status="inactive",
        provenance=provenance,
    )
    w = WorldSpec.for_testing(rules=(enabler, enabled))

    result = apply_action(
        w, w.initial_state(), GrantApplicationAccess(employee_id="E-001", application_id="APP-CRM")
    )

    assert result.status == "ok"
    assert result.fired_rule_ids == ("R-0004", "R-0005")
    assert dict(result.state.rule_status_overrides)["R-0005"] == "active"
    assert result.state.employee("E-001").clearance == 1


def test_max_firings_constant_is_bounded():
    assert 8 <= MAX_FIRINGS <= 128


def test_world_schema_rejects_more_than_128_rules():
    with pytest.raises(ValidationError, match="at most 128 rules"):
        WorldSpec.for_testing(rules=_inactive_trigger_rules(129))


def test_trigger_candidate_bound_rejects_inactive_rules_before_sorting():
    world = WorldSpec.for_testing(rules=_inactive_trigger_rules(MAX_FIRINGS + 1))
    initial = world.initial_state()

    result = apply_action(
        world, initial, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )

    assert result.status == "invariant_failed"
    assert result.error == "cascade bound exceeded; action rolled back"
    assert result.state == initial
    assert result.events == ()


@pytest.mark.parametrize(
    ("tamper", "expected_error"),
    [
        (
            lambda result: result.model_copy(
                update={
                    "state": result.state.with_employee(
                        result.state.employee("E-002").with_entitlement("APP-CRM")
                    )
                }
            ),
            "unexplained state mutation: E-002.entitlements",
        ),
        (
            lambda result: result.model_copy(
                update={"events": (result.events[0].model_copy(update={"seq": 1}),)}
            ),
            "event sequence is not contiguous from zero",
        ),
        (
            lambda result: result.model_copy(
                update={"events": (result.events[0].model_copy(update={"changes": ()}),)}
            ),
            "event 0 has no state changes",
        ),
        (
            lambda result: result.model_copy(
                update={"events": (result.events[0].model_copy(update={"rule_id": "R-FAKE"}),)}
            ),
            "invalid action provenance at event 0",
        ),
    ],
)
def test_transition_integrity_rejects_forged_trace_controls(tamper, expected_error):
    world = WorldSpec.for_testing(rules=())
    before = world.initial_state()
    result = apply_action(
        world, before, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )

    assert expected_error in validate_transition_integrity(world, before, tamper(result))


def test_transition_integrity_rejects_structurally_traced_replay_divergence():
    world = WorldSpec.for_testing(rules=())
    before = world.initial_state()
    result = apply_action(
        world, before, GrantApplicationAccess(employee_id="E-001", application_id="APP-VIP")
    )
    employee = before.employee("E-001").with_entitlement("APP-CRM")
    tampered = result.model_copy(
        update={
            "state": before.with_employee(employee),
            "events": (
                result.events[0].model_copy(
                    update={
                        "changes": (
                            result.events[0]
                            .changes[0]
                            .model_copy(update={"after": "APP-CRM,APP-PAY"}),
                        ),
                    }
                ),
            ),
        }
    )

    assert validate_transition_integrity(world, before, tampered) == (
        "transition result diverges from deterministic replay",
    )
