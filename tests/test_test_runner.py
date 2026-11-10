import pytest

from src.test_runner import collect_tests, run_tests


def test_full_and_selected_run_use_exact_ids_and_capture_outcomes(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "price.py").write_text("def twice(n): return n * 2\n")
    (tmp_path / "test_price.py").write_text(
        "import pytest\n"
        "from price import twice\n"
        "@pytest.mark.parametrize('n', [1, 2])\n"
        "def test_twice(n): assert twice(n) == 2\n"
        "@pytest.mark.skip(reason='platform')\n"
        "def test_skip(): pass\n"
        "@pytest.mark.xfail(reason='known')\n"
        "def test_xfail(): assert False\n"
        "@pytest.fixture\n"
        "def broken(): raise ValueError('fixture broke')\n"
        "def test_fixture(broken): pass\n"
    )
    outcomes = {
        "test_price.py::test_twice[1]": "passed",
        "test_price.py::test_twice[2]": "failed",
        "test_price.py::test_skip": "skipped",
        "test_price.py::test_xfail": "xfailed",
        "test_price.py::test_fixture": "error",
    }
    assert collect_tests(tmp_path) == set(outcomes)
    full = run_tests(tmp_path)
    assert full.outcomes == outcomes
    assert full.duration > 0
    assert full.failed == {"test_price.py::test_twice[2]", "test_price.py::test_fixture"}
    selected = run_tests(tmp_path, ["test_price.py::test_twice[2]"])
    assert selected.outcomes == {"test_price.py::test_twice[2]": "failed"}
    with pytest.raises(RuntimeError):
        run_tests(tmp_path, ["test_price.py::test_nonexistent"])


def test_empty_selection_never_runs_pytest(tmp_path):
    (tmp_path / "conftest.py").write_text("raise RuntimeError('should not execute')\n")
    assert run_tests(tmp_path, []).outcomes == {}


def test_empty_subject(tmp_path):
    assert collect_tests(tmp_path) == set()
    assert run_tests(tmp_path).outcomes == {}


def test_collection_errors_are_not_recorded_as_killed_mutants(tmp_path):
    (tmp_path / "test_broken.py").write_text("def invalid python")
    with pytest.raises(RuntimeError, match="SyntaxError"):
        run_tests(tmp_path)
    with pytest.raises(RuntimeError, match="SyntaxError"):
        collect_tests(tmp_path)
