"""Independent engine checks for the six measurement-v2 development fixtures."""

from __future__ import annotations

import json
from typing import Any

from development.measurement_v2.cases import build_cases

from cascadeshift.domain.actions import parse_action
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec, evaluate_task
from cascadeshift.tasks.oracle import verify_plan


def _resolve(value: object, pointer: str) -> object:
    assert pointer.startswith("/")
    current = value
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        else:
            assert isinstance(current, dict)
            current = current[token]
    return current


def _models(case: dict[str, Any]) -> tuple[WorldSpec, WorldSpec, TaskSpec]:
    return (
        WorldSpec.model_validate(case["baseline_world"]),
        WorldSpec.model_validate(case["active_world"]),
        TaskSpec.model_validate(case["task"]),
    )


def test_cases_are_canonical_json_with_expected_shape():
    cases = build_cases()
    assert [case["case_id"] for case in cases] == [
        "M2-001-policy-threshold",
        "M2-002-application-risk",
        "M2-003-role-clearance",
        "M2-004-conflict-pair",
        "M2-005-rule-activation",
        "M2-006-rule-priority",
    ]
    assert len(cases) == 6
    for case in cases:
        assert set(case) == {
            "case_id",
            "purpose",
            "baseline_world",
            "active_world",
            "task",
            "baseline_plan",
            "active_plan",
            "fact_witnesses",
        }
        json.dumps(case, sort_keys=True)
        task_id = case["task"]["task_id"]
        prefix, number, _mechanism = case["case_id"].split("-", 2)
        assert task_id == f"T-{prefix}-{number}"
        task_text = json.dumps(case["task"], sort_keys=True)
        assert case["purpose"] not in task_text
        assert not any(
            mechanism in task_id
            for mechanism in (
                "policy-threshold",
                "application-risk",
                "role-clearance",
                "conflict-pair",
                "rule-activation",
                "rule-priority",
            )
        )


def test_cases_have_visible_initial_failure_and_paired_plan_effect():
    for case in build_cases():
        baseline, active, task = _models(case)
        baseline_plan = tuple(parse_action(action) for action in case["baseline_plan"])
        active_plan = tuple(parse_action(action) for action in case["active_plan"])

        assert not evaluate_task(baseline, baseline.initial_state(), task).goal_satisfied
        assert not evaluate_task(active, active.initial_state(), task).goal_satisfied
        assert verify_plan(baseline, task, baseline_plan).csts
        assert not verify_plan(active, task, baseline_plan).csts
        assert verify_plan(active, task, active_plan).csts


def test_cases_preserve_records_and_expose_changed_action_relevant_facts():
    for case in build_cases():
        baseline, active, _task = _models(case)
        assert (
            baseline.model_dump(mode="json")["employees"]
            == active.model_dump(mode="json")["employees"]
        )

        baseline_data = baseline.model_dump(mode="json")
        active_data = active.model_dump(mode="json")
        assert case["fact_witnesses"]
        for witness in case["fact_witnesses"]:
            assert set(witness) == {"section", "path", "rationale"}
            assert witness["section"] in {
                "policy",
                "applications",
                "roles",
                "conflict_pairs",
                "rules",
            }
            assert witness["path"].startswith("/")
            assert witness["rationale"]
            section = witness["section"]
            assert _resolve(baseline_data[section], witness["path"]) != _resolve(
                active_data[section], witness["path"]
            )
