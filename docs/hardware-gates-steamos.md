# SteamOS H0–H4 evidence plan — DSR013-P / R-009

These are **unexecuted physical protocols**, extending DSR012-P rather than new
executors. Existing [CPU reference](fullframe-reference.md),
[native worker](inference-worker.md), [device probe](npu-device-probe.md) and
[benchmark analysis](benchmark-laboratory.md) remain authoritative for their
implemented scope. The [H1 runner](h1-inference-harness.md) now exposes a persistent single-tile
attempt; validated physical proof adapters, full-frame H2 and P-D timed collectors
are still pending. This document is not a runnable complete hardware-day kit.
No extra backend, scheduler, model, Gamescope hook or Decky code is added.

## Common evidence and stop policy

Every run needs exact source/model/input/runtime/options/cache identities, OS,
kernel, driver/firmware/plugin fingerprint, monotonic clock/unit, fixed power
profile and declared comparison/acceptance policy. Record actual command exit
statuses. Keep raw evidence private, immutable and hashed. Canonical
`hardware-evidence.schema.json` plus optional `benchmark_run` carry observations;
`steamos-readiness.schema.json` only references those artifacts and gate reviews.
Both validators check metadata consistency, not that hardware actually executed.

On wrong output, CPU-only/critical-CPU placement, unbounded queues, timeout,
firmware/driver errors or instability: stop admitting work, retain ownership until
executor quiescence, disable only DockSR, preserve evidence and leave ordinary
gaming untouched. Do not induce reset/suspend stress, repair drivers or change
power/memlock/firmware automatically. Actual device operations beyond passive
discovery need an owner-reviewed phase; elevated work needs exact commands,
risk and rollback approved before execution.

## H0 — visibility, not inference or compatibility

Start with [passive discovery](steamos-first-readiness.md). Establish the exact
SteamOS build and kernel, CPU/APU and NPU PCI identity, actual amdxdna binding,
module provenance, installed **and loaded** firmware evidence, relevant character
nodes/access, memlock and compatible XRT base/plugin/library versions. Missing
metadata is UNKNOWN, not an invented version or automatic FAIL. A kernel version
above6.10 does not prove its config, firmware or plugin ABI.

If XRT is already installed, review its version/help and documented platform
report capability before an explicitly approved query. Do not source a guessed
`/opt` path. An XRT device/platform listing is H0 only. `xrt-smi validate` is an
active latency/throughput/GEMM validation workload, not passive inventory or SESR
proof; keep it a separate approval-gated diagnostic, not an automatic prerequisite.

## H1 — unchanged SESR-M7 on physical XDNA2

Require all of the following together, not a provider/model-loading badge:

- Original107131-byte artifact SHA256
  `63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1`,
  source revision and inspected graph identity: INT8 NHWC[1,256,256,3] →
  [1,512,512,3], native2×, IR9/opset19,60 standard nodes. No conversion.
- Actual installed ORT/Vitis version/provider availability and effective
  `VitisAIExecutionProvider` options; `target=X2` only after exact support review.
- Operator/partition report mapping original critical reconstruction work to
  NPU, critical CPU/unassigned counts zero, CPU partitions explicitly retained;
  no silent CPU-only fallback. Runtime `disable_fallback()` cannot prevent
  initial CPU partitioning. Fused-node labels alone are insufficient.
- Active XRT hardware context/command evidence **during this exact run**, with
  attributable execution window/identity; an idle listing or another client's
  context is insufficient. If instrumentation is unavailable, H1 stays BLOCKED.
- CPU-reference agreement under a declared policy before the run: start with
  atol=0,rtol=0 on INT8 output, subtract in INT16; report every mismatch and
  investigate before proposing a justified new acceptance policy.
- Input/output/reference hashes, successful samples and the canonical hardware
  record. Self-test output is not a consumed/presented neural game frame.

AMD's1.8 model deployment documentation describes
`XLNX_ONNX_EP_REPORT_FILE` plus provider option
`enable_cache_file_io_in_mem=0` for a Linux operator-assignment report. Use a
private absolute report path when implementing the future harness; preserve its
hash and original-node mapping. Verify the installed version's behavior. No
current script sets up or executes this physical experiment.

Use one persistent session and reusable host-staged tensors. Record creation/
compilation/cache I/O separately where instrumentation permits; otherwise label
combined initialization honestly. Reuse compiled caches only with a compatible
model/runtime/options/compiler/driver/firmware fingerprint.

## H2 — complete-frame service, then bounded concurrency

The checked-in CPU reference structurally derives an11-pixel input halo and
234×234 useful core, global reflection and row-major partial edges. 1280×720 uses
6×4=24 calls and produces2560×1440 at2×. This is **not** the eventual exact
1280×720→3840×2160 production path. Preserve that distinction.

