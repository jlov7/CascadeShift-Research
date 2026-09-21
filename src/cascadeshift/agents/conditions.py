"""Condition wiring: one runner, three dynamics backends.

C1/C2 share identical tool schemas, ranker, top-k, retries, and formatting;
the only parameter is which configuration snapshot the backend reads.
"""

from __future__ import annotations

from dataclasses import dataclass

from cascadeshift.agents.protocol import DynamicsMode
from cascadeshift.domain.rules import Rule
from cascadeshift.engine.world import WorldSpec
from cascadeshift.retrieval.tools import DiscoveryTools


@dataclass(frozen=True)
class ConditionSpec:
    mode: DynamicsMode
    expose_discovery: bool
    frozen_backend: bool  # True => always read the baseline snapshot

    def discovery_rules(
        self, baseline_world: WorldSpec, active_world: WorldSpec
    ) -> tuple[Rule, ...]:
        if not self.expose_discovery:
            return ()
        return baseline_world.rules if self.frozen_backend else active_world.rules


def condition_spec(mode: DynamicsMode) -> ConditionSpec:
    if mode == "surface":
        return ConditionSpec(mode=mode, expose_discovery=False, frozen_backend=False)
    if mode == "frozen_discovery":
        return ConditionSpec(mode=mode, expose_discovery=True, frozen_backend=True)
    if mode == "live_discovery":
        return ConditionSpec(mode=mode, expose_discovery=True, frozen_backend=False)
    raise ValueError("preflight condition is out of scope for v1 core runs")


def make_tools(
    spec: ConditionSpec, baseline_world: WorldSpec, active_world: WorldSpec
) -> DiscoveryTools | None:
    rules = spec.discovery_rules(baseline_world, active_world)
    return DiscoveryTools(rules) if spec.expose_discovery else None


def tool_schemas_bytes(spec: ConditionSpec) -> bytes:
    """Canonical schema bytes; must be identical for C1 and C2."""
    tools = DiscoveryTools(())
    import json

    if not spec.expose_discovery:
        return b"[]"
    return json.dumps(tools.schemas(), sort_keys=True).encode()
