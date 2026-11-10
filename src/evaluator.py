"""Compare matched full and selected runs of one target revision."""

from .test_runner import RunResult


def _reduction_pct(original: float, reduced: float) -> float | None:
    return 100 * (original - reduced) / original if original else None


def evaluate(full: RunResult, selected: RunResult, selection_seconds: float) -> dict:
    """Charge the selected run for computing the selection as well as running it."""
    if selection_seconds < 0:
        raise ValueError("selection_seconds must be nonnegative")
    if not selected.executed <= full.executed:
        raise ValueError("selected tests must belong to the full suite")
    full_count = len(full.executed)
    selected_count = len(selected.executed)
    total_time = selected.duration + selection_seconds
    missed = full.failed - selected.failed
    retained = full.failed & selected.failed
    return {
        "full_tests": full_count,
        "selected_tests": selected_count,
        "test_reduction_pct": _reduction_pct(full_count, selected_count),
        "full_seconds": full.duration,
        "selected_run_seconds": selected.duration,
        "selection_seconds": selection_seconds,
        "selected_total_seconds": total_time,
        "time_reduction_pct": _reduction_pct(full.duration, total_time),
        "full_failures": sorted(full.failed),
        "selected_failures": sorted(selected.failed),
        "missed_failures": sorted(missed),
        "extra_failures": sorted(selected.failed - full.failed),
        "failure_retention_pct": 100 * len(retained) / len(full.failed) if full.failed else None,
    }
