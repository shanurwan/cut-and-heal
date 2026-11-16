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
| Steady window | Messages sent in the last half of a phase, never in its first `guard_s` (20 s), and at least `deadline_s` before it ends. |
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
| 2026-11-11 | Steady window | The last half of each phase. Was: everything after the first 20 s. | In the withdrawn 150-node runs, cross-border delivery took about 100 s to resume after two nodes reopened. A 20 s guard put most of that transition inside the "steady" figure, which then described neither the transition nor the level reached. Settle time is measured against the amended level. Predictions P1 to P7 are judged as written. |
| 2026-11-11 | V7 | The start line is `Host info`. | The pinned image does not log `Node started`. |


## 10. Follow-up question: what sets the nine minutes?

Written on 2026-11-14, before either scenario below was run.

In the Iran runs the nodes inside kept their pre-cut mesh size for 535 to 574 s after the
border shut. The report listed a connection timeout as a lead and did not test it. This
section tests one candidate.

**Hypothesis.** A node stops counting an unreachable peer when the kernel gives up on the
TCP connection to it, and not before. Nothing above TCP notices sooner.

**Design.** Two scenarios that differ in one setting. `long-cut` holds a full shutdown for
900 s with kernel defaults. `long-cut-short-timeout` is the same with
`net.ipv4.tcp_retries2` set to 5 on every node, where the default is 15. The setting is per
network namespace and is applied through the pod's security context; a pod whose setting the
kubelet refused does not start, so V1 covers it. Three seeds each. Validity rules and limits
are unchanged.

| # | Prediction | Refuted if |
|---|---|---|
| P8 | With default timers, the inside region's mean mesh size first moves by more than 10% between 480 and 660 s after the cut, as in the Iran runs. | It moves outside that window, or never, in any valid run. |
| P9 | With 5 retransmissions, it first moves within 120 s of the cut. | It takes longer than 120 s in any valid run. |

If P9 holds, the kernel's retransmission timeout is what a cut-off node waits for. If P9
fails while P8 holds, the timer is above TCP and this experiment has ruled the kernel out.
If P8 fails, the nine minutes did not reproduce and neither conclusion is drawn.

**What it cannot show.** Which nim-libp2p code path reacts to the closed connection, and
whether a NetworkPolicy cut behaves the same as a netem drop.

## 11. Follow-up question: is the kernel the only timer?

Written on 2026-11-15, before any scenario below was run.

Section 10 concluded that the kernel's retransmission limit sets how long a cut-off node
keeps a dead peer. That conclusion has a gap, noted in the report: the default arm reacted
at 537 to 577 s, and the documented default of 15 retransmissions cannot produce that. The
kernel closes a connection once the time since the first retransmission reaches the sum of
the backoff schedule: the timeout doubles from 200 ms, is capped at 120 s, and is counted
for `tcp_retries2` retransmissions plus the wait after the last one.

| `tcp_retries2` | Kernel closes after |
|---|---|
| 5 | 12.6 s |
| 8 | 102.2 s |
| 10 | 324.6 s |
| 13 | 684.6 s |
| 15 | 924.6 s |

A single test connection on another Linux host, cut with netem, closed after 13 s at 5,
107 s at 8 and 951 s at 15. So either the pods on the runners do not have 15, or something
other than the kernel closes the connection at about nine minutes. Section 10 could not tell
these apart because no run recorded the value inside a pod.

**Change to the tool.** Each pod's shaper now logs `tcp_retries2` and `tcp_keepalive_time`
as read from the pod's own network namespace, and the report prints them.

**Design.** `long-cut` once more, to record the default. Three new arms identical to it
except for `tcp_retries2`: `long-cut-retries-8`, `long-cut-retries-10`, `long-cut-retries-13`.
Three seeds per new arm, one for the default. Validity rules and limits are unchanged. In
section 10 the mesh moved 6 to 10 s after the kernel's own time at 5 retransmissions, so
each window below is the kernel's time plus up to 35 s.

