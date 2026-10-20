# Reference benchmark and interpretation

`docksr-bench` is an offline headless Vulkan compute reference for packed RGBA8 nearest and bilinear resize. It produces deterministic input/output RGB PPM captures, checks all RGBA channels against a CPU reference, and saves raw timing samples plus a versioned JSON summary. The byte-domain interpolation does not apply transfer-function or premultiplied-alpha conversion. HDR and game capture are not implemented.

## Reproduce the resolution matrix

After activating the development environment and building Vulkan:

```sh
python scripts/run_baselines.py --binary build/bin/docksr-bench \
  --output-dir results/baseline-matrix --warmup 2 --iterations 10
```

This uses 1280×720 input, both filters, and 1920×1080 / 2560×1440 / 3840×2160 output. Output directories must be new. Each run retains `input.ppm`, `output.ppm`, `samples.csv` and `result.json`. A matrix manifest records source-file SHA-256 values (including the working tree), executable/SPIR-V hashes, commands, UTC collection times and result hashes. It detects source changes during the matrix. Ten samples are a smoke-run distribution, not a robust p99 gaming study.

For changing deterministic frames, run a single benchmark with `--changing-frames`. Source generation and CPU reference checks are excluded from the host dispatch timing; the JSON records its actual timing scope. The benchmark includes mapped input upload/cache work in the host scope and performs diagnostic readback. These are not a production copy-free pipeline.

## What the fields mean

- `evidence_class`: `vulkan_software` for a CPU Vulkan device; `vulkan_hardware` for an integrated/discrete device; `vulkan_unknown` for virtual/other. This is device classification, not proof of gaming or NPU readiness.
- `host_dispatch_to_completion_ms`: the measured host interval described by `host_scope` in the result. It includes orchestration and relevant mapped-buffer operations, separately from shader timestamps.
- `gpu_dispatch_ms`: timestamp-query interval when supported. On software Vulkan it is still a software-driver interval; its field name does not turn it into physical GPU data. Missing timestamps are null with a reason.
- Summaries use nearest-rank p50/p95/p99/min/max over measured iterations only. Warmups do not appear in the sample CSV. At small sample counts tail percentiles often select the same maximum sample.
- NPU time, power, game render time and game FPS are null. Their absence is not zero overhead or zero watts.
- Image/SPIR-V FNV-1a identifiers are checksums. The outer matrix manifest supplies cryptographic SHA-256 provenance; neither checksum proves perceptual quality.

`tests/test_telemetry.py` supplies structural plus linked-artifact validation. A schema alone does not prove values were measured, quantiles are correct, pixels match, or hidden copies are absent. Independent shader checks and raw evidence are required.

The shader uses storage-buffer fetches/manual interpolation. It is not an optimized sampler/Gamescope implementation and cannot establish a win over existing scalers. A later hardware benchmark must add a competitive texture-based baseline, matched quality/content and actual game/presentation cost.

## NPU and product comparison later

Before a cost-saving claim, predeclare the reference scaler/version, scene, input/internal-render/output sizes, quality floor, power conditions and primary cost metric. Compare actual real frames, frame-time tails, input latency, moving-image stability, CPU/GPU/NPU and pack/sync/compose costs, plus whole-device energy/power. Overlapped device times are not simply added as end-to-end latency. A working graph or reduced GPU busy time alone is insufficient.

The offline executable is not safe game integration. It uses a finite submission wait, but driver shutdown can still block; the test/matrix runner supplies an outer process watchdog. The deterministic mock proves ownership/fallback policy only. A real adapter requires independently bounded recovery and valid GPU/WSI ordering.
