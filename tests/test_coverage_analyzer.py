from pathlib import Path

import pytest

from src.coverage_analyzer import capture_coverage
from src.change_detector import Change
from src.test_selector import select_tests


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


@pytest.mark.parametrize("nested", [False, True], ids=["direct-child", "nested-child"])
def test_python_cli_coverage_preserves_parameterized_parent_context(tmp_path, nested):
    # Neither CLI module is imported by pytest. The measured function bodies
    # therefore prove that real child execution reaches the baseline map.
    (tmp_path / "cli_app.py").write_text(
        "import os, sys\n"
        "def choose(value):\n"
        "    assert os.environ['CLI_TOKEN'] == value\n"
        "    if value == 'left':\n"
        "        return 'LEFT'\n"
        "    return 'RIGHT'\n"
        "if __name__ == '__main__':\n"
        "    print(choose(sys.argv[1]))\n"
    )
    (tmp_path / "cli_bridge.py").write_text(
        "import os, subprocess, sys\n"
        "if __name__ == '__main__':\n"
        "    result = subprocess.run(\n"
        "        [sys.executable, '-m', 'cli_app', sys.argv[1]],\n"
        "        env=os.environ.copy(), cwd=os.getcwd(),\n"
        "        check=True, capture_output=True, text=True)\n"
        "    print(result.stdout, end='')\n"
    )
    module = "cli_bridge" if nested else "cli_app"
    (tmp_path / "test_cli.py").write_text(
        "import os, subprocess, sys, tempfile\n"
        "import pytest\n"
        "@pytest.mark.parametrize('arg,want', [('left','LEFT'), ('right','RIGHT')], "
        "ids=['left','right'])\n"
        "def test_cli(arg, want):\n"
        "    environment = os.environ.copy()\n"
        "    environment['CLI_TOKEN'] = arg\n"
        "    with tempfile.TemporaryDirectory() as elsewhere:\n"
        "        result = subprocess.run(\n"
        f"            [sys.executable, '-m', {module!r}, arg],\n"
        "            cwd=elsewhere, env=environment,\n"
        "            check=True, capture_output=True, text=True)\n"
        "    assert result.stdout.strip() == want\n"
        "def test_unrelated():\n"
        "    assert 1 + 1 == 2\n"
    )

    mapping, shared = capture_coverage(tmp_path)
    left = "test_cli.py::test_cli[left]"
    right = "test_cli.py::test_cli[right]"
    unrelated = "test_cli.py::test_unrelated"
    assert set(mapping) == {left, right, unrelated}
    assert {3, 4, 5} <= mapping[left]["cli_app.py"]
    assert 6 not in mapping[left]["cli_app.py"]
    assert {3, 4, 6} <= mapping[right]["cli_app.py"]
    assert 5 not in mapping[right]["cli_app.py"]
    assert "cli_app.py" not in mapping[unrelated]
    assert not shared.get("cli_app.py", set()).intersection({3, 4, 5, 6})
    if nested:
        assert "cli_bridge.py" in mapping[left]
        assert "cli_bridge.py" in mapping[right]
        assert "cli_bridge.py" not in mapping[unrelated]

    changes = [Change("M", "cli_app.py", "cli_app.py", frozenset({5}))]
    assert select_tests(changes, mapping, shared, mapping, "line") == {left}
    assert select_tests(changes, mapping, shared, mapping, "file") == {left, right}
    assert all(not Path(path).is_absolute() for files in mapping.values() for path in files)
    assert not list(tmp_path.rglob(".coverage*"))


def test_python_cli_shared_fixture_and_teardown_remain_conservative(tmp_path):
    (tmp_path / "lifecycle.py").write_text(
        "import sys\n"
        "def setup():\n"
        "    return 'ready'\n"
        "def cleanup():\n"
        "    return 'closed'\n"
        "if __name__ == '__main__':\n"
        "    print(setup() if sys.argv[1] == 'setup' else cleanup())\n"
    )
    (tmp_path / "test_lifecycle.py").write_text(
        "import subprocess, sys\n"
        "import pytest\n"
        "@pytest.fixture(scope='module')\n"
        "def resource():\n"
        "    ready = subprocess.check_output(\n"
        "        [sys.executable, '-m', 'lifecycle', 'setup'], text=True)\n"
        "    yield ready.strip()\n"
        "    closed = subprocess.check_output(\n"
        "        [sys.executable, '-m', 'lifecycle', 'cleanup'], text=True)\n"
        "    assert closed.strip() == 'closed'\n"
        "def test_first(resource):\n"
        "    assert resource == 'ready'\n"
        "def test_second(resource):\n"
        "    assert resource == 'ready'\n"
        "def test_unrelated():\n"
        "    assert True\n"
    )

    mapping, shared = capture_coverage(tmp_path)
    assert set(mapping) == {
        "test_lifecycle.py::test_first", "test_lifecycle.py::test_second",
        "test_lifecycle.py::test_unrelated",
    }
    assert {3, 5} <= shared["lifecycle.py"]
    assert all(3 not in files.get("lifecycle.py", set()) for files in mapping.values())
    assert any(5 in files.get("lifecycle.py", set()) for files in mapping.values())
    for changed_line in (3, 5):
        changes = [Change("M", "lifecycle.py", "lifecycle.py", frozenset({changed_line}))]
        for strategy in ("file", "line"):
            assert select_tests(changes, mapping, shared, mapping, strategy) == set(mapping)
    assert not list(tmp_path.rglob(".coverage*"))
