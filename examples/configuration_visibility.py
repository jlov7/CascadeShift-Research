"""Show an observable configuration difference without calling a model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def main() -> None:
    from development.measurement_v2.cases import build_cases
    from development.measurement_v2.interface import MeasurementInterface

    from cascadeshift.domain.actions import parse_action
    from cascadeshift.engine.world import WorldSpec
    from cascadeshift.tasks.models import TaskSpec
    from cascadeshift.tasks.oracle import verify_plan

    case = next(item for item in build_cases() if item["case_id"] == "M2-001-policy-threshold")
    baseline = WorldSpec.model_validate(case["baseline_world"])
    active = WorldSpec.model_validate(case["active_world"])
    task = TaskSpec.model_validate(case["task"])
    state = active.initial_state()
    frozen = MeasurementInterface("frozen", baseline, active)
    current = MeasurementInterface("current", baseline, active)
    frozen_fact = json.loads(frozen.call("read_configuration", {"section": "policy"}, state))[
        "value"
    ]
    current_fact = json.loads(current.call("read_configuration", {"section": "policy"}, state))[
        "value"
    ]
    baseline_plan = tuple(parse_action(item) for item in case["baseline_plan"])
    active_plan = tuple(parse_action(item) for item in case["active_plan"])
    baseline_pass = verify_plan(baseline, task, baseline_plan).csts
    active_baseline_fail = not verify_plan(active, task, baseline_plan).csts
    corrected_pass = verify_plan(active, task, active_plan).csts
    print("case=M2-001-policy-threshold")
    print(f"frozen.policy.risk_threshold={frozen_fact['risk_threshold']}")
    print(f"current.policy.risk_threshold={current_fact['risk_threshold']}")
    print(f"baseline_plan_on_baseline={'PASS' if baseline_pass else 'FAIL'}")
    print(f"baseline_plan_on_current={'FAIL' if active_baseline_fail else 'PASS'}")
    print(f"corrected_plan_on_current={'PASS' if corrected_pass else 'FAIL'}")
    if not (baseline_pass and active_baseline_fail and corrected_pass):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