Test in order: one persistent-session tile → one complete24-tile frame →
continuous full frames with one request in flight → two → three only if two is
stable → separately controlled cold/warm session/cache comparisons. Optional
AMD512 model acquisition/characterization is later, not authorized here. Fixed256
cannot accept arbitrary128/192/320/512 shapes.

Define concurrency unambiguously in every manifest: the1/2/3 sweep is maximum
simultaneously submitted **tile inference requests**, not three partially owned
frames or three newly created sessions. Separately record resident/queued frames
and frame assembly ownership. If the installed runtime supports only independent
sessions, record that as a different experiment with its own initialization and
memory costs; do not silently substitute it for same-session requests. The
current native Worker defaults to two slots: do not bypass its bound to claim a
three-request physical experiment. A reviewed future bounded backend change and
supported runtime API are required first.

Capture every tile's frame/session/generation/tile/model identity, submit/start/
completion timestamps; full-frame SUBMITTED→COMPLETED→VALIDATED→CONSUMED,
age, queue depth, peak memory scope, allocation/copy counts, errors and misses.
Do not label consumption as presentation. Distinguish host request duration from
isolated NPU kernel timing. Analyze with existing statistics/availability rules.

| Delivered target (unmeasured) | Period | Sustained24-tile service needed |
| --- | --- | --- |
| 40FPS | 25ms | 960tiles/s |
| 45FPS | 1000/45ms ≈22.222ms | 1080tiles/s |
| 60FPS | 1000/60ms ≈16.667ms | 1440tiles/s |

These are requirements, not predictions. Extra presentation latency cannot
increase sustainable service rate. Promote concurrency only if complete-frame
throughput improves beyond paired run variance without unacceptable p95 frame
age/deadlines/queue growth, memory or GPU interference. Record numerical limits
before acquisition. Tile throughput alone never selects the winner.

## H3 — shared APU budget

R-010 refinement: after stable H1/H2 and separate owner approval, ramp gradually:
NPU alone → modest repeatable Vulkan workload plus NPU → representative game
workload plus NPU. At each GPU level keep a matching GPU-only control and
alternating paired trials. Do not start with maximum GPU/NPU stress or ROCm/HIP
LLM reproductions. Predeclare duration, power/thermal conditions and acceptable
frame-time/queue limits before acquisition; no active test runs automatically.

Abort on the first firmware timeout, reset/context/device loss, stale/wrong output,
GPU disruption, or predeclared thermal/timing/queue limit violation. Stop only
DockSR admission, preserve producer/consumer ownership until actual quiescence,
retain private evidence and leave ordinary gaming independent. Do not restart
the compositor, change power/firmware/driver policy, suspend or reboot as recovery
without separate approval. Successful light-load trials do not pass game load.

Compare A: fixed GPU workload only; B: **identical** GPU workload plus physical
H1/H2-verified background NPU inference, with results discarded; C: integrated
reconstruction **later**. Use matched power settings, source/output, workload,
software, thermal/battery/AC and display conditions; alternating AB/BA trial order,
independent repeated pairs. Warm-up and observation windows must be explicit.

Retain GPU frame-time p50/p95/p99/1%low with existing minimum sample policy,
NPU complete-frame service/age, queue/misses, CPU load, trustworthy clocks,
temperatures, scoped power and firmware/driver errors. Missing or unsupported
sensors remain null; configured TDP is not measured watts. `gpu_metrics` requires
validated ABI/version/length/units before interpretation. Firmware NPU power is
not a separate measured rail. Do not infer whole-device energy from package
readings; charging/discharging contaminates the initial energy protocol.

R-009's reported Strix Halo ROCm+NPU timeout and idle/resume issues are
**COMMUNITY_REPORTED**, not reproduced on Z2 Extreme/SteamOS or ordinary Vulkan
gaming. They justify error capture and stop conditions, not automatic workarounds.
If background NPU work harms gaming enough to outweigh reconstruction benefit,
the system-level gate fails despite excellent isolated NPU throughput.

## H4 — capability ladder, input and output separately

R-010 future **capability-only** probe, after genuine H1 and baseline H2:

1. Record the exact installed ORT/Vitis/device/runtime tuple and existing gate
   evidence. Negotiate a native API supported by that installed build, not a
   development header/version guess. No compatible API/device catalog means
   API_UNAVAILABLE/UNKNOWN, not proof that every Vitis version lacks an importer.
2. Identify the actual Vitis EP device; request its external-resource importer.
   A successful call returning null means IMPORTER_UNAVAILABLE for this tuple.
3. If non-null, query `CanImportMemory` and `CanImportSemaphore` for exact handle
   types in that ABI. Record booleans/status/error availability; never relabel a
   Vulkan DMA_BUF handle as OPAQUE_FD.
