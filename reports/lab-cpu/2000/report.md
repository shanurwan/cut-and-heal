# A short shutdown with 2000 millicores for all region nodes

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- CPU cap per region node: `ir` 0.667 cores, `world` 1.333 cores.
- 3 run(s): `lab-cpu-2000-seed1` (seed 1), `lab-cpu-2000-seed2` (seed 2), `lab-cpu-2000-seed3` (seed 3).
- Runner of `lab-cpu-2000-seed1`: 4 CPUs, Intel(R) Xeon(R) 6975P-C , kernel 7.0.0-1014-aws.
- Runner of `lab-cpu-2000-seed2`: 4 CPUs, AMD EPYC 9V45 96-Core Processor , kernel 7.0.0-1017-azure.
- Runner of `lab-cpu-2000-seed3`: 4 CPUs, AMD EPYC 7763 64-Core Processor , kernel 7.0.0-1017-azure.
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `lab-cpu-2000-seed1` | `lab-cpu-2000-seed2` | `lab-cpu-2000-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | pass | **FAIL** | **FAIL** |
| V2 Every pod applied every phase, on schedule | **FAIL** | pass | **FAIL** |
| V3 The network was healthy before anything was cut (>= 0.99) | pass | **FAIL** | **FAIL** |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | pass | **FAIL** | **FAIL** |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | pass | pass | pass |
| V7 The evidence is complete and two records of it agree | pass | **FAIL** | **FAIL** |

Run `lab-cpu-2000-seed1` is withdrawn and contributes no numbers. V2: lateness p50 101 ms, p99 651 ms, max 671 ms over 450 applications; shaper off schedule (limit 500 ms)

Run `lab-cpu-2000-seed2` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 5 restarted, 0 not running; V3: lowest baseline delivery 0.9388; V5: 840 publishes, send lateness p99 5 ms, 5 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V7: 835 publishes reconciled against 808 node send lines; 5175 receive lines for messages nobody logged sending; 5 pods where the controller and the node disagree on messages sent

Run `lab-cpu-2000-seed3` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 21 restarted, 0 not running; V2: lateness p50 104 ms, p99 793 ms, max 1111 ms over 450 applications; shaper off schedule (limit 500 ms); V3: lowest baseline delivery 0.7959; V5: 840 publishes, send lateness p99 7 ms, 21 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V7: 819 publishes reconciled against 716 node send lines; 18370 receive lines for messages nobody logged sending; 21 pods where the controller and the node disagree on messages sent


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| lab-cpu-2000-seed1 | cah-ir | 1073 | 0.477 | 39.0% | 1039.1 |
| lab-cpu-2000-seed1 | cah-world | 1073 | 0.955 | 37.1% | 735.3 |
| lab-cpu-2000-seed2 | cah-ir | 1146 | 0.437 | 42.0% | 1142.8 |
| lab-cpu-2000-seed2 | cah-world | 1146 | 0.909 | 41.8% | 749.7 |
| lab-cpu-2000-seed3 | cah-ir | 1251 | 0.521 | 60.6% | 1740.6 |
| lab-cpu-2000-seed3 | cah-world | 1251 | 1.068 | 61.3% | 1302.2 |
No run passed every validity rule, so this report has no results.
