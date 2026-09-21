# Historical artifact scope

`uv run python scripts/check_artifacts.py` freeze-verifies these retained historical v1 source paths:

- `src/cascadeshift/agents/conditions.py`
- `src/cascadeshift/domain/actions.py`, `constraints.py`, `entities.py`, `rules.py`, and `state.py`
- `src/cascadeshift/engine/transition.py`
- `src/cascadeshift/retrieval/index.py`, `relevance.py`, and `tools.py`
- `src/cascadeshift/shifts/operators.py`
- `src/cascadeshift/tasks/models.py`

It also freeze-verifies the archive, historical manifest, preregistration, task anchors, split, and baseline-world bytes.

Three source-assembly files use expected source-assembly hashes rather than historical freeze hashes: `src/cascadeshift/engine/world.py`, `src/cascadeshift/engine/world_io.py`, and `src/cascadeshift/tasks/oracle.py`. The oracle differs at its node-budget boundary and is not used by the v1 replay. `scripts/replay_study.py` validates generated-world canonical hashes, transitions, and final verdicts.

This scope does not verify every file in version `1.3.0`, and it is not a model or external-validation result.
