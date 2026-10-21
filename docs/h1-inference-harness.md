# H1 persistent-session laboratory — DSR014-H

`scripts/h1_probe.py` is a bounded unchanged-SESR experiment, not a native product
backend, installer or presentation hook. It reuses artifact verification,
`CpuReferenceSession` inspection/CPU policy, private writers, SteamOS readiness,
canonical hardware evidence and benchmark analysis. No dependencies are installed.

**Physical execution is NOT_TESTED.** This version can attempt approved Vitis
inference, but does not guess installed compiler/XRT report formats. Successful
candidate runs remain **INCONCLUSIVE** until device-specific placement/context
adapters and attribution are validated. H1 is prepared, not physically passed.

## Model and modes

Only107131 bytes with SHA256
`63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1`
are accepted. Shared inspection rejects external data/custom operators and
unsupported features; signatures must be INT8 NHWC[1,256,256,3] →[1,512,512,3].
No conversion/re-export/shape mutation. This2× probe is not exact720p→4K3×.

Input RGB8 is `(flat_index*37 + seed) mod256`, widened to INT16, minus128 and
converted to signed INT8. Output is widened, plus128, clipped and converted to
RGB8. The integer formula does not depend on a version-specific random generator.

In an existing optional Gate-0 environment, as an ordinary user:

```sh
mkdir -m 700 /tmp/docksr-h1-NEW
python scripts/h1_probe.py --mode cpu-reference --model /ABSOLUTE/verified/model.onnx \
  --output-dir /tmp/docksr-h1-NEW/cpu --warmup 1 --samples 3 --seed 0 --timeout 60
python scripts/validate_gate0.py hardware /tmp/docksr-h1-NEW/cpu/hardware-evidence.json
python scripts/benchmark_analysis.py /tmp/docksr-h1-NEW/cpu/hardware-evidence.json \
  --output /tmp/docksr-h1-NEW/cpu-analysis.json
```

The existing parent must be owner-controlled0700, outside every Git checkout;
new run directory0700, artifacts0600, no overwrite/symlinks/Git destinations.
Use new names and privately preserve `/tmp` evidence before reboot. Necessary
model/runtime paths appear only in private job configuration, not stdout.
Missing dependencies produce BLOCKED. Do not install ordinary CPU ORT over an
AMD environment: that may remove Vitis. Cloud CPU setup is not a SteamOS recipe.

One candidate session is initialized/warmed once and reused across timed requests.
A **second independent CPU session** executes the identical input twice; both
goldens must match bitwise. Each timed candidate result must match exactly under
declared atol=0/rtol=0, with INT16 error arithmetic, validated signature, unchanged
input and no effective-provider change. Old cached output is never a fresh CPU
reference. CPU mode enables only CPUExecutionProvider and can report REAL_CPU only.

## NPU command proposed for separate owner approval

First inspect the actual [SteamOS host](steamos-first-readiness.md). The owner
must separately review/approve the installed runtime and exact active command.
A flag records that decision, not permission in itself. The reviewed ledger must
be DEVICE_INVENTORY, OBSERVED_ON_DEVICE, SteamOS H0 PASS; its inventory must match
this execution environment and an actual PCI amdxdna binding. A fictional ledger
cannot authorize execution. H0 is visibility, not inference proof.

```sh
python scripts/h1_probe.py --mode npu-candidate --model /ABSOLUTE/verified/model.onnx \
  --readiness /ABSOLUTE/private/reviewed-h0.json --approve-physical-run \
  --output-dir /ABSOLUTE/private/NEW-h1 --warmup 1 --samples 3 --timeout 120
```

For separately approved raw context capture, add `--collect-xrt-context`.
It runs `xrt-smi examine --report aie-partitions --format JSON` during the workload;
this may open the device and retain context/process identifiers needed for
attribution. Review privacy scope first. Missing/failed/timed-out queries differ.
Raw success is hashed, **not interpreted as attributable active NPU work**.
No `xrt-smi validate`, broad system logs, setup-script sourcing, privileged changes,
module loading or automatic repairs are invoked.

The runner requests Vitis explicitly, disables runtime fallback retry, requests
`session.disable_cpu_ep_fallback=1`, and checks actual providers after creation
and each request. The installed runtime can reject that strict initial-partition
policy or the model/options: return BLOCKED/FAILED, never retry silently on CPU.

