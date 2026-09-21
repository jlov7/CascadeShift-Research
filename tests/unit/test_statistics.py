"""Statistics requirements on synthetic episodes (ledger ST-01, M-01)."""

from cascadeshift.agents.protocol import (
    EpisodeRecord,
    RetrievalLog,
    UsageRecord,
)
from cascadeshift.engine.events import Event
from cascadeshift.experiments.metrics import build_stats_payload, cascade_depths_from_episodes
from cascadeshift.experiments.statistics import (
    cluster_bootstrap_ci,
    condition_csts,
    episode_csts,
    freshness_interaction_cells,
    silent_violation_rate,
    stale_harm_on_invalidating,
    stratum_did,
    within_parent_means,
)
from cascadeshift.tasks.models import Verdict


def _rec(
    case: str, parent: str, cond: str, csts: bool, whash: str = "W0", silent: bool = False
) -> EpisodeRecord:
    v = Verdict(goal_satisfied=csts, hard_constraints_satisfied=csts, violated_codes=(), csts=csts)
    return EpisodeRecord(
        episode_id=f"{case}-{cond}",
        split="development",
        case_id=case,
        parent_task_id=parent,
        family="F1_grant_preserve",
        condition=cond,  # type: ignore[arg-type]
        rollout_seed_id="s",
        world_id="w",
        world_hash=whash,
        task_text_hash="t",
        system_prompt_hash="p",
        usage=UsageRecord(),
        claimed_success=True,
        verdict=v,
        claim_outcome_match=csts,
        silent_violation=silent,
    )


def test_condition_csts_counts():
    eps = [
        _rec("S1", "P1", "surface", True),
        _rec("S1", "P1", "surface", False),
        _rec("S2", "P2", "live_discovery", True, whash="W1"),
    ]
    k, n, rate = condition_csts(eps, "surface")
    assert (k, n) == (1, 2) and abs(rate - 0.5) < 1e-9


def test_episode_csts_excludes_provider_failures():
    failed = _rec("S3", "P3", "surface", False).model_copy(
        update={"provider_error": "provider_error:http_503"}
    )
    assert episode_csts(
        [_rec("S1", "P1", "surface", True), _rec("S2", "P2", "surface", False), failed]
    ) == (1, 2, 1, 0.5)


def test_silent_violation_rate_visible():
    eps = [
        _rec("S1", "P1", "frozen_discovery", False, silent=True),
        _rec("S2", "P2", "frozen_discovery", True),
    ]
    k, n, rate = silent_violation_rate(eps, "frozen_discovery")
    assert k == 1 and n == 2


def test_within_parent_means_nested_repeats_not_independent():
    eps = []
    for _ in range(3):  # three repeats of the same case
        eps.append(_rec("S9", "P7", "surface", True))
        eps.append(_rec("S9", "P7", "surface", False))
    cells = within_parent_means(eps)
    assert cells["P7"].csts["surface"] == 0.5  # repeat mean, not pooled count


def test_freshness_interaction_positive_direction_detected():
    eps = []
    # Parent P1: baseline C1=C2=1; shifted C1=0 C2=1 => DiD = +1
    for rep in range(3):
        eps.append(_rec(f"B{rep}", "P1", "frozen_discovery", True, whash="W0"))
        eps.append(_rec(f"B{rep}", "P1", "live_discovery", True, whash="W0"))
        eps.append(_rec(f"S{rep}", "P1", "frozen_discovery", False, whash="WS"))
        eps.append(_rec(f"S{rep}", "P1", "live_discovery", True, whash="WS"))
    dids = freshness_interaction_cells(eps, shifted_hashes={"WS"})
    assert dids["P1"] == [1.0]


def test_cluster_bootstrap_ci_structure():
    data = {f"P{i}": [float(i % 2)] for i in range(20)}
    ci = cluster_bootstrap_ci(data, b=500)
    assert ci["n_clusters"] == 20
    assert 0.0 <= ci["lo"] <= ci["point"] <= ci["hi"] <= 1.0
    # determinism
    ci2 = cluster_bootstrap_ci(data, b=500)
    assert ci == ci2


def test_empty_ci_is_explicitly_non_estimable():
    ci = cluster_bootstrap_ci({})
    assert ci == {
        "n_clusters": 0,
        "point": None,
        "mean": None,
        "lo": None,
        "hi": None,
        "b": 10000,
        "seed": 20260825,
        "confidence_level": 0.95,
        "estimable": False,
    }


def test_stratum_and_stale_harm_helpers_run():
    eps = [
        _rec("X1", "P1", "surface", True, whash="WS"),
        _rec("X1", "P1", "frozen_discovery", False, whash="WS"),
        _rec("X1", "P1", "live_discovery", True, whash="WS"),
        _rec("X1b", "P1", "frozen_discovery", True, whash="W0"),
        _rec("X1b", "P1", "live_discovery", True, whash="W0"),
    ]
    effect_map = {"X1": "plan_invalidating"}
    s = stratum_did(eps, "plan_invalidating", effect_map, {"WS"})
    assert s["parents"] == 1
    assert s["confidence_level"] == 0.90
    h = stale_harm_on_invalidating(eps, effect_map)
    assert h["n_clusters"] == 1
    assert h["confidence_level"] == 0.90


