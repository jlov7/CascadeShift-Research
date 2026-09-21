# Reproducibility

CascadeShift has three different reproducibility surfaces. They should not be confused.

1. The v1 archive checks recompute reported counts and replay archived actions through the preserved engine.
2. The v2 construction checks validate six hand-built, observable configuration cases.
3. A fresh live-model evaluation is not included in this prototype.

## Install the locked environment

Run these commands in a source checkout with [uv](https://docs.astral.sh/uv/) installed:

```sh
uv sync --locked --all-groups
```

This installs the locked dependencies used for local verification. It does not download a model, configure a provider, or send data to a remote service.

## Check the v2 construction example

```sh
uv run python examples/configuration_visibility.py
```

The output is deterministic and uses no model. It displays the M2-001 configuration fact, shows that the baseline plan passes in the baseline world and fails in the active world, then shows that a corrected plan passes in the active world. It is an example of interface observability and plan validation, not a performance result.

## Run the local verification suite

```sh
make verify
```

This command runs linting, type checks, unit, property, integration, package, documentation, archive-recompute, archive-replay, visibility-audit, and six-case construction checks. It exits successfully only when those local checks pass. It does not make a release, perform a fresh model run, or establish external validity.

## Inspect the historical archive

```sh
uv run python scripts/recompute_results.py
uv run python scripts/replay_study.py
uv run python scripts/audit_visibility.py
```

`recompute_results.py` recomputes the 450-cell matrix and reports the primary estimate as +9.16667 percentage points with a percentile interval of [-1.66667, 20.83333]. `replay_study.py` replays 587 archived actions and 450 final verdicts against the preserved engine. `audit_visibility.py` compares C1 and C2 discovery responses and reports that 14 of 30 shifted worlds had no exposed interface difference, including 9 of 15 plan-invalidating worlds.

All three scripts operate on retained evidence. They do not run the historical model, reproduce the original live environment, or independently implement the simulator. A passing replay establishes archive-engine agreement only.

## Check preservation and public-surface scope

```sh
uv run python scripts/check_artifacts.py
uv run python scripts/check_public_surface.py
```

The artifact check verifies the selected v1 archive and scientific engine files against the retained preservation record. The public-surface check looks for excluded material and credential markers in this repository. Each check has the scope stated in its output. Neither check establishes scientific validity, external review, or publication.

## Measurement-v2 diagnostic boundary

The repository contains the six offline v2 cases and their construction checks. It contains a sanitized, source-derived summary of a stopped provider diagnostic. The raw provider record is not public, so the summary cannot be independently replayed as a model run. It therefore supports no model comparison, null result, or efficacy estimate.

See [Results](RESULTS.md), [Technical note](TECHNICAL-NOTE.md), and [Future study](docs/future-study.md) before using any historical result.
