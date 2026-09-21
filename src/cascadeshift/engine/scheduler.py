"""Deterministic rule scheduler. Order: priority desc, then rule_id asc."""

from __future__ import annotations

from cascadeshift.domain.rules import Rule


class ScheduledFiring:
    __slots__ = ("rule", "origin_seq", "depth")

    def __init__(self, rule: Rule, origin_seq: int, depth: int) -> None:
        self.rule = rule
        self.origin_seq = origin_seq
        self.depth = depth


def order_firings(firings: list[ScheduledFiring]) -> list[ScheduledFiring]:
    return sorted(
        firings,
        key=lambda f: (-f.rule.priority, f.rule.rule_id, f.origin_seq),
    )


def effective_status(rule: Rule, overrides: dict[str, str]) -> str:
    return overrides.get(rule.rule_id, rule.status)
