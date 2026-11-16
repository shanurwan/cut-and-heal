# A 420-second shutdown

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- 6 run(s): `cut-length-420-seed1` (seed 1), `cut-length-420-seed2` (seed 2), `cut-length-420-seed3` (seed 3), `cut-length-420-seed4` (seed 4), `cut-length-420-seed5` (seed 5), `cut-length-420-seed6` (seed 6).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `cut-length-420-seed1` | `cut-length-420-seed2` | `cut-length-420-seed3` | `cut-length-420-seed4` | `cut-length-420-seed5` | `cut-length-420-seed6` |
|---|---|---|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | **FAIL** | pass | **FAIL** | **FAIL** | pass | pass |
| V2 Every pod applied every phase, on schedule | pass | pass | pass | pass | pass | pass |
| V3 The network was healthy before anything was cut (>= 0.99) | **FAIL** | pass | **FAIL** | **FAIL** | pass | pass |
| V4 No message was received across a border while it had no open node | pass | pass | pass | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | **FAIL** | **FAIL** | pass | **FAIL** | **FAIL** | pass |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | pass | pass | pass | **FAIL** | pass | pass |
| V7 The evidence is complete and two records of it agree | **FAIL** | pass | **FAIL** | **FAIL** | pass | pass |

Run `cut-length-420-seed1` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 1 restarted, 0 not running; V3: lowest baseline delivery 0.9796; V5: 1020 publishes, send lateness p99 103 ms, 2 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V7: 1018 publishes reconciled against 1012 node send lines; 1383 receive lines for messages nobody logged sending; 2 pods where the controller and the node disagree on messages sent

Run `cut-length-420-seed2` is withdrawn and contributes no numbers. V5: 1020 publishes, send lateness p99 130 ms, 0 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault)

Run `cut-length-420-seed3` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 1 restarted, 0 not running; V3: lowest baseline delivery 0.9796; V7: 1019 publishes reconciled against 1012 node send lines; 1192 receive lines for messages nobody logged sending; 1 pods where the controller and the node disagree on messages sent

Run `cut-length-420-seed4` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 10 restarted, 0 not running; V3: lowest baseline delivery 0.9091; V5: 1020 publishes, send lateness p99 131 ms, 10 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V6: CPU busy p50 52%, p95 100%, max 100% over 214 samples; V7: 1010 publishes reconciled against 976 node send lines; 7889 receive lines for messages nobody logged sending; 10 pods where the controller and the node disagree on messages sent

Run `cut-length-420-seed5` is withdrawn and contributes no numbers. V5: 1020 publishes, send lateness p99 55 ms, 0 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault)


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| cut-length-420-seed4 | cah-ir | 1252 | 0.709 | n/a | 0.0 |
| cut-length-420-seed4 | cah-world | 1252 | 1.199 | n/a | 0.0 |
| cut-length-420-seed5 | cah-ir | 1184 | 0.497 | n/a | 0.0 |
| cut-length-420-seed5 | cah-world | 1184 | 0.915 | n/a | 0.0 |
| cut-length-420-seed6 | cah-ir | 1192 | 0.592 | n/a | 0.0 |
| cut-length-420-seed6 | cah-world | 1192 | 1.038 | n/a | 0.0 |
## Delivery in steady state

Share of (message, node) pairs delivered, mean of 1 valid run(s) with the range across runs. *no path* marks a pair of regions with no open border between them in that phase. *late* is the share that arrived after the 10 s deadline, for example once a border reopened.

| Phase | Border | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|---|
| baseline | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |
| shut | 0/50 open | 100.00% | 0.00%, 100.0% late *(no path)* | 0.00%, 100.0% late *(no path)* | 100.00% |
| restored | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |

## Latency of delivered pairs

Median / 99th percentile, milliseconds, steady state.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| baseline | 33 / 64 | 142 / 207 | 131 / 197 | 76 / 237 |
| shut | 29 / 58 | n/a / n/a | n/a / n/a | 72 / 190 |
| restored | 31 / 64 | 139 / 223 | 133 / 210 | 78 / 232 |

## Time to settle after each change

Seconds from the start of a phase to the last message whose delivery was more than 1% below that phase's steady level. One value per valid run.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| shut | 0 | no path | no path | 0 |
| restored | 46.18 | 53.34 | 47.43 | 53.52 |

## When the mesh noticed

Seconds after each change until a region's mean mesh size first moved by more than 10%. One value per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node reports about itself, so it includes peers the node has not yet found to be unreachable.

| Phase | Region | Mesh size at start | at end | Reacted after (s) |
|---|---|---|---|---|
| shut | ir | 7.9 | 7.9 | never |
| shut | world | 7.1 | 7.1 | never |
| restored | ir | 7.9 | 6.6 | 46 |
| restored | world | 7.1 | 7.0 | never |

## Messages sent while a border was shut

Of the messages published in one region while it had no path to another, the share of (message, node) pairs in the other region delivered by the end of the run, and when, in seconds after the path reopened. The last column is when the sending region's mean mesh first moved by more than 10% during the shutdown, if it did.

| Run | Phase | From | To | Shut (s) | Messages | Delivered later | First (s) | Median (s) | Last (s) | Sender's mesh moved after (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| cut-length-420-seed6 | shut | ir | world | 420 | 209 | 100.00% | 6.7 | 26 | 31.7 | never |
| cut-length-420-seed6 | shut | world | ir | 420 | 209 | 100.00% | 31.4 | 40.5 | 61.1 | never |

## Mesh reaction against node age

For the pods whose own mesh fell below its size at the start of the phase: the median moment of that first fall, counted from the change and from the start of the pod's node. A reaction tied to the change keeps the first number from run to run; one tied to a clock that began with the node keeps the last.

| Run | Phase | Region | Pods | After the change (s) | Node age at the change (s) | Node age at the fall (s) |
|---|---|---|---|---|---|---|
| cut-length-420-seed6 | restored | ir | 42 | 46 | 780 | 826 |

## Stream idle timeouts when the mesh moved

Multiplexer streams the region's nodes closed for inactivity, from the nodes' own counter `libp2p_stream_timeouts`: from 25 s before the region's mean mesh first moved to 5 s after, and earlier in the same phase.

| Run | Phase | Region | Mesh moved after (s) | Timeouts around it | Earlier in the phase |
|---|---|---|---|---|---|
| cut-length-420-seed6 | restored | ir | 46 | 0 | 0 |

## Bursts of stream idle timeouts

Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. Seconds after the phase began.

| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |
|---|---|---|---|---|---|---|
| cut-length-420-seed6 | shut | ir | 261 | 356 | 276 | 9799 |
| cut-length-420-seed6 | restored | ir | 136 | 191 | 156 | 350 |
| cut-length-420-seed6 | shut | world | 261 | 356 | 346 | 11211 |
| cut-length-420-seed6 | restored | world | 136 | 236 | 226 | 1469 |

## Kernel TCP settings on the nodes

Read by each pod's shaper from the pod's own network namespace when it started. Pods per value, one column per valid run.

| Setting | cut-length-420-seed6 |
|---|---|
| tcp_keepalive_time | 7200 (150 pods) |
| tcp_retries2 | 15 (150 pods) |

## Figures

From run `cut-length-420-seed6`.

![Share of nodes reached by each message, by origin and destination region](delivery.png)

![Gossipsub mesh size per region over time](mesh.png)

