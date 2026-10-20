# Deterministic frame scheduling experiment

`docksr-mock --schedule` implements **R005-G0B-1**, the R-003 timing experiment
authorized by v1.6 while exact SESR model acquisition remains blocked. It reuses
the existing `FrameScheduler` ticket/ownership state machine. This is an
event-driven **SIMULATED** workload, without sleeping, NPU dispatch or game input.
The existing `docksr-mock` lifecycle scenarios and JSON contract are unchanged.

```sh
./build-host/bin/docksr-mock --schedule --fps 60 --service-ms 20 --gpu-ms 0 \
  --slots 3 --queue-capacity 2 --frames 6 --delay-frames 0 --execution overlap
```

JSON goes to stdout and a concise summary to stderr. Redirect them separately
when retaining results. Identical options produce byte-identical output; there
is no randomness, timestamp or physical performance claim. Use `--help` for all
options. Frames are capped at 100000 before allocation; times/counts use checked
unsigned arithmetic. Accepted FPS are 40/45/60, NPU service 1–25 integer ms,
GPU stage 0–25 integer ms, slots 1–3, admission queue capacity 0–3, extra delay
0/1 frame and deterministic `--infer-every` 1–60. The default tests create no
model/runtime dependency.

## Exact timing and ownership

The virtual clock has 18000 ticks/second: 40/45/60 FPS have exact periods of
450/400/300 ticks, and one integer millisecond is 18 ticks. Frame requests arrive
at `index * period`. Each presentation is `(index + 1 + delay_frames) * period`.
Delay 0 is the next frame boundary; delay 1 gives another full frame of latency.
Inference must finish **strictly before** that presentation. Completion exactly
at it is late, preserving the existing ownership model's exclusive-boundary rule.

The driver distinguishes that inference deadline from a consumer lease ending
one tick after presentation. Timely completion immediately acquires consumer
ownership, which is retained until presentation and then released. The extra
lease tick lets presentation release safely at the boundary; it never makes a
same-tick producer completion timely. The result counters come from the timing
driver, not the state machine's generic ready-output count.

Equal-time events run in this order: producer completions, presentations and
releases/cancellation, previously queued dispatch, then new arrivals. Zero-time
GPU stages run as additional events at that same tick. Ready results retain slots
until presentation; active work retains slots beyond a missed deadline until its
modeled producer actually completes. Never-started admission-queue work can be
cancelled at its deadline using an explicit trusted cancellation acknowledgement;
the driver checks its unstarted phase first. `ProducerPending` alone is not proof
that arbitrary external work can be cancelled. Interstage or active work has
started and is never cancelled by a timeout.

## Serial and hypothetical overlapped work

Both modes have **one serial NPU server**. More slots do not add processing units.
The capacity formulas below are ideal upper bounds; slots/deadlines, admission
and finite-run startup can make actual simulated delivery lower.
The configurable GPU stage models assumed preprocessing on the reconstruction
path, not measured game rendering. A base fallback frame is assumed already
available, with zero presentation/composition/release cost.

- `serial`: a frame's GPU and NPU stages share one exclusive resource. Assumed
  capacity is `1000 / (gpu_ms + service_ms)` unique results/second.
- `overlap`: one GPU preprocessing stage may run alongside one NPU stage for a
  different frame; dependency order is preserved. Assumed capacity is
  `1000 / max(gpu_ms, service_ms)`. This is an optimistic independent-resource
  hypothesis; actual GPU/NPU contention, dispatch, transfers and fences are absent.

FIFO admission waiting is bounded by `queue_capacity`. Zero means admission may
start the first stage immediately but cannot wait for it. Internal GPU-to-NPU
waiting is a separate FIFO, reported separately and bounded by the total slot
count. Slots cover all queued, active and retained-ready jobs. Queue depth means
waiting work, excluding active stages and ready outputs. Average depths are
time-weighted integrals over the explicit observation horizon, not averages of
event snapshots.

`infer_every=2` intentionally requests inference for every second arrival; other
frames use fallback. This changes offered inference load explicitly and never
counts skipped frames as new inference. Admission rejection is dropped work;
unstarted expiration is cancelled work; a late completed inference remains a
unique processed frame but cannot supply a timely presentation.

## Reading results

The command above has a 100 ms observation window. A 20 ms single server finishes
at 20, 40, 60, 80 and 100 ms: **5 unique completions**, not 6. All six presentations
use fallback because this no-delay configuration misses their respective
deadlines. The last work remains backlog; it is not drained into the reported
throughput. The concise summary distinguishes those quantities:

```text
SIMULATED only: 60 FPS arrivals, 20 ms NPU, 0 ms GPU, 3 slots; overlap. Assumed capacity 50.000 unique/s; offered 60.000 unique/s; capacity overload YES. Submitted 6, completed 5, cancelled 0, dropped 0; admission queue capacity 2, max 0, time-average 0.000; presented unique 0, fallback 6, delivered 6, end backlog 1. No hardware inference or game FPS measured.
```

At 40 FPS/20 ms/GPU 0 with one slot and no extra delay, all 40 requests in a
one-second run finish before presentation. At 40 FPS/25 ms exact equality, none
are timely; one extra delayed frame and two slots allow that latency, but cannot
raise the 40/s service ceiling. At 60 FPS/20 ms, even three slots cannot exceed
the 50/s server capacity. Delay can improve deadlines; it cannot repair deficient
service rate.

Serial/overlap comparisons also include this model's conservative cancellation
policy. Even with a zero-duration GPU stage, overlapped jobs enter the started
interstage queue and cannot be cancelled; serial jobs still waiting for their
first stage can expire unstarted. Their cancelled/dropped/backlog counts can
therefore differ without a service-rate improvement. Do not attribute every
mode difference solely to physical GPU/NPU overlap.

JSON includes configuration, virtual periods/horizon, assumed capacity/offered
load, overload flag, admission/interstage queue maximum and time-weighted mean,
submitted/completed/cancelled/dropped counts, met/missed deadlines, presented
unique results, fallback/delivered frames and remaining work/owned backlog.
`processed_unique_frames` counts actual simulated NPU service completions,
including late ones, not fallback or stale reuse. Presentation never reuses stale
neural output. Results/second divide by the stated observation window, including
extra startup presentation delay; finite-run rates are not steady-state promises.

Bounded queues and dropping can keep backlog small under overload. Therefore
bounded depth is **not** labeled stability: `demand_exceeds_assumed_capacity`
compares the declared offered rate against this simple model's capacity
independently of drop/cancel behavior. Equality may still miss deadlines.

## Verification and limits

```sh
cmake --build build-host --parallel 2
ctest --test-dir build-host -R 'docksr-schedule|docksr-core|docksr-mock' --output-on-failure
```

Tests use independent hand-calculated deadline/throughput cases and a complete
40/45/60 FPS × 1–25 ms × 1/2/3-slot × serial/overlap × delay 0/1 grid with
accounting invariants. Other checks cover cancellation ownership, exact boundary,
delayed presentation, cadence, deterministic JSON, invalid/overflow-sized input
and unchanged default mock behavior. The simulation does not establish model
compatibility, NPU throughput, real scheduler feasibility, queue stability under
measured jitter, GPU contention, power, image quality or a working Decky plugin.
