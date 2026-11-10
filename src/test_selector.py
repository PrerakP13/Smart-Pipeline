"""Select current pytest node IDs using coverage from the baseline revision."""

from collections.abc import Iterable
from pathlib import PurePosixPath

from .change_detector import Change
from .test_mapper import CoverageMap, SharedLines


def _documentation(filename: str) -> bool:
    path = PurePosixPath(filename)
    if path.suffix.lower() not in {".md", ".rst", ".txt"}:
        return False
    return (path.parts[0] == "docs" or
            (len(path.parts) == 1 and path.stem.lower() in {"readme", "changelog", "license"}))


def select_tests(changes: Iterable[Change], mapping: CoverageMap, shared: SharedLines,
                 current_tests: Iterable[str], strategy: str = "file") -> set[str]:
    """Use baseline-side coordinates and return only IDs still present on the target.

    Unattributed execution on a changed line can affect any test. A pure insertion
    lacks a baseline coordinate, so use file coverage, or all tests for a shared
    file. A previously uncovered line within a mapped file can select zero tests
    in line mode; the full comparison measures the risk of this heuristic.
    """
    if strategy not in {"file", "line"}:
        raise ValueError("strategy must be 'file' or 'line'")
    current = set(current_tests)
    selected = current.difference(mapping)  # New or newly parameterized tests.
    current_by_file: dict[str, set[str]] = {}
    for nodeid in current:
        current_by_file.setdefault(nodeid.partition("::")[0], set()).add(nodeid)

    for change in changes:
        paths = [p for p in (change.old_path, change.new_path) if p is not None]
        if paths and all(_documentation(p) and p not in current_by_file for p in paths):
            continue
        if any(PurePosixPath(p).name == "conftest.py" for p in paths):
            return current
        if change.status == "A" and change.new_path in current_by_file:
            selected.update(current_by_file[change.new_path])
            continue
        if change.status != "M" or change.old_path is None:
            # Unknown effects of renames, deletions, new production files or type changes.
            return current
        path = change.old_path
        if not path.endswith(".py"):
            return current  # Includes settings, test data and dependency files.
        if path in current_by_file:
            selected.update(current_by_file[path])
        shared_lines = shared.get(path, set())
        if shared_lines and (change.has_insertions or not change.old_lines
                             or shared_lines.intersection(change.old_lines)):
            return current
        covered = {nodeid: files[path] for nodeid, files in mapping.items() if path in files}
        if not covered and path not in current_by_file:
            return current
        if strategy == "file" or change.has_insertions or not change.old_lines:
            selected.update(current.intersection(covered))
        else:
            selected.update(nodeid for nodeid, lines in covered.items()
                            if nodeid in current and change.old_lines.intersection(lines))
    return selected