X2, fresh private cache, `enable_cache_file_io_in_mem=0` and private
`XLNX_ONNX_EP_REPORT_FILE` are requested against the reviewed installed AMD version.
The cache/environment identity is retained; cross-run cache reuse is not yet
implemented. File existence cannot establish original critical-node placement.
Provider registration, a created session and correct output are not NPU proof.

## Evidence and classification

The canonical hardware schema accepts optional `h1_run`; legacy records remain
unchanged. It carries run/seed/frame/generation, provider/runtime/options/cache,
preflight fingerprint/reviewed-H0 hash, phase timings, comparisons and raw refs.
The shared validator checks identity/counts, provider/mode, comparison and exact
ns→ms request durations. H1 v1 forbids REAL_NPU and true physical-proof milestones,
even if a caller inserts plausible metadata or simulated report files.

| Observation | Meaning |
| --- | --- |
| CPU_REFERENCE_PASS | Actual CPU candidate agrees with independently executed CPU golden |
| provider_discovered | Registered provider only |
| provider_session_created | Effective provider checked; no placement proof |
| placement_status=RAW_UNVERIFIED | Report retained; NPU_PLACEMENT_EVIDENCE_PRESENT remains false until validated mapping |
| context_status=RAW_UNVERIFIED | Query retained; ACTIVE_XRT_CONTEXT_EVIDENCE_PRESENT remains false until attributable active work |
| cpu_reference_agreement_pass | All measured results equal the separate CPU reference |
| real_npu_verified=false | REAL_NPU_VERIFIED unreachable pending device report adapters/review |
| BLOCKED | Missing model/dependencies/approval/host/provider/session or required setup |
| INCONCLUSIVE | Approved candidate ran correctly; physical evidence still unverified |
| FAILED | Output/provider/signature mismatch, timeout/interruption or worker failure |

Exit codes:0 CPU pass,1 failed,2 blocked,3 inconclusive,124 timeout,130 interrupted.
Argument/output errors return2 without raw private paths or exception text.
Partial artifacts are not completion. Future REAL_NPU promotion must require
validated original-node partitions, matching active XRT context/window, exact
device/runtime identity and independently checked output with no silent CPU-only
fallback. Preserve hashes and review, as required by [H1 gates](hardware-gates-steamos.md).

## Timing, supervision and limits

Lifecycle uses integer host-monotonic nanoseconds; request samples are milliseconds.
Initialization, warmup, input preparation, separate CPU initialization/execution,
comparison, output conversion and artifact writes are distinct. Initialization may
combine compiler/cache/runtime work; compilation, cache loading, internal staging,
isolated provider kernel and final evidence serialization remain null where
unavailable. Do not estimate them by subtraction. Host request duration includes
runtime and visible validation overhead, not pure NPU compute.

The timeout bounds the **entire worker**, including imports/compilation, reference
and artifacts; it is not per-kernel. The isolated child owns sessions. On timeout,
SIGINT or SIGTERM, stop its process group, escalate if necessary and reap before
accepting a failure report. Only the supervisor publishes `hardware-evidence.json`,
after checking the child receipt, raw input/output/reference bytes, hashes, RGB8
conversion and trace identity. `worker-evidence.json` alone is not an accepted
result. A late result is retained as unaccepted. Unconfirmed
quiescence cannot produce success. Reaping user-space does not prove recovery of
a hung accelerator/kernel; do not reset, reload or reboot automatically. This is
not a hostile-runtime sandbox or a guarantee that kernel hangs are killable.

Canonical small-sample quantiles are descriptive nearest-rank values; the existing
analyzer keeps p95/p99 unavailable below20/100 samples. No power or presentation
measurement is performed, and no energy/FPS benefit follows from these timings.

## Minimal H1→H2 boundary

`PersistentTileSession.initialize/run/close` exposes sequential persistent reuse.
A future H2 adapter takes buffers from the existing halo11/core234/24-tile plan
and preserves native session/frame/generation/trace identity and ownership. No
new scheduler, Python/Decky frame transport or native two-slot change is added.

H1 `benchmark_run` declares **one tile per lab item**,256²→512², explicit IDs and
generation, no presentation. Consumption means laboratory inspection. Deadlines
are the supervisor's total-test deadline, not40/45/60FPS scheduling promises.
The observation includes comparison/output work: its rate is not H2 complete-frame
throughput. H2 must group24 correct tiles per source frame, separate calibration
from steady-state acquisition, then investigate1/2/stable3 requests and GPU cost.
