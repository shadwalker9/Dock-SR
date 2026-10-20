# Upstream evidence and dependency scope

Recorded 2026-10-19. These pins identify source review, not a validated target runtime combination. Current owner/task state is in [PROJECT_STATE.md](../docs/PROJECT_STATE.md) and [DECISIONS.md](../docs/DECISIONS.md).

| Project/source | Reviewed revision | What the evidence establishes |
|---|---|---|
| [AMD xdna-driver](https://github.com/amd/xdna-driver/tree/0140477afa9d6bc41e53afc19810d1e0d71336d0) | `0140477afa9d6bc41e53afc19810d1e0d71336d0` | Real native BO import/export, driver attach/map paths and fence semantics. No RADV-origin graph roundtrip was executed. |
| [Paired XRT](https://github.com/Xilinx/XRT/tree/1ea5176dbcdd31bb1cbe035661f1127e2be22574) | `1ea5176dbcdd31bb1cbe035661f1127e2be22574` | Public BO import/run arguments; imported backing preserved in reviewed argument path. Not proof of ONNX EP binding. |
| [Khronos Vulkan-Docs](https://github.com/KhronosGroup/Vulkan-Docs/tree/193ebe195f47ffc5004683d1659e71c725658c4d) | `193ebe195f47ffc5004683d1659e71c725658c4d` | External memory/sync/ownership API contracts. Actual capabilities are queried per selected device. |
| [Linux v6.16](https://github.com/torvalds/linux/tree/038d61fd642278bab63ee8ef722c50d10ab01e8f) | `038d61fd642278bab63ee8ef722c50d10ab01e8f` | Reviewed PRIME import/mmap plumbing, compared with v6.14/v6.15. Kernel version alone does not prove full runtime readiness. |
| [AMD RyzenAI-SW](https://github.com/amd/RyzenAI-SW/tree/43b2dabe4d1bf084d0421953b134707b8cb7275a) | `43b2dabe4d1bf084d0421953b134707b8cb7275a` | Published INT8 SR examples; SESR-M7 is 2×. Separate Windows NPU/iGPU demo supports concurrency as an intended use, not Linux frame-sharing proof. |
| [FidelityFX-FSR](https://github.com/GPUOpen-Effects/FidelityFX-FSR/tree/a21ffb8f6c13233ba336352bdff293894c706575) | `a21ffb8f6c13233ba336352bdff293894c706575` | EASU/RCAS spatial functions and stated 1×–4× area quality range. 720p→4K is 9× area. No FSR shader code is incorporated in this increment. |
| [Gamescope](https://github.com/ValveSoftware/gamescope/tree/74a06ff517ed9fc1307227406bd53ae847be3a91) | `74a06ff517ed9fc1307227406bd53ae847be3a91` | Existing filter/control source. Our manual storage-buffer reference is not an optimized Gamescope scaler. |
| [MAKO](https://github.com/eugeniosegala/MAKO/tree/e933b42fcdf2768c34aa5e921aa6b76da03304c0) | `e933b42fcdf2768c34aa5e921aa6b76da03304c0` | Presentation study; configuration documents 1×–2× scaling. No MAKO code/proprietary LS payload is included or required. |
| [HelixSR](https://github.com/lonewolf0622/HelixSR/tree/2ca54d14110342c6d301703bebad7c62cf792d7d) | `2ca54d14110342c6d301703bebad7c62cf792d7d` | Neural D3D12 implementation described by developer; inference source unpublished. Published pass timing is not our device measurement. |
| [Decky template](https://github.com/SteamDeckHomebrew/decky-plugin-template/tree/90d0780e882a17f5714fc6de044c645f22608290) | `90d0780e882a17f5714fc6de044c645f22608290` | Future TypeScript/React/Python starter shape. No installed plugin or RPC service exists in S003. |

## Inaccessible claims

During onboarding and the subsequent network-state-change retry, direct Microsoft Auto SR blog/support, AMD product/SR/Linux documentation, Hugging Face model-card and original SESR-paper requests were rejected at the proxy with CONNECT 403. Their exact rollout requirements, release-specific Linux support and quoted SR latency/throughput/model-paper figures remain independently unverified here. A supplied research document repeating a claim does not resolve that gap. A preview must not be silently relabeled general release or a Z2 result confused with Snapdragon measurements.

Generic Microsoft Windows ML documentation and accessible AMD sample code do not disclose Auto SR's private topology, quantization, model, wattage or synchronization. O-002's <2 W/<1 W and 95% retention values are owner targets, not findings.

## Build dependencies

- `requirements-dev.lock` pins Python schema-test packages and allows their published artifact SHA-256 values, checked against PyPI release metadata. They are test tooling, not inference dependencies.
- `tools/cloud-packages.lock.json` pins the workspace-only Debian Vulkan/glslang/software-driver bundle using SHA-256 values from archive-keyring-verified APT indexes. The bootstrap preserves HTTPS/checksum verification and does not install system drivers or packages.
- The scaler, scheduler, status and fixtures are original prototype code using standard APIs. No model weights, proprietary inference resources or GUI foundation are bundled.
- S004 must separately review/pin a small UI dependency and its license before adding it. SDL/GLFW/ImGui are candidates, not current dependencies or an already-built preview.

Avoid bulk upstream clones or re-reading historic documents at resumption. Consult a specific source only when it resolves the current bounded implementation question.
