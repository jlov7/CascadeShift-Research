"""Snapshot / restore / replay equivalence (ledger E-03)."""

from cascadeshift.domain.actions import (
    ApproveRequest,
    GrantApplicationAccess,
    RevokeApplicationAccess,
)
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.transition import apply_action
from tests.unit.test_engine import build_cascade_world


def test_snapshot_restore_midway_equivalent():
    w = build_cascade_world()
    s = w.initial_state()
    r1 = apply_action(w, s, GrantApplicationAccess(employee_id="E-001", application_id="APP-CRM"))
    assert r1.status == "ok"
    snapshot = r1.state.model_dump_json()

    restored = WorldState.model_validate_json(snapshot)
    tail = [
        RevokeApplicationAccess(employee_id="E-001", application_id="APP-CRM"),
        GrantApplicationAccess(employee_id="E-001", application_id="APP-PAY"),
    ]
    a_state, b_state = restored, WorldState.model_validate_json(snapshot)
    for act in tail:
        ra = apply_action(w, a_state, act)
        rb = apply_action(w, b_state, act)
        a_state, b_state = ra.state, rb.state
        assert ra.state.model_dump_json() == rb.state.model_dump_json()


def test_approval_request_ids_stay_deterministic_across_replay():
    w = build_cascade_world()
    s0 = w.initial_state().model_copy(update={"review_required": (("E-002", "APP-VIP"),)})
    res = apply_action(w, s0, GrantApplicationAccess(employee_id="E-002", application_id="APP-VIP"))
    req = res.state.requests[-1]
    res2 = apply_action(w, res.state, ApproveRequest(request_id=req.request_id))
    assert res2.state.employee("E-002").entitlements == ("APP-VIP",)
