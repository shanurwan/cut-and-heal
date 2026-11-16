# A short shutdown with uncapped region nodes

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- 6 run(s): `lab-cpu-uncapped-seed1` (seed 1), `lab-cpu-uncapped-seed2` (seed 2), `lab-cpu-uncapped-seed3` (seed 3), `lab-cpu-uncapped-seed4` (seed 4), `lab-cpu-uncapped-seed5` (seed 5), `lab-cpu-uncapped-seed6` (seed 6).
- Runner of `lab-cpu-uncapped-seed4`: 4 CPUs, AMD EPYC 9V74 80-Core Processor , kernel 7.0.0-1017-azure.
- Runner of `lab-cpu-uncapped-seed5`: 4 CPUs, AMD EPYC 9V74 80-Core Processor , kernel 7.0.0-1017-azure.
- Runner of `lab-cpu-uncapped-seed6`: 4 CPUs, Intel(R) Xeon(R) 6975P-C , kernel 7.0.0-1014-aws.
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `lab-cpu-uncapped-seed1` | `lab-cpu-uncapped-seed2` | `lab-cpu-uncapped-seed3` | `lab-cpu-uncapped-seed4` | `lab-cpu-uncapped-seed5` | `lab-cpu-uncapped-seed6` |
|---|---|---|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | pass | pass | **FAIL** | pass | pass | pass |
| V2 Every pod applied every phase, on schedule | pass | pass | pass | pass | pass | pass |
| V3 The network was healthy before anything was cut (>= 0.99) | pass | pass | **FAIL** | pass | pass | pass |
| V4 No message was received across a border while it had no open node | pass | pass | pass | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | pass | **FAIL** | **FAIL** | pass | **FAIL** | pass |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | pass | **FAIL** | **FAIL** | pass | pass | pass |
| V7 The evidence is complete and two records of it agree | pass | pass | **FAIL** | pass | pass | pass |

Run `lab-cpu-uncapped-seed2` is withdrawn and contributes no numbers. V5: 840 publishes, send lateness p99 64 ms, 0 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 57%, p95 98%, max 100% over 178 samples

Run `lab-cpu-uncapped-seed3` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 2 restarted, 0 not running; V3: lowest baseline delivery 0.9796; V5: 840 publishes, send lateness p99 70 ms, 2 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 57%, p95 98%, max 100% over 178 samples; V7: 838 publishes reconciled against 828 node send lines; 1975 receive lines for messages nobody logged sending; 2 pods where the controller and the node disagree on messages sent

Run `lab-cpu-uncapped-seed5` is withdrawn and contributes no numbers. V5: 840 publishes, send lateness p99 62 ms, 0 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault)


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| lab-cpu-uncapped-seed1 | cah-ir | 1048 | 0.677 | n/a | 0.0 |
| lab-cpu-uncapped-seed1 | cah-world | 1048 | 1.217 | n/a | 0.0 |
| lab-cpu-uncapped-seed2 | cah-ir | 1056 | 0.751 | n/a | 0.0 |
| lab-cpu-uncapped-seed2 | cah-world | 1056 | 1.261 | n/a | 0.0 |
| lab-cpu-uncapped-seed3 | cah-ir | 1051 | 0.759 | n/a | 0.0 |
| lab-cpu-uncapped-seed3 | cah-world | 1051 | 1.23 | n/a | 0.0 |
| lab-cpu-uncapped-seed4 | cah-ir | 1036 | 0.666 | n/a | 0.0 |
| lab-cpu-uncapped-seed4 | cah-world | 1036 | 1.13 | n/a | 0.0 |
| lab-cpu-uncapped-seed5 | cah-ir | 1025 | 0.631 | n/a | 0.0 |
| lab-cpu-uncapped-seed5 | cah-world | 1025 | 1.103 | n/a | 0.0 |
| lab-cpu-uncapped-seed6 | cah-ir | 999 | 0.531 | n/a | 0.0 |
| lab-cpu-uncapped-seed6 | cah-world | 999 | 1.011 | n/a | 0.0 |
## Delivery in steady state

Share of (message, node) pairs delivered, mean of 3 valid run(s) with the range across runs. *no path* marks a pair of regions with no open border between them in that phase. *late* is the share that arrived after the 10 s deadline, for example once a border reopened.

| Phase | Border | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|---|
| baseline | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |
| shut | 0/50 open | 100.00% | 0.00%, 100.0% late *(no path)* | 0.00%, 100.0% late *(no path)* | 100.00% |
| restored | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |

## Latency of delivered pairs

Median / 99th percentile, milliseconds, steady state.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| baseline | 31 / 62 | 141 / 205 | 130 / 186 | 72 / 230 |
| shut | 29 / 60 | n/a / n/a | n/a / n/a | 71 / 204 |
| restored | 30 / 62 | 139 / 226 | 131 / 198 | 75 / 218 |

## Time to settle after each change

Seconds from the start of a phase to the last message whose delivery was more than 1% below that phase's steady level. One value per valid run.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| shut | 0, 0, 0 | no path | no path | 0, 0, 0 |
| restored | 0, 0, 0 | 0, 0, 0 | 43, 0, 83 | 102.03, 0, 0 |

## When the mesh noticed

Seconds after each change until a region's mean mesh size first moved by more than 10%. One value per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node reports about itself, so it includes peers the node has not yet found to be unreachable.

