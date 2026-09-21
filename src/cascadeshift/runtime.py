"""Runtime boundaries for checkout-only evidence and portable wheel resources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path, PurePosixPath

import yaml

from cascadeshift.boundaries import WORLD_MAX_BYTES, load_bounded_yaml
from cascadeshift.engine.world import WorldSpec

BASELINE_RESOURCE = PurePosixPath("_resources/worlds/baseline/world.yaml")
CHECKOUT_MARKERS = (
    Path("pyproject.toml"),
    Path("src/cascadeshift"),
    Path("worlds"),
    Path("tasks"),
    Path("protocol"),
)


class RuntimeMode(StrEnum):
    CHECKOUT = "checkout"
    INSTALLED = "installed"


class CheckoutRequiredError(RuntimeError):
    def __init__(self, command: str) -> None:
        super().__init__(
            f"CHECKOUT_REQUIRED: `{command}` operates on frozen v1 evidence and is unavailable "
            "from an installed wheel. Run it from an authoritative CascadeShift checkout; use "
            "`cascadeshift doctor` to inspect this directory."
        )


@dataclass(frozen=True)
class RuntimeLayout:
    workspace_root: Path
    checkout_root: Path | None
    mode: RuntimeMode

    @classmethod
    def discover(cls, cwd: Path | None = None) -> RuntimeLayout:
        root = (cwd or Path.cwd()).resolve()
        git_marker = root / ".git"
        is_checkout = (
            cls._is_non_symlink_path(root, Path(".git"))
            and (git_marker.is_file() or git_marker.is_dir())
            and all(cls._is_non_symlink_path(root, marker) for marker in CHECKOUT_MARKERS)
        )
        return cls(
            workspace_root=root,
            checkout_root=root if is_checkout else None,
            mode=RuntimeMode.CHECKOUT if is_checkout else RuntimeMode.INSTALLED,
        )

    @staticmethod
    def _is_non_symlink_path(root: Path, relative: Path) -> bool:
        component = root
        for part in relative.parts:
            component /= part
            if component.is_symlink():
                return False
        return component.exists()

    def require_checkout(self, command: str) -> Path:
        if self.checkout_root is None:
            raise CheckoutRequiredError(command)
        return self.checkout_root

    def output_path(self, relative: Path, *, label: str) -> Path:
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise RuntimeError(f"invalid {label} output path: {relative}")
        candidate = self.workspace_root / relative
        component = self.workspace_root
        for part in relative.parts:
            component /= part
            if component.is_symlink():
                raise RuntimeError(f"{label} output path contains a symlink: {relative}")
            if not component.exists():
                break
        if not candidate.resolve(strict=False).is_relative_to(self.workspace_root):
            raise RuntimeError(f"{label} output path escapes repository: {relative}")
        return candidate

    def resource_bytes(self, relative: PurePosixPath) -> bytes:
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"invalid resource path: {relative}")
        return resources.files("cascadeshift").joinpath(*relative.parts).read_bytes()

    def baseline_world(self) -> WorldSpec:
        if self.checkout_root is not None:
            data = load_bounded_yaml(
                self.checkout_root / "worlds/baseline/world.yaml", max_bytes=WORLD_MAX_BYTES
            )
        else:
            return self.bundled_baseline_world()
        return WorldSpec.model_validate(data)

    def bundled_baseline_world(self) -> WorldSpec:
        return WorldSpec.model_validate(yaml.safe_load(self.resource_bytes(BASELINE_RESOURCE)))
