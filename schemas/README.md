# Telemetry contracts

These schemas use JSON Schema draft 2020-12 and `schema_version: "1.0.0"`.
Their schema identifiers are local contract names; validation needs no network fetch.

Gate-0 adds `model-provenance.schema.json` and `hardware-evidence.schema.json` as
separate document contracts; existing runtime status is unchanged. Use
`python scripts/validate_gate0.py provenance models/sesr-m7-256.provenance.json`
or `python scripts/validate_gate0.py hardware RECORD.json` for schema and semantic
checks. [Gate-0 documentation](../docs/gate0.md) explains unknown versus measured
identity, synthetic fixtures, raw-sample checks and the limits of validation.
Neither a valid future record nor a license identifier is execution/rights proof.

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

## DSR012-P benchmark extension

`hardware-evidence.schema.json` optionally carries `benchmark_run`; prior records
remain valid without it. The existing backend/placement rules remain in force.
`scripts/benchmark_analysis.py` reuses Gate-0 validation and checks lifecycle
ordering, unique frame IDs, raw sample arithmetic, coverage and clock units.
See [benchmark laboratory](../docs/benchmark-laboratory.md) for the exact
percentile/1% low/deadline/energy definitions, private CLI and paired uncertainty.
Synthetic schema examples remain SIMULATED in the derived analysis. Structure
and statistical consistency do not attest execution or matched image quality.

`npu-probe.schema.json` accepts the optional `laboratory` inventory extension and
ORT module version; it continues to prohibit physical success. Missing devices,
permissions/configuration, unsupported queries and unmeasured sensors retain
meaningful unavailable states. No existing runtime activation API is changed.

## DSR013-P SteamOS readiness

`steamos-readiness.schema.json` v1.0.0 describes a checklist, not inference
measurements. `scripts/steamos_readiness.py --validate FILE` additionally enforces
reference/gate order, documentation versus device evidence, H1 proof categories,
H4 prerequisites and SteamOS-only compatibility. Its fixed NOT_ATTESTED/false
execution fields cannot claim REAL_NPU; use the existing canonical hardware
record plus independent artifacts for actual execution. Artifact authenticity is
not established by either schema. Initial hardware areas remain NOT_TESTED.
See [SteamOS readiness](../docs/steamos-first-readiness.md) and explicitly fictional
[fixtures](../tests/fixtures/steamos-readiness/README.md). No legacy schema changed.

## DSR014-H H1 laboratory extension

R-010 adds optional `user_systemd_memlock` and `installed_runtime_metadata` to
readiness inventory without changing schema1.0.0. Historical inventories remain
valid. Manager defaults are byte/infinity observations, not running-unit limits;
allowlisted local package/Python metadata never attests loaded runtime execution.
The command allowlist also permits the fixed read-only systemctl/pacman queries.

The canonical hardware schema optionally accepts `h1_run`; no second evidence
format replaces it. `validate_gate0.py` adds model/mode/provider/comparison and
lifecycle ns/ms consistency checks. The current extension deliberately prohibits
REAL_NPU/true physical-proof milestones until installed-device placement/context
adapters are validated. A raw report or simulated provider response cannot pass.
CPU_REFERENCE_PASS requires an actual CPU result and separately executed golden;
SCHEMA_EXAMPLE tests remain synthetic. See [H1 limits and commands](../docs/h1-inference-harness.md).
Legacy records without this extension retain their original guards and format.
