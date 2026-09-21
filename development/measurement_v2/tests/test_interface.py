from __future__ import annotations

import json

from development.measurement_v2.cases import build_cases
from development.measurement_v2.interface import CONFIG_SECTIONS, MeasurementInterface
from development.measurement_v2.runner import initial_messages

from cascadeshift.domain.state import WorldState
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec


def _models() -> tuple[WorldSpec, WorldSpec, TaskSpec]:
    case = build_cases()[0]
    return (
        WorldSpec.model_validate(case["baseline_world"]),
        WorldSpec.model_validate(case["active_world"]),
        TaskSpec.model_validate(case["task"]),
    )


def test_conditions_share_schemas_prompt_and_neutral_records() -> None:
    baseline, active, task = _models()
    state = active.initial_state()
    frozen = MeasurementInterface("frozen", baseline, active)
    current = MeasurementInterface("current", baseline, active)

    assert frozen.schemas() == current.schemas()
    assert initial_messages(task, frozen, state) == initial_messages(task, current, state)
    expected = json.loads(frozen.call("read_records", {}, state))
    assert expected == json.loads(current.call("read_records", {}, state))
    assert set(expected) == {"employees", "requests", "review_required"}


def test_configuration_is_condition_selected_and_records_hide_overrides() -> None:
    baseline, active, _task = _models()
    rule_id = active.rules[0].rule_id
    state = WorldState(
        employees=active.initial_state().employees,
        rule_status_overrides=((rule_id, "inactive"),),
    )
    frozen = MeasurementInterface("frozen", baseline, active)
    current = MeasurementInterface("current", baseline, active)

    for section in CONFIG_SECTIONS:
        assert (
            json.loads(frozen.call("read_configuration", {"section": section}, state))["value"]
            == (baseline.model_dump(mode="json")[section])
        )
    current_rules = json.loads(current.call("read_configuration", {"section": "rules"}, state))[
        "value"
    ]
    assert (
        next(rule for rule in current_rules if rule["rule_id"] == rule_id)["status"] == "inactive"
    )
    assert "rule_status_overrides" not in json.loads(current.call("read_records", {}, state))


def test_full_information_contains_all_active_sections_and_initial_records() -> None:
    baseline, active, task = _models()
    interface = MeasurementInterface("full_information", baseline, active)
    content = initial_messages(task, interface, active.initial_state())[-1]["content"]
    payload = json.loads(content.removeprefix("Initial company information:\n"))

    assert set(payload["configuration"]) == set(CONFIG_SECTIONS)
    assert payload["configuration"]["policy"] == active.model_dump(mode="json")["policy"]
    assert payload["records"] == json.loads(
        interface.call("read_records", {}, active.initial_state())
    )
