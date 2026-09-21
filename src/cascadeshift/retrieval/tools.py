"""Discovery tools exposed to C1/C2 agents.

One implementation, parameterized only by the configuration snapshot.
Responses are canonical JSON strings so byte-equivalence is testable.
"""

from __future__ import annotations

from typing import Any

from cascadeshift.domain.rules import Rule
from cascadeshift.retrieval.index import RetrievalIndex, canonical_json


class DiscoveryTools:
    """Byte-equivalent tool surface; the snapshot is the only free parameter."""

    names = ("search_rules", "inspect_rule", "inspect_dependencies", "inspect_schema")

    def __init__(self, rules: tuple[Rule, ...]) -> None:
        self._index = RetrievalIndex(rules)

    # -- OpenAI-compatible tool schemas (identical for C1/C2) ---------------

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_rules",
                    "description": (
                        "Search the tenant configuration rulebook. Requires a "
                        "text query and/or structured filters. Returns at most "
                        "8 summaries ranked by lexical relevance."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Non-empty keyword query.",
                            },
                            "event_type": {
                                "type": "string",
                                "enum": [
                                    "access_granted",
                                    "access_revoked",
                                    "role_assigned",
                                    "onboarding_completed",
                                    "employee_offboarded",
                                    "approval_granted",
                                ],
                            },
                            "entity_type": {
                                "type": "string",
                                "enum": ["application", "role", "employee", "policy"],
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "inspect_rule",
                    "description": ("Return one full configuration rule by its opaque id."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rule_id": {"type": "string"},
                        },
                        "required": ["rule_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "inspect_dependencies",
                    "description": (
                        "List one-hop references for a rule id or entity id. Bounded result size."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "identifier": {"type": "string"},
                        },
                        "required": ["identifier"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "inspect_schema",
                    "description": "List record fields for an entity type.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entity_type": {
                                "type": "string",
                                "enum": ["application", "role", "employee", "policy"],
                            },
                        },
                        "required": ["entity_type"],
                    },
                },
            },
        ]

    # -- dispatch ------------------------------------------------------------

    def call(self, name: str, args: dict[str, object]) -> str:
        if name == "search_rules":
            et = args.get("event_type")
            ent = args.get("entity_type")
            out = self._index.search(
                query=str(args.get("query") or ""),
                event_type=str(et) if isinstance(et, str) else None,
                entity_type=str(ent) if isinstance(ent, str) else None,
            )
        elif name == "inspect_rule":
            out = self._index.inspect(str(args.get("rule_id") or ""))
        elif name == "inspect_dependencies":
            out = self._index.dependencies(str(args.get("identifier") or ""))
        elif name == "inspect_schema":
            out = self._index.schema_of(str(args.get("entity_type") or ""))
        else:
            out = {"error": "unknown_tool"}
        return canonical_json(out)
