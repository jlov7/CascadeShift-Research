"""World file I/O: canonical YAML serialization with content-hash checks."""

from __future__ import annotations

from pathlib import Path

import yaml

from cascadeshift.boundaries import WORLD_MAX_BYTES, load_bounded_yaml
from cascadeshift.engine.world import WorldSpec


def dump_world(world: WorldSpec) -> str:
    data = world.model_dump(mode="json")
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def load_world(path: str | Path) -> WorldSpec:
    data = load_bounded_yaml(Path(path), max_bytes=WORLD_MAX_BYTES)
    return WorldSpec.model_validate(data)


def write_world(world: WorldSpec, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(dump_world(world))
