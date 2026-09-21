"""Deterministic scripted agents driven by visible goal sequences.

Policies consume only what an agent could legitimately see: visible goal
constraints and tool responses. DiscoveryScripted additionally evaluates
publicly inspected rule DSL locally to anticipate confirmation gates.

Scripted episodes validate harness mechanics offline. They are NOT evidence
about LLM behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cascadeshift.domain.actions import (
    Action,
    ApproveRequest,
    AssignRole,
    CompleteOnboarding,
    FinishTask,
    GrantApplicationAccess,
    OffboardEmployee,
    RevokeApplicationAccess,
)

_APP_RISK: dict[str, int] = {
    "APP-PAY": 10,
    "APP-CRM": 45,
    "APP-VIP": 60,
    "APP-SHR": 15,
    "APP-VPN": 20,
    "APP-BID": 55,
}


@dataclass(frozen=True)
class DiscoverStep:
    tool: str
    args: dict[str, str]


@dataclass(frozen=True)
class BusinessStep:
    action: Action


Step = DiscoverStep | BusinessStep


def _cond_holds(c: dict[str, Any], st: _Beliefs, app_risk: int | None) -> bool:
    k = c.get("kind")
    if k == "always":
        return True
    if k == "employee_field_at_least":
        field = {"clearance": st.clearance, "risk_load": st.risk_load}[c["field"]]
        return bool(field >= c["value"])
    if k == "employee_field_below":
        field = {"clearance": st.clearance, "risk_load": st.risk_load}[c["field"]]
        return bool(field < c["value"])
    if k == "employee_has_entitlement":
        return c["application_id"] in st.holds
    if k == "employee_lacks_entitlement":
        return c["application_id"] not in st.holds
    if k == "event_application_risk_above":
        return app_risk is not None and app_risk > c["value"]
    if k == "employee_is_contractor":
        return st.is_contractor
    # Threshold/role-coupled tenant values are unknowable locally; a
    # cautious assistant treats those conditions as potentially true.
    return k in ("risk_load_at_least_threshold", "clearance_below_role_required")


class _Beliefs:
    def __init__(self) -> None:
        self.holds: frozenset[str] = frozenset()
        self.clearance = 5
        self.risk_load = 0
        self.is_contractor = False
        self.role_id = ""
        self.status = "active"


class ScriptedAgent:
    """Reactive policy skeleton; subclasses inject pre-grant discovery."""

    def __init__(self) -> None:
        self.beliefs = _Beliefs()
        self.employee_id = "E-?"
        self._goals: list[tuple[str, str]] = []
        self._pending_rid: str | None = None
        self._busy = True

    def bind_goals(self, employee_id: str, goals: list[tuple[str, str]]) -> None:
        self.employee_id = employee_id
        self._goals = list(goals)
        self._pending_rid = None
        self._busy = True

    def observe(self, obs: dict[str, Any]) -> None:
        kind = obs.get("obs_kind")
        b = self.beliefs
        if kind == "schema_record":
            emp = obs.get("employee", {}) or {}
            if emp.get("employee_id") == self.employee_id:
                b.holds = frozenset(emp.get("entitlements", []) or [])
                b.clearance = int(emp.get("clearance", 5))
                b.risk_load = int(emp.get("risk_load", 0))
                b.is_contractor = bool(emp.get("is_contractor", False))
                b.role_id = str(emp.get("role_id", ""))
            return
        if kind in ("discovery_search", "discovery_inspect"):
            return
        note = obs.get("note")
        if note in ("granted", "already_held"):
            app = obs.get("application_id") or self._current_arg()
            if isinstance(app, str):
                b.holds = frozenset({*b.holds, app})
            self._busy = True
        elif note in ("revoked", "not_held"):
            app = obs.get("application_id")
            if note == "revoked" and isinstance(app, str):
                b.holds = frozenset(a for a in b.holds if a != app)
            self._busy = True
        elif note in ("assigned", "already_role"):
            rid = obs.get("role_id")
            if isinstance(rid, str):
                b.role_id = rid
            self._busy = True
        elif note == "onboarded":
            b.status = "active"
            self._busy = True
        elif note == "offboarded":
            b.status = "inactive"
            b.holds = frozenset()
            self._busy = True
        elif note == "request_created":
            rid = obs.get("request_id")
            self._pending_rid = str(rid) if rid else None
        elif note == "approved":
            app = obs.get("application_id") or self._current_arg()
            if isinstance(app, str):
                b.holds = frozenset({*b.holds, app})
            self._pending_rid = None
            self._busy = True
        elif note == "rejected":
            self._busy = True

    def _current_arg(self) -> str | None:
        if self._goals:
            return self._goals[0][1]
        return None

    def _pre_grant_steps(self, app: str) -> list[Step]:
        return []

    def _post_grant_goals(self, app: str) -> list[tuple[str, str]]:
        return []

    def step(self) -> Step:
        if self._pending_rid:
            rid = self._pending_rid
            self._pending_rid = None
            return BusinessStep(ApproveRequest(request_id=rid))
        if self._goals and self._busy:
            kind, arg = self._goals[0]
            if kind == "grant":
                pre = self._pre_grant_steps(arg)
                if pre:
                    return pre[0]
            self._goals.pop(0)
            self._busy = False
            if kind == "grant":
                post = self._post_grant_goals(arg)
                if post:
                    self._goals[0:0] = post
                return BusinessStep(
                    GrantApplicationAccess(employee_id=self.employee_id, application_id=arg)
                )
            if kind == "revoke":
                return BusinessStep(
                    RevokeApplicationAccess(employee_id=self.employee_id, application_id=arg)
                )
            if kind == "role":
                return BusinessStep(AssignRole(employee_id=self.employee_id, role_id=arg))
            if kind == "onboard":
                return BusinessStep(CompleteOnboarding(employee_id=self.employee_id))
            if kind == "offboard":
                return BusinessStep(OffboardEmployee(employee_id=self.employee_id))
        return BusinessStep(FinishTask(summary="requested changes applied"))


class SurfaceScripted(ScriptedAgent):
    """No discovery calls; reacts to visible responses only."""


class DiscoveryScripted(ScriptedAgent):
    """Searches/inspects rules before grants; identical code for C1/C2."""

    def __init__(self) -> None:
        super().__init__()
        self._discovers: list[DiscoverStep] = []
        self._inspected: set[str] = set()
        self._checked_apps: set[str] = set()
        self._expects_review_apps: set[str] = set()
        self._bundled: dict[str, set[str]] = {}

    def _post_grant_goals(self, app: str) -> list[tuple[str, str]]:
        return [("revoke", x) for x in sorted(self._bundled.get(app, set()))]

    def _queue_search(self, app: str, query: str) -> None:
        self._discovers.append(
            DiscoverStep(tool="search_rules", args={"query": query, "event_type": "access_granted"})
        )
        self._searching_for = app

    def _learn_rule(self, rec: dict[str, Any], app: str) -> None:
        rid = rec.get("rule_id")
        if rid:
            self._inspected.add(str(rid))
        effects = rec.get("effects") or []
        conditions = rec.get("conditions") or []
        wants_review = any(
            isinstance(e, dict) and e.get("kind") == "require_security_review" for e in effects
        )
        if wants_review:
            ok = all(
                _cond_holds(c, self.beliefs, _APP_RISK.get(app))
                for c in conditions
                if isinstance(c, dict)
            )
            if ok:
                self._expects_review_apps.add(app)

        for e in effects:
            if (
                isinstance(e, dict)
                and e.get("kind") == "grant_entitlement"
                and isinstance(e.get("application_id"), str)
                and e["application_id"] != app
            ):
                ok2 = (
                    all(
                        _cond_holds(c, self.beliefs, _APP_RISK.get(app))
                        for c in conditions
                        if isinstance(c, dict)
                    )
                    if conditions
                    else True
                )
                if ok2:
                    self._bundled.setdefault(app, set()).add(e["application_id"])

    def observe(self, obs: dict[str, Any]) -> None:
        kind = obs.get("obs_kind")
        if kind == "discovery_search":
            for hit in obs.get("results", []):
                rid = hit.get("rule_id")
                if (
                    rid
                    and hit.get("status") == "active"
                    and hit.get("trigger") == "access_granted"
                    and rid not in self._inspected
                    and len([d for d in self._discovers if d.tool == "inspect_rule"]) < 6
                ):
                    self._discovers.append(
                        DiscoverStep(tool="inspect_rule", args={"rule_id": str(rid)})
                    )
            return
        if kind == "discovery_inspect":
            app = getattr(self, "_searching_for", "") or self._last_app()
            self._learn_rule(obs.get("record", {}) or {}, app)
            return
        super().observe(obs)
        # Mitigate anticipated bundle side-effects once the grant lands.
        note = obs.get("note")
        if note in ("granted", "already_held"):
            app = obs.get("application_id") or self._current_arg()
            key = app if isinstance(app, str) else ""
            extras = sorted(self._bundled.get(key, set()) & self.beliefs.holds)
            for extra in extras:
                if extra not in {g[1] for g in self._goals if g[0] == "revoke"}:
                    self._goals.insert(0, ("revoke", extra))

    def _last_app(self) -> str:
        for kind, arg in self._goals:
            if kind == "grant":
                return arg
        return ""

    def _pre_grant_steps(self, app: str) -> list[Step]:
        if self._discovers:
            step = self._discovers.pop(0)
            if step.tool == "search_rules":
                self._searching_for = app
            return [step]
        if app not in self._checked_apps:
            self._checked_apps.add(app)
            # Two-query sweep: confirmation gates then effect-vocabulary.
            self._discovers.append(
                DiscoverStep(
                    tool="search_rules",
                    args={"query": f"{app} confirmation review", "event_type": "access_granted"},
                )
            )
            self._discovers.append(
                DiscoverStep(
                    tool="search_rules",
                    args={
                        "query": "grant entitlement bundle expansion suite",
                        "event_type": "access_granted",
                    },
                )
            )
            step = self._discovers.pop(0)
            self._searching_for = app
            return [step]
        return []
