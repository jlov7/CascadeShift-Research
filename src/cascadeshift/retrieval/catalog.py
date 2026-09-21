"""Deterministic 128-rule catalog and baseline world generation.

Composition (preregistered): 24 core + 72 active distractors + 32 dormant
(inactive/superseded). Rule ids are opaque, unique, and assigned by a seeded
permutation so membership blocks are not contiguous. No LLM involvement.
"""

from __future__ import annotations

from collections.abc import Callable

from cascadeshift.domain.entities import (
    Application,
    ConflictPair,
    Employee,
    Policy,
    Role,
)
from cascadeshift.domain.rules import Provenance, Rule
from cascadeshift.engine.world import WorldSpec

WORLD_SEED = 20260822
CORE = 24
ACTIVE_DISTRACTORS = 72
DORMANT = 32
TOTAL = CORE + ACTIVE_DISTRACTORS + DORMANT  # 128


def _lcg(seed: int) -> Callable[[], int]:
    """Small deterministic PRNG for shuffling (stable across versions)."""
    state = seed & 0xFFFFFFFFFFFF

    def nxt() -> int:
        nonlocal state
        state = (state * 25214903917 + 11) & 0xFFFFFFFFFFFF
        return state >> 16

    return nxt


def _prov(owner: str, source: str, day: int) -> Provenance:
    return Provenance(
        owner=owner,
        effective_date=f"2026-{1 + day % 12:02d}-{1 + day % 27:02d}",
        source=source,
    )


def _rule(
    rid_slot: int,
    title: str,
    description: str,
    trigger: str,
    conditions: list[dict[str, object]],
    effects: list[dict[str, object]],
    priority: int,
    status: str,
    owner: str,
    src: str,
    day: int,
) -> Rule:
    return Rule(
        rule_id=f"SLOT-{rid_slot:04d}",  # replaced after permutation
        title=title,
        description=description,
        trigger=trigger,  # type: ignore[arg-type]
        conditions=conditions,  # type: ignore[arg-type]
        effects=effects,  # type: ignore[arg-type]
        priority=priority,
        status=status,  # type: ignore[arg-type]
        provenance=_prov(owner, src, day),
    )


# --- core rules (causally relevant to task families) ------------------------