| # | Prediction | Refuted if |
|---|---|---|
| P10 | Every pod of `long-cut` records `tcp_retries2 = 15`, and every pod of each arm records the value its scenario set. | Any pod records another value. |
| P11 | With 8 retransmissions, the inside mesh first moves 100 to 140 s after the cut. | It moves outside that window in any valid run. |
| P12 | With 10, it first moves 320 to 360 s after the cut. | It moves outside that window in any valid run. |
| P13 | With 13, it first moves 530 to 590 s after the cut: the same as with defaults, and about 100 s before the kernel would close the connection. | It moves outside that window in any valid run. |

**Reading the outcomes.**

- P10 to P13 all hold: two timers. The kernel governs below about nine minutes, and
  something else ends the connection at about nine minutes whatever the kernel's limit. The
  headline of the long-cut report is then too strong and is corrected.
- P10 fails because the default pods record 12: the kernel alone explains every run, and
  P13 should fail with a reaction near 685 to 720 s.
- P10 holds and P13 fails with a reaction near 685 to 720 s: the kernel governs at 13 but
  not at 15, which this design cannot explain. It is reported as open.
- P11 or P12 fails: the backoff rule above does not describe these nodes, and section 10's
  conclusion is withdrawn until it is understood.

**What it cannot show.** What the second timer is, if there is one. Candidates are a
keepalive or ping in the node's multiplexer and the gossipsub peer score; finding it means
reading nim-libp2p, which is not part of this experiment.

## 12. Follow-up question: is the second timer the multiplexer's idle check?

Written on 2026-11-15, before any scenario below was run.

Section 11 found that something other than the kernel ends connections about nine minutes
after a silent cut, and could not say what. Two things were done since, neither of them a
new run: the node's source was read, and the stored evidence was analysed again.

**What the source says.** nim-libp2p at commit `73c3637` (2.4.0), the one the regression
node's lock file pins:

- Every yamux stream has an idle timeout of 5 minutes (`inTimeout`, `outTimeout` in
  `libp2p/muxers/yamux/yamux.nim`).
- The timeout is a periodic check, not a deadline. `timeoutMonitor` in
  `libp2p/stream/connection.nim` sleeps for the timeout, then resets the stream only if no
  byte was read or written since the previous check. A stream that goes idle is therefore
  reset at the second check after its last byte: 5 to 10 minutes later, at a moment fixed by
  when the stream was opened and not by when it went idle.
- Gossipsub removes a peer from the mesh when its send stream to that peer is lost
  (`onPubSubPeerEvent`, `StreamClosed`, in `libp2p/protocols/pubsub/gossipsub.nim`).
- The regression node's own keepalive ping stops when the first message arrives
  (`ping_utils.nim`), so it plays no part here.

Two other paths were found that also end a stream to a peer that has stopped answering:
yamux resets a stream whose send queue passes 256 KB once the peer's window is used up, and
gossipsub disconnects a peer with 256 unfinished high-priority sends. Both would come a
fixed amount of traffic after the cut, whatever the age of the stream.

This is a reading of code, not a measurement.

**What the stored runs say.** If the idle check is the second timer, the mesh should fall
at a fixed age of the stream and not a fixed time after the cut. Stream ages are not
recorded; node ages are, from the first line of each node's log. For the eight stored runs
with default timers, the median inside node whose mesh fell:

| Run | Node age at the cut (s) | Mesh fell after the cut (s) | Node age when it fell (s) |
|---|---|---|---|
| long-cut seed 2 | 347 | 567 | 919 |
| long-cut seed 1 | 352 | 572 | 924 |
| iran-2019-11 seed 4 | 359 | 564 | 929 |
| iran-2019-11 seed 3 | 392 | 538 | 926 |
| iran-2019-11 seed 1 | 406 | 528 | 935 |
| iran-2019-11 seed 5 (withdrawn under V2) | 411 | 535 | 946 |
| long-cut seed 3 | 420 | 537 | 958 |
| iran-2019-11 seed 2 | 438 | 525 | 955 |

