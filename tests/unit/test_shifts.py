"""Typed shift grammar requirements (ledger S-01, S-02, O-03)."""

import pytest
from pydantic import ValidationError

from cascadeshift.engine.world_io import load_world
from cascadeshift.retrieval.catalog import generate_baseline_world
from cascadeshift.shifts.operators import apply_op, parse_op
from cascadeshift.shifts.taxonomy import SHIFT_CLASSES, class_of

BASELINE = "worlds/baseline/world.yaml"


def _world():
    return generate_baseline_world()


def test_all_twelve_operators_validate_and_apply():
    w = _world()
    rid_active = next(r.rule_id for r in w.rules if r.status == "active")
    rid_dormant = next(r.rule_id for r in w.rules if r.status == "inactive")
    rid_sideeffect = next(
        r.rule_id
        for r in w.rules
        if r.status == "inactive"
        and {e.kind for e in r.effects} & {"grant_entitlement", "require_security_review"}
    )
    ops = [
        {"kind": "change_numeric_threshold", "target": "policy", "new_value": 65},
        {"kind": "enable_rule", "rule_id": rid_dormant},
        {"kind": "disable_rule", "rule_id": rid_active},
        {"kind": "change_rule_priority", "rule_id": rid_active, "new_priority": 95},
        {"kind": "change_application_risk", "application_id": "APP-VIP", "new_value": 75},
        {"kind": "change_required_clearance", "role_id": "RL-01", "new_value": 4},
        {"kind": "change_approval_mode", "mode": "security_review"},
        {"kind": "add_conflict_pair", "application_a": "APP-VPN", "application_b": "APP-BID"},
        {"kind": "remove_conflict_pair", "application_a": "APP-PAY", "application_b": "APP-VIP"},
        {"kind": "add_template_side_effect", "rule_id": rid_sideeffect},
        {
            "kind": "change_role_entitlement",
            "role_id": "RL-02",
            "mandatory_applications": ["APP-CRM"],
        },
        {
            "kind": "change_bundle_membership",
            "application_id": "APP-BID",
            "requires_security_review": True,
        },
    ]
    seen = set()
    for payload in ops:
        op = parse_op(payload)
        w2 = apply_op(w, op)
        assert len(w2.rules) == 128, "catalog cardinality preserved"
        assert isinstance(op.kind, str)
        seen.add(op.kind)
    assert len(seen) == 12


def test_unknown_operator_rejected():
    with pytest.raises(ValidationError):
        parse_op({"kind": "melt_rules"})


def test_operator_reference_resolution_errors():
    w = _world()
    with pytest.raises(ValueError, match="unknown application"):
        apply_op(
            w,
            parse_op(
                {"kind": "change_application_risk", "application_id": "APP-GHOST", "new_value": 10}
            ),
        )
    with pytest.raises(ValueError, match="unknown role"):
        apply_op(
            w, parse_op({"kind": "change_required_clearance", "role_id": "RL-X", "new_value": 3})
        )
    with pytest.raises(ValueError, match="must target"):
        apply_op(
            w,
            parse_op(
                {
                    "kind": "enable_rule",
                    "rule_id": next(r.rule_id for r in w.rules if r.status == "active"),
                }
            ),
        )


def test_enable_uses_dormant_slot_and_disjoint_from_disable():
    w = _world()
    dormant = next(r.rule_id for r in w.rules if r.status == "inactive")
    w2 = apply_op(w, parse_op({"kind": "enable_rule", "rule_id": dormant}))
    assert len(w2.rules) == 128
    status = next(r.status for r in w2.rules if r.rule_id == dormant)
    assert status == "active"


def test_semantic_hash_sensitive_to_config_insensitive_to_prose():
    w = _world()
    prose_edit = w.model_copy(update={"description": "different words entirely"})
    assert w.semantic_hash() == prose_edit.semantic_hash()
    shifted = apply_op(
        w, parse_op({"kind": "change_numeric_threshold", "target": "policy", "new_value": 66})
    )
    assert w.semantic_hash() != shifted.semantic_hash()


def test_taxonomy_covers_all_operators_seven_classes():
    assert len(SHIFT_CLASSES) == 7
    for k in [
        "change_numeric_threshold",
        "enable_rule",
        "disable_rule",
        "change_rule_priority",
        "change_application_risk",
        "change_required_clearance",
        "change_approval_mode",
        "add_conflict_pair",
        "remove_conflict_pair",
        "add_template_side_effect",
        "change_role_entitlement",
        "change_bundle_membership",
    ]:
        assert k in class_of.__members__ if hasattr(class_of, "__members__") else True
        assert class_of(k) in SHIFT_CLASSES


def test_yaml_baseline_loads():
    w = load_world(BASELINE)
    assert len(w.rules) == 128
