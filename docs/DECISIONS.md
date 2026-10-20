# Current owner decisions

Updated 2026-10-19. This is the implementation decision record; it does not replace private session reports.

## Reading order and authority

The owner explicitly directed us to read the deep-research DOCX first. It has placeholder 1970 creation/modification metadata, and the TXT notes provide dates at most, not reliable times. No intraday chronology is invented. After the DOCX, the text notes were applied in the order presented: R-003, O-002, EGR-001, then the pre-hardware visible-demo addendum v1.1. Execution Handoff v1.2 authorized S004. The later v1.3 requires reconciliation of the missing S004 report before selecting one task, and leaves R-004 architecture proposed only. Approved O-002 targets and the S003→S004→S005 order remain. The referenced v1.0 was not supplied. Actual inspected checkout and explicit owner instructions govern over unverified handoff claims.

| Source | Decision applied | Evidence/limits |
|---|---|---|
| Deep research, read first | Study existing Linux scalers and public NPU sharing; preserve raw data and a cheap GPU resolve. | Research proposals and vendor results are not Dock SR measurements. Prior Microsoft/AMD primary-page access gaps remain unresolved. |
| R-003, proposed experiment | Later compare compact reconstruction CNN against edge-guided correction at matched inputs/output/quality. Before neural implementation, run a pipelined simulator across 40/45/60 FPS, 1–25 ms inference delay and 1/2/3 slots. | Existing mock lifecycle tests are not yet this full timing-grid simulator. S003/S004 priorities unchanged. |
| O-002, approved owner update | Docked first: 720p→4K, 30–35 W selected APU profile, 40/45/60 FPS, universal spatial EGR; incremental NPU power goal <2 W. 95% native-720p FPS retention is a stretch target. | Targets, not measurements or guarantees. Selected power limit is not actual whole-device draw or an isolated NPU sensor. |
| O-002, secondary mode | After docked validation: 720p→1080p at 15–17 W, incremental NPU goal <1 W; lightweight temporal EGR with game metadata where available. | No FSR4.1 requirement on RDNA3.5; metadata injection/stacking is later research, not available from an arbitrary final frame. |
| EGR-001 | Later compare raw reference 3×, post-adaptive sharpening, pre-sharpening, and raw+gradient/high-pass-guided reconstruction. Preserve raw input; use strengths and ablations. | Need held-out 4K ground truth, PSNR/SSIM and artifact/motion checks. Host features are not NPU acceleration. Reject pre-sharpening if controlled evidence does not help. |
| Addendum v1.1, applied last | Finish one bounded S003 functional CPU/Vulkan CLI deliverable now. S004 is the next visible own-window preview/HUD milestone; S005 package/status-only Decky work follows. | No GUI or plugin completion may be claimed by writing a plan or building headless shaders. No drivers, global layers, Gamescope changes or early Intel NPU work. |
| Execution Handoff v1.2 | Implement S004 only: launchable own-window preview, real CPU/Vulkan methods, matched A/B, truthful typed HUD, controls, error handling and executed-window evidence where possible. | Native X11 is the smallest available foundation; SDL3/ImGui were optional suggestions. A virtual X11 window and software Vulkan are distinct from physical-display/GPU validation. No push/publication or driver changes authorized. |
| Execution Handoff v1.3, latest | Selected Task A: finish/verify S004. Preserve the implemented preview and missing-report evidence, complete reproducible checks and report the physical-display blocker. | Authenticated Xvfb execution is verified; a physical interactive display is unavailable. v1.3 explicitly prevents promoting to S005 on this host without that acceptance gate. No S005 package, Decky or research implementation in this session. |

The v1.2 research appendix favors testing compact neural guidance (edge/filter weights, optionally a bounded residual) with cheap GPU reconstruction instead of assuming full 4K RGB tensors are efficient. CARAFE and Meta-SR are conceptual references only, not validated XDNA2 designs or Dock SR results. No research implementation or neural training is included in S004. S005 remains the next non-root smoke-package step after S004 acceptance; Decky integration is deferred by v1.3; the proposed R-003 timing grid must precede serious neural training.

R-004 proposes adaptive 3× polyphase filtering, preserved raw RGB plus signed high-pass/geometry and optional compact NPU guidance. Its RAISR/BLADE/GuideNet rankings are hypotheses, not an approved product architecture. GuideNet arithmetic and guidance payload sizes are workload descriptions, not latency or power estimates. Exact operator placement, shared-buffer inference and CPU fallback must be measured on the actual runtime. Preserve independent matched-sharpness and temporal controls. R-004's source citations do not establish new independent primary-source verification in this checkout. No model/dataset/code is imported. Its reported patent and dataset restrictions remain review checkpoints before a close implementation or distribution; free/noncommercial intent does not itself establish permission.

## Status and publication rules

- Evidence identifies actual CPU, actual physical GPU, software Vulkan, simulation or actual NPU separately. CPU output must never display a GPU-active badge. The suggested status enum is extended with `CPU_REFERENCE_ACTIVE` and software-Vulkan evidence for that reason.
- A processed frame is counted only after completed output; unknown timings remain null. NPU readiness and successful inference are distinct, and this increment cannot activate a real NPU backend.
- Source publication, driver installation and visibility changes require the owner's explicit approval. No remote push or application deployment has been authorized by this update.
- Private session reports stay outside source control. The owner now requests the complete short report inline in chat as well as a `.txt` file.

## Comparison contract

Always separate composed resolution from reconstructed detail. Compare equal source/settings/power, measure native-720p retention independently, and compare quality with higher-resolution ground truth. Windows Auto SR is a reference with OS/driver/device differences recorded, not proven parity. Do not attribute individual NPU watts from unsupported indirect telemetry. The cost-saving MVP still requires a functioning plugin plus a declared, matched-quality comparative efficiency result.
