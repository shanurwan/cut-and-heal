# A 720-second shutdown

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- 3 run(s): `cut-length-720-seed1` (seed 1), `cut-length-720-seed2` (seed 2), `cut-length-720-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `cut-length-720-seed1` | `cut-length-720-seed2` | `cut-length-720-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | pass | pass | pass |
| V2 Every pod applied every phase, on schedule | pass | pass | pass |
| V3 The network was healthy before anything was cut (>= 0.99) | pass | pass | pass |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | pass | pass | pass |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | pass | pass | pass |
| V7 The evidence is complete and two records of it agree | pass | pass | pass |

## Delivery in steady state

Share of (message, node) pairs delivered, mean of 3 valid run(s) with the range across runs. *no path* marks a pair of regions with no open border between them in that phase. *late* is the share that arrived after the 10 s deadline, for example once a border reopened.

| Phase | Border | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|---|
| baseline | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |
| shut | 0/50 open | 100.00% | 0.00%, 5.9% late *(no path)* | 0.00% *(no path)* | 100.00% |
| restored | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |

## Latency of delivered pairs

Median / 99th percentile, milliseconds, steady state.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| baseline | 32 / 66 | 142 / 226 | 132 / 208 | 75 / 225 |
| shut | 30 / 63 | n/a / n/a | n/a / n/a | 72 / 182 |
| restored | 31 / 67 | 163 / 250 | 132 / 183 | 74 / 212 |

## Time to settle after each change

Seconds from the start of a phase to the last message whose delivery was more than 1% below that phase's steady level. One value per valid run.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| shut | 0, 0, 0 | no path | no path | 0, 0, 0 |
| restored | 0, 0, 0 | 0, 0, 0 | 0, 0, 1 | 117.02, 0, 0 |

## When the mesh noticed

Seconds after each change until a region's mean mesh size first moved by more than 10%. One value per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node reports about itself, so it includes peers the node has not yet found to be unreachable.

| Phase | Region | Mesh size at start | at end | Reacted after (s) |
|---|---|---|---|---|
| shut | ir | 7.9 | 6.5 | 548, 550, 565 |
| shut | world | 7.0 | 6.6 | never, never, never |
| restored | ir | 6.5 | 6.6 | never, never, never |
| restored | world | 6.6 | 6.6 | never, never, never |

## Messages sent while a border was shut

Of the messages published in one region while it had no path to another, the share of (message, node) pairs in the other region delivered by the end of the run, and when, in seconds after the path reopened. The last column is when the sending region's mean mesh first moved by more than 10% during the shutdown, if it did.

| Run | Phase | From | To | Shut (s) | Messages | Delivered later | First (s) | Median (s) | Last (s) | Sender's mesh moved after (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| cut-length-720-seed1 | shut | ir | world | 720 | 359 | 0.00% |  |  |  | 548 |
| cut-length-720-seed1 | shut | world | ir | 720 | 359 | 0.00% |  |  |  | never |
| cut-length-720-seed2 | shut | ir | world | 720 | 359 | 6.69% | 111.3 | 112 | 115.4 | 550 |
| cut-length-720-seed2 | shut | world | ir | 720 | 359 | 0.00% |  |  |  | never |
| cut-length-720-seed3 | shut | ir | world | 720 | 359 | 4.74% | 117.6 | 118 | 125.8 | 565 |
| cut-length-720-seed3 | shut | world | ir | 720 | 359 | 0.00% |  |  |  | never |

## Mesh reaction against node age

For the pods whose own mesh fell below its size at the start of the phase: the median moment of that first fall, counted from the change and from the start of the pod's node. A reaction tied to the change keeps the first number from run to run; one tied to a clock that began with the node keeps the last.

| Run | Phase | Region | Pods | After the change (s) | Node age at the change (s) | Node age at the fall (s) |
|---|---|---|---|---|---|---|
| cut-length-720-seed1 | shut | ir | 42 | 543 | 372 | 914 |
| cut-length-720-seed2 | shut | ir | 47 | 550 | 384 | 928 |
| cut-length-720-seed3 | shut | ir | 46 | 567 | 347 | 917 |

## Stream idle timeouts when the mesh moved

Multiplexer streams the region's nodes closed for inactivity, from the nodes' own counter `libp2p_stream_timeouts`: from 25 s before the region's mean mesh first moved to 5 s after, and earlier in the same phase.

| Run | Phase | Region | Mesh moved after (s) | Timeouts around it | Earlier in the phase |
|---|---|---|---|---|---|
| cut-length-720-seed1 | shut | ir | 548 | 1493 | 8682 |
| cut-length-720-seed2 | shut | ir | 550 | 2310 | 8333 |
| cut-length-720-seed3 | shut | ir | 565 | 1719 | 10128 |

## Bursts of stream idle timeouts

Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. Seconds after the phase began.

| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |
|---|---|---|---|---|---|---|
| cut-length-720-seed1 | shut | ir | 223 | 378 | 278 | 8675 |
| cut-length-720-seed1 | shut | ir | 523 | 623 | 573 | 3618 |
| cut-length-720-seed1 | restored | ir | 103 | 178 | 123 | 1188 |
| cut-length-720-seed1 | shut | world | 223 | 378 | 358 | 9575 |
| cut-length-720-seed1 | shut | world | 523 | 678 | 573 | 4841 |
| cut-length-720-seed1 | restored | world | 108 | 228 | 128 | 1337 |
| cut-length-720-seed2 | shut | ir | 225 | 345 | 255 | 8286 |
| cut-length-720-seed2 | shut | ir | 515 | 605 | 550 | 4129 |
| cut-length-720-seed2 | restored | ir | 95 | 165 | 115 | 1779 |
| cut-length-720-seed2 | shut | world | 235 | 345 | 330 | 10987 |
| cut-length-720-seed2 | shut | world | 525 | 645 | 555 | 5356 |
| cut-length-720-seed2 | restored | world | 105 | 205 | 120 | 1548 |
| cut-length-720-seed3 | shut | ir | 260 | 330 | 290 | 10108 |
| cut-length-720-seed3 | shut | ir | 550 | 625 | 575 | 4817 |
| cut-length-720-seed3 | restored | ir | 130 | 195 | 155 | 239 |
| cut-length-720-seed3 | shut | world | 260 | 330 | 315 | 13458 |
| cut-length-720-seed3 | shut | world | 555 | 640 | 575 | 6099 |
| cut-length-720-seed3 | restored | world | 130 | 195 | 155 | 322 |

## Kernel TCP settings on the nodes

Read by each pod's shaper from the pod's own network namespace when it started. Pods per value, one column per valid run.

| Setting | cut-length-720-seed1 | cut-length-720-seed2 | cut-length-720-seed3 |
|---|---|---|---|
| tcp_keepalive_time | 7200 (150 pods) | 7200 (150 pods) | 7200 (150 pods) |
| tcp_retries2 | 15 (150 pods) | 15 (150 pods) | 15 (150 pods) |

## Figures

From run `cut-length-720-seed1`.

![Share of nodes reached by each message, by origin and destination region](delivery.png)

![Gossipsub mesh size per region over time](mesh.png)

