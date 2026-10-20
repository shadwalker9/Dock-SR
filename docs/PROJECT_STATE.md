# Dock SR project state

Updated 2026-10-19 (America/Chicago). Read this and [DECISIONS.md](DECISIONS.md) before resuming. Latest assignment: **v1.4 S005-PRE**, safe pre-hardware preparation. Only the short assignment was supplied; its longer referenced handoff was not provided. No AGENTS.md or docs/OWNER_UPDATES.md exists here; approved O-002 targets are recorded in DECISIONS.md.

## Implemented scope

S003 provides real CPU nearest/bilinear CLI output, protected P6 image I/O, typed status, guarded profiles, simulated scheduler and a Vulkan reference. S004 provides an actually executed own X11 window with unchanged-source matched A/B, truthful HUD, 1080p/4K controls, cached redraws and safe exit. **S004 physical-display acceptance is still PARTIAL/BLOCKED.** Xvfb is a virtual display; lavapipe is software Vulkan. No AMD hardware result is established.

**S005-PRE adds a relocatable non-root Linux x86_64 smoke bundle and launcher**, manifest integrity checks, host ABI requirements, four actual CPU full-size self-test cases, reusable atomic status output, bounded sanitized private diagnostics, small owned fixtures and [device-day instructions](device-day.md). It is pre-hardware preparation, not target compatibility, S004 hardware acceptance, a release or a Decky plugin.

The CPU self-test checks every RGB pixel for nearest/bilinear at 1280×720→1920×1080 and →3840×2160, preserves raw input and uses independent tiny goldens/direct reference formulas. Outputs are validated in memory and discarded: published-frame count remains zero and actual published dimensions null. The optional Vulkan shader resolves relative to the executable; moved tools cannot borrow a missing shader from the build directory. Smoke executables contain no developer SDK RPATH/RUNPATH; the launcher does not override the host ICD/library path.

The bundle verifies exact files, modes, sizes/hashes and manifest identity, rejects unexpected/escaping/symlink/hardlink content and isolates Python imports before verification. Diagnostics copy only bounded allowlisted observations; exports are private, atomic and do not overwrite a concurrent owner file. No raw logs, environment values, screenshots, private reports, driver libraries or models are packaged. Hash integrity is not a cryptographic signature.

## Observed checks and limits

- Full preview build: **22/22 CTest groups passed**, zero failures/skips, including unchanged core/CPU/Vulkan behavior, actual Xvfb window checks, shader relocation and smoke packaging. Local logs: ignored `results/session-006/full-preview-build.log` and `full-preview-ctest.log`.
- CPU-only host: **16/16 groups passed**, zero failures/skips. Its CPU command does not link X11 or Vulkan. Logs: `results/session-006/host-build.log`, `host-ctest.log`.
- Packaging suite: **15/15 tests passed**, including moving to a path with spaces, real CPU self-test/status, valid status replacement, privacy canaries, tampering/missing/extra/escaping/link rejection, safe permissions, bounded subprocesses and atomic export races. The import regression covers `json.py`, `__future__.py` and `os.py` before verification.
- Shader relocation: three real software-Vulkan tests passed; an isolated additional check executed with the original shader hidden. Missing/corrupt bundled assets fail. Software results do not forecast physical GPU timing.
- Earlier S003/S004 logs/captures remain under ignored `results/session-003/` and `results/session-004/`. Authentic virtual-window captures are in `session-004/executed-window-final/`; PNGs are lossless format conversions of executed-window PPMs. Prior library-only 4/4 and CPU-preview-without-CLI 8/8 checks remain historical evidence.

The cloud has no physical GPU/NPU or physical desktop. The owner confirmed no Linux desktop is available yet; the Ryzen AI Z2 Extreme device is forthcoming. Intel NPU work is deferred. SteamOS/Bazzite Desktop Mode, physical window/GPU, Gaming Mode and target ABI are **UNRUN**. A relocatable directory is not proof of ABI compatibility: the manifest records host GLIBC/GLIBCXX/CXXABI and shared-library requirements. No system libraries or drivers should be replaced to make this smoke check run.

## Next independent work

Propose one bounded **EGR-001/R-004 offline reconstruction experiment**, using owned/licensed synthetic moving-scene pairs, preserved raw RGB, raw-only/high-pass/pre-sharpen controls, matched final sharpening, held-out fidelity/artifact/temporal evaluation and an explicit go/no-go criterion. Do not start training merely because the proposal exists. Research architecture is unapproved; any close learned-filter implementation needs the recorded source-rights review. The R-003 timing grid must precede serious neural training.

When a physical Linux desktop is available, run the existing preview acceptance controls and retain real evidence. When the target arrives, identify the device/OS/runtime and prove actual non-identity NPU inference/operator placement before interop, ownership/coherency/synchronization and measured concurrency. Decky/game integration is later work.

## MVP and backup status

MVP remains **NOT_READY**: no Decky plugin, NPU execution, graphics/NPU sharing, zero-copy game pipeline, game integration, reconstructed-quality advantage, native-720p retention or matched-quality lower system cost. CPU/software-Vulkan timings are diagnostic observations; power/FPS goals remain unmeasured. Actual driver timeout/loss recovery has not been induced.

The owner explicitly authorized reviewed source backups to the existing GitHub repository, preserving visibility. Foundation checkpoint `22dc410` was pushed and its full remote SHA verified on `origin/main`. Current work is on branch `work`; use Git history and the remote ref to inspect the latest S005-PRE checkpoint. No release, deployment, visibility change or system-driver installation was authorized/performed. Private reports/attachments and generated device evidence remain outside Git. Hosted GitHub Actions runs have not been observed; workflow definitions alone do not establish a CI pass.

See [maintainer continuity](MAINTAINER_CONTINUITY.md) for the resume workflow. Private reports are delivered directly to the owner, not published here.