The later the cut came in a node's life, the sooner the mesh reacted. Every fall came when
the nodes were 919 to 958 s old, just past 900 s, the third 5-minute check. The age is not
constant: it rises by about 40 s across the table. Streams are opened some time after the
node starts, and a slower start-up would delay both the streams and the cut, but that is a
guess. This table was computed after the idea was formed, so it is a reason to run the
experiment and not a result of it.

**Change to the tool.** The report now gives, per run, the node age at which the mesh
fell. The controller exports the nodes' own counter of streams closed for inactivity,
`libp2p_stream_timeouts`, by stream type, and the report states how many yamux streams the
region closed around the moment its mesh moved.

**Design.** `long-cut-late`, identical to `long-cut` except that the baseline is 390 s
instead of 240 s, so the cut comes 150 s later in every node's life. Three seeds.
`long-cut` once more, for the counter. Validity rules and limits are unchanged.

With the cut 150 s later, the 5-minute check that follows it comes about 50 to 140 s after
the cut instead of about 200 to 290 s. If the nodes have stopped writing to their dead
peers by then, the streams are reset at the check after that, near a node age of 935 s. If
they are still writing, the reset comes one check later, near 1235 s. Which of the two
happens is not known; either one moves the reaction away from nine minutes.

| # | Prediction | Refuted if |
|---|---|---|
| P14 | In every valid run of `long-cut-late`, the median inside node is 900 to 975 s old, or 1200 to 1275 s old, when its mesh first falls. In the `long-cut` run it is 900 to 975 s old. | The age is outside those windows in any valid run. |
| P15 | In every valid run of `long-cut-late`, the inside mesh first moves either less than 480 s or more than 600 s after the cut. Every run so far with default timers or 13 retransmissions gave 492 to 582 s. | It first moves 480 to 600 s after the cut in any valid run. |
| P16 | In every valid run of both scenarios, the inside nodes count at least 35 yamux stream idle timeouts from 25 s before the inside mesh first moves to 5 s after. A 10% fall of the mean mesh of 50 nodes is about 39 peers removed. | They count fewer than 35 in any valid run. |

**Reading the outcomes.**

- P14 to P16 hold: the second timer is the multiplexer's idle check. "Nine minutes" was a
  5-minute limit plus the place where these scenarios happened to put the cut in the cycle
  of the check. The same node reacts to a silent cut anywhere from 5 to 10 minutes later,
  depending only on when the cut lands.
- They hold with falls at 1200 to 1275 s: the same, and the nodes went on writing to dead
  peers past the first check after the cut.
- P15 fails: the reaction is tied to the cut after all. The idle check is not the second
  timer, the pattern in the table above is unexplained, and the question stays open.
- P14 and P15 hold and P16 fails: something on a 5-minute cycle, but not this counter.
  Reported as open.

**What it cannot show.** The idle timeout itself is not varied; it is compiled into the
node, and changing it means building another image. The evidence would be timing and the
node's own counter, not an intervention on the mechanism. Nor does it show why a node stops
writing to a dead peer when it does, or how mplex and QUIC behave.

## 13. Follow-up question: does the reaction move when the idle timeout is changed?

Written on 2026-11-15, before any scenario below was run.

Section 12 concluded that the multiplexer's idle check is what makes a node with default
settings drop a dead peer. Its evidence was the source, the timing of the runs and the
nodes' own counter. It did not change the timeout, and said so. This section does.

**Change to the node.** The regression node is built from its own source
(`iftech/dst-libp2p-test-node` at `fb8691e`, its own Dockerfile and lock file) with one
change, `cluster/node/yamux-idle-timeout.patch`: the idle timeout of yamux streams, which
nim-libp2p already takes as a parameter, is read from `YAMUX_IDLE_TIMEOUT_S`. Unset, it is
the library's 300 s. The bootstrap node is the published image, unchanged.

