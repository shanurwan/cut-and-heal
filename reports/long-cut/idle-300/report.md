# An eighteen-minute shutdown with a yamux idle timeout of 300 s

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `cut-and-heal-node:yamux-idle`.
- Node settings: `YAMUX_IDLE_TIMEOUT_S=300`.
- 3 run(s): `idle-check-300-seed1` (seed 1), `idle-check-300-seed2` (seed 2), `idle-check-300-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `idle-check-300-seed1` | `idle-check-300-seed2` | `idle-check-300-seed3` |
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
| shut | 0/50 open | 100.00% | 0.00% *(no path)* | 0.00% *(no path)* | 100.00% |
| restored | 50/50 open | 100.00% | 1.43% (0.00% to 4.29%) | 1.90% (0.00% to 5.71%) | 100.00% |

## Latency of delivered pairs

Median / 99th percentile, milliseconds, steady state.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| baseline | 31 / 68 | 140 / 216 | 131 / 194 | 77 / 232 |
| shut | 30 / 64 | n/a / n/a | n/a / n/a | 75 / 182 |
| restored | 29 / 62 | 714 / 2455 | 706 / 2896 | 73 / 181 |

## Time to settle after each change

Seconds from the start of a phase to the last message whose delivery was more than 1% below that phase's steady level. One value per valid run.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| shut | 0, 0, 0 | no path | no path | 0, 0, 0 |
| restored | 0, 0, 0 | 0, 282, 0 | 0, 281, 0 | 0, 0, 0 |

## When the mesh noticed

Seconds after each change until a region's mean mesh size first moved by more than 10%. One value per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node reports about itself, so it includes peers the node has not yet found to be unreachable.

| Phase | Region | Mesh size at start | at end | Reacted after (s) |
|---|---|---|---|---|
| shut | ir | 7.8 | 6.7 | 575, 533, 553 |
| shut | world | 7.1 | 6.6 | never, never, 578 |
| restored | ir | 6.7 | 6.7 | never, never, never |
| restored | world | 6.6 | 6.6 | never, never, never |

## Mesh reaction against node age

For the pods whose own mesh fell below its size at the start of the phase: the median moment of that first fall, counted from the change and from the start of the pod's node. A reaction tied to the change keeps the first number from run to run; one tied to a clock that began with the node keeps the last.

| Run | Phase | Region | Pods | After the change (s) | Node age at the change (s) | Node age at the fall (s) |
|---|---|---|---|---|---|---|
| idle-check-300-seed1 | shut | ir | 42 | 565 | 378 | 944 |
| idle-check-300-seed2 | shut | ir | 39 | 523 | 426 | 949 |
| idle-check-300-seed3 | shut | ir | 46 | 551 | 384 | 935 |
| idle-check-300-seed3 | shut | world | 72 | 563 | 376 | 939 |

## Stream idle timeouts when the mesh moved

Multiplexer streams the region's nodes closed for inactivity, from the nodes' own counter `libp2p_stream_timeouts`: from 25 s before the region's mean mesh first moved to 5 s after, and earlier in the same phase.

| Run | Phase | Region | Mesh moved after (s) | Timeouts around it | Earlier in the phase |
|---|---|---|---|---|---|
| idle-check-300-seed1 | shut | ir | 575 | 2279 | 9611 |
| idle-check-300-seed2 | shut | ir | 533 | 1491 | 8860 |
| idle-check-300-seed3 | shut | ir | 553 | 1672 | 9896 |
| idle-check-300-seed3 | shut | world | 578 | 1882 | 13164 |

## Bursts of stream idle timeouts

Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. Seconds after the phase began.

| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |
|---|---|---|---|---|---|---|
| idle-check-300-seed1 | shut | ir | 245 | 355 | 290 | 9212 |
| idle-check-300-seed1 | shut | ir | 525 | 615 | 580 | 4133 |
| idle-check-300-seed1 | shut | ir | 825 | 915 | 835 | 3482 |
| idle-check-300-seed1 | shut | world | 245 | 355 | 335 | 10861 |
| idle-check-300-seed1 | shut | world | 525 | 650 | 555 | 5280 |
| idle-check-300-seed1 | shut | world | 820 | 925 | 845 | 3795 |
| idle-check-300-seed2 | shut | ir | 203 | 363 | 353 | 8131 |
| idle-check-300-seed2 | shut | ir | 478 | 608 | 518 | 3890 |
| idle-check-300-seed2 | shut | ir | 773 | 873 | 793 | 3569 |
| idle-check-300-seed2 | restored | ir | 293 | 298 | 298 | 102 |
| idle-check-300-seed2 | shut | world | 198 | 368 | 358 | 9109 |
| idle-check-300-seed2 | shut | world | 473 | 663 | 518 | 4866 |
| idle-check-300-seed2 | shut | world | 768 | 943 | 798 | 4045 |
| idle-check-300-seed2 | restored | world | 288 | 298 | 298 | 119 |
| idle-check-300-seed3 | shut | ir | 238 | 353 | 243 | 9817 |
| idle-check-300-seed3 | shut | ir | 518 | 638 | 573 | 4184 |
| idle-check-300-seed3 | shut | ir | 813 | 908 | 833 | 3532 |
| idle-check-300-seed3 | shut | world | 238 | 348 | 338 | 11763 |
| idle-check-300-seed3 | shut | world | 513 | 648 | 538 | 5203 |
| idle-check-300-seed3 | shut | world | 813 | 923 | 838 | 3764 |

## Kernel TCP settings on the nodes

Read by each pod's shaper from the pod's own network namespace when it started. Pods per value, one column per valid run.

| Setting | idle-check-300-seed1 | idle-check-300-seed2 | idle-check-300-seed3 |
|---|---|---|---|
| tcp_keepalive_time | 7200 (150 pods) | 7200 (150 pods) | 7200 (150 pods) |
| tcp_retries2 | 15 (150 pods) | 15 (150 pods) | 15 (150 pods) |

## Figures

From run `idle-check-300-seed1`.

![Share of nodes reached by each message, by origin and destination region](delivery.png)

![Gossipsub mesh size per region over time](mesh.png)

