# Current owner decisions

Updated 2026-10-19. This is the implementation decision record; it does not replace private session reports.

Current directive: **v1.6 model validation, conditional R005-G0B-1 simulation and project mission**. Earlier entries preserve the decisions and next-task suggestions at their original stage; the appended v1.6 entry governs current scope.

## Reading order and authority

The owner explicitly directed us to read the deep-research DOCX first. It has placeholder 1970 creation/modification metadata, and the TXT notes provide dates at most, not reliable times. No intraday chronology is invented. After the DOCX, the text notes were applied in the order presented: R-003, O-002, EGR-001, then the pre-hardware visible-demo addendum v1.1. Execution Handoff v1.2 authorized S004. v1.3 required reconciliation before advancement; the latest v1.4 explicitly permits S005-PRE safe preparation while S004 physical acceptance remains pending. Approved O-002 requirements remain. Only the short v1.4 assignment was supplied; its reference to a longer Kepler handoff does not establish that file was read. Referenced v1.0 was not supplied. Actual inspected checkout and explicit owner instructions govern over unverified handoff claims.

| Source | Decision applied | Evidence/limits |
|---|---|---|
| Deep research, read first | Study existing Linux scalers and public NPU sharing; preserve raw data and a cheap GPU resolve. | Research proposals and vendor results are not Dock SR measurements. Prior Microsoft/AMD primary-page access gaps remain unresolved. |
| R-003, proposed experiment | Later compare compact reconstruction CNN against edge-guided correction at matched inputs/output/quality. Before neural implementation, run a pipelined simulator across 40/45/60 FPS, 1–25 ms inference delay and 1/2/3 slots. | Existing mock lifecycle tests are not yet this full timing-grid simulator. S003/S004 priorities unchanged. |
| O-002, approved owner update | Docked first: 720p→4K, 30–35 W selected APU profile, 40/45/60 FPS, universal spatial EGR; incremental NPU power goal <2 W. 95% native-720p FPS retention is a stretch target. | Targets, not measurements or guarantees. Selected power limit is not actual whole-device draw or an isolated NPU sensor. |
| O-002, secondary mode | After docked validation: 720p→1080p at 15–17 W, incremental NPU goal <1 W; lightweight temporal EGR with game metadata where available. | No FSR4.1 requirement on RDNA3.5; metadata injection/stacking is later research, not available from an arbitrary final frame. |
| EGR-001 | Later compare raw reference 3×, post-adaptive sharpening, pre-sharpening, and raw+gradient/high-pass-guided reconstruction. Preserve raw input; use strengths and ablations. | Need held-out 4K ground truth, PSNR/SSIM and artifact/motion checks. Host features are not NPU acceleration. Reject pre-sharpening if controlled evidence does not help. |
| Addendum v1.1, applied last | Finish one bounded S003 functional CPU/Vulkan CLI deliverable now. S004 is the next visible own-window preview/HUD milestone; S005 package/status-only Decky work follows. | No GUI or plugin completion may be claimed by writing a plan or building headless shaders. No drivers, global layers, Gamescope changes or early Intel NPU work. |
| Execution Handoff v1.2 | Implement S004 only: launchable own-window preview, real CPU/Vulkan methods, matched A/B, truthful typed HUD, controls, error handling and executed-window evidence where possible. | Native X11 is the smallest available foundation; SDL3/ImGui were optional suggestions. A virtual X11 window and software Vulkan are distinct from physical-display/GPU validation. No push/publication or driver changes authorized. |
| Execution Handoff v1.3 | Selected Task A for that session: finish/verify S004 and reconcile missing reports. | Authenticated Xvfb evidence did not establish physical-display acceptance. Its advancement restriction is superseded only by v1.4's explicit S005-PRE authorization. |
| Execution Handoff v1.4, latest | Implement S005-PRE: non-root relocatable smoke package, real CPU self-test/status, private diagnostics, packaging tests and device-day/maintainer instructions. | S004 is not physically validated. No Decky, neural filtering, NPU inference, game integration or system-driver work. Propose EGR-001/R-004 offline testing afterward; do not start it. |
| Owner's accompanying v1.4 chat | Commit and push reviewed source to the existing GitHub repository for backup. | Explicit authorization supersedes the attachment's default no-push restriction. Preserve visibility; exclude reports, attachments, generated captures and private data. No release/deployment authorized. |

The v1.2 research appendix favors testing compact neural guidance (edge/filter weights, optionally a bounded residual) with cheap GPU reconstruction instead of assuming full 4K RGB tensors are efficient. CARAFE and Meta-SR are conceptual references only, not validated XDNA2 designs or Dock SR results. No research implementation or neural training is included in S004/S005-PRE. Decky remains deferred; the proposed R-003 timing grid must precede serious neural training.

R-004 proposes adaptive 3× polyphase filtering, preserved raw RGB plus signed high-pass/geometry and optional compact NPU guidance. Its RAISR/BLADE/GuideNet rankings are hypotheses, not an approved product architecture. GuideNet arithmetic and guidance payload sizes are workload descriptions, not latency or power estimates. Exact operator placement, shared-buffer inference and CPU fallback must be measured on the actual runtime. Preserve independent matched-sharpness and temporal controls. R-004's source citations do not establish new independent primary-source verification in this checkout. No model/dataset/code is imported. Its reported patent and dataset restrictions remain review checkpoints before a close implementation or distribution; free/noncommercial intent does not itself establish permission.

