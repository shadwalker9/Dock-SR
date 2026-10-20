#!/usr/bin/env python3
"""Independently check docksr-bench captures, metadata, and argument validation.

Usage: python3 tests/vulkan_correctness.py /path/to/docksr-bench [scratch-root]

Only the Python standard library is required. Each invocation uses a temporary
artifact directory, removed on completion. The reference reads the captured
input rather than reproducing the benchmark's source-pattern implementation.
"""

import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def read_ppm(path):
    """Decode one 8-bit P6 image without treating pixel bytes as whitespace."""
    raw = path.read_bytes()
    offset = 0

    def token():
        nonlocal offset
        while offset < len(raw):
            if raw[offset] in b" \t\r\n\v\f":
                offset += 1
            elif raw[offset] == ord("#"):
                newline = raw.find(b"\n", offset)
                if newline < 0:
                    raise ValueError("Unterminated PPM header comment")
                offset = newline + 1
            else:
                break
        start = offset
        while offset < len(raw) and raw[offset] not in b" \t\r\n\v\f#":
            offset += 1
        if start == offset:
            raise ValueError("Missing PPM header token")
        return raw[start:offset]

    if token() != b"P6":
        raise ValueError("Expected a binary P6 PPM image")
    width, height, maximum = int(token()), int(token()), int(token())
    if width <= 0 or height <= 0 or maximum != 255:
        raise ValueError("Expected positive PPM dimensions and an 8-bit maximum")
    if offset >= len(raw) or raw[offset] not in b" \t\r\n\v\f":
        raise ValueError("Missing whitespace before PPM pixel data")
    # A CRLF is a single header line ending. No general whitespace stripping:
    # the first pixel is allowed to contain a newline, a space, or '#'.
    offset += 2 if raw[offset:offset + 2] == b"\r\n" else 1
    pixels = raw[offset:]
    if len(pixels) != width * height * 3:
        raise ValueError("PPM pixel payload does not match its dimensions")
    return width, height, pixels


