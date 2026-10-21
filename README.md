# Dock SR

DockSR is an experimental Linux image reconstruction project targeting Ryzen AI Z2 Extreme first, with Bazzite and SteamOS as intended destinations. We are working toward a freely available, Decky-controlled scaler that improves image quality while costing less than an existing scaling solution at comparable quality. That advantage has **not** been demonstrated; this is a development prototype, not an installed gaming plugin.

## Mission

**DockSR's mission is to extend the useful life of gaming hardware through efficient, accessible, and openly developed image reconstruction technology.**

Better software can help existing handhelds, laptops and compact gaming systems remain capable for longer. We are exploring GPU and NPU cooperation to improve visual quality while preserving the performance and power budget games need. This is about the useful performance life of devices; it is not a claim to extend the physical lifespan of silicon.

We are building for the Linux gaming community with transparency, reproducible experiments, maintainability and collaboration in mind. We aim to reuse suitable existing standards, research and tooling, and document enough for others to study, improve and eventually carry the project forward. The current direction is **NPU-first**: test learned reconstruction on XDNA2 while the GPU retains preparation, composition and reliable fallback. Verified physical NPU contribution is required for the first usable NPU-targeted version; its efficiency still has to be measured.

## AI-Assisted Development Disclosure

DockSR is a human-directed project developed with substantial assistance from AI tools, including ChatGPT for technical planning, research synthesis, architecture discussions and documentation, and OpenAI Codex for software implementation, testing and development support.

Project direction, goals, approvals and release decisions remain under human oversight. AI tools are assistants; project ownership belongs to its human owner.

AI-generated or AI-assisted work is reviewed through source inspection, automated tests, reproducible experiments and, when available, physical hardware validation. This process does not mean every implementation or research claim has been independently verified, formally audited or validated on target hardware.

We disclose this process because transparency is part of DockSR's mission. We hope small teams can contribute useful technology by combining human direction, existing research and AI-assisted engineering.

## Community Use and Attribution — Licensing Pending

DockSR is being developed with the intention of becoming a freely available, openly licensed community project.

The project owner welcomes the idea of others studying, using, adapting and forking DockSR's original code and research, with appropriate attribution to **DockSR / shadwalker9** and its contributors. We ask future users and derivative projects to preserve attribution, acknowledge relevant upstream work and maintain the provenance of reused research and software.

**Formal licensing is still being finalized.** Until the applicable license files and notices are published, this statement describes the project's goals and does not independently grant redistribution or modification rights. Third-party dependencies, model weights, datasets and research materials may have separate licenses or restrictions; their rights must be evaluated independently.

Maintainer decisions still pending:

- Select a source-code license.
- Select terms for original research and documentation.
- Define attribution and notice requirements.
- Confirm third-party model, runtime, dataset and patent considerations.
- Approve public repository visibility and release readiness separately.

## What works today

**S004 standalone preview** adds a real window, matched CPU/Vulkan A/B and truthful diagnostics to the S003 scaling foundation. Read [preview commands and evidence limits](docs/preview.md), [project state](docs/PROJECT_STATE.md) and [current owner decisions](docs/DECISIONS.md) before resuming. CPU neural references now exist; physical NPU execution, game integration and Decky remain separate gates.

**S005-PRE smoke preparation** packages the existing tools for non-root, relocatable Linux x86_64 checks. See [device-day instructions](docs/device-day.md) and [maintainer continuity](docs/MAINTAINER_CONTINUITY.md). This does not establish physical-display or SteamOS/Bazzite acceptance. Source checkpoints are backed up to this repository; private progress reports and generated device artifacts are excluded.

**R005-G0A evidence tooling** adds optional [ONNX inspection and CPU references](docs/gate0.md), pinned model provenance and future hardware-evidence validation. The owner-provided SESR artifact is independently verified and executes on CPU; the unchanged model is fixed2×, not a production3× model. These tools do not activate an NPU or change ordinary application dependencies.

