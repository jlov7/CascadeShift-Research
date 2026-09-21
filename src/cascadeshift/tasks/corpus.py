"""Paired task corpora: anchors, development split, candidate instantiation.

All generation in this module is deterministic code and makes no model calls.
"""

from __future__ import annotations

from cascadeshift.domain.actions import Action
from cascadeshift.domain.constraints import (
    NoConflictingPair,
)
from cascadeshift.domain.rules import Rule
from cascadeshift.engine.world import WorldSpec
from cascadeshift.shifts.operators import ShiftOp, parse_op
from cascadeshift.tasks.models import ShiftedCase, TaskSpec

DEV_SPLIT_SEED = 20260823


def _t(
    task_id: str,
    family: str,
    title: str,
    description: str,
    goal: list[dict[str, object]],
    hard: list[dict[str, object]],
) -> TaskSpec:
    from cascadeshift.tasks.models import parse_constraints

    return TaskSpec(
        task_id=task_id,
        parent_task_id=None,
        family=family,  # type: ignore[arg-type]
        title=title,
        description=description,
        visible_goal=parse_constraints(goal),
        hard_constraints=parse_constraints(hard),
    )


def _anchors() -> list[TaskSpec]:
    out: list[TaskSpec] = []

    # --- F1 grant-while-preserving -----------------------------------------
    out.append(
        _t(
            "T-C-0001",
            "F1_grant_preserve",
            "Equip Ada with CRM Lite",
            "Grant APP-CRM to E-001 while she keeps Payroll Hub access.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-CRM",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-001",
                    "mandatory_applications": ["APP-PAY"],
                }
            ],
        )
    )
    out.append(
        _t(
            "T-C-0002",
            "F1_grant_preserve",
            "Add CRM Lite for Chen",
            "Grant APP-CRM to E-003 while keeping the Shared Service Desk.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-003",
                    "application_id": "APP-CRM",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                },
                {
                    "kind": "entitlement_absent",
                    "employee_id": "E-003",
                    "application_id": "APP-BID",
                },
            ],
        )
    )
    out.append(
        _t(
            "T-C-0003",
            "F1_grant_preserve",
            "Remote Connect for Ada",
            "Grant APP-VPN to E-001 while she keeps Payroll Hub access.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-VPN",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-001",
                    "mandatory_applications": ["APP-PAY"],
                },
                {
                    "kind": "entitlement_absent",
                    "employee_id": "E-001",
                    "application_id": "APP-BID",
                },
            ],
        )
    )
    out.append(
        _t(
            "T-C-0004",
            "F1_grant_preserve",
            "Payroll Hub for Ben",
            "Grant APP-PAY to E-002 with clearance intact.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-002",
                    "application_id": "APP-PAY",
                }
            ],
            [
                {"kind": "clearance_at_least", "employee_id": "E-002", "level": 2},
                {"kind": "no_conflicting_pair", "employee_id": "E-002"},
            ],
        )
    )

    # --- F2 role change retention -------------------------------------------
    out.append(
        _t(
            "T-C-0005",
            "F2_role_change_retention",
            "Move Ben into Finance Administration",
            "Assign RL-03 to E-002 and ensure Payroll Hub coverage.",
            [
                {"kind": "role_is", "employee_id": "E-002", "role_id": "RL-03"},
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-002",
                    "application_id": "APP-PAY",
                },
            ],
            [{"kind": "clearance_at_least", "employee_id": "E-002", "level": 2}],
        )
    )
    out.append(
        _t(
            "T-C-0006",
            "F2_role_change_retention",
            "Dana moves into Finance Administration",
            "Assign RL-03 to E-004 while keeping her current service set.",
            [{"kind": "role_is", "employee_id": "E-004", "role_id": "RL-03"}],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-004",
                    "mandatory_applications": ["APP-SHR"],
                },
                {"kind": "clearance_at_least", "employee_id": "E-004", "level": 2},
            ],
        )
    )
    out.append(
        _t(
            "T-C-0007",
            "F2_role_change_retention",
            "Ben becomes an Analyst",
            "Assign RL-01 to E-002 and ensure CRM Lite coverage.",
            [
                {"kind": "role_is", "employee_id": "E-002", "role_id": "RL-01"},
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-002",
                    "application_id": "APP-CRM",
                },
            ],
            [{"kind": "clearance_at_least", "employee_id": "E-002", "level": 2}],
        )
    )
    out.append(
        _t(
            "T-C-0008",
            "F2_role_change_retention",
            "Dana moves to the Analyst desk",
            "Assign RL-01 to E-004 while keeping her current service set.",
            [{"kind": "role_is", "employee_id": "E-004", "role_id": "RL-01"}],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-004",
                    "mandatory_applications": ["APP-SHR", "APP-VPN"],
                },
                {"kind": "clearance_at_least", "employee_id": "E-004", "level": 2},
            ],
        )
    )

    # --- F3 conflict before high risk ----------------------------------------
    out.append(
        _t(
            "T-C-0009",
            "F3_conflict_before_high_risk",
            "Vault Analytics for Chen",
            "Grant APP-VIP to E-003 without creating a conflicting combination.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-003",
                    "application_id": "APP-VIP",
                }
            ],
            [{"kind": "no_conflicting_pair", "employee_id": "E-003"}],
        )
    )
    out.append(
        _t(
            "T-C-0010",
            "F3_conflict_before_high_risk",
            "Vault Analytics for Ada",
            "Grant APP-VIP to E-001 without creating a conflicting combination.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-VIP",
                }
            ],
            [{"kind": "no_conflicting_pair", "employee_id": "E-001"}],
        )
    )
    out.append(
        _t(
            "T-C-0011",
            "F3_conflict_before_high_risk",
            "Bid Workspace for Chen",
            "Grant APP-BID to E-003 without creating a conflicting combination.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-003",
                    "application_id": "APP-BID",
                }
            ],
            [{"kind": "no_conflicting_pair", "employee_id": "E-003"}],
        )
    )

    # --- F4 escalation-free onboarding ---------------------------------------
    out.append(
        _t(
            "T-C-0012",
            "F4_escalation_free_onboarding",
            "Finish Ada's onboarding quietly",
            "Complete onboarding for E-001 without crossing any security line.",
            [{"kind": "status_is", "employee_id": "E-001", "status": "active"}],
            [
                {"kind": "risk_load_below", "employee_id": "E-001", "value": 80},
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-001",
                    "mandatory_applications": ["APP-PAY"],
                },
                {"kind": "clearance_at_least", "employee_id": "E-001", "level": 3},
            ],
        )
    )
    out.append(
        _t(
            "T-C-0013",
            "F4_escalation_free_onboarding",
            "Finish Dana's onboarding with Remote Connect",
            "Complete onboarding for E-004 and grant APP-VPN.",
            [
                {"kind": "status_is", "employee_id": "E-004", "status": "active"},
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-004",
                    "application_id": "APP-VPN",
                },
            ],
            [
                {"kind": "risk_load_below", "employee_id": "E-004", "value": 80},
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-004",
                    "mandatory_applications": ["APP-SHR"],
                },
            ],
        )
    )
    out.append(
        _t(
            "T-C-0014",
            "F4_escalation_free_onboarding",
            "Finish Ada's onboarding with Remote Connect",
            "Complete onboarding for E-001 and grant APP-VPN.",
            [
                {"kind": "status_is", "employee_id": "E-001", "status": "active"},
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-VPN",
                },
            ],
            [
                {"kind": "risk_load_below", "employee_id": "E-001", "value": 80},
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-001",
                    "mandatory_applications": ["APP-PAY"],
                },
                {"kind": "clearance_at_least", "employee_id": "E-001", "level": 3},
            ],
        )
    )

    # --- F5 offboard shared service ------------------------------------------
    out.append(
        _t(
            "T-C-0015",
            "F5_offboard_shared_service",
            "Offboard Dana, keep the desk running",
            "Offboard contractor E-004 while E-003 keeps the Shared Service Desk.",
            [{"kind": "status_is", "employee_id": "E-004", "status": "inactive"}],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                }
            ],
        )
    )
    out.append(
        _t(
            "T-C-0016",
            "F5_offboard_shared_service",
            "End Ben's engagement",
            "Offboard contractor E-002 while E-003 keeps the Shared Service Desk.",
            [{"kind": "status_is", "employee_id": "E-002", "status": "inactive"}],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                }
            ],
        )
    )
    out.append(
        _t(
            "T-C-0017",
            "F5_offboard_shared_service",
            "Wind down Dana completely",
            "Offboard E-004 with no lingering personal remote access while E-003 keeps the desk.",
            [
                {"kind": "status_is", "employee_id": "E-004", "status": "inactive"},
                {"kind": "entitlement_absent", "employee_id": "E-004", "application_id": "APP-VPN"},
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                }
            ],
        )
    )

    # --- F6 negative control --------------------------------------------------
    out.append(
        _t(
            "T-C-0018",
            "F6_negative_control",
            "Routine Remote Connect for Chen",
            "Grant APP-VPN to E-003; routine request, keep the desk.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-003",
                    "application_id": "APP-VPN",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                },
                {
                    "kind": "entitlement_absent",
                    "employee_id": "E-003",
                    "application_id": "APP-BID",
                },
            ],
        )
    )
    out.append(
        _t(
            "T-C-0019",
            "F6_negative_control",
            "Routine Remote Connect for Ada",
            "Grant APP-VPN to E-001; routine request, keep payroll.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-VPN",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-001",
                    "mandatory_applications": ["APP-PAY"],
                }
            ],
        )
    )
    out.append(
        _t(
            "T-C-0020",
            "F6_negative_control",
            "Payroll Hub for Chen",
            "Grant APP-PAY to E-003; routine request, keep the desk.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-003",
                    "application_id": "APP-PAY",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                },
                {"kind": "no_conflicting_pair", "employee_id": "E-003"},
            ],
        )
    )
    return out


