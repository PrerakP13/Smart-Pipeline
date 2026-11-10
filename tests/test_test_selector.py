import pytest

from src.change_detector import Change
from src.test_selector import select_tests


A = "tests/test_app.py::test_a"
B = "tests/test_app.py::test_b[1]"
C = "tests/test_other.py::test_c"
NEW = "tests/test_other.py::test_new"
MAPPING = {A: {"app.py": {8}, "tests/test_app.py": {7}},
           B: {"app.py": {10}, "tests/test_app.py": {10}}, C: {"other.py": {2}}}


def modified(path, *lines, insertion=False):
    return Change("M", path, path, frozenset(lines), insertion)


def test_file_and_line_selection_use_old_hits_in_same_module():
    changes = [modified("app.py", 10)]
    assert select_tests(changes, MAPPING, {"app.py": {1}}, MAPPING) == {A, B}
    assert select_tests(changes, MAPPING, {"app.py": {1}}, MAPPING, "line") == {B}
    assert select_tests([modified("app.py", 22)], MAPPING, {}, MAPPING, "line") == set()


def test_multiple_changes_union_only_current_nodes_and_always_include_new_nodes():
    changes = [modified("app.py", 8), modified("other.py", 2)]
    assert select_tests(changes, MAPPING, {}, {A, C, NEW}, "line") == {A, C, NEW}
    assert select_tests([], MAPPING, {}, {C, NEW}) == {NEW}


def test_insertions_use_file_coverage_and_shared_changes_run_all_tests():
    inserted = [modified("app.py", insertion=True)]
    assert select_tests(inserted, MAPPING, {}, MAPPING, "line") == {A, B}
    assert select_tests(inserted, MAPPING, {"app.py": {1}}, MAPPING, "line") == set(MAPPING)
    assert select_tests([modified("app.py", 1)], MAPPING, {"app.py": {1}}, MAPPING) == set(MAPPING)


@pytest.mark.parametrize("change", [
    Change("A", None, "new_module.py", frozenset()),
    Change("D", "app.py", None, frozenset({8})),
    Change("R", "app.py", "new.py", frozenset()),
    modified("pyproject.toml", 3), modified("data/expected.json", 2),
    modified("tests/conftest.py", 3), modified("never_measured.py", 1),
])
def test_uncertain_changes_fall_back_to_all_current_tests(change):
    assert select_tests([change], MAPPING, {}, {A, B, NEW}) == {A, B, NEW}


def test_changed_test_files_rerun_their_current_ids():
    assert select_tests([modified("tests/test_app.py", 7)], MAPPING, {}, MAPPING, "line") == {A, B}
    added = Change("A", None, "tests/test_new.py", frozenset())
    new = "tests/test_new.py::test_new"
    assert select_tests([added], MAPPING, {}, set(MAPPING) | {new}) == {new}


def test_removed_and_renamed_tests_never_return_stale_ids():
    renamed = Change("R", "tests/test_app.py", "tests/test_changed.py", frozenset())
    assert select_tests([renamed], MAPPING, {}, {C, NEW}) == {C, NEW}


def test_document_only_change_skips_unless_collected_as_a_test():
    docs = [modified("docs/example.rst", 1)]
    assert select_tests(docs, MAPPING, {}, MAPPING) == set()
    doc_test = "docs/example.rst::example.rst"
    current = {**MAPPING, doc_test: {}}
    assert doc_test in select_tests(docs, current, {}, current)


def test_unrecognized_strategy_fails():
    with pytest.raises(ValueError, match="strategy"):
        select_tests([], MAPPING, {}, MAPPING, "unknown")
