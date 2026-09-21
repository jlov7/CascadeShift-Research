"""Closed business-action schema. The action space is fixed; agents cannot invent actions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def action_name(self) -> str:
        return type(self).__name__


class GrantApplicationAccess(_Action):
    kind: Literal["grant_application_access"] = "grant_application_access"
    employee_id: str
    application_id: str


class RevokeApplicationAccess(_Action):
    kind: Literal["revoke_application_access"] = "revoke_application_access"
    employee_id: str
    application_id: str


class AssignRole(_Action):
    kind: Literal["assign_role"] = "assign_role"
    employee_id: str
    role_id: str


class CompleteOnboarding(_Action):
    kind: Literal["complete_onboarding"] = "complete_onboarding"
    employee_id: str


class OffboardEmployee(_Action):
    kind: Literal["offboard_employee"] = "offboard_employee"
    employee_id: str


class ApproveRequest(_Action):
    kind: Literal["approve_request"] = "approve_request"
    request_id: str


class FinishTask(_Action):
    kind: Literal["finish_task"] = "finish_task"
    summary: str = ""


Action = Annotated[
    GrantApplicationAccess
    | RevokeApplicationAccess
    | AssignRole
    | CompleteOnboarding
    | OffboardEmployee
    | ApproveRequest
    | FinishTask,
    Field(discriminator="kind"),
]

_ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)

BUSINESS_ACTIONS: tuple[str, ...] = (
    "grant_application_access",
    "revoke_application_access",
    "assign_role",
    "complete_onboarding",
    "offboard_employee",
    "approve_request",
)


def parse_action(payload: dict[str, object]) -> Action:
    """Validate an untyped payload against the closed union."""
    return _ACTION_ADAPTER.validate_python(payload)
