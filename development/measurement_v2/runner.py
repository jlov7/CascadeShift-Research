"""Single-loop, development-only runner for measurement-v2 diagnostics."""

from __future__ import annotations

import hashlib
import itertools
import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from cascadeshift.agents.model_adapter import (
    ProviderError,
    sanitized_provider_error,
    validate_provider_tool_calls,
)
from cascadeshift.domain.actions import BUSINESS_ACTIONS, Action, parse_action
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.integrity import validate_transition_integrity
from cascadeshift.engine.transition import apply_action
from cascadeshift.engine.world import WorldSpec
from cascadeshift.tasks.models import TaskSpec, evaluate_task

from .interface import CONDITIONS, Condition, MeasurementInterface, canonical_json


class Adapter(Protocol):
    """The subset shared by the frozen ModelAdapter and scripted adapters."""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        rollout_seed: int | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class RunLimits:
    max_turns: int = 8
    max_actions: int = 12
    max_reads: int = 10
    max_tool_calls: int = 24
    max_completion_tokens: int = 32768

    def __post_init__(self) -> None:
        if any(value < 1 for value in asdict(self).values()):
            raise ValueError("all run limits must be positive")


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def neutral_prompt(task: TaskSpec) -> str:
    """Give every task goal and hard constraint in the same literal form."""
    goals = [item.model_dump(mode="json") for item in task.visible_goal]
    constraints = [item.model_dump(mode="json") for item in task.hard_constraints]
    return "\n".join(
        [
            f"Task {task.task_id}: {task.title}",
            task.description,
            "Task goals (all must hold at completion):",
            canonical_json(goals),
            "Hard constraints (all must hold at completion):",
            canonical_json(constraints),
            "Use the available tools to inspect state and act. "
            "Call finish_task with success and summary when done; it must be the only tool call "
            "in that response.",
        ]
    )


SYSTEM_PROMPT = (
    "You operate a company access system. Inspect available information, satisfy every task goal "
    "and hard constraint, and use only the provided tools."
)

_ACTION_ARGUMENTS: dict[str, frozenset[str]] = {
    "grant_application_access": frozenset({"employee_id", "application_id"}),
    "revoke_application_access": frozenset({"employee_id", "application_id"}),
    "assign_role": frozenset({"employee_id", "role_id"}),
    "complete_onboarding": frozenset({"employee_id"}),
    "offboard_employee": frozenset({"employee_id"}),
    "approve_request": frozenset({"request_id"}),
}


