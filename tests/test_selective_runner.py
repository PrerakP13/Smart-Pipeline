"""Exercise fresh discovery and selection in the same subject pytest process."""

import pytest

from src.change_detector import Change
from src.test_runner import run_selection


def modified(path, *lines):
    return Change("M", path, path, frozenset(lines))


@pytest.mark.parametrize("strategy", ["file", "line"])
def test_selection_collects_once_and_keeps_subject_imports_isolated(tmp_path, strategy):
    package = tmp_path / "src"
    package.mkdir()
    (package / "__init__.py").write_text("SUBJECT = True\n")
    (package / "pricing.py").write_text(
        "def price():\n    return -1\n\ndef tax():\n    return 5\n"
    )
    (tmp_path / "test_pricing.py").write_text(
        "from pathlib import Path\n"
        "import src\n"
        "from src.pricing import price, tax\n"
        "counter = Path('imports.txt')\n"
        "counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')\n"
        "def test_price():\n    assert src.SUBJECT\n    assert price() == 20\n"
        "def test_tax():\n    assert tax() == 5\n"
        "def test_unrelated():\n    pass\n"
    )
    (tmp_path / "test_new.py").write_text("def test_new():\n    pass\n")
    price = "test_pricing.py::test_price"
    tax = "test_pricing.py::test_tax"
    unrelated = "test_pricing.py::test_unrelated"
    new = "test_new.py::test_new"
    mapping = {
        price: {"src/pricing.py": {2}},
        tax: {"src/pricing.py": {5}},
        unrelated: {},
    }

    result = run_selection(
        tmp_path, mapping, {}, [modified("src/pricing.py", 2)], strategy
    )

    expected = {price, new} | ({tax} if strategy == "file" else set())
    assert result.available == {price, tax, unrelated, new}
    assert result.selected == expected
    assert result.run.executed == expected
    assert result.run.failed == {price}
    assert result.selection_seconds >= 0
    assert (tmp_path / "imports.txt").read_text() == "1"


def test_current_parameter_ids_replace_removed_ids_and_select_new_cases(tmp_path):
    source = tmp_path / "cases.py"
    source.write_text("VALUES = ['removed', 'keep']\n")
    (tmp_path / "test_cases.py").write_text(
        "import pytest\n"
        "from cases import VALUES\n"
        "@pytest.mark.parametrize('value', VALUES)\n"
        "def test_value(value):\n    assert value in {'keep', 'new|$'}\n"
    )
    removed = "test_cases.py::test_value[removed]"
    kept = "test_cases.py::test_value[keep]"
    added = "test_cases.py::test_value[new|$]"
    mapping = {removed: {"cases.py": {1}}, kept: {"cases.py": {2}}}
    source.write_text("VALUES = ['keep', 'new|$']\n")

    result = run_selection(tmp_path, mapping, {}, [modified("cases.py", 1)], "line")

    assert result.available == {kept, added}
    assert result.selected == {added}
    assert result.run.outcomes == {added: "passed"}


def test_empty_selection_still_discovers_without_running_fixtures(tmp_path):
    (tmp_path / "test_untouched.py").write_text(
        "import pytest\n"
        "from pathlib import Path\n"
        "Path('discovered.txt').write_text('yes')\n"
        "@pytest.fixture(autouse=True)\n"
        "def forbidden():\n    raise AssertionError('fixture must not run')\n"
        "def test_untouched():\n    raise AssertionError('test must not run')\n"
    )
    node = "test_untouched.py::test_untouched"

    result = run_selection(tmp_path, {node: {}}, {}, [], "line")

    assert result.available == {node}
    assert result.selected == set()
    assert result.run.outcomes == {}
    assert (tmp_path / "discovered.txt").read_text() == "yes"


@pytest.mark.parametrize("path", ["conftest.py", "pytest.ini"])
def test_uncertain_configuration_changes_keep_full_suite_fallback(tmp_path, path):
    (tmp_path / "test_subject.py").write_text(
        "def test_first():\n    pass\n"
        "def test_second():\n    pass\n"
    )
    nodes = {"test_subject.py::test_first", "test_subject.py::test_second"}

    result = run_selection(
        tmp_path, dict.fromkeys(nodes, {}), {}, [modified(path, 1)], "line"
    )

    assert result.available == nodes
    assert result.selected == nodes
    assert result.run.outcomes == dict.fromkeys(nodes, "passed")


def test_collection_error_is_not_hidden_by_a_zero_selection(tmp_path):
    (tmp_path / "test_broken.py").write_text("def invalid python")

    with pytest.raises(RuntimeError, match="SyntaxError"):
        run_selection(tmp_path, {}, {}, [], "line")


@pytest.mark.parametrize("wrapper", [False, True], ids=["ordinary", "tryfirst-wrapper"])
def test_subject_collection_hook_filters_and_orders_before_selection(tmp_path, wrapper):
    prefix = "import pytest\n@pytest.hookimpl(wrapper=True, tryfirst=True)\n" if wrapper else ""
    pause = "    yield\n" if wrapper else ""
    (tmp_path / "conftest.py").write_text(
        prefix + "def pytest_collection_modifyitems(config, items):\n" + pause +
        "    removed = [item for item in items if item.name == 'test_filtered']\n"
        "    items[:] = [item for item in reversed(items) if item.name != 'test_filtered']\n"
        "    config.hook.pytest_deselected(items=removed)\n"
    )
    (tmp_path / "test_order.py").write_text(
        "from pathlib import Path\n"
        "def test_first():\n    assert Path('second-ran.txt').is_file()\n"
        "def test_second():\n    Path('second-ran.txt').write_text('yes')\n"
        "def test_filtered():\n    raise AssertionError('plugin filtered this test')\n"
    )
    first = "test_order.py::test_first"
    second = "test_order.py::test_second"
    filtered = "test_order.py::test_filtered"
    mapping = {node: {"app.py": {1}} for node in (first, second, filtered)}

    result = run_selection(tmp_path, mapping, {}, [modified("app.py", 1)], "line")

    assert result.available == {first, second}
    assert result.selected == {first, second}
    assert result.run.outcomes == {first: "passed", second: "passed"}
