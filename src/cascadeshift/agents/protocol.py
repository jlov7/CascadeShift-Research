"""Episode transcript and record schemas (runner outputs)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from cascadeshift.domain.actions import Action
from cascadeshift.engine.events import Event
from cascadeshift.tasks.models import Verdict

DynamicsMode = Literal["surface", "frozen_discovery", "live_discovery", "preflight"]
EvidenceSource = Literal["scripted_validation", "live_model", "unverified_live_archive"]

CONDITION_LABELS: dict[DynamicsMode, str] = {
    "surface": "C0",
    "frozen_discovery": "C1",
    "live_discovery": "C2",
    "preflight": "C3",
}


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn: int
    tool: str
    args: dict[str, Any]
    response_canonical: str
    kind: Literal["discovery", "business", "finish"]


class TurnRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn: int
    action: Action | None = None
    observation_note: str | None = None


class UsageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_turns: int = 0
    business_actions: int = 0
    discovery_calls: int = 0
    total_tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class RetrievalLog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queries: tuple[str, ...] = ()
    returned_rule_ids: tuple[str, ...] = ()
    inspected_rule_ids: tuple[str, ...] = ()
    causal_closure_rule_ids: tuple[str, ...] = ()
    causal_closure_computed: bool = False
    returned_rule_precision: float | None = None
    returned_rule_recall: float | None = None
    inspected_rule_precision: float | None = None
    inspected_rule_recall: float | None = None
    causal_closure_size: int = 0
    first_relevant_returned_discovery_call: int | None = None
    first_relevant_inspected_discovery_call: int | None = None


class EpisodeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_id: str
    split: Literal["smoke", "development", "confirmatory"]
    case_id: str
    parent_task_id: str
    family: str
    condition: DynamicsMode
    rollout_seed_id: str
    execution_mode: Literal["scripted", "live"] = "scripted"
    requested_provider_seed: int | None = None
    world_id: str
    world_hash: str
    baseline_world_hash: str | None = None
    plan_effect: str | None = None

    task_text_hash: str
    system_prompt_hash: str

    events: tuple[Event, ...] = ()
    tool_calls: tuple[ToolCallRecord, ...] = ()
    usage: UsageRecord = UsageRecord()
    retrieval: RetrievalLog = RetrievalLog()
    fired_rules: tuple[str, ...] = ()

    claimed_success: bool = False
    verdict: Verdict
    claim_outcome_match: bool
    silent_violation: bool

    provider_model: str | None = None
    seed_supported: bool | None = None
    provider_error: str | None = None


@dataclass(frozen=True)
class LiveArchiveBinding:
    """Canonical, non-provider fields that identify one live episode."""

    episode_id: str
    split: str
    case_id: str
    parent_task_id: str
    family: str
    condition: str
    rollout_seed_id: str
    provider_seed: int
    world_id: str
    world_hash: str
    baseline_world_hash: str | None
    plan_effect: str | None
    task_text_hash: str
    system_prompt_hash: str
    execution_mode: str


def live_archive_binding(record: EpisodeRecord) -> LiveArchiveBinding:
    try:
        repeat = int(record.episode_id.rsplit("-r", 1)[1])
    except (IndexError, ValueError):
        raise ValueError("live record episode_id does not encode a repeat") from None
    seed_key = f"{record.case_id}|{record.world_id}|{repeat}"
    provider_seed = (
        int.from_bytes(hashlib.sha256(seed_key.encode()).digest()[:4], "big") & 0x7FFFFFFF
    )
    return LiveArchiveBinding(
        episode_id=record.episode_id,
        split=record.split,
        case_id=record.case_id,
        parent_task_id=record.parent_task_id,
        family=record.family,
        condition=record.condition,
        rollout_seed_id=record.rollout_seed_id,
        provider_seed=provider_seed,
        world_id=record.world_id,
        world_hash=record.world_hash,
        baseline_world_hash=record.baseline_world_hash,
        plan_effect=record.plan_effect,
        task_text_hash=record.task_text_hash,
        system_prompt_hash=record.system_prompt_hash,
        execution_mode=record.execution_mode,
    )
