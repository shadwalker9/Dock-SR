# R005-G0A: evidence and model readiness

Gate-0A provides provenance, bounded ONNX inspection, CPU reference inference and a separate future hardware-evidence contract. It does not execute an NPU or authorize Gate-0B, driver work, training or game integration. **Infrastructure is host-tested; SESR-specific graph/reference validation is blocked by artifact download.** See [acquisition evidence](model-acquisition.md).

## Optional host environment

The C++ application and smoke launcher do not depend on ONNX. The analysis tools use a separate hash-locked environment: ONNX 1.17.0, CPU ONNX Runtime 1.20.1, NumPy 1.26.4 and their pinned dependencies. CPython 3.12/Linux x86_64 is tested; the setup helper supports CPython 3.10–3.12 wheels. These versions are a reproducible host reference stack, not AMD's Vitis AI runtime or an operator-support guarantee.

```sh
bash scripts/setup_gate0.sh .venv-gate0
.venv-gate0/bin/python tests/test_gate0_schemas.py -v
.venv-gate0/bin/python tests/test_onnx_inspect.py -v
.venv-gate0/bin/python tests/test_onnx_reference.py -v
```

On the prepared cloud machine the environment is `/workspace/.venvs/docksr-gate0`. Retained native tools still activate through the two existing cloud env files. A normal `BUILD_TESTING=ON` build runs schema tests with existing dev dependencies; set `DOCKSR_ENABLE_GATE0_TESTS=ON` and select the optional environment's `Python3_EXECUTABLE` to add inspector/reference tests. Missing ONNX dependencies return explicit nonzero errors from the tools; no ordinary application target imports them.

```sh
cmake -S . -B build-gate0-host -G Ninja -DDOCKSR_ENABLE_VULKAN=OFF \
  -DDOCKSR_ENABLE_GATE0_TESTS=ON -DPython3_EXECUTABLE="$PWD/.venv-gate0/bin/python"
cmake --build build-gate0-host --parallel 2
ctest --test-dir build-gate0-host --output-on-failure
```

## Provenance and validation

`models/sesr-m7-256.provenance.json` pins the intended AMD model repository, source/license evidence and separately advertised versus locally measured artifact hashes. Unknown facts remain null. It records source-code, model-weight, AMD-runtime and training-data rights independently. Its current redistribution decision is **unresolved**; weights and datasets are not in Git or the smoke package.

```sh
.venv-gate0/bin/python scripts/validate_gate0.py provenance models/sesr-m7-256.provenance.json
.venv-gate0/bin/python scripts/validate_gate0.py hardware tests/fixtures/gate0_hardware_not_run.json
```

Validation checks JSON Schema and semantic consistency, including evidence references, actual/advertised hashes, sample counts, nearest-rank quantiles and critical-operator counts. It always reports `hardware_execution_verified=false` and `license_clearance_verified=false`. A structurally valid statement does not prove that its observations occurred or establish legal rights. The positive future-NPU fixture is prominently marked synthetic and exists only to test constraints; it is not a benchmark.

Selected fields from validating the current candidate record:

```json
{"status":"VALID","kind":"provenance","hardware_execution_verified":false,"license_clearance_verified":false}
```

## Graph inspector

```sh
.venv-gate0/bin/python scripts/onnx_inspect.py /path/to/owned-or-pinned.onnx \
  --output /private/new-inspection.json
```

The report contains the actual file SHA-256, IR/opsets, graph inputs/outputs and tensor types/static/symbolic dimensions, domain/operator histograms, quantization markers, initializer statistics, external-data references, unresolved conditions, tool versions and UTC inspection time. It emits `GRAPH_INSPECTION` evidence with NPU compatibility `NOT_EVALUATED`. It does not execute operators, perform shape inference or expose initializer tensor values.

Selected fields from the executed owned-fixture inspection (not SESR):

```json
{"status":"INSPECTED","evidence":"GRAPH_INSPECTION","model":{"filename":"tiny_model.onnx","sha256":"a727c297a0ab739e1e0f6d47847bee6958be09c8e6067d5de0cd624abd246cc9","size_bytes":341},"scope":{"inference_executed":false,"npu_compatibility":"NOT_EVALUATED","external_data_loaded":false}}
```

