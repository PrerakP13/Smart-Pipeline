"""Run the subject project's pytest suite in a fresh process for each measurement."""

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    duration: float
    outcomes: dict[str, str]

    @property
    def executed(self) -> set[str]:
        """Node IDs with a terminal pytest outcome, including skips."""
        return set(self.outcomes)

    @property
    def failed(self) -> set[str]:
        return {node for node, outcome in self.outcomes.items() if outcome in {"failed", "error"}}


@dataclass
class SelectionRun:
    run: RunResult
    available: set[str]
    selected: set[str]
    selection_seconds: float


def subject_env(repo: Path) -> dict[str, str]:
    """Use the subject checkout for both flat and src-layout projects."""
    repo = repo.resolve()
    env = os.environ.copy()
    paths = [str(repo / "src"), str(repo)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env.update(PYTHONPATH=os.pathsep.join(paths), PYTHONDONTWRITEBYTECODE="1")
    return env


class _Reports:
    def __init__(self):
        self.collected = []
        self.outcomes = {}
        self.collection_errors = []
        self.available = []
        self.selected = []
        self.selection_seconds = 0.0

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_sessionfinish(self, session):
        # A collection wrapper may finish after collection_finish. Validate
        # the final item list, including any late subject-plugin changes.
        self.collected = [item.nodeid for item in session.items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(report.nodeid)

    def pytest_runtest_logreport(self, report):
        node = report.nodeid
        if report.failed:
            self.outcomes[node] = "failed" if report.when == "call" else "error"
        elif self.outcomes.get(node) in {"failed", "error"}:
            return
        elif report.skipped:
            self.outcomes[node] = "xfailed" if hasattr(report, "wasxfail") else "skipped"
        elif report.when == "call":
            self.outcomes[node] = "xpassed" if hasattr(report, "wasxfail") else "passed"


def _worker(request_path: Path, result_path: Path) -> int:
    # This script lives outside the subject. Remove its directory from the
    # module search path so the subject cannot accidentally import our modules.
    script_dir = str(Path(__file__).resolve().parent)
    if sys.path[0] == script_dir:
        sys.path.pop(0)
    import pytest

    request = json.loads(request_path.read_text())
    reports = _Reports()
    selection = request.get("selection")
    plugins = [reports]
    if selection is not None:
        # Load the same selector used by the public API without importing our
        # `src` package: the subject may have its own package with that name.
        import importlib.util
        from types import SimpleNamespace

        spec = importlib.util.spec_from_file_location(
            "_testmind_selection_policy", Path(__file__).with_name("test_selector.py")
        )
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        mapping = selection["mapping"]
        shared = {path: set(lines) for path, lines in selection["shared"].items()}
        changes = [SimpleNamespace(**(change | {"old_lines": frozenset(change["old_lines"])}))
                   for change in selection["changes"]]

        class SelectionPlugin:
            def pytest_configure(self, config):
                if getattr(config.option, "numprocesses", None):
                    raise pytest.UsageError("TestMind selection requires single-process pytest")

            @pytest.hookimpl(wrapper=True, tryfirst=True)
            def pytest_collection(self, session):
                # Resume after the complete collection phase, including all
                # collection_modifyitems wrappers and collection_finish hooks.
                outcome = yield
                started = time.perf_counter()
                items = session.items
                current = {item.nodeid for item in items}
                if len(current) != len(items):
                    raise pytest.UsageError("TestMind requires unique pytest node IDs")
                selected = policy.select_tests(
                    changes, mapping, shared, current, selection["strategy"]
                )
                kept, deselected = [], []
                for item in items:
                    (kept if item.nodeid in selected else deselected).append(item)
                items[:] = kept
                session.testscollected = len(kept)
                reports.available = sorted(current)
                reports.selected = sorted(selected)
                reports.selection_seconds = time.perf_counter() - started
                if deselected:
                    session.config.hook.pytest_deselected(items=deselected)
                return outcome

        plugins.append(SelectionPlugin())
    args = ["-q", "--rootdir=.", "-p", "no:cacheprovider", "--maxfail=0"]
    if request["collect_only"]:
        args.append("--collect-only")
    if request["tests"] is not None:
        args.extend(["--", *request["tests"]])
    code = pytest.main(args, plugins=plugins)
    result_path.write_text(json.dumps(vars(reports)))
    return int(code)


def _invoke(repo: Path, tests: list[str] | None, collect_only: bool, selection=None):
    # Transfer IDs as JSON to avoid platform-specific argv size limits and
    # preserve exact parameterized IDs without parsing pytest's text output.
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="testmind-pytest-") as temp:
        request = Path(temp) / "request.json"
        report = Path(temp) / "report.json"
        request.write_text(json.dumps({"tests": tests, "collect_only": collect_only,
                                       "selection": selection}))
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(request), str(report)],
            cwd=repo, env=subject_env(repo), capture_output=True, text=True, errors="replace",
        )
        data = json.loads(report.read_text()) if report.exists() else None
    seconds = time.perf_counter() - start
    if data is None or data["collection_errors"] or proc.returncode not in (0, 1, 5):
        raise RuntimeError(f"pytest could not complete (exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}")

    collected = set(data["collected"])
    if len(collected) != len(data["collected"]):
        raise RuntimeError("TestMind requires unique pytest node IDs")
    result = RunResult(seconds, data["outcomes"])
    if tests is not None and collected != set(tests):
        raise RuntimeError("pytest collected a different set of tests than requested")
    if proc.returncode == 5 and collected:
        raise RuntimeError("pytest reported no tests despite a nonempty collection")
    if proc.returncode == 1 and not result.failed:
        raise RuntimeError(f"pytest exited 1 without a failing test\n{proc.stdout}\n{proc.stderr}")
    if not collect_only and result.executed != collected:
        raise RuntimeError("pytest did not report an outcome for every collected test")
    if selection is not None and collected != set(data["selected"]):
        raise RuntimeError("pytest collected a different set of tests than selected")
    return collected, result, data


