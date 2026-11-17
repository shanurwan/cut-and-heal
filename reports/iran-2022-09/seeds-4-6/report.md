# Iran, September 2022 - a nightly partial shutdown, repeated

**Event.** Nightly mobile internet curfew during the protests, Iran, 21 September to 3 October 2022

**Signal.** IODA gtr-norm (traffic to Google services, normalised), country IR ([view](https://ioda.live/country/IR?from=1662940800&until=1665187200)), window 2022-09-12 to 2022-10-08 UTC, retrieved 2026-11-16.

**Derivation.** fetch_ioda("IR", "2022-09-12", "2022-10-08", baseline_days=3): each half-hour sample divided by the median of the same slot over 12-14 September. From 22 September to 5 October the signal repeats daily. Medians of the samples in three daily windows: 13:30-20:30 UTC 0.32 (quartiles 0.29, 0.39); 01:00-12:30 UTC 0.72 (0.66, 0.79); 21:00-24:00 UTC 1.00. The 15:00-19:00 UTC mean is below 0.5 on every evening from 22 September to 3 October except 29 September (0.49). Two of those days are replayed.

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- 3 run(s): `iran-2022-09-seed4` (seed 4), `iran-2022-09-seed5` (seed 5), `iran-2022-09-seed6` (seed 6).
- Runner of `iran-2022-09-seed4`: 4 CPUs, AMD EPYC 9V74 80-Core Processor , kernel 7.0.0-1017-azure.
- Runner of `iran-2022-09-seed5`: 4 CPUs, AMD EPYC 9V45 96-Core Processor , kernel 7.0.0-1017-azure.
- Runner of `iran-2022-09-seed6`: 4 CPUs, AMD EPYC 7763 64-Core Processor , kernel 7.0.0-1017-azure.
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `iran-2022-09-seed4` | `iran-2022-09-seed5` | `iran-2022-09-seed6` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | pass | pass | pass |
| V2 Every pod applied every phase, on schedule | **FAIL** | pass | **FAIL** |
| V3 The network was healthy before anything was cut (>= 0.99) | pass | **FAIL** | **FAIL** |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | **FAIL** | **FAIL** | **FAIL** |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | **FAIL** | **FAIL** | **FAIL** |
| V7 The evidence is complete and two records of it agree | pass | **FAIL** | **FAIL** |

Run `iran-2022-09-seed4` is withdrawn and contributes no numbers. V2: lateness p50 109 ms, p99 181 ms, max 519 ms over 1050 applications; shaper off schedule (limit 500 ms); V5: 4200 publishes, send lateness p99 14 ms, 44 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 47%, p95 100%, max 100% over 852 samples

Run `iran-2022-09-seed5` is withdrawn and contributes no numbers. V3: lowest baseline delivery 0.9192; V5: 4200 publishes, send lateness p99 22 ms, 53 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 44%, p95 100%, max 100% over 851 samples; V7: 4147 publishes reconciled against 3979 node send lines; 10 logs missing; 17 log collection errors; 23596 receive lines for messages nobody logged sending; 8 pods where the controller and the node disagree on messages sent

Run `iran-2022-09-seed6` is withdrawn and contributes no numbers. V2: lateness p50 108 ms, p99 375 ms, max 560 ms over 1050 applications; shaper off schedule (limit 500 ms); V3: lowest baseline delivery 0.9192; V5: 4200 publishes, send lateness p99 30 ms, 38 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 56%, p95 100%, max 100% over 850 samples; V7: 4162 publishes reconciled against 3994 node send lines; 9 logs missing; 16 log collection errors; 23644 receive lines for messages nobody logged sending; 8 pods where the controller and the node disagree on messages sent


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| iran-2022-09-seed4 | cah-ir | 4420 | 0.742 | n/a | 0.0 |
| iran-2022-09-seed4 | cah-world | 4420 | 1.25 | n/a | 0.0 |
| iran-2022-09-seed5 | cah-ir | 4425 | 0.712 | n/a | 0.0 |
| iran-2022-09-seed5 | cah-world | 4425 | 1.224 | n/a | 0.0 |
| iran-2022-09-seed6 | cah-ir | 4503 | 0.865 | n/a | 0.0 |
| iran-2022-09-seed6 | cah-world | 4503 | 1.416 | n/a | 0.0 |
No run passed every validity rule, so this report has no results.
