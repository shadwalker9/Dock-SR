# SESR-M7 candidate acquisition evidence

Updated 2026-10-20 UTC. The canonical record is [the candidate provenance manifest](../models/sesr-m7-256.provenance.json); [Gate-0 commands](gate0.md) describe validation and host execution. Current outcome: **MODEL_VALIDATED**, scoped to unchanged-artifact inspection and **REAL_CPU** single-tile reference inference. No physical NPU, whole-frame reconstruction, image-quality improvement or production readiness is established.

## DSR010 owner attachment — MODEL_VALIDATED (REAL_CPU)

The owner supplied the actual `.onnx` attachment. Existing `scripts/import_sesr.py` imported it into a new private destination, `/workspace/DockSR-model-cache/manual-sesr-010/`, outside all Git checkouts. Independently measured **107131 bytes** and SHA-256 **63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1** match the advertised artifact at official Hugging Face revision `edbe46281e894e31da3f42aa353db1e04a50f00a`, path `onnx-models/sesr_nhwc_int8_256x256.onnx`. This closes the prior acquisition blocker through the owner upload; no CDN retry was made. The receipt proves byte identity, rather than the owner's original retrieval route or legal clearance.

The existing inspector parsed the unchanged bytes successfully:

| Observed graph property | Actual value |
| --- | --- |
| Input | `input`: INT8 `[1,256,256,3]` |
| Output | `output`: INT8 `[1,512,512,3]` |
| Layout evidence | First transpose `[0,3,1,2]`, final transpose `[0,2,3,1]`: NHWC boundary tensors |
| IR / opset / domain | IR 9; standard ONNX opset 19; empty standard domain only |
| Nodes / initializers | 60 / 29 |
| Operators | Add 1, Conv 9, DepthToSpace 1, DequantizeLinear 20, QuantizeLinear 20, Relu 7, Transpose 2 |
| Quantization | Explicit INT8 I/O with Q/DQ nodes; boundary input and output scale `1.0`, zero point `0` |
| Unsupported model features | No external data, custom domains, subgraphs, local functions, training graphs or sparse initializers observed |

Preprocessing was established from the **same pinned official repository's** `onnx_runner.py`, read from an already fetched Git object and never executed. Publisher preprocessing converts OpenCV BGR pixels to RGB and subtracts `(128,128,128)`; its inference loop clips to `[-128,127]`, casts to INT8 and adds the batch dimension in the observed NHWC layout. It does **not** divide by 255. Output is centered INT8 RGB; publisher postprocessing adds 128, clips to `[0,255]`, casts to UINT8, then reverses channels for OpenCV. These operations agree with the inspected boundary Q/DQ constants. The publisher runner's general Q/DQ description is broader than its actual `run` implementation; this particular graph has unity boundary scales, so the observed implementation is consistent here.

Pinned source-text SHA-256 values are `0136fcf2ffed8e953cf614ef83b4509b9dea73f5be7a1c7a96a7a11480c37828` for `onnx_runner.py` and `19a88971827e95edcd15abead29cc844c1280c1a3e64b678257d705b7fcbf7ab` for `onnx_inference.py`. Source references and dates are in the provenance manifest. No publisher script, cached NPU binary or runtime was executed.

The existing `scripts/onnx_reference.py` then ran one newly created, owned synthetic RGB tile: red/green gradients, blue checkerboard and thin white/black lines, encoded as `RGB - 128`. ONNX Runtime **1.20.1**, ONNX **1.17.0**, NumPy **1.26.4**, Python **3.12.14**, CPUExecutionProvider only, sequential execution, one intra/inter-op thread, and disabled graph optimization produced a finite INT8 `[1,512,512,3]` output. Two warmups and three measured repeats succeeded; identical inputs produced bitwise-identical outputs, and retained input bytes were unchanged.

| CPU reference evidence | Result |
| --- | --- |
| Encoded input NPY SHA-256 | `68aefeeb9f7ca7e3d2f852925109dfd86434ad40065417df33980163421afc9a` |
| Output NPY SHA-256 | `8784d72b7b3aa2374100f9dce9fa1c05a2b886af943701118ea057c78e7e5ceb` |
| Measured host inference samples | 69.829791, 69.609140, 97.718878 ms per single 256→512 tile |
| Host session initialization | 9.989526 ms, separate from inference |
| Comparison policy | `abs(candidate-reference) <= 1e-6 + 1e-5*abs(reference)`; only same-provider repeated equality exercised |

These are cloud CPU reference observations with three measured samples. They are not target-device latency, whole-game FPS, watts, image-quality scores, a target NPU benchmark or an inferred tiled-frame throughput. Full-image reflect padding, 16-pixel overlap and tile merging from the publisher entry point were **not run**. The fixed **2×** tile model is a feasibility probe and does not implement the separate **3× 1280×720→3840×2160** Gamescope milestone.