def _core_rules() -> list[Rule]:
    out: list[Rule] = []

    def add(*a: object, **k: object) -> None:
        out.append(_rule(*a, **k))  # type: ignore[arg-type]

    # F1 grant-while-preserving
    add(
        0,
        "Cumulative risk accounting",
        "Adds the granted service risk weight to the person's cumulative load.",
        "access_granted",
        [{"kind": "always"}],
        [{"kind": "adjust_risk_load", "source": "event_app_risk", "value": 0}],
        90,
        "active",
        "iam-platform",
        "SEC-POL-100",
        3,
    )
    add(
        1,
        "Threshold compliance gate",
        "Aligns clearance with the floor when the cumulative load crosses the tenant threshold.",
        "access_granted",
        [{"kind": "risk_load_at_least_threshold"}],
        [{"kind": "set_clearance", "level": 2}],
        80,
        "active",
        "security",
        "SEC-POL-114",
        5,
    )
    add(
        2,
        "Payroll entitlement integrity",
        "Removes payroll access from people whose clearance sits below the role requirement.",
        "access_granted",
        [
            {"kind": "clearance_below_role_required"},
            {"kind": "employee_has_entitlement", "application_id": "APP-PAY"},
        ],
        [{"kind": "revoke_entitlement", "application_id": "APP-PAY"}],
        70,
        "active",
        "payroll",
        "FIN-POL-020",
        9,
    )
    add(
        3,
        "Elevated risk review",
        "Requests a second pair of eyes before elevated-risk services are provisioned.",
        "access_granted",
        [{"kind": "event_application_risk_above", "value": 50}],
        [{"kind": "require_security_review"}],
        60,
        "active",
        "security",
        "SEC-POL-121",
        11,
    )

    # F2 role change retention
    add(
        4,
        "Role change load rebalance",
        "Applies a standard load adjustment whenever a person changes role.",
        "role_assigned",
        [{"kind": "always"}],
        [{"kind": "adjust_risk_load", "source": "static", "value": 15}],
        90,
        "active",
        "hr-systems",
        "HR-POL-044",
        13,
    )
    add(
        5,
        "Contractor role surcharge",
        "External staff carry additional load when moved into a new role.",
        "role_assigned",
        [{"kind": "employee_is_contractor"}],
        [{"kind": "adjust_risk_load", "source": "static", "value": 25}],
        80,
        "active",
        "vendor-mgmt",
        "VM-POL-007",
        15,
    )
    add(
        6,
        "Post-move gate check",
        "Re-checks the tenant threshold after any role move.",
        "role_assigned",
        [{"kind": "risk_load_at_least_threshold"}],
        [{"kind": "set_clearance", "level": 2}],
        70,
        "active",
        "security",
        "SEC-POL-118",
        17,
    )
    add(
        7,
        "Remote work starter kit",
        "Contractor role moves include the standard remote kit.",
        "role_assigned",
        [{"kind": "employee_is_contractor"}],
        [{"kind": "grant_entitlement", "application_id": "APP-VPN"}],
        50,
        "active",
        "it-facilities",
        "IT-POL-201",
        19,
    )

    # F3 conflict before high risk
    add(
        8,
        "Segregation of duties guard",
        "Holding payroll while taking on heavier services is not permitted.",
        "access_granted",
        [
            {"kind": "event_application_risk_above", "value": 55},
            {"kind": "employee_has_entitlement", "application_id": "APP-PAY"},
        ],
        [{"kind": "revoke_entitlement", "application_id": "APP-PAY"}],
        84,
        "active",
        "finance-controls",
        "FIN-POL-031",
        21,
    )
    add(
        9,
        "Bid desk eligibility",
        "Bid vault provisioning requires clearance alignment before use.",
        "access_granted",
        [
            {"kind": "event_application_risk_above", "value": 50},
            {"kind": "clearance_below_role_required"},
        ],
        [{"kind": "revoke_entitlement", "application_id": "APP-BID"}],
        76,
        "active",
        "sales-ops",
        "SO-POL-012",
        23,
    )
    add(
        10,
        "Risky onboarding lock",
        "Disables the legacy discount when onboarding completes above the threshold.",
        "onboarding_completed",
        [{"kind": "risk_load_at_least_threshold"}],
        [{"kind": "disable_rule", "rule_id": "SLOT-0011"}],
        88,
        "active",
        "security",
        "SEC-POL-130",
        25,
    )
    add(
        11,
        "Legacy mid-tier discount",
        "Older pricing pilot reduced load for mid-tier services.",
        "access_granted",
        [{"kind": "event_application_risk_above", "value": 45}],
        [{"kind": "adjust_risk_load", "source": "static", "value": -10}],
        40,
        "active",
        "it-legacy",
        "IT-POL-099",
        27,
    )

    # F4 escalation-free onboarding
    add(
        12,
        "Onboarding completion load",
        "Completing onboarding adds the standard administrative load.",
        "onboarding_completed",
        [{"kind": "always"}],
        [{"kind": "adjust_risk_load", "source": "static", "value": 20}],
        90,
        "active",
        "hr-systems",
        "HR-POL-051",
        29,
    )
    add(
        13,
        "Onboarding threshold gate",
        "Clearance aligns to the floor when completion crosses the threshold.",
        "onboarding_completed",
        [{"kind": "risk_load_at_least_threshold"}],
        [{"kind": "set_clearance", "level": 2}],
        80,
        "active",
        "security",
        "SEC-POL-131",
        31,
    )
    add(
        14,
        "Payroll floor at start",
        "New starters below the role requirement cannot retain payroll.",
        "onboarding_completed",
        [
            {"kind": "clearance_below_role_required"},
            {"kind": "employee_has_entitlement", "application_id": "APP-PAY"},
        ],
        [{"kind": "revoke_entitlement", "application_id": "APP-PAY"}],
        70,
        "active",
        "payroll",
        "FIN-POL-022",
        33,
    )
    add(
        15,
        "Starter connectivity kit",
        "Contractors finishing onboarding receive the standard remote starter set.",
        "onboarding_completed",
        [{"kind": "employee_is_contractor"}],
        [{"kind": "grant_entitlement", "application_id": "APP-VPN"}],
        50,
        "active",
        "it-facilities",
        "IT-POL-203",
        35,
    )

    # F5 offboard shared service
    add(
        16,
        "Desk tool cleanup",
        "Leavers lose the shared desk utility from their personal profile.",
        "employee_offboarded",
        [{"kind": "always"}],
        [{"kind": "revoke_entitlement", "application_id": "APP-SHR"}],
        90,
        "active",
        "service-desk",
        "SD-POL-018",
        37,
    )
    add(
        17,
        "Connectivity wind-down",
        "Personal remote access closes with the engagement window.",
        "employee_offboarded",
        [{"kind": "always"}],
        [{"kind": "revoke_entitlement", "application_id": "APP-VPN"}],
        80,
        "active",
        "it-facilities",
        "IT-POL-210",
        39,
    )
    add(
        18,
        "Exit threshold review",
        "Exits above the threshold drop clearance to the minimum.",
        "employee_offboarded",
        [{"kind": "risk_load_at_least_threshold"}],
        [{"kind": "set_clearance", "level": 1}],
        60,
        "active",
        "security",
        "SEC-POL-140",
        41,
    )
    add(
        19,
        "Approval credit release",
        "Approved requests settle part of the accumulated load.",
        "approval_granted",
        [{"kind": "always"}],
        [{"kind": "adjust_risk_load", "source": "static", "value": -10}],
        60,
        "active",
        "iam-platform",
        "SEC-POL-102",
        43,
    )

    # F6 negative control (routine low-risk grant path)
    add(
        20,
        "Light service surcharge",
        "Nominal load added for ordinary services beyond the base tier.",
        "access_granted",
        [{"kind": "event_application_risk_above", "value": 5}],
        [{"kind": "adjust_risk_load", "source": "static", "value": 2}],
        30,
        "active",
        "iam-platform",
        "SEC-POL-104",
        45,
    )
    add(
        21,
        "Release credit",
        "Returning capacity reduces the cumulative load slightly.",
        "access_revoked",
        [{"kind": "always"}],
        [{"kind": "adjust_risk_load", "source": "static", "value": -5}],
        90,
        "active",
        "iam-platform",
        "SEC-POL-105",
        47,
    )
    add(
        22,
        "Post-release recovery",
        "Heavy users recover standard clearance after releasing capacity.",
        "access_revoked",
        [{"kind": "risk_load_at_least_threshold"}],
        [{"kind": "set_clearance", "level": 3}],
        80,
        "active",
        "security",
        "SEC-POL-106",
        49,
    )
    add(
        23,
        "Routine request hygiene",
        "Approved routine requests keep records aligned with policy.",
        "approval_granted",
        [{"kind": "always"}],
        [{"kind": "adjust_risk_load", "source": "static", "value": -2}],
        40,
        "active",
        "service-desk",
        "SD-POL-021",
        51,
    )
    return out[:CORE]


