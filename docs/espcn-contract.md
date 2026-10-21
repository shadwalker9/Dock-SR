# Exact-3× owned ONNX model contract

DSR011 task B implements a **HOST-VERIFIED MODEL CONTRACT**, with every generated
graph labelled **UNTRAINED_MODEL_FIXTURE**. It is not a trained super-resolution
model, an image-quality result or an NPU benchmark. No third-party checkpoint,
training data, FSR assets or AMD model bytes are used by the generator.

## Graph and provenance

`scripts/espcn_fixture.py` generates this deliberately minimal topology:

```text
FLOAT32 [1,3,256,256]
  → Conv 1×1, 3→6 channels → Relu
  → Conv 1×1, 6→27 channels
  → DepthToSpace(blocksize=3, mode=DCR or CRD)
FLOAT32 [1,3,768,768]
```

Both convolutions remain at low resolution. The graph has two Conv, one Relu and
one DepthToSpace node, 213 deterministic float parameters, and no custom domains
or external data. Its sparse dyadic weights/biases make input color, activation
sign and subpixel position distinguishable with binary-exact fixture values.
The 1×1 topology has no spatial neighborhood; it tests the subpixel execution
contract and cannot represent a useful trained spatial reconstruction model.
It does not reproduce the compute cost or quality of a production ESPCN.

The final pre-shuffle depth is **3×3²=27**, not 81. A literal expression in R-007
adds an extra factor of three; the handoff's explicit 27-channel requirement is
correct. ONNX DepthToSpace consumes NCHW. The optional NHWC boundary variant
inserts `[0,3,1,2]` and `[0,2,3,1]` Transpose nodes around the same NCHW graph.

The owned fixture uses standard ONNX **opset 17 / IR 8**. Opset17 follows the AMD
deployment recommendation quoted by the controlling handoff; the local ONNX
schema supports these operators. This is not proof that the exact graph compiles
or runs on Vitis AI/XDNA2. The unrelated unchanged AMD SESR remains opset 19.

The generator runs ONNX checking, strict shape inference and the existing graph
inspector. It records graph signatures, histogram, byte size, model SHA-256,
generator-source SHA-256, layout/mode and limitations in `manifest.json`.
Generated weights are original fixture constants, not learned parameters.
Formal project licensing remains pending; this does not select a license.

The destination must be new, outside all Git checkouts, with a user-owned parent
that is not group/world writable. Directory/files are 0700/0600. Only the
generator, tests and documentation belong in source control.

## Independent mapping oracle

For output color `c∈[0,2]`, source position `(y,x)`, and subpixel offsets
`dy,dx∈[0,2]`, the independent scalar oracle assigns:

```text
DCR: out[n,c,3*y+dy,3*x+dx] = pre[n,(dy*3+dx)*3+c,y,x]
CRD: out[n,c,3*y+dy,3*x+dx] = pre[n,c*9+dy*3+dx,y,x]
```

`scalar_pixel_shuffle` uses indexed loops rather than ONNX Runtime, reshape or
transpose. A separate closed-form scalar convolution oracle computes expected
pre-shuffle values without reading graph weights or calling the generator.
Thus incorrect export weights/channel assignments do not silently become their
own expected result. Hand-derived positions and element conservation supplement
full CPU comparisons. Swapped RGB channels, wrong DCR/CRD selection and misplaced
subpixels differ on the signed owned input pattern.

Actual CPU execution goes through existing `onnx_reference.run_reference`,
retaining its model restrictions, tensor bounds, provider-only CPU checks,
repeatability protections and private input/output reports. It is not a second
general-purpose inference runner.

## Layout and byte costs

The actual fixture is FLOAT32. Do not report its I/O as the theoretical INT8
tile payload in R-007.

| Buffer | FLOAT32 fixture bytes | RGB8/INT8 logical counterpart |
| --- | ---: | ---: |
| Input 256×256×3 | 786432 | 196608 |
| Pre-shuffle 256×256×27 | 7077888 | 1769472 |
| Output 768×768×3 | 7077888 | 1769472 |

