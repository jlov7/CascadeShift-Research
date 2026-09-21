"""Canonical world state (mutable facts only; configuration lives in WorldSpec)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from cascadeshift.domain.entities import AccessRequestRecord, Employee


class WorldState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    employees: tuple[Employee, ...]
    requests: tuple[AccessRequestRecord, ...] = ()
    review_required: tuple[tuple[str, str], ...] = ()
    rule_status_overrides: tuple[tuple[str, str], ...] = ()

    def employee(self, employee_id: str) -> Employee:
        for e in self.employees:
            if e.employee_id == employee_id:
                return e
        raise KeyError(f"unknown employee: {employee_id}")

    def with_employee(self, updated: Employee) -> WorldState:
        return self.model_copy(
            update={
                "employees": tuple(
                    updated if e.employee_id == updated.employee_id else e for e in self.employees
                )
            }
        )

    def request(self, request_id: str) -> AccessRequestRecord:
        for r in self.requests:
            if r.request_id == request_id:
                return r
        raise KeyError(f"unknown request: {request_id}")

    def with_request(self, record: AccessRequestRecord) -> WorldState:
        return self.model_copy(update={"requests": (*self.requests, record)})
