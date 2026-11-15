"""Capture a green baseline, then compare full and selective pytest runs."""

import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sqlite3
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import perf_counter

import coverage
import pytest

from src.change_detector import detect_changes, git_root, resolve_commit
from src.coverage_analyzer import capture_coverage
from src.evaluator import evaluate
from src.test_mapper import CAPTURE_VERSION, load_map, save_map
from src.test_runner import collect_tests, run_tests
from src.test_selector import select_tests


@contextmanager
def checkout(repo, ref):
    """Give a run its own files and index without touching the user's checkout."""
    root = git_root(repo)
    sha = resolve_commit(root, ref)
    with TemporaryDirectory(prefix="testmind-checkout-") as temp:
        subject = Path(temp) / "subject"
        for args in (
            ["clone", "--quiet", "--shared", "--no-checkout", "--", str(root), str(subject)],
            ["-C", str(subject), "checkout", "--quiet", "--detach", sha],
        ):
            subprocess.run(["git", *args], check=True, capture_output=True, text=True)
        yield subject


def write_json(path, data):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    out = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
    temporary = Path(out.name)
    try:
        with out:
            json.dump(data, out, indent=2, ensure_ascii=True, allow_nan=False)
            out.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def environment():
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "coverage": coverage.__version__,
        "pytest": pytest.__version__,
    }


def baseline(repo: Path, base: str, db: Path) -> dict:
    """Always capture the exact committed files, even from a dirty checkout."""
    root = git_root(repo)
    sha = resolve_commit(root, base)
    start = perf_counter()
    with checkout(root, sha) as clean:
        mapping, shared = capture_coverage(clean)
    if not mapping:
        raise ValueError("The baseline contains no collected tests.")
    save_map(db, sha, mapping, shared)
    mapped_files = set(shared)
    for files in mapping.values():
        mapped_files.update(files)
    return {
        "schema_version": 1, "capture_version": CAPTURE_VERSION,
        "base": sha, "environment": environment(),
        "test_count": len(mapping), "baseline_seconds": perf_counter() - start,
        "mapped_python_files": len(mapped_files),
    }


def _summary(run):
    return {"duration": run.duration, "count": len(run.outcomes),
            "failed": sorted(run.failed), "outcomes": dict(sorted(run.outcomes.items()))}


def _prepare(repo, base, db):
    start = perf_counter()
    root = git_root(repo)
    sha = resolve_commit(root, base)
    mapping, shared = load_map(db, sha)
    changes = detect_changes(root, sha)
    current = collect_tests(root)
    return root, sha, mapping, shared, changes, current, perf_counter() - start


def _select(strategy, mapping, shared, changes, current, common_seconds):
    start = perf_counter()
    nodes = select_tests(changes, mapping, shared, current, strategy=strategy)
    return nodes, common_seconds + (perf_counter() - start)


def run_selected(repo: Path, base: str, db: Path, strategy: str) -> dict:
    """Perform a normal RTS run without running the benchmark suite."""
    root, sha, mapping, shared, changes, current, common = _prepare(repo, base, db)
    nodes, selection_seconds = _select(strategy, mapping, shared, changes, current, common)
    selected = run_tests(root, nodes)
    return {"schema_version": 1, "base": sha, "target_head": resolve_commit(root, "HEAD"),
            "strategy": strategy, "available": len(current), "selected": sorted(nodes),
            "selection_seconds": selection_seconds, **_summary(selected)}


def compare(repo: Path, base: str, db: Path, strategies=("file", "line")) -> dict:
    """Benchmark one target tree. Both selection paths pay the common preparation cost."""
    root, sha, mapping, shared, changes, current, common_seconds = _prepare(repo, base, db)
    plans = {strategy: _select(strategy, mapping, shared, changes, current, common_seconds)
             for strategy in strategies}

    full = run_tests(root)
    if set(full.outcomes) != set(current):
        raise RuntimeError("Full-run inventory differs from target collection. Check for unstable test IDs or early exit.")
    result = {
        "schema_version": 1, "base": sha, "target_head": resolve_commit(root, "HEAD"),
        "environment": environment(), "changes": [
            {"status": c.status, "old_path": c.old_path, "new_path": c.new_path,
             "old_lines": sorted(c.old_lines), "has_insertions": c.has_insertions}
            for c in changes
        ], "common_selection_seconds": common_seconds, "full": _summary(full), "strategies": {},
    }
    for strategy, (nodes, seconds) in plans.items():
        selected = run_tests(root, nodes)
        if set(selected.outcomes) != set(nodes):
            raise RuntimeError(f"{strategy} run did not report every selected node ID.")
        result["strategies"][strategy] = {
            **_summary(selected), "selected": sorted(nodes),
            "metrics": evaluate(full, selected, seconds),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="action", required=True)
    capture = modes.add_parser("baseline", help="Capture coverage on a clean checkout of --base.")
    benchmark = modes.add_parser("compare", help="Compare the current tree or an isolated --target commit.")
    run = modes.add_parser("run", help="Run only selected tests; exit 1 on test failures.")
    for mode in (capture, benchmark, run):
        mode.add_argument("--repo", type=Path, required=True, help="Subject Git repository")
        mode.add_argument("--base", required=True, help="Baseline commit or ref")
        mode.add_argument("--db", type=Path, required=True, help="Coverage SQLite file, preferably outside subject")
        mode.add_argument("--output", type=Path, help="Save result JSON here (default: stdout)")
    for mode in (benchmark, run):
        mode.add_argument("--target", help="Target commit or ref (default: current working tree)")
    run.add_argument("--strategy", choices=("file", "line"), default="file")
    benchmark.add_argument("--strategy", choices=("file", "line", "both"), default="both")
    args = parser.parse_args()
    try:
        if args.output and args.output.resolve() == args.db.resolve():
            raise ValueError("Choose distinct database and report paths.")
        if args.action == "baseline":
            report = baseline(args.repo, args.base, args.db)
        else:
            sha = resolve_commit(git_root(args.repo), args.base)
            target = checkout(args.repo, args.target) if args.target else nullcontext(args.repo)
            with target as subject:
                if args.action == "run":
                    report = run_selected(subject, sha, args.db, args.strategy)
                else:
                    strategies = ("file", "line") if args.strategy == "both" else (args.strategy,)
                    report = compare(subject, sha, args.db, strategies)
        if args.output:
            write_json(args.output, report)
            print(args.output)
        else:
            print(json.dumps(report, indent=2))
        if args.action == "run" and report["failed"]:
            parser.exit(1)
    except (ValueError, RuntimeError, OSError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"testmind: {exc}\n")


if __name__ == "__main__":
    main()
