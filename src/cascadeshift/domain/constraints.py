"""Typed terminal constraints. The verifier evaluates these on canonical state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from cascadeshift.domain.entities import Employee, EmployeeStatus
from cascadeshift.domain.state import WorldState


class _Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def stable_code(self) -> str:
        payload = json.dumps(
            {**self.model_dump(), "_c": type(self).__name__},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _emp(state: WorldState, employee_id: str) -> Employee:
    for e in state.employees:
        if e.employee_id == employee_id:
            return e
    raise KeyError(f"unknown employee: {employee_id}")


class GoalEntitlementPresent(_Constraint):
    kind: Literal["goal_entitlement_present"] = "goal_entitlement_present"
    employee_id: str
    application_id: str

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        return self.application_id in _emp(state, self.employee_id).entitlements


class EntitlementAbsent(_Constraint):
    kind: Literal["entitlement_absent"] = "entitlement_absent"
    employee_id: str
    application_id: str

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        return self.application_id not in _emp(state, self.employee_id).entitlements


class RetainsAllMandatory(_Constraint):
    kind: Literal["retains_all_mandatory"] = "retains_all_mandatory"
    employee_id: str
    mandatory_applications: tuple[str, ...]

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        held = set(_emp(state, self.employee_id).entitlements)
        return all(m in held for m in self.mandatory_applications)


class ClearanceAtLeast(_Constraint):
    kind: Literal["clearance_at_least"] = "clearance_at_least"
    employee_id: str
    level: int

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        return bool(_emp(state, self.employee_id).clearance >= self.level)


class RiskLoadBelow(_Constraint):
    kind: Literal["risk_load_below"] = "risk_load_below"
    employee_id: str
    value: int

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        return bool(_emp(state, self.employee_id).risk_load < self.value)


class RoleIs(_Constraint):
    kind: Literal["role_is"] = "role_is"
    employee_id: str
    role_id: str

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        return bool(_emp(state, self.employee_id).role_id == self.role_id)


class StatusIs(_Constraint):
    kind: Literal["status_is"] = "status_is"
    employee_id: str
    status: EmployeeStatus

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        return bool(_emp(state, self.employee_id).status == self.status)


class NoConflictingPair(_Constraint):
    kind: Literal["no_conflicting_pair"] = "no_conflicting_pair"
    employee_id: str

    def evaluate(
        self,
        state: WorldState,
        applications: Mapping[str, object],
        conflict_pairs: frozenset[tuple[str, str]],
    ) -> bool:
        held = set(_emp(state, self.employee_id).entitlements)
        return all(not (a in held and b in held) for a, b in conflict_pairs)


TerminalConstraint = Annotated[
    GoalEntitlementPresent
    | EntitlementAbsent
    | RetainsAllMandatory
    | ClearanceAtLeast
    | RiskLoadBelow
    | RoleIs
    | StatusIs
    | NoConflictingPair,
    Field(discriminator="kind"),
]

_CONSTRAINT_ADAPTER: TypeAdapter[TerminalConstraint] = TypeAdapter(TerminalConstraint)


def parse_constraint(payload: dict[str, object]) -> TerminalConstraint:
    return _CONSTRAINT_ADAPTER.validate_python(payload)
