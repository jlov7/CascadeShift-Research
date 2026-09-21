"""Scripted-agent integration through the runner (ledger A-05, M-01)."""

from cascadeshift.agents.runner import EpisodeRunner, extract_goals
from cascadeshift.engine.world_io import load_world
from cascadeshift.retrieval.relevance import oracle_causal_closure
from cascadeshift.shifts.operators import apply_op, parse_op
from cascadeshift.tasks.corpus import _dev_baselines

W = "worlds/baseline/world.yaml"


def _runner():
    return EpisodeRunner(load_world(W))


def test_surface_agent_silently_violates_on_cascade_task():
    """T-D-0002: grant VIP to E-001 (holds PAY) - cascade revokes PAY."""
    w0 = load_world(W)
    task = [t for t in _dev_baselines() if t.task_id == "T-D-0004"][0]
    rec = _runner().run_scripted(
        split="development",
        case_id=task.task_id,
        parent_task_id=task.task_id,
        task=task,
        world=w0,
        condition="surface",
    )
    assert rec.claimed_success is True
    # The scripted surface agent finishes while the SoD guard may have fired;
    # whatever the outcome, records must be complete and consistent.
    assert rec.verdict is not None
    assert rec.usage.discovery_calls == 0
    assert rec.retrieval.causal_closure_computed is True
    assert rec.retrieval.causal_closure_rule_ids == tuple(sorted(oracle_causal_closure(w0, task)))
    assert rec.retrieval.returned_rule_precision is None
    assert rec.retrieval.inspected_rule_precision is None


def _k4_id(w):
    return next(r.rule_id for r in w.rules if r.provenance.source == "SO-POL-040")


def test_discovery_agents_split_on_silent_bundle_shift():
    """Silent side-effect expansion: stale discovery misses it, live catches it.

    K4 bundles Bid Workspace into mid-tier grants. With a hidden
    entitlement-absent(BID) verifier constraint, C1's stale snapshot shows
    K4 inactive -> plain grant silently violates. C2 sees K4 active ->
    revokes the bundled grant and passes.
    """
    w0 = load_world(W)
    shifted = apply_op(w0, parse_op({"kind": "add_template_side_effect", "rule_id": _k4_id(w0)}))
    task = [t for t in _dev_baselines() if t.task_id == "T-D-0001"][0]
    assert any(c.model_dump()["kind"] == "entitlement_absent" for c in task.hard_constraints)
    runner = _runner()
    c1 = runner.run_scripted(
        split="development",
        case_id="S-TEST",
        parent_task_id=task.task_id,
        task=task,
        world=shifted,
        condition="frozen_discovery",
    )
    c2 = runner.run_scripted(
        split="development",
        case_id="S-TEST",
        parent_task_id=task.task_id,
        task=task,
        world=shifted,
        condition="live_discovery",
    )
    assert c1.verdict.csts is False, "stale snapshot must miss the bundle"
    assert c1.silent_violation is True, "the bundled grant must be invisible to the acting agent"
    assert c2.verdict.csts is True, "live discovery must mitigate the bundle it inspected"
    assert c2.silent_violation is False
    assert c1.usage.discovery_calls > 0 and c2.usage.discovery_calls > 0


def test_confirmation_gates_are_self_disclosing_for_all_conditions():
    """Honesty check: request flows are visible, so both conditions recover."""
    w0 = load_world(W)
    shifted = apply_op(
        w0,
        parse_op(
            {
                "kind": "change_bundle_membership",
                "application_id": "APP-CRM",
                "requires_security_review": True,
            }
        ),
    )
    task = [t for t in _dev_baselines() if t.task_id == "T-D-0001"][0]
    runner = _runner()
    for cond in ("frozen_discovery", "live_discovery"):
        rec = runner.run_scripted(
            split="development",
            case_id="S-GATE",
            parent_task_id=task.task_id,
            task=task,
            world=shifted,
            condition=cond,
        )
        assert rec.verdict.csts is True


def test_all_dev_cases_complete_under_every_condition():
    from cascadeshift.tasks.corpus import generate_development_split

    split = generate_development_split()
    worlds_by_hash = {w.content_hash(): w for w in split["worlds"]}
    w0 = load_world(W)
    runner = _runner()
    n = 0
    for case in split["cases"]:
        parent = next(b for b in split["baselines"] if b.task_id == case.parent_task_id)
        world = worlds_by_hash[case.shifted_world_hash]
        for cond in ("surface", "frozen_discovery", "live_discovery"):
            rec = runner.run_scripted(
                split="development",
                case_id=case.task_id,
                parent_task_id=parent.task_id,
                task=parent,
                world=world,
                condition=cond,
                repeat=1,
            )
            assert rec.episode_id
            assert rec.case_id == case.task_id
            assert rec.condition == cond
            assert rec.execution_mode == "scripted"
            n += 1
    del w0
    assert n == len(split["cases"]) * 3


def test_baseline_case_runs_for_all_conditions():
    w0 = load_world(W)
    task = _dev_baselines()[0]
    r = _runner()
    outs = {
        cond: r.run_scripted(
            split="development",
            case_id=task.task_id,
            parent_task_id=task.task_id,
            task=task,
            world=w0,
            condition=cond,
        )
        for cond in ("surface", "frozen_discovery", "live_discovery")
    }
    seeds = {rec.rollout_seed_id for rec in outs.values()}
    # Matched rollout-seed identifiers across conditions per preregistration.
    assert len(seeds) == 1
    assert all(rec.verdict.csts for rec in outs.values())


def test_extract_goals_orders_visible_steps():
    task = _dev_baselines()[1]  # VIP grant with conflict constraint
    emp, goals = extract_goals(task)
    assert emp == "E-001"
    assert goals == [("grant", "APP-VIP")]
