# Dock SR

Dock SR is an early Linux development prototype for NPU-assisted game upscaling, targeting Ryzen AI Z2 Extreme first. The product goal is a Decky-controlled native backend that costs less than an existing scaler at comparable quality. That advantage has **not** been demonstrated.

**S004 standalone preview** adds a real window, matched CPU/Vulkan A/B and truthful diagnostics to the S003 scaling foundation. Read [preview commands and evidence limits](docs/preview.md), [project state](docs/PROJECT_STATE.md) and [current owner decisions](docs/DECISIONS.md) before resuming. Neural inference, game integration and Decky follow this pre-hardware work.

**S005-PRE smoke preparation** packages the existing tools for non-root, relocatable Linux x86_64 checks. See [device-day instructions](docs/device-day.md) and [maintainer continuity](docs/MAINTAINER_CONTINUITY.md). This does not establish physical-display or SteamOS/Bazzite acceptance. Source checkpoints are backed up to this repository; private progress reports and generated device artifacts are excluded.

The current code includes:

- A CPU-only nearest/bilinear image-scaling command with deterministic input, bounded P6 PPM file support and a truthful completed-output status snapshot.
- An optional X11 preview with a HUD, method/backend/output controls, matched 1:1 crops and actual-window capture. A virtual display does not establish physical-display or handheld compatibility.
- A C++20 profile registry and bounded, deterministic mock scheduler with explicit producer/consumer ownership and deadline fallback.
- A standalone nearest/bilinear Vulkan compute reference, image captures, raw timing CSV and versioned JSON results.
- Read-only host diagnostics and schemas that keep simulation, software Vulkan and physical GPU observations distinct.
- Host tests, independent shader-correctness checks and CI definitions for host and software-Vulkan modes.

There is no NPU model execution, game interception, installed Decky plugin or target-handheld validation yet. The mock's virtual ticks are not measurements. Mesa lavapipe results are CPU software-rendering evidence, not AMD graphics performance. The storage-buffer shader is a reference control, not an optimized Gamescope texture scaler.

## Build and run

See [development setup](docs/development.md) for the tested Debian cloud helper and ordinary Linux prerequisites. With CMake, Ninja, a C++20 compiler, Python and the test dependencies installed:

```sh
python -m pip install --require-hashes -r requirements-dev.lock
cmake -S . -B build -G Ninja -DDOCKSR_ENABLE_VULKAN=OFF
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
./build/bin/docksr-mock --enable --scenario late-consumer
python scripts/docksr_detect.py
mkdir -p results
./build/bin/docksr-scale --generate --output results/cpu-4k.ppm \
  --size 3840x2160 --filter bilinear --dump-status-json results/cpu-status.json
```

For a host with Vulkan development files and glslang, configure with `-DDOCKSR_REQUIRE_VULKAN=ON`. A selected Vulkan ICD must also be available at runtime.

```sh
./build/bin/docksr-bench --probe
./build/bin/docksr-bench --input 1280x720 --output 3840x2160 \
  --filter bilinear --warmup 2 --iterations 10 --artifact-dir results/4k-bilinear
python scripts/run_baselines.py --binary build/bin/docksr-bench \
  --output-dir results/baseline-matrix
```

Use a new artifact directory for every run; existing captures are protected. The matrix retains command, source/binary/shader identity, raw samples and validated results. It does not measure game FPS, NPU work, power or perceptual quality.

## Direction

The primary docked destination is 720p→4K SDR. A standalone buffer/NPU proof and useful 720p→1080p reconstruction come first. Compact neural correction plus GPU composition is a candidate to measure, not a promised speedup. Expensive training and game integration wait for real inference, interop and whole-system evidence.

- [Architecture and MVP gates](docs/architecture.md)
- [AMD interop audit](docs/interop.md)
- [Benchmark interpretation](docs/benchmarks.md)
- [Pinned upstream evidence](notes/UPSTREAM.md)
- [Telemetry contracts](schemas/README.md)
