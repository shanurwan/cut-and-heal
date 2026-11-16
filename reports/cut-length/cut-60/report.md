# A 60-second shutdown

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- 3 run(s): `cut-length-60-seed1` (seed 1), `cut-length-60-seed2` (seed 2), `cut-length-60-seed3` (seed 3).
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `cut-length-60-seed1` | `cut-length-60-seed2` | `cut-length-60-seed3` |
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
| shut | 0/50 open | 100.00% | 0.00%, 100.0% late *(no path)* | 0.00%, 100.0% late *(no path)* | 100.00% |
| restored | 50/50 open | 100.00% | 100.00% | 100.00% | 100.00% |

## Latency of delivered pairs

Median / 99th percentile, milliseconds, steady state.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| baseline | 33 / 71 | 142 / 228 | 136 / 238 | 77 / 245 |
| shut | 31 / 57 | n/a / n/a | n/a / n/a | 73 / 191 |
| restored | 33 / 76 | 144 / 227 | 136 / 219 | 76 / 250 |

## Time to settle after each change

Seconds from the start of a phase to the last message whose delivery was more than 1% below that phase's steady level. One value per valid run.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| shut | 0, 0, 0 | no path | no path | 0, 0, 0 |
| restored | 0, 0, 0 | 0, 0, 0 | 0, 0, 0 | 0, 0, 0 |

## When the mesh noticed

Seconds after each change until a region's mean mesh size first moved by more than 10%. One value per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node reports about itself, so it includes peers the node has not yet found to be unreachable.

| Phase | Region | Mesh size at start | at end | Reacted after (s) |
|---|---|---|---|---|
| shut | ir | 7.8 | 7.8 | never, never, never |
| shut | world | 7.2 | 7.2 | never, never, never |
| restored | ir | 7.8 | 7.8 | never, never, never |
| restored | world | 7.2 | 7.2 | never, never, never |

## Messages sent while a border was shut

Of the messages published in one region while it had no path to another, the share of (message, node) pairs in the other region delivered by the end of the run, and when, in seconds after the path reopened. The last column is when the sending region's mean mesh first moved by more than 10% during the shutdown, if it did.

| Run | Phase | From | To | Shut (s) | Messages | Delivered later | First (s) | Median (s) | Last (s) | Sender's mesh moved after (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| cut-length-60-seed1 | shut | ir | world | 60 | 29 | 100.00% | 0.4 | 1.4 | 46.8 | never |
| cut-length-60-seed1 | shut | world | ir | 60 | 29 | 100.00% | 0.4 | 3.4 | 46.9 | never |
| cut-length-60-seed2 | shut | ir | world | 60 | 29 | 100.00% | 0.6 | 1.4 | 48.6 | never |
| cut-length-60-seed2 | shut | world | ir | 60 | 29 | 100.00% | 0.6 | 2.2 | 19.7 | never |
| cut-length-60-seed3 | shut | ir | world | 60 | 29 | 100.00% | 0.3 | 3.3 | 49.1 | never |
| cut-length-60-seed3 | shut | world | ir | 60 | 29 | 100.00% | 0.4 | 1 | 48.7 | never |

## Bursts of stream idle timeouts

Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. Seconds after the phase began.

| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |
|---|---|---|---|---|---|---|
| cut-length-60-seed1 | restored | ir | 202 | 292 | 202 | 6019 |
| cut-length-60-seed1 | restored | world | 202 | 287 | 277 | 7939 |
| cut-length-60-seed2 | restored | ir | 197 | 292 | 202 | 6306 |
| cut-length-60-seed2 | restored | world | 197 | 292 | 287 | 7632 |
| cut-length-60-seed3 | restored | ir | 122 | 302 | 132 | 6072 |
| cut-length-60-seed3 | restored | world | 117 | 302 | 292 | 7125 |

## Kernel TCP settings on the nodes

Read by each pod's shaper from the pod's own network namespace when it started. Pods per value, one column per valid run.

| Setting | cut-length-60-seed1 | cut-length-60-seed2 | cut-length-60-seed3 |
|---|---|---|---|
| tcp_keepalive_time | 7200 (150 pods) | 7200 (150 pods) | 7200 (150 pods) |
| tcp_retries2 | 15 (150 pods) | 15 (150 pods) | 15 (150 pods) |

## Figures

From run `cut-length-60-seed1`.

![Share of nodes reached by each message, by origin and destination region](delivery.png)

![Gossipsub mesh size per region over time](mesh.png)

