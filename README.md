# TestMind

TestMind uses historical Python coverage to select pytest tests after a Git change. It measures a research question: how much testing time can file-level or line-level selection save, and which detectable regressions can selection miss?

## Try the verified example

From this directory, set up a Python 3.12 environment with Git available. These commands work in a macOS or Linux shell.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q

subject=$(mktemp -d)
git clone --quiet https://github.com/more-itertools/more-itertools.git "$subject"
base=8927b5ccc52a16dfaca74af899acad43fd1679de
target=612a009deeaebb36e34cfe5ace1b7f67c4f3af41
python -m experiments.run_experiment baseline --repo "$subject" --base "$base" --db .testmind/map.sqlite
python -m experiments.run_experiment compare --repo "$subject" --base "$base" --target "$target" \
  --db .testmind/map.sqlite --output .testmind/comparison.json
```

Open `.testmind/comparison.json`. Under `strategies.line`, `selected` lists the four tests selected for the change to `circular_shifts`. The adjacent `metrics` record the number skipped by selection, expressed as a percentage, and elapsed time including selection overhead. Individual pytest skips are recorded under `outcomes`.

| Command | What it does |
| --- | --- |
| `python -m experiments.run_experiment baseline` | Run the full baseline under coverage in an isolated checkout and save a revision-specific SQLite snapshot. |
| `python -m experiments.run_experiment run` | Use an existing snapshot and execute only the selected tests. Choose `--strategy file` or `--strategy line`. A test failure returns exit code 1. |
| `python -m experiments.run_experiment compare` | Run the full suite and chosen strategies on the same target. A completed comparison writes results even if a test failed. |
| `python -m experiments.run_mutations` | Run controlled one-at-a-time source edits in disposable checkouts and compare fault detection. |

Omit `--target` on `run` or `compare` to inspect the subject's current working tree. Include the subject's test dependencies in the active environment. Keep generated maps and reports outside the subject or in an ignored directory. The selector reads Git changes across all nonignored paths.

Each selected run discovers the target's current tests, selects items and executes them in one fresh pytest process. This removes the separate collect-only process while preserving new-test discovery and the existing selection rules. Startup and collection are charged once, including when selection is empty. Fewer selected tests can still take longer than the full suite.

Python subprocesses contribute coverage to the test that launched them. **Rebuild baselines captured before subprocess support:** those snapshots omit these dependencies and are rejected rather than silently reused. The efficient runner continues to use collector version 2, so existing version-2 snapshots remain compatible. Supported children must use the same Python environment, inherit coverage variables, and finish normally. The collector temporarily installs coverage.py's startup hook in the active virtual environment; its coverage configuration and data files live outside the subject. See the [coverage limits](docs/algorithm.md#limits).

## ETL Customer regression checks

The [ETL mutation configuration](experiments/configurations/etl_customer_mutations.json) covers boolean IDs, email case, phone normalization, email validation and transaction persistence in `PrerakP13/ETL_Customer` at commit `8c8ff5414f808642394566a96f4e8a877313663a`. From this repository, after installing both projects' requirements into the same Python 3.12 environment:

```sh
etl_results=$(mktemp -d)
.venv/bin/python -m experiments.run_mutations \
  --repo "$HOME/ETL_Customer" \
  --base 8c8ff5414f808642394566a96f4e8a877313663a \
  --db "$etl_results/coverage.sqlite" \
  --config experiments/configurations/etl_customer_mutations.json \
  --output "$etl_results/mutations.json"
```

This captures the full passing control and applies each intentional fault in a separate temporary checkout. The original ETL files are preserved. `summary` reports whether each strategy detects each fault; individual `trials[].comparison.strategies` also report missed failing tests and total selective time. Intentional test failures are expected. An experiment can detect a fault while still missing another failing test, and it can reduce test counts without saving time.

For one strategy, use `metrics.selected_total_seconds` in a comparison or `total_seconds` in a `run` report. These include Git and map preparation, selection, pytest startup, collection and execution. `comparison_seconds` measures preparation plus the full run and every requested strategy; it excludes baseline capture and creation of an outer target checkout. `campaign_seconds` includes the baseline, temporary checkouts and all mutation trials. These measurements end before the final JSON report is written. See the [timing definitions](docs/experiment-plan.md) before comparing strategy costs with an entire experiment's duration.

## Reference results

The [ETL efficiency verification](docs/etl-efficiency.md) records the current runner's 61 passing self-tests, five mutation checks and repeated comparisons against the previous runner. It includes full timing boundaries and cases where file selection remained slower.

For the historical more-itertools change, line selection ran 4 of 660 pytest items. File selection ran 538. In the separate mutation experiments, both strategies detected all four faults that the full suites detected. One Colorama mutation survived the full suite. Those historical timings describe the runner used for the pilot; rerun the experiments to measure the current runner. Timings and applicability are discussed in the [pilot results](docs/research-notes.md).

- [Reproduce the two experiments and the historical comparison](datasets/README.md)
- [Understand the selection algorithm and its fallbacks](docs/algorithm.md)
- [Read the evaluation method and metric definitions](docs/experiment-plan.md)
- [Inspect individual outcomes and hardware-dependent timings](results/raw/)
- [Read the original course project plan](docs/original-proposal.md)