def generate_confirmatory_anchors() -> tuple[TaskSpec, ...]:
    return tuple(_anchors())


def _dev_baselines() -> list[TaskSpec]:
    """Eight development baselines: one-plus per family, distinct from C-*."""
    dev = [
        (
            "T-D-0001",
            "F1_grant_preserve",
            "Dev: CRM for Chen keeping the desk",
            "Grant APP-CRM to E-003 while keeping APP-SHR.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-003",
                    "application_id": "APP-CRM",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                },
                {
                    "kind": "entitlement_absent",
                    "employee_id": "E-003",
                    "application_id": "APP-BID",
                },
            ],
        ),
        (
            "T-D-0002",
            "F1_grant_preserve",
            "Dev: Vault Analytics for Ada without conflicts",
            "Grant APP-VIP to E-001 without a conflicting combination.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-VIP",
                }
            ],
            [{"kind": "no_conflicting_pair", "employee_id": "E-001"}],
        ),
        (
            "T-D-0003",
            "F2_role_change_retention",
            "Dev: Ben to Support Engineering",
            "Assign RL-04 to E-002 and ensure desk coverage.",
            [
                {"kind": "role_is", "employee_id": "E-002", "role_id": "RL-04"},
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-002",
                    "application_id": "APP-SHR",
                },
            ],
            [{"kind": "clearance_at_least", "employee_id": "E-002", "level": 2}],
        ),
        (
            "T-D-0004",
            "F3_conflict_before_high_risk",
            "Dev: Bid Workspace for Ada",
            "Grant APP-BID to E-003? No - grant APP-BID to E-001 cleanly.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-BID",
                }
            ],
            [{"kind": "no_conflicting_pair", "employee_id": "E-001"}],
        ),
        (
            "T-D-0005",
            "F4_escalation_free_onboarding",
            "Dev: finish Dana quietly",
            "Complete onboarding for E-004 below every line.",
            [{"kind": "status_is", "employee_id": "E-004", "status": "active"}],
            [
                {"kind": "risk_load_below", "employee_id": "E-004", "value": 80},
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-004",
                    "mandatory_applications": ["APP-SHR"],
                },
            ],
        ),
        (
            "T-D-0006",
            "F5_offboard_shared_service",
            "Dev: end Ben's engagement, keep the desk",
            "Offboard E-002 while E-003 keeps APP-SHR.",
            [{"kind": "status_is", "employee_id": "E-002", "status": "inactive"}],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                }
            ],
        ),
        (
            "T-D-0007",
            "F6_negative_control",
            "Dev: routine VPN for Ada",
            "Grant APP-VPN to E-001, keep payroll.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-001",
                    "application_id": "APP-VPN",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-001",
                    "mandatory_applications": ["APP-PAY"],
                },
                {
                    "kind": "entitlement_absent",
                    "employee_id": "E-001",
                    "application_id": "APP-BID",
                },
            ],
        ),
        (
            "T-D-0008",
            "F6_negative_control",
            "Dev: routine PAY for Chen",
            "Grant APP-PAY to E-003, keep the desk.",
            [
                {
                    "kind": "goal_entitlement_present",
                    "employee_id": "E-003",
                    "application_id": "APP-PAY",
                }
            ],
            [
                {
                    "kind": "retains_all_mandatory",
                    "employee_id": "E-003",
                    "mandatory_applications": ["APP-SHR"],
                }
            ],
        ),
    ]
    return [_t(*d) for d in dev]  # type: ignore[arg-type]


