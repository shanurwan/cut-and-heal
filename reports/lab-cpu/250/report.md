# A short shutdown with 250 millicores for all region nodes

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- CPU cap per region node: `ir` 0.083 cores, `world` 0.167 cores.
- 3 run(s): `lab-cpu-250-seed1` (seed 1), `lab-cpu-250-seed2` (seed 2), `lab-cpu-250-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `lab-cpu-250-seed1` | `lab-cpu-250-seed2` | `lab-cpu-250-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | **FAIL** | **FAIL** | **FAIL** |
| V2 Every pod applied every phase, on schedule | **FAIL** | **FAIL** | **FAIL** |
| V3 The network was healthy before anything was cut (>= 0.99) | **FAIL** | **FAIL** | **FAIL** |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | **FAIL** | **FAIL** | **FAIL** |
| V6 The host had CPU headroom throughout | **FAIL** | **FAIL** | **FAIL** |
| V7 The evidence is complete and two records of it agree | **FAIL** | **FAIL** | **FAIL** |

Run `lab-cpu-250-seed1` is withdrawn and contributes no numbers. V1: status=failed TimeoutError('147/150 node pods running after 900s'); 150/150 pods at end, 41 restarted, 3 not running; V2: no phase acknowledgements; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples; V7: 0 publishes reconciled against 0 node send lines; 19 log collection errors

Run `lab-cpu-250-seed2` is withdrawn and contributes no numbers. V1: status=failed TimeoutError("33 pods never acknowledged setup: ['ir-20', 'ir-21', 'ir-27', 'ir-28', 'ir-32']"); 150/150 pods at end, 70 restarted, 2 not running; V2: no phase acknowledgements; 32 pods without a clean shaper setup; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples; V7: 0 publishes reconciled against 0 node send lines; 10 logs missing; 10 node logs truncated (no start line); 18 log collection errors

Run `lab-cpu-250-seed3` is withdrawn and contributes no numbers. V1: status=failed TimeoutError('144/150 node pods running after 900s'); 150/150 pods at end, 94 restarted, 6 not running; V2: no phase acknowledgements; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples; V7: 0 publishes reconciled against 0 node send lines; 2 log collection errors


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| lab-cpu-250-seed1 | cah-ir | 1012 | 0.088 | 99.9% | 3761.2 |
| lab-cpu-250-seed1 | cah-world | 1012 | 0.167 | 99.9% | 3783.1 |
| lab-cpu-250-seed2 | cah-ir | 1840 | 0.087 | 100.0% | 6840.4 |
| lab-cpu-250-seed2 | cah-world | 1840 | 0.167 | 100.0% | 6870.9 |
| lab-cpu-250-seed3 | cah-ir | 992 | 0.088 | 99.9% | 3662.4 |
| lab-cpu-250-seed3 | cah-world | 992 | 0.168 | 100.0% | 3693.0 |
No run passed every validity rule, so this report has no results.
