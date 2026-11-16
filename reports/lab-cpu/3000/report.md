# A short shutdown with 3000 millicores for all region nodes

## Setup

- 50 nodes in `ir`, 100 nodes in `world`; bootstrap node in `world`.
- Publish rate 1 msg/s, 1000 bytes, origins alternating between regions.
- System under test: `albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988`.
- CPU cap per region node: `ir` 1 cores, `world` 2 cores.
- 3 run(s): `lab-cpu-3000-seed1` (seed 1), `lab-cpu-3000-seed2` (seed 2), `lab-cpu-3000-seed3` (seed 3).
- Runner of `lab-cpu-3000-seed1`: 4 CPUs, AMD EPYC 7763 64-Core Processor , kernel 7.0.0-1017-azure.
- Runner of `lab-cpu-3000-seed2`: 4 CPUs, Intel(R) Xeon(R) 6975P-C , kernel 7.0.0-1014-aws.
- Runner of `lab-cpu-3000-seed3`: 4 CPUs, INTEL(R) XEON(R) PLATINUM 8573C , kernel 7.0.0-1017-azure.
- A pair (message, receiving node) counts as delivered within 10 s. Steady-state figures cover the last 50% of each phase.

## Validity

| Rule | `lab-cpu-3000-seed1` | `lab-cpu-3000-seed2` | `lab-cpu-3000-seed3` |
|---|---|---|---|
| V1 The run completed on the intended topology, with no pod restarts | **FAIL** | pass | pass |
| V2 Every pod applied every phase, on schedule | **FAIL** | pass | pass |
| V3 The network was healthy before anything was cut (>= 0.99) | **FAIL** | pass | pass |
| V4 No message was received across a border while it had no open node | pass | pass | pass |
| V5 The publisher kept its schedule and reached the nodes | **FAIL** | pass | pass |
| V6 The host had CPU headroom throughout (p95 busy <= 85%) | pass | pass | pass |
| V7 The evidence is complete and two records of it agree | **FAIL** | pass | pass |

Run `lab-cpu-3000-seed1` is withdrawn and contributes no numbers. V1: status=completed; 150/150 pods at end, 5 restarted, 0 not running; V2: lateness p50 103 ms, p99 461 ms, max 1473 ms over 450 applications; shaper off schedule (limit 500 ms); V3: lowest baseline delivery 0.8980; V5: 840 publishes, send lateness p99 3 ms, 5 never reached a node, 0 refused by the node for having no peers (an outcome, not a fault); V7: 835 publishes reconciled against 800 node send lines; 6065 receive lines for messages nobody logged sending; 5 pods where the controller and the node disagree on messages sent


## CPU of the region machines

From each region node's cgroup, before and after the run, for every run including withdrawn ones. *Throttled* is the share of 100 ms scheduler periods in which the node had used its whole cap.

| Run | Node | Seconds | Cores used | Throttled periods | Seconds throttled |
|---|---|---|---|---|---|
| lab-cpu-3000-seed1 | cah-ir | 1111 | 0.661 | 41.0% | 710.0 |
| lab-cpu-3000-seed1 | cah-world | 1111 | 1.381 | 38.1% | 318.5 |
| lab-cpu-3000-seed2 | cah-ir | 1003 | 0.493 | 21.1% | 292.0 |
| lab-cpu-3000-seed2 | cah-world | 1003 | 1.037 | 17.5% | 129.7 |
| lab-cpu-3000-seed3 | cah-ir | 1051 | 0.608 | 32.7% | 545.2 |
| lab-cpu-3000-seed3 | cah-world | 1051 | 1.232 | 26.5% | 214.0 |
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
| baseline | 31 / 107 | 140 / 227 | 130 / 206 | 73 / 204 |
| shut | 29 / 89 | n/a / n/a | n/a / n/a | 71 / 173 |
| restored | 31 / 2607 | 139 / 349 | 130 / 2273 | 73 / 239 |

## Time to settle after each change

Seconds from the start of a phase to the last message whose delivery was more than 1% below that phase's steady level. One value per valid run.

| Phase | ir to ir | ir to world | world to ir | world to world |
|---|---|---|---|---|
| shut | 0, 0 | no path | no path | 0, 0 |
| restored | 100.02, 117.4 | 0, 62 | 107.1, 119 | 0, 99.28 |

## When the mesh noticed

Seconds after each change until a region's mean mesh size first moved by more than 10%. One value per valid run; *never* means it stayed within 10% for the whole phase. The size is what each node reports about itself, so it includes peers the node has not yet found to be unreachable.

