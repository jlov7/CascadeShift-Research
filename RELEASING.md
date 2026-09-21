# Releasing

CascadeShift 1.3.0 is a research-software release candidate. Publishing, tagging, signing, and
package distribution are maintainer-controlled actions; local verification does not perform them.

Before a release:

1. Confirm that `pyproject.toml`, `CITATION.cff`, `CHANGELOG.md`, and package assertions use the same
   version.
2. Run `uv sync --locked --all-groups` and `make verify` from a clean clone.
3. Build the wheel and source distribution, inspect their members, and install each artifact in a
   fresh environment.
4. Review the README claim boundary, [Results](RESULTS.md), [Provenance](PROVENANCE.md), and
   [Disclaimer](DISCLAIMER.md) against the retained evidence.
5. Confirm that the candidate contains no credentials, local paths, personal data, review notes, or
   unpublished diagnostic records.
6. Only after those checks pass, create the public repository history and any `v1.3.0` tag or
   release record through the maintainer's approved publication process.

The historical v1 freeze material verifies only the retained historical scope. It does not sign or
attest to version 1.3.0, and it does not establish scientific replication. See
[Reproducibility](REPRODUCIBILITY.md) for the exact scope of the local checks.
