"""CascadeShift command-line interface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import typer

from cascadeshift import __version__
from cascadeshift.boundaries import (
    JSON_MAX_BYTES,
    BoundaryError,
    bounded_json_files,
    load_bounded_json,
)
from cascadeshift.cli_contract import CLI_COMMANDS
from cascadeshift.engine.world import WorldSpec
from cascadeshift.runtime import BASELINE_RESOURCE, RuntimeLayout
from cascadeshift.tasks.models import ShiftedCase, TaskSpec

app = typer.Typer(add_completion=False, no_args_is_help=True, invoke_without_command=True)
world_app = typer.Typer(no_args_is_help=True)
task_app = typer.Typer(no_args_is_help=True)
rules_app = typer.Typer(no_args_is_help=True)
shifts_app = typer.Typer(no_args_is_help=True)
oracle_app = typer.Typer(no_args_is_help=True)
WORLD_PATH_ARGUMENT = typer.Argument(None)
PATH_MAX_CHARS = 1024
app.add_typer(world_app, name="world", help="World file operations")
app.add_typer(task_app, name="task", help="Task corpus operations")
app.add_typer(rules_app, name="rules", help="Rule catalog operations")
app.add_typer(shifts_app, name="shifts", help="Shift generation")
app.add_typer(oracle_app, name="oracle", help="Oracle solvability checks")


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show CascadeShift version and exit."),
) -> None:
    if version:
        typer.echo(f"cascadeshift {__version__}")
        raise typer.Exit()


def _world(path: str) -> WorldSpec:
    from cascadeshift.engine.world_io import load_world

    return load_world(path)


def _bounded_text(value: str, *, limit: int, code: str) -> str:
    if not value or len(value) > limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise BoundaryError(code)
    return value


def _runtime() -> RuntimeLayout:
    return RuntimeLayout.discover()


def _baseline_world() -> WorldSpec:
    return _runtime().baseline_world()


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Check the runtime, bundled world, and available local commands."""
    layout = _runtime()
    try:
        resource = layout.resource_bytes(BASELINE_RESOURCE)
        world = layout.bundled_baseline_world()
        from cascadeshift.shifts.validation import validate_world

        if not validate_world(world).ok:
            raise ValueError("invalid bundled baseline")
    except Exception:
        typer.secho(
            "DOCTOR_FAILED: bundled baseline world is unavailable or invalid", fg=typer.colors.RED
        )
        raise typer.Exit(1) from None

    mode = layout.mode.value
    checkout_available = layout.checkout_root is not None
    baseline_sha256 = hashlib.sha256(resource).hexdigest()
    bundled_resources: dict[str, dict[str, str]] = {
        "worlds/baseline/world.yaml": {"status": "ok", "sha256": baseline_sha256}
    }
    payload: dict[str, object] = {
        "schema": "cascadeshift.doctor/v1",
        "mode": mode,
        "checkout_available": checkout_available,
        "capability": "CHECKOUT_AVAILABLE" if checkout_available else "INSTALLED_ONLY",
        "capability_contract": "PUBLIC_PROTOTYPE_CLI_V1",
        "command_count": len(CLI_COMMANDS),
        "commands": list(CLI_COMMANDS),
        "bundled_resources": bundled_resources,
        "checkout_only": [],
    }
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(f"runtime mode: {mode}")
        typer.echo(
            "capability: " + ("CHECKOUT_AVAILABLE" if checkout_available else "INSTALLED_ONLY")
        )
        typer.echo("bundled baseline: OK " + baseline_sha256)
        typer.echo("checkout capability: " + ("available" if checkout_available else "unavailable"))


