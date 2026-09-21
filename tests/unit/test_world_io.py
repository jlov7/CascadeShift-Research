"""Round-trip and determinism requirements for world files (H-01 support)."""

from cascadeshift.engine.world_io import dump_world, load_world
from cascadeshift.retrieval.catalog import (
    WORLD_SEED,
    generate_baseline_world,
)


def test_world_yaml_roundtrip_preserves_hash(tmp_path):
    w = generate_baseline_world()
    p = tmp_path / "world.yaml"
    from cascadeshift.engine.world_io import write_world

    write_world(w, p)
    loaded = load_world(p)
    assert loaded.content_hash() == w.content_hash()
    assert len(loaded.rules) == 128


def test_dump_is_deterministic():
    w = generate_baseline_world()
    assert dump_world(w) == dump_world(w)
    assert w.generator_seed == WORLD_SEED
