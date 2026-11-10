# Reproducing and interpreting the experiment

Use the commands and Git SHAs in [the dataset guide](../datasets/README.md). Run commands from the TestMind project root in an environment with the subject's test dependencies. Keep the SQLite map and output JSON outside the subject checkout. Untracked files inside the subject are inputs to working-tree selection.

1. Capture the unmodified commit under coverage and record the setup cost. A failing or incomplete suite cannot establish the baseline.
2. On the target, compute both selections before executing the full test suite. Each strategy pays for reading the snapshot, inspecting the diff, collecting the target test IDs and choosing its tests.
3. Run the full suite, file selection and line selection in fresh pytest processes. Report elapsed wall-clock seconds including interpreter startup. A skipped item counts toward suite size and its outcome remains visible. An empty selection takes zero pytest execution time and still pays its selection cost.
4. For mutations, apply one exact replacement per disposable checkout. Compare failing test IDs across suites. A strategy detects a mutant if it reproduces at least one full-suite failure. A mutant that survives the full suite cannot establish whether RTS missed a detectable fault.

| Metric | Calculation |
| --- | --- |
| Test reduction | 100 × (full count − selected count) / full count |
| End-to-end time reduction | 100 × (full time − selection time − selected run time) / full time |
| Fault detection | Detected mutants / (detected + missed mutants) |
| Missed-fault rate | Missed mutants / (detected + missed mutants) |

A negative time reduction means the selective path took longer. Reports use null when a denominator is zero. Invalid edits, collection errors and inconsistent failures are reported separately. Setup failures during execution of a specific pytest item have an attributable test ID and count as test failures.

The bundled runs are a pilot. Their fixed execution order, host load, filesystem caches and short runtimes affect timing. Repeat trials under comparable conditions and vary execution order before making a general performance claim. Test suites with order-sensitive tests or persistent external state can produce different outcomes in a selected run.
