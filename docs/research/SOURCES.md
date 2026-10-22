# Primary-source register

[Research hub](README.md) | [Consensus](CONSENSUS.md)

Initial access/review date: **2026-10-21**; R-010 additions below: **2026-10-22**.
Exact pinned source was inspected during project
work; mutable documentation can change. This is a documentary register, not a
claim that an API executed on the target device. Refer to each exact installed
version before testing. No private paper, internal path or operational artifact
is linked here. Original R-008 is missing; later outlines are not its source.

| ID | Title / organization / public URL | Version or revision | Decisions supported / limitations |
| --- | --- | --- | --- |
| S-001 | AMD, [Model Compilation and Deployment](https://ryzenai.docs.amd.com/en/latest/modelrun.html) | Page identified Ryzen AI1.8.0 when retrieved; mutable latest | C-004/005/006: Vitis/X2, caching and operator reports. Supported reference documentation does not prove SteamOS support, installed options or zero-copy. |
| S-002 | AMD, [Linux installation](https://ryzenai.docs.amd.com/en/latest/linux.html) and [NPU management](https://ryzenai.docs.amd.com/en/latest/xrt_smi.html) | Ryzen AI1.8.0 when retrieved; mutable latest | C-001/006/012: host/runtime layers, platform/context diagnostics. Ubuntu-named packages are not a SteamOS install recipe; validate is active, not passive inventory. |
| S-003 | AMD, [SESR example](https://github.com/amd/RyzenAI-SW/blob/43b2dabe4d1bf084d0421953b134707b8cb7275a/CNN-examples/super-resolution/README.md) and [model card](https://huggingface.co/amd/sesr-m7-256x256-tiles-amdnpu/tree/edbe46281e894e31da3f42aa353db1e04a50f00a) | Example43b2dabe4d1bf084d0421953b134707b8cb7275a; model edbe46281e894e31da3f42aa353db1e04a50f00a | C-006: separate fixed256/512 2× INT8 artifacts. Exact bytes checked separately; vendor benchmark is not DockSR throughput; model/runtime licenses separate. |
| S-004 | AMD, [XDNA driver README](https://github.com/amd/xdna-driver/blob/bc5dd96b6a11fcdba0884c492f897c9e6ed5aa79/README.md); Xilinx/AMD, [XRT native APIs](https://xilinx.github.io/XRT/master/html/xrt_native_apis.html) | Driver bc5dd96b6a11fcdba0884c492f897c9e6ed5aa79; XRT master docs mutable | C-009/012: driver/plugin/firmware/memlock coupling and BO sharing. Arch/Fedora packaging and BO import do not prove SteamOS/Vitis tensor binding. |
| S-005 | Microsoft, [ONNX Runtime C API](https://github.com/microsoft/onnxruntime/blob/a926b837fb8a39b0e4840fcb997ff1336cdf5db1/include/onnxruntime/core/session/onnxruntime_c_api.h) | a926b837fb8a39b0e4840fcb997ff1336cdf5db1, development API32 | C-009: optional importer may return null; exact handle types and Linux DMA-BUF TODO. Development HEAD is not installed/released AMD runtime; host CPU1.20.1 lacks this API. |
| S-006 | Intel/OpenVINO, [NPU inference-request design](https://github.com/openvinotoolkit/openvino/blob/5f6bbdfdf4667cc39415a469449343494dc986f2/src/plugins/intel_npu/docs/inference-request.md) | 5f6bbdfdf4667cc39415a469449343494dc986f2 | C-005/009/010: allocation/context identity, reuse, synchronization and shadow copies. Intel Level Zero implementation is conceptual guidance, not AMD support evidence. |
| S-007 | Valve, [Gamescope](https://github.com/ValveSoftware/gamescope/tree/4d5b7f3c9e1b6d3ee41c5c460b835fe5e0fe71b3) | Existing DockSR experiment pin4d5b7f3c9e1b6d3ee41c5c460b835fe5e0fe71b3 | C-008/011: compositor ownership, render/output boundary and composition cost. Our linked lab builds; no exact-path runtime or neural-frame proof. |
| S-008 | Shi et al., [Real-Time Single Image and Video Super-Resolution Using an Efficient Sub-Pixel Convolutional Neural Network](https://arxiv.org/abs/1609.05158); ONNX, [DepthToSpace](https://onnx.ai/onnx/operators/onnx__DepthToSpace.html) | ESPCN2016; ONNX operator docs mutable, code reviewed at18fb3cfb3b7b2c3f3b05ba9bd3829333432c095d | C-007: low-resolution features and final rearrangement; DCR/CRD semantics. Architectural principle is not proof of target quality or INT8 compilation. |
| S-009 | AMD, [Super Res Acceleration on Ryzen AI NPU](https://www.amd.com/en/developer/resources/technical-articles/2026/super-res-acceleration-on-ryzen-ai-npu.html); [ImageTilingNPU](https://github.com/amd/ImageTilingNPU/tree/6d68513bcf6d5e7dbb6f653d030dfda16fbc7bc6) | 2026 article; repository6d68513bcf6d5e7dbb6f653d030dfda16fbc7bc6 | C-005/006/009: locality/tiling, subviews and Windows-oriented shared resources. Not Linux Vulkan-to-Vitis proof or a DockSR performance prediction. |
| S-010 | Khronos, [Vulkan external-memory DMA-BUF](https://docs.vulkan.org/refpages/latest/refpages/source/VK_EXT_external_memory_dma_buf.html) and [external-semaphore FD](https://docs.vulkan.org/refpages/latest/refpages/source/VK_KHR_external_semaphore_fd.html) | Mutable specification | C-009: distinguish allocation sharing from synchronization and exact handle support; requires actual usage/device/driver capability tests. |

The research papers are project inputs, not new rights grants. We use original
summaries and public citations rather than redistribute report bodies, weights,
figures or vendor software. Formal DockSR licensing remains pending. External
source visibility alone does not authorize reuse; review applicable component,
model, runtime and dataset terms separately. License/contribution policy and
owner approval are prerequisites for a responsible future public release.

## R-010 amendment sources — reviewed2026-10-22

| ID | Title / organization / public URL | Version/revision | Evidence and limitations |
| --- | --- | --- | --- |
| S-011 | AMD, [Triton-XDNA README](https://github.com/amd/Triton-XDNA/blob/b0ecabc1916d32b2242865ca6e563c8508372665/README.md) | Paper pin b0ecabc1916d32b2242865ca6e563c8508372665, retrieved2026-10-22 | Source documents experimental XRT/HSA paths, HSA/HIP shared pages, staging counters/pooling. Mapping timings are PROJECT_AUTHOR_REPORTED, not DockSR measurements or Vulkan compatibility. Current upstream HEAD has moved. |
| S-012 | AMD, [IRON](https://github.com/amd/IRON/blob/b3ba3cf3a138c21e021d5ee2d6794573cd7a3287/README.md) | b3ba3cf3a138c21e021d5ee2d6794573cd7a3287 | Verified source describes close-to-metal NPU programming; conditional low-level fallback, not installed and not a turnkey SESR/ONNX backend. |
| S-013 | Project author, [xdna-engine](https://github.com/atassis/xdna-engine/blob/5489d40fcfd14497650f293821a9c81a1f8b3c93/README.md) | 5489d40fcfd14497650f293821a9c81a1f8b3c93 | Author reports Linux ESPCN/EDSR and CPU-oracle checks on Ryzen AI9465. No DockSR reproduction. Root license does not resolve the paper-reported component-license discrepancy; no code/weights adopted. |
| S-014 | Craig Chandler, [Ryzen AI on Arch/CachyOS](https://github.com/craigchandler/ryzen-ai-arch/blob/5eb7e6cf20aefedd8b2cd59030d45e0b39aea6d2/README.md) | 5eb7e6cf20aefedd8b2cd59030d45e0b39aea6d2 | COMMUNITY_REPORTED Ryzen AI1.8/ORT1.27.0/Vitis with in-tree driver; different hardware and transformer-derived workload/CPU partitions. Its compatibility/security/installation changes are not approved SteamOS instructions. |
| S-015 | AMD, [Adrenalin26.10.1 release notes](https://www.amd.com/en/resources/support-articles/release-notes/RN-RAD-WIN-26-10-1.html) | Mutable page retrieved2026-10-22 | Primary notes identify Windows packages and exclude generic handheld support in favor of OEM drivers. Not SteamOS FSR/Vitis support; broader eligibility/performance claims were not independently established here. |
| S-016 | systemd, [manager D-Bus properties](https://github.com/systemd/systemd/blob/v258/src/core/dbus-manager.c) | v258, DefaultLimitMEMLOCK/Soft read from Manager.defaults.rlimit | Supports read-only default-limit query. Defaults differ from actual running-unit limits, manager process hard cap and explicit overrides; no limit change prescribed. |
| S-017 | Microsoft/ORT, [generic Vitis provider page](https://onnxruntime.ai/docs/execution-providers/Vitis-AI-ExecutionProvider.html) | Access attempt2026-10-22 unavailable | R-010 reports a Ryzen-Linux support-table conflict with AMD1.8 docs. This amendment could not retrieve that page; conflict remains RESEARCH_REPORTED_NOT_RECHECKED. AMD's Linux quicktest documentation was independently retrieved. |

The pinned XDNA README in S-004 was re-read: Arch package names support only a
local `pacman -Q` inventory, never installation. AMD's Linux documentation was
also re-read and explicitly describes compiling/running a CNN quicktest. Exact
retrieved-byte hashes are in [upstream notes](../../notes/UPSTREAM.md). No source
text, installation script, binary, model or private research body was copied.