# --- distractor bank ---------------------------------------------------------

_AREAS = [
    "invoice",
    "badge",
    "travel",
    "print",
    "parking",
    "cafeteria",
    "library",
    "mentorship",
    "alumni",
    "wellness",
    "labs",
    "studio",
    "archive",
    "mailroom",
    "helpdesk",
    "training",
    "procurement",
    "facilities",
    "legal-hold",
    "records",
]
_ASPECTS = [
    "notification",
    "ledger",
    "review cycle",
    "escalation ladder",
    "quota",
    "seasonal window",
    "audit trail",
    "reminder schedule",
    "capacity plan",
    "retention rule",
]

_TRIGGERS = [
    "access_granted",
    "access_revoked",
    "role_assigned",
    "onboarding_completed",
    "employee_offboarded",
    "approval_granted",
]


def _distractor_rules(start_slot: int) -> list[Rule]:
    out: list[Rule] = []
    i = start_slot
    n_areas = len(_AREAS)
    n_aspects = len(_ASPECTS)
    idx = 0
    while len(out) < ACTIVE_DISTRACTORS:
        area = _AREAS[idx % n_areas]
        aspect = _ASPECTS[(idx // n_areas) % n_aspects]
        trig = _TRIGGERS[(idx * 5 + 1) % len(_TRIGGERS)]
        prio = 25 + (idx * 7) % 30
        day = (idx * 3) % 27
        if idx % 4 == 0:
            conds: list[dict[str, object]] = [{"kind": "always"}]
            effs: list[dict[str, object]] = [
                {"kind": "adjust_risk_load", "source": "static", "value": 1}
            ]
        elif idx % 4 == 1:
            conds = [{"kind": "event_application_risk_above", "value": 80}]
            effs = [{"kind": "adjust_risk_load", "source": "static", "value": -1}]
        elif idx % 4 == 2:
            conds = [{"kind": "always"}]
            effs = [{"kind": "adjust_risk_load", "source": "static", "value": -1}]
        else:
            conds = [{"kind": "risk_load_at_least_threshold"}]
            effs = [{"kind": "set_clearance", "level": 1 + idx % 3}]
        title = f"{area.title()} {aspect.title()} control"
        desc = (
            f"Standard {area} {aspect} handling applied automatically "
            f"when related activity is recorded."
        )
        out.append(
            _rule(
                i, title, desc, trig, conds, effs, prio, "active", "governance", "GOV-POL-900", day
            )
        )
        i += 1
        idx += 1
    return out


def _dormant_rules(start_slot: int) -> list[Rule]:
    out: list[Rule] = []

    def add(*a: object, **k: object) -> None:
        out.append(_rule(*a, **k))  # type: ignore[arg-type]

    add(
        start_slot + 0,
        "Shared desk continuity sweep",
        "When external staff exit, the shared desk utility is rotated across the roster.",
        "employee_offboarded",
        [{"kind": "employee_is_contractor"}],
        [{"kind": "revoke_entitlement_globally", "application_id": "APP-SHR"}],
        92,
        "inactive",
        "service-desk",
        "SD-POL-030",
        53,
    )
    add(
        start_slot + 1,
        "Contractor connectivity review",
        "Second-person confirmation applies before external staff receive remote connectivity.",
        "access_granted",
        [{"kind": "employee_is_contractor"}, {"kind": "event_application_risk_above", "value": 10}],
        [{"kind": "require_security_review"}],
        88,
        "inactive",
        "vendor-mgmt",
        "VM-POL-019",
        55,
    )
    add(
        start_slot + 2,
        "Threshold companion sweep",
        "Above-threshold people also lose remote connectivity until reviewed.",
        "access_granted",
        [{"kind": "risk_load_at_least_threshold"}],
        [{"kind": "revoke_entitlement", "application_id": "APP-VPN"}],
        65,
        "inactive",
        "security",
        "SEC-POL-150",
        57,
    )
    add(
        start_slot + 3,
        "Suite bundling expansion",
        "Provisioning mid-tier services pulls in the bid workspace bundle.",
        "access_granted",
        [
            {"kind": "event_application_risk_above", "value": 10},
            {"kind": "employee_lacks_entitlement", "application_id": "APP-BID"},
        ],
        [{"kind": "grant_entitlement", "application_id": "APP-BID"}],
        62,
        "inactive",
        "sales-ops",
        "SO-POL-040",
        59,
    )
    add(
        start_slot + 4,
        "Approval settlement penalty",
        "Approvals granted above the threshold settle against payroll first.",
        "approval_granted",
        [{"kind": "risk_load_at_least_threshold"}],
        [{"kind": "revoke_entitlement", "application_id": "APP-PAY"}],
        95,
        "inactive",
        "payroll",
        "FIN-POL-041",
        61,
    )
    add(
        start_slot + 5,
        "Role mapping expansion",
        "Role moves include the bid workspace mapping.",
        "role_assigned",
        [{"kind": "always"}],
        [{"kind": "grant_entitlement", "application_id": "APP-BID"}],
        60,
        "inactive",
        "hr-systems",
        "HR-POL-072",
        63,
    )
    add(
        start_slot + 6,
        "Shared desk segregation",
        "Heavier services cannot coexist with the shared desk utility.",
        "access_granted",
        [
            {"kind": "event_application_risk_above", "value": 50},
            {"kind": "employee_has_entitlement", "application_id": "APP-SHR"},
        ],
        [{"kind": "revoke_entitlement", "application_id": "APP-SHR"}],
        86,
        "inactive",
        "finance-controls",
        "FIN-POL-055",
        65,
    )
    add(
        start_slot + 7,
        "Legacy discount retirement",
        "Superseded variant of the mid-tier discount retained for audit.",
        "access_granted",
        [{"kind": "event_application_risk_above", "value": 45}],
        [{"kind": "adjust_risk_load", "source": "static", "value": -10}],
        40,
        "superseded",
        "it-legacy",
        "IT-POL-099A",
        67,
    )
    # Blanket and per-application confirmation gates. Approval-policy shift
    # operators toggle these, so every dynamic behavior stays rule-mediated
    # and inspectable through the discovery tools.
    add(
        start_slot + 8,
        "Universal provisioning confirmation",
        "Every access grant waits for a second person to confirm it.",
        "access_granted",
        [{"kind": "always"}],
        [{"kind": "require_security_review"}],
        93,
        "inactive",
        "security",
        "SEC-POL-160",
        69,
    )
    for _slot_i, _app in enumerate(
        ["APP-PAY", "APP-CRM", "APP-VIP", "APP-SHR", "APP-VPN", "APP-BID"]
    ):
        add(
            start_slot + 9 + _slot_i,
            f"{_app[4:].title()} confirmation gate",
            "Provisioning this service records a confirmation step first.",
            "access_granted",
            [{"kind": "event_application_risk_above", "value": -1}],
            [{"kind": "require_security_review"}],
            91 - _slot_i,
            "inactive",
            "iam-platform",
            f"RVW-POL-{_app}",
            70,
        )

    # Remaining dormant slots: rotated inactive/superseded filler variants.
    i = start_slot + 15
    idx = 0
    while len(out) < DORMANT:
        area = _AREAS[(idx + 7) % len(_AREAS)]
        aspect = _ASPECTS[(idx + 4) % len(_ASPECTS)]
        trig = _TRIGGERS[(idx * 3 + 2) % len(_TRIGGERS)]
        status = "inactive" if idx % 3 else "superseded"
        title = f"{area.title()} {aspect.title()} archive control"
        desc = "Retired or paused configuration retained for historical reporting."
        out.append(
            _rule(
                i,
                title,
                desc,
                trig,
                [{"kind": "always"}],
                [{"kind": "adjust_risk_load", "source": "static", "value": -1}],
                20 + idx % 10,
                status,
                "governance",
                "GOV-POL-950",
                (idx * 5) % 27,
            )
        )
        i += 1
        idx += 1
    return out


def generate_catalog_with_manifest(
    seed: int = WORLD_SEED,
) -> tuple[tuple[Rule, ...], dict[str, str]]:
    """Return (rules, rule_id -> kind) where kind names membership block."""
    slots = _core_rules() + _distractor_rules(CORE) + _dormant_rules(CORE + ACTIVE_DISTRACTORS)
    if len(slots) != TOTAL:
        raise RuntimeError(f"catalog template count {len(slots)} does not match {TOTAL}")
    kinds = ["core"] * CORE + ["distractor"] * ACTIVE_DISTRACTORS + ["dormant"] * DORMANT
    rng = _lcg(seed)
    order = list(range(TOTAL))
    for i in range(TOTAL - 1, 0, -1):
        j = rng() % (i + 1)
        order[i], order[j] = order[j], order[i]
    numbered: list[Rule] = []
    manifest: dict[str, str] = {}
    for position, slot_index in enumerate(order):
        r = slots[slot_index]
        rid = f"R-{1001 + position:04d}"
        numbered.append(r.model_copy(update={"rule_id": rid}))
        manifest[rid] = kinds[slot_index]
    slot_to_final = {f"SLOT-{i:04d}": f"R-{1001 + order.index(i):04d}" for i in range(TOTAL)}
    resolved: list[Rule] = []
    for r in numbered:
        blob = r.model_dump()
        changed = False
        for e in blob["effects"]:
            if isinstance(e, dict) and e.get("kind") in {"enable_rule", "disable_rule"}:
                target = e.get("rule_id")
                if target in slot_to_final:
                    e["rule_id"] = slot_to_final[target]
                    changed = True
        resolved.append(r.model_validate(blob) if changed else r)
    return tuple(resolved), manifest


def generate_catalog(seed: int = WORLD_SEED) -> tuple[Rule, ...]:
    return generate_catalog_with_manifest(seed)[0]


BASELINE_APPS: tuple[Application, ...] = (
    Application(
        application_id="APP-PAY", name="Payroll Hub", risk_score=10, requires_security_review=False
    ),
    Application(
        application_id="APP-CRM", name="CRM Lite", risk_score=45, requires_security_review=False
    ),
    Application(
        application_id="APP-VIP",
        name="Vault Analytics",
        risk_score=60,
        requires_security_review=False,
    ),
    Application(
        application_id="APP-SHR",
        name="Shared Service Desk",
        risk_score=15,
        requires_security_review=False,
    ),
    Application(
        application_id="APP-VPN",
        name="Remote Connect",
        risk_score=20,
        requires_security_review=False,
    ),
    Application(
        application_id="APP-BID",
        name="Bid Workspace",
        risk_score=55,
        requires_security_review=False,
    ),
)

BASELINE_ROLES: tuple[Role, ...] = (
    Role(
        role_id="RL-01", title="Analyst", mandatory_applications=("APP-CRM",), clearance_required=3
    ),
    Role(role_id="RL-02", title="Contractor", mandatory_applications=(), clearance_required=2),
    Role(
        role_id="RL-03",
        title="Finance Administrator",
        mandatory_applications=("APP-PAY",),
        clearance_required=4,
    ),
    Role(
        role_id="RL-04",
        title="Support Engineer",
        mandatory_applications=("APP-SHR",),
        clearance_required=2,
    ),
)

BASELINE_EMPLOYEES: tuple[Employee, ...] = (
    Employee(
        employee_id="E-001",
        name="Ada Marsh",
        role_id="RL-02",
        status="onboarding",
        is_contractor=False,
        clearance=4,
        risk_load=20,
        entitlements=("APP-PAY",),
    ),
    Employee(
        employee_id="E-002",
        name="Ben Ortega",
        role_id="RL-02",
        status="active",
        is_contractor=True,
        clearance=2,
        risk_load=0,
        entitlements=(),
    ),
    Employee(
        employee_id="E-003",
        name="Chen Wu",
        role_id="RL-01",
        status="active",
        is_contractor=False,
        clearance=3,
        risk_load=10,
        entitlements=("APP-SHR",),
    ),
    Employee(
        employee_id="E-004",
        name="Dana Iyer",
        role_id="RL-04",
        status="onboarding",
        is_contractor=True,
        clearance=2,
        risk_load=5,
        entitlements=("APP-SHR", "APP-VPN"),
    ),
)


def generate_baseline_world(seed: int = WORLD_SEED) -> WorldSpec:
    rules = generate_catalog(seed)
    return WorldSpec(
        world_id="world-baseline-v1",
        description=("Employee onboarding and application-access management baseline."),
        policy=Policy(risk_threshold=80, clearance_floor=2, approval_mode="auto"),
        applications=BASELINE_APPS,
        roles=BASELINE_ROLES,
        conflict_pairs=(
            ConflictPair(application_a="APP-PAY", application_b="APP-VIP"),
            ConflictPair(application_a="APP-SHR", application_b="APP-BID"),
        ),
        employees=BASELINE_EMPLOYEES,
        rules=rules,
        generator_seed=seed,
    )
