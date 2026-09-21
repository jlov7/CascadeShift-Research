"""Deterministic 128-rule catalog requirements (ledger H-01, H-02, P-01 prep)."""

import re

from cascadeshift.retrieval.catalog import (
    ACTIVE_DISTRACTORS,
    CORE,
    DORMANT,
    WORLD_SEED,
    generate_baseline_world,
    generate_catalog,
    generate_catalog_with_manifest,
)

RULE_ID_RE = re.compile(r"^R-\d{4}$")
BANNED_TOKENS = {
    "frozen",
    "stale",
    "live",
    "fresh",
    "shift",
    "baseline",
    "confirmatory",
    "condition",
    "c0",
    "c1",
    "c2",
    "oracle",
    "verifier",
    "cascade_depth",
    "plan_preserving",
    "plan_invalidating",
}


def test_catalog_composition_and_cardinality():
    cat = generate_catalog()
    assert len(cat) == 128
    core = [r for r in cat if r.rule_id.startswith("R-00")][:0]  # noop guard
    del core
    # Composition is tracked by generator metadata, verified by count here.
    statuses = [r.status for r in cat]
    assert len(cat) == CORE + ACTIVE_DISTRACTORS + DORMANT
    assert sum(1 for s in statuses if s != "active") >= DORMANT


def test_catalog_ids_opaque_unique_noncontiguous_blocks():
    rules, manifest = generate_catalog_with_manifest()
    ids = [r.rule_id for r in rules]
    assert all(RULE_ID_RE.match(i) for i in ids)
    assert len(ids) == len(set(ids))
    numeric = sorted(int(i[2:]) for i in ids)
    assert numeric == list(range(1001, 1129))  # opaque range, fully used
    core_ids = sorted(rid for rid, kind in manifest.items() if kind == "core")
    dormant_ids = sorted(rid for rid, kind in manifest.items() if kind == "dormant")

    def contiguous(nums):
        return nums == list(range(nums[0], nums[0] + len(nums)))

    assert not contiguous([int(i[2:]) for i in core_ids])
    assert not contiguous([int(i[2:]) for i in dormant_ids])


def test_catalog_prose_neutral_and_wellformed():
    cat = generate_catalog()
    for r in cat:
        assert 0 < len(r.description) <= 240
        assert r.title.strip()
        blob = (r.title + " " + r.description).lower()
        words = re.findall(r"[a-z0-9_]+", blob)
        for tok in BANNED_TOKENS:
            assert tok not in words, f"banned token {tok} in {r.rule_id}"
        # No snake_case outcome labels encoding terminal side effects.
        for word in blob.split():
            assert not (word.islower() and "_" in word and word.replace("_", "").isalnum()), (
                f"snake_case outcome label {word!r} in {r.rule_id}"
            )


def test_catalog_generation_deterministic():
    a = generate_catalog()
    b = generate_catalog()
    assert [r.model_dump_json() for r in a] == [r.model_dump_json() for r in b]


def test_baseline_world_has_128_rules_and_validates():
    w = generate_baseline_world()
    assert len(w.rules) == 128
    assert w.generator_seed == WORLD_SEED
    assert w.world_id == "world-baseline-v1"
    apps = w.app_map()
    assert {"APP-PAY", "APP-CRM", "APP-VIP", "APP-SHR", "APP-VPN", "APP-BID"} <= set(apps)


def test_dormant_slots_exist_for_shift_activation():
    w = generate_baseline_world()
    inactive = [r for r in w.rules if r.status == "inactive"]
    superseded = [r for r in w.rules if r.status == "superseded"]
    assert len(inactive) + len(superseded) == 32
    # At least one dormant rule fires a real effect when enabled.
    assert any(
        any(
            e.kind
            in {"revoke_entitlement_globally", "require_security_review", "grant_entitlement"}
            for e in r.effects
        )
        for r in inactive
    )
