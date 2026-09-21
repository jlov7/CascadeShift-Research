"""Deterministic construction gate for measurement-v2 cases."""

from __future__ import annotations

import copy
import itertools
import json
from collections import Counter
from typing import Any

from cascadeshift.domain.actions import FinishTask, parse_action
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec, evaluate_task
from cascadeshift.tasks.oracle import verify_plan

from .interface import CONDITIONS, CONFIG_SECTIONS, MeasurementInterface, canonical_json
from .runner import counterbalanced_schedule, initial_messages


def _pointer(value: Any, path: object) -> Any:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("pointer must start with '/'")
    current = value
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdecimal() or str(int(token)) != token:
                raise ValueError("invalid list pointer")
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError("pointer passes through scalar")
    return current


def _set_pointer(value: Any, path: object, replacement: Any) -> None:
    """Set a non-root RFC-6901 path while rejecting scalar parents."""
    if not isinstance(path, str) or path == "/" or not path.startswith("/"):
        raise ValueError("pointer must name a non-root value")
    tokens = [token.replace("~1", "/").replace("~0", "~") for token in path[1:].split("/")]
    current = value
    for token in tokens[:-1]:
        if isinstance(current, list):
            if not token.isdecimal() or str(int(token)) != token:
                raise ValueError("invalid list pointer")
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError("pointer passes through scalar")
    final = tokens[-1]
    if isinstance(current, list):
        if not final.isdecimal() or str(int(final)) != final:
            raise ValueError("invalid list pointer")
        current[int(final)] = replacement
    elif isinstance(current, dict):
        if final not in current:
            raise ValueError("pointer key missing")
        current[final] = replacement
    else:
        raise ValueError("pointer parent is scalar")


def _plans(value: object) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise ValueError("plan must be a list")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("plan action must be an object")
        action = parse_action(dict(item))
        if isinstance(action, FinishTask):
            raise ValueError("plans must not include finish_task")
        result.append(action)
    return tuple(result)


def _error(errors: list[dict[str, str]], case_id: object, check: str, detail: str) -> None:
    errors.append({"case_id": str(case_id), "check": check, "detail": detail})


