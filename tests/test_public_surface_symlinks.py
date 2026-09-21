"""Release scan must reject symlinks before following their file type."""

from pathlib import Path

import pytest
from scripts import check_public_surface


@pytest.mark.parametrize("kind", ["file", "directory", "dangling"])
def test_public_surface_rejects_every_symlink_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    target = tmp_path / "target"
    if kind == "file":
        target.write_text("ordinary content", encoding="utf-8")
    elif kind == "directory":
        target.mkdir()
    (tmp_path / "link").symlink_to(target, target_is_directory=kind == "directory")
    monkeypatch.setattr(check_public_surface, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="link:excluded-file"):
        check_public_surface.main()


def test_public_surface_accepts_ordinary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "README.md").write_text("Synthetic example", encoding="utf-8")
    monkeypatch.setattr(check_public_surface, "ROOT", tmp_path)
    check_public_surface.main()


def test_ignored_name_above_checkout_does_not_suppress_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "build" / "checkout"
    checkout.mkdir(parents=True)
    (checkout / "link").symlink_to(checkout / "absent")
    monkeypatch.setattr(check_public_surface, "ROOT", checkout)
    with pytest.raises(SystemExit, match="link:excluded-file"):
        check_public_surface.main()


@pytest.mark.parametrize("ignored_part", sorted(check_public_surface.IGNORED_PARTS))
def test_ignored_path_contents_remain_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ignored_part: str
) -> None:
    ignored = tmp_path / ignored_part
    ignored.mkdir()
    (ignored / "ignored-link").symlink_to(tmp_path / "absent")
    monkeypatch.setattr(check_public_surface, "ROOT", tmp_path)
    check_public_surface.main()
