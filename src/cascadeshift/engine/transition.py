"""Deterministic transition engine.

For every mutating action:
  validate -> apply direct effect -> run eligible rules in deterministic
  order (priority desc, rule_id asc) -> append all changes to an immutable
  event trace -> return the observation.

Each rule evaluates at most once per business event against live state;
enable/disable effects take effect immediately for later rules in the pass.
Failed hard invariants roll back the whole action (atomicity).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from cascadeshift.domain.actions import (
    Action,
    ApproveRequest,
    AssignRole,
    CompleteOnboarding,
    FinishTask,
    GrantApplicationAccess,
    OffboardEmployee,
    RevokeApplicationAccess,
)
from cascadeshift.domain.entities import AccessRequestRecord
from cascadeshift.domain.rules import (
    AdjustRiskLoad,
    ClearanceBelowRoleRequired,
    Condition,
    DisableRule,
    Effect,
    EmployeeFieldAtLeast,
    EmployeeFieldBelow,
    EmployeeHasEntitlement,
    EmployeeIsContractor,
    EmployeeLacksEntitlement,
    EnableRule,
    EventApplicationRiskAbove,
    GrantEntitlement,
    RequireSecurityReview,
    RevokeEntitlement,
    RevokeEntitlementGlobally,
    RiskLoadAtLeastThreshold,
    SetClearance,
)
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.events import Event, FieldChange
from cascadeshift.engine.scheduler import (
    ScheduledFiring,
    effective_status,
    order_firings,
)
from cascadeshift.engine.world import WorldSpec

MAX_FIRINGS = 64
MAX_DEPTH = 16


class TransitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: WorldState
    events: tuple[Event, ...]
    status: Literal["ok", "rejected", "invariant_failed"]
    error: str | None = None
    fired_rule_ids: tuple[str, ...] = ()
    note: str | None = None


class _Payload:
    """Triggering-event context for condition evaluation."""

    __slots__ = ("employee_id", "application_id")

    def __init__(self, employee_id: str | None, application_id: str | None) -> None:
        self.employee_id = employee_id
        self.application_id = application_id


def _change(entity_id: str, field: str, before: object, after: object) -> FieldChange:
    return FieldChange(entity_id=entity_id, field=field, before=str(before), after=str(after))


def _check_conditions(
    conditions: tuple[Condition, ...],
    state: WorldState,
    world: WorldSpec,
    payload: _Payload,
) -> bool:
    if payload.employee_id is None:
        return False
    emp = state.employee(payload.employee_id)
    apps = world.app_map()
    for c in conditions:
        if isinstance(c, EmployeeFieldAtLeast):
            if getattr(emp, c.field) < c.value:
                return False
        elif isinstance(c, EmployeeFieldBelow):
            if getattr(emp, c.field) >= c.value:
                return False
        elif isinstance(c, EmployeeHasEntitlement):
            if c.application_id not in emp.entitlements:
                return False
        elif isinstance(c, EmployeeLacksEntitlement):
            if c.application_id in emp.entitlements:
                return False
        elif isinstance(c, EventApplicationRiskAbove):
            app = apps.get(payload.application_id or "")
            if app is None or app.risk_score <= c.value:
                return False
        elif isinstance(c, EmployeeIsContractor):
            if not emp.is_contractor:
                return False
        elif isinstance(c, RiskLoadAtLeastThreshold):
            if emp.risk_load < world.policy.risk_threshold:
                return False
        elif isinstance(c, ClearanceBelowRoleRequired):
            role = world.role_map().get(emp.role_id)
            if role is None or emp.clearance >= role.clearance_required:
                return False
        else:  # Always
            continue
    return True


def _apply_effects(
    effects: tuple[Effect, ...],
    state: WorldState,
    world: WorldSpec,
    payload: _Payload,
) -> tuple[WorldState, list[FieldChange], list[str]]:
    changes: list[FieldChange] = []
    notes: list[str] = []
    emp = state.employee(payload.employee_id) if payload.employee_id else None
    for eff in effects:
        if isinstance(eff, AdjustRiskLoad):
            if emp is None:
                raise RuntimeError("adjust_risk_load requires an employee payload")
            delta = (
                world.app_map()[payload.application_id].risk_score
                if eff.source == "event_app_risk" and payload.application_id
                else eff.value
            )
            new_load = max(0, min(100, emp.risk_load + delta))
            if new_load != emp.risk_load:
                changes.append(_change(emp.employee_id, "risk_load", emp.risk_load, new_load))
                state = state.with_employee(emp.model_copy(update={"risk_load": new_load}))
                emp = state.employee(emp.employee_id)
        elif isinstance(eff, SetClearance):
            if emp is None:
                raise RuntimeError("set_clearance requires an employee payload")
            if emp.clearance != eff.level:
                changes.append(_change(emp.employee_id, "clearance", emp.clearance, eff.level))
                state = state.with_employee(emp.model_copy(update={"clearance": eff.level}))
                emp = state.employee(emp.employee_id)
        elif isinstance(eff, RevokeEntitlement):
            if emp is None:
                raise RuntimeError("revoke_entitlement requires an employee payload")
            if eff.application_id in emp.entitlements:
                before = emp.entitlements
                state = state.with_employee(emp.without_entitlement(eff.application_id))
                emp = state.employee(emp.employee_id)
                changes.append(
                    _change(
                        emp.employee_id,
                        "entitlements",
                        ",".join(before),
                        ",".join(emp.entitlements),
                    )
                )
        elif isinstance(eff, RevokeEntitlementGlobally):
            for e in state.employees:
                if eff.application_id in e.entitlements:
                    before = e.entitlements
                    updated = e.without_entitlement(eff.application_id)
                    state = state.with_employee(updated)
                    changes.append(
                        _change(
                            e.employee_id,
                            "entitlements",
                            ",".join(before),
                            ",".join(updated.entitlements),
                        )
                    )
            if emp is not None:
                emp = state.employee(emp.employee_id)
        elif isinstance(eff, GrantEntitlement):
            if emp is None:
                raise RuntimeError("grant_entitlement requires an employee payload")
            if eff.application_id not in emp.entitlements:
                before = emp.entitlements
                state = state.with_employee(emp.with_entitlement(eff.application_id))
                emp = state.employee(emp.employee_id)
                changes.append(
                    _change(
                        emp.employee_id,
                        "entitlements",
                        ",".join(before),
                        ",".join(emp.entitlements),
                    )
                )
        elif isinstance(eff, RequireSecurityReview):
            if emp is None or payload.application_id is None:
                raise RuntimeError("require_security_review requires employee and application")
            pair = (emp.employee_id, payload.application_id)
            if pair not in state.review_required:
                state = state.model_copy(
                    update={"review_required": tuple(sorted((*state.review_required, pair)))}
                )
                changes.append(
                    _change(emp.employee_id, "review_required", "", f"{pair[0]}|{pair[1]}")
                )
                notes.append("security_review_required")
        elif isinstance(eff, EnableRule | DisableRule):
            target = eff.rule_id
            new_status = "active" if isinstance(eff, EnableRule) else "inactive"
            current = dict(state.rule_status_overrides).get(target)
            if current != new_status:
                overrides = {**dict(state.rule_status_overrides), target: new_status}
                state = state.model_copy(
                    update={"rule_status_overrides": tuple(sorted(overrides.items()))}
                )
                changes.append(_change(f"rule:{target}", "status", current or "base", new_status))
    return state, changes, notes


def _hard_invariants(state: WorldState, world: WorldSpec) -> str | None:
    apps = set(world.app_map())
    known_emp = {e.employee_id for e in world.employees}
    if len(state.employees) != len(world.employees):
        return "employee roster changed"
    for e in state.employees:
        if e.employee_id not in known_emp:
            return f"unknown employee {e.employee_id}"
        if e.status == "inactive" and e.entitlements:
            return f"inactive employee {e.employee_id} retains entitlements"
        for a in e.entitlements:
            if a not in apps:
                return f"entitlement references unknown application {a}"
    for r in state.requests:
        if r.employee_id not in known_emp or r.application_id not in apps:
            return f"request {r.request_id} references unknown entities"
    return None


def _review_required(world: WorldSpec, state: WorldState, payload: _Payload) -> bool:
    """Review gates are rule-mediated configuration read at grant time.

    Any ACTIVE rule with trigger access_granted and a RequireSecurityReview
    effect whose conditions match the current state/payload gates the grant.
    Accumulated pairs in state.review_required persist as well.
    """
    if payload.employee_id is None:
        return False
    if (payload.employee_id, payload.application_id) in state.review_required:
        return True
    overrides = dict(state.rule_status_overrides)
    for r in world.rules:
        if r.trigger != "access_granted":
            continue
        if effective_status(r, overrides) != "active":
            continue
        if not any(isinstance(e, RequireSecurityReview) for e in r.effects):
            continue
        if _check_conditions(r.conditions, state, world, payload):
            return True
    return False


def apply_action(
    world: WorldSpec,
    state: WorldState,
    action: Action,
    *,
    _approved_request_id: str | None = None,
    _origin_action_name: str | None = None,
) -> TransitionResult:
    """Apply one business action through validation, direct effect, and cascade."""
    if isinstance(action, FinishTask):
        return TransitionResult(state=state, events=(), status="ok", note="finish")

    new_state = state
    events: list[Event] = []
    fired: list[str] = []
    seq = 0
    rules_by_id = world.rule_map()

    def emit(
        cause: str,
        rule_id: str | None,
        origin: int,
        depth: int,
        changes: list[FieldChange],
        payload_: _Payload,
        ev_note: str | None,
    ) -> None:
        nonlocal seq
        ev = Event(
            seq=seq,
            cause="action" if cause == "action" else "rule",
            action_name=(
                (_origin_action_name or type(action).__name__) if cause == "action" else None
            ),
            rule_id=rule_id,
            rule_content_hash=(
                rules_by_id[rule_id].content_hash() if rule_id is not None else None
            ),
            origin_seq=origin,
            depth=depth,
            changes=tuple(changes),
            note=ev_note,
            employee_id=payload_.employee_id,
            application_id=payload_.application_id,
        )
        seq += 1
        events.append(ev)

    # ---- validate and apply direct effect ----------------------------------
    trigger_type: str | None = None
    payload: _Payload

    def run_cascade(trigger: str, event_payload: _Payload) -> str | None:
        """Apply one deterministic rule pass for a single business event."""
        nonlocal new_state

        eligible: list[ScheduledFiring] = []
        for rule in world.rules:
            if rule.trigger != trigger:
                continue
            eligible.append(ScheduledFiring(rule, origin_seq=events[-1].seq, depth=1))
            if len(eligible) > MAX_FIRINGS:
                return "cascade bound exceeded; action rolled back"
        processed = 0
        for firing in order_firings(eligible):
            rule = rules_by_id[firing.rule.rule_id]
            if effective_status(rule, dict(new_state.rule_status_overrides)) != "active":
                continue
            processed += 1
            if processed > MAX_FIRINGS or firing.depth > MAX_DEPTH:
                return "cascade bound exceeded; action rolled back"
            if _check_conditions(rule.conditions, new_state, world, event_payload):
                new_state, changes, notes = _apply_effects(
                    rule.effects, new_state, world, event_payload
                )
                if not changes:
                    continue
                fired.append(rule.rule_id)
                emit(
                    "rule",
                    rule.rule_id,
                    firing.origin_seq,
                    firing.depth,
                    changes,
                    event_payload,
                    ";".join(notes) or None,
                )
        return None

    try:
        if isinstance(action, GrantApplicationAccess):
            emp = new_state.employee(action.employee_id)
            app = world.app_map()[action.application_id]
            payload = _Payload(emp.employee_id, app.application_id)
            if emp.status == "inactive":
                return TransitionResult(
                    state=state, events=(), status="rejected", error="inactive_employee"
                )
            if app.application_id in emp.entitlements:
                return TransitionResult(state=state, events=(), status="ok", note="already_held")
            if _approved_request_id is not None:
                req = new_state.request(_approved_request_id)
                if (
                    req.status != "approved"
                    or req.employee_id != emp.employee_id
                    or req.application_id != app.application_id
                ):
                    return TransitionResult(
                        state=state, events=(), status="rejected", error="invalid_approved_request"
                    )
            review_needed = _approved_request_id is None and _review_required(
                world, new_state, payload
            )
            if review_needed:
                rid = f"REQ-{len(new_state.requests) + 1:04d}"
                rec = AccessRequestRecord(
                    request_id=rid,
                    employee_id=emp.employee_id,
                    application_id=app.application_id,
                    status="pending",
                )
                new_state = new_state.with_request(rec)
                emit(
                    "action",
                    None,
                    0,
                    0,
                    [_change(rid, "status", "-", "pending")],
                    payload,
                    "request_created",
                )
                err = _hard_invariants(new_state, world)
                if err is not None:
                    return TransitionResult(
                        state=state, events=(), status="invariant_failed", error=err
                    )
                return TransitionResult(
                    state=new_state, events=tuple(events), status="ok", note="request_created"
                )
            before = emp.entitlements
            new_state = new_state.with_employee(emp.with_entitlement(app.application_id))
            emp2 = new_state.employee(emp.employee_id)
            emit(
                "action",
                None,
                0,
                0,
                [
                    _change(
                        emp.employee_id,
                        "entitlements",
                        ",".join(before),
                        ",".join(emp2.entitlements),
                    )
                ],
                payload,
                "granted",
            )
            trigger_type = "access_granted"
        elif isinstance(action, RevokeApplicationAccess):
            emp = new_state.employee(action.employee_id)
            if action.application_id not in emp.entitlements:
                return TransitionResult(state=state, events=(), status="ok", note="not_held")
            world.app_map()[action.application_id]
            payload = _Payload(emp.employee_id, action.application_id)
            before = emp.entitlements
            new_state = new_state.with_employee(emp.without_entitlement(action.application_id))
            emp2 = new_state.employee(emp.employee_id)
            emit(
                "action",
                None,
                0,
                0,
                [
                    _change(
                        emp.employee_id,
                        "entitlements",
                        ",".join(before),
                        ",".join(emp2.entitlements),
                    )
                ],
                payload,
                "revoked",
            )
            trigger_type = "access_revoked"
        elif isinstance(action, AssignRole):
            emp = new_state.employee(action.employee_id)
            role = world.role_map()[action.role_id]
            payload = _Payload(emp.employee_id, None)
            if emp.role_id == role.role_id:
                return TransitionResult(state=state, events=(), status="ok", note="already_role")
            new_state = new_state.with_employee(emp.model_copy(update={"role_id": role.role_id}))
            emit(
                "action",
                None,
                0,
                0,
                [_change(emp.employee_id, "role_id", emp.role_id, role.role_id)],
                payload,
                "assigned",
            )
            trigger_type = "role_assigned"
        elif isinstance(action, CompleteOnboarding):
            emp = new_state.employee(action.employee_id)
            payload = _Payload(emp.employee_id, None)
            if emp.status != "onboarding":
                return TransitionResult(
                    state=state, events=(), status="rejected", error="not_onboarding"
                )
            new_state = new_state.with_employee(emp.model_copy(update={"status": "active"}))
            emit(
                "action",
                None,
                0,
                0,
                [_change(emp.employee_id, "status", "onboarding", "active")],
                payload,
                "onboarded",
            )
            trigger_type = "onboarding_completed"
        elif isinstance(action, OffboardEmployee):
            emp = new_state.employee(action.employee_id)
            payload = _Payload(emp.employee_id, None)
            if emp.status == "inactive":
                return TransitionResult(
                    state=state, events=(), status="rejected", error="already_inactive"
                )
            before = emp.entitlements
            new_state = new_state.with_employee(
                emp.model_copy(update={"status": "inactive", "entitlements": ()})
            )
            cancelled = [
                r
                for r in new_state.requests
                if r.employee_id == emp.employee_id and r.status == "pending"
            ]
            if cancelled:
                cancelled_ids = {r.request_id for r in cancelled}
                new_state = new_state.model_copy(
                    update={
                        "requests": tuple(
                            r.model_copy(update={"status": "cancelled"})
                            if r.request_id in cancelled_ids
                            else r
                            for r in new_state.requests
                        )
                    }
                )
            changes = [
                _change(emp.employee_id, "status", emp.status, "inactive"),
            ]
            if before:
                changes.append(_change(emp.employee_id, "entitlements", ",".join(before), ""))
            changes.extend(
                _change(r.request_id, "status", "pending", "cancelled") for r in cancelled
            )
            emit(
                "action",
                None,
                0,
                0,
                changes,
                payload,
                "offboarded",
            )
            trigger_type = "employee_offboarded"
        elif isinstance(action, ApproveRequest):
            req = new_state.request(action.request_id)
            emp = new_state.employee(req.employee_id)
            if emp.status == "inactive":
                return TransitionResult(
                    state=state, events=(), status="rejected", error="inactive_employee"
                )
            if req.status == "approved":
                return TransitionResult(
                    state=state, events=(), status="ok", note="already_approved"
                )
            if req.status != "pending":
                return TransitionResult(
                    state=state, events=(), status="rejected", error=f"request_{req.status}"
                )
            payload = _Payload(req.employee_id, req.application_id)
            new_state = new_state.model_copy(
                update={
                    "requests": tuple(
                        r.model_copy(update={"status": "approved"})
                        if r.request_id == req.request_id
                        else r
                        for r in new_state.requests
                    )
                }
            )
            emit(
                "action",
                None,
                0,
                0,
                [_change(req.request_id, "status", "pending", "approved")],
                payload,
                "approved",
            )
            cascade_error = run_cascade("approval_granted", payload)
            if cascade_error is not None:
                return TransitionResult(
                    state=state, events=(), status="invariant_failed", error=cascade_error
                )
            err = _hard_invariants(new_state, world)
            if err is not None:
                return TransitionResult(
                    state=state, events=(), status="invariant_failed", error=err
                )

            grant_result = apply_action(
                world,
                new_state,
                GrantApplicationAccess(
                    employee_id=req.employee_id, application_id=req.application_id
                ),
                _approved_request_id=req.request_id,
                _origin_action_name=type(action).__name__,
            )
            if grant_result.status != "ok":
                return TransitionResult(
                    state=state,
                    events=(),
                    status=grant_result.status,
                    error=grant_result.error,
                )
            event_offset = len(events)
            events.extend(
                event.model_copy(
                    update={
                        "seq": event.seq + event_offset,
                        "origin_seq": event.origin_seq + event_offset,
                    }
                )
                for event in grant_result.events
            )
            fired.extend(grant_result.fired_rule_ids)
            return TransitionResult(
                state=grant_result.state,
                events=tuple(events),
                status="ok",
                fired_rule_ids=tuple(fired),
                note=events[0].note,
            )
        else:  # pragma: no cover - closed union
            raise AssertionError("unhandled action")
    except KeyError as exc:
        return TransitionResult(
            state=state, events=(), status="rejected", error=f"unknown reference: {exc}"
        )

    cascade_error = run_cascade(trigger_type, payload)
    if cascade_error is not None:
        return TransitionResult(
            state=state, events=(), status="invariant_failed", error=cascade_error
        )

    err = _hard_invariants(new_state, world)
    if err is not None:
        return TransitionResult(state=state, events=(), status="invariant_failed", error=err)

    return TransitionResult(
        state=new_state,
        events=tuple(events),
        status="ok",
        fired_rule_ids=tuple(fired),
        note=events[0].note if events else None,
    )
