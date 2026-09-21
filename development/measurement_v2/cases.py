"""Six illustrative development fixtures for the measurement-v2 harness.

These cases are deliberately small, hand-constructed checks of whether a
declared configuration fact changes the safe action sequence.  They are not
an independent sample, a preregistered evaluation, or evidence of efficacy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from cascadeshift.domain.constraints import TerminalConstraint
from cascadeshift.domain.entities import Application, ConflictPair, Employee, Policy, Role
from cascadeshift.domain.rules import Condition, Effect, EventType, Provenance, Rule, RuleStatus
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec

_EMPLOYEE = Employee(
    employee_id="E-001",
    name="Morgan Lee",
    role_id="RL-BASE",
    status="active",
    is_contractor=False,
    clearance=3,
    risk_load=20,
    entitlements=("APP-KEEP", "APP-TEMP"),
)

_PROVENANCE = {
    "owner": "measurement-v2",
    "effective_date": "2026-09-13",
    "source": "development-fixture",
}


def _rule(
    rule_id: str,
    title: str,
    trigger: EventType,
    conditions: list[dict[str, object]],
    effects: list[dict[str, object]],
    priority: int,
    status: RuleStatus = "active",
) -> Rule:
    return Rule(
        rule_id=rule_id,
        title=title,
        description=f"Development fixture rule: {title}.",
        trigger=trigger,
        conditions=cast(tuple[Condition, ...], conditions),
        effects=cast(tuple[Effect, ...], effects),
        priority=priority,
        status=status,
        provenance=cast(Provenance, _PROVENANCE),
    )


def _applications(target_risk: int = 20) -> tuple[Application, ...]:
    return (
        Application(application_id="APP-KEEP", name="Core Workspace", risk_score=5),
        Application(application_id="APP-TARGET", name="Project Console", risk_score=target_risk),
        Application(application_id="APP-TEMP", name="Temporary Workspace", risk_score=5),
        Application(application_id="APP-BOOST", name="Clearance Briefing", risk_score=5),
        Application(application_id="APP-OTHER", name="Archive Viewer", risk_score=5),
    )


def _roles(new_clearance: int = 3) -> tuple[Role, ...]:
    return (
        Role(role_id="RL-BASE", title="General Operator", clearance_required=3),
        Role(role_id="RL-NEW", title="Project Operator", clearance_required=new_clearance),
    )


def _world(
    case_id: str,
    version: str,
    *,
    policy: Policy,
    applications: tuple[Application, ...],
    roles: tuple[Role, ...],
    conflict_pairs: tuple[ConflictPair, ...],
    rules: tuple[Rule, ...],
) -> WorldSpec:
    return WorldSpec(
        world_id=case_id,
        description="Small configuration-measurement fixture.",
        policy=policy,
        applications=applications,
        roles=roles,
        conflict_pairs=conflict_pairs,
        employees=(_EMPLOYEE,),
        rules=rules,
        generator_seed=None,
    )


def _task_id(case_id: str) -> str:
    """Keep the model-visible task identifier free of the case mechanism."""
    prefix, number, _mechanism = case_id.split("-", 2)
    return f"T-{prefix}-{number}"


def _constraints(
    values: tuple[Mapping[str, object], ...],
) -> tuple[TerminalConstraint, ...]:
    """Keep fixture payloads as runtime-validated data while exposing their DSL type."""
    return cast(tuple[TerminalConstraint, ...], values)


def _grant_task(case_id: str, purpose: str) -> TaskSpec:
    return TaskSpec(
        task_id=_task_id(case_id),
        parent_task_id=None,
        family="F1_grant_preserve",
        title="Provide Project Console access",
        description="Grant Project Console access while retaining Core Workspace.",
        visible_goal=_constraints(
            (
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-TARGET",
                },
            )
        ),
        hard_constraints=_constraints(
            (
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-001",
                    "mandatory_applications": ("APP-KEEP",),
                },
            )
        ),
    )


def _conflict_task(case_id: str, purpose: str) -> TaskSpec:
    return TaskSpec(
        task_id=_task_id(case_id),
        parent_task_id=None,
        family="F3_conflict_before_high_risk",
        title="Provide Project Console access without a conflict",
        description="Grant Project Console access without a conflicting entitlement pair.",
        visible_goal=_constraints(
            (
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-TARGET",
                },
            )
        ),
        hard_constraints=_constraints(({"kind": "no_conflicting_pair", "employee_id": "E-001"},)),
    )


def _role_task(case_id: str, purpose: str) -> TaskSpec:
    return TaskSpec(
        task_id=_task_id(case_id),
        parent_task_id=None,
        family="F2_role_change_retention",
        title="Assign the Project Operator role",
        description="Assign the Project Operator role while retaining Core Workspace.",
        visible_goal=_constraints(
            ({"kind": "role_is", "employee_id": "E-001", "role_id": "RL-NEW"},)
        ),
        hard_constraints=_constraints(
            (
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-001",
                    "mandatory_applications": ("APP-KEEP",),
                },
            )
        ),
    )


def _case(
    case_id: str,
    purpose: str,
    baseline: WorldSpec,
    active: WorldSpec,
    task: TaskSpec,
    baseline_plan: list[dict[str, object]],
    active_plan: list[dict[str, object]],
    fact_witnesses: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "purpose": purpose,
        "baseline_world": baseline.model_dump(mode="json"),
        "active_world": active.model_dump(mode="json"),
        "task": task.model_dump(mode="json"),
        "baseline_plan": baseline_plan,
        "active_plan": active_plan,
        "fact_witnesses": fact_witnesses,
    }


def _policy_threshold_case() -> dict[str, Any]:
    case_id = "M2-001-policy-threshold"
    purpose = (
        "A lower active risk threshold means granting Project Console revokes Core Workspace; "
        "removing temporary access first lowers risk enough to preserve it."
    )
    rules = (
        _rule(
            "R-0001",
            "Account for granted application risk",
            "access_granted",
            [{"kind": "always"}],
            [{"kind": "adjust_risk_load", "source": "event_app_risk", "value": 0}],
            90,
        ),
        _rule(
            "R-0002",
            "Protect core access above the policy threshold",
            "access_granted",
            [
                {"kind": "risk_load_at_least_threshold"},
                {"kind": "employee_has_entitlement", "application_id": "APP-KEEP"},
            ],
            [{"kind": "revoke_entitlement", "application_id": "APP-KEEP"}],
            80,
        ),
        _rule(
            "R-0003",
            "Remove temporary access risk",
            "access_revoked",
            [{"kind": "always"}],
            [{"kind": "adjust_risk_load", "source": "static", "value": -20}],
            70,
        ),
    )
    baseline = _world(
        case_id,
        "baseline",
        policy=Policy(risk_threshold=80, clearance_floor=1, approval_mode="auto"),
        applications=_applications(target_risk=30),
        roles=_roles(),
        conflict_pairs=(ConflictPair(application_a="APP-KEEP", application_b="APP-OTHER"),),
        rules=rules,
    )
    active = baseline.model_copy(
        update={
            "policy": Policy(risk_threshold=40, clearance_floor=1, approval_mode="auto"),
        }
    )
    return _case(
        case_id,
        purpose,
        baseline,
        active,
        _grant_task(case_id, purpose),
        [
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            }
        ],
        [
            {
                "kind": "revoke_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TEMP",
            },
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            },
        ],
        [
            {
                "section": "policy",
                "path": "/risk_threshold",
                "rationale": (
                    "The lower active threshold causes the grant cascade to revoke Core Workspace."
                ),
            }
        ],
    )


def _application_risk_case() -> dict[str, Any]:
    case_id = "M2-002-application-risk"
    purpose = (
        "A higher active Project Console risk score crosses the unchanged policy threshold; "
        "removing temporary access first prevents the revocation."
    )
    rules = (
        _rule(
            "R-0001",
            "Account for granted application risk",
            "access_granted",
            [{"kind": "always"}],
            [{"kind": "adjust_risk_load", "source": "event_app_risk", "value": 0}],
            90,
        ),
        _rule(
            "R-0002",
            "Protect core access above the policy threshold",
            "access_granted",
            [
                {"kind": "risk_load_at_least_threshold"},
                {"kind": "employee_has_entitlement", "application_id": "APP-KEEP"},
            ],
            [{"kind": "revoke_entitlement", "application_id": "APP-KEEP"}],
            80,
        ),
        _rule(
            "R-0003",
            "Remove temporary access risk",
            "access_revoked",
            [{"kind": "always"}],
            [{"kind": "adjust_risk_load", "source": "static", "value": -20}],
            70,
        ),
    )
    baseline = _world(
        case_id,
        "baseline",
        policy=Policy(risk_threshold=50, clearance_floor=1, approval_mode="auto"),
        applications=_applications(target_risk=20),
        roles=_roles(),
        conflict_pairs=(ConflictPair(application_a="APP-KEEP", application_b="APP-OTHER"),),
        rules=rules,
    )
    active = baseline.model_copy(
        update={
            "applications": _applications(target_risk=40),
        }
    )
    return _case(
        case_id,
        purpose,
        baseline,
        active,
        _grant_task(case_id, purpose),
        [
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            }
        ],
        [
            {
                "kind": "revoke_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TEMP",
            },
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            },
        ],
        [
            {
                "section": "applications",
                "path": "/1/risk_score",
                "rationale": (
                    "The active risk score alone pushes the direct grant over the threshold."
                ),
            }
        ],
    )


def _role_clearance_case() -> dict[str, Any]:
    case_id = "M2-003-role-clearance"
    purpose = (
        "A higher active Project Operator clearance requirement revokes Core Workspace on direct "
        "role assignment; a Clearance Briefing grant raises clearance before assignment."
    )
    rules = (
        _rule(
            "R-0001",
            "Briefing raises clearance",
            "access_granted",
            [{"kind": "always"}],
            [{"kind": "set_clearance", "level": 4}],
            90,
        ),
        _rule(
            "R-0002",
            "Remove core access below role clearance",
            "role_assigned",
            [
                {"kind": "clearance_below_role_required"},
                {"kind": "employee_has_entitlement", "application_id": "APP-KEEP"},
            ],
            [{"kind": "revoke_entitlement", "application_id": "APP-KEEP"}],
            80,
        ),
    )
    baseline = _world(
        case_id,
        "baseline",
        policy=Policy(risk_threshold=80, clearance_floor=1, approval_mode="auto"),
        applications=_applications(),
        roles=_roles(new_clearance=3),
        conflict_pairs=(ConflictPair(application_a="APP-KEEP", application_b="APP-OTHER"),),
        rules=rules,
    )
    active = baseline.model_copy(
        update={
            "roles": _roles(new_clearance=4),
        }
    )
    return _case(
        case_id,
        purpose,
        baseline,
        active,
        _role_task(case_id, purpose),
        [{"kind": "assign_role", "employee_id": "E-001", "role_id": "RL-NEW"}],
        [
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-BOOST",
            },
            {"kind": "assign_role", "employee_id": "E-001", "role_id": "RL-NEW"},
        ],
        [
            {
                "section": "roles",
                "path": "/1/clearance_required",
                "rationale": (
                    "The active role requirement makes direct assignment revoke Core Workspace."
                ),
            }
        ],
    )


def _conflict_pair_case() -> dict[str, Any]:
    case_id = "M2-004-conflict-pair"
    purpose = (
        "An active conflict pair makes direct Project Console access unsafe; revoking Core "
        "Workspace before the grant resolves the active conflict."
    )
    baseline = _world(
        case_id,
        "baseline",
        policy=Policy(risk_threshold=80, clearance_floor=1, approval_mode="auto"),
        applications=_applications(),
        roles=_roles(),
        conflict_pairs=(ConflictPair(application_a="APP-KEEP", application_b="APP-OTHER"),),
        rules=(),
    )
    active = baseline.model_copy(
        update={
            "conflict_pairs": (ConflictPair(application_a="APP-KEEP", application_b="APP-TARGET"),),
        }
    )
    return _case(
        case_id,
        purpose,
        baseline,
        active,
        _conflict_task(case_id, purpose),
        [
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            }
        ],
        [
            {
                "kind": "revoke_application_access",
                "employee_id": "E-001",
                "application_id": "APP-KEEP",
            },
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            },
        ],
        [
            {
                "section": "conflict_pairs",
                "path": "/0/application_b",
                "rationale": (
                    "The active pair makes Core Workspace and Project Console incompatible."
                ),
            }
        ],
    )


def _rule_activation_case() -> dict[str, Any]:
    case_id = "M2-005-rule-activation"
    purpose = (
        "An active entitlement-protection rule revokes Core Workspace when the temporary marker is "
        "present; removing that marker before the grant is safe."
    )
    baseline_rules = (
        _rule(
            "R-0001",
            "Protect core access while temporary access remains",
            "access_granted",
            [{"kind": "employee_has_entitlement", "application_id": "APP-TEMP"}],
            [{"kind": "revoke_entitlement", "application_id": "APP-KEEP"}],
            90,
            status="inactive",
        ),
    )
    active_rules = (
        _rule(
            "R-0001",
            "Protect core access while temporary access remains",
            "access_granted",
            [{"kind": "employee_has_entitlement", "application_id": "APP-TEMP"}],
            [{"kind": "revoke_entitlement", "application_id": "APP-KEEP"}],
            90,
            status="active",
        ),
    )
    baseline = _world(
        case_id,
        "baseline",
        policy=Policy(risk_threshold=80, clearance_floor=1, approval_mode="auto"),
        applications=_applications(),
        roles=_roles(),
        conflict_pairs=(ConflictPair(application_a="APP-KEEP", application_b="APP-OTHER"),),
        rules=baseline_rules,
    )
    active = _world(
        case_id,
        "active",
        policy=baseline.policy,
        applications=baseline.applications,
        roles=baseline.roles,
        conflict_pairs=baseline.conflict_pairs,
        rules=active_rules,
    )
    return _case(
        case_id,
        purpose,
        baseline,
        active,
        _grant_task(case_id, purpose),
        [
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            }
        ],
        [
            {
                "kind": "revoke_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TEMP",
            },
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            },
        ],
        [
            {
                "section": "rules",
                "path": "/0/status",
                "rationale": (
                    "The active rule alone turns the direct grant into a Core Workspace revocation."
                ),
            }
        ],
    )


def _rule_priority_case() -> dict[str, Any]:
    case_id = "M2-006-rule-priority"
    purpose = (
        "Changing rule priorities changes whether the temporary marker is removed before a "
        "protective revocation; removing it first is safe in the active ordering."
    )
    baseline_rules = (
        _rule(
            "R-0001",
            "Clear temporary marker first",
            "access_granted",
            [{"kind": "always"}],
            [{"kind": "revoke_entitlement", "application_id": "APP-TEMP"}],
            90,
        ),
        _rule(
            "R-0002",
            "Protect core access while marker remains",
            "access_granted",
            [{"kind": "employee_has_entitlement", "application_id": "APP-TEMP"}],
            [{"kind": "revoke_entitlement", "application_id": "APP-KEEP"}],
            80,
        ),
    )
    active_rules = (
        _rule(
            "R-0001",
            "Clear temporary marker first",
            "access_granted",
            [{"kind": "always"}],
            [{"kind": "revoke_entitlement", "application_id": "APP-TEMP"}],
            70,
        ),
        _rule(
            "R-0002",
            "Protect core access while marker remains",
            "access_granted",
            [{"kind": "employee_has_entitlement", "application_id": "APP-TEMP"}],
            [{"kind": "revoke_entitlement", "application_id": "APP-KEEP"}],
            90,
        ),
    )
    baseline = _world(
        case_id,
        "baseline",
        policy=Policy(risk_threshold=80, clearance_floor=1, approval_mode="auto"),
        applications=_applications(),
        roles=_roles(),
        conflict_pairs=(ConflictPair(application_a="APP-KEEP", application_b="APP-OTHER"),),
        rules=baseline_rules,
    )
    active = _world(
        case_id,
        "active",
        policy=baseline.policy,
        applications=baseline.applications,
        roles=baseline.roles,
        conflict_pairs=baseline.conflict_pairs,
        rules=active_rules,
    )
    return _case(
        case_id,
        purpose,
        baseline,
        active,
        _grant_task(case_id, purpose),
        [
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            }
        ],
        [
            {
                "kind": "revoke_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TEMP",
            },
            {
                "kind": "grant_application_access",
                "employee_id": "E-001",
                "application_id": "APP-TARGET",
            },
        ],
        [
            {
                "section": "rules",
                "path": "/0/priority",
                "rationale": (
                    "The lower active priority lets the entitlement-protection rule fire first."
                ),
            },
            {
                "section": "rules",
                "path": "/1/priority",
                "rationale": (
                    "The higher active priority makes the protection rule see the temporary marker."
                ),
            },
        ],
    )


def build_cases() -> list[dict[str, Any]]:
    """Return six canonical, JSON-serializable development fixtures."""
    return [
        _policy_threshold_case(),
        _application_risk_case(),
        _role_clearance_case(),
        _conflict_pair_case(),
        _rule_activation_case(),
        _rule_priority_case(),
    ]
