# Iran, September 2022 - a nightly partial shutdown, repeated

**Event.** Nightly mobile internet curfew during the protests, Iran, 21 September to 3 October 2022

**Signal.** IODA gtr-norm (traffic to Google services, normalised), country IR ([view](https://ioda.live/country/IR?from=1662940800&until=1665187200)), window 2022-09-12 to 2022-10-08 UTC, retrieved 2026-11-16.

**Derivation.** fetch_ioda("IR", "2022-09-12", "2022-10-08", baseline_days=3): each half-hour sample divided by the median of the same slot over 12-14 September. From 22 September to 5 October the signal repeats daily. Medians of the samples in three daily windows: 13:30-20:30 UTC 0.32 (quartiles 0.29, 0.39); 01:00-12:30 UTC 0.72 (0.66, 0.79); 21:00-24:00 UTC 1.00. The 15:00-19:00 UTC mean is below 0.5 on every evening from 22 September to 3 October except 29 September (0.49). Two of those days are replayed.

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- 3 run(s): `iran-2022-09-seed1` (seed 1), `iran-2022-09-seed2` (seed 2), `iran-2022-09-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `iran-2022-09-seed1` | `iran-2022-09-seed2` | `iran-2022-09-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | pass | pass | pass |
| V2 Every pod applied every phase, on schedule | **FAIL** | pass | pass |
| V3 The network was healthy before anything was cut (>= 0.99) | pass | **FAIL** | **FAIL** |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | **FAIL** | **FAIL** | **FAIL** |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | **FAIL** | **FAIL** | **FAIL** |
| V7 The evidence is complete and two records of it agree | pass | **FAIL** | **FAIL** |

Run `iran-2022-09-seed1` is withdrawn and contributes no numbers. V2: lateness p50 110 ms, p99 358 ms, max 530 ms over 1050 applications; shaper off schedule (limit 500 ms); V5: 4200 publishes, send lateness p99 31 ms, 42 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 58%, p95 100%, max 100% over 850 samples

Run `iran-2022-09-seed2` is withdrawn and contributes no numbers. V3: lowest baseline delivery 0.6531; V5: 4200 publishes, send lateness p99 28 ms, 67 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 42%, p95 100%, max 100% over 851 samples; V7: 4133 publishes reconciled against 3432 node send lines; 18 logs missing; 32 log collection errors; 95362 receive lines for messages nobody logged sending; 17 pods where the controller and the node disagree on messages sent

Run `iran-2022-09-seed3` is withdrawn and contributes no numbers. V3: lowest baseline delivery 0.9192; V5: 4200 publishes, send lateness p99 12 ms, 38 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 42%, p95 100%, max 100% over 850 samples; V7: 4162 publishes reconciled against 3994 node send lines; 8 logs missing; 16 log collection errors; 23678 receive lines for messages nobody logged sending; 8 pods where the controller and the node disagree on messages sent

No run passed every validity rule, so this report has no results.
