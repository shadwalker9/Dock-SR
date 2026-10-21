# Inference accounting and its limits

DSR011 measures host reference work and counts caller-visible buffer operations.
It does not measure physical DDR traffic, GPU/NPU transfers, package power or a
gaming throughput advantage. The existing [payload calculator](payload.md)
supplies checked integer arithmetic; the full-frame and worker ledgers attach
actual identities, operations and host durations to that arithmetic.

## Three different quantities

- **Logical payload:** the shape/dtype size of a source, tensor or output.
- **Counted caller-visible operations:** gathers, conversions, stitching and
  prototype staging file reads/writes whose payload sizes are known.
- **Unobserved internals:** NumPy/ORT/native allocator copies, cache behavior,
  compiler activation spills and physical memory-controller traffic.

These categories are not interchangeable. Tensor preparation and input gather
fields overlap with some host materialization fields; summing all fields would
double-count them. `crop_bytes` is model-output capacity discarded by cropping,
not evidence that those bytes were copied. A view has no copied pixel payload.

## Actual SESR full-frame example

The unchanged fixed2× model uses an analytically derived11-pixel halo and234²
usable core. Its720p grid needs24 fixed256² tile calls, including partial edge
cores. The [full-frame reference](fullframe-reference.md) records each placement,
crop, inference call and coverage check.

| Per-frame item | Bytes or count | Meaning |
| --- | ---: | --- |
| RGB8 source | 2,764,800 | Logical source payload |
| Aggregate INT8 model inputs | 4,718,592 | 24 complete256² RGB tiles |
| Aggregate INT8 model outputs | 18,874,368 | 24 complete512² RGB tiles |
| Stitched RGB8 output | 11,059,200 | Actual2560×1440 output |
| Discarded output capacity | 7,815,168 | Cropped model pixels, not copy traffic |
| Input gathers + decoded core writes | 15,777,792 | 48 caller-visible materializations |
| Deduplicated visible image reads | 18,542,592 | Encode, gather and retained decode/stitch operands |
| Deduplicated visible image writes | 18,542,592 | Same scoped image operands; not measured DDR |
| Accounted array/validation-mask high-water | 19,824,640 | Named simultaneously-live buffers only |

The grid includes170,940 repeated in-bounds input pixels and480,324 reflected
out-of-bounds pixel positions. Those sum to651,264 additional input positions
beyond the921,600 unique source pixels. Fixed-shape edge tiles and halo work are
therefore explicit costs; a geometric15-tile no-overlap estimate is not the
actual neural transaction. Source encoding happens once; tile input/output
storage and the initialized CPU session are reused.

The accounted high-water excludes ORT/model/native allocator internals, Python
metadata, pattern generation, file serialization and separately reported seam
diagnostic copies. It is not process RSS. GPU upload is zero operations in this
CPU-only path; no physical upload capability or latency was tested. Frame wall
times, inference-call sums and initialization are distinct. Two complete-frame
samples do not justify a p95/p99 or an XDNA2 projection.

## Native CPU bridge example

The [worker](inference-worker.md) reserves expected output storage at admission,
but a reservation is not an allocation. Actual owned vector capacities are
counted separately. Its laboratory CPU executor starts a private child process
and one CPU session per job, executes twice to verify repeatability, and returns
one useful result. This deliberately visible startup/transport cost is not a
production-performance design.

For input payload `I` and output payload `O`:

- Useful result signature payload: `I+O`.
- Two verification inferences: `2I` input and `2O` output tensor payloads.
- Four successful raw-file staging transfers: `2I+2O` payload bytes.
- Caller-visible input/output buffers, finite checks and worker-owned vector
  capacities have their own scoped accounting; model/runtime peaks remain unknown.

Initial CLI fixture loads and metadata serialization are outside the callback's
four-transfer scope. Failed jobs record only operations actually observed; a
missing receipt cannot establish child copy/inference counts. No field claims
that file I/O is a Vulkan/NPU transfer, that internal copies are absent, or that
completed/consumed output has been presented.

## Device-day decisions

Measure real complete-frame service under representative GPU load before
optimizing tile size, quantization, copies or runtime. Compare equal source,
output, quality and power conditions. If host staging dominates a correct NPU
run, investigate the provider's actual import capability; if neural compute
dominates, change the model. More queue slots or one-frame delay cannot raise
sustainable inference throughput. No current host result selects either pivot.
