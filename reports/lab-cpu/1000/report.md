# A short shutdown with 1000 millicores for all region nodes

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- CPU cap per region node: `ir` 0.333 cores, `world` 0.667 cores.
- 3 run(s): `lab-cpu-1000-seed1` (seed 1), `lab-cpu-1000-seed2` (seed 2), `lab-cpu-1000-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `lab-cpu-1000-seed1` | `lab-cpu-1000-seed2` | `lab-cpu-1000-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | **FAIL** | **FAIL** | **FAIL** |
| V2 Every pod applied every phase, on schedule | **FAIL** | **FAIL** | **FAIL** |
| V3 The network was healthy before anything was cut (>= 0.99) | **FAIL** | **FAIL** | **FAIL** |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | **FAIL** | **FAIL** | **FAIL** |
| V6 The host had CPU headroom throughout | **FAIL** | **FAIL** | **FAIL** |
| V7 The evidence is complete and two records of it agree | pass | pass | pass |

Run `lab-cpu-1000-seed1` is withdrawn and contributes no numbers. V1: status=failed TimeoutError("8 nodes below mesh size 4: {'ir-39': None, 'world-79': None, 'world-86': None, 'world-87': None, 'world-89': None}"); 150/150 pods at end, 0 restarted, 0 not running; V2: no phase acknowledgements; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples

Run `lab-cpu-1000-seed2` is withdrawn and contributes no numbers. V1: status=failed TimeoutError("20 nodes below mesh size 4: {'ir-31': None, 'ir-32': None, 'ir-33': None, 'ir-36': None, 'ir-41': None}"); 150/150 pods at end, 47 restarted, 0 not running; V2: no phase acknowledgements; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples

Run `lab-cpu-1000-seed3` is withdrawn and contributes no numbers. V1: status=failed TimeoutError("1 nodes below mesh size 4: {'world-80': None}"); 150/150 pods at end, 2 restarted, 0 not running; V2: no phase acknowledgements; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| lab-cpu-1000-seed1 | cah-ir | 1366 | 0.339 | 99.9% | 4920.3 |
| lab-cpu-1000-seed1 | cah-world | 1366 | 0.668 | 99.9% | 4436.3 |
| lab-cpu-1000-seed2 | cah-ir | 1078 | 0.338 | 100.0% | 3555.5 |
| lab-cpu-1000-seed2 | cah-world | 1078 | 0.667 | 99.9% | 3161.8 |
| lab-cpu-1000-seed3 | cah-ir | 1110 | 0.339 | 99.9% | 3990.4 |
| lab-cpu-1000-seed3 | cah-world | 1110 | 0.667 | 99.9% | 3606.3 |
No run passed every validity rule, so this report has no results.