For contiguous FLOAT32, input NCHW strides in bytes are
`[786432,262144,1024,4]`; output NCHW strides are
`[7077888,2359296,3072,4]`. The full output's contiguous NHWC strides are
`[7077888,9216,12,4]`. These are memory layouts, not DDR-traffic measurements.

`convert_layout` makes an explicit, owned contiguous host copy, records actual
array strides and one copied payload, and leaves physical DDR bytes null. A
256-input plus 768-output pair of host conversions copies 786432+7077888 bytes;
its logical read-plus-write volume is twice that sum. Provider-internal costs
of graph Transpose operators are not instrumented or inferred to be zero.

The FLOAT32 full 720p→4K output would contain 99532800 bytes and exceeds the
existing bounded CPU runner's 67108864-byte output limit. That optional shape
is NOT_RUN; the limit is preserved. The required 256→768 contract is verified.

## Reproduce

Use the separately prepared Gate-0 SDK. All output directories must be new and
outside Git. For a DCR graph:

```sh
/workspace/.venvs/docksr-gate0/bin/python scripts/espcn_fixture.py \
  --output-dir /workspace/DockSR-model-cache/session-011/NEW_DCR_FIXTURE \
  --mode DCR --layout NCHW
/workspace/.venvs/docksr-gate0/bin/python tests/test_espcn_fixture.py -v
```

The generator also accepts `--mode CRD` and `--layout NHWC`; dimensions 1..256
allow small independent mapping cases without changing the required default.
After generation, the ordinary inspector/reference CLIs may inspect/run the
model. No NPU runtime is loaded.

To reproduce an independent comparison from the repository root:

```sh
PYTHONPATH=scripts /workspace/.venvs/docksr-gate0/bin/python - <<'PY'
from pathlib import Path
import numpy as np
import espcn_fixture as fixture
import onnx_reference as reference
destination = Path('/workspace/DockSR-model-cache/session-011/NEW_VERIFIED_FIXTURE')
fixture.write_fixture(destination, mode='DCR')
source = fixture.sentinel_input()
reference._write(destination/'owned-input.npy', lambda f: np.save(f, source, allow_pickle=False))
reference.run_reference(destination/'model.onnx', destination/'reference',
    input_path=destination/'owned-input.npy', layout='NCHW', warmup=2, samples=3)
actual = np.load(destination/'reference/output.npy', allow_pickle=False)
np.testing.assert_array_equal(actual, fixture.scalar_fixture_oracle(source, mode='DCR'))
PY
```

## Observed DSR011 host evidence

Six test methods pass, including both full 256 modes, independent scalar goldens,
hand-derived positions, RGB/subpixel negative comparisons, NHWC graph wrappers,
host strides/copies, deterministic generation and destination/input guards.
Three separately retained full 256 variants each passed two warmups and three
bitwise-repeat-identical CPU measurements plus the independent oracle:

| Variant | Model bytes | Model SHA-256 |
| --- | ---: | --- |
| NCHW DCR | 1640 | `be05b65bd65cc3b78ce93f0655db22c8e64a7f6833b5870826beb78c3b7bb4ab` |
| NCHW CRD | 1640 | `79cf2d1ba806b43ef6a593223c6911e790c4e6baef70dcf43ea1d4a0c2cbfc40` |
| NHWC DCR wrappers | 1754 | `0202148508d932c1c8cb1562d819f07986fb6694a13a2b809bb93b08d84f8ef6` |

NCHW DCR and CRD generated twice with identical bytes per mode. Private evidence
is `/workspace/DockSR-model-cache/session-011/espcn-summary.json` and associated
fixture/reference directories. These original FLOAT32 constants and CPU timings
do not establish INT8 compilation, image quality, physical NPU acceleration,
game presentation, real frame cadence or whole-device power.

A8W8 and XINT8 remain prospective deployment configurations marked
**NOT_VALIDATED**. Quantization accuracy, compiler partitioning and actual
operator placement require the exact future graph/runtime/device; merely adding
QDQ nodes would not settle those questions. No quantized performance claim is
made here.
