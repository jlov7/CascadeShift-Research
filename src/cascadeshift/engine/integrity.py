"""Independent integrity checks for immutable transition observations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cascadeshift.domain.actions import (
    Action,
    ApproveRequest,
    AssignRole,
    CompleteOnboarding,
    GrantApplicationAccess,
    OffboardEmployee,
    RevokeApplicationAccess,
)
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.world import WorldSpec

if TYPE_CHECKING:
    from cascadeshift.engine.transition import TransitionResult


ChangeIdentity = tuple[str, str]
ChangeValues = tuple[str, str]

_EMPLOYEE_FIELDS = frozenset({"role_id", "status", "clearance", "risk_load", "entitlements"})
_ACTION_NAMES = frozenset(
    {
        "GrantApplicationAccess",
        "RevokeApplicationAccess",
        "AssignRole",
        "CompleteOnboarding",
        "OffboardEmployee",
        "ApproveRequest",
    }
)
_ACTION_TRIGGERS = {
    "GrantApplicationAccess": frozenset({"access_granted"}),
    "RevokeApplicationAccess": frozenset({"access_revoked"}),
    "AssignRole": frozenset({"role_assigned"}),
    "CompleteOnboarding": frozenset({"onboarding_completed"}),
    "OffboardEmployee": frozenset({"employee_offboarded"}),
    "ApproveRequest": frozenset({"approval_granted", "access_granted"}),
}


def _value(field: str, value: object) -> str:
    if field == "entitlements":
        return ",".join(value)  # type: ignore[arg-type]
    return str(value)


def _changed_fields(before: WorldState, after: WorldState) -> dict[ChangeIdentity, ChangeValues]:
    changed: dict[ChangeIdentity, ChangeValues] = {}
    for field, identifier in (("employees", "employee_id"), ("requests", "request_id")):
        old_items = {
            getattr(item, identifier): item.model_dump() for item in getattr(before, field)
        }
        new_items = {getattr(item, identifier): item.model_dump() for item in getattr(after, field)}
        for item_id in old_items.keys() | new_items.keys():
            old = old_items.get(item_id, {})
            new = new_items.get(item_id, {})
            if field == "requests" and not old:
                changed[(item_id, "status")] = ("-", _value("status", new["status"]))
                continue
            for name in old.keys() | new.keys():
                if old.get(name) != new.get(name):
                    before_value = "-" if name not in old else _value(name, old[name])
                    after_value = "-" if name not in new else _value(name, new[name])
                    changed[(item_id, name)] = (before_value, after_value)

    old_reviews = set(before.review_required)
    new_reviews = set(after.review_required)
    for employee_id, application_id in new_reviews - old_reviews:
        changed[(employee_id, "review_required")] = ("", f"{employee_id}|{application_id}")
    for employee_id, application_id in old_reviews - new_reviews:
        changed[(employee_id, "review_required")] = (f"{employee_id}|{application_id}", "")

    old_overrides = dict(before.rule_status_overrides)
    new_overrides = dict(after.rule_status_overrides)
    for rule_id in old_overrides.keys() | new_overrides.keys():
        old_status = old_overrides.get(rule_id)
        new_status = new_overrides.get(rule_id)
        if old_status != new_status:
            changed[(f"rule:{rule_id}", "status")] = (
                old_status or "base",
                new_status or "base",
            )
    return changed


def _field_values(state: WorldState) -> dict[ChangeIdentity, str]:
    values: dict[ChangeIdentity, str] = {}
    for employee in state.employees:
        dumped = employee.model_dump()
        for field in _EMPLOYEE_FIELDS:
            values[(employee.employee_id, field)] = _value(field, dumped[field])
    for request in state.requests:
        values[(request.request_id, "status")] = request.status
    for employee_id, application_id in state.review_required:
        values[(employee_id, "review_required")] = f"{employee_id}|{application_id}"
    for rule_id, status in state.rule_status_overrides:
        values[(f"rule:{rule_id}", "status")] = status
    return values


def _valid_identity(
    identity: ChangeIdentity,
    before_values: dict[ChangeIdentity, str],
    after_values: dict[ChangeIdentity, str],
) -> bool:
    entity_id, field = identity
    if entity_id.startswith("rule:"):
        return field == "status"
    if field == "review_required":
        return (
            (entity_id, field) in before_values
            or (entity_id, field) in after_values
            or any(key[0] == entity_id for key in before_values | after_values)
        )
    if (entity_id, field) in before_values or (entity_id, field) in after_values:
        return True
    return field == "status" and entity_id.startswith("REQ-")


def _missing_value(identity: ChangeIdentity) -> str:
    if identity[0].startswith("rule:"):
        return "base"
    if identity[1] == "review_required":
        return ""
    return "-"


def _reconstruct_action(result: TransitionResult) -> Action | None:
    action_event = next((event for event in result.events if event.cause == "action"), None)
    if action_event is None or action_event.action_name is None:
        return None

    employee_id = action_event.employee_id
    application_id = action_event.application_id
    if action_event.action_name == "GrantApplicationAccess":
        if employee_id is None or application_id is None:
            return None
        return GrantApplicationAccess(employee_id=employee_id, application_id=application_id)
    if action_event.action_name == "RevokeApplicationAccess":
        if employee_id is None or application_id is None:
            return None
        return RevokeApplicationAccess(employee_id=employee_id, application_id=application_id)
    if action_event.action_name == "AssignRole":
        if employee_id is None:
            return None
        role_change = next(
            (change for change in action_event.changes if change.field == "role_id"), None
        )
        if role_change is None:
            return None
        return AssignRole(employee_id=employee_id, role_id=role_change.after)
    if action_event.action_name == "CompleteOnboarding":
        if employee_id is None:
            return None
        return CompleteOnboarding(employee_id=employee_id)
    if action_event.action_name == "OffboardEmployee":
        if employee_id is None:
            return None
        return OffboardEmployee(employee_id=employee_id)
    if action_event.action_name == "ApproveRequest":
        status_change = next(
            (
                change
                for change in action_event.changes
                if change.field == "status" and change.entity_id.startswith("REQ-")
            ),
            None,
        )
        if status_change is None:
            return None
        return ApproveRequest(request_id=status_change.entity_id)
    return None


def validate_transition_integrity(
    world: WorldSpec, before: WorldState, result: TransitionResult
) -> tuple[str, ...]:
    """Report state changes not attributable to a returned immutable event."""
    if result.status != "ok":
        non_ok_errors: list[str] = []
        if result.state != before:
            non_ok_errors.append("non-ok transition changed state")
        if result.events:
            non_ok_errors.append("non-ok transition emitted events")
        if result.fired_rule_ids:
            non_ok_errors.append("non-ok transition fired rules")
        return tuple(non_ok_errors)
    observed = _changed_fields(before, result.state)
    before_values = _field_values(before)
    after_values = _field_values(result.state)
    errors: list[str] = []
    expected_seq = list(range(len(result.events)))
    if [event.seq for event in result.events] != expected_seq:
        errors.append("event sequence is not contiguous from zero")

    action_names: set[str] = set()
    rule_ids: list[str] = []
    current = dict(before_values)
    traced: set[ChangeIdentity] = set()
    actions_by_seq: dict[int, str] = {}
    rules = world.rule_map()

    for event in result.events:
        if not event.changes:
            errors.append(f"event {event.seq} has no state changes")
        if event.cause == "action":
            if (
                event.action_name not in _ACTION_NAMES
                or event.rule_id is not None
                or event.rule_content_hash is not None
                or event.origin_seq != event.seq
                or event.depth != 0
            ):
                errors.append(f"invalid action provenance at event {event.seq}")
            if event.action_name is not None:
                action_names.add(event.action_name)
            if event.action_name is not None:
                actions_by_seq[event.seq] = event.action_name
        else:
            origin_action = actions_by_seq.get(event.origin_seq)
            rule = rules.get(event.rule_id or "")
            if (
                event.action_name is not None
                or event.rule_id is None
                or origin_action is None
                or event.origin_seq >= event.seq
                or event.depth != 1
                or rule is None
                or event.rule_content_hash != rule.content_hash()
                or rule.trigger not in _ACTION_TRIGGERS.get(origin_action, frozenset())
            ):
                errors.append(f"invalid rule provenance at event {event.seq}")
            if event.rule_id is not None:
                rule_ids.append(event.rule_id)

        identities_in_event: set[ChangeIdentity] = set()
        for change in event.changes:
            identity = (change.entity_id, change.field)
            if identity in identities_in_event:
                errors.append(
                    f"duplicate field change at event {event.seq}: "
                    f"{change.entity_id}.{change.field}"
                )
                continue
            identities_in_event.add(identity)
            if not _valid_identity(identity, before_values, after_values):
                errors.append(f"invalid event identity: {change.entity_id}.{change.field}")
                continue
            expected_before = current.get(identity, _missing_value(identity))
            if change.before != expected_before:
                errors.append(
                    f"event before mismatch: {change.entity_id}.{change.field} expected "
                    f"{expected_before!r}, got {change.before!r}"
                )
                continue
            if change.before == change.after:
                errors.append(f"event change has no effect: {change.entity_id}.{change.field}")
                continue
            current[identity] = change.after
            traced.add(identity)

    if len(action_names) > 1:
        errors.append("multiple action names in one transition trace")
    if tuple(rule_ids) != result.fired_rule_ids:
        errors.append("fired rule ids do not match rule events")

    for identity, (_before_value, after_value) in sorted(observed.items()):
        if identity not in traced:
            errors.append(f"unexplained state mutation: {identity[0]}.{identity[1]}")
            continue
        if current.get(identity) != after_value:
            errors.append(
                f"event after mismatch: {identity[0]}.{identity[1]} expected {after_value!r}, "
                f"got {current.get(identity)!r}"
            )
    for identity in sorted(traced):
        expected_after = after_values.get(identity, _missing_value(identity))
        if current.get(identity) != expected_after:
            errors.append(
                f"event after mismatch: {identity[0]}.{identity[1]} expected {expected_after!r}, "
                f"got {current.get(identity)!r}"
            )

    if result.events:
        action = _reconstruct_action(result)
        if action is None:
            errors.append("transition action cannot be reconstructed")
        else:
            # Structural tracing proves that every mutation was recorded. Replaying the
            # reconstructed action additionally proves that the selected rules, their
            # order, and their effects agree with the deterministic engine semantics.
            from cascadeshift.engine.transition import apply_action

            expected = apply_action(world, before, action)
            if expected != result:
                errors.append("transition result diverges from deterministic replay")
    return tuple(errors)