4. Release the capability object. Do not allocate/export/import buffers, bind
   tensors, import semaphores or execute inference. No zero-copy stage passes
   from these queries alone. Loading/enumerating an EP may initialize a device,
   so even this future probe needs owner review and is not passive H0 inventory.

No capability-probe code or DMA-BUF integration is added in this amendment.

| Stage | Required distinct proof |
| --- | --- |
| HOST_STAGING | Correct H1 input/output, explicit logical copies/materializations and measured total baseline |
| VULKAN_DMA_BUF_EXPORTED | Exact linear VkBuffer usage/handle/allocation export and independent same-byte check |
| XRT_BO_IMPORTED | Same exported allocation recognized by XDNA/XRT, ownership/lifetime and correct bytes |
| ORT_IMPORTER_AVAILABLE | Installed native API, actual Vitis device returns non-null importer; exact handle/capability supported |
| EXTERNAL_TENSOR_BOUND | Imported allocation is the actual model input/output with shape/stride/offset/lifetime defined |
| ACTUAL_NPU_CONSUMPTION_VERIFIED | H1 evidence while SESR really consumes shared input/produces output, correct against reference, copies investigated |
| SHARED_SYNCHRONIZATION_VERIFIED | Repeated producer/consumer correctness, explicit fences/FD ownership and no early reuse/close |
| END_TO_END_PERFORMANCE_BENEFIT_VERIFIED | Paired total-frame benefit beyond variance against identical host staging, with quality and GPU cost accounted |

Do not pass a later stage while an earlier required stage is unproven. Early
capabilities may be investigated independently, but cannot promote the complete
inference ladder. Use linear buffers first; an optimal-layout image adds modifiers,
planes, pitch and layout. Blocking synchronization is acceptable for initial
correctness. Allocation sharing is not proof of absence of internal shadow copies.

ORT's current source marks interop as since1.24 and explicitly permits a
successful API call to return a **null importer**. Installed Vitis support remains
UNKNOWN; version or Python I/O binding is insufficient. Inspect the actual ABI
and exact handle enum before a future probe; Vulkan OPAQUE_FD and DMA_BUF FDs
are not interchangeable by assertion. If no importer exists, record that boundary
and stop. No custom XRT/IRON backend or unsupported handle workaround here.
Input sharing with copied output must be labeled as such, never full zero-copy.

## Structured failure classification

`scripts/steamos_readiness.py` defines stable codes below; the readiness ledger's
`failures` array carries SUSPECTED/CONFIRMED plus evidence references. Inventory
does not diagnose these automatically. CONFIRMED needs actual device evidence;
community reports cannot confirm a target defect. No code requests a repair.

| Code | First diagnostic layer / action to propose, not execute |
| --- | --- |
| NPU_DEVICE_ABSENT | Host visibility vs container namespace; exact PCI identity |
| DRIVER_NOT_BOUND | Host kernel/config/binding provenance |
| FIRMWARE_MISSING_OR_MISMATCHED | Installed vs loaded firmware and driver pairing |
| XRT_KERNEL_PLUGIN_INCOMPATIBLE | XRT/plugin ioctls and host driver versions |
| MEMLOCK_INSUFFICIENT | Actual process limit and allocation error; no automatic limit change |
| PROVIDER_MISSING | Intended environment/package provenance; do not overwrite AMD ORT with ordinary CPU wheel |
| NO_NPU_OPERATOR_ASSIGNMENT | Actual graph partition/options/compiler report |
| ACTIVE_CONTEXT_MISSING | Execution-window attribution and instrumentation availability |
| MODEL_OUTPUT_MISMATCH | Frozen bytes, preprocessing, output, declared tolerance |
| INFERENCE_TIMEOUT | Bounded stop and private runtime/firmware error evidence |
| GPU_NPU_CONTENTION | Matched H3 timing/power/thermal conditions |
| IDLE_RESUME_INSTABILITY | Runtime/host logs; no automatic suspend/resume stress |
| STEAMOS_UPDATE_REGRESSION | Before/after compatibility tuple, leave NPU disabled |

## R-009 hypotheses

[Machine-readable register](r009-hypotheses.json) preserves HYP-001–012 with
evidence category, baseline, capability, measurement, falsification, stop/go,
hardware dependency, SteamOS-host prerequisite and current NOT_TESTED state.
Source evidence labels describe R-009's rationale, not our measured success.

HYP-001 persistent sessions and010 caching are baseline;002 buffers early;
003 tile shapes after256 characterization;004 stride views conditional;
005 sharing after H4;006 two requests high-priority H2;007 three only after two;
008 assembly measure first;009 trained native3× later;011 lower-level backend
contingency;012 power/deadline admission only after H3. Existing CPU buffer/session
reuse supports host correctness, not any claimed physical AMD performance gain.
