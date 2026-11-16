# How much CPU can be taken away before the measurement changes? Findings

A lab that packs more pods onto each machine runs bigger experiments on the same hardware,
until the pods wait for CPU and the waiting shows up as latency the protocol did not cause.
Rule V6 guards against this by watching the host's load. It cannot see a node with its own
CPU limit, which is how capacity is shared in most clusters. This experiment caps the CPU of
each region's Kubernetes node and asks whether the validity rules notice. The question and
predictions are in [METHOD.md section 16](../../docs/METHOD.md#16-lab-question-how-much-cpu-can-be-taken-away-before-the-measurement-changes)
and [section 20](../../docs/METHOD.md#20-reruns-on-17-november).

The network is 50 gossipsub nodes in `ir` and 100 in `world`, 360 s of baseline, a 240 s
shutdown and 240 s after it. A cap is the millicores shared by both region nodes, a third to
`ir` and two thirds to `world`. Everything on a node shares its cap: the gossipsub nodes,
their shapers and the node's own Kubernetes agents.

## Result

**Starved runs did not slip through: they broke, and the rules withdrew them. But rule V6,
the one meant for this, saw none of it.** No run whose region nodes were throttled in more
than a third of scheduler periods was valid. Each one was caught by pod restarts, late
shapers or an unhealthy baseline, while the host stayed below half busy.

| Cap (millicores) | Runs valid | Region nodes throttled | Host busy, 95th percentile | What failed |
|---|---|---|---|---|
| none | 4 of 6 | none | 51 to 98% | V5 in three runs; V6 in two, V1, V3 and V7 in one (16 Nov) |
| 3000 | 2 of 3 | 18 to 41% of periods | 61 to 83% | one run: V1, V2, V3, V5, V7 |
| 2000 | 0 of 3 | 37 to 61% | 51 to 60% | V2 alone in one run; V1, V3, V5, V7 in two |
| 1500 | 0 of 3 | 61 to 76% | 45 to 47% | V1, V2, V3, V5, V7 in all |
| 1000, 500, 250 | 0 of 9 | 99.9 to 100% | not reached | the network never formed (16 Nov) |

Inside-to-inside delivery in the baseline's steady state, valid runs of 17 November:

| Arm | Median | 99th percentile | Region nodes throttled |
|---|---|---|---|
| uncapped (seeds 4 and 6) | 31.8, 29.5 ms | 61.9, 57.6 ms | none |
| 3000 (seeds 2 and 3) | 30.0, 31.7 ms | 77.2, 136.5 ms | 18 to 21%, 27 to 33% |

Uncapped, the region nodes used 1.5 to 2.0 cores in total over a run, start-up included.

## Predictions

| # | Prediction | Result |
|---|---|---|
| P27 | Every run of every arm passes V6 | **Refuted**: two uncapped runs on 16 November failed it (95th percentile 98%) |
| P28 | With 250 millicores, the median is at least twice the uncapped one | **Refuted**: no run with 250 was valid |
| P29 | A capped run passes all seven rules with the median at least 50% higher | **Refuted**: no such run in any arm |
| P30 | With 250 millicores, each region node is throttled in at least 20% of periods | Held: 99.9 to 100% |
| P36 | With 3000, every valid run's median is within 25% of the same day's uncapped mean | Held: −2% and +4% |
| P37 | With 1500, at most one run of three completes its timeline | **Refuted**: all three completed, and all three were withdrawn |
| P38 | With 2000, a valid run is at least 50% slower and throttled in at least 20% of periods | **Refuted**: no run with 2000 was valid |

Section 20 called P27 to P29 unjudgeable after the first runs. By the criteria written in
section 16 they are refuted, and they are listed so here.

## What the runs showed

**1. V6 is blind to a capped node.** With 1500 millicores, region nodes were throttled in 61
to 76% of periods while the host was at most 47% busy. V6 passed every one of those runs.

**2. Starvation shows as breakage before it shows as latency.** Pods restarted (5 to 21 per
run, in six of the seven withdrawn capped runs that started), shapers applied phases late, and the baseline lost messages. Not one run had a median
that was quietly higher and every rule passing, which is what P29 and P38 looked for. The
rules as they stand were enough for this workload.

**3. The margin is thin.** One run with 2000 millicores failed only V2: its slowest shapers
were 651 ms late at the 99th percentile, against a limit of 500 ms. Its baseline median was
29 ms, normal. A slightly looser V2 would have let a run throttled in 37 to 39% of periods
count.

**4. The tail moves before the median.** The valid runs with 3000 millicores, throttled in
up to a third of periods, kept the median within 4% and raised the 99th percentile by up to
2.3 times. A result about tail latency needs more headroom than one about the median.

**5. Size a lab by its peak, not its average.** The nodes averaged 1.5 to 2.0 cores, but a cap
of 2 cores lost every run and 1 core or less never formed the network: start-up needs far
more than the steady state. For this workload, 150 nodes needed about 3 cores, 50 nodes per
core.

## What this does not establish

- **A heavier workload.** One 1000-byte message a second.
- **Memory, disk or network limits** of the host.
- **The DST lab's machines**, which have more cores and a different network plugin.
- **A throttling rule.** P38 was to show whether a rule V8 on throttling is needed. It is
  not shown to be needed here, and point 3 says it might be on another day.
- **Many runs per arm.** Two valid runs with 3000 millicores and four uncapped.

## Why it matters

A lab that shares machines through CPU limits cannot rely on host load to tell it a run was
starved. Here the other rules caught it, because starvation broke things this workload
depends on. A workload that degrades more gently would not be caught, so each region node's
throttled share belongs in every run's evidence, as it now is in this tool.

## Provenance

| Cap | Report | Evidence | Valid runs |
|---|---|---|---|
| none | [uncapped](uncapped/report.md) | [replay run 43894842645](https://github.com/shanurwan/cut-and-heal/actions/runs/43894842645) (seeds 1 to 3, 16 Nov), [43906821689](https://github.com/shanurwan/cut-and-heal/actions/runs/43906821689) (seeds 4 to 6, 17 Nov) | 4 of 6 |
| 3000 | [3000](3000/report.md) | [43906842185](https://github.com/shanurwan/cut-and-heal/actions/runs/43906842185) | 2 of 3 |
| 2000 | [2000](2000/report.md) | [43906862260](https://github.com/shanurwan/cut-and-heal/actions/runs/43906862260) | 0 of 3 |
| 1500 | [1500](1500/report.md) | [43906882028](https://github.com/shanurwan/cut-and-heal/actions/runs/43906882028) | 0 of 3 |
| 1000 | [1000](1000/report.md) | [43894863278](https://github.com/shanurwan/cut-and-heal/actions/runs/43894863278) | 0 of 3 |
| 500 | [500](500/report.md) | [43894880525](https://github.com/shanurwan/cut-and-heal/actions/runs/43894880525) | 0 of 3 |
| 250 | [250](250/report.md) | [43894902482](https://github.com/shanurwan/cut-and-heal/actions/runs/43894902482) | 0 of 3 |

One job, one fresh K3s cluster and one seed per run, on GitHub-hosted `ubuntu-24.04` runners
(4 CPUs). Throttling is read from each region node's cgroup `cpu.stat` before and after the
run (`lab/` in the evidence). Every run that was started is listed: twenty-four runs, six valid.
