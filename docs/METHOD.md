# Method

This document fixes what is measured, how, and what makes a run void. It is written before
the runs it governs. Changes go in the amendments table at the end and apply to every run,
old and new.

## 1. Question

When a country's international links are cut or reduced while its domestic network stays up,
what does a gossipsub mesh spanning the border still deliver, to whom, and how long does it
take to adapt at each change?

## 2. Model

**Regions.** Nodes are grouped into regions. Each region is one or more Kubernetes nodes, so
its pods share pod CIDRs. That makes "the border" an address boundary the kernel can match.

**Links.** Every node shapes its own egress with `tc`: one netem class for traffic to its own
region, one per border, and an unshaped default class for everything else (API server, DNS,
metrics, the run controller). Shaping at both ends gives each direction its delay once.

**Border state.** In each phase a border has a number of *open nodes*: nodes of the gated
region that still have the border. A node that is not open drops border traffic in both
directions. Dropping only egress is not a partition, because TCP still delivers data to a
node that merely fails to acknowledge it. Nodes open in a fixed seeded order, so the set open
at 2 is inside the set open at 5.

**Why open nodes rather than packet loss.** A shutdown does not make every path equally
lossy. It disconnects most networks and leaves a few connected. The public signal used here
measures traffic, not networks, so mapping "3.6% of normal traffic" to "2 of 50 nodes open"
is an assumption. It is the assumption under test in the sensitivity runs (section 7).

**Time.** Durations are not preserved. Protocol timers do not compress: a gossipsub heartbeat
is 1 s whether the outage lasted an hour or a week. Each phase is long enough to reach a
steady state and to observe the transition into it. What is preserved is the order of the
phases and the depth of each.

**Synchrony.** Every shaper receives the whole timeline before T0 and applies each phase at
an absolute wall-clock time. A phase change does not wait for a control message, a watch
event or a policy to propagate.

## 3. Definitions

| Term | Definition |
|---|---|
| Pair | One message and one node other than its origin. |
| Delivered | The node logged the message within `deadline_s` (10 s) of the send time carried in the payload. |
| Late | Logged after the deadline. Counted separately, never as delivered. Reported beside the delivery ratio. |
| Steady window | Messages sent at least `guard_s` (20 s) after a phase starts and at least `deadline_s` before it ends. |
| Delivery ratio | Delivered pairs over all pairs, for one phase, origin region and receiving region. |
| Interval | 95% bootstrap interval over messages (2,000 resamples). Pairs from one message are not independent, so messages are resampled, not pairs. |
| Settle time | Seconds from the start of a phase to the last message whose ratio was more than 0.01 below that phase's steady ratio. |
| Path | Two regions have a path in a phase if a chain of borders joins them and each has at least one open node. |

Origins alternate between regions, so each region originates the same number of messages
whatever its size. Within a region a seeded shuffle visits every node before repeating.

Send and receive times come from the nodes' own logs. The controller's record of what it
published is used only to cross-check them.

## 4. Validity rules

A run that fails any rule is withdrawn. It is listed in the report with the reason and
contributes no numbers.

| Rule | Requirement | Fault it catches |
|---|---|---|
| V1 | The run completed; every pod is running at the end with zero restarts. | A restarted node rejoins with an empty mesh and looks like a protocol effect. |
| V2 | Every pod acknowledged setup and every phase with exit code 0, each within 500 ms of schedule. | A shaper that silently failed leaves a node unshaped: the run looks healthier than the scenario. |
| V3 | In the baseline's steady window every region pair delivered at least 99%. | A network that was not healthy before the cut makes everything after it uninterpretable. |
| V4 | No message was received by a node while its region had no path to the origin's region, judged by receive time, from 2 s after the phase began. | A leaking partition. |
| V5 | Publish send times are within 50 ms of schedule at the 99th percentile, and under 0.1% of publishes failed to reach a node. | A stalled load generator reads as a quiet network. |
| V6 | Host CPU busy at the 95th percentile is at most 85%. | A saturated host stretches every latency. |
| V7 | Logs exist for every container and contain the node's start line; the nodes' "Sent" lines match the controller's publish record pod by pod; no receive line refers to an unknown message. | Truncated or rotated logs under-count delivery without any error. |

