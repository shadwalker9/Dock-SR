#!/usr/bin/env python3
"""Exact logical frame payloads; never a transfer, latency or power benchmark."""
import argparse
import json
import sys


UINT64_MAX = (1 << 64) - 1
FRAME_RATES = (40, 45, 60)
PRESETS = {
    "720p-rgb8": (1280, 720, 3, 1),
    "720p-bgra8": (1280, 720, 4, 1),
    "1440p-rgb8": (2560, 1440, 3, 1),
    "1440p-bgra8": (2560, 1440, 4, 1),
    "4k-rgb8": (3840, 2160, 3, 1),
    "4k-bgra8": (3840, 2160, 4, 1),
    "guide-int8": (320, 180, 4, 1),
}


def _positive_u64(value, label):
    if type(value) is not int or not 1 <= value <= UINT64_MAX:
        raise ValueError(label + " must be an integer in 1..2^64-1")
    return value


def _multiply(left, right, label):
    if left > UINT64_MAX // right:
        raise ValueError(label + " exceeds the unsigned 64-bit arithmetic limit")
    return left * right


def calculate_payload(width, height, channels, bytes_per_element, *, fps=FRAME_RATES):
    """Calculate unpadded, uncompressed payload/volumes with checked integers.

    This allocates no image/tensor storage. Copy volume assumes exactly one
    read and one write per payload byte; actual hardware traffic is unknown.
    """
    dimensions = dict(width=width, height=height, channels=channels,
                      bytes_per_element=bytes_per_element)
    payload = 1
    for label, value in dimensions.items():
        payload = _multiply(payload, _positive_u64(value, label), "Payload")
    if not isinstance(fps, (list, tuple)) or not fps:
        raise ValueError("fps must be a nonempty list/tuple of 40, 45 or 60")
    if any(type(rate) is not int or rate not in FRAME_RATES for rate in fps):
        raise ValueError("Each fps must be one of the integers 40, 45 or 60")
    if len(fps) != len(set(fps)):
        raise ValueError("Duplicate frame rates are not permitted")
    rates = []
    for rate in fps:
        one_way = _multiply(payload, rate, "One-way bytes per second")
        copy_volume = _multiply(one_way, 2, "Copy read-plus-write bytes per second")
        rates.append({"fps": rate,
                      "logical_one_way_bytes_per_second": one_way,
                      "logical_copy_read_plus_write_bytes_per_second": copy_volume})
    return {**dimensions, "logical_payload_bytes": payload, "rates": rates}


def build_report(*, presets=None, custom=None, fps=FRAME_RATES):
    if custom is not None and presets is not None:
        raise ValueError("Choose presets or custom dimensions, not both")
    if custom is not None:
        if not isinstance(custom, (tuple, list)) or len(custom) != 4:
            raise ValueError("Custom dimensions require width, height, channels and bytes per element")
        entries = [("custom", custom)]
    else:
        selected = list(PRESETS) if presets is None else presets
        if not isinstance(selected, (list, tuple)) or not selected:
            raise ValueError("Select at least one preset")
        if any(type(name) is not str or name not in PRESETS for name in selected):
            raise ValueError("Unknown payload preset")
        if len(selected) != len(set(selected)):
            raise ValueError("Duplicate presets are not permitted")
        entries = [(name, PRESETS[name]) for name in selected]
    return {
        "schema_version": "1.0.0", "document_type": "docksr_frame_payload",
        "status": "CALCULATED", "evidence": "CALCULATED", "hardware_measured": False,
        "units": "bytes and bytes/second; exact integers, decimal byte counts",
        "assumptions": [
            "Logical payload is width * height * channels * bytes_per_element.",
            "No row pitch, alignment, padding, compression or extra model tensors are included.",
            "One-way volume assumes one logical payload transfer per delivered frame.",
            "Copy volume assumes one read and one write per logical payload byte.",
            "Actual memory traffic, interop, latency and power require hardware measurement.",
            "The compact guide is a proposed tensor shape, not a validated reconstruction model."
        ],
        "payloads": [{"name": name, **calculate_payload(*dimensions, fps=fps)}
                     for name, dimensions in entries],
    }


def text_summary(report):
    lines = ["CALCULATED logical payloads; no hardware measurements."]
    for payload in report["payloads"]:
        lines.append(f'{payload["name"]}: {payload["logical_payload_bytes"]} bytes/frame')
        for rate in payload["rates"]:
            lines.append(f'  {rate["fps"]} FPS: one-way {rate["logical_one_way_bytes_per_second"]} B/s; '
                         f'copy read+write {rate["logical_copy_read_plus_write_bytes_per_second"]} B/s')
    lines.append("Excludes padding, cache behavior and additional copies; smaller payloads do not prove lower latency or power.")
    return "\n".join(lines)


def _cli_integer(text):
    if not text.isascii() or not text.isdigit() or len(text) > 20:
        raise argparse.ArgumentTypeError("Use a positive unsigned 64-bit integer")
    value = int(text)
    try:
        return _positive_u64(value, "Value")
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", nargs="+", choices=list(PRESETS), dest="presets")
    parser.add_argument("--width", type=_cli_integer)
    parser.add_argument("--height", type=_cli_integer)
    parser.add_argument("--channels", type=_cli_integer)
    parser.add_argument("--bytes-per-element", type=_cli_integer)
    parser.add_argument("--fps", nargs="+", type=int, choices=FRAME_RATES, default=FRAME_RATES)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)
    custom = (args.width, args.height, args.channels, args.bytes_per_element)
    if any(value is not None for value in custom):
        if not all(value is not None for value in custom):
            parser.error("Custom payload requires --width, --height, --channels and --bytes-per-element")
        if args.presets is not None:
            parser.error("--preset cannot be combined with custom dimensions")
    else:
        custom = None
    try:
        report = build_report(presets=args.presets, custom=custom, fps=args.fps)
    except ValueError as error:
        print(json.dumps({"status": "ERROR", "evidence": "CALCULATED",
                          "hardware_measured": False, "error": str(error)}, sort_keys=True))
        return 1
    print(text_summary(report) if args.format == "text" else json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