def reference_pixels(source, source_width, source_height,
                     output_width, output_height, filter_name):
    """CPU reference with exact integer sample positions and interpolation.

    The bilinear weights are rational integers. This avoids introducing a
    second floating-point implementation with the shader's rounding behavior.
    """
    result = bytearray()
    for y in range(output_height):
        for x in range(output_width):
            if filter_name == "nearest":
                source_x = min(((2 * x + 1) * source_width) //
                               (2 * output_width), source_width - 1)
                source_y = min(((2 * y + 1) * source_height) //
                               (2 * output_height), source_height - 1)
                base = (source_y * source_width + source_x) * 3
                result.extend(source[base:base + 3])
                continue

            x_denominator = 2 * output_width
            y_denominator = 2 * output_height
            x_numerator = (2 * x + 1) * source_width - output_width
            y_numerator = (2 * y + 1) * source_height - output_height
            x_floor, x_weight = divmod(x_numerator, x_denominator)
            y_floor, y_weight = divmod(y_numerator, y_denominator)
            left = max(0, min(source_width - 1, x_floor))
            right = max(0, min(source_width - 1, x_floor + 1))
            top = max(0, min(source_height - 1, y_floor))
            bottom = max(0, min(source_height - 1, y_floor + 1))
            denominator = x_denominator * y_denominator
            for channel in range(3):
                top_left = source[(top * source_width + left) * 3 + channel]
                top_right = source[(top * source_width + right) * 3 + channel]
                bottom_left = source[(bottom * source_width + left) * 3 + channel]
                bottom_right = source[(bottom * source_width + right) * 3 + channel]
                numerator = (
                    top_left * (x_denominator - x_weight) *
                    (y_denominator - y_weight) +
                    top_right * x_weight * (y_denominator - y_weight) +
                    bottom_left * (x_denominator - x_weight) * y_weight +
                    bottom_right * x_weight * y_weight
                )
                # floor(value + 0.5), including exact half-integer ties.
                result.append((2 * numerator + denominator) // (2 * denominator))
    return bytes(result)


def fnv1a64(raw):
    digest = 14695981039346656037
    for byte in raw:
        digest = ((digest ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f"{digest:016x}"


class VulkanCorrectness(unittest.TestCase):
    binary = None
    scratch_root = None

    def invoke(self, arguments):
        try:
            return subprocess.run(
                [str(self.binary), *arguments], capture_output=True,
                text=True, check=False, timeout=60,
            )
        except subprocess.TimeoutExpired as error:
            self.fail(f"Benchmark timed out: {error.cmd}")

    def assert_finite_nonnegative(self, value):
        self.assertIsInstance(value, (int, float))
        self.assertNotIsInstance(value, bool)
        self.assertTrue(math.isfinite(value))
        self.assertGreaterEqual(value, 0)

    def assert_summary(self, summary):
        for name in ("min", "p50", "p95", "p99", "max"):
            self.assert_finite_nonnegative(summary[name])
        values = [summary[name] for name in ("min", "p50", "p95", "p99", "max")]
        self.assertEqual(values, sorted(values))

    def assert_metadata(self, report, directory, input_size, output_size, filter_name):
        self.assertEqual(report["schema_version"], "1.0.0")
        self.assertEqual(report["benchmark"], "docksr-vulkan-scaler")
        device = report["device"]
        self.assertIsInstance(device["name"], str)
        self.assertTrue(device["name"])
        expected_classes = {
            "cpu": "vulkan_software",
            "discrete_gpu": "vulkan_hardware",
            "integrated_gpu": "vulkan_hardware",
            "virtual_gpu": "vulkan_unknown",
            "other": "vulkan_unknown",
        }
        self.assertIn(device["type"], expected_classes)
        # A CPU Vulkan device remains software evidence regardless of its name.
        self.assertEqual(report["evidence_class"], expected_classes[device["type"]])
        for field in ("vendor_id", "device_id"):
            self.assertIsInstance(device[field], int)
            self.assertNotIsInstance(device[field], bool)
            self.assertGreaterEqual(device[field], 0)

        configuration = report["configuration"]
        for field, value in {
            "input_width": input_size[0], "input_height": input_size[1],
            "output_width": output_size[0], "output_height": output_size[1],
            "filter": filter_name, "warmup_iterations": 2,
            "measured_iterations": 3, "changing_frames": False,
        }.items():
            self.assertEqual(configuration[field], value, field)

        timings = report["timings"]
        self.assert_summary(timings["host_dispatch_to_completion_ms"])
        if timings["gpu_dispatch_ms"] is not None:
            self.assert_summary(timings["gpu_dispatch_ms"])
        correctness = report["correctness"]
        self.assertIs(correctness["passed"], True)
        allowed_error = 0 if filter_name == "nearest" else 1
        self.assertEqual(correctness["allowed_absolute_error"], allowed_error)
        self.assert_finite_nonnegative(correctness["max_absolute_error"])
        self.assertLessEqual(correctness["max_absolute_error"], allowed_error)
        # PPM captures expose RGB; the internal checker may also include alpha.
        self.assertIn(correctness["channels_compared"],
                      (output_size[0] * output_size[1] * 3,
                       output_size[0] * output_size[1] * 4))

        for metric in ("power_w", "game_internal_render_ms", "npu_ms", "game_fps"):
            self.assertIsNone(report["metrics"][metric], metric)
        for name in ("input", "output"):
            artifact = report["artifacts"][name]
            self.assertEqual(artifact["path"], f"{name}.ppm")
            self.assertEqual(artifact["hash"]["algorithm"], "fnv1a64")
            self.assertEqual(artifact["hash"]["value"],
                             fnv1a64((directory / f"{name}.ppm").read_bytes()))

        sample_columns = [
            "sample_index", "host_dispatch_to_completion_ms",
            "gpu_dispatch_ms", "input_frame_index",
        ]
        self.assertEqual(report["artifacts"]["samples"], {
            "path": "samples.csv", "format": "csv", "columns": sample_columns,
        })

        with (directory / "samples.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, sample_columns)
            rows = list(reader)
        self.assertEqual(len(rows), 3, "Warmup samples must not appear in samples.csv")
        for index, row in enumerate(rows):
            self.assertEqual(int(row["sample_index"]), index)
            self.assertEqual(int(row["input_frame_index"]), 0)
            self.assert_finite_nonnegative(float(row["host_dispatch_to_completion_ms"]))
            if timings["gpu_dispatch_ms"] is None:
                self.assertEqual(row["gpu_dispatch_ms"], "")
            else:
                self.assert_finite_nonnegative(float(row["gpu_dispatch_ms"]))

    def test_captures_against_independent_cpu_reference(self):
        cases = (
            ((1, 1), (1, 1)),
            ((1, 3), (7, 5)),
            ((4, 1), (3, 9)),
            ((3, 2), (6, 4)),
            ((5, 3), (8, 7)),
            ((9, 7), (4, 3)),
            ((7, 5), (7, 5)),
            ((2, 2), (1, 1)),
        )
        for filter_name in ("nearest", "bilinear"):
            for input_size, output_size in cases:
                with self.subTest(filter=filter_name, source=input_size, target=output_size):
                    with tempfile.TemporaryDirectory(
                        prefix="docksr-correctness-", dir=self.scratch_root,
                    ) as temporary:
                        directory = Path(temporary)
                        process = self.invoke([
                            "--input", f"{input_size[0]}x{input_size[1]}",
                            "--output", f"{output_size[0]}x{output_size[1]}",
                            "--filter", filter_name, "--warmup", "2",
                            "--iterations", "3", "--artifact-dir", str(directory),
                        ])
                        self.assertEqual(process.returncode, 0,
                                         f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}")
                        source_width, source_height, source = read_ppm(directory / "input.ppm")
                        width, height, actual = read_ppm(directory / "output.ppm")
                        self.assertEqual((source_width, source_height), input_size)
                        self.assertEqual((width, height), output_size)
                        if source_width * source_height > 1:
                            self.assertGreater(len(set(source)), 1,
                                               "A uniform fixture cannot exercise filtering")
                        expected = reference_pixels(source, source_width, source_height,
                                                    width, height, filter_name)
                        tolerance = 0 if filter_name == "nearest" else 1
                        errors = [abs(observed - wanted)
                                  for observed, wanted in zip(actual, expected)]
                        max_error = max(errors, default=0)
                        self.assertLessEqual(max_error, tolerance,
                                             f"Independent RGB reference: max error {max_error}")
                        report = json.loads((directory / "result.json").read_text(encoding="utf-8"))
                        self.assert_metadata(report, directory, input_size, output_size, filter_name)

    def test_malformed_arguments_fail(self):
        invalid_arguments = (
            ["--not-a-real-option"],
            ["--filter", "invalid"],
            ["--input", "0x3"],
            ["--input", "3x0"],
            ["--input", "-1x3"],
            ["--input", "3"],
            ["--input", "3x4trailing"],
            ["--input", "8193x1"],
            ["--input", "1x8193"],
            ["--input", "8192x8192"],
            ["--input", "999999999999999999999999999999999999x1"],
            ["--output", "3x-1"],
            ["--output", "8193x1"],
            ["--output", "8192x8192"],
            ["--iterations", "0"],
            ["--iterations", "-1"],
            ["--iterations", "10001"],
            ["--iterations", "3trailing"],
            ["--warmup", "-1"],
            ["--warmup", "1001"],
            ["--warmup", "1.5"],
            ["--artifact-dir", ""],
            ["--filter", "nearest", "--filter", "invalid"],
            ["--input"],
            ["--filter"],
            ["--artifact-dir"],
        )
        for invalid in invalid_arguments:
            with self.subTest(arguments=invalid):
                with tempfile.TemporaryDirectory(
                    prefix="docksr-invalid-", dir=self.scratch_root,
                ) as temporary:
                    process = self.invoke([
                        "--input", "3x2", "--output", "5x4",
                        "--warmup", "0", "--iterations", "1",
                        "--artifact-dir", temporary, *invalid,
                    ])
                    self.assertNotEqual(process.returncode, 0,
                                        f"Malformed arguments were accepted: {invalid}")


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    VulkanCorrectness.binary = Path(sys.argv[1]).resolve()
    if not VulkanCorrectness.binary.is_file():
        print(f"Benchmark binary does not exist: {VulkanCorrectness.binary}", file=sys.stderr)
        return 2
    if len(sys.argv) == 3:
        VulkanCorrectness.scratch_root = Path(sys.argv[2]).resolve()
        VulkanCorrectness.scratch_root.mkdir(parents=True, exist_ok=True)
    try:
        probe = subprocess.run(
            [str(VulkanCorrectness.binary), "--probe"], capture_output=True,
            text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Vulkan probe failed: {error}", file=sys.stderr)
        return 1
    if probe.returncode != 0:
        if probe.returncode == 77:
            print("Vulkan unavailable: benchmark probe exited with code 77.", file=sys.stderr)
        else:
            print(f"Vulkan probe failed with code {probe.returncode}.", file=sys.stderr)
        if probe.stdout:
            print(probe.stdout.rstrip(), file=sys.stderr)
        if probe.stderr:
            print(probe.stderr.rstrip(), file=sys.stderr)
        return 77 if probe.returncode == 77 else 1
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(VulkanCorrectness)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
