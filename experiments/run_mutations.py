"""Evaluate one controlled source mutation per clean checkout.

The UTF-8 JSON config contains a "mutations" list. Each object specifies a
unique "id", a repository-relative Python source "path", the exact "before"
snippet (occurs once in the base), and its "after" replacement. Example:

    {"mutations": [{"id": "inclusive-limit", "path": "src/limit.py",
                    "before": "return n < limit", "after": "return n <= limit"}]}

Only mutants detected by the unselected full suite can measure RTS retention.
The report preserves per-run results and counts invalid or inconclusive trials
separately. An empty denominator produces JSON null.
"""

import argparse
import json
import subprocess
import sqlite3
import sys
from pathlib import Path
from time import perf_counter

from experiments.run_experiment import baseline, checkout, compare, write_json
from src.change_detector import resolve_commit


STRATEGIES = ("file", "line")


class InvalidMutation(ValueError):
    """The specified edit cannot produce a valid mutant of this revision."""


def read_mutations(config: Path) -> list[dict]:
    document = json.loads(config.read_text(encoding="utf-8"))
    mutations = document.get("mutations") if isinstance(document, dict) else None
    if not isinstance(mutations, list) or not mutations:
        raise ValueError("Expected a nonempty 'mutations' array")
    seen = set()
    for mutation in mutations:
        fields = ("id", "path", "before", "after")
        if not isinstance(mutation, dict) or not all(
            isinstance(mutation.get(field), str) for field in fields
        ):
            raise ValueError("Each mutation needs string id, path, before and after fields")
        identifier = mutation["id"]
        if not identifier.strip() or identifier in seen:
            raise ValueError(f"Empty or duplicate mutation ID: {identifier!r}")
        seen.add(identifier)
    return mutations


def apply_mutation(root: Path, mutation: dict) -> None:
    """Replace a unique snippet, preserving surrounding bytes and line endings."""
    relative = Path(mutation["path"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
        raise InvalidMutation(f"Expected a relative Python source path: {relative}")
    root = root.resolve()
    path = root / relative
    if path.resolve() != path or ".git" in relative.parts or not path.is_file():
        raise InvalidMutation(f"Expected a regular Python source file in this checkout: {relative}")
    before = mutation["before"].encode("utf-8")
    after = mutation["after"].encode("utf-8")
    if not before or before == after:
        raise InvalidMutation("The original snippet must be nonempty and change")
    original = path.read_bytes()
    first = original.find(before)
    if first < 0 or first != original.rfind(before):
        raise InvalidMutation(f"Original snippet must occur exactly once in {relative}")
    changed = original[:first] + after + original[first + len(before):]
    try:
        compile(changed, str(relative), "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as error:
        raise InvalidMutation(f"Invalid Python in {relative}: {error}") from error
    path.write_bytes(changed)


def classify(full_failures: set[str], selected_failures: set[str]) -> str:
    """Confirm a kill by reproducing at least one full-suite failing node."""
    if full_failures & selected_failures:
        return "killed"
    if selected_failures:
        # An unrelated or order-dependent failure cannot establish detection.
        return "inconsistent"
    return "missed" if full_failures else "survived"


def summarize(trials: list[dict]) -> dict:
    summary = {}
    for strategy in STRATEGIES:
        counts = dict.fromkeys(
            ("killed", "missed", "survived", "inconsistent",
             "invalid_mutation", "infrastructure_error"), 0
        )
        for trial in trials:
            counts[trial["outcomes"][strategy]] += 1
        detectable = counts["killed"] + counts["missed"]
        summary[strategy] = {
            **counts,
            "evaluable_full_suite_kills": detectable,
            "fault_detection_pct": 100 * counts["killed"] / detectable if detectable else None,
            "missed_fault_pct": 100 * counts["missed"] / detectable if detectable else None,
        }
    return summary


def run_campaign(repo: Path, base: str, db: Path, config: Path) -> dict:
    started = perf_counter()
    mutations = read_mutations(config)
    repo = repo.resolve()
    db = db.resolve()
    commit = resolve_commit(repo, base)
    # Captures the complete unmutated suite and raises if it is not green.
    control = baseline(repo, commit, db)
    trials = []
    for mutation in mutations:
        trial = {"mutation": mutation}
        try:
            with checkout(repo, commit) as work:
                apply_mutation(work, mutation)
                comparison = compare(work, commit, db, STRATEGIES)
            full_failures = set(comparison["full"]["failed"])
            trial["outcomes"] = {
                strategy: classify(full_failures, set(comparison["strategies"][strategy]["failed"]))
                for strategy in STRATEGIES
            }
            trial["comparison"] = comparison
        except InvalidMutation as error:
            trial.update(outcomes=dict.fromkeys(STRATEGIES, "invalid_mutation"), error=str(error))
        except (OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
            # Includes collection failures. Only actual test failures count as kills.
            trial.update(outcomes=dict.fromkeys(STRATEGIES, "infrastructure_error"), error=str(error))
        trials.append(trial)
    return {"base_commit": commit, "control": control, "trials": trials,
            "summary": summarize(trials), "campaign_seconds": perf_counter() - started}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base", default="HEAD", help="Git revision used for all trials")
    parser.add_argument("--db", required=True, type=Path, help="SQLite coverage map rebuilt for the base")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.db.resolve() == args.output.resolve() or args.config.resolve() in (
            args.db.resolve(), args.output.resolve()
        ):
            raise ValueError("Choose distinct database, configuration, and output paths")
        report = run_campaign(args.repo, args.base, args.db, args.config)
        write_json(args.output, report)
    except (OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"Mutation campaign: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved {len(report['trials'])} trials to {args.output}")
    return int(any(
        row["invalid_mutation"] or row["infrastructure_error"] or row["inconsistent"]
        for row in report["summary"].values()
    ))


if __name__ == "__main__":
    sys.exit(main())
