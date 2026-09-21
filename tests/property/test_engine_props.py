"""Engine properties: event-mutation bijection, determinism, bounds."""

import hashlib

from hypothesis import given, settings
from hypothesis import strategies as st

from cascadeshift.domain.actions import (
    AssignRole,
    CompleteOnboarding,
    GrantApplicationAccess,
    OffboardEmployee,
    RevokeApplicationAccess,
)
from cascadeshift.engine.transition import TransitionResult, apply_action
from cascadeshift.engine.world import WorldSpec
from tests.unit.test_engine import build_cascade_world


def seq_hash(res: TransitionResult) -> str:
    payload = res.state.model_dump_json() + "|" + ",".join(e.model_dump_json() for e in res.events)
    return hashlib.sha256(payload.encode()).hexdigest()


employee_ids = st.sampled_from(["E-001", "E-002"])
app_ids = st.sampled_from(["APP-PAY", "APP-CRM", "APP-VIP"])
role_ids = st.sampled_from(["RL-01", "RL-02", "RL-03"])

actions = st.one_of(
    st.tuples(st.just("g"), employee_ids, app_ids).map(
        lambda t: GrantApplicationAccess(employee_id=t[1], application_id=t[2])
    ),
    st.tuples(st.just("r"), employee_ids, app_ids).map(
        lambda t: RevokeApplicationAccess(employee_id=t[1], application_id=t[2])
    ),
    st.tuples(employee_ids, role_ids).map(lambda t: AssignRole(employee_id=t[0], role_id=t[1])),
    employee_ids.map(lambda e: CompleteOnboarding(employee_id=e)),
    employee_ids.map(lambda e: OffboardEmployee(employee_id=e)),
)


@settings(max_examples=200, deadline=None)
@given(st.lists(actions, max_size=12))
def test_no_mutation_without_event_and_determinism(action_list):
    w: WorldSpec = build_cascade_world()
    s = w.initial_state()
    for a in action_list:
        before = s.model_dump_json()
        res = apply_action(w, s, a)
        assert res.status in {"ok", "rejected", "invariant_failed"}
        if res.status == "rejected":
            assert res.events == ()
            assert res.state.model_dump_json() == before
        else:
            # Every field-level difference must be covered by some event change.
            after_events = {
                (c.entity_id, c.field, c.before, c.after) for e in res.events for c in e.changes
            }
            prev = type(w.initial_state()).model_validate_json(before)
            nxt = res.state
            diffs = set()
            for e_old, e_new in zip(prev.employees, nxt.employees, strict=True):
                d_old = e_old.model_dump()
                d_new = e_new.model_dump()
                for f in d_old:
                    if d_old[f] != d_new[f]:
                        diffs.add((e_old.employee_id, f, str(d_old[f]), str(d_new[f])))
            reqs_old = {r.request_id: r.status for r in prev.requests}
            reqs_new = {r.request_id: r.status for r in nxt.requests}
            for rid_, stt in reqs_new.items():
                if reqs_old.get(rid_) != stt:
                    diffs.add((rid_, "status", str(reqs_old.get(rid_, "-")), str(stt)))
            unexplained = {
                d
                for d in diffs
                if d not in after_events
                and not any(ae[0] == d[0] and ae[1] == d[1] for ae in after_events)
            }
            assert not unexplained, f"mutations without events: {unexplained}"
            s = res.state


@settings(max_examples=100, deadline=None)
@given(st.lists(actions, max_size=10))
def test_same_sequence_same_trace(action_list):
    w = build_cascade_world()

    def run():
        s = w.initial_state()
        out = []
        for a in action_list:
            res = apply_action(w, s, a)
            out.append(seq_hash(res))
            s = res.state
        return out

    assert run() == run()
