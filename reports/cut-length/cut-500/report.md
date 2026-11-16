# A 500-second shutdown

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- 3 run(s): `cut-length-500-seed1` (seed 1), `cut-length-500-seed2` (seed 2), `cut-length-500-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `cut-length-500-seed1` | `cut-length-500-seed2` | `cut-length-500-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | pass | **FAIL** | pass |
| V2 Every pod applied every phase, on schedule | pass | pass | pass |
| V3 The network was healthy before anything was cut (>= 0.99) | pass | **FAIL** | pass |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | pass | **FAIL** | pass |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | pass | pass | pass |
| V7 The evidence is complete and two records of it agree | pass | **FAIL** | pass |

Run `cut-length-500-seed2` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 3 restarted, 0 not running; V3: lowest baseline delivery 0.9388; V5: 1100 publishes, send lateness p99 80 ms, 4 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V7: 1096 publishes reconciled against 1073 node send lines; 4583 receive lines for messages nobody logged sending; 4 pods where the controller and the node disagree on messages sent

## Delivery in steady state

Share of (message, node) pairs delivered, mean of 2 valid run(s) with the range across runs. *no path* marks a pair of regions with no open border between them in that phase. *late* is the share that arrived after the 10 s deadline, for example once a border reopened.

| Phase | Border | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|---|
| baseline | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |
| shut | 0/50 open | 100.00% | 0.00%, 100.0% late *(no path)* | 0.00%, 100.0% late *(no path)* | 100.00% |
| restored | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |

## Latency of delivered pairs

Median / 99th percentile, milliseconds, steady state.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| baseline | 30 / 64 | 138 / 197 | 129 / 173 | 74 / 212 |
| shut | 29 / 57 | n/a / n/a | n/a / n/a | 70 / 181 |
| restored | 30 / 60 | 151 / 235 | 131 / 176 | 71 / 188 |

## Time to settle after each change

Seconds from the start of a phase to the last message whose delivery was more than 1% below that phase's steady level. One value per valid run.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| shut | 0, 0 | no path | no path | 0, 0 |
| restored | 0, 0 | 24, 28 | 77, 73 | 0, 0 |

## When the mesh noticed

Seconds after each change until a region's mean mesh size first moved by more than 10%. One value per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node reports about itself, so it includes peers the node has not yet found to be unreachable.

| Phase | Region | Mesh size at start | at end | Reacted after (s) |
|---|---|---|---|---|
| shut | ir | 8.0 | 8.0 | never, never |
| shut | world | 6.9 | 6.9 | never, never |
| restored | ir | 8.0 | 6.6 | 81, 80 |
| restored | world | 6.9 | 6.8 | never, never |

## Messages sent while a border was shut

Of the messages published in one region while it had no path to another, the share of (message, node) pairs in the other region delivered by the end of the run, and when, in seconds after the path reopened. The last column is when the sending region's mean mesh first moved by more than 10% during the shutdown, if it did.

| Run | Phase | From | To | Shut (s) | Messages | Delivered later | First (s) | Median (s) | Last (s) | Sender's mesh moved after (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| cut-length-500-seed1 | shut | ir | world | 500 | 249 | 100.00% | 12.3 | 28.2 | 34.3 | never |
| cut-length-500-seed1 | shut | world | ir | 500 | 249 | 97.19% | 12.3 | 83.9 | 102.1 | never |
| cut-length-500-seed3 | shut | ir | world | 500 | 249 | 100.00% | 10.2 | 33.7 | 39 | never |
| cut-length-500-seed3 | shut | world | ir | 500 | 249 | 98.80% | 6.1 | 85.6 | 101.7 | never |

## Mesh reaction against node age

For the pods whose own mesh fell below its size at the start of the phase: the median moment of that first fall, counted from the change and from the start of the pod's node. A reaction tied to the change keeps the first number from run to run; one tied to a clock that began with the node keeps the last.

| Run | Phase | Region | Pods | After the change (s) | Node age at the change (s) | Node age at the fall (s) |
|---|---|---|---|---|---|---|
| cut-length-500-seed1 | restored | ir | 39 | 76 | 851 | 920 |
| cut-length-500-seed3 | restored | ir | 45 | 80 | 842 | 920 |

## Stream idle timeouts when the mesh moved

Multiplexer streams the region's nodes closed for inactivity, from the nodes' own counter `libp2p_stream_timeouts`: from 25 s before the region's mean mesh first moved to 5 s after, and earlier in the same phase.

| Run | Phase | Region | Mesh moved after (s) | Timeouts around it | Earlier in the phase |
|---|---|---|---|---|---|
| cut-length-500-seed1 | restored | ir | 81 | 2411 | 1 |
| cut-length-500-seed3 | restored | ir | 80 | 2260 | 0 |

## Bursts of stream idle timeouts

Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. Seconds after the phase began.

| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |
|---|---|---|---|---|---|---|
| cut-length-500-seed1 | shut | ir | 266 | 341 | 281 | 10711 |
| cut-length-500-seed1 | restored | ir | 51 | 111 | 81 | 3690 |
| cut-length-500-seed1 | shut | world | 266 | 341 | 326 | 13061 |
| cut-length-500-seed1 | restored | world | 61 | 141 | 81 | 4604 |
| cut-length-500-seed3 | shut | ir | 265 | 335 | 285 | 11463 |
| cut-length-500-seed3 | restored | ir | 55 | 105 | 80 | 3727 |
| cut-length-500-seed3 | shut | world | 270 | 335 | 320 | 13276 |
| cut-length-500-seed3 | restored | world | 65 | 135 | 85 | 4736 |

## Kernel TCP settings on the nodes

Read by each pod's shaper from the pod's own network namespace when it started. Pods per value, one column per valid run.

| Setting | cut-length-500-seed1 | cut-length-500-seed3 |
|---|---|---|
| tcp_keepalive_time | 7200 (150 pods) | 7200 (150 pods) |
| tcp_retries2 | 15 (150 pods) | 15 (150 pods) |

## Figures

From run `cut-length-500-seed1`.

![Share of nodes reached by each message, by origin and destination region](delivery.png)

![Gossipsub mesh size per region over time](mesh.png)