**Change to the tool.** A scenario may name an image built on the machine and pass settings
to the node (`node.image`, `node.env`), and `cluster/build-node.sh` builds this one. The
report lists the bursts in which a region's nodes closed streams for inactivity, which
section 12 read from the evidence by hand.

**Design.** Three arms that differ in that one setting and nothing else: `idle-check-120`,
`idle-check-300`, `idle-check-600`. The regions, links and cut of `long-cut`, with the
shutdown held for 1080 s instead of 900 s so that a late reaction still falls inside it.
Three seeds each. Validity rules and limits are unchanged.

The arm at 300 is the control: a node built here from source, with the default timeout,
should behave as the published image did. If it does not, the build differs in some way that
matters and the other two arms say nothing.

Sections 11 and 12 put a node's last write to a dead peer between about 75 and 240 s after
the cut. A stream is reset at the first check that finds a whole interval without a byte, so
between one and two timeouts after that last write.

| # | Prediction | Refuted if |
|---|---|---|
| P17 | With 300 s, the inside mesh first moves 480 to 600 s after the cut, and the median inside node is 900 to 975 s old when its mesh falls: the same as the published node. | Either is outside its window in any valid run. |
| P18 | With 120 s, the inside mesh first moves 190 to 480 s after the cut. | It first moves outside that window in any valid run. |
| P19 | With 600 s, the inside mesh first moves more than 700 s after the cut. | It first moves 700 s or less after the cut in any valid run. |
| P20 | The peaks of consecutive bursts of yamux idle timeouts in the inside region during the shutdown are 270 to 330 s apart with 300 s and 570 to 630 s apart with 600 s. | Any pair of consecutive peaks is outside its window in any valid run. |

No spacing is predicted for 120 s. In section 12 a burst lasted 100 to 160 s, so at that
timeout the bursts would run into each other.

**Reading the outcomes.**

- P17 to P20 hold: the reaction to a silent cut moves with the yamux idle timeout, earlier
  when it is shorter and later when it is longer. With the source, the timing and the
  counter of section 12, that settles what the second timer is.
- P17 fails: the node built here does not behave like the published one. The experiment is
  void until the difference is found.
- P17 holds and P18 or P19 fails: changing the timeout does not move the reaction as the
  idle check would. Section 12's conclusion is withdrawn.
- P20 fails alone: the reaction moves with the setting but the counter's cycle does not
  follow it. Reported as open.

**What it cannot show.** In the arm at 600 s the stream reset is due about 800 to 930 s
after the cut. The kernel closes a silent connection after about 925 s, and the TCP
transport has an idle check of its own every 600 s. A late reaction there shows that the
yamux timeout was what produced nine minutes; it does not show which of the three ends the
connection once yamux is out of the way. Nothing here concerns mplex or QUIC.

## 14. Follow-up question: is a message sent into a shutdown lost, or only late?

Written on 2026-11-16, before any scenario below was run.

Gossipsub keeps no store of past messages beyond a few heartbeats. A message published while
a border is shut can only cross later if it waited in a connection that survived the cut:
in the kernel's send buffer, or queued in the multiplexer. Sections 10 to 13 found that a
cut-off node keeps its connections to dead peers until an idle check in nim-libp2p ends
them, 5 to 10 minutes after its last write. If that is all there is, a shutdown shorter than
that check costs users nothing but delay, and a longer one loses everything sent during it.

**What the stored runs already say.** The report now has a measure for this: of the
messages published in one region while it had no path to another (leaving out the first
2 s, when some were still in flight), the share of (message, node) pairs in the other region
delivered by the end of the run, and when. Applied to evidence collected before this
question was asked:

| Shutdown | Runs | Delivered later, inside to outside | Last delivery after reopening | Inside mesh moved during the shutdown |
|---|---|---|---|---|
| 300 s (open-nodes-sweep seed 5, three cuts) | 1 | 100% | 51 to 57 s | never |
| 600 s (iran-2019-11, valid seeds) | 4 | 0% | none | 535 to 574 s |
| 900 s (long-cut) | 3 | 0% | none | 537 to 577 s |

