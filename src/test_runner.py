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

    def pytest_collection_finish(self, session):
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
    args = ["-q", "--rootdir=.", "-p", "no:cacheprovider", "--maxfail=0"]
    if request["collect_only"]:
        args.append("--collect-only")
    if request["tests"] is not None:
        args.extend(["--", *request["tests"]])
    code = pytest.main(args, plugins=[reports])
    result_path.write_text(json.dumps(vars(reports)))
    return int(code)


def _invoke(repo: Path, tests: list[str] | None, collect_only: bool):
    # Transfer IDs as JSON to avoid platform-specific argv size limits and
    # preserve exact parameterized IDs without parsing pytest's text output.
    with tempfile.TemporaryDirectory(prefix="testmind-pytest-") as temp:
        request = Path(temp) / "request.json"
        report = Path(temp) / "report.json"
        request.write_text(json.dumps({"tests": tests, "collect_only": collect_only}))
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(request), str(report)],
            cwd=repo, env=subject_env(repo), capture_output=True, text=True, errors="replace",
        )
        seconds = time.perf_counter() - start
        data = json.loads(report.read_text()) if report.exists() else None
    if data is None or data["collection_errors"] or proc.returncode not in (0, 1, 5):
        raise RuntimeError(f"pytest could not complete (exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}")

    collected = set(data["collected"])
    result = RunResult(seconds, data["outcomes"])
    if tests is not None and collected != set(tests):
        raise RuntimeError("pytest collected a different set of tests than requested")
    if proc.returncode == 5 and collected:
        raise RuntimeError("pytest reported no tests despite a nonempty collection")
    if proc.returncode == 1 and not result.failed:
        raise RuntimeError(f"pytest exited 1 without a failing test\n{proc.stdout}\n{proc.stderr}")
    if not collect_only and result.executed != collected:
        raise RuntimeError("pytest did not report an outcome for every collected test")
    return collected, result


def collect_tests(repo: Path) -> set[str]:
    """Collect exact pytest node IDs, raising an error for invalid suites."""
    collected, _ = _invoke(repo, None, collect_only=True)
    return collected


def run_tests(repo: Path, tests: Iterable[str] | None = None) -> RunResult:
    """Run all tests (None) or the exact node IDs supplied, including an empty set."""
    ids = None if tests is None else sorted(set(tests))
    if ids == []:
        return RunResult(0.0, {})
    _, result = _invoke(repo, ids, collect_only=False)
    return result


if __name__ == "__main__":
    raise SystemExit(_worker(Path(sys.argv[1]), Path(sys.argv[2])))