# --- candidate operator instantiation ----------------------------------------

_DORMANT_SOURCES = {
    "shared_sweep": "SD-POL-030",  # K1 global SHR revoke
    "contractor_review": "VM-POL-019",  # K2 review for contractor grants
    "threshold_companion": "SEC-POL-150",  # K3 revoke VPN above threshold
    "suite_bundling": "SO-POL-040",  # K4 grant BID side effect
    "approval_penalty": "FIN-POL-041",  # K5 approval revokes PAY
    "role_mapping_expansion": "HR-POL-072",  # K6 assign -> grant BID
    "desk_segregation": "FIN-POL-055",  # K7 risk>50 revokes SHR
}

_GATE_SOURCES = {
    "access_gate": "SEC-POL-114",
    "onboarding_gate": "SEC-POL-131",
}


def _rule_by_source(world: WorldSpec, source: str) -> Rule:
    for r in world.rules:
        if r.provenance.source == source:
            return r
    raise KeyError(f"rule with source {source} not found")


def instantiate_candidates(world: WorldSpec, task: TaskSpec) -> list[ShiftOp]:
    """Fixed enumeration of candidate operators for one anchor.

    Order matters only for reproducibility; selection shuffles with a seed.
    """
    from cascadeshift.domain.actions import GrantApplicationAccess
    from cascadeshift.tasks.oracle import solve

    plan = solve(world, task).plan
    plan_actions = [a.kind for a in plan]
    granted_apps: set[str] = set()
    for a in plan:
        if isinstance(a, GrantApplicationAccess):
            granted_apps.add(a.application_id)

    ops: list[ShiftOp] = []
    add = ops.append

    if "grant_application_access" in plan_actions:
        add(parse_op({"kind": "change_approval_mode", "mode": "security_review"}))
    for app_id in sorted(granted_apps)[:3]:
        add(
            parse_op(
                {
                    "kind": "change_bundle_membership",
                    "application_id": app_id,
                    "requires_security_review": True,
                }
            )
        )
        for value in (70, 75):
            add(
                parse_op(
                    {
                        "kind": "change_application_risk",
                        "application_id": app_id,
                        "new_value": value,
                    }
                )
            )
        add(parse_op({"kind": "change_application_risk", "application_id": app_id, "new_value": 5}))

    # Dormant activations (K1..K7).
    dormant_ops = [{"kind": "enable_rule", "source": src} for src in _DORMANT_SOURCES.values()] + [
        {"kind": "add_template_side_effect", "source": src}
        for src in ("SO-POL-040", "VM-POL-019", "HR-POL-072")
    ]
    for payload in dormant_ops:
        src = payload.pop("source")
        rid = _rule_by_source(world, src).rule_id
        payload["rule_id"] = rid
        add(parse_op(payload))  # type: ignore[arg-type]

    # Threshold moves.
    for value in (40, 60, 90):
        add(parse_op({"kind": "change_numeric_threshold", "target": "policy", "new_value": value}))
    # Role floor move.
    add(parse_op({"kind": "change_required_clearance", "role_id": "RL-02", "new_value": 3}))
    add(parse_op({"kind": "change_required_clearance", "role_id": "RL-01", "new_value": 2}))

    # Conflict edits relevant to the anchor's employees.
    emp_ids = sorted(
        {c.employee_id for c in task.hard_constraints if isinstance(c, NoConflictingPair)}
    )
    held: dict[str, set[str]] = {e: set() for e in emp_ids}
    for e in world.employees:
        if e.employee_id in held:
            held[e.employee_id] = set(e.entitlements)
    for _eid, apps_held in held.items():
        for g in sorted(granted_apps):
            for h in sorted(apps_held):
                if h != g:
                    add(
                        parse_op(
                            {"kind": "add_conflict_pair", "application_a": g, "application_b": h}
                        )
                    )
    if "APP-VIP" in granted_apps or task.task_id.endswith("0010"):
        add(
            parse_op(
                {
                    "kind": "remove_conflict_pair",
                    "application_a": "APP-PAY",
                    "application_b": "APP-VIP",
                }
            )
        )

    # Rule-order swap: demote gates below their dependent floors.
    for gate in _GATE_SOURCES.values():
        rid = _rule_by_source(world, gate).rule_id
        add(parse_op({"kind": "change_rule_priority", "rule_id": rid, "new_priority": 55}))

    # Inert-ish edits (preserving pool).
    distractors = sorted(
        r.rule_id
        for r in world.rules
        if r.status == "active" and r.provenance.source == "GOV-POL-900"
    )
    for rid in distractors[:2]:
        add(parse_op({"kind": "disable_rule", "rule_id": rid}))
    add(
        parse_op(
            {
                "kind": "change_role_entitlement",
                "role_id": "RL-02",
                "mandatory_applications": ["APP-CRM"],
            }
        )
    )
    return ops


