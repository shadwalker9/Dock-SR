# Dock SR project state

Updated 2026-10-19 (America/Chicago; 2026-10-20 UTC). Read this and [DECISIONS.md](DECISIONS.md) before resuming. Latest assignment: **v1.5 R005-G0A**, read R-005 research first, then implement Gate-0A evidence/model readiness. No AGENTS.md or docs/OWNER_UPDATES.md exists here; approved O-002 targets are recorded in DECISIONS.md.

## Implemented scope

S003 provides real CPU nearest/bilinear CLI output, protected P6 image I/O, typed status, guarded profiles, simulated scheduler and a Vulkan reference. S004 provides an actually executed own X11 window with unchanged-source matched A/B, truthful HUD, 1080p/4K controls, cached redraws and safe exit. **S004 physical-display acceptance is still PARTIAL/BLOCKED.** Xvfb is a virtual display; lavapipe is software Vulkan. No AMD hardware result is established.

**S005-PRE adds a relocatable non-root Linux x86_64 smoke bundle and launcher**, manifest integrity checks, host ABI requirements, four actual CPU full-size self-test cases, reusable atomic status output, bounded sanitized private diagnostics, small owned fixtures and [device-day instructions](device-day.md). It is pre-hardware preparation, not target compatibility, S004 hardware acceptance, a release or a Decky plugin.

The CPU self-test checks every RGB pixel for nearest/bilinear at 1280×720→1920×1080 and →3840×2160, preserves raw input and uses independent tiny goldens/direct reference formulas. Outputs are validated in memory and discarded: published-frame count remains zero and actual published dimensions null. The optional Vulkan shader resolves relative to the executable; moved tools cannot borrow a missing shader from the build directory. Smoke executables contain no developer SDK RPATH/RUNPATH; the launcher does not override the host ICD/library path.

The bundle verifies exact files, modes, sizes/hashes and manifest identity, rejects unexpected/escaping/symlink/hardlink content and isolates Python imports before verification. Diagnostics copy only bounded allowlisted observations; exports are private, atomic and do not overwrite a concurrent owner file. No raw logs, environment values, screenshots, private reports, driver libraries or models are packaged. Hash integrity is not a cryptographic signature.

**R005-G0A infrastructure is complete; model-specific validation is blocked.** [Gate-0 tooling](gate0.md) adds separate provenance/hardware-evidence contracts, semantic validation, an isolated bounded ONNX inspector, deterministic CPU-only reference inference and optional hash-locked host dependencies. A pinned [SESR candidate record](../models/sesr-m7-256.provenance.json) preserves unknown actual artifact identity, runtime/dataset rights and redistribution scope. The artifact redirects to `us.aws.cdn.hf.co`, which the current proxy rejects. The hostname is saved in an environment draft, not applied/published. See [acquisition evidence](model-acquisition.md). No Gate-0B implementation or full Gate-0 PASS is claimed.

## Observed checks and limits

- Full preview with optional Gate-0 SDK tests: **25/25 CTest groups passed**, zero failures/skips. Ordinary preview without that SDK: **23/23 passed**. Existing core/CPU/software-Vulkan, actual Xvfb window, shader relocation and smoke packaging checks remain passing. Logs: ignored `results/session-007/gate0-final.log` and `preview-final.log`.
- CPU-only host without the optional SDK: **17/17 groups passed**; library-only: **5/5 passed**, zero failures/skips. Logs: `results/session-007/host-final.log`, `library-no-sdk.log`. The ordinary CPU command has no X11/Vulkan link dependency.
- New focused checks: **15 schema tests, 12 inspector tests and 12 CPU-reference tests passed**. They cover missing dependencies, unsafe external references, bounded input, graph signatures, nonfinite/wrong/identity output and false NPU claims. Two fresh executions of an owned tiny resize-plus-add graph matched an independent NumPy golden and identical input/output file hashes. This is REAL_CPU evidence, not SESR or an NPU test. Actual SESR graph/reference and natural-image quality checks remain blocked/not run.
- Packaging suite: **15/15 tests passed**, including moving to a path with spaces, real CPU self-test/status, valid status replacement, privacy canaries, tampering/missing/extra/escaping/link rejection, safe permissions, bounded subprocesses and atomic export races. The import regression covers `json.py`, `__future__.py` and `os.py` before verification.
- Shader relocation: three real software-Vulkan tests passed; an isolated additional check executed with the original shader hidden. Missing/corrupt bundled assets fail. Software results do not forecast physical GPU timing.
- Earlier S003/S004 logs/captures remain under ignored `results/session-003/` and `results/session-004/`. Authentic virtual-window captures are in `session-004/executed-window-final/`; PNGs are lossless format conversions of executed-window PPMs. Prior library-only 4/4 and CPU-preview-without-CLI 8/8 checks remain historical evidence.

The cloud has no physical GPU/NPU or physical desktop. The owner confirmed no Linux desktop is available yet; the Ryzen AI Z2 Extreme device is forthcoming. Intel NPU work is deferred. SteamOS/Bazzite Desktop Mode, physical window/GPU, Gaming Mode and target ABI are **UNRUN**. A relocatable directory is not proof of ABI compatibility: the manifest records host GLIBC/GLIBCXX/CXXABI and shared-library requirements. No system libraries or drivers should be replaced to make this smoke check run.

## Next bounded milestone

Complete blocked **R005-G0A model-specific validation**: after permitted CDN access is active, acquire the immutable SESR artifact outside Git, independently verify actual size/hash, inspect its graph and establish documented CPU reference behavior if supported. Preserve an explicit NOT RUN/BLOCKED result if host operators or preprocessing remain unresolved. Do not alter the model to manufacture support. Resolve model/runtime/data distribution scopes separately. Gate-0B remains proposed and unstarted; do not substitute scheduler, payload, driver, training, EGR or integration work for this gate.

When a physical Linux desktop is available, run the existing preview acceptance controls and retain real evidence. When the target arrives, identify the device/OS/runtime and prove actual non-identity NPU inference/operator placement before interop, ownership/coherency/synchronization and measured concurrency. Decky/game integration is later work.

## MVP and backup status

MVP remains **NOT_READY**: no Decky plugin, NPU execution, graphics/NPU sharing, zero-copy game pipeline, game integration, reconstructed-quality advantage, native-720p retention or matched-quality lower system cost. CPU/software-Vulkan timings are diagnostic observations; power/FPS goals remain unmeasured. Actual driver timeout/loss recovery has not been induced.

The owner explicitly authorized reviewed source backups to the existing GitHub repository, preserving visibility. Foundation checkpoint `22dc410` was pushed and its full remote SHA verified on `origin/main`. Current work is on branch `work`; use Git history and the remote ref to inspect the latest S005-PRE checkpoint. No release, deployment, visibility change or system-driver installation was authorized/performed. Private reports/attachments and generated device evidence remain outside Git. Hosted GitHub Actions runs have not been observed; workflow definitions alone do not establish a CI pass.

See [maintainer continuity](MAINTAINER_CONTINUITY.md) for the resume workflow. Private reports are delivered directly to the owner, not published here.
