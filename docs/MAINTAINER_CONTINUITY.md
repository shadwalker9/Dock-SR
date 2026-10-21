# Maintainer continuity

Start with [PROJECT_STATE.md](PROJECT_STATE.md) and [DECISIONS.md](DECISIONS.md), then the current task's code and newest owner handoff. Do not re-ingest every historical research paper. Inspect the current branch, HEAD and dirty files; preserve unrelated work. Cloud tasks are isolated and do not need an extra worktree unless requested.

The latest scope is v1.9 **DSR011**, NPU-first full-frame CPU reference,
owned exact3× model contract, replaceable worker and efficiency/probe preparation.
Read [full-frame reference](fullframe-reference.md), [exact3× contract](espcn-contract.md),
[inference worker](inference-worker.md) and [device-day preparation](npu-device-probe.md).
Do not replace these with another inspector, reference runner or parallel scheduler.
The shared `CpuReferenceSession` preserves the original Gate-0 safety policy.

The unchanged SESR upload and actual graph/reference are verified; full-frame
execution remains REAL_CPU. Generated exact3× FLOAT32 weights are untrained
fixtures outside Git, not a production model or quantization proof. Physical
XDNA2 inference/placement and imported-memory binding remain NOT_RUN/UNKNOWN.
Target hardware is forthcoming; do not repeat answered availability questions.

The [Gamescope lab](../experiments/gamescope/README.md) remains DSR010 build-only.
Do not repeat its understood cloud failure, remove Vulkan requirements, modify
system Gamescope or pivot to another graphics stack within DSR011. GPU fallback
is essential but does not waive the owner's verified-NPU requirement for the
first usable version targeted December31,2026.

The project owner approves priorities and external publication. The earlier v1.4 assignment authorized S005-PRE pre-hardware packaging without declaring S004 physically validated. The owner's accompanying chat explicitly authorizes backing up reviewed source changes to the existing GitHub repository; v1.6 preserves that authorization. Preserve visibility; no release, deployment or driver installation was requested. Private progress reports remain outside every checkout and must never enter Git, bundles, PRs or releases.

## What exists

- `src/image`: CPU nearest/bilinear, bounded P6 input, protected image publication, four real full-size self-test cases.
- `src/core`: typed status/schema, guarded profiles and scheduler ownership; the new inference worker reuses that ownership without presenting frames. No physical NPU backend exists.
- `scripts/sesr_fullframe.py`, `espcn_fixture.py`, `cpu_worker_executor.py`: CPU neural/reference and prototype bridge tools using the optional Gate-0 SDK; generated tensors/model bytes stay outside Git.
- `src/vulkan`: shared packed-buffer compute reference for preview/benchmark; actual evidence is classified from the selected device. Bundled SPIR-V is resolved relative to the executable. X11 display currently needs CPU readback.
- `src/preview`: own X11 window, unchanged-source matched A/B, CPU/Vulkan selection, truthful HUD and cached redraws. It is not game integration.
- `experiments/gamescope`: pinned native lab patch, scoped control contract and owned synthetic fixture/probe. Synthetic fixtures are not games; contract callbacks are not GPU/presentation evidence.
- `scripts/build_smoke_bundle.py`, `scripts/docksr_smoke.py`: explicit asset bundle, integrity checks, non-root launcher and opt-in private diagnostics.

The target Ryzen AI Z2 Extreme device is forthcoming. No physical Linux desktop is currently available to the owner. Intel NPU work is deferred. Xvfb/lavapipe evidence is real virtual-window/software-Vulkan execution, not AMD GPU/NPU performance. Product goals and power/FPS numbers remain targets, not results.

## Work and verify

On the supported cloud image, `bash scripts/install_environment.sh` prepares workspace-only pinned dependencies, builds `build-preview` and runs CTest. Activate both `/workspace/.cache/docksr-cloud/env.sh` and `preview-env.sh` when using retained tools. The first selects software lavapipe; never silently carry that selection into hardware testing. No live service is expected to survive a restored environment.

Use task-relevant tests and distinguish pass/fail/skip/unrun. [device-day.md](device-day.md) describes relocated bundle checks and target prerequisites; [preview.md](preview.md) covers the visible application. Do not count self-test in-memory images as published frames. Do not infer actual inference from a device node, extension, model file or CPU-partitioned ONNX graph.

Before publication, review the exact staged file list and source diff for private data and claim accuracy. Test first, commit only intended source, use a normal fast-forward push, and verify the remote SHA. Never force-push to bypass concurrent work. GitHub Actions definitions are not successful hosted runs until observed.

At each session close, deliver a concise private `.txt` report outside Git plus its complete copyable text in chat. Include changed paths/reasons, exact checks and evidence classes, actual versus expected benefits, research/decisions, future value and MVP blockers, branch/HEAD/dirty state, commit/push/publication status and one next task. Reserve budget for delivery. Reporting instructions may be retained in environment configuration; report bodies may not.

## Deferred research after the current lab

An offline EGR-001/R-004 experiment remains outside the current bounded lab; do not silently start training. A learned-filter/NPU guide is still a hypothesis. Any future experiment needs rights-cleared inputs, raw-preserving ablations, matched sharpness, held-out motion and an explicit stop criterion. R-003 scheduling must precede serious neural training. Actual NPU execution/operator placement, buffer binding, synchronization, concurrency and whole-system power remain independent hardware gates. A functional smoke package is not the requested lower-cost Decky MVP.