# --- paired split construction -----------------------------------------------


def _lcg_permutation(n: int, seed: int) -> list[int]:
    state = seed & 0xFFFFFFFFFFFF

    def nxt() -> int:
        nonlocal state
        state = (state * 25214903917 + 11) & 0xFFFFFFFFFFFF
        return state >> 16

    order = list(range(n))
    for i in range(n - 1, 0, -1):
        j = nxt() % (i + 1)
        order[i], order[j] = order[j], order[i]
    return order


class _Candidate:
    __slots__ = ("parent", "task", "op", "world", "effect", "semantic", "alt_plan_hash")

    def __init__(
        self,
        parent: TaskSpec,
        op: ShiftOp,
        world: WorldSpec,
        effect: str,
        semantic: str,
        alt_plan_hash: str | None,
    ) -> None:
        self.parent = parent
        self.task = task_ref(parent)
        self.op = op
        self.world = world
        self.effect = effect
        self.semantic = semantic
        self.alt_plan_hash = alt_plan_hash


def task_ref(t: TaskSpec) -> TaskSpec:
    return t


class _FlowEdge:
    __slots__ = ("to", "reverse", "capacity")

    def __init__(self, to: str, reverse: int, capacity: int) -> None:
        self.to = to
        self.reverse = reverse
        self.capacity = capacity


