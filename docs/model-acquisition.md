# SESR-M7 candidate acquisition evidence

Updated 2026-10-20 America/Chicago. The canonical record is [the candidate provenance manifest](../models/sesr-m7-256.provenance.json); [Gate-0 commands](gate0.md) describe validation and host execution. Current outcome: **MODEL_ACQUISITION_BLOCKED**.

The Hugging Face API, pinned model card/LICENSE and read-only Git query succeeded. Repository revision is `edbe46281e894e31da3f42aa353db1e04a50f00a`. Its selected artifact path is `onnx-models/sesr_nhwc_int8_256x256.onnx`, with publisher-advertised length **107131 bytes** and LFS SHA-256 **63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1**. Those are declarations, not locally measured artifact identity. A filename mentioning NHWC/INT8 is not an inspected graph signature.

The pinned artifact URL redirects to **us.aws.cdn.hf.co**; the current proxy rejects that host's CONNECT request with HTTP 403. No artifact bytes were acquired, so actual SHA-256/size and graph signature remain null/unknown, and SESR CPU execution is NOT RUN. This is narrower than the old general Hugging Face access blocker. Signed redirect URLs are not retained in source or logs.

### DSR008 focused retry — MODEL_ACQUISITION_BLOCKED

At 2026-10-20 04:39 UTC, the environment configuration read showed a different base version from DSR007, no pending draft, and `us.aws.cdn.hf.co` in the custom allowlist. DSR007's statement that this addition was only a pending draft is therefore historical. Saved configuration alone does not establish that the current runtime proxy has activated the rule; no agent-callable publication/runtime-activation control is available here.

A single normal HTTPS retrieval of the exact pinned artifact, with redirects, TLS verification, a 60-second deadline and 1 MiB cap, returned curl exit 22 / HTTP 403 without artifact bytes. Separate read-only HEAD checks returned HTTP 200 for the pinned model card and `Tunnel connection failed: 403 Forbidden` for the CDN host. The artifact remains blocked despite the saved allowlist entry. No proxy bypass, mirror, different revision or model rewrite was attempted. Graph inspection and CPU reference remain NOT RUN. Sanitized attempt/connectivity records are retained outside Git under `/workspace/DockSR-model-cache/acquisition/session-008/`.

### DSR009 bounded investigation — MODEL_ACQUISITION_BLOCKED

On 2026-10-20, the exact pinned HTTPS GET returned HF HTTP 302 to `us.aws.cdn.hf.co`, then failed at proxy CONNECT with 403 before artifact bytes. The current saved configuration still includes this CDN host; saved rules do not establish active execution-policy propagation. No callable runtime-activation control is available. This identifies the observed failure stage; CDN-origin DNS/TLS/authentication were not reached or tested.

Official no-smudge Git clone and exact-revision fetch succeeded. `git show` returned only the Git LFS pointer with the advertised identity, not model bytes. Native Git LFS 3.6.1 fetch was stopped after 60 seconds without an artifact. The canonical official batch API (`https://huggingface.co/amd/sesr-m7-256x256-tiles-amdnpu.git/info/lfs/objects/batch`) returned HTTP 200 and directs the requested object to the same CDN. A guessed batch path without `.git` initially returned 404; the canonical endpoint was then obtained from `git lfs env`. That path error does not mean the model is missing.

No exact-size candidate was found in the existing `/workspace/DockSR-model-cache` or `/workspace/.cache`; ordinary Hugging Face cache directories were absent. Other approved artifact connectors are not callable here. No model copy was supplied by the owner. Sanitized evidence is retained under ignored `results/session-009/` and `/workspace/DockSR-model-cache/acquisition/session-009/`, without signed URLs, credentials or model bytes.

Stop network retries until a meaningful access change. Either use supported environment/platform help to establish active CDN policy, or supply the exact artifact through the manual procedure below. No proxy bypass, mirror, different revision or download framework was used. Graph inspection and real-model CPU reference remain NOT_RUN.

## Manual fallback for the owner

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

Read actual signatures, domains, quantization and preprocessing evidence before generating constant/gradient/edge/checkerboard inputs. Only after input encoding is understood, run `scripts/onnx_reference.py MODEL --input VERIFIED_INPUT.npy --output-dir NEW_REFERENCE_DIRECTORY` with the separate Gate-0 Python environment. Layout and ranges must come from evidence; no NHWC/NCHW, scaling or image-quality meaning is inferred from a filename. Unsupported operators or preprocessing ambiguity remain explicit blockers, without rewriting the graph. Tool regression commands are in [gate0.md](gate0.md). The manual acquisition/import/real-model commands are a future procedure, not a claim that this unavailable artifact ran here.

## License separation

- The pinned AMD model card declares Apache-2.0 and links an Apache LICENSE at the same revision; both retrieved text hashes are recorded. Actual asset-specific redistribution remains unresolved while artifact/notices review is incomplete. No weights are included here.
- AMD RyzenAI-SW example source is MIT at `43b2dabe4d1bf084d0421953b134707b8cb7275a`, with independently retrieved LICENSE.txt. Underlying ARM SESR source has its own Apache-2.0 evidence. None of this licenses AMD runtime binaries.
- The intended AMD Linux/Vitis AI stack is a future test plan, not an installed or executed runtime. Its binary/EULA distribution terms are not evaluated by a model-card declaration.
- DIV2K training is disclosed by the model card. Model-weight rights do not grant rights to redistribute its training images; dataset rights remain a separate unresolved scope. No dataset or natural-image samples were downloaded for this implementation.

Read-only source metadata/text evidence is cached outside Git under `/workspace/DockSR-model-cache/acquisition/sesr-m7-256/`; the public manifest records pinned URLs, dates and hashes without copying weights, signed URLs or private reports. Missing guessed LICENSE paths were ordinary 404 path errors; the actual LICENSE and LICENSE.txt files above were found and read. No runtime installation, driver action, model inference or license clearance is implied by these source observations.
