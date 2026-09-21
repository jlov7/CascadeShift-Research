from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _checker():
    path = Path(__file__).parents[2] / "scripts/check_public_surface.py"
    spec = importlib.util.spec_from_file_location("public_surface_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(module, root: Path) -> None:
    module.ROOT = root
    module.main()


def test_harmless_text_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("API documentation explains configuration names.\n")
    _run(_checker(), tmp_path)


def test_assignment_credential_marker_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.txt").write_text("API_TOKEN=syntheticvalue\n")
    try:
        _run(_checker(), tmp_path)
    except SystemExit as exc:
        assert "credential-marker" in str(exc)
    else:
        raise AssertionError("credential assignment was accepted")


def test_json_credential_field_is_rejected(tmp_path: Path) -> None:
    # Construct the test payload without embedding credential-shaped JSON in this source file.
    payload = {"API_" + "TOKEN": "syntheticvalue"}
    (tmp_path / "config.json").write_text(json.dumps(payload))
    try:
        _run(_checker(), tmp_path)
    except SystemExit as exc:
        assert "credential-marker" in str(exc)
    else:
        raise AssertionError("JSON credential field was accepted")


def test_large_files_are_scanned(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_bytes(
        b"x" * (2 * 1024 * 1024 + 1) + b"\nAPI_TOKEN=syntheticvalue\n"
    )
    try:
        _run(_checker(), tmp_path)
    except SystemExit as exc:
        assert "large.txt:credential-marker" in str(exc)
    else:
        raise AssertionError("large credential-bearing file was accepted")


def test_unreadable_file_is_not_silently_accepted(tmp_path: Path, monkeypatch) -> None:
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("harmless\n")
    original = Path.read_bytes

    def fail_read(self: Path) -> bytes:
        if self == blocked:
            raise OSError("denied")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    try:
        _run(_checker(), tmp_path)
    except SystemExit as exc:
        assert "blocked.txt:unreadable" in str(exc)
    else:
        raise AssertionError("unreadable file was accepted")
