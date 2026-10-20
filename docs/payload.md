# Logical frame payload calculator

`scripts/frame_payload.py` calculates exact unpadded, uncompressed image/tensor
payloads with Python's integer arithmetic and an explicit unsigned 64-bit limit
on inputs and every product. It allocates no image/model storage. This is a
calculation, not a GPU↔NPU interop benchmark or an estimate of latency or power.

```sh
python3 scripts/frame_payload.py
python3 scripts/frame_payload.py --format text
python3 scripts/frame_payload.py --preset guide-int8 4k-rgb8 --fps 40 45 60
python3 scripts/frame_payload.py --width 1280 --height 720 --channels 3 --bytes-per-element 1 --fps 60
python3 tests/test_frame_payload.py -v
```

JSON is the default. It contains `evidence: CALCULATED` and
`hardware_measured: false`; there are no runtime, NPU, FPS-achievement or power
measurements. `--format text` provides a concise summary. All four custom
dimension arguments are required together and cannot be mixed with `--preset`.
Dimensions/channels/bytes per element must be positive integers; rates are
40, 45 or 60 FPS. Duplicate rates/presets, invalid values and overflow return a
nonzero exit code. Ordinary execution needs only Python's standard library.

| Logical image/tensor | Bytes/frame | One-way B/s at 40 FPS | At 45 FPS | At 60 FPS |
|---|---:|---:|---:|---:|
| 1280×720 RGB8 | 2,764,800 | 110,592,000 | 124,416,000 | 165,888,000 |
| 1280×720 BGRA8 | 3,686,400 | 147,456,000 | 165,888,000 | 221,184,000 |
| 2560×1440 RGB8 | 11,059,200 | 442,368,000 | 497,664,000 | 663,552,000 |
| 2560×1440 BGRA8 | 14,745,600 | 589,824,000 | 663,552,000 | 884,736,000 |
| 3840×2160 RGB8 | 24,883,200 | 995,328,000 | 1,119,744,000 | 1,492,992,000 |
| 3840×2160 BGRA8 | 33,177,600 | 1,327,104,000 | 1,492,992,000 | 1,990,656,000 |
| Proposed 320×180×4 INT8 guide | 230,400 | 9,216,000 | 10,368,000 | 13,824,000 |

Payload bytes are `width × height × channels × bytes_per_element`.
One-way logical volume is that size times the assumed frame rate and assumes
one full payload transfer per frame. Copy read-plus-write volume counts exactly
one read and one write: at 60 FPS, 4K RGB8 is 1,492,992,000 B/s one way and
2,985,984,000 B/s for that copy model. Values are decimal bytes, not MiB/GiB.

Actual memory traffic depends on row pitch, alignment, caches, compression,
mapping, coherence, synchronization, model intermediates and additional copies.
It must be measured on the target. A shared buffer can avoid a copy while still
requiring producer writes and consumer reads. The guide shape is hypothetical;
its smaller payload proves neither useful reconstruction quality nor lower
whole-device power/latency. These calculations isolate one systems question
without substituting for the physical evidence gates.
