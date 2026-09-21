from __future__ import annotations

from pathlib import Path

from typer.main import get_command
from typer.testing import CliRunner

from cascadeshift.cli import app

RUNNER = CliRunner()


def test_help_lists_only_public_commands() -> None:
    result = RUNNER.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert set(get_command(app).commands) == {
        "doctor",
        "world",
        "task",
        "rules",
        "shifts",
        "oracle",
    }


def test_doctor_and_world_validation_work_outside_checkout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert RUNNER.invoke(app, ["doctor", "--json"]).exit_code == 0
    assert RUNNER.invoke(app, ["world", "validate"]).exit_code == 0


def test_rules_rejects_noncanonical_count() -> None:
    result = RUNNER.invoke(app, ["rules", "generate", "--count", "127"])
    assert result.exit_code != 0


def test_task_validation_rejects_bad_payloads(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "case.json").write_text("{not json}\n")
    assert RUNNER.invoke(app, ["task", "validate", str(empty)]).exit_code != 0
    assert RUNNER.invoke(app, ["task", "validate", str(malformed)]).exit_code != 0


def test_world_validation_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "world.yaml"
    target.write_text("world_id: unsafe\n")
    link = tmp_path / "link.yaml"
    link.symlink_to(target)
    assert RUNNER.invoke(app, ["world", "validate", str(link)]).exit_code != 0


def test_confirmatory_paths_fail_without_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    before = sorted(path.name for path in tmp_path.iterdir())
    assert (
        RUNNER.invoke(
            app, ["shifts", "generate", "--seed", "1", "--split", "confirmatory"]
        ).exit_code
        != 0
    )
    assert RUNNER.invoke(app, ["oracle", "verify", "--split", "confirmatory"]).exit_code != 0
    assert sorted(path.name for path in tmp_path.iterdir()) == before
