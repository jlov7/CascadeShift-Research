"""Check the repository for excluded or credential-bearing material."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PATHS = (
    ".claude",
    ".env",
    ".env.example",
    "protocol/allowed_signers",
    "protocol/claims.yaml",
    "protocol/post_freeze_policy.json",
    "artifacts/results/confirmatory/live-run.journal.jsonl",
)
IGNORED_PARTS = {
    ".git",
    ".venv",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".cache",
}
CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?m)^[A-Z][A-Z0-9_]*(?:API|TOKEN|SECRET|KEY)[A-Z0-9_]*\s*=\s*(?:['\"]|[A-Za-z_-][A-Za-z0-9_-]{7,})"
)
JSON_CREDENTIAL = re.compile(
    rb'"[A-Z][A-Z0-9_]*(?:API|TOKEN|SECRET|KEY)[A-Z0-9_]*"\s*:\s*"[^"\n]+"'
)


def main() -> None:
    failures = [name for name in EXCLUDED_PATHS if (ROOT / name).exists()]
    if failures:
        raise SystemExit("PUBLIC SURFACE FAIL: " + ", ".join(sorted(failures)))
    for path in ROOT.rglob("*"):
        if any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts):
            continue
        if path.is_symlink() or path.name.startswith(".env"):
            failures.append(str(path.relative_to(ROOT)) + ":excluded-file")
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            failures.append(str(path.relative_to(ROOT)) + ":unreadable")
            continue
        if CREDENTIAL_ASSIGNMENT.search(content) or JSON_CREDENTIAL.search(content):
            failures.append(str(path.relative_to(ROOT)) + ":credential-marker")
    if failures:
        raise SystemExit("PUBLIC SURFACE FAIL: " + ", ".join(sorted(failures)))
    print("PUBLIC SURFACE OK: excluded and credential-bearing material is absent")


if __name__ == "__main__":
    main()
