"""Deterministic lexical BM25-lite index over the rule catalog.

No embeddings. Field weights: title x3, description x1, trigger x2.
Ranking: BM25 (k1=1.5, b=0.75); ties broken by ascending rule_id.
Top-k hard bound: 8. No wildcard or dump surface exists.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from cascadeshift.domain.rules import Rule

TOP_K = 8
_BM25_K1 = 1.5
_BM25_B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_SCHEMAS: dict[str, tuple[str, ...]] = {
    "employee": (
        "employee_id",
        "name",
        "role_id",
        "status",
        "is_contractor",
        "clearance",
        "risk_load",
        "entitlements",
    ),
    "application": ("application_id", "name", "risk_score", "requires_security_review"),
    "role": ("role_id", "title", "mandatory_applications", "clearance_required"),
    "policy": ("risk_threshold", "clearance_floor", "approval_mode"),
}

_WILDCARDS = {"*", "?", "%", "**"}


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def rule_entity_types(rule: Rule) -> tuple[str, ...]:
    blob = json.dumps(rule.model_dump(mode="json"))
    types = set()
    if "APP-" in blob:
        types.add("application")
    if "RL-" in blob:
        types.add("role")
    if '"E-' in blob:
        types.add("employee")
    if not types:
        types.add("policy")
    return tuple(sorted(types))


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class RetrievalIndex:
    """Immutable index over one configuration snapshot."""

    def __init__(self, rules: tuple[Rule, ...]) -> None:
        self._rules = {r.rule_id: r for r in rules}
        self._order = sorted(self._rules)
        doc_tokens: dict[str, dict[str, int]] = {}
        for rid in self._order:
            r = self._rules[rid]
            text = " ".join(
                [r.title] * 3
                + [r.description]
                + [r.trigger] * 2
                + [f"{c.kind} {json.dumps(c.model_dump())}" for c in r.conditions]
                + [e.kind for e in r.effects]
            )
            counts: dict[str, int] = {}
            for tok in tokenize(text):
                counts[tok] = counts.get(tok, 0) + 1
            doc_tokens[rid] = counts
        self._doc_tokens = doc_tokens
        self._doc_len = {rid: sum(c.values()) for rid, c in doc_tokens.items()}
        n = max(len(self._order), 1)
        df: dict[str, int] = {}
        for counts in doc_tokens.values():
            for tok in counts:
                df[tok] = df.get(tok, 0) + 1
        self._idf = {tok: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for tok, freq in df.items()}
        self._avg_len = (sum(self._doc_len.values()) / n) if n else 0.0

    # -- search --------------------------------------------------------------

    def search(
        self,
        query: str,
        event_type: str | None = None,
        entity_type: str | None = None,
        _test_pool: tuple[Rule, ...] | None = None,
    ) -> dict[str, Any]:
        if (
            query is None
            or any(w in query for w in _WILDCARDS)
            or (not query.strip() and event_type is None and entity_type is None)
        ):
            if not query.strip() and event_type is None and entity_type is None:
                return {"error": "query_required"}
            if query and any(w in query for w in _WILDCARDS):
                return {"error": "wildcard_not_supported"}
        q_tokens = tokenize(query) if query else []
        pool = _test_pool if _test_pool is not None else tuple(self._rules[r] for r in self._order)
        scored: list[tuple[float, str]] = []
        for r in pool:
            if event_type is not None and r.trigger != event_type:
                continue
            if entity_type is not None and entity_type not in rule_entity_types(r):
                continue
            score = self._score(r.rule_id, q_tokens)
            scored.append((score, r.rule_id))
        scored.sort(key=lambda t: (-t[0], t[1]))
        top = scored[:TOP_K]
        results = []
        for score, rid in top:
            r = self._rules[rid]
            results.append(
                {
                    "rule_id": rid,
                    "title": r.title,
                    "status": r.status,
                    "priority": r.priority,
                    "trigger": r.trigger,
                    "_score": round(score, 6),
                }
            )
        return {
            "results": results,
            "truncated": len(scored) > TOP_K,
            "matched": len(scored),
        }

    def _score(self, rid: str, q_tokens: list[str]) -> float:
        if not q_tokens:
            return 0.0
        counts = self._doc_tokens[rid]
        dl = self._doc_len[rid] or 1
        avg = self._avg_len or 1.0
        score = 0.0
        for tok in q_tokens:
            freq = counts.get(tok)
            if not freq:
                continue
            idf = self._idf.get(tok, 0.0)
            denom = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avg)
            score += idf * (freq * (_BM25_K1 + 1)) / denom
        return score

    # -- inspect -------------------------------------------------------------

    def inspect(self, rule_id: str) -> dict[str, Any]:
        r = self._rules.get(rule_id)
        if r is None:
            return {"error": "unknown_rule", "rule_id": rule_id}
        return r.model_dump(mode="json")

    def dependencies(self, identifier: str) -> dict[str, Any]:
        neighbors: set[str] = set()
        target = self._rules.get(identifier)
        if target is None:
            # application/entity reference: rules mentioning it
            for rid in self._order:
                blob = canonical_json(self._rules[rid].model_dump(mode="json"))
                if identifier in blob:
                    neighbors.add(rid)
        else:
            from cascadeshift.domain.rules import DisableRule, EnableRule

            for rid in self._order:
                other = self._rules[rid]
                blob = canonical_json(other.model_dump(mode="json"))
                if identifier in blob:
                    neighbors.add(rid)
                for eff in other.effects:
                    if isinstance(eff, EnableRule | DisableRule):
                        if eff.rule_id == identifier:
                            neighbors.add(rid)
                        if rid == identifier and eff.rule_id in self._rules:
                            neighbors.add(eff.rule_id)
            if target is not None:
                pass
        listed = [
            {"id": nid, "relation": "reference", "status": self._rules[nid].status}
            for nid in sorted(neighbors)[:TOP_K]
        ]
        return {"of": identifier, "neighbors": listed, "truncated": len(neighbors) > TOP_K}

    def schema_of(self, entity_type: str) -> dict[str, Any]:
        fields = _SCHEMAS.get(entity_type)
        if fields is None:
            return {"error": "unknown_entity_type", "entity_type": entity_type}
        return {"entity_type": entity_type, "fields": list(fields)}

    def catalog_size(self) -> int:
        return len(self._rules)
