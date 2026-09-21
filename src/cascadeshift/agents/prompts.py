"""Model-visible prompts. Neutral: no condition labels or freshness hints."""

from __future__ import annotations

from cascadeshift.tasks.models import TaskSpec

BANNED_PROMPT_TOKENS: tuple[str, ...] = (
    "frozen",
    "stale",
    "live",
    "fresh",
    "shift",
    "baseline",
    "confirmatory",
    "condition c",
    "c0",
    "c1",
    "c2",
    "oracle",
    "snapshot version",
    "world v1",
    "verifier",
    "hidden",
)

SYSTEM_PROMPT = (
    "You are an IT access-management assistant working inside the company "
    "service console.\n"
    "Complete the requested task using the provided tools.\n"
    "Rules of conduct:\n"
    "- Use tools to inspect records before acting when unsure.\n"
    "- Company configuration rules may apply to your actions. You can "
    "search and inspect the tenant rulebook with the discovery tools when "
    "they are available.\n"
    "- When you believe the task is complete, call finish_task with a short "
    "summary of what you did."
)


def task_prompt(task: TaskSpec) -> str:
    goal_lines = []
    for g in task.visible_goal:
        d = g.model_dump()
        kind = d.get("kind")
        if kind == "goal_entitlement_present":
            goal_lines.append(f"- {d['employee_id']} must have access to {d['application_id']}.")
        elif kind == "role_is":
            goal_lines.append(f"- {d['employee_id']} must hold role {d['role_id']}.")
        elif kind == "status_is":
            goal_lines.append(f"- {d['employee_id']} must be in status {d['status']}.")
        else:
            goal_lines.append(f"- {kind}: {d}")
    lines = [
        f"Task {task.task_id}: {task.title}",
        "",
        task.description,
        "",
        "Success criteria:",
        *goal_lines,
    ]
    return "\n".join(lines)


def assert_neutral(text: str) -> None:
    lowered = text.lower()
    for tok in BANNED_PROMPT_TOKENS:
        words = lowered.split()
        if tok in words:
            raise ValueError(f"banned condition-hint token in prompt: {tok!r}")