In the long shutdowns about 0.2% of pairs from outside to inside did cross, all within 3 s of
the reopening and all from the last 2 to 3 s before it: the length of gossip's own history.
These numbers were seen before the predictions below were written.

**Design.** Six scenarios that differ only in how long the border stays shut:
`cut-length-60`, `-240`, `-420`, `-500`, `-580` and `-720`. The regions and links of
`long-cut`, a 240 s baseline, and 360 s after the reopening so that late deliveries are
seen. Three seeds each, default kernel and node. Validity rules and limits are unchanged.
The lengths bracket where the inside mesh moved in earlier runs with default settings,
492 to 582 s after the cut.

| # | Prediction | Refuted if |
|---|---|---|
| P21 | With 60, 240 and 420 s, at least 99% of pairs published during the shutdown are delivered by the end of the run, in both directions. | Below 99% in either direction in any valid run. |
| P22 | With 720 s, at most 1% are, in both directions. | Above 1% in either direction in any valid run. |
| P23 | In every valid run of any length, from inside to outside: if the inside mean mesh had not moved by more than 10% when the border reopened, at least 95% are delivered; if it first moved more than 60 s before the reopening, at most 5% are. | Either half fails in any valid run. Runs in which the mesh first moved in the last 60 s are not judged. |
| P24 | In every valid run in which at least 95% are delivered, the last of them arrives within 125 s of the reopening, in both directions. Linux retransmits an unanswered segment at least every 120 s. | Any arrives later. |

**Reading the outcomes.**

- P21 to P24 hold: a shutdown shorter than the idle check delays messages by up to two
  minutes and loses none; a longer one loses all of them, and the line is drawn by the
  same check found in sections 12 and 13. For a messaging network, the cost of a short
  outage is a timer setting.
- P23 fails in its first half: messages are lost even though the connection has not been
  dropped. Something else discards them, such as the multiplexer's send-queue limit.
- P24 fails: messages survive but arrive later than the kernel's retransmission schedule
  allows, so something above TCP holds them.

**What it cannot show.** Any outage longer than 720 s. Messages larger or more frequent
than 1000 bytes a second, which fill the multiplexer's 256 KB window sooner. Whether an
application above gossipsub resends what was lost.

## 15. A second outage: Iran, September 2022

Written on 2026-11-16, before the scenario below was run.

The first replay was one long total shutdown. Three years later the same country used a
different tactic: from 21 September 2022, during the protests, mobile internet was cut every
evening while fixed lines stayed up, and traffic came back each night. IODA's signal for
22 September to 3 October repeats daily: about 72% of normal traffic in the day, 32% in the
evening curfew, 100% late at night (`scenarios/iran-2022-09.yaml` has the derivation).

**Design.** `iran-2022-09`: the regions and links of `iran-2019-11`, and two days of the
cycle, each phase 660 s. The real phases last hours, far longer than the 5 to 10 minutes a
node takes to drop a dead peer; 660 s keeps each phase on the same side of that. The share of
traffic is read as the share of inside nodes with a border link, as in 2019, so 36 nodes are
open in the day, 16 in the curfew and 50 at night. Nodes are opened in a fixed seeded order,
so each curfew closes 20 of the day's 36, each night reopens all 34 that are closed, and each
morning closes 14 again. Three seeds.

| # | Prediction | Refuted if |
|---|---|---|
| P25 | In the steady state of every phase, at least 99% of pairs are delivered within 10 s, inside, outside, and across the border in both directions. In 2019, two open nodes in fifty were enough. | Any of these is below 99% in any phase of any valid run. |
| P26 | The second day costs no more than the first: for each phase of day 2 and each direction across the border, the steady-state median latency is within 25% of the same phase on day 1. | It differs by more in any valid run. |

