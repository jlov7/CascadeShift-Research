"""Closed typed shift grammar: 12 operators preserving catalog cardinality."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from cascadeshift.domain.entities import ConflictPair
from cascadeshift.engine.world import WorldSpec


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChangeNumericThreshold(_Op):
    kind: Literal["change_numeric_threshold"] = "change_numeric_threshold"
    target: Literal["policy"]
    new_value: int = Field(ge=0, le=100)


class EnableRule(_Op):
    kind: Literal["enable_rule"] = "enable_rule"
    rule_id: str


class DisableRule(_Op):
    kind: Literal["disable_rule"] = "disable_rule"
    rule_id: str


class ChangeRulePriority(_Op):
    kind: Literal["change_rule_priority"] = "change_rule_priority"
    rule_id: str
    new_priority: int = Field(ge=0, le=100)


class ChangeApplicationRisk(_Op):
    kind: Literal["change_application_risk"] = "change_application_risk"
    application_id: str
    new_value: int = Field(ge=0, le=100)


class ChangeRequiredClearance(_Op):
    kind: Literal["change_required_clearance"] = "change_required_clearance"
    role_id: str
    new_value: int = Field(ge=1, le=5)


class ChangeApprovalMode(_Op):
    """security_review activates the blanket confirmation rule; auto retires it.

    Kept as a distinct operator for taxonomy fidelity; implementation is
    rule-mediated so the change is discoverable through the catalog.
    """

    kind: Literal["change_approval_mode"] = "change_approval_mode"
    mode: Literal["auto", "security_review"]


class AddConflictPair(_Op):
    kind: Literal["add_conflict_pair"] = "add_conflict_pair"
    application_a: str
    application_b: str


class RemoveConflictPair(_Op):
    kind: Literal["remove_conflict_pair"] = "remove_conflict_pair"
    application_a: str
    application_b: str


class AddTemplateSideEffect(_Op):
    """Activate a dormant slot whose effects expand side behavior."""

    kind: Literal["add_template_side_effect"] = "add_template_side_effect"
    rule_id: str


class ChangeRoleEntitlement(_Op):
    kind: Literal["change_role_entitlement"] = "change_role_entitlement"
    role_id: str
    mandatory_applications: tuple[str, ...]


class ChangeBundleMembership(_Op):
    """Toggles the per-application confirmation gate rule (dormant slot)."""

    kind: Literal["change_bundle_membership"] = "change_bundle_membership"
    application_id: str
    requires_security_review: bool


ShiftOp = Annotated[
    ChangeNumericThreshold
    | EnableRule
    | DisableRule
    | ChangeRulePriority
    | ChangeApplicationRisk
    | ChangeRequiredClearance
    | ChangeApprovalMode
    | AddConflictPair
    | RemoveConflictPair
    | AddTemplateSideEffect
    | ChangeRoleEntitlement
    | ChangeBundleMembership,
    Field(discriminator="kind"),
]

_ADAPTER: TypeAdapter[ShiftOp] = TypeAdapter(ShiftOp)


def parse_op(payload: dict[str, object]) -> ShiftOp:
    return _ADAPTER.validate_python(payload)


def apply_op(world: WorldSpec, op: ShiftOp) -> WorldSpec:
    """Apply one operator; returns a new WorldSpec. References must resolve.

    Catalog cardinality is invariant: operators never add or remove rules.
    """
    if isinstance(op, ChangeNumericThreshold):
        return world.model_copy(
            update={"policy": world.policy.model_copy(update={"risk_threshold": op.new_value})}
        )
    if isinstance(op, EnableRule | AddTemplateSideEffect):
        rules = world.rule_map()
        target = rules.get(op.rule_id)
        if target is None:
            raise ValueError(f"unknown rule {op.rule_id}")
        if op.rule_id not in {r.rule_id for r in world.rules if r.status == "inactive"}:
            raise ValueError(
                f"enable/side-effect ops must target a dormant (inactive) slot, "
                f"{op.rule_id} has status {target.status!r}"
            )
        if isinstance(op, AddTemplateSideEffect):
            kinds = {e.kind for e in target.effects}
            if not kinds & {"grant_entitlement", "require_security_review"}:
                raise ValueError(
                    "add_template_side_effect must target a dormant slot with grant/review effects"
                )
        updated = [r for r in world.rules]
        idx = next(i for i, r in enumerate(updated) if r.rule_id == op.rule_id)
        updated[idx] = updated[idx].model_copy(update={"status": "active"})
        return world.model_copy(update={"rules": tuple(updated)})
    if isinstance(op, DisableRule):
        rules = world.rule_map()
        target = rules.get(op.rule_id)
        if target is None:
            raise ValueError(f"unknown rule {op.rule_id}")
        if target.status != "active":
            raise ValueError("disable_rule must target an active rule")
        updated = list(world.rules)
        idx = next(i for i, r in enumerate(updated) if r.rule_id == op.rule_id)
        updated[idx] = updated[idx].model_copy(update={"status": "inactive"})
        return world.model_copy(update={"rules": tuple(updated)})
    if isinstance(op, ChangeRulePriority):
        rules = world.rule_map()
        if op.rule_id not in rules:
            raise ValueError(f"unknown rule {op.rule_id}")
        updated = list(world.rules)
        idx = next(i for i, r in enumerate(updated) if r.rule_id == op.rule_id)
        updated[idx] = updated[idx].model_copy(update={"priority": op.new_priority})
        return world.model_copy(update={"rules": tuple(updated)})
    if isinstance(op, ChangeApplicationRisk):
        apps = world.app_map()
        if op.application_id not in apps:
            raise ValueError(f"unknown application {op.application_id}")
        new_apps = tuple(
            a.model_copy(update={"risk_score": op.new_value})
            if a.application_id == op.application_id
            else a
            for a in world.applications
        )
        return world.model_copy(update={"applications": new_apps})
    if isinstance(op, ChangeRequiredClearance):
        roles = world.role_map()
        if op.role_id not in roles:
            raise ValueError(f"unknown role {op.role_id}")
        new_roles = tuple(
            r.model_copy(update={"clearance_required": op.new_value})
            if r.role_id == op.role_id
            else r
            for r in world.roles
        )
        return world.model_copy(update={"roles": new_roles})
    if isinstance(op, ChangeApprovalMode):
        return _toggle_rule(world, "SEC-POL-160", active=(op.mode == "security_review"))
    if isinstance(op, AddConflictPair):
        known_apps = set(world.app_map())
        missing = {op.application_a, op.application_b} - known_apps
        if missing:
            raise ValueError(f"unknown application(s): {sorted(missing)}")
        pair = ConflictPair(application_a=op.application_a, application_b=op.application_b).pair
        existing = world.conflict_set()
        if pair in existing:
            raise ValueError("conflict pair already present")
        cp = ConflictPair(application_a=pair[0], application_b=pair[1])
        return world.model_copy(update={"conflict_pairs": (*world.conflict_pairs, cp)})
    if isinstance(op, RemoveConflictPair):
        pair = ConflictPair(application_a=op.application_a, application_b=op.application_b).pair
        existing = world.conflict_set()
        if pair not in existing:
            raise ValueError("conflict pair not present")
        kept = tuple(cp for cp in world.conflict_pairs if cp.pair != pair)
        return world.model_copy(update={"conflict_pairs": kept})
    if isinstance(op, ChangeRoleEntitlement):
        roles = world.role_map()
        if op.role_id not in roles:
            raise ValueError(f"unknown role {op.role_id}")
        unknown = set(op.mandatory_applications) - set(world.app_map())
        if unknown:
            raise ValueError(f"unknown application(s): {sorted(unknown)}")
        new_roles = tuple(
            r.model_copy(
                update={"mandatory_applications": tuple(sorted(set(op.mandatory_applications)))}
            )
            if r.role_id == op.role_id
            else r
            for r in world.roles
        )
        return world.model_copy(update={"roles": new_roles})
    if isinstance(op, ChangeBundleMembership):
        return _toggle_rule(
            world,
            f"RVW-POL-{op.application_id}",
            active=op.requires_security_review,
        )
    raise AssertionError("unhandled operator")  # pragma: no cover


def _toggle_rule(world: WorldSpec, source: str, active: bool) -> WorldSpec:
    """Enable/disable the rule carrying the given provenance source code."""
    matches = [r for r in world.rules if r.provenance.source == source]
    if not matches:
        raise ValueError(f"no rule with provenance source {source}")
    rid = matches[0].rule_id
    current = next(r for r in world.rules if r.rule_id == rid)
    new_status = "active" if active else "inactive"
    if current.status == new_status:
        raise ValueError(f"rule {rid} already {new_status}")
    updated = list(world.rules)
    idx = next(i for i, r in enumerate(updated) if r.rule_id == rid)
    updated[idx] = updated[idx].model_copy(update={"status": new_status})
    return world.model_copy(update={"rules": tuple(updated)})
