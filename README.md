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

## Reference results

For the historical more-itertools change, line selection ran 4 of 660 pytest items. File selection ran 538. In the separate mutation experiments, both strategies detected all four faults that the full suites detected. One Colorama mutation survived the full suite. Timings and applicability are discussed in the [pilot results](docs/research-notes.md).

- [Reproduce the two experiments and the historical comparison](datasets/README.md)
- [Understand the selection algorithm and its fallbacks](docs/algorithm.md)
- [Read the evaluation method and metric definitions](docs/experiment-plan.md)
- [Inspect individual outcomes and hardware-dependent timings](results/raw/)
- [Read the original course project plan](docs/original-proposal.md)