**Observed but not predicted.** The 2019 runs found crossing outward about four times slower
than at baseline while only some inside nodes were open. Its phases were shorter than the
idle check, so dead peers were still in the mesh throughout. The report gives the median
latency per phase; whether outward crossing is slower in the curfew, and whether that
lasts after the dead peers are dropped, is read from it without a prediction.

**What it cannot show.** Throttling. The fixed lines that stayed up in 2022 were also slow,
and nothing here models a slow or lossy border; every open node has the healthy link. Mobile
and fixed users who are the same people, or move between networks. More than two days.

## 16. Lab question: how much CPU can be taken away before the measurement changes?

Written on 2026-11-16, before any scenario below was run.

A lab that packs more pods onto each machine runs bigger experiments on the same hardware,
until the pods wait for CPU and the waiting shows up as latency that the protocol did not
cause. Rule V6 guards against this by watching the host's load. It cannot see a node that
has its own CPU limit, which is how capacity is shared in most clusters: such a node can be
starved while the host is idle.

In earlier runs the whole 4-CPU host was 26% busy at the median and 43% at the 95th
percentile, Kubernetes and the metrics store included. The median delivery from inside to
inside in the baseline was 28 to 33 ms.

**Change to the tool.** A scenario may cap the CPU of each region's Kubernetes node
(`lab.cpus`), which `cluster/up.sh` applies to the node's container. Everything on that node
shares the cap: the gossipsub nodes, their shapers, and the node's own kubelet and network
agents. The workflow records each region node's cgroup CPU counters before and after the run,
and the report gives the cores used and the share of scheduler periods in which the node was
throttled.

**Design.** Four arms that differ only in the cap: `lab-cpu-uncapped`, and `lab-cpu-1000`,
`-500` and `-250`, the millicores shared by both region nodes, a third to `ir` and two thirds
to `world`. A 360 s baseline, a 240 s shutdown and 240 s after it. Three seeds each. Validity
rules and limits are unchanged.

| # | Prediction | Refuted if |
|---|---|---|
| P27 | Every run of every arm passes V6. | Any run fails V6. |
| P28 | With 250 millicores, the median delivery from inside to inside in the baseline's steady state is at least twice that of the uncapped arm, averaged over valid runs of each. | It is less than twice, or no run with 250 is valid. |
| P29 | At least one capped arm has a run that passes all seven rules with that median at least 50% above the uncapped arm's mean. | No such run. |
| P30 | With 250 millicores, each region node is throttled in at least 20% of scheduler periods. | Below 20% for any region node in any run. |

**Reading the outcomes.**

- P27 to P30 hold: the validity rules pass runs whose latency is set by CPU starvation, not
  by the network. The fix is a rule on throttling, which this tool would then add as V8, and
  a capacity figure for the lab: the highest number of nodes per core at which the arm's
  latency matches the uncapped one.
- P28 fails: 150 nodes need less CPU than expected, and the capacity figure is at least
  600 nodes per core for this workload.
- P29 fails while P28 holds: the existing rules, most likely V2 through late shapers, already
  withdraw starved runs. The rules are sufficient and the capacity figure still stands.

**What it cannot show.** Memory pressure, disk or network limits of the host. A heavier
workload than one 1000-byte message a second. The DST lab's machines, which have more cores
and a different network plugin.

## 17. Lab question: does a NetworkPolicy partition a running mesh?

Written on 2026-11-16, before the scenario below was run.

A partition test in a Kubernetes lab is often made with NetworkPolicies: label the two sides
and allow each to talk only to itself. That is how 10ksim's partition experiment works. Every
cut in this project so far was made with netem, which drops every packet of the closed border
at a set time. A policy is different in two ways. It is enforced by the cluster's network
plugin when the plugin gets to it, not at a set time. And many plugins let packets of a
connection that already exists through before they look at policy, so that a policy blocks
new connections and leaves existing ones alone. Gossipsub's mesh is made of connections that
already exist.

**Change to the tool.** A scenario may shut its borders with policies (`cut: networkpolicy`).
The controller creates one policy per side when a shut phase begins and deletes them when it
ends, and records when it asked and when the API answered. Links keep their netem profile;
nothing is dropped by the shapers. Only whole cuts can be made this way.

