# Development setup

The core uses C++20 and the standard library; no inference runtime is required to build host/mock code. Python 3.10+ runs diagnostics and schema tests. CMake 3.25+ and Ninja build the native targets. The Python test dependencies are frozen with release/artifact hashes in `requirements-dev.lock`.

## Tested Debian 13 cloud image

This helper installs into workspace-owned paths only. It does not run a system package manager, change OS/kernel/firmware, fetch a model, or start a service. Its Vulkan packages are pinned Debian 13 x86_64 artifacts whose hashes were obtained from Debian archive-keyring-verified package indexes. Normal HTTPS and SHA-256 verification remain enabled.

```sh
cd /workspace/Dock-SR
python3 scripts/bootstrap_cloud.py
source /workspace/.cache/docksr-cloud/env.sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DDOCKSR_REQUIRE_VULKAN=ON \
  -DPython3_EXECUTABLE=/workspace/.venvs/docksr-host/bin/python \
  -DVulkan_INCLUDE_DIR="$DOCKSR_VULKAN_ROOT/include" \
  -DVulkan_LIBRARY="$DOCKSR_VULKAN_ROOT/lib/x86_64-linux-gnu/libvulkan.so.1" \
  -DVulkan_GLSLANG_VALIDATOR_EXECUTABLE="$DOCKSR_VULKAN_ROOT/bin/glslangValidator"
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

The activation file selects lavapipe and directs Mesa/runtime caches into writable workspace paths. **This deliberately selects a software ICD**. Do not carry that override into an AMD hardware benchmark. On a physical target, record which device/driver actually executed and choose its supported runtime configuration separately.

The helper requires the base image's compiler, Python/venv, `dpkg-deb` and runtime dependencies such as LLVM 19. It extracts trusted binary packages; it does not resolve every package dependency on an arbitrary distribution. It rejects other OS/architecture combinations rather than mixing Debian libraries into another host. Use `--host-only` to prepare only the shared host tools/tests on the supported image.

The complete exercised cloud setup/build/test sequence is also available as `bash scripts/install_environment.sh`.

## Ordinary Linux development

Use your distribution's supported C++ compiler, CMake/Ninja, Python virtual environment, Vulkan headers/loader, glslang compiler and GPU or Mesa software ICD. On disposable Ubuntu 24.04 CI, the Vulkan packages are `libvulkan-dev glslang-tools mesa-vulkan-drivers`; the checked-in workflow installs them there. Do not use those commands as an immutable SteamOS/Bazzite deployment procedure.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.lock
cmake -S . -B build-host -G Ninja -DDOCKSR_ENABLE_VULKAN=OFF
cmake --build build-host --parallel 2
ctest --test-dir build-host --output-on-failure
```

For Vulkan, use a separate build with `-DDOCKSR_REQUIRE_VULKAN=ON`. This flag requires headers/loader/glslang at configure time; it does not prove a runtime device exists. The independent Vulkan test reports a distinct skip when no usable runtime exists; inspect the CTest summary and do not count skipped tests as validated shader behavior. CI explicitly selects its installed lavapipe ICD.

## Native commands

The CPU engine requires no graphics device. It supports RGB, binary 8-bit P6 PPM (`maxval=255`) or deterministic 1280×720 generated input. Dimensions are used exactly as requested, including deliberate aspect stretching; there is no hidden crop or letterboxing. Other codecs/HDR and video are outside this S003 deliverable. Existing output images are protected.

```sh
mkdir -p results
./build/bin/docksr-scale --generate --output results/cpu-1080.ppm \
  --size 1920x1080 --filter nearest
./build/bin/docksr-scale --generate --output results/cpu-4k.ppm \
  --size 3840x2160 --filter bilinear --dump-status-json results/cpu-status.json
```

Status output identifies CPU work and leaves GPU/NPU timing null. The optional status file is atomically published with owner-only permissions in a user-owned directory that is not group/world writable. The CLI produces a final snapshot; the separate [preview](preview.md) reuses this contract for its own window. Use a distinct image output path per invocation.

```sh
./build/bin/docksr-mock --list-profiles
./build/bin/docksr-mock
./build/bin/docksr-mock --enable --scenario late
./build/bin/docksr-mock --enable --scenario crash
./build/bin/docksr-mock --enable --scenario late-consumer
python scripts/docksr_detect.py
mkdir -p results
python scripts/docksr_detect.py --output results/detection.json
./build/bin/docksr-bench --probe > results/vulkan-probe.json
```

Mock scenarios are `normal`, `late`, `late-consumer`, `crash`, `resize`, `suspend`, `exhaustion` and `stale`. Mock `--enable` authorizes only simulation-scoped validation; it cannot enable an actual NPU profile. Defaults remain disabled. The scheduler assumes one trusted owner and is not a multithreaded GPU/WSI implementation.

Build options `BUILD_CLI`, `BUILD_PREVIEW` and `BUILD_TESTING` are separate. `BUILD_PREVIEW=ON` builds the X11 window described in [preview.md](preview.md); leaving it off requires no X11 dependency. The preview may use the optional shared Vulkan engine independently of CLI executables.

The detector reports device-node visibility, metadata, tool versions and unrun runtime gates. A node, extension name or successful `vulkaninfo` summary never sets `npu_ready=true`. The separate native probe queries exact external-buffer and sync-FD properties for the selected Vulkan device but does not test a shared allocation or graph.

## Test interpretation

Core tests exercise exact identity/profile validation, invalid inputs, bounded events, deadlines, late producer/consumer completions, resize, suspend, crash and stale generations. Python tests check absent/permission/error inventory states and reject misleading telemetry labels or corrupted artifacts. Shader tests use independent CPU/reference properties, odd dimensions, both filters and invalid allocation/argument bounds.

The matrix validates JSON against its schema, CSV sample counts/frame indices/quantiles and image hashes, then retains source/binary/shader provenance. Image fixtures are deterministic gradients, edges, UI-like strokes and pixel-art regions; they are not a game dataset or perceptual-quality regression suite.

The GitHub Actions files are CI definitions. Only local execution actually observed in this workspace may be reported as passed; no hosted Actions run is established by adding the workflow.
