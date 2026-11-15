# Reproducing and interpreting the experiment

Use the commands and Git SHAs in [the dataset guide](../datasets/README.md). Run commands from the TestMind project root in an environment with the subject's test dependencies. Keep the SQLite map and output JSON outside the subject checkout. Untracked files inside the subject are inputs to working-tree selection.

1. Capture the unmodified commit under coverage and record the setup cost. A failing or incomplete suite cannot establish the baseline.
2. On the target, read the snapshot and inspect the diff. Run the full suite in its own fresh pytest process to obtain the comparison outcomes.
3. For each requested strategy, use another fresh pytest process to collect current items, select after ordinary collection hooks finish and execute the retained items. Each strategy pays for its own discovery; the full run's inventory is used only to check consistency. Charge interpreter startup and collection once. A skipped item counts toward suite size and its outcome remains visible. An empty selection still starts pytest and collects the target, so its elapsed run time is not zero.
4. For mutations, apply one exact replacement per disposable checkout. Compare failing test IDs across suites. A strategy detects a mutant if it reproduces at least one full-suite failure. A mutant that survives the full suite cannot establish whether RTS missed a detectable fault.

| Metric | Calculation |
| --- | --- |
| Test reduction | 100 × (full count − selected count) / full count |
| Selective time reduction | 100 × (full time − total selective time) / full time |
| Fault detection | Detected mutants / (detected + missed mutants) |
| Missed-fault rate | Missed mutants / (detected + missed mutants) |
| Failure retention | Full-suite failing node IDs also failing in the selected run / full-suite failing node IDs |

A negative time reduction means the selective path took longer. Reports use null when a denominator is zero. Invalid edits, collection errors and inconsistent failures are reported separately. Setup failures during execution of a specific pytest item have an attributable test ID and count as test failures.

## Timing boundaries

Let `P` be parent-process preparation: Git resolution, loading the snapshot and inspecting changes. Let `W` be the elapsed selective runner call, including request preparation, interpreter startup, pytest collection, selection, test execution and result handling. Let `S` be the measured work selecting and filtering the collected items inside that call.

The report assigns `P + S` to selection and `W - S` to execution. Their sum is `P + W`: all selective work is charged once. Normal pytest startup and collection remain execution costs for both full and selected runs. Each strategy is charged the common preparation cost even though a comparison computes that preparation once.

| Report field | Included work |
| --- | --- |
| `metrics.full_seconds` | The full pytest runner, including startup, collection, execution and result handling. |
| `metrics.selection_seconds` | `P + S`: parent preparation and choosing/filtering collected items. |
| `metrics.selected_run_seconds` | `W - S`: the selective runner excluding the separately charged selection calculation. |
| `metrics.selected_total_seconds` | `P + W`: one strategy's measured selective path. The standalone `run` report calls this `total_seconds`. |
| `comparison_seconds` | Actual elapsed time for comparison preparation, the full run, every requested strategy and comparison bookkeeping. With both strategies this includes three pytest runs. |
| `campaign_seconds` | Actual elapsed time for the mutation campaign, including configuration reading, baseline capture, temporary checkout creation/cleanup, mutations and all comparisons. |

Per-strategy timings and `comparison_seconds` exclude baseline capture and creation of any outer target checkout. `campaign_seconds` includes those campaign operations. All fields exclude the final JSON report write. They are measurements within the experiment functions, not the entire shell command's runtime. `comparison_seconds` is not the sum of the strategies' total times: the full run is additional work, while common preparation happens only once in the comparison.

The saved pilot timings predate this runner change. Reproduce those experiments to measure the current implementation; do not infer a new speedup from old timing fields.

The bundled runs are a pilot. Their fixed execution order, host load, filesystem caches and short runtimes affect timing. Repeat trials under comparable conditions and vary execution order before making a general performance claim. Test suites with order-sensitive tests or persistent external state can produce different outcomes in a selected run.
