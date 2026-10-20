# SESR-M7 candidate acquisition evidence

Inspected 2026-10-20 UTC (2026-10-19 America/Chicago). The canonical record is [the candidate provenance manifest](../models/sesr-m7-256.provenance.json); [Gate-0 commands](gate0.md) describe validation and host execution.

The Hugging Face API, pinned model card/LICENSE and read-only Git query succeeded. Repository revision is `edbe46281e894e31da3f42aa353db1e04a50f00a`. Its selected artifact path is `onnx-models/sesr_nhwc_int8_256x256.onnx`, with publisher-advertised length **107131 bytes** and LFS SHA-256 **63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1**. Those are declarations, not locally measured artifact identity. A filename mentioning NHWC/INT8 is not an inspected graph signature.

The pinned artifact URL redirects to **us.aws.cdn.hf.co**; the current proxy rejects that host's CONNECT request with HTTP 403. No artifact bytes were acquired, so actual SHA-256/size and graph signature remain null/unknown, and SESR CPU execution is NOT RUN. This is narrower than the old general Hugging Face access blocker. Signed redirect URLs are not retained in source or logs.

### DSR008 focused retry — MODEL_ACQUISITION_BLOCKED

At 2026-10-20 04:39 UTC, the environment configuration read showed a different base version from DSR007, no pending draft, and `us.aws.cdn.hf.co` in the custom allowlist. DSR007's statement that this addition was only a pending draft is therefore historical. Saved configuration alone does not establish that the current runtime proxy has activated the rule; no agent-callable publication/runtime-activation control is available here.

A single normal HTTPS retrieval of the exact pinned artifact, with redirects, TLS verification, a 60-second deadline and 1 MiB cap, returned curl exit 22 / HTTP 403 without artifact bytes. Separate read-only HEAD checks returned HTTP 200 for the pinned model card and `Tunnel connection failed: 403 Forbidden` for the CDN host. The artifact remains blocked despite the saved allowlist entry. No proxy bypass, mirror, different revision or model rewrite was attempted. Graph inspection and CPU reference remain NOT RUN. Sanitized attempt/connectivity records are retained outside Git under `/workspace/DockSR-model-cache/acquisition/session-008/`.

The next access investigation should establish whether the current execution proxy has received the saved CDN rule, using supported environment controls or administrator help. Repeatedly saving the same hostname is not evidence that activation occurred. Retry artifact acquisition after an actual runtime access change, then require the identity checks below before inspection.

## Controlled manual acquisition after access is available

Use a new private directory outside every checkout. This downloads a pinned data artifact, never a remote script or runtime installer. HTTPS and SHA-256 verification must remain enabled.

```sh
mkdir -m 700 /workspace/DockSR-model-cache/manual-sesr-001
curl --proto '=https' --proto-redir '=https' --fail --location \
  --max-time 60 --max-filesize 1048576 \
  --output /workspace/DockSR-model-cache/manual-sesr-001/model.download \
  'https://huggingface.co/amd/sesr-m7-256x256-tiles-amdnpu/resolve/edbe46281e894e31da3f42aa353db1e04a50f00a/onnx-models/sesr_nhwc_int8_256x256.onnx'
python3 - <<'PY'
import hashlib
from pathlib import Path
source = Path('/workspace/DockSR-model-cache/manual-sesr-001/model.download')
destination = source.with_name('sesr_nhwc_int8_256x256.onnx')
if source.stat().st_size != 107131:
    raise SystemExit('Artifact size mismatch; do not use this file')
actual = hashlib.sha256(source.read_bytes()).hexdigest()
if actual != '63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1':
    raise SystemExit('Artifact SHA-256 mismatch; do not use this file')
with destination.open('xb') as output:
    destination.chmod(0o600)
    output.write(source.read_bytes())
source.unlink()
print('Locally verified:', destination, '107131 bytes', actual)
PY
```

The verification step requires both actual size and locally calculated hash to match the advertised values and refuses to overwrite an existing verified file. These commands are instructions for a future acquisition, not evidence that it ran here. Do not use a partial `.download` file after a network or checksum error. Do not relabel an expected hash as a measured hash. Record the successful acquisition in a new reviewed manifest revision before considering redistribution. Inspection/reference commands must point at the verified local file; do not edit ONNX operators, signatures or IR versions to conceal unsupported CPU execution.

## License separation

- The pinned AMD model card declares Apache-2.0 and links an Apache LICENSE at the same revision; both retrieved text hashes are recorded. Actual asset-specific redistribution remains unresolved while artifact/notices review is incomplete. No weights are included here.
- AMD RyzenAI-SW example source is MIT at `43b2dabe4d1bf084d0421953b134707b8cb7275a`, with independently retrieved LICENSE.txt. Underlying ARM SESR source has its own Apache-2.0 evidence. None of this licenses AMD runtime binaries.
- The intended AMD Linux/Vitis AI stack is a future test plan, not an installed or executed runtime. Its binary/EULA distribution terms are not evaluated by a model-card declaration.
- DIV2K training is disclosed by the model card. Model-weight rights do not grant rights to redistribute its training images; dataset rights remain a separate unresolved scope. No dataset or natural-image samples were downloaded for this implementation.

Read-only source metadata/text evidence is cached outside Git under `/workspace/DockSR-model-cache/acquisition/sesr-m7-256/`; the public manifest records pinned URLs, dates and hashes without copying weights, signed URLs or private reports. Missing guessed LICENSE paths were ordinary 404 path errors; the actual LICENSE and LICENSE.txt files above were found and read. No runtime installation, driver action, model inference or license clearance is implied by these source observations.