| Phase | Region | Mesh size at start | at end | Reacted after (s) |
|---|---|---|---|---|
| shut | ir | 7.7 | 7.7 | never, never, never |
| shut | world | 7.1 | 7.1 | never, never, never |
| restored | ir | 7.7 | 6.5 | 102, 103, 103 |
| restored | world | 7.1 | 6.8 | 87, never, never |

## Messages sent while a border was shut

Of the messages published in one region while it had no path to another, the share of (message, node) pairs in the other region delivered by the end of the run, and when, in seconds after the path reopened. *During* is the share that crossed while the border was meant to be shut. The last column is when the sending region's mean mesh first moved by more than 10% during the shutdown, if it did.

| Run | Phase | From | To | Shut (s) | Messages | During | Delivered later | First (s) | Median (s) | Last (s) | Sender's mesh moved after (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lab-cpu-uncapped-seed1 | shut | ir | world | 240 | 119 | 0.00% | 100.00% | 1.1 | 14.8 | 18.7 | never |
| lab-cpu-uncapped-seed1 | shut | world | ir | 240 | 119 | 0.00% | 100.00% | 1.2 | 96 | 103.1 | never |
| lab-cpu-uncapped-seed4 | shut | ir | world | 240 | 119 | 0.00% | 100.00% | 0.7 | 21.7 | 25.3 | never |
| lab-cpu-uncapped-seed4 | shut | world | ir | 240 | 119 | 0.00% | 100.00% | 0.8 | 96 | 106.1 | never |
| lab-cpu-uncapped-seed6 | shut | ir | world | 240 | 119 | 0.00% | 100.00% | 1.1 | 2.7 | 5.3 | never |
| lab-cpu-uncapped-seed6 | shut | world | ir | 240 | 119 | 0.00% | 100.00% | 3.4 | 97.3 | 103.6 | never |

## Mesh reaction against node age

For the pods whose own mesh fell below its size at the start of the phase: the median moment of that first fall, counted from the change and from the start of the pod's node. A reaction tied to the change keeps the first number from run to run; one tied to a clock that began with the node keeps the last.

| Run | Phase | Region | Pods | After the change (s) | Node age at the change (s) | Node age at the fall (s) |
|---|---|---|---|---|---|---|
| lab-cpu-uncapped-seed1 | restored | ir | 37 | 102 | 755 | 857 |
| lab-cpu-uncapped-seed1 | restored | world | 66 | 82 | 749 | 833 |
| lab-cpu-uncapped-seed4 | restored | ir | 38 | 103 | 748 | 847 |
| lab-cpu-uncapped-seed6 | restored | ir | 48 | 103 | 707 | 811 |

## Stream idle timeouts when the mesh moved

Multiplexer streams the region's nodes closed for inactivity, from the nodes' own counter `libp2p_stream_timeouts`: from 25 s before the region's mean mesh first moved to 5 s after, and earlier in the same phase.

| Run | Phase | Region | Mesh moved after (s) | Timeouts around it | Earlier in the phase |
|---|---|---|---|---|---|
| lab-cpu-uncapped-seed1 | restored | ir | 102 | 0 | 0 |
| lab-cpu-uncapped-seed1 | restored | world | 87 | 0 | 0 |
| lab-cpu-uncapped-seed4 | restored | ir | 103 | 0 | 0 |
| lab-cpu-uncapped-seed6 | restored | ir | 103 | 0 | 0 |

## Bursts of stream idle timeouts

Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. Seconds after the phase began.

| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |
|---|---|---|---|---|---|---|
| lab-cpu-uncapped-seed1 | shut | ir | 102 | 237 | 112 | 8945 |
| lab-cpu-uncapped-seed1 | restored | ir | 162 | 232 | 212 | 398 |
| lab-cpu-uncapped-seed1 | shut | world | 97 | 237 | 232 | 10927 |
| lab-cpu-uncapped-seed1 | restored | world | 157 | 237 | 202 | 394 |
| lab-cpu-uncapped-seed4 | shut | ir | 108 | 233 | 163 | 8291 |
| lab-cpu-uncapped-seed4 | restored | ir | 168 | 228 | 203 | 402 |
| lab-cpu-uncapped-seed4 | shut | world | 103 | 233 | 113 | 9857 |
| lab-cpu-uncapped-seed4 | restored | world | 163 | 238 | 173 | 383 |
| lab-cpu-uncapped-seed6 | shut | ir | 143 | 208 | 163 | 9796 |
| lab-cpu-uncapped-seed6 | restored | ir | 198 | 233 | 208 | 357 |
| lab-cpu-uncapped-seed6 | shut | world | 143 | 208 | 198 | 12812 |
| lab-cpu-uncapped-seed6 | restored | world | 198 | 238 | 238 | 682 |

## Kernel TCP settings on the nodes

Read by each pod's shaper from the pod's own network namespace when it started. Pods per value, one column per valid run.

| Setting | lab-cpu-uncapped-seed1 | lab-cpu-uncapped-seed4 | lab-cpu-uncapped-seed6 |
|---|---|---|---|
| tcp_keepalive_time | 7200 (150 pods) | 7200 (150 pods) | 7200 (150 pods) |
| tcp_retries2 | 15 (150 pods) | 15 (150 pods) | 15 (150 pods) |

## Figures

From run `lab-cpu-uncapped-seed1`.

![Share of nodes reached by each message, by origin and destination region](delivery.png)

![Gossipsub mesh size per region over time](mesh.png)

