"""Paired development corpus + confirmatory anchors (ledger P-01, P-02)."""

import json

import pytest

from cascadeshift.engine.world_io import load_world
from cascadeshift.retrieval.catalog import generate_baseline_world
from cascadeshift.shifts.generator import generate_confirmatory_split
from cascadeshift.shifts.operators import parse_op
from cascadeshift.tasks.corpus import (
    _Candidate,
    _select_exact_candidates,
    generate_confirmatory_anchors,
    generate_development_split,
)
from cascadeshift.tasks.oracle import solve

BASELINE = "worlds/baseline/world.yaml"


def test_confirmatory_anchor_count_and_families():
    anchors = generate_confirmatory_anchors()
    assert len(anchors) == 20
    fams = {a.family for a in anchors}
    assert len(fams) == 6
    ids = [a.task_id for a in anchors]
    assert len(set(ids)) == 20
    assert all(a.parent_task_id is None for a in anchors)


def test_every_anchor_solvable_on_baseline():
    w = load_world(BASELINE)
    for t in generate_confirmatory_anchors():
        res = solve(w, t)
        assert res.status == "solved", f"{t.task_id} unsolvable"
        assert 0 < len(res.plan) <= 8


@pytest.mark.slow
def test_fixed_confirmatory_seed_fills_quotas_and_is_deterministic():
    """Regression: the frozen seed must satisfy all blind allocation constraints."""
    baseline = load_world(BASELINE)
    anchors = list(generate_confirmatory_anchors())

    def generate_signature() -> tuple[tuple[str, ...], tuple[str, ...]]:
        cases, worlds, _ = generate_confirmatory_split(
            baseline,
            anchors,
            seed=20260822,
            n_preserving=15,
            n_invalidating=15,
        )
        assert len(cases) == 30
        assert sum(case.plan_effect == "plan_preserving" for case in cases) == 15
        assert sum(case.plan_effect == "plan_invalidating" for case in cases) == 15
        per_parent: dict[str, int] = {}
        for case in cases:
            per_parent[case.parent_task_id] = per_parent.get(case.parent_task_id, 0) + 1
        assert set(per_parent) == {anchor.task_id for anchor in anchors}
        assert max(per_parent.values()) <= 2
        assert {case.family for case in cases} == {anchor.family for anchor in anchors}
        assert len({world.semantic_hash() for world in worlds}) == len(worlds)
        return (
            tuple(json.dumps(case.model_dump(mode="json"), sort_keys=True) for case in cases),
            tuple(world.content_hash() for world in worlds),
        )

    assert generate_signature() == generate_signature()


def test_exact_allocator_enforces_strata_parent_coverage_and_semantic_uniqueness():
    world = load_world(BASELINE)
    anchors = list(generate_confirmatory_anchors())
    op = parse_op({"kind": "disable_rule", "rule_id": "R-001"})
    pool = [
        _Candidate(anchor, op, world, "plan_preserving", f"p-{index}", None)
        for index, anchor in enumerate(anchors)
    ] + [
        _Candidate(anchor, op, world, "plan_invalidating", f"i-{index}", "alt")
        for index, anchor in enumerate(anchors[:15])
    ]

    selected = _select_exact_candidates(
        pool,
        [anchor.task_id for anchor in anchors],
        n_preserving=15,
        n_invalidating=15,
        max_per_parent=2,
        require_all_parents=True,
    )

    assert selected is not None
    assert len(selected) == 30
    assert sum(item.effect == "plan_preserving" for item in selected) == 15
    assert sum(item.effect == "plan_invalidating" for item in selected) == 15
    assert len({item.semantic for item in selected}) == 30
    parent_counts: dict[str, int] = {}
    for item in selected:
        parent_counts[item.parent.task_id] = parent_counts.get(item.parent.task_id, 0) + 1
    assert set(parent_counts) == {anchor.task_id for anchor in anchors}
    assert max(parent_counts.values()) == 2


def test_exact_allocator_rejects_semantic_collisions():
    world = load_world(BASELINE)
    anchors = list(generate_confirmatory_anchors())
    op = parse_op({"kind": "disable_rule", "rule_id": "R-001"})
    pool = [_Candidate(anchor, op, world, "plan_preserving", "shared", None) for anchor in anchors]

    assert (
        _select_exact_candidates(
            pool,
            [anchor.task_id for anchor in anchors],
            n_preserving=20,
            n_invalidating=0,
            max_per_parent=2,
            require_all_parents=True,
        )
        is None
    )


def test_exact_allocator_preserves_parent_semantic_candidate_identity():
    world = load_world(BASELINE)
    first, second = generate_confirmatory_anchors()[:2]
    op = parse_op({"kind": "disable_rule", "rule_id": "R-001"})
    pool = [
        _Candidate(first, op, world, "plan_invalidating", "shared", "alt"),
        _Candidate(second, op, world, "plan_preserving", "shared", None),
        _Candidate(second, op, world, "plan_preserving", "second-only", None),
    ]

    selected = _select_exact_candidates(
        pool,
        [first.task_id, second.task_id],
        n_preserving=1,
        n_invalidating=1,
        max_per_parent=2,
        require_all_parents=True,
    )

    assert selected is not None
    assert {(item.parent.task_id, item.effect, item.semantic) for item in selected} == {
        (first.task_id, "plan_invalidating", "shared"),
        (second.task_id, "plan_preserving", "second-only"),
    }


def test_dev_split_shape_and_strata():
    split = generate_development_split()
    baselines = split["baselines"]
    cases = split["cases"]
    assert len(baselines) == 8
    assert len(cases) >= 8
    effects = {c.plan_effect for c in cases}
    assert {"plan_preserving", "plan_invalidating"} <= effects
    parent_ids = {b.task_id for b in baselines}
    for c in cases:
        assert c.parent_task_id in parent_ids
        assert c.plan_effect in {"plan_preserving", "plan_invalidating"}
    # every dev baseline has >= 1 paired shifted variant
    for b in baselines:
        assert any(c.parent_task_id == b.task_id for c in cases)
    # every case solvable on its own shifted world
    w0 = load_world(BASELINE)
    worlds = {w.world_id: w for w in split["worlds"]}
    for c in cases:
        assert c.shifted_world_hash is not None
        assert c.alternative_plan_hash is None or isinstance(c.alternative_plan_hash, str)
    del w0, worlds


def test_dev_generation_is_deterministic():
    a = generate_development_split()
    b = generate_development_split()
    assert [x.task_id for x in a["baselines"]] == [x.task_id for x in b["baselines"]]
    assert [x.model_dump_json() for x in a["cases"]] == [x.model_dump_json() for x in b["cases"]]
    ha = sorted(w.content_hash() for w in a["worlds"])
    hb = sorted(w.content_hash() for w in b["worlds"])
    assert ha == hb


def test_baseline_world_fixture_matches_file():
    assert generate_baseline_world().content_hash() == load_world(BASELINE).content_hash()
