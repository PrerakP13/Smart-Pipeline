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
