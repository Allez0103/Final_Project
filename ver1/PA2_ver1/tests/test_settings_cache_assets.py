from dataclasses import replace
from pathlib import Path

import pytest

from pa2.settings.config import AppSettings, SettingsStore
from pa2.storage.assets import AssetStore, sha256_file
from pa2.storage.cache import CacheStore, cache_key
from pa2.storage.layout import DataLayout


def test_automatic_geometry_defaults():
    resolved = AppSettings().resolved_for_diagonal(1000)
    assert resolved["geometry_epsilon_mm"] == 0.001
    assert resolved["exit_clearance_mm"] == 5.0
    assert resolved["coarse_mesh_deflection_mm"] == 1.0


def test_settings_snapshot_validation(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    settings = replace(AppSettings(), max_directions=32)
    store.save(settings)
    assert store.load().max_directions == 32
    with pytest.raises(ValueError): replace(settings, max_directions=3).validate()


def test_cache_key_ignores_json_key_order_and_changes_relevant_setting():
    a = cache_key("mesh", ["a"], "v1", {"x": 1, "y": 2})
    b = cache_key("mesh", ["a"], "v1", {"y": 2, "x": 1})
    c = cache_key("mesh", ["a"], "v1", {"x": 1, "y": 3})
    assert a == b and a != c


def test_asset_ingest_copies_and_preserves_source(tmp_path):
    source = tmp_path / "input.step"; source.write_bytes(b"ISO-10303-21;\nEND-ISO-10303-21;")
    original = sha256_file(source)
    layout = DataLayout(tmp_path / "data")
    managed = AssetStore(layout).ingest(source, "assembly_step")
    assert sha256_file(source) == original
    assert sha256_file(layout.root / managed.relative_path) == original
    assert source.read_bytes() == b"ISO-10303-21;\nEND-ISO-10303-21;"


def test_cache_only_publishes_complete_entries(tmp_path):
    store = CacheStore(DataLayout(tmp_path / "data"))
    with pytest.raises(RuntimeError):
        with store.publisher("shape", "key") as path:
            (path / "partial.txt").write_text("x")
            raise RuntimeError("stop")
    assert store.get("shape", "key") is None
    with store.publisher("shape", "key") as path:
        (path / "value.txt").write_text("ok")
    assert store.get("shape", "key") is not None

