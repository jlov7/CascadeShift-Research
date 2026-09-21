"""Shift taxonomy: operator to shift-class mapping (preregistered)."""

from __future__ import annotations

SHIFT_CLASSES: tuple[str, ...] = (
    "threshold",
    "rule_activation",
    "rule_order",
    "cross_entity_dependency",
    "side_effect_expansion",
    "approval_policy",
    "mapping_entitlement",
)

_OPERATOR_CLASS: dict[str, str] = {
    "change_numeric_threshold": "threshold",
    "enable_rule": "rule_activation",
    "disable_rule": "rule_activation",
    "add_template_side_effect": "side_effect_expansion",
    "change_rule_priority": "rule_order",
    "change_application_risk": "mapping_entitlement",
    "change_required_clearance": "mapping_entitlement",
    "change_approval_mode": "approval_policy",
    "change_bundle_membership": "approval_policy",
    "add_conflict_pair": "cross_entity_dependency",
    "remove_conflict_pair": "cross_entity_dependency",
    "change_role_entitlement": "side_effect_expansion",
}


def class_of(operator_kind: str) -> str:
    return _OPERATOR_CLASS[operator_kind]


def class_members() -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {c: [] for c in SHIFT_CLASSES}
    for op, cls in _OPERATOR_CLASS.items():
        out[cls].append(op)
    return {c: tuple(ops) for c, ops in out.items()}