For this scenario V4 is a measurement, not a validity rule: whether traffic crosses a policy
is the question. The report states what crossed and the run is not withdrawn for it.

**Design.** `policy-cut`: the regions and links of `long-cut`, the border shut for 600 s by
policies, three seeds. The test cluster is K3s, whose policies are enforced by its built-in
controller (kube-router), with flannel. The DST lab uses Cilium and Kube-OVN; nothing here is
measured on them.

| # | Prediction | Refuted if |
|---|---|---|
| P31 | The API server accepts every policy (HTTP 201 on create, 200 on delete) within 1 s of the phase starting. | Any request fails or answers later. |
| P32 | Messages keep crossing on the connections that existed before the policy: in the shut phase's steady state at least 90% of pairs across the border are delivered within 10 s, in both directions, in every run. | Below 90% in either direction in any run. |

**Reading the outcomes.**

- P31 and P32 hold: on this cluster a NetworkPolicy does not partition a running gossipsub
  mesh; it only stops new connections. A partition experiment built on policies would then
  measure an intact mesh unless it also ends the existing connections.
- P32 fails: the policy does stop existing connections. When the inside mesh first moves then
  tells how: within about 30 s if connections are reset, or 480 to 600 s, as with netem, if
  packets are silently dropped or refused with an ICMP error, which TCP ignores on an open
  connection.

**What it cannot show.** Cilium or Kube-OVN, which the DST lab runs, or how they are
configured there. Whether 10ksim's own partition, which applies its policies before or after
the mesh forms, is affected: that depends on when it applies them, which is not tested here.

## 18. Follow-up question: what does a shorter TCP timeout cost on a link that is only bad?

Written on 2026-11-16, before any scenario below was run.

The long-cut report says that lowering `tcp_retries2` to 8 or less makes a node notice a cut
within two minutes. It also says that this was never tried on a border that is slow and
lossy but still up, where the same setting may close connections that would have recovered.
The fixed lines that stayed up in Iran in 2022 were of that kind.

With independent loss `p` in each direction, a retransmission fails if either the segment
or its acknowledgement is lost, with probability `1 - (1 - p)^2`: 0.19 at 10%, 0.51 at 30%.
With 300 ms added each way the retransmission timeout starts near a second, so the kernel
gives up after about 7 consecutive failures at `tcp_retries2 = 8` and about 14 at the default
of 15. At 30% loss, 0.51^7 is about 1 in 110 and 0.51^14 about 1 in 12,000: every
connection meets hundreds of losses in fifteen minutes, so the shorter setting should close
many connections and the default very few. At 10% loss neither should close any.

**Design.** Four arms: `lossy-10`, `lossy-10-retries-8`, `lossy-30`, `lossy-30-retries-8`.
The regions and links of `long-cut`; for 900 s the border adds 300 ms each way (30 ms
jitter), loses 10% or 30% of packets each way and is limited to 5 Mbit/s; then it returns to
its healthy profile. The default kernel or `tcp_retries2 = 8`. Three seeds each.

| # | Prediction | Refuted if |
|---|---|---|
| P33 | With 10% loss, under either setting, the inside mean mesh does not move by more than 10% during the lossy phase, and at least 99% of pairs across the border in its steady state are delivered within 10 s. | Either fails in any valid run. |
| P34 | With 30% loss and `tcp_retries2 = 8`, the inside mean mesh moves by more than 10% during the lossy phase in every valid run. | It does not in any valid run. |
| P35 | With 30% loss and the default, it does not move by more than 10% in any valid run. | It does in any valid run. |

**Reading the outcomes.**

- P33 to P35 hold: the shorter timeout is free on a moderately bad link and costly on a very
  bad one, so the long-cut report's advice must name the loss it holds for.
- P34 fails: the shorter timeout closes too few connections to move the mesh even at 30%
  loss, and the advice stands without a condition at these levels.