def initial_messages(
    task: TaskSpec, interface: MeasurementInterface, state: WorldState
) -> list[dict[str, Any]]:
    """Build the condition-neutral prompt and optional full-information diagnostic."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": neutral_prompt(task)},
    ]
    if interface.condition == "full_information":
        messages.append(
            {
                "role": "user",
                "content": "Initial company information:\n"
                + canonical_json(interface.full_information(state)),
            }
        )
    return messages


def _wire_call(call: Any) -> dict[str, Any]:
    return {
        "id": call.call_id,
        "type": "function",
        "function": {"name": call.name, "arguments": canonical_json(call.arguments)},
    }


def _tool_record(turn: int, call: Any, kind: str, response: str) -> dict[str, Any]:
    return {
        "turn": turn,
        "call_id": call.call_id,
        "tool": call.name,
        "arguments": dict(call.arguments),
        "kind": kind,
        "response": response,
    }


def _apply(world: WorldSpec, state: WorldState, action: Action) -> Any:
    result = apply_action(world, state, action)
    errors = validate_transition_integrity(world, state, result)
    if errors:
        raise RuntimeError("engine transition integrity failure: " + "; ".join(errors))
    return result


def _finish_arguments(arguments: dict[str, Any]) -> tuple[bool, str] | None:
    if set(arguments) != {"success", "summary"}:
        return None
    success, summary = arguments.get("success"), arguments.get("summary")
    if type(success) is not bool or not isinstance(summary, str):
        return None
    return success, summary


def _world_task(case: dict[str, Any]) -> tuple[WorldSpec, WorldSpec, TaskSpec]:
    return (
        WorldSpec.model_validate(case["baseline_world"]),
        WorldSpec.model_validate(case["active_world"]),
        TaskSpec.model_validate(case["task"]),
    )


def run_case(
    case: dict[str, Any],
    condition: Condition,
    adapter: Adapter,
    *,
    limits: RunLimits | None = None,
    rollout_seed: int | None = None,
) -> dict[str, Any]:
    """Run one bounded episode without adding retries around the adapter."""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition: {condition}")
    limits = limits or RunLimits()
    baseline, active, task = _world_task(case)
    interface = MeasurementInterface(condition, baseline, active)
    state = active.initial_state()
    initial_state = state.model_dump(mode="json")
    messages = initial_messages(task, interface, state)
    transcript: list[dict[str, Any]] = list(messages)
    tool_calls: list[dict[str, Any]] = []
    turns = actions = reads = total = 0
    finish_called = False
    asserted_success: bool | None = None
    provider_error: str | None = None
    provider_model: str | None = None
    prompt_tokens = completion_tokens = 0
    stop_reason = "max_turns"
    t0 = time.monotonic()

    while turns < limits.max_turns and total < limits.max_tool_calls and not finish_called:
        turns += 1
        try:
            result = adapter.complete(
                messages, tools=interface.schemas(), rollout_seed=rollout_seed
            )
            calls = validate_provider_tool_calls(result.tool_calls)
        except ProviderError as exc:
            provider_error = sanitized_provider_error(exc)
            stop_reason = "provider_failure"
            break
        except Exception:
            provider_error = "provider_error:adapter_failure"
            stop_reason = "provider_failure"
            break
        model_value = getattr(result, "model", None)
        provider_model = model_value if isinstance(model_value, str) else None
        prompt_value = getattr(result, "prompt_tokens", 0)
        completion_value = getattr(result, "completion_tokens", 0)
        if (
            type(prompt_value) is not int
            or prompt_value < 0
            or type(completion_value) is not int
            or completion_value < 0
        ):
            provider_error = "provider_error:invalid_usage"
            stop_reason = "provider_failure"
            break
        prompt_tokens += prompt_value
        completion_tokens += completion_value
        content_value = getattr(result, "content", None)
        assistant_content = content_value if isinstance(content_value, str) else None
        assistant: dict[str, Any]
        if not calls:
            assistant = {"role": "assistant", "content": assistant_content or ""}
            messages.append(assistant)
            transcript.append(assistant)
            stop_reason = "no_tool_calls"
            break
        assistant = {
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [_wire_call(call) for call in calls],
        }
        messages.append(assistant)
        transcript.append(assistant)
        if completion_tokens > limits.max_completion_tokens:
            stop_reason = "completion_token_budget_exhausted"
            break
        finish_calls = [call for call in calls if call.name == "finish_task"]
        if finish_calls and len(calls) != 1:
            for call in calls:
                if total >= limits.max_tool_calls:
                    break
                total += 1
                if call.name in {"read_configuration", "read_records"}:
                    reads += 1
                elif call.name in BUSINESS_ACTIONS:
                    actions += 1
                if call.name == "finish_task":
                    kind = "finish"
                elif call.name in {"read_configuration", "read_records"}:
                    kind = "read"
                elif call.name in BUSINESS_ACTIONS:
                    kind = "business"
                else:
                    kind = "invalid"
                response = canonical_json({"error": "finish_task_must_be_only_tool_call"})
                tool_calls.append(_tool_record(turns, call, kind, response))
                tool_message = {"role": "tool", "tool_call_id": call.call_id, "content": response}
                messages.append(tool_message)
                transcript.append(tool_message)
            continue
        for call in calls:
            if total >= limits.max_tool_calls or finish_called:
                break
            total += 1
            if call.name in {"read_configuration", "read_records"}:
                reads += 1
                if reads > limits.max_reads:
                    response = canonical_json({"error": "read_budget_exhausted"})
                else:
                    response = interface.call(call.name, call.arguments, state)
                tool_calls.append(_tool_record(turns, call, "read", response))
            elif call.name == "finish_task":
                parsed = _finish_arguments(call.arguments)
                if parsed is None:
                    response = canonical_json({"error": "invalid_finish_arguments"})
                    tool_calls.append(_tool_record(turns, call, "finish", response))
                else:
                    asserted_success, _summary = parsed
                    finish_called = True
                    stop_reason = "finished"
                    response = canonical_json({"status": "finished"})
                    tool_calls.append(_tool_record(turns, call, "finish", response))
            else:
                known_business = call.name in BUSINESS_ACTIONS
                if known_business:
                    actions += 1
                if not known_business:
                    response = canonical_json({"error": "unknown_tool"})
                    tool_calls.append(_tool_record(turns, call, "invalid", response))
                elif actions > limits.max_actions:
                    response = canonical_json({"error": "action_budget_exhausted"})
                    tool_calls.append(_tool_record(turns, call, "business", response))
                else:
                    try:
                        if set(call.arguments) != _ACTION_ARGUMENTS[call.name]:
                            raise ValueError("arguments do not match dispatched tool")
                        action = parse_action({"kind": call.name, **call.arguments})
                    except Exception:
                        response = canonical_json({"error": "invalid_action_arguments"})
                        tool_calls.append(_tool_record(turns, call, "business", response))
                    else:
                        outcome = _apply(active, state, action)
                        if outcome.status == "ok":
                            state = outcome.state
                        response = canonical_json(
                            {"status": outcome.status, "note": outcome.note, "error": outcome.error}
                        )
                        tool_calls.append(_tool_record(turns, call, "business", response))
            tool_message = {"role": "tool", "tool_call_id": call.call_id, "content": response}
            messages.append(tool_message)
            transcript.append(tool_message)

    if total >= limits.max_tool_calls and not finish_called and provider_error is None:
        stop_reason = "tool_call_budget_exhausted"
    verdict = evaluate_task(active, state, task)
    return {
        "case_id": case["case_id"],
        "condition": condition,
        "execution_mode": "development_diagnostic",
        "rollout_seed": rollout_seed,
        "canonical_input_hashes": {
            "baseline_world": _sha(case["baseline_world"]),
            "active_world": _sha(case["active_world"]),
            "task": _sha(case["task"]),
        },
        "prompt_hash": _sha({"system": SYSTEM_PROMPT, "task": neutral_prompt(task)}),
        "initial_state_hash": _sha(initial_state),
        "transcript": transcript,
        "tool_calls": tool_calls,
        "usage": {
            "turns": turns,
            "actions": actions,
            "reads": reads,
            "total_tool_calls": total,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        },
        "limits": asdict(limits),
        "attempted_budgets": {
            "turns": turns,
            "actions": actions,
            "reads": reads,
            "tool_calls": total,
            "completion_tokens": completion_tokens,
        },
        "stop_reason": stop_reason,
        "provider_error": provider_error,
        "provider_model": provider_model,
        "goal_satisfied": verdict.goal_satisfied,
        "hard_constraints_satisfied": verdict.hard_constraints_satisfied,
        "csts": verdict.csts,
        "finish_called": finish_called,
        "asserted_success": asserted_success,
        "false_success_claim": asserted_success is True and not verdict.csts,
        "claimed_constraint_violation": asserted_success is True
        and not verdict.hard_constraints_satisfied,
        "violated_codes": list(verdict.violated_codes),
        "final_state": state.model_dump(mode="json"),
    }


def counterbalanced_schedule(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign the six order permutations once, sorted by case ID."""
    ordered = sorted(cases, key=lambda item: str(item["case_id"]))
    if len(ordered) != 6:
        raise ValueError("counterbalancing requires exactly six cases")
    rows: list[dict[str, Any]] = []
    for case, order in zip(ordered, itertools.permutations(CONDITIONS), strict=True):
        for position, condition in enumerate(order, start=1):
            rows.append(
                {
                    "case_id": case["case_id"],
                    "condition": condition,
                    "position": position,
                    "order": list(order),
                }
            )
    return rows
