# Telemetry contracts

These schemas use JSON Schema draft 2020-12 and `schema_version: "1.0.0"`.
Their URN identifiers are local contract names; validation needs no network fetch.

- `detection.schema.json` describes `scripts/docksr_detect.py` inventory output.
  Missing paths, missing executables, permission errors, failed commands, and
  unrun capability checks remain distinct. Inventory always reports
  `npu_ready: false` and `hardware_validated: false`. A Vulkan summary cannot
  establish exact buffer import/export support or successful NPU execution.
- `vulkan-benchmark.schema.json` describes the isolated spatial compute baseline.
  CPU Vulkan devices must use `vulkan_software`; physical integrated/discrete
  devices use `vulkan_hardware`; virtual/other devices use `vulkan_unknown`.
  These classes describe a Vulkan dispatch, not game performance or GPU/NPU
  interoperability. Power, NPU time, game render time, and game FPS stay null.
- `mock-state.schema.json` describes virtual scheduler runs, profile listings,
  and error reports. Its simulated clock has no physical duration. Validation
  applies only to the simulation tuple; hardware remains unvalidated.
- `runtime-status.schema.json` matches the typed CLI/preview status snapshot.
  `CPU_REFERENCE_ACTIVE` uses `REAL_CPU`; `SOFTWARE_VULKAN` is distinct from
  `GPU_BASELINE_ACTIVE` / `REAL_GPU`. Completed-output counts and actual dimensions
  must agree. Unmeasured timings remain null; this build rejects real NPU states,
  real NPU evidence, and NPU timings. Errors may retain truthful evidence of
  earlier completed output. Status age uses the same host's monotonic clock;
  structural validation cannot establish freshness or actual execution.

Benchmark JSON links `samples.csv`, containing measured iterations only. Host
timings and GPU timestamp timings are separate and use milliseconds. The
`host_scope` field identifies included work. A missing GPU timestamp appears as
null in the summary and an empty CSV field. FNV-1a hashes identify image artifact
bytes; they provide no cryptographic integrity or implementation provenance.

The schemas check structure and evidence labels. `validate_vulkan_samples` in
`tests/test_telemetry.py` also verifies linked CSV rows and nearest-rank summaries.
These checks cannot prove that a run
occurred, an artifact matches its hash, quantiles match raw samples, or a device
executed a particular workload. Functional checks must verify those facts.
Record the source revision, build/shader identity, run command, and collection
time with retained run evidence. Checked-in `tests/fixtures` are explicitly
synthetic schema examples and contain no measured performance claims.

Run the contract tests with the development Python environment:

```sh
python tests/test_detection.py
python tests/test_telemetry.py
```

Run native/CLI/window/package tests through CTest in the configured build directory;
CTest supplies their actual executable paths. Unrestricted unittest discovery does
not supply those arguments and is not a complete test command.

Install test dependencies using the repository's hash-locked
`requirements-dev.lock`. The detector itself uses only Python's standard library.
