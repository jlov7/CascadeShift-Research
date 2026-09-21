"""Condition-neutral tool surface for the measurement-v2 harness."""

from __future__ import annotations

import copy
import json
from typing import Any, Literal

from cascadeshift.agents.runner import business_tool_schemas
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.world import WorldSpec

Condition = Literal["frozen", "current", "full_information"]
Section = Literal["policy", "applications", "roles", "conflict_pairs", "rules"]
CONDITIONS: tuple[Condition, ...] = ("frozen", "current", "full_information")
CONFIG_SECTIONS: tuple[Section, ...] = (
    "policy",
    "applications",
    "roles",
    "conflict_pairs",
    "rules",
)


def canonical_json(value: Any) -> str:
    """Stable JSON encoding used for persisted wire values and hashes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _finish_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "finish_task",
            "description": "Finish the task and explicitly state whether it succeeded.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "summary": {"type": "string"},
                },
                "required": ["success", "summary"],
                "additionalProperties": False,
            },
        },
    }


def measurement_tool_schemas() -> list[dict[str, Any]]:
    """Return the identical tool contracts supplied for every condition."""
    schemas = copy.deepcopy(business_tool_schemas())
    schemas[-1] = _finish_schema()
    schemas.extend(
        [
            {
                "type": "function",
                "function": {
                    "name": "read_configuration",
                    "description": "Read one company configuration section.",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "section": {"type": "string", "enum": list(CONFIG_SECTIONS)}
                        },
                        "required": ["section"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_records",
                    "description": "Read the current employee and request records.",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                },
            },
        ]
    )
    return schemas


def _section_value(
    world: WorldSpec, section: Section, state: WorldState, *, effective: bool
) -> Any:
    if section == "policy":
        return world.policy.model_dump(mode="json")
    if section == "applications":
        return [item.model_dump(mode="json") for item in world.applications]
    if section == "roles":
        return [item.model_dump(mode="json") for item in world.roles]
    if section == "conflict_pairs":
        return [item.model_dump(mode="json") for item in world.conflict_pairs]
    overrides = dict(state.rule_status_overrides) if effective else {}
    rules: list[dict[str, Any]] = []
    for rule in world.rules:
        item = rule.model_dump(mode="json")
        if rule.rule_id in overrides:
            item["status"] = overrides[rule.rule_id]
        rules.append(item)
    return rules


class MeasurementInterface:
    """Reads configuration and records without exposing condition provenance."""

    def __init__(
        self,
        condition: Condition,
        baseline_world: WorldSpec,
        active_world: WorldSpec,
    ) -> None:
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition: {condition}")
        self.condition = condition
        self.baseline_world = baseline_world
        self.active_world = active_world

    def schemas(self) -> list[dict[str, Any]]:
        return measurement_tool_schemas()

    def configuration(self, section: Section, state: WorldState) -> Any:
        """Raw section value used by witnesses and read_configuration responses."""
        if section not in CONFIG_SECTIONS:
            raise ValueError(f"unknown configuration section: {section}")
        world = self.baseline_world if self.condition == "frozen" else self.active_world
        return _section_value(world, section, state, effective=self.condition != "frozen")

    def records(self, state: WorldState) -> dict[str, Any]:
        """Condition-neutral live records. Rule overrides are deliberately excluded."""
        return {
            "employees": [item.model_dump(mode="json") for item in state.employees],
            "requests": [item.model_dump(mode="json") for item in state.requests],
            "review_required": [list(item) for item in state.review_required],
        }

    def full_information(self, state: WorldState) -> dict[str, Any]:
        """Diagnostic-only initial material for full-information episodes."""
        return {
            "configuration": {
                section: _section_value(self.active_world, section, state, effective=True)
                for section in CONFIG_SECTIONS
            },
            "records": self.records(state),
        }

    def call(self, name: str, arguments: dict[str, Any], state: WorldState) -> str:
        """Apply only interface reads; the runner owns business actions."""
        if name == "read_configuration":
            if set(arguments) != {"section"} or arguments.get("section") not in CONFIG_SECTIONS:
                return canonical_json({"error": "invalid_read_configuration_arguments"})
            section = arguments["section"]
            return canonical_json({"section": section, "value": self.configuration(section, state)})
        if name == "read_records":
            if arguments:
                return canonical_json({"error": "invalid_read_records_arguments"})
            return canonical_json(self.records(state))
        return canonical_json({"error": "unknown_tool"})