A node refusing a publish because it has no peers (HTTP 500) is an outcome, not a fault. It
is counted and reported.

## 5. Replicates and comparison

Each scenario is run at least three times with different seeds. The seed changes which nodes
open first and the order of origins. Reports give the mean of valid runs and the range across
them. Two configurations are called different only if their ranges do not overlap and the
gap exceeds the larger range.

## 6. Predictions

Written on 2026-11-11, before the first cluster run, for `scenarios/iran-2019-11.yaml`.
Refuted predictions are reported as findings.

| # | Prediction | Refuted if |
|---|---|---|
| P1 | With the border fully shut, messages published inside still reach at least 99% of inside nodes in steady state. | Steady ratio below 0.99. |
| P2 | Inside-to-inside delivery settles within 10 s of the cut, although inside nodes lose about two thirds of their mesh at that instant. | Settle time above 10 s in any valid run. |
| P3 | Outside-to-outside delivery stays at or above 99% in every phase. | Any steady ratio below 0.99. |
| P4 | When 2 of 50 inside nodes reopen, cross-border delivery resumes in both directions within 60 s, with no node restarted. | Settle time above 60 s, or steady ratio of 0. |
| P5 | With 2 of 50 open, steady cross-border delivery is at least 95% in both directions: two bridging nodes are enough for the whole region. | Either direction below 0.95. |
| P6 | With 2 of 50 open, the bridging nodes send at least 3 times the median bytes of the other inside nodes. | Ratio below 3. |
| P7 | After full restoration, every region pair is back at or above 99% within 60 s. | Settle time above 60 s or steady ratio below 0.99. |

## 7. Sensitivity

The mapping from traffic share to open nodes is the weakest link in the model.
`scenarios/open-nodes-sweep.yaml` holds the border at 1, 2 and 5 open nodes for a full phase
each, with a full shutdown before every step so each starts from the same state. It shows
how the result depends on that one number.

## 8. Limits

- **Scale.** Hundreds of nodes on one host, not a public network of thousands. Mesh degree
  is fixed at D=6, so path lengths grow slowly with size, but nothing here is evidence about
  10,000 nodes.
- **One host, one clock.** All pods share a kernel clock, so latencies need no clock
  correction. On a multi-machine lab the same analysis needs measured clock offsets.
- **Links are per node.** Rate limits apply to each node's own border traffic. A national
  uplink shared by everyone, where one node's traffic slows another's, is not modelled.
- **The bootstrap node** replies unshaped. It carries no gossip, so this affects only how
  quickly peers are discovered.
- **One implementation.** nim-libp2p, the DST regression node at a pinned image digest, with
  the parameters that image ships: D=6, D_low=4, D_high=8, heartbeat 1 s, flood publish on.
- **Gossipsub only.** There is no store-and-forward here. Messages published while a border
  is shut are not expected to cross it later, and the analysis does not count that as a loss
  of the protocol under test.
- **Emulation.** netem delay, jitter, loss and rate are a model of a path, not a path.

## 9. Amendments

| Date | Rule | Change | Reason |
|---|---|---|---|
| 2026-11-11 | V4 | Judged by receive time instead of send time. Was: no pair delivered, on time or late, between regions with no path in the phase the message was sent. | The first end-to-end run failed V4 with every cross-border message of a 60 s cut marked late and none on time. The shapers' counters showed the border dropping packets throughout. The messages arrived after the border reopened: the TCP connections had stalled, not died, and delivered what they had buffered. That is delivery over a path that exists again, and a result worth reporting, not a leak. The original wording could not tell the two apart. |
| 2026-11-11 | none (V2 limit unchanged) | Three 150-node runs of `iran-2019-11` on a 4-CPU machine were withdrawn under V2: shapers applied phases up to 1,950 ms late against a 500 ms limit, while every other rule passed. | Each shaper forked `date`, one `tc` per command and `curl` on waking, and 150 of them woke at once. The shaper now forks once per phase or not at all. The limit stays where it was set. |
| 2026-11-11 | V7 | The start line is `Host info`. | The pinned image does not log `Node started`. |
