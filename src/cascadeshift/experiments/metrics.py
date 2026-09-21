"""Metric aggregation: episodes -> report-ready statistics payload."""

from __future__ import annotations

from typing import Any

from cascadeshift.agents.protocol import EpisodeRecord
from cascadeshift.experiments.statistics import (
    cluster_bootstrap_ci,
    freshness_interaction_cells,
    stale_harm_on_invalidating,
    stratum_did,
)
from cascadeshift.reporting.report import select_trajectory


def cascade_depths_from_episodes(episodes: list[EpisodeRecord]) -> dict[str, int]:
    """Maximum recorded causal-event depth for each case.

    Event depth is the engine's causal-chain depth. Fired-rule counts are not
    a depth measure because sibling firings can occur at the same depth.
    """
    depths: dict[str, int] = {}
    for episode in episodes:
        depth = max((event.depth for event in episode.events), default=0)
        depths[episode.case_id] = max(depths.get(episode.case_id, 0), depth)
    return depths


def _side_summary(episodes: list[EpisodeRecord], condition: str) -> dict[str, Any]:
    total = [episode for episode in episodes if episode.condition == condition]
    eligible = [episode for episode in total if episode.provider_error is None]
    csts = sum(1 for episode in eligible if episode.verdict.csts)
    silent = sum(1 for episode in eligible if episode.silent_violation)
    n = len(eligible)
    return {
        "episodes": len(total),
        "provider_failures": len(total) - n,
        "excluded_provider_failures": len(total) - n,
        "csts": {"numerator": csts, "denominator": n, "rate": csts / n if n else None},
        "silent_violations": {
            "numerator": silent,
            "denominator": n,
            "rate": silent / n if n else None,
        },
        "usage": {
            "mean_total_tokens": sum(episode.usage.total_tokens for episode in eligible) / n
            if n
            else None,
            "mean_total_tool_calls": sum(episode.usage.total_tool_calls for episode in eligible) / n
            if n
            else None,
            "mean_business_actions": sum(episode.usage.business_actions for episode in eligible) / n
            if n
            else None,
            "mean_discovery_calls": sum(episode.usage.discovery_calls for episode in eligible) / n
            if n
            else None,
        },
    }


def _nullable_mean(values: list[float | int | None]) -> dict[str, float | int | None]:
    defined = [value for value in values if value is not None]
    return {
        "mean": sum(defined) / len(defined) if defined else None,
        "defined_episodes": len(defined),
    }


def _retrieval_summary(episodes: list[EpisodeRecord], condition: str) -> dict[str, Any]:
    total = [episode for episode in episodes if episode.condition == condition]
    measured = [
        episode
        for episode in total
        if episode.provider_error is None and episode.retrieval.causal_closure_computed
    ]
    fields = (
        "returned_rule_precision",
        "returned_rule_recall",
        "inspected_rule_precision",
        "inspected_rule_recall",
        "causal_closure_size",
        "first_relevant_returned_discovery_call",
        "first_relevant_inspected_discovery_call",
    )
    summary: dict[str, Any] = {
        "episodes": len(total),
        "provider_failures": sum(episode.provider_error is not None for episode in total),
        "metric_episodes": len(measured),
    }
    for field in fields:
        summary[field] = _nullable_mean([getattr(episode.retrieval, field) for episode in measured])
    return summary


def _plan_strata(episodes: list[EpisodeRecord], case_effect: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for effect in ("plan_preserving", "plan_invalidating"):
        cases = sorted(case for case, value in case_effect.items() if value == effect)
        sel = [episode for episode in episodes if episode.case_id in cases]
        out[effect] = {
            "cases": len(cases),
            "episodes": len(sel),
            "provider_failures": sum(episode.provider_error is not None for episode in sel),
        }
    return out


def build_stats_payload(
    *,
    baseline_episodes: list[EpisodeRecord],
    shifted_episodes: list[EpisodeRecord],
    shifted_hashes: set[str],
    case_effect: dict[str, str],
    cascade_depths: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Primary estimand + secondaries from paired episode sets."""
    all_eps = [*baseline_episodes, *shifted_episodes]
    dids = freshness_interaction_cells(all_eps, shifted_hashes=shifted_hashes)
    primary = cluster_bootstrap_ci(dids)
    payload: dict[str, Any] = {
        "primary": primary,
        "stratum_plan_preserving": stratum_did(
            all_eps, "plan_preserving", case_effect, shifted_hashes
        ),
        "stratum_plan_invalidating": stratum_did(
            all_eps, "plan_invalidating", case_effect, shifted_hashes
        ),
        "stale_harm": stale_harm_on_invalidating(all_eps, case_effect),
        "raw": {},
    }
    for cond in ("surface", "frozen_discovery", "live_discovery"):
        payload["raw"][cond] = {
            "baseline": _side_summary(baseline_episodes, cond),
            "shifted": _side_summary(shifted_episodes, cond),
        }
    payload["raw"]["retrieval"] = {
        cond: {
            "baseline": _retrieval_summary(baseline_episodes, cond),
            "shifted": _retrieval_summary(shifted_episodes, cond),
        }
        for cond in ("surface", "frozen_discovery", "live_discovery")
    }
    payload["raw"]["plan_strata"] = _plan_strata(shifted_episodes, case_effect)
    depths = cascade_depths or {}
    payload["trajectory"] = select_trajectory(all_eps, case_effect, depths)
    return payload