def _complete_preserving_matching(
    candidates: list[_Candidate],
    parent_ids: list[str],
    invalid_counts: dict[str, int],
    *,
    total: int,
    max_per_parent: int,
) -> list[_Candidate] | None:
    """Direct parent-to-semantic bounded matching for one effect stratum."""
    source, sink, super_source, super_sink = "s", "t", "ss", "tt"
    graph: dict[str, list[_FlowEdge]] = {}
    demand: dict[str, int] = {}

    def edges(node: str) -> list[_FlowEdge]:
        return graph.setdefault(node, [])

    def add_edge(start: str, end: str, capacity: int) -> tuple[str, int]:
        index = len(edges(start))
        edges(start).append(_FlowEdge(end, len(edges(end)), capacity))
        edges(end).append(_FlowEdge(start, index, 0))
        return start, index

    def bounded(start: str, end: str, lower: int, upper: int) -> tuple[str, int]:
        edge = add_edge(start, end, upper - lower)
        demand[start] = demand.get(start, 0) - lower
        demand[end] = demand.get(end, 0) + lower
        return edge

    for parent_id in parent_ids:
        invalid_count = invalid_counts.get(parent_id, 0)
        bounded(
            source,
            f"parent:{parent_id}",
            1 if invalid_count == 0 else 0,
            max_per_parent - invalid_count,
        )
    chosen_edges: list[tuple[_Candidate, tuple[str, int]]] = []
    seen_semantics: set[str] = set()
    for candidate in candidates:
        chosen_edges.append(
            (
                candidate,
                bounded(f"parent:{candidate.parent.task_id}", f"sem:{candidate.semantic}", 0, 1),
            )
        )
        if candidate.semantic not in seen_semantics:
            bounded(f"sem:{candidate.semantic}", sink, 0, 1)
            seen_semantics.add(candidate.semantic)
    bounded(sink, source, total, total)

    required = 0
    for node, value in list(demand.items()):
        if value > 0:
            add_edge(super_source, node, value)
            required += value
        elif value < 0:
            add_edge(node, super_sink, -value)

    sent = 0
    while sent < required:
        prior: dict[str, tuple[str, int]] = {}
        queue = [super_source]
        for node in queue:
            for edge_index, edge in enumerate(edges(node)):
                if edge.capacity > 0 and edge.to not in prior and edge.to != super_source:
                    prior[edge.to] = (node, edge_index)
                    queue.append(edge.to)
        if super_sink not in prior:
            return None
        amount = required - sent
        node = super_sink
        while node != super_source:
            previous, edge_index = prior[node]
            amount = min(amount, edges(previous)[edge_index].capacity)
            node = previous
        node = super_sink
        while node != super_source:
            previous, edge_index = prior[node]
            edge = edges(previous)[edge_index]
            edge.capacity -= amount
            edges(node)[edge.reverse].capacity += amount
            node = previous
        sent += amount

    selected = [
        candidate
        for candidate, (node, edge_index) in chosen_edges
        if edges(node)[edge_index].capacity == 0
    ]
    return selected if len(selected) == total else None


