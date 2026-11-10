"""Build a historical per-test coverage map by running pytest in the subject."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from .test_runner import subject_env


def capture_coverage(repo: Path) -> tuple[dict[str, dict[str, set[int]]], dict[str, set[int]]]:
    """Return per-node coverage and shared lines for a passing baseline.

    Paths are relative to the subject root. Line numbers belong to the exact
    baseline checkout. The worker lives in a fresh Python process so imports
    and pytest plugins from the subject cannot leak into later experiments.
    """
    root = Path(repo).resolve(strict=True)
    worker = Path(__file__).with_name("_coverage_worker.py")
    with TemporaryDirectory(prefix="testmind-coverage-") as temp:
        report = Path(temp, "coverage.json")
        run = subprocess.run(
            [sys.executable, str(worker), str(report)],
            cwd=root, env=subject_env(root), capture_output=True, text=True, errors="replace",
        )
        if run.returncode != 0:
            raise RuntimeError(
                f"Baseline coverage failed (exit {run.returncode}).\n"
                + (run.stdout + run.stderr)[-12000:]
            )
        if not report.is_file():
            raise RuntimeError("Baseline finished without a coverage report.")
        data = json.loads(report.read_text(encoding="utf-8"))
    tests = {
        test: {path: set(lines) for path, lines in files.items()}
        for test, files in data["tests"].items()
    }
    shared = {path: set(lines) for path, lines in data["shared"].items()}
    return tests, shared