## Status and publication rules

- Evidence identifies actual CPU, actual physical GPU, software Vulkan, simulation or actual NPU separately. CPU output must never display a GPU-active badge. The suggested status enum is extended with `CPU_REFERENCE_ACTIVE` and software-Vulkan evidence for that reason.
- A processed frame is counted only after completed output; unknown timings remain null. NPU readiness and successful inference are distinct, and this increment cannot activate a real NPU backend.
- The owner explicitly authorized this session's source backup/push. Future publication follows the scope of that instruction; driver installation, visibility changes, release and application deployment remain unauthorized. Private data must remain outside every source push.
- Private session reports stay outside source control. The owner now requests the complete short report inline in chat as well as a `.txt` file.

## Comparison contract

Always separate composed resolution from reconstructed detail. Compare equal source/settings/power, measure native-720p retention independently, and compare quality with higher-resolution ground truth. Windows Auto SR is a reference with OS/driver/device differences recorded, not proven parity. Do not attribute individual NPU watts from unsupported indirect telemetry. The cost-saving MVP still requires a functioning plugin plus a declared, matched-quality comparative efficiency result.

## v1.5 — R-005 Gate-0A adoption (2026-10-19 America/Chicago)

The owner directed R-005 to be read first, then the full v1.5 handoff, and authorized its bounded Gate-0A assignment. Identical reuploads do not supersede that scope. The handoff's footer says v1.4; its filename/header and requested milestone identify it as v1.5.

- Implement provenance/dependency metadata, ONNX inspection, deterministic CPU reference and a separate future hardware-evidence schema. Existing runtime status/clients remain unchanged and cannot activate a real NPU.
- SESR-M7-256 is a proposed first physical inference-proof model, not an approved final game scaler. Exact revision/license text can be observed while actual artifact SHA, graph signature and reference execution remain unknown. Publisher LFS identity must not be relabeled as a local hash. No weights, datasets or AMD runtime binaries are redistributed.
- Current HF metadata/card/LICENSE access works; the pinned artifact redirects to `us.aws.cdn.hf.co`, whose CONNECT request is denied. A known-domain network addition was saved to an environment draft; it is not an applied runtime change. Model-specific validation stays blocked until the exact bytes are acquired and verified.
- R-005's GPU exact-3× plus compact NPU guide remains a research hypothesis. The current CPU/Vulkan nearest/bilinear references are not an implemented adaptive filter bank. Keep a useful GPU-only option as a product direction, without claiming learned reconstruction exists.
- Gate-0B scheduling/payload/adapter/corpus/interop scaffolding and hardware Gates 1–5 are future work, not automatically authorized by this implementation. No neural training, NPU execution, drivers, Gamescope/Decky or game capture in this cycle.
- Prior owner approval for reviewed source backups to the existing repository remains in force. Preserve repository visibility and private-data boundaries; no final source license, release, deployment or driver authorization is inferred. R-005's description of repo privacy is not a new independent visibility check.

The separate model, source-code, runtime and dataset license evidence and current candidate blockers are canonical in [the provenance manifest](../models/sesr-m7-256.provenance.json) and [acquisition notes](model-acquisition.md). Schema validation is not license clearance or hardware attestation.

## v1.6 — bounded continuation and mission (2026-10-19 America/Chicago)

The owner authorized the v1.6 handoff: update the mission/AI-assistance/licensing-pending README, time-box another exact SESR acquisition attempt and, if blocked, implement R005-G0B-1 deterministic scheduling plus a small payload calculator. This specifically supersedes v1.5's deferral of those two host-side tools; it does not authorize the NPU adapter, interop layer, training, Gamescope or Decky work.

- The current saved configuration includes the CDN host and shows a newer base version with no pending draft at inspection. Actual execution still rejects the CDN CONNECT with 403. Do not repeat the historical instruction to publish the old DSR007 draft as though it explains the current denial. Investigate runtime rule activation through supported controls; no agent-callable activation control exists here.
- Model acquisition remains blocked after a focused normal HTTPS retry; actual model identity/signature and CPU reference remain unknown/unrun. Proceed with the explicitly authorized simulation work, without treating it as actual NPU dispatch or full Gate-0 completion.
- Scheduling assumptions must identify latency, single-server service capacity, deadline behavior, queue pressure and delivered frames separately. Additional slots and frame delay cannot create NPU throughput. Reused, missed or bypassed output cannot count as a new completed neural frame.
- Payload arithmetic describes logical bytes and copy read/write volume, not measured physical bus traffic, latency or power.
- DockSR's mission is longer useful device life through efficient accessible reconstruction. Human direction and substantial ChatGPT/Codex assistance are disclosed. Community reuse/forking with attribution is an intention, not a license grant. Formal source/research terms, third-party rights, public visibility and release readiness remain separate owner decisions.
- Reviewed normal source backup pushes remain authorized; preserve visibility and private report/model/cache boundaries. No final license, release, deployment or system changes are inferred.
