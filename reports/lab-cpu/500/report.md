# A short shutdown with 500 millicores for all region nodes

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- CPU cap per region node: `ir` 0.167 cores, `world` 0.333 cores.
- 3 run(s): `lab-cpu-500-seed1` (seed 1), `lab-cpu-500-seed2` (seed 2), `lab-cpu-500-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `lab-cpu-500-seed1` | `lab-cpu-500-seed2` | `lab-cpu-500-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | **FAIL** | **FAIL** | **FAIL** |
| V2 Every pod applied every phase, on schedule | **FAIL** | **FAIL** | **FAIL** |
| V3 The network was healthy before anything was cut (>= 0.99) | **FAIL** | **FAIL** | **FAIL** |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | **FAIL** | **FAIL** | **FAIL** |
| V6 The host had CPU headroom throughout | **FAIL** | **FAIL** | **FAIL** |
| V7 The evidence is complete and two records of it agree | **FAIL** | **FAIL** | **FAIL** |

Run `lab-cpu-500-seed1` is withdrawn and contributes no numbers. V1: status=failed TimeoutError("55 pods never acknowledged setup: ['ir-1', 'ir-12', 'ir-13', 'ir-14', 'ir-17']"); 150/150 pods at end, 36 restarted, 8 not running; V2: no phase acknowledgements; 49 pods without a clean shaper setup; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples; V7: 0 publishes reconciled against 0 node send lines; 46 logs missing; 22 node logs truncated (no start line); 88 log collection errors

Run `lab-cpu-500-seed2` is withdrawn and contributes no numbers. V1: status=failed TimeoutError("18 pods never acknowledged setup: ['world-63', 'world-64', 'world-66', 'world-69', 'world-70']"); 150/150 pods at end, 18 restarted, 0 not running; V2: no phase acknowledgements; 14 pods without a clean shaper setup; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples; V7: 0 publishes reconciled against 0 node send lines; 2 node logs truncated (no start line)

Run `lab-cpu-500-seed3` is withdrawn and contributes no numbers. V1: status=failed TimeoutError("15 pods never acknowledged setup: ['ir-38', 'ir-47', 'world-75', 'world-81', 'world-82']"); 150/150 pods at end, 24 restarted, 0 not running; V2: no phase acknowledgements; 15 pods without a clean shaper setup; no phase acknowledgements; V3: no baseline messages; V5: no publishes recorded; V6: no load samples; V7: 0 publishes reconciled against 0 node send lines; 1 node logs truncated (no start line)


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| lab-cpu-500-seed1 | cah-ir | 1714 | 0.166 | 100.0% | 6461.4 |
| lab-cpu-500-seed1 | cah-world | 1714 | 0.335 | 99.9% | 6187.5 |
| lab-cpu-500-seed2 | cah-ir | 1310 | 0.169 | 99.9% | 4946.8 |
| lab-cpu-500-seed2 | cah-world | 1310 | 0.337 | 99.9% | 4733.1 |
| lab-cpu-500-seed3 | cah-ir | 1280 | 0.168 | 100.0% | 4836.4 |
| lab-cpu-500-seed3 | cah-world | 1280 | 0.336 | 100.0% | 4618.2 |
No run passed every validity rule, so this report has no results.