def collect_tests(repo: Path) -> set[str]:
    """Collect exact pytest node IDs, raising an error for invalid suites."""
    collected, _, _ = _invoke(repo, None, collect_only=True)
    return collected


def run_tests(repo: Path, tests: Iterable[str] | None = None) -> RunResult:
    """Run all tests (None) or the exact node IDs supplied, including an empty set."""
    ids = None if tests is None else sorted(set(tests))
    if ids == []:
        return RunResult(0.0, {})
    _, result, _ = _invoke(repo, ids, collect_only=False)
    return result


def run_selection(repo: Path, mapping, shared, changes, strategy="file") -> SelectionRun:
    """Discover, select and run in one fresh pytest process.

    All wall time is charged once. The tiny selector calculation is split out
    from run.duration; normal pytest startup/collection remains execution cost.
    Only changed-file coverage is sent, while retaining every baseline test ID
    so newly discovered and newly parameterized tests are always included.
    """
    if strategy not in {"file", "line"}:
        raise ValueError("strategy must be 'file' or 'line'")
    started = time.perf_counter()
    changes = list(changes)
    paths = {change.old_path for change in changes}
    payload = {
        "strategy": strategy,
        "mapping": {node: {path: sorted(lines) for path, lines in files.items() if path in paths}
                    for node, files in mapping.items()},
        "shared": {path: sorted(lines) for path, lines in shared.items() if path in paths},
        "changes": [{"status": change.status, "old_path": change.old_path,
                     "new_path": change.new_path, "old_lines": sorted(change.old_lines),
                     "has_insertions": change.has_insertions} for change in changes],
    }
    _, result, data = _invoke(repo, None, collect_only=False, selection=payload)
    duration = time.perf_counter() - started
    selection_seconds = data["selection_seconds"]
    result.duration = duration - selection_seconds
    return SelectionRun(result, set(data["available"]), set(data["selected"]), selection_seconds)


if __name__ == "__main__":
    raise SystemExit(_worker(Path(sys.argv[1]), Path(sys.argv[2])))
