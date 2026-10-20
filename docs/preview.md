# Standalone preview (S004)

This is an ordinary X11 application, including through XWayland when available. It is **PREVIEW ONLY — NOT GAME INTEGRATION**. It does not intercept a game, execute an NPU model or establish an efficiency advantage. Native Wayland presentation and SteamOS/Bazzite execution are separate, untested gates.

## Build and launch

On a Linux development host, install the distribution's supported X11 development files (`libx11-dev` on Debian/Ubuntu), plus the prerequisites in [development.md](development.md). Vulkan is optional; its development files and glslang are needed to build that backend. The preview reuses the same CPU library, Vulkan shader/engine and typed status as the CLI.

```sh
cmake -S . -B build-preview -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_PREVIEW=ON -DDOCKSR_ENABLE_VULKAN=OFF
cmake --build build-preview --parallel 2
ctest --test-dir build-preview --output-on-failure
./build-preview/bin/docksr-preview
```

Use `-DDOCKSR_REQUIRE_VULKAN=ON` instead of disabling Vulkan to require the Vulkan build. `BUILD_CLI=OFF` builds the preview and libraries without CLI executables; `BUILD_TESTING=OFF` omits tests. `BUILD_PREVIEW=OFF` needs no X11 development files. No implicit Vulkan layers, root or background service are required.

On the supported Debian 13 cloud image:

```sh
python3 scripts/bootstrap_cloud.py
python3 scripts/bootstrap_preview.py --with-test-tools
source /workspace/.cache/docksr-cloud/env.sh
source /workspace/.cache/docksr-cloud/preview-env.sh
cmake -S . -B build-preview -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_PREVIEW=ON -DDOCKSR_REQUIRE_VULKAN=ON \
  -DPython3_EXECUTABLE=/workspace/.venvs/docksr-host/bin/python \
  -DVulkan_INCLUDE_DIR="$DOCKSR_VULKAN_ROOT/include" \
  -DVulkan_LIBRARY="$DOCKSR_VULKAN_ROOT/lib/x86_64-linux-gnu/libvulkan.so.1" \
  -DVulkan_GLSLANG_VALIDATOR_EXECUTABLE="$DOCKSR_VULKAN_ROOT/bin/glslangValidator" \
  -DX11_X11_INCLUDE_PATH="$DOCKSR_PREVIEW_ROOT/include" \
  -DX11_X11_LIB="$DOCKSR_PREVIEW_ROOT/lib/x86_64-linux-gnu/libX11.so"
cmake --build build-preview --parallel 2
ctest --test-dir build-preview --output-on-failure
```

The cloud activation explicitly selects **software Vulkan**. Remove that selection before planning a physical-device benchmark; record the device actually used. The X11 helper extracts hash-pinned user-space prerequisites into workspace paths without changing system packages or graphics configuration. See [dependency/license audit](../notes/PREVIEW_DEPENDENCIES.md).

The cloud has no existing display. The optional window test starts and stops its own authenticated Xvfb server with TCP disabled. It launches the real application, sends real X11 input/resize events and captures the actual drawable. This verifies a virtual window; it does not verify a physical monitor, AMD GPU, desktop compositor or target handheld.

## Use

```sh
mkdir -p results/preview-local
chmod 700 results/preview-local
./build-preview/bin/docksr-preview --size 3840x2160 --backend vulkan \
  --filter bilinear --dump-status-json results/preview-local/status.json \
  --capture results/preview-local/actual-window.ppm
```

Default input is the real deterministic 1280×720 S003 image. `--input RAW.ppm` accepts the same bounded binary P6 format as the CLI; it preserves that source unchanged. Both sides independently scale the same raw source to exactly 1920×1080 or 3840×2160. Left A is always CPU nearest; right B uses the selected nearest/bilinear method and CPU/Vulkan backend. Two nearest sides can match; this is expected, not a fabricated algorithm difference.

| Key | Action |
|---|---|
| M | Switch right-side nearest/bilinear |
| V | Request CPU/Vulkan; unavailable or unclassified Vulkan falls back to real CPU with reason |
| O | Switch actual processing output between 1080p and 4K |
| A | Matched A/B or right-side-only display |
| D | Toggle full diagnostics |
| Z | Fit both outputs or show the same center crop at one output pixel per window pixel |
| R | Retry/reprocess the selected configuration |
| C | Capture the executed window to the new `--capture` PPM path; never overwrite |
| Q / Escape | Quit |

Window resizing and display controls reuse completed pixels and do not increment processed-output counters. Fit view uses nearest display sampling; it is a convenience view, not a quality metric. Use the matched 1:1 crop to inspect output detail. The HUD separates source/output processing dimensions from the window size. No animations or assumed frame rates are shown.

Status is the existing versioned `docksr_status` schema. Each processing update emits one JSON line to stdout; the optional owner-only file is atomically replaced in a private user-owned directory. CPU timing measures resize only. Vulkan timing, when available, is the real device timestamp interval around dispatch; software-device timestamps remain software evidence. Unknown timings are null/UNMEASURED. Neither interval measures X11 presentation, input latency, FPS or whole-system cost. Status is a last-processing snapshot, not a liveness heartbeat after exit.

The Vulkan path uses S003 packed storage buffers and reads completed RGB pixels for actual X11 display. It is not an optimized GPU swapchain, zero-copy composition or a game pipeline. Readback is needed for the shown pixels, not solely for telemetry. A Vulkan submission has a five-second fence bound; a still-in-flight failed context is disabled and retained until process exit so fallback does not free its buffers or wait indefinitely in `vkDeviceWaitIdle`. An arbitrary driver entry point can still hang; integration tests have an outer watchdog. Actual device loss/timeout recovery has not been induced on hardware.

## Repeatable evidence

```sh
# Retain an actual executed-window capture and result record; choose a new path.
python tests/test_preview_window.py build-preview/bin/docksr-preview \
  --artifact-dir results/preview-window-run
```

Headless tests exercise independent pixel goldens, full 720p→1080p/4K dimensions, preserved raw input, cached redraws, invalid requests, explicit fallback and transactional error counters. Injected provider tests are state simulations; actual native Vulkan correctness tests are reported separately. Startup tests check invalid dimensions, bad/missing images and absent display without claiming completed output. The optional actual-window runner exits 77 if Xvfb/xdotool are missing; a skip is not a pass. A capture is produced only after execution and verified against independently computed raw-source pixels. No synthetic screenshot is used.