Private cache evidence comprises `verification.json`, `inspection.json`, `preprocessing-evidence.json`, read-only pinned source-text copies, owned input tensors and `reference-composite/{input.npy,output.npy,report.json}`. Command output is also retained under ignored `results/session-010/`. No model, input/output tensor, private upload or report is in Git. License and redistribution gates below remain independent.

## Historical acquisition evidence (DSR007–DSR009)

Before DSR010, Hugging Face metadata/text and the pinned source revision were reachable, but the selected artifact redirected to **us.aws.cdn.hf.co** and proxy CONNECT returned HTTP 403. No model bytes had been acquired in those sessions, so actual identity, graph signature and real-model CPU execution were unknown then. Signed redirect URLs are not retained in source or logs. The following retry records describe that historical state.

### DSR008 focused retry — MODEL_ACQUISITION_BLOCKED

At 2026-10-20 04:39 UTC, the environment configuration read showed a different base version from DSR007, no pending draft, and `us.aws.cdn.hf.co` in the custom allowlist. DSR007's statement that this addition was only a pending draft is therefore historical. Saved configuration alone does not establish that the current runtime proxy has activated the rule; no agent-callable publication/runtime-activation control is available here.

A single normal HTTPS retrieval of the exact pinned artifact, with redirects, TLS verification, a 60-second deadline and 1 MiB cap, returned curl exit 22 / HTTP 403 without artifact bytes. Separate read-only HEAD checks returned HTTP 200 for the pinned model card and `Tunnel connection failed: 403 Forbidden` for the CDN host. The artifact remains blocked despite the saved allowlist entry. No proxy bypass, mirror, different revision or model rewrite was attempted. Graph inspection and CPU reference remain NOT RUN. Sanitized attempt/connectivity records are retained outside Git under `/workspace/DockSR-model-cache/acquisition/session-008/`.

### DSR009 bounded investigation — MODEL_ACQUISITION_BLOCKED

On 2026-10-20, the exact pinned HTTPS GET returned HF HTTP 302 to `us.aws.cdn.hf.co`, then failed at proxy CONNECT with 403 before artifact bytes. The current saved configuration still includes this CDN host; saved rules do not establish active execution-policy propagation. No callable runtime-activation control is available. This identifies the observed failure stage; CDN-origin DNS/TLS/authentication were not reached or tested.

Official no-smudge Git clone and exact-revision fetch succeeded. `git show` returned only the Git LFS pointer with the advertised identity, not model bytes. Native Git LFS 3.6.1 fetch was stopped after 60 seconds without an artifact. The canonical official batch API (`https://huggingface.co/amd/sesr-m7-256x256-tiles-amdnpu.git/info/lfs/objects/batch`) returned HTTP 200 and directs the requested object to the same CDN. A guessed batch path without `.git` initially returned 404; the canonical endpoint was then obtained from `git lfs env`. That path error does not mean the model is missing.

No exact-size candidate was found in the existing `/workspace/DockSR-model-cache` or `/workspace/.cache`; ordinary Hugging Face cache directories were absent. Other approved artifact connectors were not callable. No model copy had been supplied by the owner during DSR009. Sanitized evidence is retained under ignored `results/session-009/` and `/workspace/DockSR-model-cache/acquisition/session-009/`, without signed URLs, credentials or model bytes.

The DSR009 stop decision was to avoid further network retries until a meaningful access change or an exact owner upload. No proxy bypass, mirror, different revision or download framework was used. Graph inspection and real-model CPU reference were NOT_RUN in DSR009; the DSR010 upload and results above supersede that blocker.

## Manual fallback for future owner-supplied copies

The current attachment is already verified; no further owner download is needed for DSR010. These instructions remain available for reproducing the exact intake elsewhere.

1. Open this exact pinned URL in an ordinary browser on a network where you are authorized to download it. Save the actual `.onnx` file as `sesr_nhwc_int8_256x256.onnx`, rather than a webpage or Git LFS pointer:

   https://huggingface.co/amd/sesr-m7-256x256-tiles-amdnpu/resolve/edbe46281e894e31da3f42aa353db1e04a50f00a/onnx-models/sesr_nhwc_int8_256x256.onnx

2. Verify **107131 bytes** and SHA-256 **63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1** before upload. From the download directory, use either command block below. A mismatch must stop the import; keep the original expected identity.

Linux with Python 3 (standard library only):