**DSR011 NPU-first host preparation** adds a [full-frame SESR reference](docs/fullframe-reference.md), an [owned exact3× ONNX contract](docs/espcn-contract.md), a [bounded inference-worker interface](docs/inference-worker.md) and [physical-probe preparation](docs/npu-device-probe.md). All neural execution here is CPU-only. The generated3× graph is an untrained FLOAT32 fixture; INT8 compilation, image-quality advantage, physical NPU contribution and presentation remain unverified. The existing Gamescope build-only experiment is preserved separately.

**DSR012-P P-A/P-B laboratory preparation** adds [offline benchmark analysis](docs/benchmark-laboratory.md) through the existing hardware-evidence contract and an expanded [read-only preflight/Linux deployment map](docs/STEAMOS_INTEGRATION_MAP.md). Synthetic lifecycle, statistics and power guards are tested; physical H1/H2 execution harnesses, collectors and the complete device-day kit remain later checkpoints. No NPU or gaming performance is established.

**R005-G0B-1 host experiments** provide [deterministic scheduling](docs/scheduling.md) through the existing mock command and an exact [frame-payload calculator](docs/payload.md). Their virtual timing and logical byte counts are assumptions/calculations, not physical NPU throughput, game FPS or power measurements.

The current code includes:

- A CPU-only nearest/bilinear image-scaling command with deterministic input, bounded P6 PPM file support and a truthful completed-output status snapshot.
- An optional X11 preview with a HUD, method/backend/output controls, matched 1:1 crops and actual-window capture. A virtual display does not establish physical-display or handheld compatibility.
- A C++20 profile registry and bounded, deterministic mock scheduler with explicit producer/consumer ownership and deadline fallback.
- An event-driven scheduling experiment for 40/45/60 FPS, assumed service times, bounded queues/slots and delayed presentation; no hardware is dispatched.
- Exact logical RGB8/BGRA8/guide payload and copy-volume calculations at the target frame rates.
- A standalone nearest/bilinear Vulkan compute reference, image captures, raw timing CSV and versioned JSON results.
- Read-only host diagnostics and schemas that keep simulation, software Vulkan and physical GPU observations distinct.
- Host tests, independent shader-correctness checks and CI definitions for host and software-Vulkan modes.

There is no physical NPU model execution, live game-frame processing, installed Decky plugin or target-handheld validation yet. The mock's virtual ticks are not measurements. Mesa lavapipe results are CPU software-rendering evidence, not AMD graphics performance. The storage-buffer shader is a reference control, not an optimized Gamescope texture scaler.

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

The primary docked goal is 1280×720→3840×2160 SDR at selected 30–35 W APU profiles and 40/45/60 FPS. The secondary handheld goal is 720p→1080p at selected 15–17 W profiles. These are targets, not measured outcomes or whole-device power readings; [approved owner decisions](docs/DECISIONS.md) record the remaining cost and power goals.

A GPU-only reconstruction option is intended to remain useful when NPU assistance is unavailable or offers no measured advantage. Compact neural guidance with GPU reconstruction is a research candidate, not an implemented adaptive scaler or promised speedup. Real model inference, operator placement, buffer sharing and whole-system comparisons precede serious training and game/Decky integration. Microsoft Auto SR is a reference to study, not an established compatibility or parity claim.

Contributors can start with the build commands above, [project state](docs/PROJECT_STATE.md), [maintainer continuity](docs/MAINTAINER_CONTINUITY.md) and the focused experiment guides. Preserve source/model/data provenance and keep physical measurements distinct from simulation.

- [Architecture and MVP gates](docs/architecture.md)
- [AMD interop audit](docs/interop.md)
- [Benchmark interpretation](docs/benchmarks.md)
- [Pinned upstream evidence](notes/UPSTREAM.md)
- [Telemetry contracts](schemas/README.md)
