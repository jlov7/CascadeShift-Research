"""Typed canonical domain state. Owned by the environment; never by an LLM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EmployeeStatus = Literal["onboarding", "active", "offboarding", "inactive"]
ApprovalMode = Literal["auto", "security_review"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Employee(_Strict):
    employee_id: str
    name: str
    role_id: str
    status: EmployeeStatus
    is_contractor: bool
    clearance: int = Field(ge=1, le=5)
    risk_load: int = Field(ge=0, le=100)
    entitlements: tuple[str, ...] = ()

    @field_validator("entitlements")
    @classmethod
    def _sorted_unique(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(v)))

    def with_entitlement(self, application_id: str) -> Employee:
        if application_id in self.entitlements:
            return self
        return self.model_copy(
            update={"entitlements": tuple(sorted((*self.entitlements, application_id)))}
        )

    def without_entitlement(self, application_id: str) -> Employee:
        if application_id not in self.entitlements:
            return self
        return self.model_copy(
            update={"entitlements": tuple(a for a in self.entitlements if a != application_id)}
        )


class Application(_Strict):
    application_id: str
    name: str
    risk_score: int = Field(ge=0, le=100)
    requires_security_review: bool = False


class Role(_Strict):
    role_id: str
    title: str
    mandatory_applications: tuple[str, ...] = ()
    clearance_required: int = Field(default=1, ge=1, le=5)


class Policy(_Strict):
    risk_threshold: int = Field(ge=0, le=100)
    clearance_floor: int = Field(default=1, ge=1, le=5)
    approval_mode: ApprovalMode = "auto"


class ConflictPair(_Strict):
    application_a: str
    application_b: str

    @property
    def pair(self) -> tuple[str, str]:
        return tuple(sorted((self.application_a, self.application_b)))  # type: ignore[return-value]


class AccessRequestRecord(_Strict):
    request_id: str
    employee_id: str
    application_id: str
    status: Literal["pending", "approved", "cancelled"] = "pending"
