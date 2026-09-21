"""Deterministic lexical BM25-style retrieval requirements (RT-01..RT-03)."""

from cascadeshift.engine.world import WorldSpec
from cascadeshift.retrieval.index import RetrievalIndex, tokenize
from cascadeshift.retrieval.relevance import retrieval_metrics
from tests.unit.test_engine import build_cascade_world


def test_tokenize_is_deterministic_and_lowercase():
    assert tokenize("Payroll Hub REVOKES!") == ["payroll", "hub", "revokes"]


def test_search_requires_query_or_filter():
    w = build_cascade_world()
    idx = RetrievalIndex(w.rules)
    resp = idx.search(query="", event_type=None, entity_type=None)
    assert "error" in resp and resp["error"] == "query_required"


def test_search_rejects_wildcards():
    w = build_cascade_world()
    idx = RetrievalIndex(w.rules)
    for bad in ["*", "", "?", "**"]:
        resp = idx.search(query=bad)
        assert "error" in resp


def test_search_topk_bounded_at_8():
    w = build_cascade_world()
    idx = RetrievalIndex(w.rules)
    resp = idx.search(query="rule")
    assert len(resp["results"]) <= 8
    assert resp["truncated"] in {True, False}


def test_search_filters_by_event_type():
    w = build_cascade_world()
    idx = RetrievalIndex(w.rules)
    resp = idx.search(query="clearance", event_type="access_granted")
    assert all(r["trigger"] == "access_granted" for r in resp["results"])
    empty = idx.search(query="clearance", event_type="approval_granted", _test_pool=w.rules)
    assert isinstance(empty, dict)


def test_search_ranking_deterministic_ties_by_id(monkeypatch):
    w = build_cascade_world()
    idx = RetrievalIndex(w.rules)
    monkeypatch.setattr(idx, "_score", lambda _rule_id, _tokens: 1.0)
    a = idx.search(query="payroll entitlement")
    b = idx.search(query="payroll entitlement")
    assert a == b
    ids = [r["rule_id"] for r in a["results"]]
    assert ids == sorted(ids)
    # exact tie-break proof: deliberately identical scores resolve ascending.
    scores = [r["_score"] for r in a["results"]]
    assert scores == sorted(scores, reverse=True)


def test_inspect_rule_returns_full_record_or_missing():
    w = build_cascade_world()
    be_index = RetrievalIndex(w.rules)
    full = be_index.inspect("R-0001")
    assert full["rule_id"] == "R-0001"
    assert "effects" in full and "provenance" in full
    miss = be_index.inspect("R-9999")
    assert "error" in miss


def test_dependencies_bounded_one_hop():
    w = build_cascade_world()
    idx = RetrievalIndex(w.rules)
    deps = idx.dependencies("APP-PAY")
    assert len(deps.get("neighbors", [])) <= 8
    ids = [n["id"] for n in deps.get("neighbors", [])]
    assert ids == sorted(ids)


def test_schema_endpoint_lists_fields_only():
    w = build_cascade_world()
    idx = RetrievalIndex(w.rules)
    sch = idx.schema_of("employee")
    assert "fields" in sch and "clearance" in sch["fields"]
    bad = idx.schema_of("ufo")
    assert "error" in bad


def test_canonical_json_is_byte_stable():
    w = build_cascade_world()
    idx = RetrievalIndex(w.rules)
    r1 = idx.search(query="risk")
    r2 = idx.search(query="risk")
    import json

    c1 = json.dumps(r1, sort_keys=True, separators=(",", ":"))
    c2 = json.dumps(r2, sort_keys=True, separators=(",", ":"))
    assert c1 == c2


def test_world_fixture_type_available():
    assert isinstance(build_cascade_world(), WorldSpec)


def test_closure_metrics_are_deterministic_and_call_indexed():
    metrics = retrieval_metrics(
        returned=("R-0009", "R-0001", "R-0001"),
        inspected=("R-0009", "R-0002"),
        closure=frozenset({"R-0001", "R-0002"}),
        returned_call_indexes=(1, 2, 2),
        inspected_call_indexes=(3, 4),
    )

    assert metrics == {
        "returned_rule_precision": 0.5,
        "returned_rule_recall": 0.5,
        "inspected_rule_precision": 0.5,
        "inspected_rule_recall": 0.5,
        "causal_closure_size": 2,
        "first_relevant_returned_discovery_call": 2,
        "first_relevant_inspected_discovery_call": 4,
    }


def test_empty_closure_keeps_undefined_recall_and_precision_null():
    metrics = retrieval_metrics(
        returned=(),
        inspected=(),
        closure=frozenset(),
        returned_call_indexes=(),
        inspected_call_indexes=(),
    )

    assert metrics == {
        "returned_rule_precision": None,
        "returned_rule_recall": None,
        "inspected_rule_precision": None,
        "inspected_rule_recall": None,
        "causal_closure_size": 0,
        "first_relevant_returned_discovery_call": None,
        "first_relevant_inspected_discovery_call": None,
    }
