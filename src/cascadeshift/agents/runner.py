"""Single parameterized episode runner for all conditions (A-01..A-04).

One core loop; conditions differ ONLY in which configuration snapshot the
discovery backend reads and whether discovery tools are exposed.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Literal

from cascadeshift.agents.conditions import condition_spec, make_tools
from cascadeshift.agents.model_adapter import (
    ModelAdapter,
    ProviderError,
    sanitized_provider_error,
    validate_provider_tool_calls,
)
from cascadeshift.agents.prompts import SYSTEM_PROMPT, task_prompt
from cascadeshift.agents.protocol import (
    CONDITION_LABELS,
    DynamicsMode,
    EpisodeRecord,
    RetrievalLog,
    ToolCallRecord,
    UsageRecord,
)
from cascadeshift.agents.scripted import (
    BusinessStep,
    DiscoverStep,
    DiscoveryScripted,
    ScriptedAgent,
    Step,
    SurfaceScripted,
)
from cascadeshift.domain.actions import BUSINESS_ACTIONS, Action, FinishTask, parse_action
from cascadeshift.domain.state import WorldState
from cascadeshift.engine.events import Event
from cascadeshift.engine.integrity import validate_transition_integrity
from cascadeshift.engine.transition import TransitionResult, apply_action
from cascadeshift.engine.world import WorldSpec
from cascadeshift.retrieval.relevance import oracle_causal_closure, retrieval_metrics
from cascadeshift.tasks.models import TaskSpec, evaluate_task

MAX_MODEL_TURNS = 24
MAX_BUSINESS_ACTIONS = 12
MAX_DISCOVERY_CALLS = 10


def _apply_verified_action(world: WorldSpec, state: WorldState, action: Action) -> TransitionResult:
    result = apply_action(world, state, action)
    problems = validate_transition_integrity(world, state, result)
    if problems:
        raise RuntimeError("engine transition integrity failure: " + "; ".join(problems))
    return result


def rollout_seed_id(task_world_id: str, repeat: int) -> str:
    """Matched across conditions for the same task-world and repeat."""
    raw = f"{task_world_id}|{repeat}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def rollout_provider_seed(task_world_id: str, repeat: int) -> int:
    """Deterministic integer seed matched across conditions for a rollout."""
    raw = f"{task_world_id}|{repeat}"
    return int.from_bytes(hashlib.sha256(raw.encode()).digest()[:4], "big") & 0x7FFFFFFF


def _function_schema(
    name: str,
    description: str,
    properties: dict[str, dict[str, str]],
    required: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


def business_tool_schemas() -> list[dict[str, Any]]:
    """Canonical OpenAI function contracts for every business action and finish."""
    string = {"type": "string"}
    schemas = [
        _function_schema(
            "grant_application_access",
            "Grant an employee access to an application.",
            {"employee_id": string, "application_id": string},
            ("employee_id", "application_id"),
        ),
        _function_schema(
            "revoke_application_access",
            "Revoke an employee's application access.",
            {"employee_id": string, "application_id": string},
            ("employee_id", "application_id"),
        ),
        _function_schema(
            "assign_role",
            "Assign a role to an employee.",
            {"employee_id": string, "role_id": string},
            ("employee_id", "role_id"),
        ),
        _function_schema(
            "complete_onboarding",
            "Complete an employee's onboarding.",
            {"employee_id": string},
            ("employee_id",),
        ),
        _function_schema(
            "offboard_employee",
            "Offboard an employee.",
            {"employee_id": string},
            ("employee_id",),
        ),
        _function_schema(
            "approve_request",
            "Approve a pending access request.",
            {"request_id": string},
            ("request_id",),
        ),
        _function_schema(
            "finish_task",
            "Finish the task and provide a short summary.",
            {"summary": string},
            ("summary",),
        ),
    ]
    if tuple(schema["function"]["name"] for schema in schemas[:-1]) != BUSINESS_ACTIONS:
        raise RuntimeError("business tool schema order diverges from BUSINESS_ACTIONS")
    return schemas


def extract_goals(task: TaskSpec) -> tuple[str, list[tuple[str, str]]]:
    """Derive (primary_employee, ordered visible-goal steps) for scripts."""
    employee = ""
    goals: list[tuple[str, str]] = []
    for g in task.visible_goal:
        d = g.model_dump()
        k = d.get("kind")
        emp = str(d.get("employee_id", ""))
        employee = employee or emp
        if k == "goal_entitlement_present":
            goals.append(("grant", str(d["application_id"])))
        elif k == "entitlement_absent":
            goals.append(("revoke", str(d["application_id"])))
        elif k == "role_is":
            goals.append(("role", str(d["role_id"])))
        elif k == "status_is" and d.get("status") == "inactive":
            goals.append(("offboard", ""))
        elif k == "status_is" and d.get("status") == "active":
            goals.append(("onboard", ""))
    return employee, goals


class EpisodeRunner:
    def __init__(
        self,
        baseline_world: WorldSpec,
        *,
        max_model_turns: int = MAX_MODEL_TURNS,
        max_business_actions: int = MAX_BUSINESS_ACTIONS,
        max_discovery_calls: int = MAX_DISCOVERY_CALLS,
        token_budget: int = 60000,
    ) -> None:
        self.baseline_world = baseline_world
        self.max_model_turns = max_model_turns
        self.max_business_actions = max_business_actions
        self.max_discovery_calls = max_discovery_calls
        self.token_budget = token_budget
        self._causal_closure_cache: dict[tuple[str, str], frozenset[str]] = {}

    def _causal_closure(self, world: WorldSpec, task: TaskSpec) -> frozenset[str]:
        task_digest = hashlib.sha256(task.model_dump_json().encode()).hexdigest()
        key = (world.content_hash(), task_digest)
        if key not in self._causal_closure_cache:
            self._causal_closure_cache[key] = oracle_causal_closure(world, task)
        return self._causal_closure_cache[key]

    # ------------------------------------------------------------------

    def run_scripted(
        self,
        *,
        split: str,
        case_id: str,
        parent_task_id: str,
        task: TaskSpec,
        world: WorldSpec,
        condition: DynamicsMode,
        repeat: int = 1,
    ) -> EpisodeRecord:
        spec = condition_spec(condition)
        tools = make_tools(spec, self.baseline_world, world)
        policy: ScriptedAgent
        if condition == "surface":
            policy = SurfaceScripted()
        else:
            policy = DiscoveryScripted()
        employee_id, goals = extract_goals(task)
        policy.bind_goals(employee_id, goals)

        state = world.initial_state()
        events_out: list[Any] = []
        tool_calls: list[ToolCallRecord] = []
        c_business = 0
        c_disc = 0
        c_total = 0
        retrieval_q: list[str] = []
        retrieved_ids: list[str] = []
        retrieved_call_indexes: list[int] = []
        inspected: list[str] = []
        inspected_call_indexes: list[int] = []
        fired: list[str] = []
        claimed = False
        label = CONDITION_LABELS[condition]
        seed_id = rollout_seed_id(f"{case_id}|{world.world_id}", repeat)

        def observe_for_policy(res: TransitionResult, action_name: str) -> dict[str, Any]:
            obs: dict[str, Any] = {
                "obs_kind": "business",
                "action": action_name,
                "note": res.note or res.error,
            }
            if res.note == "request_created" and res.state.requests:
                obs["request_id"] = res.state.requests[-1].request_id
                obs["application_id"] = res.state.requests[-1].application_id
            elif res.events:
                ev = res.events[0]
                obs["employee_id"] = ev.employee_id
                obs["application_id"] = ev.application_id
                obs["role_id"] = None
                if res.note in ("assigned", "already_role"):
                    for c in res.events[0].changes:
                        if c.field == "role_id":
                            obs["role_id"] = c.after
            return obs

        turns = 0
        while turns < self.max_model_turns * 4:
            turns += 1
            step: Step = policy.step()
            if isinstance(step, DiscoverStep):
                if tools is None or c_disc >= self.max_discovery_calls:
                    break
                resp_raw = tools.call(step.tool, dict(step.args))
                c_disc += 1
                c_total += 1
                tool_calls.append(
                    ToolCallRecord(
                        turn=turns,
                        tool=step.tool,
                        args=dict(step.args),
                        response_canonical=resp_raw,
                        kind="discovery",
                    )
                )
                parsed = json.loads(resp_raw)
                if step.tool == "search_rules":
                    retrieval_q.append(str(step.args.get("query", "")))
                    for r_ in parsed.get("results", []):
                        retrieved_ids.append(r_["rule_id"])
                        retrieved_call_indexes.append(c_disc)
                    policy.observe(
                        {"obs_kind": "discovery_search", "results": parsed.get("results", [])}
                    )
                elif step.tool == "inspect_rule":
                    inspected.append(str(step.args.get("rule_id")))
                    inspected_call_indexes.append(c_disc)
                    policy.observe({"obs_kind": "discovery_inspect", "record": parsed})
                else:
                    policy.observe({"obs_kind": "discovery_other"})
                continue
            if not isinstance(step, BusinessStep):
                raise RuntimeError("scripted agent emitted an unsupported step")
            action = step.action
            if isinstance(action, FinishTask):
                claimed = True
                break
            if c_business >= self.max_business_actions:
                break
            res = _apply_verified_action(world, state, action)
            c_business += 1
            c_total += 1
            if res.status == "ok":
                state = res.state
                fired.extend(res.fired_rule_ids)
                events_out.extend(res.events)
                policy.observe(observe_for_policy(res, action.kind))
            else:
                policy.observe(
                    {
                        "obs_kind": "business",
                        "action": action.kind,
                        "note": res.note or "rejected",
                        "error": res.error,
                    }
                )

        verdict = evaluate_task(world, state, task)
        silent = claimed and not verdict.csts
        closure = self._causal_closure(world, task)
        retrieval_values = retrieval_metrics(
            tuple(retrieved_ids),
            tuple(inspected),
            closure,
            returned_call_indexes=tuple(retrieved_call_indexes),
            inspected_call_indexes=tuple(inspected_call_indexes),
        )
        return EpisodeRecord(
            episode_id=f"{case_id}-{label}-r{repeat}",
            split=split,  # type: ignore[arg-type]
            case_id=case_id,
            parent_task_id=parent_task_id,
            family=task.family,
            condition=condition,
            rollout_seed_id=seed_id,
            execution_mode="scripted",
            world_id=world.world_id,
            world_hash=world.content_hash(),
            baseline_world_hash=self.baseline_world.content_hash(),
            task_text_hash=hashlib.sha256(task_prompt(task).encode()).hexdigest()[:16],
            system_prompt_hash=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:16],
            events=tuple(events_out),
            tool_calls=tuple(tool_calls),
            usage=UsageRecord(
                model_turns=0,
                business_actions=c_business,
                discovery_calls=c_disc,
                total_tool_calls=c_total,
            ),
            retrieval=RetrievalLog(
                queries=tuple(retrieval_q),
                returned_rule_ids=tuple(retrieved_ids),
                inspected_rule_ids=tuple(inspected),
                causal_closure_rule_ids=tuple(sorted(closure)),
                causal_closure_computed=True,
                **retrieval_values,
            ),
            fired_rules=tuple(dict.fromkeys(fired)),
            claimed_success=claimed,
            verdict=verdict,
            claim_outcome_match=claimed == verdict.csts,
            silent_violation=silent,
        )

    # ------------------------------------------------------------------

    def run_live(
        self,
        *,
        adapter: ModelAdapter,
        split: str,
        case_id: str,
        parent_task_id: str,
        task: TaskSpec,
        world: WorldSpec,
        condition: DynamicsMode,
        repeat: int = 1,
    ) -> EpisodeRecord:
        spec = condition_spec(condition)
        tools = make_tools(spec, self.baseline_world, world)
        schemas = business_tool_schemas()
        if tools is not None:
            schemas.extend(tools.schemas())
        label = CONDITION_LABELS[condition]
        seed_id = rollout_seed_id(f"{case_id}|{world.world_id}", repeat)
        provider_seed = rollout_provider_seed(f"{case_id}|{world.world_id}", repeat)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt(task)},
        ]
        state = world.initial_state()
        events_out: list[Event] = []
        tool_calls: list[ToolCallRecord] = []
        c_business = 0
        c_disc = 0
        c_total = 0
        c_prompt = 0
        c_completion = 0
        c_turns = 0
        retrieval_q: list[str] = []
        retrieved_ids: list[str] = []
        retrieved_call_indexes: list[int] = []
        inspected: list[str] = []
        inspected_call_indexes: list[int] = []
        fired: list[str] = []
        claimed = False
        provider_error: str | None = None
        provider_model: str | None = None
        seed_capability = getattr(adapter, "supports_seed", None)
        seed_supported: bool | None = seed_capability if isinstance(seed_capability, bool) else None
        requested_provider_seed = provider_seed if seed_supported else None

        t0 = time.monotonic()
        turn = 0
        try:
            while turn < self.max_model_turns:
                turn += 1
                result = adapter.complete(messages, tools=schemas, rollout_seed=provider_seed)
                c_turns += 1
                c_prompt += result.prompt_tokens
                c_completion += result.completion_tokens
                provider_model = result.model
                if c_prompt + c_completion > self.token_budget:
                    break
                calls = validate_provider_tool_calls(result.tool_calls)
                if not calls:
                    messages.append({"role": "assistant", "content": result.content or ""})
                    break
                msg_tool: dict[str, Any] = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": c.call_id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in calls
                    ],
                }
                messages.append(msg_tool)
                stop = False
                finish_calls = [call for call in calls if call.name == "finish_task"]
                if finish_calls and len(calls) != 1:
                    content = json.dumps({"error": "finish_task_must_be_only_tool_call"})
                    for c in calls:
                        c_total += 1
                        kind: Literal["discovery", "business", "finish"] = (
                            "finish"
                            if c.name == "finish_task"
                            else (
                                "discovery"
                                if spec.expose_discovery
                                and tools is not None
                                and c.name in tools.names
                                else "business"
                            )
                        )
                        tool_calls.append(
                            ToolCallRecord(
                                turn=turn,
                                tool=c.name,
                                args=dict(c.arguments),
                                response_canonical=content,
                                kind=kind,
                            )
                        )
                        messages.append(
                            {"role": "tool", "tool_call_id": c.call_id, "content": content}
                        )
                    continue
                for c in calls:
                    c_total += 1
                    if c.name == "finish_task":
                        claimed = True
                        stop = True
                        tool_calls.append(
                            ToolCallRecord(
                                turn=turn,
                                tool=c.name,
                                args=dict(c.arguments),
                                response_canonical="{}",
                                kind="finish",
                            )
                        )
                        messages.append(
                            {"role": "tool", "tool_call_id": c.call_id, "content": "acknowledged"}
                        )
                        break
                    if spec.expose_discovery and tools is not None and c.name in tools.names:
                        if c_disc >= self.max_discovery_calls:
                            content = json.dumps({"error": "discovery_budget_exhausted"})
                        else:
                            resp_raw = tools.call(c.name, c.arguments)
                            content = resp_raw
                            c_disc += 1
                            parsed = json.loads(resp_raw)
                            if c.name == "search_rules":
                                retrieval_q.append(str(c.arguments.get("query", "")))
                                retrieved_ids.extend(
                                    r_["rule_id"] for r_ in parsed.get("results", [])
                                )
                                retrieved_call_indexes.extend(
                                    c_disc for _ in parsed.get("results", [])
                                )
                            elif c.name == "inspect_rule":
                                inspected.append(str(c.arguments.get("rule_id")))
                                inspected_call_indexes.append(c_disc)
                        tool_calls.append(
                            ToolCallRecord(
                                turn=turn,
                                tool=c.name,
                                args=dict(c.arguments),
                                response_canonical=content,
                                kind="discovery",
                            )
                        )
                        messages.append(
                            {"role": "tool", "tool_call_id": c.call_id, "content": content}
                        )
                        continue
                    # business tool
                    if c_business >= self.max_business_actions:
                        content = json.dumps({"error": "action_budget_exhausted"})
                        tool_calls.append(
                            ToolCallRecord(
                                turn=turn,
                                tool=c.name,
                                args=dict(c.arguments),
                                response_canonical=content,
                                kind="business",
                            )
                        )
                        messages.append(
                            {"role": "tool", "tool_call_id": c.call_id, "content": content}
                        )
                        continue
                    try:
                        action: Action = parse_action({"kind": c.name, **c.arguments})
                    except Exception as exc:  # invalid tool args are outcomes
                        content = json.dumps({"error": f"invalid_action:{exc}"})
                        tool_calls.append(
                            ToolCallRecord(
                                turn=turn,
                                tool=c.name,
                                args=dict(c.arguments),
                                response_canonical=content,
                                kind="business",
                            )
                        )
                        messages.append(
                            {"role": "tool", "tool_call_id": c.call_id, "content": content}
                        )
                        continue
                    c_business += 1
                    res = _apply_verified_action(world, state, action)
                    if res.status == "ok":
                        state = res.state
                        fired.extend(res.fired_rule_ids)
                        events_out.extend(res.events)
                        summary = {"status": "ok", "note": res.note}
                        if res.note == "request_created" and res.state.requests:
                            summary["request_id"] = res.state.requests[-1].request_id
                    else:
                        summary = {"status": res.status, "note": res.note, "error": res.error}
                    tool_calls.append(
                        ToolCallRecord(
                            turn=turn,
                            tool=c.name,
                            args=dict(c.arguments),
                            response_canonical=json.dumps(summary, sort_keys=True),
                            kind="business",
                        )
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": c.call_id, "content": json.dumps(summary)}
                    )
                if stop:
                    break
        except ProviderError as exc:
            provider_error = sanitized_provider_error(exc)

        latency_ms = int((time.monotonic() - t0) * 1000)
        final_usage = UsageRecord(
            model_turns=c_turns,
            business_actions=c_business,
            discovery_calls=c_disc,
            total_tool_calls=c_total,
            prompt_tokens=c_prompt,
            completion_tokens=c_completion,
            latency_ms=latency_ms,
        )
        verdict = evaluate_task(world, state, task)
        silent = claimed and not verdict.csts
        closure = self._causal_closure(world, task)
        retrieval_values = retrieval_metrics(
            tuple(retrieved_ids),
            tuple(inspected),
            closure,
            returned_call_indexes=tuple(retrieved_call_indexes),
            inspected_call_indexes=tuple(inspected_call_indexes),
        )
        return EpisodeRecord(
            episode_id=f"{case_id}-{label}-r{repeat}",
            split=split,  # type: ignore[arg-type]
            case_id=case_id,
            parent_task_id=parent_task_id,
            family=task.family,
            condition=condition,
            rollout_seed_id=seed_id,
            execution_mode="live",
            requested_provider_seed=requested_provider_seed,
            world_id=world.world_id,
            world_hash=world.content_hash(),
            baseline_world_hash=self.baseline_world.content_hash(),
            task_text_hash=hashlib.sha256(task_prompt(task).encode()).hexdigest()[:16],
            system_prompt_hash=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:16],
            events=tuple(events_out),
            tool_calls=tuple(tool_calls),
            usage=final_usage,
            retrieval=RetrievalLog(
                queries=tuple(retrieval_q),
                returned_rule_ids=tuple(retrieved_ids),
                inspected_rule_ids=tuple(inspected),
                causal_closure_rule_ids=tuple(sorted(closure)),
                causal_closure_computed=True,
                **retrieval_values,
            ),
            fired_rules=tuple(dict.fromkeys(fired)),
            claimed_success=claimed,
            verdict=verdict,
            claim_outcome_match=claimed == verdict.csts,
            silent_violation=silent,
            provider_model=provider_model,
            seed_supported=seed_supported,
            provider_error=provider_error,
        )


def build_scripted_policy(condition: DynamicsMode) -> ScriptedAgent:
    if condition == "surface":
        return SurfaceScripted()
    if condition in ("frozen_discovery", "live_discovery"):
        return DiscoveryScripted()
    raise ValueError("preflight is out of scope for v1")
