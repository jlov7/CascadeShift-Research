"""C1/C2 byte-equivalence and prompt hygiene (ledger A-02, A-03)."""

import json

from cascadeshift.agents.conditions import condition_spec, make_tools, tool_schemas_bytes
from cascadeshift.agents.prompts import SYSTEM_PROMPT, assert_neutral, task_prompt
from cascadeshift.engine.world_io import load_world
from cascadeshift.retrieval.tools import DiscoveryTools
from cascadeshift.shifts.operators import apply_op, parse_op
from cascadeshift.tasks.corpus import _dev_baselines

W = "worlds/baseline/world.yaml"
BANNED = ("frozen", "stale", " live ", "fresh", "shift", "baseline", "confirmatory")


def test_tool_schemas_byte_identical_c1_c2():
    c1 = condition_spec("frozen_discovery")
    c2 = condition_spec("live_discovery")
    assert tool_schemas_bytes(c1) == tool_schemas_bytes(c2)
    assert len(tool_schemas_bytes(c1)) > 100


def test_baseline_responses_byte_identical_between_backends():
    w = load_world(W)
    c1_tools = make_tools(condition_spec("frozen_discovery"), w, w)
    c2_tools = make_tools(condition_spec("live_discovery"), w, w)
    assert c1_tools is not None and c2_tools is not None
    queries = [
        {
            "tool": "search_rules",
            "args": {"query": "payroll review", "event_type": "access_granted"},
        },
        {"tool": "search_rules", "args": {"query": "APP-CRM confirmation"}},
        {"tool": "search_rules", "args": {"query": "risk"}},
        {"tool": "inspect_rule", "args": {"rule_id": "R-1001"}},
        {"tool": "inspect_dependencies", "args": {"identifier": "APP-PAY"}},
        {"tool": "inspect_schema", "args": {"entity_type": "employee"}},
    ]
    for q in queries:
        a = c1_tools.call(q["tool"], q["args"])  # type: ignore[arg-type]
        b = c2_tools.call(q["tool"], q["args"])  # type: ignore[arg-type]
        assert a == b, f"backend divergence on baseline for {q}"
        json.loads(a)  # canonical JSON


def test_shifted_world_diverges_live_from_frozen():
    w = load_world(W)
    shifted = apply_op(
        w,
        parse_op(
            {
                "kind": "change_bundle_membership",
                "application_id": "APP-CRM",
                "requires_security_review": True,
            }
        ),
    )
    c1_tools = make_tools(condition_spec("frozen_discovery"), w, shifted)
    c2_tools = make_tools(condition_spec("live_discovery"), w, shifted)
    q = {
        "tool": "inspect_rule",
        "args": {
            "rule_id": next(
                r.rule_id for r in shifted.rules if r.provenance.source == "RVW-POL-APP-CRM"
            )
        },
    }
    a = c1_tools.call(q["tool"], q["args"])  # type: ignore[arg-type]
    b = c2_tools.call(q["tool"], q["args"])  # type: ignore[arg-type]
    assert json.loads(a)["status"] == "inactive"
    assert json.loads(b)["status"] == "active"


def test_prompts_and_schemas_contain_no_condition_hints():
    w = load_world(W)
    tools = DiscoveryTools(w.rules)
    blob = SYSTEM_PROMPT + json.dumps(tools.schemas())
    for t in _dev_baselines()[:4]:
        blob += task_prompt(t)
        assert_neutral(task_prompt(t))
    lowered = blob.lower()
    for tok in [
        "frozen",
        "stale",
        "freshness",
        "condition",
        "c0",
        "c1",
        "c2",
        "oracle",
        "verifier",
    ]:
        words = lowered.split()
        assert tok not in words, tok


def test_assert_neutral_rejects_label():
    import pytest

    with pytest.raises(ValueError):
        assert_neutral("you are the frozen discovery agent")


def test_confirmatory_anchor_prompts_carry_no_condition_hints():
    """Substring scan over every model-visible confirmatory string, not just dev prompts."""
    from cascadeshift.tasks.corpus import generate_confirmatory_anchors

    w = load_world(W)
    blobs = [SYSTEM_PROMPT, json.dumps(DiscoveryTools(w.rules).schemas())]
    anchors = list(generate_confirmatory_anchors())
    assert len(anchors) == 20
    blobs.extend(task_prompt(t) for t in anchors)
    hints = (
        "frozen",
        "stale",
        "fresh",
        "shift",
        "baseline",
        "confirmatory",
        "oracle",
        "verifier",
        "hidden",
        "snapshot",
        "world v1",
        "condition c",
        "c0 ",
        "c1 ",
        "c2 ",
    )
    for blob in blobs:
        lowered = blob.lower()
        for hint in hints:
            assert hint not in lowered, (hint, blob[:120])
