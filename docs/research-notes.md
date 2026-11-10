# Pilot results

The benchmark compared two selection strategies on five specified mutations and one historical change. Each measurement is a single wall-clock run. Counts include pytest items skipped by the subject. File and line times include target collection, change detection, map loading, selection and test execution. Baseline capture is a separate setup cost.

| Subject | Change | Full tests | File tests | Line tests | Full seconds | File seconds | Line seconds | Outcome |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Colorama | ansi-wrong-style-terminator | 52 | 52 | 52 | 0.595 | 0.839 | 0.870 | killed |
| Colorama | ansi-wrong-erase-default | 52 | 30 | 1 | 0.406 | 0.882 | 0.848 | killed |
| Colorama | cursor-up-moves-down | 52 | 52 | 52 | 0.380 | 0.729 | 0.763 | survived |
| more-itertools | last-returns-first | 664 | 541 | 3 | 2.686 | 2.921 | 1.304 | killed |
| more-itertools | first-true-ignores-predicate | 664 | 211 | 4 | 3.054 | 2.026 | 1.268 | killed |
| more-itertools | Historical circular_shifts edit | 660 | 538 | 4 | 2.387 | 2.710 | 1.019 | green |

Both selectors detected four of four full-suite-detectable faults. The cursor mutation survived all three runs. Counting that trial as an RTS miss would overstate the risk of selection because the upstream suite itself supplies no failing test. The import-time ANSI style mutation triggered full selection under both strategies.

Line selection saved elapsed time on the larger historical change. On the smaller Colorama erase-default mutation it chose a single test, yet still took longer end to end. For this short suite, Python startup and collection outweighed the test execution avoided.

The sample contains five hand-selected mutations and one timing observation per case. It supports reproducing these specific outcomes. It does not estimate the broader probability of missing bugs or the average performance gain on future commits. Selected node IDs execute in sorted order, while the benchmark full suite follows ordinary pytest discovery order.

[Raw reports](../results/raw/) · [Pinned projects and reproduction commands](../datasets/README.md)
