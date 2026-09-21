"""Offline command line entry point for measurement-v2 construction checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .cases import build_cases
from .validate import validate_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="CascadeShift measurement-v2 development checks")
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser(
        "validate", help="validate handcrafted cases without model calls"
    )
    validate.add_argument(
        "--out", required=True, type=Path, help="write deterministic gate report here"
    )
    args = parser.parse_args()
    if args.command != "validate":  # pragma: no cover - argparse keeps this unreachable
        return 2
    report = validate_cases(build_cases())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
