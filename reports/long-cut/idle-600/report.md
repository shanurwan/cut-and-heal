# An eighteen-minute shutdown with a yamux idle timeout of 600 s

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `cut-and-heal-node:yamux-idle`.
- Node settings: `YAMUX_IDLE_TIMEOUT_S=600`.
- 3 run(s): `idle-check-600-seed1` (seed 1), `idle-check-600-seed2` (seed 2), `idle-check-600-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `idle-check-600-seed1` | `idle-check-600-seed2` | `idle-check-600-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | pass | pass | pass |
| V2 Every pod applied every phase, on schedule | **FAIL** | pass | pass |
| V3 The network was healthy before anything was cut (>= 0.99) | pass | pass | pass |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | pass | pass | pass |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | pass | pass | pass |
| V7 The evidence is complete and two records of it agree | pass | pass | pass |

Run `idle-check-600-seed1` is withdrawn and contributes no numbers. V2: lateness p50 106 ms, p99 532 ms, max 579 ms over 450 applications; shaper off schedule (limit 500 ms)

## Delivery in steady state

Share of (message, node) pairs delivered, mean of 2 valid run(s) with the range across runs. *no path* marks a pair of regions with no open border between them in that phase. *late* is the share that arrived after the 10 s deadline, for example once a border reopened.

| Phase | Border | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|---|
| baseline | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |
| shut | 0/50 open | 100.00% | 0.00% *(no path)* | 0.00% *(no path)* | 100.00% |
| restored | 50/50 open | 100.00% | 0.00% | 0.00% | 100.00% |

## Latency of delivered pairs

Median / 99th percentile, milliseconds, steady state.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| baseline | 31 / 75 | 144 / 221 | 135 / 216 | 82 / 240 |
| shut | 30 / 69 | n/a / n/a | n/a / n/a | 74 / 186 |
| restored | 29 / 65 | n/a / n/a | n/a / n/a | 73 / 183 |

## Time to settle after each change

Seconds from the start of a phase to the last message whose delivery was more than 1% below that phase's steady level. One value per valid run.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| shut | 0, 0 | no path | no path | 0, 0 |
| restored | 0, 0 | 0, 0 | 0, 0 | 0, 0 |

## When the mesh noticed

Seconds after each change until a region's mean mesh size first moved by more than 10%. One value per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node reports about itself, so it includes peers the node has not yet found to be unreachable.

| Phase | Region | Mesh size at start | at end | Reacted after (s) |
|---|---|---|---|---|
| shut | ir | 7.8 | 6.3 | 536, 577 |
| shut | world | 7.1 | 6.7 | never, never |
| restored | ir | 6.3 | 6.3 | never, never |
| restored | world | 6.7 | 6.7 | never, never |

## Mesh reaction against node age

For the pods whose own mesh fell below its size at the start of the phase: the median moment of that first fall, counted from the change and from the start of the pod's node. A reaction tied to the change keeps the first number from run to run; one tied to a clock that began with the node keeps the last.

| Run | Phase | Region | Pods | After the change (s) | Node age at the change (s) | Node age at the fall (s) |
|---|---|---|---|---|---|---|
| idle-check-600-seed2 | shut | ir | 47 | 536 | 412 | 946 |
| idle-check-600-seed3 | shut | ir | 41 | 567 | 376 | 948 |

## Stream idle timeouts when the mesh moved

Multiplexer streams the region's nodes closed for inactivity, from the nodes' own counter `libp2p_stream_timeouts`: from 25 s before the region's mean mesh first moved to 5 s after, and earlier in the same phase.

| Run | Phase | Region | Mesh moved after (s) | Timeouts around it | Earlier in the phase |
|---|---|---|---|---|---|
| idle-check-600-seed2 | shut | ir | 536 | 0 | 0 |
| idle-check-600-seed3 | shut | ir | 577 | 0 | 0 |

## Bursts of stream idle timeouts

Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. Seconds after the phase began.

| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |
|---|---|---|---|---|---|---|
| idle-check-600-seed2 | shut | ir | 816 | 966 | 836 | 11266 |
| idle-check-600-seed2 | shut | world | 811 | 966 | 956 | 12114 |
| idle-check-600-seed3 | shut | ir | 852 | 962 | 877 | 11689 |
| idle-check-600-seed3 | shut | world | 847 | 962 | 952 | 13917 |

## Kernel TCP settings on the nodes

Read by each pod's shaper from the pod's own network namespace when it started. Pods per value, one column per valid run.

| Setting | idle-check-600-seed2 | idle-check-600-seed3 |
|---|---|---|
| tcp_keepalive_time | 7200 (150 pods) | 7200 (150 pods) |
| tcp_retries2 | 15 (150 pods) | 15 (150 pods) |

## Figures

From run `idle-check-600-seed2`.

![Share of nodes reached by each message, by origin and destination region](delivery.png)

![Gossipsub mesh size per region over time](mesh.png)