```sh
python3 - <<'PY'
import hashlib
from pathlib import Path
file = Path('sesr_nhwc_int8_256x256.onnx')
if file.stat().st_size != 107131:
    raise SystemExit('Wrong size. Do not upload this file.')
actual = hashlib.sha256(file.read_bytes()).hexdigest()
if actual != '63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1':
    raise SystemExit('Wrong SHA-256. Do not upload this file.')
print('Size and SHA-256 match the pinned artifact.')
PY
```

Windows PowerShell:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $file = Get-Item -LiteralPath '.\sesr_nhwc_int8_256x256.onnx'
    $expected = '63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1'
    $actual = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($file.Length -ne 107131 -or $actual -ne $expected) {
        throw 'Wrong size or SHA-256. Do not upload this file.'
    }
    'Size and SHA-256 match the pinned artifact.'
}
```

3. Attach only that verified model file to this chat. No credentials, tokens, datasets, drivers or runtime installer are needed. The agent will independently verify the uploaded bytes again. If normal authorized download also fails on your computer, contact the environment/platform administrator with the CDN CONNECT failure details; do not use an arbitrary mirror.

## Agent procedure after an owner upload

Download the attachment with the supported file tool, then pass its actual local path to the importer. Use a new destination outside every Git checkout, with the existing private model-cache parent. Example from the repository root:

```sh
python3 scripts/import_sesr.py /path/from/upload/sesr_nhwc_int8_256x256.onnx \
  --destination /workspace/DockSR-model-cache/manual-sesr-009
```

Run the importer in the Linux/POSIX agent workspace; the owner-side PowerShell block only verifies the download before upload. The importer has no network or ONNX dependency, fixes the candidate identity, refuses a mismatch/unsafe destination/overwrite and leaves tracked provenance unchanged. A successful private receipt establishes local byte identity only, not graph correctness, legal clearance or model/NPU compatibility. Review the receipt and update the canonical provenance manifest with actual observations separately.

Then use the existing inspector, preserving all original bytes:

```sh
/workspace/.venvs/docksr-gate0/bin/python scripts/onnx_inspect.py \
  /workspace/DockSR-model-cache/manual-sesr-009/sesr_nhwc_int8_256x256.onnx \
  --output /workspace/DockSR-model-cache/manual-sesr-009/inspection.json
```

Read actual signatures, domains, quantization and preprocessing evidence before generating constant/gradient/edge/checkerboard inputs. Only after input encoding is understood, run `scripts/onnx_reference.py MODEL --input VERIFIED_INPUT.npy --output-dir NEW_REFERENCE_DIRECTORY` with the separate Gate-0 Python environment. Layout and ranges must come from evidence; no NHWC/NCHW, scaling or image-quality meaning is inferred from a filename. Unsupported operators or preprocessing ambiguity remain explicit blockers, without rewriting the graph. Tool regression commands are in [gate0.md](gate0.md). The examples here require new destinations; DSR010 used `manual-sesr-010` and the retained reference described above.

## License separation

- The pinned AMD model card declares Apache-2.0 and links an Apache LICENSE at the same revision; both retrieved text hashes are recorded. Actual asset-specific redistribution remains unresolved while artifact/notices review is incomplete. No weights are included here.
- AMD RyzenAI-SW example source is MIT at `43b2dabe4d1bf084d0421953b134707b8cb7275a`, with independently retrieved LICENSE.txt. Underlying ARM SESR source has its own Apache-2.0 evidence. None of this licenses AMD runtime binaries.
- The intended AMD Linux/Vitis AI stack is a future test plan, not an installed or executed runtime. Its binary/EULA distribution terms are not evaluated by a model-card declaration.
- DIV2K training is disclosed by the model card. Model-weight rights do not grant rights to redistribute its training images; dataset rights remain a separate unresolved scope. No dataset or natural-image samples were downloaded for this implementation.

Read-only source metadata/text evidence is cached outside Git under `/workspace/DockSR-model-cache/acquisition/sesr-m7-256/`; DSR010 also read exact-revision source objects from the existing official Git cache. The public manifest records pinned URLs, dates and hashes without copying weights, signed URLs or private reports. Missing guessed LICENSE paths were ordinary 404 path errors; the actual LICENSE and LICENSE.txt files above were found and read. Source-license observations do not establish runtime installation, driver action or redistribution clearance. The separately recorded model inference above is REAL_CPU only.

## DSR011 reuse of the unchanged artifact

The same verified bytes now support the complete synthetic720p→1440p
[CPU reference](fullframe-reference.md) and a real
[native worker bridge](inference-worker.md) execution. No replacement model,
conversion or new CDN acquisition was needed. These are REAL_CPU host gates;
physical XDNA2, quality, model/runtime redistribution and licensing remain
separate. The [prepared physical probe](npu-device-probe.md) starts with this
unchanged model before any owned exact3× fixture compilation.
