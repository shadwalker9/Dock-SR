# Dock SR project state

Updated 2026-10-19 (America/Chicago). Read this and [DECISIONS.md](DECISIONS.md) before resuming. Latest owner directive: Execution Handoff v1.3; research R-004 is proposed only. No AGENTS.md or docs/OWNER_UPDATES.md exists in this checkout; approved O-002 requirements are recorded in DECISIONS.md and prior owner documents.

## S004 reconciliation and selected task

**S004 implementation is present and runs in an authenticated virtual X11 window. Overall acceptance remains PARTIAL/BLOCKED on physical interactive-display validation under v1.3. Selected Task A: finish/verify S004 only; S005 has not started.** The credit pause prevented delivery of the prior report, not preservation of source or evidence. Do not redo the preview or promote to packaging based on a build alone.

The real X11 application reuses S003 CPU nearest/bilinear and its extracted shared Vulkan engine. Both A/B sides preserve the same raw source and process equal 1080p/4K output dimensions. The HUD distinguishes window dimensions, actual completed outputs, method, backend/evidence, timing and error/fallback. NPU remains NOT_TESTED/NOT_ACTIVE. Method/backend/output controls recompute only when needed; window resize, fit/1:1 crop, diagnostics and A/B controls reuse completed pixels. Capture reads the actual executed window. See [commands and limits](preview.md).

## Observed evidence

- Pre-S004 baseline: 16/16 CTest groups passed. Preview build: 20/20 groups passed in the retained pre-pause run and again through the updated `bash scripts/install_environment.sh` during reconciliation; zero failures/skips.
- Authenticated Xvfb execution: six actual-window check groups passed, including independent captured-pixel checks, genuine A/B differences, method/output/backend controls, cached counters, resize and quit. Real CPU and software-Vulkan 720p→1080p/4K paths executed. The controller's five headless groups and CLI startup tests cover fallback, invalid dimensions/images and absent display. Injected backend observations are state tests, not hardware evidence.
- Authentic pre-pause captures: ignored `results/session-004/executed-window-final/actual-window-cpu-1080.ppm` and `actual-window.ppm`. PNG copies are lossless conversions of these captured pixels. `window-result.json`, stdout/status and raw input remain beside them. The screenshots show the virtual window, not an attached physical monitor or game.
- Reconciliation setup log: `results/session-004/reconciled-install.log`. Preview-disabled host build passed 15/15 groups, library-only 4/4, and CPU-only preview with BUILD_CLI=OFF 8/8; zero failures/skips. Modular build results are recorded separately in `host-only-recheck.log`, `library-recheck.log` and `preview-cpu-only.log` in that directory.
- S003's four real CPU output/status cases and six software-Vulkan baseline cases remain under `results/session-003/`. They are diagnostic image-scaler evidence, not game/quality/power benchmarks. The new shared Vulkan engine and unchanged benchmark CLI have independent correctness checks.

The cloud has no physical GPU/NPU device nodes or active physical display. Xvfb is an actual virtual X server; lavapipe is CPU software Vulkan. No AMD physical-GPU result is established. The Ryzen AI Z2 Extreme device is forthcoming; the owner confirmed no Linux desktop is available yet. Optional Intel hardware remains unconfirmed and Intel NPU work is deferred.

## Sequence and remaining gates

1. S003 functional CLI: locally validated; preserve it.
2. **Current S004 gate:** run the existing preview interactively on a physical Linux X11/XWayland desktop; confirm readable HUD, method/backend/output changes, resize and exit, retaining actual evidence. Use CPU fallback if physical Vulkan is absent. This gate is UNRUN here; v1.3 forbids silently promoting to S005.
3. After S004 acceptance, S005 is a minimal non-root x86_64 smoke bundle only: launcher/manifest, self-test/status dump, private logs, fixtures and SteamOS/Bazzite Desktop Mode instructions. No Decky/game integration in that sprint. Target execution remains a separate gate.
4. Read-only target telemetry, actual XDNA graph dispatch/operator placement and direct buffer binding, then ownership/coherency/synchronization, interop and measured concurrency.
5. Owner-approved scheduling-grid and held-out moving-scene EGR experiments before serious neural training. R-004's learned filter bank, signed guide and tiny NPU model are research candidates; no implementation or architecture change is approved by reading the paper.

## Not verified / publication

No Decky plugin, NPU inference, GPU/NPU sharing, zero-copy game path, Gamescope/game injection, reconstructed-quality advantage, native-720p retention, comparative cost or power benefit. Actual driver timeout/device-loss recovery is untested; finite fence waits cannot bound arbitrary driver-entry-point hangs. Existing Vulkan readback serves X11 display and is not the final presentation design.

GitHub Actions definitions are not observed hosted runs. Current restored branch is `work`, HEAD `a42da2a948f5dc79840ba51bd619765f658ce45d` (initial commit), with S003/S004 changes local and uncommitted. The earlier session recorded `main` at the same HEAD. No local checkpoint, remote push, release, deployment, visibility change or driver installation was performed. Private progress reports stay outside the repository.
