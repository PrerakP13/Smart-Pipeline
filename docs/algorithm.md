# How TestMind selects tests

A baseline is a specific Git commit with a passing pytest suite. TestMind runs that suite once under coverage.py and stores each test's pytest node ID, repository-relative Python paths and executed line numbers in SQLite. Each commit has its own snapshot. Capturing the same commit again replaces its snapshot in one transaction.

For a target, TestMind collects its test IDs, reads the baseline map and obtains a zero-context Git diff. For a working tree the diff includes the final staged and unstaged contents and nonignored untracked files. For a commit target the command uses a disposable checkout. Line numbers always refer to the **old side** of the diff, where coverage was measured.

| Change | Selection rule |
| --- | --- |
| Existing Python file with a changed function body | File mode selects every current test observed in that file. Line mode selects tests that executed any changed baseline line. |
| New pytest item or parameter | Both modes include its new node ID. |
| Modified test module | Both modes include the tests currently collected from the module, plus any other affected tests. |
| Edit overlaps a shared line | Run the full current suite. Shared lines include imports during collection, broader-scope fixture setup, and teardown. |
| Pure insertion, or no comparable baseline line | Use file coverage. For a file with shared lines, run the full suite. |
| Unknown production file, deletion, rename, file type change, conftest.py or changed configuration/data | Run the full suite. A newly added test module can select just its new items. |
| Uncollected documentation under docs/ or top-level README, CHANGELOG or LICENSE with a supported text extension | Ignore the document when selecting. A project that reads its documentation as runtime data needs a different policy. |

For example, if two tests both call functions in the same module, file selection can choose both. If only one executed the old line edited inside a function, line selection can choose just that test. A line that received no test coverage can yield an empty selection. A completed full run on the target provides the comparison for those decisions.

## Relation to the paper

Kauhanen and colleagues describe Git differencing, per-test dynamic coverage, SQLite and file/line selection. TestMind implements those ideas with its own selector. The paper also describes shifting stored line numbers and updating a map after committed changes. TestMind uses explicit, immutable-revision snapshots and a fresh baseline command when the reference changes. The coursework experiments use named source edits and two pinned subjects. They are independent measurements.

[Original paper, DOI 10.1109/SANER50967.2021.00077](https://doi.org/10.1109/SANER50967.2021.00077)

## Limits

Coverage observes the main pytest process. Code executed only in child processes, external services, native extensions or dynamically read files can affect tests without appearing in the Python map. The prototype supports single-process pytest and expects stable node IDs. Keep the subject's Python version, dependencies and environment consistent between capture and selection. Regenerate a baseline after an environment change.