def test_stratum_did_excludes_other_shifted_plan_effects_but_keeps_baseline():
    eps = [
        _rec("wanted", "P1", "frozen_discovery", True, whash="W0"),
        _rec("wanted", "P1", "live_discovery", True, whash="W0"),
        _rec("wanted", "P1", "frozen_discovery", False, whash="WS"),
        _rec("wanted", "P1", "live_discovery", True, whash="WS"),
        _rec("other", "P1", "frozen_discovery", True, whash="WS"),
        _rec("other", "P1", "live_discovery", False, whash="WS"),
    ]
    result = stratum_did(
        eps,
        "plan_invalidating",
        {"wanted": "plan_invalidating", "other": "plan_preserving"},
        {"WS"},
    )
    assert result["parents"] == 1
    assert result["point"] == 1.0


def test_did_excludes_provider_failures_and_incomplete_parent_cells():
    good = [
        _rec("good", "P-good", "frozen_discovery", True, whash="W0"),
        _rec("good", "P-good", "live_discovery", True, whash="W0"),
        _rec("good", "P-good", "frozen_discovery", False, whash="WS"),
        _rec("good", "P-good", "live_discovery", True, whash="WS"),
    ]
    provider_failed = _rec("failed", "P-failed", "live_discovery", True, whash="WS").model_copy(
        update={"provider_error": "provider_error:http_503"}
    )
    incomplete = [
        _rec("incomplete", "P-incomplete", "frozen_discovery", True, whash="W0"),
        _rec("incomplete", "P-incomplete", "frozen_discovery", False, whash="WS"),
        _rec("incomplete", "P-incomplete", "live_discovery", True, whash="WS"),
    ]
    episodes = [
        *good,
        _rec("failed", "P-failed", "frozen_discovery", True, whash="W0"),
        _rec("failed", "P-failed", "live_discovery", True, whash="W0"),
        _rec("failed", "P-failed", "frozen_discovery", False, whash="WS"),
        provider_failed,
        *incomplete,
    ]

    assert freshness_interaction_cells(episodes, shifted_hashes={"WS"}) == {"P-good": [1.0]}


def test_non_estimable_stratum_did_is_explicit_when_a_provider_error_removes_a_cell():
    episodes = [
        _rec("wanted", "P1", "frozen_discovery", True, whash="W0"),
        _rec("wanted", "P1", "live_discovery", True, whash="W0"),
        _rec("wanted", "P1", "frozen_discovery", False, whash="WS"),
        _rec("wanted", "P1", "live_discovery", True, whash="WS").model_copy(
            update={"provider_error": "provider_error:http_503"}
        ),
    ]

    result = stratum_did(episodes, "plan_invalidating", {"wanted": "plan_invalidating"}, {"WS"})

    assert result["parents"] == 0
    assert result["estimable"] is False
    assert result["point"] is None


def test_cascade_depth_uses_event_chain_depth_not_fired_rule_count():
    episode = _rec("S1", "P1", "surface", True).model_copy(
        update={
            "fired_rules": ("R1", "R2", "R3"),
            "events": (
                Event(seq=1, cause="action", action_name="grant", origin_seq=1, depth=0),
                Event(seq=2, cause="rule", rule_id="R1", origin_seq=1, depth=1),
                Event(seq=3, cause="rule", rule_id="R2", origin_seq=1, depth=1),
            ),
        }
    )
    assert cascade_depths_from_episodes([episode]) == {"S1": 1}


def test_stats_payload_groups_retrieval_metrics_by_condition_and_world_side():
    retrieval = RetrievalLog(
        causal_closure_rule_ids=("R-0001", "R-0002"),
        causal_closure_computed=True,
        returned_rule_precision=0.5,
        returned_rule_recall=0.5,
        inspected_rule_precision=None,
        inspected_rule_recall=None,
        causal_closure_size=2,
        first_relevant_returned_discovery_call=2,
        first_relevant_inspected_discovery_call=None,
    )
    baseline = _rec("B1", "P1", "surface", True).model_copy(update={"retrieval": retrieval})
    shifted = _rec("S1", "P1", "surface", True, whash="WS").model_copy(
        update={"retrieval": retrieval}
    )

    payload = build_stats_payload(
        baseline_episodes=[baseline],
        shifted_episodes=[shifted],
        shifted_hashes={"WS"},
        case_effect={"S1": "plan_preserving"},
    )

    summary = payload["raw"]["retrieval"]["surface"]["baseline"]
    assert summary["metric_episodes"] == 1
    assert summary["returned_rule_precision"] == {"mean": 0.5, "defined_episodes": 1}
    assert summary["inspected_rule_precision"] == {"mean": None, "defined_episodes": 0}
    assert summary["causal_closure_size"] == {"mean": 2.0, "defined_episodes": 1}
