# Iran, September 2022: no valid run

From 21 September 2022 mobile internet in Iran was cut every evening while fixed lines stayed
up, and traffic came back each night. `iran-2022-09` replays two days of that cycle against
the network of `iran-2019-11`: 36 of 50 inside nodes open in the day, 16 in the curfew, all
50 at night, each phase 660 s. The design and predictions are in
[METHOD.md section 15](../../docs/METHOD.md#15-a-second-outage-iran-september-2022).

**All six runs were withdrawn, so P25 and P26 are not judged and this report has no
results.**

## Why the runs were withdrawn

Every run failed V6: the 4-CPU host was 100% busy at the 95th percentile. The saturation came
at the same point in every run, in the last phase:

| Run | Host busy, median per phase: baseline, day-1, curfew-1, night-1, day-2, curfew-2, night-2 |
|---|---|
| seed 1 | 62, 55, 45, 51, 63, 59, **100%** |
| seed 2 | 45, 42, 35, 38, 44, 42, **100%** |
| seed 3 | 48, 42, 35, 38, 43, 41, **100%** |
| seed 4 | 52, 47, 39, 43, 49, 45, **100%** |
| seed 5 | 49, 44, 38, 42, 47, 44, **100%** |
| seed 6 | 60, 55, 46, 50, 61, 56, **100%** |

`night-2` is the same phase as `night-1`, which the host ran at a median of 51% or less. What
differs is that it starts about an hour into the run, later than in any other scenario here. Whatever
loads the host then is not identified: the nodes, the metrics store and log collection are
candidates. V2, V5 and V7 failed with the overload; four runs also had a baseline below 99%,
which is a separate failure, an hour earlier.

## What this does not establish

Anything about the 2022 outage. The data from the first six phases is not used, because
runs that fail a rule contribute no numbers. Every other scenario here runs for about half
an hour, and none has met this.

## Provenance

| Seeds | Report | Evidence | Valid runs |
|---|---|---|---|
| 1 to 3 | [seeds-1-3](seeds-1-3/report.md) | [replay run 43885890417](https://github.com/shanurwan/cut-and-heal/actions/runs/43885890417) | 0 of 3 |
| 4 to 6 | [seeds-4-6](seeds-4-6/report.md) | [43906920379](https://github.com/shanurwan/cut-and-heal/actions/runs/43906920379) | 0 of 3 |

Host load per phase is computed from each run's `load.csv` against the phase times in
`analysis/summary.json`.
