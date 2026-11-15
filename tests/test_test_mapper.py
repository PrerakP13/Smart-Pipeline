import sqlite3

import pytest

from src.test_mapper import load_map, save_map


def test_roundtrip_preserves_inventory_edges_and_shared_execution(tmp_path):
    path = tmp_path / "cache" / "history sqlite.db"
    mapping = {"test_io.py::test_read[1]": {"src/read.py": {7, 9}, "src/empty.py": set()},
               "test_io.py::test_skipped": {}}
    shared = {"src/read.py": {1, 2}, "conftest.py": {3}}
    save_map(path, "base", mapping, shared)
    assert load_map(path, "base") == (mapping, shared)


def test_snapshots_are_isolated_and_can_be_replaced(tmp_path):
    path = tmp_path / "history.sqlite"
    old = {"test_io.py::test_a": {"io.py": {1}}}
    save_map(path, "a", old, {})
    save_map(path, "b", {}, {})
    save_map(path, "a", {}, {"io.py": {3}})
    assert load_map(path, "a") == ({}, {"io.py": {3}})
    assert load_map(path, "b") == ({}, {})
    with pytest.raises(ValueError, match="No coverage snapshot"):
        load_map(path, "c")


def test_failed_replacement_rolls_back(tmp_path):
    path = tmp_path / "history.sqlite"
    original = {"test_original": {"app.py": {1, 3}}}
    save_map(path, "base", original, {})
    with pytest.raises(TypeError):
        save_map(path, "base", {"broken": {"app.py": {object()}}}, {})
    assert load_map(path, "base") == (original, {})


def test_missing_database_load_has_no_side_effects(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        load_map(path, "base")
    assert not path.exists()


def test_legacy_snapshots_require_individual_recapture(tmp_path):
    path = tmp_path / "legacy.sqlite"
    old = {"test_cli": {"test_cli.py": {2}}}
    for commit in ("a", "b"):
        save_map(path, commit, old, {})
    # The old database schema had no collector version and no child coverage.
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE capture_versions")
    with pytest.raises(ValueError, match="baseline command again"):
        load_map(path, "a")

    captured = {"test_cli": {"test_cli.py": {2}, "app.py": {8}}}
    save_map(path, "a", captured, {})
    assert load_map(path, "a") == (captured, {})
    with pytest.raises(ValueError, match="baseline command again"):
        load_map(path, "b")


def test_incompatible_collector_version_is_rejected(tmp_path):
    path = tmp_path / "future.sqlite"
    save_map(path, "a", {}, {})
    with sqlite3.connect(path) as db:
        db.execute("UPDATE capture_versions SET version = 999")
    with pytest.raises(ValueError, match="incompatible collector"):
        load_map(path, "a")