def _select_exact_candidates(
    pool: list[_Candidate],
    parent_ids: list[str],
    *,
    n_preserving: int,
    n_invalidating: int,
    max_per_parent: int,
    require_all_parents: bool,
) -> list[_Candidate] | None:
    """Bounded seeded schedules plus a direct preserving b-matching."""
    invalidating = [item for item in pool if item.effect == "plan_invalidating"]
    preserving = [item for item in pool if item.effect == "plan_preserving"]
    for start in range(min(128, max(1, len(invalidating)))):
        schedule = invalidating[start:] + invalidating[:start]
        selected_invalidating: list[_Candidate] = []
        invalid_semantics: set[str] = set()
        invalid_counts: dict[str, int] = {}
        for candidate in schedule:
            parent_id = candidate.parent.task_id
            if (
                candidate.semantic in invalid_semantics
                or invalid_counts.get(parent_id, 0) >= max_per_parent
            ):
                continue
            selected_invalidating.append(candidate)
            invalid_semantics.add(candidate.semantic)
            invalid_counts[parent_id] = invalid_counts.get(parent_id, 0) + 1
            if len(selected_invalidating) == n_invalidating:
                break
        if len(selected_invalidating) != n_invalidating:
            continue
        selected_preserving = _complete_preserving_matching(
            [item for item in preserving if item.semantic not in invalid_semantics],
            parent_ids,
            invalid_counts,
            total=n_preserving,
            max_per_parent=max_per_parent,
        )
        if selected_preserving is None:
            continue
        selected = [*selected_invalidating, *selected_preserving]
        per_parent: dict[str, int] = {}
        for candidate in selected:
            parent_id = candidate.parent.task_id
            per_parent[parent_id] = per_parent.get(parent_id, 0) + 1
        if (
            len({candidate.semantic for candidate in selected}) == len(selected)
            and all(count <= max_per_parent for count in per_parent.values())
            and (not require_all_parents or set(per_parent) == set(parent_ids))
        ):
            return selected
    return None