| Phase | Region | Mesh size at start | at end | Reacted after (s) |
|---|---|---|---|---|
| shut | ir | 7.4 | 7.4 | never, never |
| shut | world | 7.3 | 7.3 | never, never |
| restored | ir | 7.4 | 6.3 | 106, 112 |
| restored | world | 7.3 | 6.8 | 86, 82 |

## Messages sent while a border was shut

Of the messages published in one region while it had no path to another, the share of (message, node) pairs in the other region delivered by the end of the run, and when, in seconds after the path reopened. *During* is the share that crossed while the border was meant to be shut. The last column is when the sending region's mean mesh first moved by more than 10% during the shutdown, if it did.

| Run | Phase | From | To | Shut (s) | Messages | During | Delivered later | First (s) | Median (s) | Last (s) | Sender's mesh moved after (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lab-cpu-3000-seed2 | shut | ir | world | 240 | 119 | 0.00% | 100.00% | 0.8 | 8.2 | 12.5 | never |
| lab-cpu-3000-seed2 | shut | world | ir | 240 | 119 | 0.00% | 100.00% | 2.3 | 97.2 | 113.4 | never |
| lab-cpu-3000-seed3 | shut | ir | world | 240 | 119 | 0.00% | 100.00% | 0.5 | 25.3 | 74 | never |
| lab-cpu-3000-seed3 | shut | world | ir | 240 | 119 | 0.00% | 100.00% | 0.5 | 97.1 | 126.3 | never |

## Mesh reaction against node age

For the pods whose own mesh fell below its size at the start of the phase: the median moment of that first fall, counted from the change and from the start of the pod's node. A reaction tied to the change keeps the first number from run to run; one tied to a clock that began with the node keeps the last.

| Run | Phase | Region | Pods | After the change (s) | Node age at the change (s) | Node age at the fall (s) |
|---|---|---|---|---|---|---|
| lab-cpu-3000-seed2 | restored | ir | 39 | 106 | 709 | 815 |
| lab-cpu-3000-seed2 | restored | world | 66 | 81 | 708 | 790 |
| lab-cpu-3000-seed3 | restored | ir | 47 | 112 | 757 | 866 |
| lab-cpu-3000-seed3 | restored | world | 67 | 77 | 755 | 833 |

## Stream idle timeouts when the mesh moved

Multiplexer streams the region's nodes closed for inactivity, from the nodes' own counter `libp2p_stream_timeouts`: from 25 s before the region's mean mesh first moved to 5 s after, and earlier in the same phase.

| Run | Phase | Region | Mesh moved after (s) | Timeouts around it | Earlier in the phase |
|---|---|---|---|---|---|
| lab-cpu-3000-seed2 | restored | ir | 106 | 0 | 0 |
| lab-cpu-3000-seed2 | restored | world | 86 | 0 | 0 |
| lab-cpu-3000-seed3 | restored | ir | 112 | -132 | 879 |
| lab-cpu-3000-seed3 | restored | world | 82 | 0 | 1491 |

## Bursts of stream idle timeouts

Stretches in which a region's nodes closed multiplexer streams for inactivity, from the same counter. A burst ends after 60 s without a timeout; bursts of fewer than 100 are left out. Seconds after the phase began.

| Run | Phase | Region | From (s) | To (s) | Peak (s) | Timeouts |
|---|---|---|---|---|---|---|
| lab-cpu-3000-seed2 | shut | ir | 146 | 236 | 231 | 8206 |
| lab-cpu-3000-seed2 | shut | world | 146 | 236 | 226 | 12662 |
| lab-cpu-3000-seed2 | restored | world | 206 | 236 | 236 | 648 |
| lab-cpu-3000-seed3 | shut | ir | 102 | 237 | 237 | 6093 |
| lab-cpu-3000-seed3 | restored | ir | 2 | 12 | 2 | 879 |
| lab-cpu-3000-seed3 | restored | ir | 127 | 237 | 127 | 245 |
| lab-cpu-3000-seed3 | shut | world | 92 | 237 | 237 | 9469 |
| lab-cpu-3000-seed3 | restored | world | 2 | 12 | 2 | 1491 |
| lab-cpu-3000-seed3 | restored | world | 112 | 237 | 112 | 676 |

## Kernel TCP settings on the nodes

Read by each pod's shaper from the pod's own network namespace when it started. Pods per value, one column per valid run.

| Setting | lab-cpu-3000-seed2 | lab-cpu-3000-seed3 |
|---|---|---|
| tcp_keepalive_time | 7200 (150 pods) | 7200 (150 pods) |
| tcp_retries2 | 15 (150 pods) | 15 (150 pods) |

## Figures

From run `lab-cpu-3000-seed2`.

![Share of nodes reached by each message, by origin and destination region](delivery.png)

![Gossipsub mesh size per region over time](mesh.png)

