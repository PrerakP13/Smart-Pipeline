from pathlib import Path

import pytest

from src.coverage_analyzer import capture_coverage


def test_baseline_tracks_nodeids_lines_and_shared_code(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "subject.py").write_text(
        "DEFAULT = 5\n"
        "def choose(left):\n"
        "    if left:\n"
        "        return 10\n"
        "    return 20\n"
        "def make_shared():\n"
        "    return DEFAULT\n"
        "def cleanup():\n"
        "    return True\n"
    )
    (tmp_path / "test_cases.py").write_text(
        "import pytest\n"
        "from subject import choose, make_shared, cleanup\n"
        "@pytest.fixture(scope='module')\n"
        "def common():\n"
        "    yield make_shared()\n"
        "    cleanup()\n"
        "@pytest.mark.parametrize('arg,want', [(True,10), (False,20)], ids=['left','right'])\n"
        "def test_choose(common, arg, want):\n"
        "    assert common == 5 and choose(arg) == want\n"
        "def test_unrelated():\n"
        "    assert 1\n"
    )
    mapping, shared = capture_coverage(tmp_path)
    left = "test_cases.py::test_choose[left]"
    right = "test_cases.py::test_choose[right]"
    assert set(mapping) == {left, right, "test_cases.py::test_unrelated"}
    assert {3, 4} <= mapping[left]["src/subject.py"]
    assert 5 not in mapping[left]["src/subject.py"]
    assert {3, 5} <= mapping[right]["src/subject.py"]
    assert 4 not in mapping[right]["src/subject.py"]
    assert {1, 2, 6, 7, 8, 9} <= shared["src/subject.py"]
    assert shared["src/subject.py"].isdisjoint({3, 4, 5})
    assert all(not Path(path).is_absolute() for files in mapping.values() for path in files)
    assert not list(tmp_path.glob(".coverage*"))
    assert not (tmp_path / ".pytest_cache").exists()


@pytest.mark.parametrize("test", ["def test_bad(): assert False", "import does_not_exist_123"])
def test_baseline_rejects_failures_including_collection_errors(tmp_path, test):
    (tmp_path / "test_bad.py").write_text(test)
    with pytest.raises(RuntimeError, match="Baseline coverage failed"):
        capture_coverage(tmp_path)


def test_function_fixture_setup_and_teardown_are_attributed(tmp_path):
    (tmp_path / "service.py").write_text(
        "def connect():\n    return 1\n"
        "def close():\n    return 2\n"
    )
    (tmp_path / "test_client.py").write_text(
        "import pytest, service\n"
        "@pytest.fixture\ndef client():\n"
        "    yield service.connect()\n"
        "    service.close()\n"
        "def test_client(client): assert client == 1\n"
        "def test_unrelated(): pass\n"
    )
    mapping, shared = capture_coverage(tmp_path)
    assert {2, 4} <= mapping["test_client.py::test_client"]["service.py"]
    assert "service.py" not in mapping["test_client.py::test_unrelated"]
    assert 2 not in shared["service.py"]
    assert 4 in shared["service.py"]


def test_collect_only_does_not_produce_a_false_baseline(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --collect-only\n")
    (tmp_path / "test_subject.py").write_text("def test_one(): pass\n")
    with pytest.raises(RuntimeError, match="requires a complete baseline"):
        capture_coverage(tmp_path)
