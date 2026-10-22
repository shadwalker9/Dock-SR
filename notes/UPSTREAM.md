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

## DSR012-P Linux deployment research (2026-10-21)

Current source pins supplement the historical notes above. Retrieved AMD1.8.0
Linux/model/XRT documentation supersedes those specific earlier access failures;
no target runtime or physical compatibility was tested. Official Valve FAQ and
Bazzite web requests remained CONNECT403. Bazzite's public Git documentation was
read at its pinned revision; no proxy/access controls were bypassed. R-008 was
not supplied. Raw source bytes/hashes and failed lookups are retained outside Git.

| Source | Exact revision | Reviewed purpose |
| --- | --- | --- |
| [AMD xdna-driver](https://github.com/amd/xdna-driver/tree/bc5dd96b6a11fcdba0884c492f897c9e6ed5aa79) | `bc5dd96b6a11fcdba0884c492f897c9e6ed5aa79` | README: host driver, matching firmware/XRT plugin, Arch/Fedora paths and memlock |
| [Valve Gamescope](https://github.com/ValveSoftware/gamescope/tree/aa289ea5977d8b21b92b0f246f0e8f0c225d180f) | `aa289ea5977d8b21b92b0f246f0e8f0c225d180f` | README: nested/embedded design; not installed SteamOS identity or a patch update |
| [Valve SteamOS](https://github.com/ValveSoftware/SteamOS/tree/25e4843add550be450da0cdae9955926b01df4f2) | `25e4843add550be450da0cdae9955926b01df4f2` | README: official repair/recovery links; tracker is not a shipping package tree |
| [SteamOS kernel public ref](https://github.com/ValveSoftware/steamos_kernel/tree/798b216f18cf4d6c605503baf7e4329efd343f24) | `798b216f18cf4d6c605503baf7e4329efd343f24` | README/ref checked; guessed amdxdna path404, no shipping-device conclusion |
| [Bazzite](https://github.com/ublue-os/bazzite/tree/4be65019183f50b1d4805a09037c47a2f8dfd43f) | `4be65019183f50b1d4805a09037c47a2f8dfd43f` | README/Containerfile: image and Atomic context |
| [Bazzite docs](https://github.com/bazzite-org/docs.bazzite.gg/tree/a0ac868202675862fd1f41b218964bf3abc08758) | `a0ac868202675862fd1f41b218964bf3abc08758` | Gaming Mode, layering, rollback, Flatpak and Distrobox pages |
| [Community session](https://github.com/ChimeraOS/gamescope-session/tree/73d2da84ace7f41006a0f85bd2fdb19ef593a464) | `73d2da84ace7f41006a0f85bd2fdb19ef593a464` | Launcher, user unit and session shell; not Valve shipping-session proof |
| [Decky loader](https://github.com/SteamDeckHomebrew/decky-loader/tree/00cd202872b85868071b041c8f1b34e734147195) | `00cd202872b85868071b041c8f1b34e734147195` | Plugin process and sandbox UID handling |
| [Decky template](https://github.com/SteamDeckHomebrew/decky-plugin-template/tree/90d0780e882a17f5714fc6de044c645f22608290) | `90d0780e882a17f5714fc6de044c645f22608290` | callable frontend/backend boundary, original Python example |
| [Flatpak docs](https://github.com/flatpak/flatpak-docs/tree/1017976c15fe847c48603de9301d873aeb77b197) | `1017976c15fe847c48603de9301d873aeb77b197` | docs/sandbox-permissions.rst: devices/display/bus/filesystem permissions |
| [Distrobox](https://github.com/89luca89/distrobox/tree/24035a6dd11d0ec2f88ee46a8a4b89876d62c56b) | `24035a6dd11d0ec2f88ee46a8a4b89876d62c56b` | docs/README.md and compatibility: host integration, rootless/security limits |

Mutable upstream documents retrieved and byte-identified this session:

- [amd-linux](https://ryzenai.docs.amd.com/en/latest/linux.html): SHA256 `72c93f258e0ee34ecfecc76392efe3952b625417222a36aec3816f1ffc0389b7`, 38574 bytes.
- [amd-modelrun](https://ryzenai.docs.amd.com/en/latest/modelrun.html): SHA256 `f9b0525a3f1eedbb7ebae63b20ce08a70afddfce717fba7f6e0d2245235d6126`, 80263 bytes.
- [amd-xrt-smi](https://ryzenai.docs.amd.com/en/latest/xrt_smi.html): SHA256 `e0c767c30108c4e26b6d313768138d64290f2b5b6a3d35a8b95ad96ae5dc93c4`, 45166 bytes.
- [amdgpu-hwmon](https://docs.kernel.org/gpu/amdgpu/thermal.html): SHA256 `586bb3c1db5c5b5633aafa15f027612eca0783fbef4737149eb0205943f059e2`, 38182 bytes.

## DSR013-P / R-009 bounded source reconciliation — 2026-10-21

Exact HEAD refs were independently queried and the following source bytes read;
raw files/manifests remain outside Git. No upstream code, runtime, model, installer
or report was copied into this change. Source facts are not target measurements.

| Repository and exact source | Revision | Retrieved SHA256 / finding |
| --- | --- | --- |
| microsoft/onnxruntime, include/onnxruntime/core/session/onnxruntime_c_api.h | `a926b837fb8a39b0e4840fcb997ff1336cdf5db1` | `28b7bf042aec952a7e20769409f26d642b6e7a9eea04ad8cba4883123a4c727d`; OrtInteropApi since1.24, optional importer may return null successfully; Linux DMA-BUF TODO and separate opaque-FD enum |
| openvinotoolkit/openvino, src/plugins/intel_npu/docs/inference-request.md | `5f6bbdfdf4667cc39415a469449343494dc986f2` | `9f5b6521e04eeda7134ed50984542443f8f58e3fc3b6a958f248b40f788dc774`; context-bound allocation tracking, reuse, shadow copies and Linux DMA-BUF remote tensors are Intel design references |
| amd/xdna-driver, README.md | `bc5dd96b6a11fcdba0884c492f897c9e6ed5aa79` | `87565ad20ca0034bc4d82e072bfefe403d08c63234ebb079a48e13308045dd7c`; host kernel/config/firmware/XRT/memlock coupling and Arch/Fedora packaging are not SteamOS acceptance |
| amd/RyzenAI-SW, CNN-examples/super-resolution/README.md | `43b2dabe4d1bf084d0421953b134707b8cb7275a` | `95c9ae379127ba47688175bd1783e6509b04fa2d8149d929118e787500d1e7cf`; fixed256/512 models separate; no Linux Vulkan-to-Vitis inference proof |

The fetched ORT main header declares API_VERSION32. That development header is
not proof of a released package or the installed AMD build; do not adopt R-009's
"current release1.31" as a tested runtime requirement. Existing CPU ORT1.20.1
cannot probe the newer API. Vitis external-resource importer availability remains
UNKNOWN, not disproved by a missing Python interface. Exact handle types must be
queried; do not relabel DMA_BUF as OPAQUE_FD.

AMD1.8 model deployment/linux source and pins from DSR012-P remain applicable to
the supported reference only. R-009's Ubuntu-first recommendation is superseded
by the owner's v2.2 SteamOS-first direction, not by a newly verified Valve support
claim. No new Valve recovery/SteamOS kernel assertion is made. Community Strix
Halo/ROCm and idle/resume reports remain unreplicated on the target; no suggested
host repair was applied. Intel source is studied conceptually, not added as an
AMD dependency. Model/runtime/component licenses remain separate unresolved
shipping reviews; no project license selected.

## R-010 amendment source review — 2026-10-22

Source inspection only; no downloaded code/installers executed. SHA-256 below
identifies retrieved bytes, not a reproduced workload or target compatibility.

| Source | Pinned revision / document | Retrieved SHA-256 |
| --- | --- | --- |
| amd/Triton-XDNA README.md | `b0ecabc1916d32b2242865ca6e563c8508372665` (paper snapshot) | `14a1100870c6a69b4007c7c7abdc973b3759754e291a4a8eff51b456927d60be` |
| amd/IRON README.md | `b3ba3cf3a138c21e021d5ee2d6794573cd7a3287` | `d550fe018aec9d8eb6f049ff9c3dcabe8ab148be66d9f2165f697c216a54d1f2` |
| atassis/xdna-engine README.md | `5489d40fcfd14497650f293821a9c81a1f8b3c93` | `98e592955733b5364595b4ae186da7055e16e4b26008cd6daaf6586d76b62f11` |
| craigchandler/ryzen-ai-arch README.md | `5eb7e6cf20aefedd8b2cd59030d45e0b39aea6d2` | `849529444240c94a09c65d8e1fbd531888e3ce27564df8738f3260698b5c5c5a` |
| amd/xdna-driver README.md | `bc5dd96b6a11fcdba0884c492f897c9e6ed5aa79` (unchanged) | `87565ad20ca0034bc4d82e072bfefe403d08c63234ebb079a48e13308045dd7c` |
| AMD Linux documentation | 1.8.0; mutable page re-read | `4c19e889fd50f3f88017803a7ac79aab7d55ced5ecc73954d6aa9b9cb3372d13` |
| AMD Adrenalin release notes | 26.10.1; mutable page | `318e0c2c0dcff2ce58a163cb6a9142c66f88420b3187a121500a11d7c9aa696a` |
| systemd src/core/dbus-manager.c | tag `v258` | `e182de0dd3da33780c338af5b89a1ec1c6c4c3f5d3015b96b546d07b022a41b4` |

Triton-XDNA HEAD queried as `9076c11c455830fe65fabf007cb6471a885e5f97`;
the paper-pinned revision above was reviewed instead of silently substituting HEAD.
HSA/HIP sharing and author mapping timings do not prove a Vulkan/Vitis importer.
Arch package names support passive local-database queries only; compatibility
patches/security changes are not a SteamOS procedure. Systemd properties describe
manager defaults, not actual running-unit/process limits.

The generic ORT Vitis documentation page could not be retrieved, and its attempted
raw-repository alternative returned404. The paper's Windows-table discrepancy is
RESEARCH_REPORTED_NOT_RECHECKED. The xdna-engine component tree was unavailable;
its reported root/SR license conflict remains unresolved. No exact shipping
SteamOS kernel or SteamOS FSR eligibility is established by this review.
