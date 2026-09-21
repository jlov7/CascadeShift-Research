# Reviewer guide

Start with [README](../README.md) and [Technical note](../TECHNICAL-NOTE.md). They state the claim boundary before the commands.

## Check the historical record

```sh
uv sync --locked --all-groups
uv run python scripts/check_artifacts.py
uv run python scripts/recompute_results.py
uv run python scripts/replay_study.py
uv run python scripts/audit_visibility.py
```

The preservation check identifies the [exact retained v1 scope](artifact-scope.md). The recomputation script reconstructs the published 450-cell result. The replay script checks 587 archived actions and 450 final verdicts against the preserved engine. The visibility audit reports which shifted worlds have no C1/C2 discovery-response difference.

These checks give a reviewer a direct way to inspect the retained archive. They are not an independent implementation, a fresh inference run, evidence of the original execution environment, or external scientific validation.

## Check the repaired interface

```sh
uv run python examples/configuration_visibility.py
make verify
```

The example and the six-case construction tests show that the measurement-v2 interface exposes the declared facts and that the witness plans behave as specified. The provider diagnostic stopped before a usable comparison. Its public summary is source-derived and cannot be independently replayed as model evidence.

## Inspect the public surface

```sh
uv run python scripts/check_public_surface.py
```

This check searches the repository for material that should not be included in the prototype. Read its scope before treating a pass as a wider disclosure or security conclusion.

## Suggested review questions

- Does the claimed v1 result match the output of the recomputation script?
- Does the visibility audit support the stated treatment-coverage limitation?
- Do the v2 construction checks demonstrate observability and metric separation without being presented as a model result?
- Do the documentation and claims stay within a synthetic, single-model, archive-specific scope?

