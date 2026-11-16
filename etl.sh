#!/bin/sh
# macOS/Linux launcher: bash ./etl.sh baseline; bash ./etl.sh compare
# Defaults: ~/ETL_Customer, the verified ETL commit, and .testmind beside this file.
# Override ETL_REPO, ETL_BASE, ETL_DB, ETL_REPORT, ETL_PYTHON, ETL_STRATEGY or ETL_TARGET.
# Example: ETL_REPO="$HOME/projects/ETL Customer" bash ./etl.sh baseline
# Compare inspects existing changes; it does not inject a mutation.
set -eu

if [ "$#" -gt 1 ]; then
    echo "Usage: bash ./etl.sh [baseline|compare]" >&2
    exit 2
fi
etl_action=${1:-compare}
case "$etl_action" in
    baseline|compare) ;;
    *) echo "Usage: bash ./etl.sh [baseline|compare]" >&2; exit 2 ;;
esac

etl_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
etl_repo=${ETL_REPO:-"$HOME/ETL_Customer"}
etl_base=${ETL_BASE:-8c8ff5414f808642394566a96f4e8a877313663a}
etl_db=${ETL_DB:-"$etl_dir/.testmind/etl.sqlite"}
if [ "$etl_action" = baseline ]; then
    etl_report=${ETL_REPORT:-"$etl_dir/.testmind/etl-baseline.json"}
    if [ -n "${ETL_TARGET:-}" ]; then
        echo "ETL_TARGET applies only to compare. Baseline captures ETL_BASE." >&2
        exit 2
    fi
else
    etl_report=${ETL_REPORT:-"$etl_dir/.testmind/etl-comparison.json"}
fi
if [ -n "${ETL_PYTHON:-}" ]; then
    etl_python=$ETL_PYTHON
elif [ -x "$etl_dir/.venv/bin/python" ]; then
    etl_python="$etl_dir/.venv/bin/python"
else
    etl_python=python3
fi

# Resolve relative overrides before switching to the Smart-Pipeline directory.
case "$etl_repo" in /*) ;; *) etl_repo="$PWD/$etl_repo" ;; esac
case "$etl_db" in /*) ;; *) etl_db="$PWD/$etl_db" ;; esac
case "$etl_report" in /*) ;; *) etl_report="$PWD/$etl_report" ;; esac
case "$etl_python" in /*) ;; */*) etl_python="$PWD/$etl_python" ;; esac
if ! command -v "$etl_python" >/dev/null 2>&1; then
    echo "Python not found: $etl_python. Set ETL_PYTHON to your Python 3.12 environment." >&2
    exit 1
fi

cd "$etl_dir"
set -- -m experiments.run_experiment "$etl_action" \
    --repo "$etl_repo" --base "$etl_base" --db "$etl_db" --output "$etl_report"
if [ "$etl_action" = compare ]; then
    set -- "$@" --strategy "${ETL_STRATEGY:-both}"
    if [ -n "${ETL_TARGET:-}" ]; then
        set -- "$@" --target "$ETL_TARGET"
    fi
fi

# set -e propagates a command failure and prevents reading an old report.
"$etl_python" "$@"
"$etl_python" - "$etl_report" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)
if "test_count" in report:
    print(f"Baseline captured: {report['test_count']} test items")
    print(f"Baseline time: {report['baseline_seconds']:.2f}s")
else:
    full = report["full"]
    print(f"\nFULL: {full['count']} tests, {len(full['failed'])} failures")
    print(f"Full execution: {full['duration']:.2f}s")
    for name, run in report["strategies"].items():
        metrics = run["metrics"]
        print(f"\n{name.upper()}: {run['count']} tests, {len(run['failed'])} failures")
        print(f"Selected execution: {run['duration']:.2f}s")
        print(f"Selection overhead: {metrics['selection_seconds']:.2f}s")
        print(f"Total selective time: {metrics['selected_total_seconds']:.2f}s")
        print(f"Time reduction: {metrics['time_reduction_pct']:.2f}%")
        print("Missed failing tests:", metrics["missed_failures"])
        print("Extra failing tests:", metrics["extra_failures"])
    print(f"\nEntire comparison: {report['comparison_seconds']:.2f}s")
print("Report:", sys.argv[1])
PY
