"""WorldSpec: full world configuration (facts + rules). Content-hashable."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, field_validator

from cascadeshift.domain.entities import (
    Application,
    ConflictPair,
    Employee,
    Policy,
    Role,
)
from cascadeshift.domain.rules import Rule
from cascadeshift.domain.state import WorldState

MAX_RULES = 128


class WorldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    world_id: str
    description: str = ""
    policy: Policy
    applications: tuple[Application, ...]
    roles: tuple[Role, ...]
    conflict_pairs: tuple[ConflictPair, ...] = ()
    employees: tuple[Employee, ...]
    rules: tuple[Rule, ...]
    generator_seed: int | None = None

    @field_validator("rules")
    @classmethod
    def _unique_rule_ids(cls, v: tuple[Rule, ...]) -> tuple[Rule, ...]:
        if len(v) > MAX_RULES:
            raise ValueError(f"world supports at most {MAX_RULES} rules")
        ids = [r.rule_id for r in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule ids in world")
        return v

    @field_validator("applications")
    @classmethod
    def _unique_application_ids(cls, v: tuple[Application, ...]) -> tuple[Application, ...]:
        ids = [app.application_id for app in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate application ids in world")
        return v

    @field_validator("roles")
    @classmethod
    def _unique_role_ids(cls, v: tuple[Role, ...]) -> tuple[Role, ...]:
        ids = [role.role_id for role in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate role ids in world")
        return v

    @field_validator("employees")
    @classmethod
    def _unique_employee_ids(cls, v: tuple[Employee, ...]) -> tuple[Employee, ...]:
        ids = [employee.employee_id for employee in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate employee ids in world")
        return v

    @field_validator("conflict_pairs")
    @classmethod
    def _unique_conflict_pairs(cls, v: tuple[ConflictPair, ...]) -> tuple[ConflictPair, ...]:
        pairs = [pair.pair for pair in v]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate conflict pairs in world")
        return v

    def initial_state(self) -> WorldState:
        return WorldState(employees=self.employees)

    def app_map(self) -> dict[str, Application]:
        return {a.application_id: a for a in self.applications}

    def role_map(self) -> dict[str, Role]:
        return {r.role_id: r for r in self.roles}

    def rule_map(self) -> dict[str, Rule]:
        return {r.rule_id: r for r in self.rules}

    def conflict_set(self) -> frozenset[tuple[str, str]]:
        return frozenset(cp.pair for cp in self.conflict_pairs)

    def content_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def semantic_hash(self) -> str:
        """Hash of normalized effective config; ignores prose and provenance.

        Used for near-duplicate shift detection (preregistration dedup rule).
        """
        norm = {
            "policy": self.policy.model_dump(),
            "applications": sorted(
                (a.application_id, a.risk_score, a.requires_security_review)
                for a in self.applications
            ),
            "roles": sorted(
                (r.role_id, tuple(sorted(r.mandatory_applications)), r.clearance_required)
                for r in self.roles
            ),
            "conflicts": sorted(self.conflict_set()),
            "rules": sorted(r.semantic_tuple() for r in self.rules),
        }
        payload = json.dumps(norm, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @classmethod
    def for_testing(cls, rules: tuple[Rule, ...]) -> WorldSpec:
        """Minimal deterministic fixture world for unit tests."""
        apps = (
            Application(
                application_id="APP-PAY",
                name="Payroll Hub",
                risk_score=10,
                requires_security_review=False,
            ),
            Application(
                application_id="APP-CRM",
                name="CRM Lite",
                risk_score=45,
                requires_security_review=False,
            ),
            Application(
                application_id="APP-VIP",
                name="Vault Analytics",
                risk_score=60,
                requires_security_review=False,
            ),
        )
        roles = (
            Role(
                role_id="RL-01",
                title="Analyst",
                mandatory_applications=("APP-CRM",),
                clearance_required=3,
            ),
            Role(
                role_id="RL-02", title="Contractor", mandatory_applications=(), clearance_required=2
            ),
            Role(
                role_id="RL-03",
                title="Finance Admin",
                mandatory_applications=("APP-PAY",),
                clearance_required=4,
            ),
        )
        employees = (
            Employee(
                employee_id="E-001",
                name="Ada Onboarding",
                role_id="RL-02",
                status="onboarding",
                is_contractor=False,
                clearance=4,
                risk_load=20,
                entitlements=("APP-PAY",),
            ),
            Employee(
                employee_id="E-002",
                name="Ben Contractor",
                role_id="RL-02",
                status="active",
                is_contractor=True,
                clearance=2,
                risk_load=0,
                entitlements=(),
            ),
        )
        return cls(
            world_id="world-test-fixture",
            description="Deterministic test fixture",
            policy=Policy(risk_threshold=80, clearance_floor=2, approval_mode="auto"),
            applications=apps,
            roles=roles,
            conflict_pairs=(ConflictPair(application_a="APP-PAY", application_b="APP-VIP"),),
            employees=employees,
            rules=rules,
            generator_seed=None,
        )