The CLI parses in an isolated worker with bounded file/report/message/node/depth budgets, a 30-second deadline and 1 GiB address-space limit. External tensors are reported **UNREAD** and never loaded; unsafe absolute/traversal/URI locations or duplicate external metadata keys fail. Multiple tensors can correctly refer to one external weights file. New output JSON files are private and never overwrite an existing destination. The direct Python API has byte/structure budgets but is not an execution sandbox; use the CLI for the worker limits.

## CPU reference

```sh
.venv-gate0/bin/python scripts/onnx_reference.py /path/to/owned-or-pinned.onnx \
  --output-dir /private/new-reference --layout NCHW --warmup 2 --samples 5
```

Use the layout appropriate to the inspected model; it is a caller declaration, not a transformation. `UNSPECIFIED` is the default. `--input TILE.npy` accepts a bounded numeric array without pickle, implicit transposition or dtype conversion. Otherwise a deterministic raw tensor is generated. Static dimensions come from the graph; symbolic input/output dimensions require explicit `--shape`/`--output-shape` comma-separated overrides. An override may not replace a static graph dimension. No RGB normalization, channel order or natural-image preprocessing is inferred from a filename.

The first runner supports one numeric input/output and standard ONNX domains only. External weights, custom domains, nested graphs, functions, training graphs and sparse initializers are rejected before session creation. It passes inspected bytes directly to a sequential single-thread `CPUExecutionProvider` session. Inputs/outputs have shape/dtype/finite checks and byte limits; unexpected identity results fail unless `--allow-identity` is explicitly requested. Reports identify session initialization separately from warmups/measured inference and record model/input/output hashes, preprocessing assumptions, providers and comparison policy. The inference engine is not a hostile-model sandbox: internal graph allocations/runtime calls are not separately capped. Use supplied, owned or reviewed pinned models.

The new 0700 output directory contains 0600 `input.npy`, `output.npy` and `report.json`. Existing directories are protected; failed attempts do not leave a success artifact. Repeats within one CPU run must be bit-identical. Host-session reproducibility is independently tested on the owned fixture, not asserted for every graph/provider/platform. The default future comparison policy is `atol=1e-6, rtol=1e-5`; real NPU tolerances must be declared and justified for that graph/quantization rather than assumed from these host defaults.

Current retained evidence is under ignored `results/session-007/owned-reference/`: two fresh CPU CLI sessions on an owned Resize+Add graph agree with an independent NumPy `repeat + 0.125` result. That is **REAL_CPU**, not SESR accuracy, image quality, game FPS or NPU performance. No rights-cleared natural-image inputs were supplied, so natural-image references are NOT RUN.

Selected fields from an executed owned-fixture CPU report:

```json
{"status":"PASS","evidence":"REAL_CPU","runs":{"warmup_count":2,"sample_count":5,"successful_inferences":7,"failed_inferences":0},"provider_assignment":{"configured":["CPUExecutionProvider"],"active":["CPUExecutionProvider"],"npu_executed":false}}
```

With the optional packages absent, the CPU CLI instead returns exit code 1 and selected fields `{"status":"NOT_RUN","evidence":"NONE","error":{"code":"OPTIONAL_DEPENDENCY_MISSING"},"npu_executed":false}`. These excerpts omit other report fields; the complete retained JSON is authoritative.

## Future hardware evidence and compatibility

`hardware-evidence.schema.json` is a new document contract; `runtime-status.schema.json` and existing clients are unchanged and still refuse real NPU activation. The future contract represents NOT_RUN/null templates, detection-only `NPU_READY`, explicit failures/fallbacks and potential hardware measurements. `NPU_ACTIVE`/`REAL_NPU` require target physical XDNA2 identity, verified non-identity correctness, critical graph assignment to NPU, reference/artifact hashes, measured samples and provenance. Host/mock/software/CPU fallback claims cannot satisfy that branch.

Transfer/synchronization/copy counts, queue/drop counts, GPU work and package/whole-device versus isolated NPU power have optional explicit provenance. Their presence is not measurement proof. Validation does not load referenced evidence files, contact a device or issue an execution attestation.

Gate-0B scheduling/payload/adapter/corpus/interop scaffolding is proposed next work only. The immediate next task is to unblock the exact SESR artifact, inspect it and attempt the same CPU reference without changing its graph to manufacture support. Hardware Gate 1 remains separately authorized device work.