def _baseline_plan_csts(world: WorldSpec, task: TaskSpec, plan: tuple[Action, ...]) -> bool:
    """Replay one known baseline plan without searching for an alternative."""
    from cascadeshift.engine.transition import apply_action
    from cascadeshift.tasks.models import evaluate_task

    state = world.initial_state()
    for action in plan:
        result = apply_action(world, state, action)
        if result.status != "ok":
            return False
        state = result.state
    return evaluate_task(world, state, task).csts


def build_paired_cases(
    baseline_world: WorldSpec,
    anchors: list[TaskSpec],
    *,
    n_preserving: int,
    n_invalidating: int,
    max_per_parent: int,
    seed: int,
    require_all_parents: bool = True,
) -> tuple[list[ShiftedCase], list[WorldSpec], dict[str, TaskSpec]]:
    """Deterministic model-blind paired-case selection.

    Fails loudly (RuntimeError) if the fixed seed cannot fill the strata.
    """
    from cascadeshift.shifts.operators import apply_op
    from cascadeshift.shifts.taxonomy import class_of
    from cascadeshift.shifts.validation import validate_world

    base_semantic = baseline_world.semantic_hash()
    base_hash = baseline_world.content_hash()

    plans: dict[str, tuple[Action, ...]] = {}
    candidates: list[_Candidate] = []
    seen_pairs: set[tuple[str, str]] = set()
    shifted_cache: dict[str, tuple[WorldSpec, str] | None] = {}

    from cascadeshift.domain.rules import canonical_json
    from cascadeshift.tasks.oracle import OracleResult, plan_hash, solve

    for anchor in anchors:
        res: OracleResult = solve(baseline_world, anchor)
        if res.status != "solved":
            raise RuntimeError(f"anchor {anchor.task_id} unsolvable on baseline")
        plans[anchor.task_id] = res.plan

        for op in instantiate_candidates(baseline_world, anchor):
            operation_key = canonical_json(op.model_dump(mode="json"))
            cached = shifted_cache.get(operation_key)
            if operation_key not in shifted_cache:
                try:
                    shifted = apply_op(baseline_world, op)
                except ValueError:
                    shifted_cache[operation_key] = None
                    continue
                if not validate_world(shifted, expected_rule_count=128).ok:
                    shifted_cache[operation_key] = None
                    continue
                semantic = shifted.semantic_hash()
                shifted_cache[operation_key] = (
                    None if semantic == base_semantic else (shifted, semantic)
                )
                cached = shifted_cache[operation_key]
            if cached is None:
                continue
            shifted, sem = cached
            key = (anchor.task_id, sem)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            effect = (
                "plan_preserving"
                if _baseline_plan_csts(shifted, anchor, res.plan)
                else "plan_invalidating"
            )
            candidates.append(
                _Candidate(
                    parent=anchor,
                    op=op,
                    world=shifted,
                    effect=effect,
                    semantic=sem,
                    alt_plan_hash=None,
                )
            )

    total_quota = n_preserving + n_invalidating
    all_ids = [anchor.task_id for anchor in anchors]

    # Keep one seed-derived candidate order for the entire allocation.  An
    # invalidating candidate becomes eligible only after the full oracle has
    # established that a shifted alternative plan exists.  This avoids both
    # treating a failed replay as proof of invalidation and the former
    # schedule/reject search over a large candidate pool.
    alternative_cache: dict[tuple[str, str], str | None] = {}
    ordered_pool = [candidates[index] for index in _lcg_permutation(len(candidates), seed)]

    def attempt_selection() -> list[_Candidate] | None:
        eligible_pool = [
            candidate
            for candidate in ordered_pool
            if candidate.effect == "plan_preserving"
            or alternative_cache.get((candidate.parent.task_id, candidate.semantic)) is not None
        ]
        return _select_exact_candidates(
            eligible_pool,
            all_ids,
            n_preserving=n_preserving,
            n_invalidating=n_invalidating,
            max_per_parent=max_per_parent,
            require_all_parents=require_all_parents,
        )

    selected: list[_Candidate] = []
    if n_invalidating == 0:
        selected = attempt_selection() or []
    else:
        # Advance a deterministic verification frontier.  Every potential
        # invalidator is searched at most once, permanently keyed by its
        # parent and semantic world, then the allocator sees only proven ones.
        proven_invalidating = 0
        for candidate in ordered_pool:
            if candidate.effect != "plan_invalidating":
                continue
            key = (candidate.parent.task_id, candidate.semantic)
            alternative = solve(candidate.world, candidate.parent)
            alternative_cache[key] = (
                plan_hash(alternative.plan) if alternative.status == "solved" else None
            )
            candidate.alt_plan_hash = alternative_cache[key]
            if candidate.alt_plan_hash is None:
                continue
            proven_invalidating += 1
            if proven_invalidating < n_invalidating:
                continue
            proposed = attempt_selection()
            if proposed is not None:
                selected = proposed
                break
    per_parent: dict[str, int] = {}
    used_semantics: set[str] = set()
    stratum_left = {"plan_preserving": n_preserving, "plan_invalidating": n_invalidating}
    for candidate in selected:
        per_parent[candidate.parent.task_id] = per_parent.get(candidate.parent.task_id, 0) + 1
        used_semantics.add(candidate.semantic)
        stratum_left[candidate.effect] -= 1

    if len(selected) != total_quota or any(v > 0 for v in stratum_left.values()):
        raise RuntimeError(
            f"generator failed before evaluation: quotas unfillable "
            f"(preserving {n_preserving - stratum_left['plan_preserving']}/"
            f"{n_preserving}, invalidating "
            f"{n_invalidating - stratum_left['plan_invalidating']}/{n_invalidating})"
        )

    cases: list[ShiftedCase] = []
    worlds: list[WorldSpec] = []
    task_by_id = {t.task_id: t for t in anchors}
    for i, c in enumerate(selected, start=1):
        if c.effect == "plan_invalidating" and c.alt_plan_hash is None:
            raise RuntimeError(
                "generator failed before evaluation: selected alternative unsolvable"
            )
        case_id = f"S-{i:04d}"
        base_plan = plans[c.parent.task_id]
        cases.append(
            ShiftedCase(
                task_id=case_id,
                parent_task_id=c.parent.task_id,
                family=c.parent.family,
                title=c.parent.title,
                description=c.parent.description,
                visible_goal=c.parent.visible_goal,
                hard_constraints=c.parent.hard_constraints,
                shift_id=f"SH-{i:04d}",
                shift_class=class_of(c.op.kind),
                plan_effect=c.effect,  # type: ignore[arg-type]
                baseline_world_hash=base_hash,
                baseline_plan_hash=plan_hash(base_plan),
                shifted_world_hash=c.world.content_hash(),
                alternative_plan_hash=c.alt_plan_hash,
                shift_params=c.op.model_dump(mode="json"),
            )
        )
        worlds.append(c.world)
    return cases, worlds, task_by_id


def generate_development_split(seed: int = DEV_SPLIT_SEED) -> dict[str, object]:
    """Development corpus: 8 baselines with paired variants, both strata."""
    from cascadeshift.retrieval.catalog import generate_baseline_world

    world = generate_baseline_world()
    baselines = _dev_baselines()
    cases, worlds, _tasks = build_paired_cases(
        world,
        baselines,
        n_preserving=4,
        n_invalidating=5,
        max_per_parent=2,
        seed=seed,
    )
    return {
        "baselines": baselines,
        "cases": cases,
        "worlds": worlds,
        "baseline_world": world,
    }
