# DSR011 physical NPU probe preparation

**DSR014-H:** the [bounded persistent H1 runner](h1-inference-harness.md) now
implements CPU-reference execution and an owner-approved Vitis candidate attempt.
Physical proof adapters remain pending; a successful candidate is INCONCLUSIVE.

**DSR013-P update:** primary acceptance is now **Z2 Extreme on SteamOS**.
Use [passive SteamOS discovery](steamos-first-readiness.md) first; the legacy
command below includes additional opt-in queries and is not the new minimal
discovery phase. [H0–H4](hardware-gates-steamos.md) adds active-XRT-context proof,
persistent-session concurrency and staged H4 requirements. An Ubuntu reference
installation is not a prerequisite or authorized device change. No target tests
have been run.

The first physical target test uses the **unchanged AMD SESR-M7 tile**, before
custom exact3× models or full-frame throughput. This document prepares that
experiment; no XDNA2 inference, operator placement, graphics sharing or game
presentation has been measured here.

`scripts/npu_probe.py` reuses the existing detector and fixed model verifier.
It only collects read-only inventory and an **unexecuted procedure**. It never
creates an inference session, compiles a model, opens a GPU/NPU memory import,
installs a runtime/driver or emits `REAL_NPU`. Its companion
`npu-probe.schema.json` cannot express a physical success. The existing
[hardware-evidence contract](../schemas/hardware-evidence.schema.json) remains
the document for a later actual measurement; there is no second hardware
attestation format.

## What can run now

Use a new owner-only evidence directory outside every Git checkout:

```sh
mkdir -m 700 /workspace/DockSR-model-cache/device-day-NEW
/workspace/.venvs/docksr-gate0/bin/python scripts/npu_probe.py \
  --model /workspace/DockSR-model-cache/manual-sesr-010/sesr_nhwc_int8_256x256.onnx \
  --inspect-ort \
  --output /workspace/DockSR-model-cache/device-day-NEW/readiness.json
```

Without `--inspect-ort`, no ONNX Runtime module is imported. With it, a bounded
child process queries the installed Python provider list only. A listed Vitis AI
provider cannot set inference/readiness/presentation flags. A missing device
path describes visibility to this process, not necessarily the physical host.
The command skips the graphics probe; it does not repeat DSR010's understood
Vulkan startup failure. Output requires an existing mode0700 parent, is0600,
refuses overwrite/symlink/Git destinations and never exports environment values.

The actual cloud observation is **NOT_RUN** for physical testing: the unchanged
model hash verifies, `/dev/accel` is absent, installed CPU ORT is1.20.1, and its
provider list contains Azure/CPU only. This is inventory, not a failed NPU
benchmark. All four NPU proof fields remain false.

## Source validation and corrections

Retrieved source bytes and exact Git refs are retained privately under
`/workspace/DockSR-planning/evidence/session-011/`; they are not executable
installers or distributed dependencies.