@world_app.command("validate")
def world_validate(path: Path | None = WORLD_PATH_ARGUMENT) -> None:
    """Validate a world file (schema, references, invariants)."""
    from cascadeshift.shifts.validation import validate_world

    try:
        if path is not None:
            _bounded_text(str(path), limit=PATH_MAX_CHARS, code="WORLD_INPUT_INVALID")
        w = _world(str(path)) if path is not None else _baseline_world()
    except (BoundaryError, OSError, ValueError):
        typer.secho("WORLD_INPUT_INVALID", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    report = validate_world(w)
    if not report.ok:
        typer.secho(f"INVALID: {report.errors}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(f"OK {w.world_id} rules={len(w.rules)} hash={w.content_hash()[:16]}")


@task_app.command("validate")
def task_validate(dir: str = typer.Argument(...)) -> None:
    """Validate a task corpus directory (schema + baseline solvability)."""
    try:
        _bounded_text(dir, limit=PATH_MAX_CHARS, code="TASK_INPUT_INVALID")
        root = Path(dir)
    except BoundaryError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    try:
        files = bounded_json_files(root)
    except BoundaryError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None

    if not files:
        typer.secho("TASK_INPUT_INVALID", fg=typer.colors.RED)
        raise typer.Exit(1)
    from cascadeshift.tasks.models import ShiftedCase, TaskSpec
    from cascadeshift.tasks.oracle import solve

    w = _baseline_world()
    payloads: list[tuple[Path, dict[str, object]]] = []
    for f in files:
        try:
            data = load_bounded_json(f, max_bytes=JSON_MAX_BYTES)
        except BoundaryError:
            typer.secho("TASK_INPUT_INVALID", fg=typer.colors.RED)
            raise typer.Exit(1) from None
        tasks: list[dict[str, object]] = []
        if isinstance(data, list):
            if any(not isinstance(task, dict) for task in data):
                typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
                raise typer.Exit(1)
            tasks = [task for task in data if isinstance(task, dict)]
        elif isinstance(data, dict) and "anchors" in data:
            anchors_list = data["anchors"]
            if not isinstance(anchors_list, list) or any(
                not isinstance(t, dict) for t in anchors_list
            ):
                typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
                raise typer.Exit(1)
            tasks.extend(t for t in anchors_list if isinstance(t, dict))
        elif isinstance(data, dict) and "baselines" in data:
            bl = data["baselines"]
            if not isinstance(bl, list) or any(not isinstance(t, dict) for t in bl):
                typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
                raise typer.Exit(1)
            tasks.extend(t for t in bl if isinstance(t, dict))
        if isinstance(data, dict) and "cases" in data:
            cs = data["cases"]
            if not isinstance(cs, list) or any(not isinstance(t, dict) for t in cs):
                typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
                raise typer.Exit(1)
            tasks.extend(t for t in cs if isinstance(t, dict))
        payloads.extend((f, task) for task in tasks)

    if not payloads:
        typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
        raise typer.Exit(1)

    parsed: list[tuple[Path, TaskSpec | ShiftedCase]] = []
    baselines: dict[str, TaskSpec] = {}
    seen_ids: set[str] = set()
    for f, payload in payloads:
        try:
            obj: TaskSpec | ShiftedCase = (
                ShiftedCase.model_validate(payload)
                if payload.get("parent_task_id")
                else TaskSpec.model_validate(payload)
            )
        except Exception:
            typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
            raise typer.Exit(1) from None
        if obj.task_id in seen_ids:
            typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
            raise typer.Exit(1)
        seen_ids.add(obj.task_id)
        parsed.append((f, obj))
        if isinstance(obj, TaskSpec):
            baselines[obj.task_id] = obj

    for _f, parsed_task in parsed:
        task = parsed_task
        if isinstance(task, ShiftedCase):
            baseline = baselines.get(task.parent_task_id)
            if baseline is None:
                typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
                raise typer.Exit(1)
            task = baseline
        res = solve(w, task)
        if res.status != "solved":
            typer.secho("TASK_SCHEMA_INVALID", fg=typer.colors.RED)
            raise typer.Exit(1)
    n_cases = len(parsed)
    typer.echo(f"OK {n_cases} tasks validated")


@rules_app.command("generate")
def rules_generate(count: int = typer.Option(128, "--count")) -> None:
    """Generate the deterministic rule catalog and verify cardinality."""
    from cascadeshift.retrieval.catalog import generate_catalog_with_manifest

    if count != 128:
        typer.secho("catalog cardinality is fixed at 128 by protocol", fg=typer.colors.RED)
        raise typer.Exit(1)
    rules, manifest = generate_catalog_with_manifest()
    kinds = {}
    for _rid, kind in manifest.items():
        kinds.setdefault(kind, 0)
        kinds[kind] += 1
    core_ids = sorted(k for k, v in manifest.items() if v == "core")[:2]
    typer.echo(
        f"OK generated {len(rules)} rules ({kinds}); sample ids {core_ids} (opaque, non-contiguous)"
    )


@shifts_app.command("generate")
def shifts_generate(
    seed: int = typer.Option(..., "--seed"),
    split: str = typer.Option("development", "--split"),
) -> None:
    """Generate paired task-world splits from a fixed seed."""
    if seed < 0 or seed > 2_147_483_647 or len(split) > 16:
        typer.secho("SHIFT_OPTIONS_INVALID", fg=typer.colors.RED)
        raise typer.Exit(1)
    if split == "confirmatory":
        typer.secho("CONFIRMATORY_GENERATION_RETIRED", fg=typer.colors.RED)
        raise typer.Exit(2)
    if split != "development":
        typer.secho("split must be development", fg=typer.colors.RED)
        raise typer.Exit(1)
    # development regeneration (exploratory)
    from cascadeshift.engine.world_io import write_world
    from cascadeshift.tasks.corpus import generate_development_split

    result = generate_development_split(seed=seed)
    baselines = cast(list[TaskSpec], result["baselines"])
    cases = cast(list[ShiftedCase], result["cases"])
    worlds = cast(list[WorldSpec], result["worlds"])
    layout = _runtime()
    try:
        tasks_dir = layout.output_path(Path("tasks/development"), label="development task")
        split_path = layout.output_path(
            Path("tasks/development/split.json"), label="development task"
        )
        worlds_dir = layout.output_path(Path("worlds/generated/dev"), label="development world")
        world_paths = [
            layout.output_path(
                Path("worlds/generated/dev") / f"{i:04d}.yaml", label="development world"
            )
            for i, _world in enumerate(worlds, start=1)
        ]
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None

    split_payload = json.dumps(
        {
            "seed": seed,
            "baselines": [b.model_dump(mode="json") for b in baselines],
            "cases": [c.model_dump(mode="json") for c in cases],
            "shifted_world_hashes": [x.content_hash() for x in worlds],
        },
        indent=2,
        sort_keys=True,
    )
    tasks_dir.mkdir(parents=True, exist_ok=True)
    worlds_dir.mkdir(parents=True, exist_ok=True)
    split_path.write_text(split_payload)
    for world, world_path in zip(worlds, world_paths, strict=True):
        write_world(world, world_path)
    typer.echo(f"OK development split regenerated with seed {seed}")


def _verify_pair_solvable(
    case: dict[str, object],
    base_task: TaskSpec,
    shifted_world: WorldSpec,
    baseline_world: WorldSpec,
) -> tuple[bool, str]:
    """Preserving cases: replay the stored baseline plan (proof by replay).
    Invalidating cases: bounded re-solve must find an alternative."""
    from cascadeshift.tasks.oracle import Plan, solve, verify_plan

    if isinstance(case.get("plan_effect"), str) and case["plan_effect"] == "plan_preserving":
        # Recompute the deterministic baseline plan and replay it.
        res = solve(baseline_world, base_task)
        if res.status != "solved":
            return False, f"baseline unsolved ({res.status})"
        v = verify_plan(shifted_world, base_task, res.plan)
        if not v.csts:
            return False, "baseline plan no longer satisfies preserving case"
        return True, ""
    alt = solve(shifted_world, base_task)
    if alt.status != "solved":
        return False, f"alternative plan not found ({alt.status})"
    plans: list[Plan] = [alt.plan]
    del plans
    v = verify_plan(shifted_world, base_task, alt.plan)
    if not v.csts:
        return False, "alternative plan failed verification"
    return True, ""


@oracle_app.command("verify")
def oracle_verify(split: str = typer.Option("development", "--split")) -> None:
    """Check solvability of the generated development task-world pairs."""
    if split != "development":
        typer.secho("SPLIT_NOT_SUPPORTED: development only", fg=typer.colors.RED)
        raise typer.Exit(2)
    from cascadeshift.shifts.validation import validate_world

    try:
        layout = _runtime()
        path = layout.output_path(Path("tasks/development/split.json"), label="development task")
        data = load_bounded_json(path, max_bytes=JSON_MAX_BYTES)
        if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
            raise ValueError("invalid development split")
        if not isinstance(data.get("baselines"), list) or not data["cases"]:
            raise ValueError("empty development split")
        baselines = {b["task_id"]: TaskSpec.model_validate(b) for b in data["baselines"]}
        world_dir = layout.output_path(Path("worlds/generated/dev"), label="development worlds")
        paths = sorted(world_dir.glob("*.yaml"))
        if len(paths) != len(data["cases"]) or len(paths) > 128:
            raise ValueError("missing or unexpected development worlds")
        worlds = [_world(str(p)) for p in paths]
        if any(not validate_world(world).ok for world in worlds):
            raise ValueError("invalid development world")
        by_hash = {world.content_hash(): world for world in worlds}
        if set(by_hash) != {case["shifted_world_hash"] for case in data["cases"]}:
            raise ValueError("development world hashes differ from the split")
        baseline = _baseline_world()
        checked = 0
        for case in data["cases"]:
            task = baselines[case["parent_task_id"]]
            world = by_hash[case["shifted_world_hash"]]
            ok, why = _verify_pair_solvable(case, task, world, baseline)
            if not ok:
                raise ValueError(why)
            checked += 1
    except (BoundaryError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        typer.secho(
            "DEVELOPMENT_VALIDATION_FAILED: generate the development split and worlds "
            "with `cascadeshift shifts generate --seed 20260823` before verifying.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1) from None
    typer.echo(f"OK oracle verified {checked} pairs on split=development")
