# S005-PRE device-day smoke check

This is a non-root Linux x86_64 development bundle, prepared before target hardware arrives. It is not a plugin, driver installer, game upscaler or release. S004 physical-display acceptance, SteamOS/Bazzite compatibility and physical AMD execution remain untested. The package can be relocated without the cloud checkout; it still needs compatible host runtimes.

## Prepare on the development host

Build and run the checks in [development.md](development.md) and [preview.md](preview.md). Python 3.10+ is needed for the standard-library launcher. The bundle requires `docksr-scale`; include the preview/benchmark only from a build that actually produced them.

```sh
python scripts/build_smoke_bundle.py --build-dir build-preview \
  --output-dir results/device-day-smoke --include-preview --include-bench
./results/device-day-smoke/docksr-smoke --self-test
```

Choose a new output directory. The builder includes only explicitly selected binaries, the compiled shader, schemas, the detector, owned small fixtures and documentation. It does not package private reports, attachments, build caches, inference models or system driver libraries. `MANIFEST.json` records source identity, file sizes/hashes, and ELF runtime requirements. Checksums detect corruption relative to this manifest; they are not a signature or a proof of trust in an unknown sender. Obtain the bundle from the owner/developer, not an arbitrary mirror.

The binary ABI depends on the build host. A Debian cloud build is not automatically a portable SteamOS/Bazzite build. Inspect the manifest's GLIBC/GLIBCXX/CXXABI and shared-library requirements. If unavailable on the device, rebuild on a compatible development host; do not replace system libraries or install AMD Ubuntu `.deb` packages onto SteamOS/Bazzite. The bundle intentionally includes no ICD, kernel module, implicit Vulkan layer or driver installer.

## First run on SteamOS/Bazzite Desktop Mode

1. Copy/extract the trusted bundle into a directory owned by your user, preserving the executable launcher bit. No root, system service or Gaming Mode changes are needed.
2. Use Desktop Mode and a terminal. Do not launch through a game or Decky. Confirm Linux x86_64 and Python 3.10+ are available. The launcher needs no pip packages or network access.
3. Run the CPU test first from the copied directory. It needs neither a display nor Vulkan:

```sh
cd "path/to/copied smoke bundle"
mkdir -p "$HOME/DockSR-smoke-results"
chmod 700 "$HOME/DockSR-smoke-results"
./docksr-smoke --self-test \
  --dump-status-json "$HOME/DockSR-smoke-results/status.json"
```

The CPU test validates all RGB pixels of four real resized outputs: nearest and bilinear, each at 1280×720→1920×1080 and →3840×2160. It preserves raw input, includes independent tiny exact goldens, and the native CPU command emits four `SELF_TEST_CASE ... PASS` records plus a four-case `SELF_TEST_SUMMARY`. The launcher verifies that summary and emits shared status JSON; run `./bin/docksr-scale --self-test` to inspect the native per-case records. Outputs are checked in memory and discarded; `frames_processed` remains zero and actual published dimensions remain null. This is deliberate: the status counter counts published image outputs, not self-test assertions. Requested dimensions end at 720p→4K, evidence is `REAL_CPU`, and NPU is `NOT_TESTED`. CPU duration excludes verification/I/O and is not game FPS or a cost comparison.

If the launcher cannot execute a binary because of a missing runtime, retain its error and the manifest requirements. Failure is not a reason to install system drivers or disable system protections.

## Optional own-window preview

The bundle must have been built with `--include-preview`. The desktop must provide X11 or XWayland (`DISPLAY`), a TrueColor visual and Xlib. A native Wayland-only session without XWayland is not currently supported.

```sh
./docksr-smoke --preview --size 1920x1080 --backend cpu \
  --filter bilinear --dump-status-json "$HOME/DockSR-smoke-results/status.json"
./docksr-smoke --preview --size 3840x2160 --backend vulkan \
  --filter bilinear --dump-status-json "$HOME/DockSR-smoke-results/status.json"
```

First verify CPU mode, readable HUD, actual source/output/window dimensions, matched A/B, M/V/O controls, Z crop/fit, resize and Q/Escape exit. See [preview controls](preview.md) in the source checkout for full behavior. The preview's own banner must remain `PREVIEW ONLY - NOT GAME INTEGRATION`.

A Vulkan-enabled preview binary needs the host Vulkan loader even when CPU mode is selected. If that loader is absent, the separate CPU self-test still works; use a compatible CPU-only preview build rather than replacing system libraries. The launcher does not select an ICD or modify `LD_LIBRARY_PATH`. Do not copy the cloud's lavapipe environment to the handheld. If Vulkan executes, identify the actual evidence: `SOFTWARE_VULKAN` is CPU software execution; `REAL_GPU` requires the engine to select an integrated/discrete GPU and complete scaling. Unavailable/unclassified Vulkan falls back to `REAL_CPU` with a reason. Neither case activates an NPU. A physical display check can pass on CPU; it does not establish physical-GPU performance.

Record device/APU, OS/kernel/driver, desktop/session, selected output and method, observed status/error, readability and controls. Keep physical monitor, software Vulkan, physical GPU and target-device results separate. Do not infer 4K detail, zero-copy, latency, efficiency or wattage from this smoke run. No frame generation, game injection, neural filtering, NPU inference or Decky is included.

## Private diagnostics export

```sh
./docksr-smoke --diagnostics-export "$HOME/DockSR-smoke-results/diagnostics.tar.gz" \
  --status-json "$HOME/DockSR-smoke-results/status.json"
```

Use a new archive path in a private directory. Export is local and opt-in; nothing is uploaded. It contains a bounded allowlist of bundle identity, inventory/status observations and safe result summaries. It excludes arbitrary files, raw command logs, environment values, credentials, screenshots and private progress reports. CPU/software/physical evidence and NPU `NOT_TESTED` remain explicit. Missing tools and errors are reported honestly. Review the archive before choosing to send it to the developer.

The status file is a last-processing snapshot, not a process heartbeat. Its monotonic timestamp belongs to the same host/boot and may be stale after exit. Do not use it to claim that the application is still running or that a model was validated.

## Stop conditions and next experiment

If startup, output correctness, controls, fallback or clean exit fail, preserve the error/status and stop that test. The smoke launcher does not repair the OS. On the cloud, actual-window checks use authenticated Xvfb and software Vulkan; target Desktop Mode and Gaming Mode are separate unrun gates.

The next independent pre-hardware proposal is a bounded EGR-001/R-004 offline experiment with owned/licensed moving-scene data, preserved raw RGB, matched final sharpening and explicit held-out fidelity/artifact/temporal tests. It requires owner approval; this package does not begin that research or choose a neural architecture.
