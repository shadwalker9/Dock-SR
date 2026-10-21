# DSR011 bounded inference worker

The native `docksr::inference::Worker` is a model-independent producer/consumer
boundary around the existing `FrameScheduler`. It is not another presentation
scheduler, a Gamescope attachment, a socket service or a physical NPU backend.
The interface uses one trusted owner thread; it does not make concurrent calls
thread-safe. See [full-frame reference](fullframe-reference.md) and
[exact-3× fixture](espcn-contract.md) for the separate host model experiments.

## Identity, tensors and ownership

[The typed interface](../include/docksr/core/inference_worker.hpp) and
[JSON schema](../schemas/inference-worker.schema.json) carry session, frame,
configuration generation, model ID/SHA-256, trace ID, source geometry/format,
tensor shape/dtype/layout/byte strides, ownership, submit time and deadline.
Expected output geometry/format/shape/dtype/layout is also required, allowing
output storage to be reserved before starting an inference request. Optional
tile metadata includes source location, core, four halo sizes and intended
output placement. Tile stitching and model-specific scale checks belong to the
frame adapter, rather than being guessed by this generic worker.

This first implementation accepts batch-one rank-four NCHW/NHWC RGB/RGBA
contiguous host tensors, `uint8`, `int8` or `float32`, with dimensions at most
8192 and each tensor at most 64 MiB. Nonfinite float inputs/outputs are rejected.
The only ownership mode is `TRANSFERRED_HOST`; raw FD/borrowed GPU or NPU
allocation import is not implemented. Actual model SHA and graph compatibility
must still be verified by the backend; metadata validation alone is not that
verification.

Default limits are two in-flight entries, 64 MiB owned input-vector capacity,
128 MiB reserved result storage and 64 MiB per tensor. Capacity, rather than
only vector size, counts against owned storage budgets. Maximum slot count is
64. The implementation separately tracks output reservation and actual owned
result capacity: reserving a future output is not a measured allocation.

## Lifecycle and deadlines

`submit → start_next → complete → consume → release` deliberately separates
admission, producer execution, completion, exact consumer acquisition and final
release. Request frame IDs must increase within a worker lifetime. A result is
accepted only for its exact trusted ticket and matching session/frame,
configuration, model ID/hash and trace. Wrong-session, stale-generation,
duplicate, malformed, out-of-order or oversized outputs cannot be consumed as
another frame. A consumer must supply the exact session/frame/generation again.

Timestamps are unsigned monotonic nanoseconds in one shared clock domain;
wall-clock timestamps and backward time are rejected. Completion at the exact
deadline is late. The owner supplies time; the generic scheduler itself reads
no physical clock. Simulated tests use explicitly simulated values and never
turn those values into measured latency.

Unstarted expired/invalidated jobs may be cancelled, and ready output that no
consumer acquired may be discarded. A deadline, configuration change or
shutdown **never frees an active producer's input or an acquired consumer's
output**. Running entries remain until their exact completion acknowledges
producer stop; consumer-owned storage remains until explicit release. Shutdown
rejects new admission and waits for these acknowledgements. An explicit trusted
quiescence acknowledgement means every producer and consumer stopped accessing
memory; elapsed time alone does not prove quiescence. The owner must keep the
`Worker` object alive until active views are released or quiescence is established.

`consume` is not physical frame presentation. No method in this library marks
a frame displayed, and all serialized results have `presented=false` and four
NPU fields fixed false. The eventual Gamescope adapter still needs its own
resource/fence and presentation ordering proof.

## Backends and evidence

- `UnavailableBackend` returns invalid `NOT_RUN` without waiting.
- `DeterministicMockBackend` produces bounded deterministic tensors tagged
  `SIMULATED`, including explicitly assumed timing. It does not run a model.
- `CpuReferenceBackend` invokes a trusted executor callback during `execute`.
  Successful receipts require exact identity and `CPU_REFERENCE / REAL_CPU`;
  the wrapper never relabels a mock/cached receipt as CPU inference. Missing,
  throwing or unstarted executors return invalid `NOT_RUN`; actual runtime
  failures may retain `REAL_CPU` only when the executor established execution.
- `VitisAiNpuBackend` and `FutureXrtBackend` are documented `NOT_IMPLEMENTED /
  NOT_RUN` contracts only. Their names are not usable success-producing backends.

The separate `docksr-worker-reference` lab executable demonstrates the actual
CPU callback using an argv-only bounded child process and the existing
`CpuReferenceSession`, with current model hash/signature checks and raw numeric
host staging. It completes, consumes and releases the matching native request.
The child is reaped before producer ownership is retired, including timeout.
This is a host lab bridge with process/session startup per job, not a persistent
production worker or a Decky per-frame transport. The full-frame SESR tool
separately reuses one session and preallocated buffers across all its tiles.

## Transaction ledger

The result ledger separates source and inference logical payload, tensor
preparation, counted caller-visible host copies and direction/scope, tile work,
stitch/crop bytes, owned-array/vector high-water accounting and observed host
intervals. Runtime-internal copies/allocations remain `UNKNOWN`; physical DDR
traffic and GPU upload remain null. CPU-only or mock inference cannot claim GPU
upload or zero-copy inference.

For an unavailable/unstarted failure, logical source/inference fields describe
the expected tensor payload, not completed work; `NOT_RUN` and the observed copy
count must be retained. Executed backends can report total logical operands
across their actual repeated calls. The lab CPU bridge executes twice to verify
repeatability, so its inference operand totals include both calls. These totals
must not be confused with the one-input-plus-one-output payload in
`Result.logical_bytes` or added indiscriminately to overlapping copy categories.

Valid result payload and copy-count consistency are checked before accepting
output. The worker derives submit-to-complete duration from accepted timestamps
and fills complete-to-consume duration only on actual consumer acquisition.
Inference duration must fit within its transaction interval. Backend timing
classification must match `SIMULATED` or `OBSERVED_HOST_CPU`. Caller-visible
high-water accounting is not process RSS and excludes unknown runtime internals.
The CPU bridge explicitly counts raw file staging; it is not the intended final
GPU/NPU transport. See [payload arithmetic](payload.md) for the corrected ideal
image budget, which is distinct from this actual transaction accounting.

## Verification

The native tests cover admission/storage limits, tensor signatures, monotonic
time, deadlines, exact identities, stale/duplicate/out-of-order results, held
producer/consumer memory, configuration changes, shutdown/quiescence, nonfinite
float data, backend evidence and ledger mismatches. `--emit-json` serializes
simulated/failed observations only. The Python harness validates those bytes
against the schema plus consumer arithmetic invariants and deliberate negative
mutations, including false NPU/presentation claims. A valid schema document is
not an execution attestation. Actual CPU bridge execution has its own optional
Gate-0 test; no model/ONNX dependency is added to the native library.

```sh
ctest --test-dir build-host -R 'inference_worker' --output-on-failure
```

The source, contract, schema and host tests prepare a replaceable inference
boundary. Physical NPU operator placement, graphics sharing, neural result
consumption in a presented game frame and whole-device cost remain unverified.
