"""Environment-side causal-rule closure for retrieval evaluation (M-02).

Computed by the engine; never exposed to agents through tools.
"""

from __future__ import annotations

from typing import TypedDict

from cascadeshift.domain.state import WorldState
from cascadeshift.engine.transition import TransitionResult, apply_action
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec
from cascadeshift.tasks.oracle import Plan, solve


class RetrievalMetrics(TypedDict):
    returned_rule_precision: float | None
    returned_rule_recall: float | None
    inspected_rule_precision: float | None
    inspected_rule_recall: float | None
    causal_closure_size: int
    first_relevant_returned_discovery_call: int | None
    first_relevant_inspected_discovery_call: int | None


def causal_closure(world: WorldSpec, task: TaskSpec, plan: Plan) -> frozenset[str]:
    """Rules that fire while replaying the oracle plan on this world."""
    state: WorldState = world.initial_state()
    fired: set[str] = set()
    for action in plan:
        res: TransitionResult = apply_action(world, state, action)
        if res.status != "ok":
            break
        state = res.state
        fired.update(res.fired_rule_ids)
    return frozenset(fired)


def oracle_causal_closure(world: WorldSpec, task: TaskSpec) -> frozenset[str]:
    """Return the deterministic oracle plan's causal rule closure, if solvable."""
    result = solve(world, task)
    if result.status != "solved":
        return frozenset()
    return causal_closure(world, task, result.plan)


def retrieval_metrics(
    returned: tuple[str, ...],
    inspected: tuple[str, ...],
    closure: frozenset[str],
    *,
    returned_call_indexes: tuple[int, ...],
    inspected_call_indexes: tuple[int, ...],
) -> RetrievalMetrics:
    """Measure retrieval against the hidden closure without duplicate inflation."""
    if len(returned) != len(returned_call_indexes):
        raise ValueError("returned rule ids and call indexes must align")
    if len(inspected) != len(inspected_call_indexes):
        raise ValueError("inspected rule ids and call indexes must align")

    returned_unique = tuple(dict.fromkeys(returned))
    inspected_unique = tuple(dict.fromkeys(inspected))
    returned_hits = tuple(rule_id for rule_id in returned_unique if rule_id in closure)
    inspected_hits = tuple(rule_id for rule_id in inspected_unique if rule_id in closure)

    def first_relevant(rule_ids: tuple[str, ...], indexes: tuple[int, ...]) -> int | None:
        return next(
            (index for rule_id, index in zip(rule_ids, indexes, strict=True) if rule_id in closure),
            None,
        )

    return {
        "returned_rule_precision": (
            len(returned_hits) / len(returned_unique) if returned_unique else None
        ),
        "returned_rule_recall": len(returned_hits) / len(closure) if closure else None,
        "inspected_rule_precision": (
            len(inspected_hits) / len(inspected_unique) if inspected_unique else None
        ),
        "inspected_rule_recall": len(inspected_hits) / len(closure) if closure else None,
        "causal_closure_size": len(closure),
        "first_relevant_returned_discovery_call": first_relevant(returned, returned_call_indexes),
        "first_relevant_inspected_discovery_call": first_relevant(
            inspected, inspected_call_indexes
        ),
    }
