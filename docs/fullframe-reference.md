# DSR011 complete-frame SESR CPU reference

`scripts/sesr_fullframe.py` extends the existing bounded
`onnx_reference.CpuReferenceSession`. It processes a deterministic original
1280×720 RGB8 frame through the unchanged owner-supplied AMD SESR-M7 artifact,
assembling **2560×1440 RGB8, native 2×**. It is a host correctness reference,
not an exact-3× production model, game pipeline, NPU benchmark or quality result.
Model bytes, inputs, outputs and diagnostic reports remain outside Git.

## Exact artifact and shared runtime policy

The required file is 107131 bytes, SHA-256
`63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1`,
from the established AMD publisher revision
`edbe46281e894e31da3f42aa353db1e04a50f00a`. The bounded importer identity
check runs before runtime initialization; the independently inspected bytes
must match again before initialization. The graph is never rewritten.

`CpuReferenceSession` reuses the existing inspector, numeric shape/byte limits,
single-I/O policy, standard-domain checks and single-thread sequential
CPUExecutionProvider configuration. Its reusable `run(input, output_buffer)`
supports a caller-owned output via CPU I/O binding, checking shape, dtype,
contiguity, writability and non-aliasing. The original CLI uses this same class;
its input-NPY validation still precedes native session initialization. No ONNX
dependency is added to the ordinary application.

## Receptive-field and halo derivation

The actual graph's longest image-dependent path is:

```
5×5 head Conv     radius +2
seven 3×3 Convs   radius +7
5×5 tail Conv     radius +2
maximum radius           11 input pixels
```

All convolutions have stride 1, dilation 1 and explicit symmetric same padding.
The shorter residual branch has radius 4, so Add takes the maximum dependency
bound rather than adding branch radii. Q/DQ and ReLU are pointwise. Final CRD
DepthToSpace(2) maps an output coordinate to floor(coordinate/2), without
expanding the low-resolution neighborhood. The conservative structural bound
is therefore **23×23, halo 11**. Unsupported spatial operators, layouts,
strides, dilations or padding are rejected rather than assigned a guessed halo.

A fixed 256 tile has a usable 234×234 low-resolution core. Row-major coverage
requires six columns and four rows: **24 inference calls/frame**. The last
column keeps 110 source pixels and the last row keeps 18. Each ordinary tile
crops 22 high-resolution pixels from its top/left halo; partial or shifted
cores have explicitly adjusted crop offsets. The manifest records input
origins, source cores, output crops and destination placements.

Source coordinates outside the image are reflected without duplicating the
edge pixel; a one-pixel extent repeats its only pixel. This defines an extended
source boundary policy. It is **not** equivalence to a variable-size network
that applies zero padding independently at every layer at the original frame
edge. No variable-size SESR graph is created or executed.

## Assembly, buffer reuse and evidence

RGB8 is encoded exactly as pixels minus 128, once per frame. A reflected gather
fills one reusable INT8 input tile. One initialized CPU session fills one
reusable 512² INT8 output. Cropped output is decoded by adding 128 directly into
the preallocated stitched RGB8 frame. Original source pixels are preserved;
pre-sharpening, normalization and implicit layout conversion are absent.

A source-core coverage map rejects overlap and unwritten positions before an
output can be published. Independent tests use a subpixel-discriminating
producer and direct coordinate goldens, rather than reusing the placement
algorithm as their expected result. Tests also cover partial corners, shifted
grids, reflected edges, malformed dependency semantics, input aliasing and
actual CPU session/I/O-buffer reuse on an owned ONNX fixture. These contract
fixtures are separate from execution of the real SESR artifact.

Actual SESR evidence compares two complete default-grid executions and another
grid shifted 13/17 source pixels. The full RGB8 frames agree bitwise across all
11,059,200 components. A separate shifted-patch comparison has 651468 equal
safe components at halo 11; reducing the retained safety by one pixel produces
a counterexample with 27 differing INT8 components, maximum difference 1. These
are bounded empirical checks, not a proof over every input/provider.

## Transaction accounting

For the 24-tile 720p frame:

| Item | Logical bytes/count |
|---|---:|
| Retained RGB8 source | 2,764,800 bytes |
| Model input payload, all tiles | 4,718,592 bytes |
| Model output payload, all tiles | 18,874,368 bytes |
| Stitched RGB8 output | 11,059,200 bytes |
| Discarded output capacity | 7,815,168 bytes |
| Counted gather and decode/stitch operations | 48 |
| Counted gather/stitch materialized payload | 15,777,792 bytes |

The accounting categories are **not additive**. Tensor-preparation fields
already include the input gather that also appears in `host_copy_bytes`.
`host_copy_count` counts the specified caller-visible materializations, not
native memcpy calls or every hidden runtime copy. Separate deduplicated image
operand totals count source encoding, input gather and crop/decode/stitch once:
18,542,592 logical bytes read and the same number written per frame. They
exclude index/coverage work and model internals, and are not DDR observations.

`crop_bytes` is unused model-output capacity; cropping is a view and does not
copy/read all discarded bytes. `gpu_upload_bytes=0` means this CPU-only path
performs no GPU operation, not that a future upload costs zero. Overlap work is
separated from reflected edge padding: 170940 repeated in-image input pixels
and 480324 padded input pixels, 651264 extra processed pixels versus the frame.

The accounted high-water is 19,824,640 bytes for simultaneously live named image,
index and coverage arrays plus the largest shared finite-validation mask. It
is **not process RSS or an ORT/native allocator peak**. Runtime internals,
temporary ufunc implementation storage, source generation, diagnostics,
hashing, serialization and Python metadata are explicitly excluded. Diagnostic
seam comparison additionally retains an 11,059,200-byte frame copy and a 15360-byte
row-difference buffer outside the ordinary transaction scope.

Reports retain initialization separately from frame wall time, encoding,
preparation, inference and stitch timings. Only 2..10 frame repeats are allowed;
raw observations are retained without claiming meaningful p95/p99 tails. The
pipeline has no presentation consumer/deadline and leaves those measurements
null. Native worker accounting separately handles lifecycle/deadline failures;
an exception here does not publish an assembled success artifact or imply zero
runtime work.
Requested seam checks must pass before any output directory is published. A
shifted-grid or safe-patch mismatch returns `FAILED` with a nonzero CLI exit
status. An explicitly skipped seam check remains `NOT_RUN` in the report.

## Reproduce

Use the existing optional SDK; the output parent must already exist, be owned
and private, and be outside every Git checkout. The destination must be new.

```sh
/workspace/.venvs/docksr-gate0/bin/python scripts/sesr_fullframe.py \
  /workspace/DockSR-model-cache/manual-sesr-010/sesr_nhwc_int8_256x256.onnx \
  --output-dir /workspace/DockSR-model-cache/session-011/NEW_FULLFRAME_RUN \
  --samples 2
/workspace/.venvs/docksr-gate0/bin/python tests/test_sesr_fullframe.py -v
/workspace/.venvs/docksr-gate0/bin/python tests/test_onnx_reference.py -v
```

The private result directory contains source/output NPY arrays and a complete
report with model/input/output hashes, placement manifest, call/session counts,
transactions and seam observations. The retained `fullframe-001` and fresh
`fullframe-002` evidence are host CPU execution only. Physical XDNA2 inference,
NPU operator placement, game/4K presentation, efficiency and model distribution
clearance remain separate gates.