def validate_cases(cases: object) -> dict[str, Any]:
    """Validate construction facts without running a model or changing inputs."""
    original = canonical_json(cases)
    errors: list[dict[str, str]] = []
    if not isinstance(cases, list):
        return {
            "ok": False,
            "case_count": 0,
            "errors": [{"case_id": "", "check": "cases", "detail": "must be a list"}],
            "schedule": [],
        }
    ids = [item.get("case_id") if isinstance(item, dict) else None for item in cases]
    invalid_ids = any(not isinstance(item, str) or not item for item in ids)
    if len(ids) != len(set(map(str, ids))) or invalid_ids:
        _error(errors, "", "unique_case_ids", "case_id values must be present and unique")
    if len(cases) != 6:
        _error(errors, "", "case_count", "exactly six cases are required")
    for raw in cases:
        case_id = raw.get("case_id", "") if isinstance(raw, dict) else ""
        if not isinstance(raw, dict):
            _error(errors, case_id, "case_shape", "case must be an object")
            continue
        required = {
            "case_id",
            "purpose",
            "baseline_world",
            "active_world",
            "task",
            "baseline_plan",
            "active_plan",
            "fact_witnesses",
        }
        missing = sorted(required - set(raw))
        if missing:
            _error(errors, case_id, "case_shape", "missing " + ",".join(missing))
            continue
        try:
            baseline = WorldSpec.model_validate(raw["baseline_world"])
            active = WorldSpec.model_validate(raw["active_world"])
            task = TaskSpec.model_validate(raw["task"])
        except Exception as exc:
            _error(errors, case_id, "models", str(exc).split("\n", 1)[0])
            continue
        baseline_employees = [item.model_dump(mode="json") for item in baseline.employees]
        active_employees = [item.model_dump(mode="json") for item in active.employees]
        if canonical_json(baseline_employees) != canonical_json(active_employees):
            _error(errors, case_id, "shared_records", "baseline and active employee records differ")
        # Exercise actual wires against authoritative serialized inputs.
        frozen = MeasurementInterface("frozen", baseline, active)
        current = MeasurementInterface("current", baseline, active)
        try:
            for section in CONFIG_SECTIONS:
                frozen_wire = json.loads(
                    frozen.call("read_configuration", {"section": section}, active.initial_state())
                )
                current_wire = json.loads(
                    current.call("read_configuration", {"section": section}, active.initial_state())
                )
                if frozen_wire.get("section") != section or "value" not in frozen_wire:
                    raise ValueError("frozen configuration wire response is malformed")
                if current_wire.get("section") != section or "value" not in current_wire:
                    raise ValueError("current configuration wire response is malformed")
                baseline_value = baseline.model_dump(mode="json")[section]
                active_value = active.model_dump(mode="json")[section]
                if canonical_json(frozen_wire["value"]) != canonical_json(baseline_value):
                    raise ValueError(f"frozen {section} does not match baseline input")
                if canonical_json(current_wire["value"]) != canonical_json(active_value):
                    raise ValueError(f"current {section} does not match active input")
            records = [
                json.loads(
                    MeasurementInterface(condition, baseline, active).call(
                        "read_records", {}, active.initial_state()
                    )
                )
                for condition in CONDITIONS
            ]
            if len({canonical_json(value) for value in records}) != 1:
                raise ValueError("read_records differs across conditions")
            expected_records = {
                "employees": [
                    item.model_dump(mode="json") for item in active.initial_state().employees
                ],
                "requests": [],
                "review_required": [],
            }
            if any(canonical_json(value) != canonical_json(expected_records) for value in records):
                raise ValueError("read_records does not match active initial records")
            full = MeasurementInterface("full_information", baseline, active)
            full_messages = initial_messages(task, full, active.initial_state())
            full_prefix = "Initial company information:\n"
            full_content = full_messages[-1].get("content", "")
            if not isinstance(full_content, str) or not full_content.startswith(full_prefix):
                raise ValueError("full-information initial payload is absent")
            expected_full = {
                "configuration": {
                    section: active.model_dump(mode="json")[section] for section in CONFIG_SECTIONS
                },
                "records": expected_records,
            }
            actual_full = json.loads(full_content.removeprefix(full_prefix))
            if canonical_json(actual_full) != canonical_json(expected_full):
                raise ValueError("full-information initial payload is incomplete")
        except Exception as exc:
            _error(errors, case_id, "configuration_access", str(exc))
        if canonical_json(frozen.schemas()) != canonical_json(current.schemas()):
            _error(errors, case_id, "schema_equality", "frozen and current schemas differ")
        frozen_messages = initial_messages(task, frozen, active.initial_state())
        current_messages = initial_messages(task, current, active.initial_state())
        if frozen_messages != current_messages:
            _error(errors, case_id, "prompt_equality", "frozen and current initial prompts differ")
        baseline_initial = evaluate_task(baseline, baseline.initial_state(), task)
        active_initial = evaluate_task(active, active.initial_state(), task)
        if baseline_initial.csts or active_initial.csts:
            _error(errors, case_id, "initial_state", "initial state is already CSTS")
        baseline_plan: tuple[Any, ...] = ()
        plans_valid = False
        try:
            baseline_plan = _plans(raw["baseline_plan"])
            active_plan = _plans(raw["active_plan"])
            plans_valid = True
            if not verify_plan(baseline, task, baseline_plan).csts:
                _error(
                    errors, case_id, "baseline_plan", "baseline plan does not succeed in baseline"
                )
            if verify_plan(active, task, baseline_plan).csts:
                _error(errors, case_id, "baseline_plan", "baseline plan does not fail in active")
            if not verify_plan(active, task, active_plan).csts:
                _error(errors, case_id, "active_plan", "active plan does not succeed in active")
        except Exception as exc:
            _error(errors, case_id, "plans", str(exc).split("\n", 1)[0])
        witnesses = raw["fact_witnesses"]
        restored = active.model_dump(mode="json")
        restored_witnesses = 0
        if not isinstance(witnesses, list) or not witnesses:
            _error(errors, case_id, "fact_witnesses", "at least one witness is required")
        else:
            for witness in witnesses:
                try:
                    if not isinstance(witness, dict) or set(witness) != {
                        "section",
                        "path",
                        "rationale",
                    }:
                        raise ValueError("witness keys must be section,path,rationale")
                    section = witness["section"]
                    valid_rationale = isinstance(witness["rationale"], str) and bool(
                        witness["rationale"].strip()
                    )
                    if section not in CONFIG_SECTIONS or not valid_rationale:
                        raise ValueError("invalid witness section or rationale")
                    base_wire = json.loads(
                        frozen.call(
                            "read_configuration", {"section": section}, active.initial_state()
                        )
                    )
                    active_wire = json.loads(
                        current.call(
                            "read_configuration", {"section": section}, active.initial_state()
                        )
                    )
                    base_value = _pointer(base_wire["value"], witness["path"])
                    active_value = _pointer(active_wire["value"], witness["path"])
                    if canonical_json(base_value) == canonical_json(active_value):
                        raise ValueError("witness does not identify a changed value")
                    _set_pointer(restored[section], witness["path"], copy.deepcopy(base_value))
                    restored_witnesses += 1
                except Exception as exc:
                    _error(errors, case_id, "fact_witnesses", str(exc))
            if plans_valid and restored_witnesses == len(witnesses):
                try:
                    restored_world = WorldSpec.model_validate(restored)
                    if not verify_plan(restored_world, task, baseline_plan).csts:
                        _error(
                            errors,
                            case_id,
                            "witness_causality",
                            "restoring declared facts does not restore baseline-plan success",
                        )
                except Exception as exc:
                    _error(errors, case_id, "witness_causality", str(exc).split("\n", 1)[0])
    schedule: list[dict[str, Any]] = []
    valid_case_ids = all(
        isinstance(item, dict) and isinstance(item.get("case_id"), str) for item in cases
    )
    if len(cases) == 6 and valid_case_ids:
        try:
            schedule = counterbalanced_schedule(copy.deepcopy(cases))
            orders = {tuple(item["order"]) for item in schedule if item["position"] == 1}
            counts = Counter((item["condition"], item["position"]) for item in schedule)
            expected = set(itertools.permutations(CONDITIONS))
            balanced_positions = all(
                counts[(condition, position)] == 2
                for condition in CONDITIONS
                for position in (1, 2, 3)
            )
            if orders != expected or not balanced_positions:
                _error(
                    errors,
                    "",
                    "counterbalance",
                    "orders do not use each permutation once with two positions per condition",
                )
        except Exception as exc:
            _error(errors, "", "counterbalance", str(exc))
    unchanged = canonical_json(cases) == original
    if not unchanged:
        _error(errors, "", "input_immutability", "validation mutated its input")
    return {
        "ok": not errors,
        "case_count": len(cases),
        "errors": sorted(errors, key=lambda item: (item["case_id"], item["check"], item["detail"])),
        "schedule": schedule,
        "input_unchanged": unchanged,
    }
