from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from development.measurement_v2.cases import build_cases
from development.measurement_v2.runner import RunLimits, run_case

from cascadeshift.agents.model_adapter import CompletionResult, ProviderError, ToolCallOut


@dataclass
class ScriptedAdapter:
    responses: list[CompletionResult]
    requests: int = 0

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        rollout_seed: int | None = None,
    ) -> CompletionResult:
        del messages, tools, rollout_seed
        self.requests += 1
        return self.responses.pop(0)


def _result(*calls: ToolCallOut, content: str | None = None) -> CompletionResult:
    return CompletionResult(calls, content, 1, 1, "scripted")


def _call(name: str, arguments: dict[str, Any], number: int = 1) -> ToolCallOut:
    return ToolCallOut(f"call-{number}", name, arguments)


def test_explicit_true_and_false_success_are_distinct() -> None:
    case = build_cases()[0]
    failed = run_case(
        case,
        "current",
        ScriptedAdapter([_result(_call("finish_task", {"success": True, "summary": "done"}))]),
    )
    assert failed["finish_called"] and failed["asserted_success"] is True
    assert failed["false_success_claim"] is True
    assert failed["goal_satisfied"] is False
    assert failed["hard_constraints_satisfied"] is True
    assert failed["claimed_constraint_violation"] is False

    responses = [
        _result(
            _call(
                action["kind"],
                {key: value for key, value in action.items() if key != "kind"},
                index,
            )
        )
        for index, action in enumerate(case["active_plan"], 1)
    ]
    responses.append(_result(_call("finish_task", {"success": False, "summary": "declined"})))
    succeeded = run_case(case, "current", ScriptedAdapter(responses))
    assert succeeded["csts"] is True
    assert succeeded["asserted_success"] is False
    assert succeeded["false_success_claim"] is False


def test_constraint_failure_and_runtime_records_are_reported_separately() -> None:
    case = build_cases()[0]
    baseline_action = case["baseline_plan"][0]
    action = _call(
        baseline_action["kind"],
        {key: value for key, value in baseline_action.items() if key != "kind"},
    )
    result = run_case(
        case,
        "current",
        ScriptedAdapter(
            [
                _result(action),
                _result(_call("read_records", {})),
                _result(_call("finish_task", {"success": True, "summary": "done"})),
            ]
        ),
    )
    assert result["goal_satisfied"] is True
    assert result["hard_constraints_satisfied"] is False
    assert result["claimed_constraint_violation"] is True
    assert result["false_success_claim"] is True
    records = json.loads(result["tool_calls"][1]["response"])
    assert records["employees"] != case["active_world"]["employees"]


def test_injected_kind_is_rejected_without_action() -> None:
    case = build_cases()[0]
    injected = _call(
        "grant_application_access",
        {"employee_id": "E-001", "application_id": "APP-TARGET", "kind": "finish_task"},
    )
    result = run_case(
        case,
        "current",
        ScriptedAdapter(
            [
                _result(injected),
                _result(_call("finish_task", {"success": False, "summary": "stop"})),
            ]
        ),
    )
    assert json.loads(result["tool_calls"][0]["response"])["error"] == "invalid_action_arguments"
    assert result["usage"]["actions"] == 1
    assert result["finish_called"] is True


def test_transcript_keeps_content_with_tool_calls() -> None:
    case = build_cases()[0]
    result = run_case(
        case,
        "current",
        ScriptedAdapter(
            [
                _result(_call("read_records", {}), content="I will inspect the records."),
                _result(_call("finish_task", {"success": False, "summary": "stop"})),
            ]
        ),
    )
    assert result["transcript"][2]["content"] == "I will inspect the records."


def test_invalid_reads_count_and_provider_failure_is_separate() -> None:
    case = build_cases()[0]
    adapter = ScriptedAdapter(
        [
            _result(_call("read_records", {"unexpected": True})),
            _result(_call("finish_task", {"success": False, "summary": "stop"})),
        ]
    )
    result = run_case(case, "frozen", adapter, limits=RunLimits(max_reads=1))
    assert result["usage"]["reads"] == 1
    assert (
        json.loads(result["tool_calls"][0]["response"])["error"] == "invalid_read_records_arguments"
    )

    sibling_finish = run_case(
        case,
        "frozen",
        ScriptedAdapter(
            [
                _result(
                    _call("read_records", {}, 1),
                    _call("finish_task", {"success": False, "summary": "stop"}, 2),
                ),
                _result(_call("finish_task", {"success": False, "summary": "stop"})),
            ]
        ),
    )
    assert sibling_finish["usage"]["reads"] == 1
    assert json.loads(sibling_finish["tool_calls"][0]["response"]) == {
        "error": "finish_task_must_be_only_tool_call"
    }
    assert [item["kind"] for item in sibling_finish["tool_calls"][:2]] == ["read", "finish"]

    class FailingAdapter:
        def complete(self, *args: Any, **kwargs: Any) -> CompletionResult:
            raise ProviderError("provider_error:transport_failure")

    failed = run_case(case, "frozen", FailingAdapter())
    assert failed["provider_error"] == "provider_error:transport_failure"
    assert failed["stop_reason"] == "provider_failure"


def test_turn_read_and_action_budgets_prevent_additional_effects() -> None:
    case = build_cases()[0]
    turn_limited = run_case(
        case,
        "current",
        ScriptedAdapter(
            [
                _result(_call("read_records", {})),
                _result(_call("finish_task", {"success": False, "summary": "late"})),
            ]
        ),
        limits=RunLimits(max_turns=1),
    )
    assert turn_limited["stop_reason"] == "max_turns"
    assert turn_limited["finish_called"] is False

    read_limited = run_case(
        case,
        "current",
        ScriptedAdapter(
            [
                _result(_call("read_records", {})),
                _result(_call("read_records", {})),
                _result(_call("finish_task", {"success": False, "summary": "stop"})),
            ]
        ),
        limits=RunLimits(max_reads=1),
    )
    assert read_limited["usage"]["reads"] == 2
    assert json.loads(read_limited["tool_calls"][1]["response"]) == {
        "error": "read_budget_exhausted"
    }

    first, second = case["active_plan"][:2]
    action_limited = run_case(
        case,
        "current",
        ScriptedAdapter(
            [
                _result(_call(first["kind"], {k: v for k, v in first.items() if k != "kind"})),
                _result(_call(second["kind"], {k: v for k, v in second.items() if k != "kind"})),
                _result(_call("finish_task", {"success": False, "summary": "stop"})),
            ]
        ),
        limits=RunLimits(max_actions=1),
    )
    assert action_limited["usage"]["actions"] == 2
    assert json.loads(action_limited["tool_calls"][1]["response"]) == {
        "error": "action_budget_exhausted"
    }
