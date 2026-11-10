import pytest

from src.evaluator import evaluate
from src.test_runner import RunResult


def test_metrics_include_analysis_time_and_identify_each_failure():
    full = RunResult(10, {"a": "passed", "b": "failed", "c": "error", "d": "skipped"})
    selected = RunResult(6, {"a": "failed", "b": "failed"})
    metrics = evaluate(full, selected, 2)
    assert metrics["full_tests"] == 4
    assert metrics["selected_tests"] == 2
    assert metrics["test_reduction_pct"] == 50
    assert metrics["time_reduction_pct"] == 20
    assert metrics["selected_total_seconds"] == 8
    assert metrics["missed_failures"] == ["c"]
    assert metrics["extra_failures"] == ["a"]
    assert metrics["failure_retention_pct"] == 50


def test_undefined_metrics_and_net_slowdown():
    empty = RunResult(0, {})
    result = evaluate(empty, empty, 0)
    assert result["test_reduction_pct"] is None
    assert result["time_reduction_pct"] is None
    assert result["failure_retention_pct"] is None
    full = RunResult(2, {"a": "passed"})
    assert evaluate(full, full, 1)["time_reduction_pct"] == -50


def test_incomparable_suites_rejected():
    with pytest.raises(ValueError, match="full suite"):
        evaluate(RunResult(2, {"a": "failed"}), RunResult(1, {"b": "passed"}), 0)
