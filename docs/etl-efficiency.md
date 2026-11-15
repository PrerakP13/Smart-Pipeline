# ETL efficiency verification

Measured on 2026-11-15 using Python 3.12.14, pytest 8.4.2 and coverage 7.10.7 on `Linux-6.18.57-x86_64-with-glibc2.41`. These are Linux measurements; rerun on the Mac before comparing absolute durations with earlier Mac results.

Source implementation: `483e20165a11098ec9e438eff843a77e4b6a11dc`. Previous implementation: `bccad9a0e5f7a2a9d138067ec2b2c082e1f83c1a`. ETL subject: `8c8ff5414f808642394566a96f4e8a877313663a`. Complete outcomes and timings are in [the raw report](../results/raw/etl-v3-efficiency.json).

## Change and checks

The previous path launched pytest to discover current tests, then launched pytest again to run selected IDs. The efficient path performs discovery, selection and execution in one fresh process. It retains current-test discovery, subprocess coverage, conservative fallbacks and exact node IDs. Each strategy still performs its own collection; it does not borrow discovery from the full benchmark run. Only changed-file coverage plus all baseline IDs is transferred to the worker.

- Smart-Pipeline: 61 tests passed, including dynamic/new/removed IDs, collection wrappers, empty selections, collection failures, subject `src` namespace isolation, unstable inventory detection and timing accounting.
- Ruff checks passed for changed Python files; Git whitespace checks passed.
- ETL baseline: 100 tests passed.
- Five mutations: both strategies detected all five and retained every full-suite failing test. No extra failures or infrastructure errors.
- All ten strategy/mutation selections and failing-test sets exactly match the preceding subprocess-fixed campaign. Test selection was not weakened to obtain faster timings.

## Five-mutation campaign

Positive time reduction means faster than the full suite. Total selective time includes preparation, startup, collection, selection and selected execution; baseline capture is excluded from this per-strategy comparison.

| Mutation | Full failures | File tests | File time reduction | Line tests | Line time reduction | Missed failures, file / line |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| boolean-id | 1 | 60 | -3.89% | 1 | 69.09% | 0 / 0 |
| email-case | 5 | 22 | 32.26% | 18 | 54.05% | 0 / 0 |
| phone-normalization | 10 | 22 | 23.06% | 18 | 43.79% | 0 / 0 |
| email-validation | 10 | 60 | 4.34% | 53 | 51.40% | 0 / 0 |
| transaction-persistence | 14 | 25 | -5.88% | 17 | 38.00% | 0 / 0 |

Summing the five independently measured full and selective paths gives:

| Path | Combined seconds | Reduction versus combined full runs |
| --- | ---: | ---: |
| Full | 52.30 | Reference |
| File | 46.82 | 10.47% |
| Line | 25.29 | 51.64% |

The complete campaign took 137.11 seconds, including a 12.70-second coverage baseline and temporary checkouts. That campaign duration is separate from the per-strategy totals above.

File mode was still slightly slower in the boolean-ID and transaction cases. It retains extra CLI/import tests that start Python subprocesses, so skipping many inexpensive tests can leave most execution cost intact. Those timing observations do not justify relabeling line selection as file selection or dropping measured dependencies. No method is guaranteed to beat the full suite for every change, especially when its fallback must run all tests.

## Repeated email-case comparison

Three comparisons per implementation, run sequentially in the same environment. Implementation order and file/line order were alternated. Each comparison ran the full suite first and used an isolated checkout. Baseline capture was excluded. There were no missed or extra failures in any run. The full suite had 100 tests and 5 failures; file selection had 22 tests and line selection had 18, each retaining all 5 failures and the CLI test.

| Efficient runner path | Median elapsed seconds | Median of per-run time reductions |
| --- | ---: | ---: |
| Full | 10.62 | Reference |
| File | 8.01 | 24.57% |
| Line | 6.34 | 40.27% |

Both efficient strategies beat the full suite in all three email-case comparisons. File reductions ranged from 20.63% to 25.66%; line reductions ranged from 32.51% to 48.99%. Median total file runtime changed from 11.15s to 8.01s, and line runtime from 8.81s to 6.34s. Host noise and cache effects remain visible; these are three-run observations, not a general performance guarantee.

The old median selection field was about 3.19s because it included a separate collection process. The new field is about 0.022s. The single remaining collection is still measured inside selected execution. The improvement is the eliminated duplicate work, not an omitted timing charge. See [timing definitions](experiment-plan.md).

## Reproduce on the Mac

From the updated project folder, create the Python 3.12 environment with the already installed uv executable:

```sh
"$HOME/ETL_Customer/.venv/bin/uv" venv --python 3.12 --seed .venv &&
.venv/bin/python -m pip install -r requirements.txt -r "$HOME/ETL_Customer/requirements-dev.txt" &&
.venv/bin/python -m pytest -q tests
```

Expect 61 passing Smart-Pipeline tests. Then use the ETL mutation command in the [README](../README.md#etl-customer-regression-checks). Its report now includes `campaign_seconds`; each comparison includes `comparison_seconds`, and each strategy retains `metrics.selected_total_seconds`. Version-2 coverage maps remain compatible. Repeat measurements with fresh result directories; preserve the same Python environment and subject commit when comparing implementations.