- P35 fails: even the default closes connections on such a link, and the comparison between
  the two settings is read from how far and how often the mesh moved.

**What it cannot show.** Loss that comes in bursts, as on a congested or radio link; netem's
loss here is independent per packet. Any other delay or rate.

## 19. Not run: nodes of different implementations in one network

The DST roadmap lists interop at scale for this quarter. The test-node repository has go and
rust nodes beside the nim one, and a cut with mixed implementations would show whether the
others take as long as nim-libp2p to drop a dead peer. It was not run, because at commit
`fb8691e` the go node cannot join the same network as the regression node, and its output
cannot be read by this tool:

- **Peer identities.** The go node derives the peer ID it expects to dial from the peer's
  host name (`go-test-node/main.go`); the regression node generates a random key and is
  found through Kademlia from a bootstrap node. A go node would refuse the handshake.
- **Discovery.** The go node dials a number of addresses resolved from a Service name
  (`SERVICE`, `CONNECTTO`); the regression node expects the `bootstrap` service and Kademlia.
- **Receipts.** The go node logs `<sent> milliseconds: <delay>` for each message, without a
  message ID, so deliveries cannot be matched to messages across nodes.

Each is a change to the go node, not to the network or to this tool. The rust node was not
examined.

## 20. Reruns on 17 November

Written on 2026-11-17, before any run below, after the runs of sections 14 to 18.

**What went wrong on 16 November.** The same workload made the 4-CPU runner about twice as
busy as on 14 November: host CPU at the median 52 to 57% in `lab-cpu-uncapped`, against 26%
in `long-cut`. Of 48 runs, 18 were withdrawn, all three of `iran-2022-09` among them. And the
caps of section 16 were set from the host's load during earlier runs, which leaves out start-
up: uncapped, the region nodes used 0.68 to 0.76 cores (`ir`) and 1.22 to 1.26 cores
(`world`) on average over the whole run. With 1000 millicores or less no capped run formed
its network, so P27 to P29 could not be judged; P30 held. Those runs stay in the record.

**Changes to the tool.**

- Each run records the runner it had (CPUs, CPU model, kernel), so a difference between days
  can be seen in the evidence.
- In a policy cut, the first pod of each region opens a fresh TCP connection across the border
  every 10 s and logs how it ended: connected, no answer within 3 s, or refused. Section 17's
  runs could not tell a policy that leaves existing connections alone from one that is not
  enforced at all, because the nodes made no new connection during them.

**Runs.**

- `lab-cpu-uncapped` seeds 4 to 6, as the same-day reference, and `lab-cpu-3000`, `-2000`
  and `-1500` (a third to `ir`, two thirds to `world`), seeds 1 to 3. Around the measured
  average of about two cores.
- `policy-cut` seeds 4 to 6 with the probe. P31 and P32 are judged again on these runs.
- `iran-2022-09` seeds 4 to 6. P25 and P26 are judged on these runs.

| # | Prediction | Refuted if |
|---|---|---|
| P36 | With 3000 millicores, every valid run's median delivery from inside to inside in the baseline's steady state is within 25% of the mean of the valid uncapped runs of the same day. | Any differs by more. |
| P37 | With 1500 millicores, at most one run of three completes its timeline. | Two or more complete. |
| P38 | With 2000 millicores, at least one run passes all seven rules with that median at least 50% above the uncapped mean, and its region nodes throttled in at least 20% of scheduler periods. | No such run. |
| P39 | In the policy cut, every probe from `ir-0` to the bootstrap node in the steady part of the shut phase fails, and every probe in the baseline and after the reopening connects. | Any probe in the shut phase connects, or any outside it fails. |

**Reading the outcomes.** P39 holding while messages still cross means the policy is
enforced for new connections and leaves existing ones alone; the probe's failures say whether
it drops (no answer) or refuses. P39 failing in the shut phase means the policy was not
enforced in this cluster at all, and section 17's result says nothing about policies.

