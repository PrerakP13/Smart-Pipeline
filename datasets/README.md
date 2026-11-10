# Reproducing the experiments

Run the following commands from the TestMind root in a POSIX shell with Git and Python 3.12 available. These examples clone upstream subjects into a temporary directory. The suites ran on Linux using Python 3.12, pytest 8.4.2 and coverage.py 7.10.7. Some upstream tests skip based on platform or Python version.

| Subject | Revision used for mutations | Clean upstream suite on Linux |
| --- | --- | --- |
| [Colorama 0.4.6](https://github.com/tartley/colorama/tree/3de9f013df4b470069d03d250224062e8cf15c49) | `3de9f013df4b470069d03d250224062e8cf15c49` | 38 passed, 14 skipped |
| [more-itertools 10.5.0](https://github.com/more-itertools/more-itertools/tree/4998a257373f36e91edef7324572ed8df10f39d1) | `4998a257373f36e91edef7324572ed8df10f39d1` | 663 passed, 1 skipped |

## Setup

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

subjects=$(mktemp -d)
git clone --quiet https://github.com/tartley/colorama.git "$subjects/colorama"
git clone --quiet https://github.com/more-itertools/more-itertools.git "$subjects/more-itertools"

colorama_base=3de9f013df4b470069d03d250224062e8cf15c49
more_base=4998a257373f36e91edef7324572ed8df10f39d1
git -C "$subjects/colorama" checkout --quiet --detach "$colorama_base"
git -C "$subjects/more-itertools" checkout --quiet --detach "$more_base"
mkdir -p .testmind/reproduction
```

To check the unmodified suites independently, run the following commands from the same shell.

```sh
(cd "$subjects/colorama" && python -m pytest -q)
(cd "$subjects/more-itertools" && python -m pytest -q)
```

## Controlled faults

Each campaign collects coverage on the pinned clean revision and applies one mutation at a time in a disposable checkout. It runs the full suite and both selection strategies for each mutation. Output includes individual test outcomes, timing and a campaign summary.

```sh
python -m experiments.run_mutations \
  --repo "$subjects/colorama" --base "$colorama_base" \
  --db .testmind/reproduction/colorama.sqlite \
  --config experiments/configurations/experiment_config.json \
  --output .testmind/reproduction/colorama-mutations.json

python -m experiments.run_mutations \
  --repo "$subjects/more-itertools" --base "$more_base" \
  --db .testmind/reproduction/more-itertools.sqlite \
  --config experiments/configurations/more_itertools_mutations.json \
  --output .testmind/reproduction/more-itertools-mutations.json
```

| Subject | Controlled changes | What the tests can reveal |
| --- | --- | --- |
| Colorama | Change an ANSI style terminator, change the default parameter for an ANSI erase command, reverse a cursor movement. | The style strings are initialized during import. The other cases exercise runtime handling and the limits of the upstream tests. |
| more-itertools | Return the first sequence element from `last`, ignore the predicate supplied to `first_true`. | The edits affect different source files and different subsets of a larger test suite. |

## Historical code change

An upstream refactor of `circular_shifts` in more-itertools split rotation and yielding onto separate lines. Both the parent and target revisions passed 659 tests and skipped one in the Linux reference environment. This comparison measures selection on an actual commit. The mutations above measure fault detection.

```sh
natural_base=8927b5ccc52a16dfaca74af899acad43fd1679de
natural_target=612a009deeaebb36e34cfe5ace1b7f67c4f3af41
python -m experiments.run_experiment baseline \
  --repo "$subjects/more-itertools" --base "$natural_base" \
  --db .testmind/reproduction/historical.sqlite \
  --output .testmind/reproduction/historical-baseline.json

python -m experiments.run_experiment compare \
  --repo "$subjects/more-itertools" --base "$natural_base" --target "$natural_target" \
  --db .testmind/reproduction/historical.sqlite --strategy both \
  --output .testmind/reproduction/historical-comparison.json
```
