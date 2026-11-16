# A short shutdown with 1500 millicores for all region nodes

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- CPU cap per region node: `ir` 0.5 cores, `world` 1 cores.
- 3 run(s): `lab-cpu-1500-seed1` (seed 1), `lab-cpu-1500-seed2` (seed 2), `lab-cpu-1500-seed3` (seed 3).
- Runner of `lab-cpu-1500-seed1`: 4 CPUs, Intel(R) Xeon(R) 6975P-C , kernel 7.0.0-1014-aws.
- Runner of `lab-cpu-1500-seed2`: 4 CPUs, Intel(R) Xeon(R) 6975P-C , kernel 7.0.0-1014-aws.
- Runner of `lab-cpu-1500-seed3`: 4 CPUs, AMD EPYC 9V74 80-Core Processor , kernel 7.0.0-1017-azure.
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `lab-cpu-1500-seed1` | `lab-cpu-1500-seed2` | `lab-cpu-1500-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | **FAIL** | **FAIL** | **FAIL** |
| V2 Every pod applied every phase, on schedule | **FAIL** | **FAIL** | **FAIL** |
| V3 The network was healthy before anything was cut (>= 0.99) | **FAIL** | **FAIL** | **FAIL** |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | **FAIL** | **FAIL** | **FAIL** |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | pass | pass | pass |
| V7 The evidence is complete and two records of it agree | **FAIL** | **FAIL** | **FAIL** |

Run `lab-cpu-1500-seed1` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 9 restarted, 0 not running; V2: lateness p50 105 ms, p99 1106 ms, max 1209 ms over 450 applications; shaper off schedule (limit 500 ms); V3: lowest baseline delivery 0.8980; V5: 840 publishes, send lateness p99 4 ms, 9 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V7: 831 publishes reconciled against 784 node send lines; 9043 receive lines for messages nobody logged sending; 9 pods where the controller and the node disagree on messages sent

Run `lab-cpu-1500-seed2` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 11 restarted, 0 not running; V2: lateness p50 104 ms, p99 975 ms, max 1894 ms over 450 applications; shaper off schedule (limit 500 ms); V3: lowest baseline delivery 0.8776; V5: 840 publishes, send lateness p99 4 ms, 11 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V7: 829 publishes reconciled against 772 node send lines; 11025 receive lines for messages nobody logged sending; 11 pods where the controller and the node disagree on messages sent

Run `lab-cpu-1500-seed3` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 15 restarted, 0 not running; V2: lateness p50 146 ms, p99 792 ms, max 2960 ms over 450 applications; shaper off schedule (limit 500 ms); V3: lowest baseline delivery 0.8571; V5: 840 publishes, send lateness p99 3 ms, 15 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V7: 825 publishes reconciled against 752 node send lines; 13871 receive lines for messages nobody logged sending; 15 pods where the controller and the node disagree on messages sent


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| lab-cpu-1500-seed1 | cah-ir | 1216 | 0.397 | 61.2% | 2197.8 |
| lab-cpu-1500-seed1 | cah-world | 1216 | 0.848 | 63.9% | 1749.2 |
| lab-cpu-1500-seed2 | cah-ir | 1184 | 0.394 | 61.8% | 1800.3 |
| lab-cpu-1500-seed2 | cah-world | 1184 | 0.822 | 63.0% | 1713.6 |
| lab-cpu-1500-seed3 | cah-ir | 1514 | 0.432 | 73.4% | 3314.7 |
| lab-cpu-1500-seed3 | cah-world | 1514 | 0.898 | 75.9% | 2916.9 |
No run passed every validity rule, so this report has no results.
