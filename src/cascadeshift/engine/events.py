"""Immutable causal events. Every state mutation is attributable to an event."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FieldChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str
    field: str
    before: str
    after: str


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int
    cause: Literal["action", "rule"]
    action_name: str | None = None
    rule_id: str | None = None
    rule_content_hash: str | None = None
    origin_seq: int
    depth: int
    changes: tuple[FieldChange, ...] = ()
    note: str | None = None
    # Event payload used by rule conditions:
    employee_id: str | None = None
    application_id: str | None = None
