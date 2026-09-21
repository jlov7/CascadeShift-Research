from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from development.measurement_v2.__main__ import main
from development.measurement_v2.cases import build_cases
from development.measurement_v2.interface import MeasurementInterface
from development.measurement_v2.validate import validate_cases


def test_valid_cases_pass_and_schedule_has_all_orders() -> None:
    cases = build_cases()
    before = json.dumps(cases, sort_keys=True)
    report = validate_cases(cases)

    assert report["ok"] is True
    assert len(report["schedule"]) == 18
    assert {tuple(row["order"]) for row in report["schedule"]} == {
        ("frozen", "current", "full_information"),
        ("frozen", "full_information", "current"),
        ("current", "frozen", "full_information"),
        ("current", "full_information", "frozen"),
        ("full_information", "frozen", "current"),
        ("full_information", "current", "frozen"),
    }
    assert json.dumps(cases, sort_keys=True) == before


def test_validator_rejects_irrelevant_changed_witness() -> None:
    cases = copy.deepcopy(build_cases())
    case = cases[0]
    case["active_world"]["applications"][0]["name"] = "Unrelated rename"
    case["fact_witnesses"] = [
        {
            "section": "applications",
            "path": "/0/name",
            "rationale": "A changed but irrelevant name.",
        }
    ]
    report = validate_cases(cases)
    assert any(error["check"] == "witness_causality" for error in report["errors"])


def test_validator_rejects_identical_treatment_invalid_pointer_and_failed_plan() -> None:
    identical = copy.deepcopy(build_cases())
    identical[0]["active_world"] = copy.deepcopy(identical[0]["baseline_world"])
    assert validate_cases(identical)["ok"] is False

    invalid_pointer = copy.deepcopy(build_cases())
    invalid_pointer[0]["fact_witnesses"][0]["path"] = "/999/not-a-value"
    assert any(
        error["check"] == "fact_witnesses" for error in validate_cases(invalid_pointer)["errors"]
    )

    failed_plan = copy.deepcopy(build_cases())
    failed_plan[0]["active_plan"] = copy.deepcopy(failed_plan[0]["baseline_plan"])
    assert any(error["check"] == "active_plan" for error in validate_cases(failed_plan)["errors"])


def test_validator_rejects_broken_record_wire(monkeypatch) -> None:
    original = MeasurementInterface.call

    def broken(self, name, arguments, state):
        if name == "read_records":
            return "{}"
        return original(self, name, arguments, state)

    monkeypatch.setattr(MeasurementInterface, "call", broken)
    report = validate_cases(build_cases())
    assert any(error["check"] == "configuration_access" for error in report["errors"])


def test_validator_rejects_broken_nonwitness_configuration_wire(monkeypatch) -> None:
    original = MeasurementInterface.call

    def broken(self, name, arguments, state):
        if name == "read_configuration" and arguments.get("section") == "rules":
            return json.dumps({"section": "rules", "value": []})
        return original(self, name, arguments, state)

    monkeypatch.setattr(MeasurementInterface, "call", broken)
    report = validate_cases(build_cases())
    assert any(error["check"] == "configuration_access" for error in report["errors"])


def test_validate_command_creates_absent_output_parent(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "new" / "nested" / "construction.json"
    monkeypatch.setattr(sys, "argv", ["measurement-v2", "validate", "--out", str(output)])

    assert main() == 0
    assert json.loads(output.read_text())["ok"] is True
