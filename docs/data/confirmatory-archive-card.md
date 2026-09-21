# Historical v1 archive card

## What is included

The repository intentionally includes the 450-episode synthetic v1 trace archive. Each episode records a task, condition, synthetic world state, agent-visible exchanges, actions, and a terminal verdict. The archive is included so readers can recompute the reported matrix and replay retained actions through the preserved engine.

The archive is synthetic. It is not customer data, production configuration, or a record of real administrative actions. Do not treat the synthetic names, access concepts, or rules as an organizational policy template.

## Integrity and scope

The retained archive SHA-256 is `dac63b8996899726315f1f04cc5967b08b3358382a7c6b6f38261a963f1b5f4a`. Run `uv run python scripts/check_artifacts.py` to check the [preserved v1 scope](../artifact-scope.md), then use the scripts in [Reproducibility](../../REPRODUCIBILITY.md) to recompute and replay the historical evidence.

The archive records one local model/runtime and a fixed synthetic corpus. Replaying it does not rerun a model or establish an independent replication. The C1/C2 discovery contrast is absent at the interface level in 14 of 30 shifted worlds, including 9 of 15 plan-invalidating worlds. See [Technical note](../../TECHNICAL-NOTE.md).

## Access and license

The archive is distributed as part of CascadeShift under the repository's Apache License 2.0. The project does not include raw provider diagnostic records from measurement v2. The public v2 summary is source-derived, incomplete, and not a reusable model-run dataset.

