# Local verification commands

## Installed prototype CLI

The installed CLI supports small, local inspection and validation tasks. It does not launch a provider or recreate the historical study.

| Command | Purpose |
| --- | --- |
| `cascadeshift doctor` | Checks the installed runtime and bundled baseline world. |
| `cascadeshift world validate` | Validates the bundled baseline world, or a supplied world file. |
| `cascadeshift task validate <directory>` | Validates a task-corpus directory against its schema and baseline solvability. |
| `cascadeshift rules generate` | Generates a deterministic rule-catalog diagnostic. |
| `cascadeshift shifts generate --seed <integer>` | Generates a deterministic development shift set. |
| `cascadeshift oracle verify --split development` | Checks oracle solvability for the development split. |

Run `cascadeshift shifts generate --seed 20260823` before the development oracle check. Generation writes the development task split and its worlds in the current directory; the oracle then reads those files. Historical confirmatory evidence is inspected with the archive scripts below.

| Command | What it does | What it does not do |
| --- | --- | --- |
| `uv run python examples/configuration_visibility.py` | Runs one deterministic v2 visibility and plan-witness example. | Run a model or measure performance. |
| `make verify` | Runs local quality, package, archive, visibility, and construction checks. | Create a release or establish external validity. |
| `uv run python scripts/check_artifacts.py` | Verifies retained v1 archive and selected preserved-engine artifacts. | Verify every file in this modified prototype. |
| `uv run python scripts/recompute_results.py` | Recomputes the historical matrix and primary result. | Rerun historical model inference. |
| `uv run python scripts/replay_study.py` | Replays retained actions and final verdicts against the preserved engine. | Independently implement the engine or repeat the original live run. |
| `uv run python scripts/audit_visibility.py` | Compares C1 and C2 discovery responses. | Establish that every changed fact was necessary in every episode. |
| `uv run python scripts/check_public_surface.py` | Checks the repository for excluded public-surface material. | Provide a general security or disclosure certification. |
