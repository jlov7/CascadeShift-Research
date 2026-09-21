"""Retrieval bounds against the real frozen 128-rule catalog (RT-01..RT-03).

The small hand-built fixtures in ``test_retrieval.py`` cannot exercise top-k
truncation or filter selectivity; these tests use ``worlds/baseline/world.yaml``.
"""

from __future__ import annotations

import itertools
import json

import pytest

from cascadeshift.engine.world_io import load_world
from cascadeshift.retrieval.index import TOP_K, RetrievalIndex
from cascadeshift.retrieval.tools import DiscoveryTools

W = "worlds/baseline/world.yaml"


@pytest.fixture(scope="module")
def catalog():
    world = load_world(W)
    assert len(world.rules) == 128
    return world.rules


@pytest.fixture(scope="module")
def tools(catalog):
    return DiscoveryTools(catalog)


def test_top_k_is_eight_and_broad_queries_truncate(catalog):
    index = RetrievalIndex(catalog)
    assert TOP_K == 8
    broad = index.search(query="access application employee role risk request")
    assert len(broad["results"]) == 8
    assert broad["truncated"] is True
    assert broad["matched"] > 8


def test_every_tool_response_is_bounded_at_eight_items(tools, catalog):
    vocabulary = sorted({token for rule in catalog for token in rule.title.lower().split()})
    calls = [("search_rules", {"query": word}) for word in vocabulary[:40]]
    calls += [("inspect_dependencies", {"identifier": rule.rule_id}) for rule in catalog[:20]]
    calls += [
        ("search_rules", {"query": "risk", "event_type": trigger})
        for trigger in sorted({rule.trigger for rule in catalog})
    ]
    for name, args in calls:
        payload = json.loads(tools.call(name, args))
        items = payload.get("results", payload.get("neighbors", []))
        assert len(items) <= 8, (name, args, len(items))


def test_event_type_filter_is_selective_on_the_real_catalog(catalog):
    index = RetrievalIndex(catalog)
    triggers = sorted({rule.trigger for rule in catalog})
    assert len(triggers) > 1
    for trigger in triggers:
        response = index.search(query="risk clearance access", event_type=trigger)
        assert all(item["trigger"] == trigger for item in response["results"]), trigger
    unfiltered = index.search(query="risk clearance access")["matched"]
    filtered = index.search(query="risk clearance access", event_type=triggers[0])["matched"]
    assert filtered < unfiltered


def test_ranking_ties_break_by_ascending_rule_id(catalog):
    index = RetrievalIndex(catalog)
    response = index.search(query="access")
    scores = [item["_score"] for item in response["results"]]
    ids = [item["rule_id"] for item in response["results"]]
    for (score_a, id_a), (score_b, id_b) in itertools.pairwise(zip(scores, ids, strict=True)):
        assert score_a >= score_b
        if score_a == score_b:
            assert id_a < id_b


def test_search_is_byte_stable_across_calls(tools):
    first = tools.call("search_rules", {"query": "payroll clearance"})
    second = tools.call("search_rules", {"query": "payroll clearance"})
    assert first == second
    assert json.loads(first)  # canonical JSON