| Claim | Independent observation | Limit |
|---|---|---|
| AMD recommends opset17 | Current [model deployment page](https://ryzenai.docs.amd.com/en/latest/modelrun.html) identifies itself as Ryzen AI1.8.0 and explicitly recommends opset17. Retrieved SHA256 `f9b0525a3f1eedbb7ebae63b20ce08a70afddfce717fba7f6e0d2245235d6126`. | `/latest` is mutable. A direct `/1.8` URL was denied; it was not treated as retrieved. Do not convert the verified SESR opset19 graph. |
| Vitis AI integer target | The same page documents `VitisAIExecutionProvider`, `target=X2` as default on STX/KRK/newer integer backends, and no `xclbin` option on STX/KRK. It lists XINT8/A8W8/A16W8 configurations. | Detect the actual device/runtime before choosing options. A historical1.5 operator table is not proof for installed1.8 binaries or our graph. |
| Official SESR example | [RyzenAI-SW](https://github.com/amd/RyzenAI-SW) HEAD pinned at `43b2dabe4d1bf084d0421953b134707b8cb7275a`; its SR README confirms SESR2×, INT8 and256/512 tile variants. | The published quick-start is Windows/PowerShell oriented. It is not SteamOS/Bazzite deployment acceptance. |
| Compiler-aware tiling | AMD's [2026 SR article](https://www.amd.com/en/developer/resources/technical-articles/2026/super-res-acceleration-on-ryzen-ai-npu.html) describes overlap, on-chip residency/fusion, stride-based buffers and D3D resource examples. Retrieved SHA256 `4ffc27772079bfd448833239da327686b6dbeef7ec18c8833265202f98a389ac`. | Vendor example timings and zero-copy technique are not DockSR/XDNA2/Linux Vulkan results. |
| ImageTilingNPU | [Official repository](https://github.com/amd/ImageTilingNPU) HEAD `6d68513bcf6d5e7dbb6f653d030dfda16fbc7bc6` requires Windows/VisualStudio, says ONNX defaults to CPU unless `--vitisai`, and provides stride/xmodel code. | It does not prove Linux Vulkan→Vitis tensor import. No ZIP/runtime binary was downloaded or installed. |
| DepthToSpace | Official [ONNX source](https://github.com/onnx/onnx/blob/18fb3cfb3b7b2c3f3b05ba9bd3829333432c095d/onnx/defs/tensor/defs.cc) confirms NCHW, DCR default and CRD modes, with explicit reshape/transpose definitions. | Model-contract host execution does not establish NPU compilation or placement. |
| ORT external-resource API | Official [current header](https://github.com/microsoft/onnxruntime/blob/a9bf4811347cc74d9647070e0bfe42866c3f0019/include/onnxruntime/core/session/onnxruntime_c_api.h) marks interop/importer methods as since1.24. Official v1.20.1 commit `5c1b7ccbff7e5141c1da7a9d963d660e5741c319` declares API_VERSION20 and has no OrtInteropApi. | Our CPU1.20.1 wheel is not a modern external-import probe. No provider importer or handle was queried. |
| Historical FSR4 source | Exact official Git fetch verifies commit `01446e6a74888bf349652fcf2cbf5f642d30c2bf`, subject AMD FidelityFX SDK2.0.0, and an `fsr4` tree. Current GPUOpen pages describe signed FSR APIs and temporal color/depth/motion/jitter inputs. | No model/initializer files were extracted or reused. Historical source presence grants no assumption about current weights or XDNA deployment. |

Two arithmetic corrections matter before device measurements:

- R-007's generic `Conv(3×3×r²)` notation is wrong for RGB. The final channel
  count is `C×r²`; for RGB and3× it is27, matching the controlling handoff.
- The handoff's direct-payload bandwidth table is slightly inconsistent with
  its own byte counts. Input+output is27,648,000 B/frame. At40/45/60 FPS the
  exact logical totals are1,105,920,000 /1,244,160,000 /1,658,880,000 B/s
  (1.10592/1.24416/1.65888 GB/s), not the printed1.106304/1.244592/1.659456.
  These remain logical arithmetic, not measured DDR traffic.

## Device-day sequence

1. **Inventory first.** Record exact APU marketing/model identity and PCI IDs,
   kernel/OS, `/dev/accel`, bound `amdxdna` driver and version, firmware,
   `xrt-smi --version`, installed runtime distribution/version and supported
   execution providers. Preserve permission errors separately from absence.
   Verify support for this exact device/OS/runtime. Do not install Ubuntu
   packages into SteamOS/Bazzite or change drivers as part of this procedure.
2. **Freeze original bytes.** Verify107131 bytes and model SHA256
   `63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1`.
   Preserve the unchanged INT8 NHWC tile input and CPU reference output hashes,
   model source revision and inspected node names. No graph conversion is
   allowed to turn a failed compatibility probe into a pass.
3. **Declare comparison policy before running.** For the initial fixed INT8
   graph, start with exact output equality (`atol=0,rtol=0`), using INT16 for
   error subtraction to avoid INT8 overflow. If rounding/fusion changes values,
   retain mismatch statistics and investigate. Any relaxed tolerance needs an
   independent numerical justification declared before a new acceptance run;
   do not silently loosen it until a result passes. This is correctness, not
   image-quality acceptance.
4. **Request the documented provider.** In the supported installed AMD
   environment, request only `VitisAIExecutionProvider` with documented
   `target=X2` on the verified supported family. Record the effective options,
   exact runtime version and private compiler/cache paths. Provider registration
   and `get_providers()` are metadata, not placement proof.
5. **Separate initialization from steady state.** Use a new private cache for
   cold creation, then separately test reuse of that exact compiled cache.
   Record model/runtime/options plus all cache file hashes. A single measured
   session-creation call may combine initialization, compilation and cache I/O;
   label it combined unless provider instrumentation separates those costs.
   Never label the combined duration as pure compilation.
6. **Run the unchanged reference tile.** Keep RGB-minus128 preprocessing and
   unchanged NHWC strides. Preserve output shape/dtype/hash, CPU-reference
   comparison and input-after-run hash. Warm up separately, then collect enough
   successful warm samples (e.g.100) to report meaningful nearest-rank
   p50/p95/p99. Host wall-clock `session.run` is submit-to-return including
   staging/provider work, not an isolated NPU-kernel timer.
7. **Prove placement and fallback.** Enable documented runtime/compiler logs
   and ORT profiling before session creation. Preserve graph partition and
   compiler reports mapping original critical Conv/reconstruction nodes to
   physical NPU subgraphs. An ORT profile may show a fused provider node without
   proving every original operator's placement; preserve the mapping too.
   Record critical NPU/CPU/unassigned counts. `disable_fallback()` stops runtime
   EP-error fallback, not initial CPU graph partitioning. Observe CPU partitions
   honestly; a full CPU result with a listed Vitis provider is a failed NPU gate.
8. **Create actual hardware evidence.** Populate
   `hardware-evidence.schema.json`, including exact target identity, original
   model/input/reference/output hashes, `operator_assignment`, actual successful
   samples and measurement provenance. Run `scripts/validate_gate0.py hardware`
   on that file. Schema validity itself does not attest the observations.
   A self-test still cannot set `npu_game_frames_consumed`: no presentation has
   happened. Full-frame/concurrent-GPU/game tests are later, independent gates.

Useful read-only commands are the existing `scripts/npu_probe.py` above,
`uname -sr`, reading `/etc/os-release`, inspecting device/driver sysfs, and
`xrt-smi --version` where installed. Activate the supported target environment
before asking Python for provider metadata; do not use the cloud CPU venv as
an AMD-runtime installation recipe.

The following shows the supported session request shape. It is **device-day
preparation, NOT_RUN here**; paths and device/runtime checks must be established
first. It does not print a physical-success badge:

```python
import hashlib
from pathlib import Path
import onnxruntime as ort

model = Path('/private/verified/sesr_nhwc_int8_256x256.onnx')
model_hash = hashlib.sha256(model.read_bytes()).hexdigest()
assert model.stat().st_size == 107131
assert model_hash == '63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1'
assert 'VitisAIExecutionProvider' in ort.get_available_providers()
# Precondition: actual device/runtime supports the current documented X2 path.
cache = Path('/private/new-model-cache')
cache.mkdir(mode=0o700)  # New directory: do not reuse an unknown compiled cache.
options = ort.SessionOptions()
options.enable_profiling = True
options.profile_file_prefix = str(cache / 'ort-profile')
options.log_severity_level = 0
provider_options = {'target': 'X2', 'cache_dir': str(cache),
                    'cache_key': model_hash, 'enable_cache_file_io_in_mem': '0'}
session = ort.InferenceSession(str(model), sess_options=options,
    providers=['VitisAIExecutionProvider'], provider_options=[provider_options])
session.disable_fallback()  # Does NOT prove or prohibit CPU graph partitioning.
# Run unchanged, verified tile input; collect partition/compiler/profile/output
# evidence and validate it before any physical-inference claim.
```

A real target implementation must retain the existing bounded input/model
validation, safe output publication and tensor checks. This short API example
is not a replacement generic model runner or a hostile-model sandbox.

## Optional external-memory capability ladder

Do not rebuild the AMD stack or implement zero-copy during this milestone.
On an installed runtime exposing the appropriate native API, record each step
independently:

| Stage | Possible observation | Does not prove |
|---|---|---|
| ORT native interop API | API_UNAVAILABLE / API_AVAILABLE / UNKNOWN | EP supplies an importer |
| EP resource importer | IMPORTER_UNAVAILABLE / IMPORTER_AVAILABLE / NOT_RUN | Linux DMA-BUF handle supported |
| Handle type | UNSUPPORTED / SUPPORTED / NOT_RUN | Import succeeds |
| Actual memory import | FAILED / SUCCEEDED / NOT_RUN | Inference consumed it |
| Bound inference | NOT_CONSUMED / CONSUMED / NOT_RUN | Graphics synchronization/coherency or presented result |
| Vulkan↔XRT sharing | Separate actual allocation/import/sync test | Vitis AI can bind that allocation as a tensor |

The optional API may return no EP importer. A generic ORT document, an XRT BO
import or a Vulkan DMA-BUF extension does not establish Vitis AI tensor binding.
The preparation command reports native API `UNKNOWN`, all actual import/query
stages `NOT_RUN` and `zero_copy_verified=false`; it deliberately does not infer
native C ABI capability from a missing Python binding or provider version.
