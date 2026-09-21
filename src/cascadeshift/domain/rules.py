"""Closed typed rule DSL. Rules are data interpreted by the engine — never code."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


EventType = Literal[
    "access_granted",
    "access_revoked",
    "role_assigned",
    "onboarding_completed",
    "employee_offboarded",
    "approval_granted",
]

RuleStatus = Literal["active", "inactive", "superseded"]

_RULE_ID_RE = re.compile(r"^R-\d{4}$")
_SLOT_ID_RE = re.compile(r"^SLOT-\d{4}$")  # pre-numbering placeholder


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Conditions -------------------------------------------------------------


class Always(_Node):
    kind: Literal["always"] = "always"


class EmployeeFieldAtLeast(_Node):
    kind: Literal["employee_field_at_least"] = "employee_field_at_least"
    field: Literal["clearance", "risk_load"]
    value: int


class EmployeeFieldBelow(_Node):
    kind: Literal["employee_field_below"] = "employee_field_below"
    field: Literal["clearance", "risk_load"]
    value: int


class EmployeeHasEntitlement(_Node):
    kind: Literal["employee_has_entitlement"] = "employee_has_entitlement"
    application_id: str


class EmployeeLacksEntitlement(_Node):
    kind: Literal["employee_lacks_entitlement"] = "employee_lacks_entitlement"
    application_id: str


class EventApplicationRiskAbove(_Node):
    kind: Literal["event_application_risk_above"] = "event_application_risk_above"
    value: int


class EmployeeIsContractor(_Node):
    kind: Literal["employee_is_contractor"] = "employee_is_contractor"


class RiskLoadAtLeastThreshold(_Node):
    """Employee risk load at or above world.policy.risk_threshold."""

    kind: Literal["risk_load_at_least_threshold"] = "risk_load_at_least_threshold"


class ClearanceBelowRoleRequired(_Node):
    """Employee clearance below role_map[employee.role_id].clearance_required."""

    kind: Literal["clearance_below_role_required"] = "clearance_below_role_required"


Condition = Annotated[
    Always
    | EmployeeFieldAtLeast
    | EmployeeFieldBelow
    | EmployeeHasEntitlement
    | EmployeeLacksEntitlement
    | EventApplicationRiskAbove
    | EmployeeIsContractor
    | RiskLoadAtLeastThreshold
    | ClearanceBelowRoleRequired,
    Field(discriminator="kind"),
]

_CONDITION_ADAPTER: TypeAdapter[Condition] = TypeAdapter(Condition)


# --- Effects ----------------------------------------------------------------


class AdjustRiskLoad(_Node):
    kind: Literal["adjust_risk_load"] = "adjust_risk_load"
    source: Literal["static", "event_app_risk"]
    value: int


class SetClearance(_Node):
    kind: Literal["set_clearance"] = "set_clearance"
    level: int = Field(ge=1, le=5)


class RevokeEntitlement(_Node):
    kind: Literal["revoke_entitlement"] = "revoke_entitlement"
    application_id: str


class RevokeEntitlementGlobally(_Node):
    kind: Literal["revoke_entitlement_globally"] = "revoke_entitlement_globally"
    application_id: str


class GrantEntitlement(_Node):
    kind: Literal["grant_entitlement"] = "grant_entitlement"
    application_id: str


class RequireSecurityReview(_Node):
    kind: Literal["require_security_review"] = "require_security_review"


class EnableRule(_Node):
    kind: Literal["enable_rule"] = "enable_rule"
    rule_id: str


class DisableRule(_Node):
    kind: Literal["disable_rule"] = "disable_rule"
    rule_id: str


Effect = Annotated[
    AdjustRiskLoad
    | SetClearance
    | RevokeEntitlement
    | RevokeEntitlementGlobally
    | GrantEntitlement
    | RequireSecurityReview
    | EnableRule
    | DisableRule,
    Field(discriminator="kind"),
]

_EFFECT_ADAPTER: TypeAdapter[Effect] = TypeAdapter(Effect)


# --- Rule -------------------------------------------------------------------


class Provenance(_Node):
    owner: str
    effective_date: str
    source: str


class Rule(_Node):
    rule_id: str
    title: str
    description: str
    trigger: EventType
    conditions: tuple[Condition, ...]
    effects: tuple[Effect, ...]
    priority: int
    status: RuleStatus
    provenance: Provenance

    @field_validator("rule_id")
    @classmethod
    def _opaque_id(cls, v: str) -> str:
        if not (_RULE_ID_RE.match(v) or _SLOT_ID_RE.match(v)):
            raise ValueError(f"rule_id must match R-\\d{{4}}, got {v!r}")
        return v

    def semantic_tuple(self) -> str:
        """Canonical config content without prose/provenance, for dedup hashing."""
        return canonical_json(
            {
                "trigger": self.trigger,
                "conditions": [c.model_dump() for c in self.conditions],
                "effects": [e.model_dump() for e in self.effects],
                "priority": self.priority,
                "status": self.status,
            }
        )

    def content_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


def parse_rule(payload: dict[str, object]) -> Rule:
    return Rule.model_validate(payload)
