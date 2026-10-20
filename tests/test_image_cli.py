#!/usr/bin/env python3
"""Independent pixel and CLI checks for the real CPU PPM scaler.

Usage: python3 tests/test_image_cli.py /path/to/docksr-scale

Requires only the Python standard library. All images, status files, and
malformed fixtures live in temporary directories. Expected pixels below are
small, explicit goldens; no production scaler or source generator is imported.
"""

import json
import math
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


def pack_rows(rows):
    return bytes(channel for row in rows for pixel in row for channel in pixel)


def read_ppm(path):
    """Read an 8-bit P6 capture, preserving every raw pixel byte."""
    raw = path.read_bytes()
    position = 0

    def word():
        nonlocal position
        while position < len(raw):
            if raw[position] in b" \t\r\n\v\f":
                position += 1
            elif raw[position] == ord("#"):
                end = raw.find(b"\n", position)
                if end < 0:
                    raise ValueError("Unterminated PPM comment")
                position = end + 1
            else:
                break
        start = position
        while position < len(raw) and raw[position] not in b" \t\r\n\v\f#":
            position += 1
        if start == position:
            raise ValueError("Missing PPM header token")
        return raw[start:position]

    if word() != b"P6":
        raise ValueError("Expected P6")
    width, height, maximum = int(word()), int(word()), int(word())
    if width <= 0 or height <= 0 or maximum != 255:
        raise ValueError("Expected positive dimensions and maxval 255")
    if position >= len(raw) or raw[position] not in b" \t\r\n\v\f":
        raise ValueError("Missing PPM raster separator")
    raster_size = width * height * 3
    crlf_separator = (raw[position:position + 2] == b"\r\n" and
                      len(raw) - position - 2 == raster_size)
    position += 2 if crlf_separator else 1
    pixels = raw[position:]
    if len(pixels) != width * height * 3:
        raise ValueError("Wrong PPM raster length")
    return width, height, pixels


class ImageCliTests(unittest.TestCase):
    binary = None

    def setUp(self):
        if self.binary is None:
            self.skipTest("Run test_image_cli.py with the docksr-scale binary path")
        temporary = tempfile.TemporaryDirectory(prefix="docksr-image-cli-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.case_index = 0

    def case_directory(self):
        self.case_index += 1
        directory = self.directory / str(self.case_index)
        directory.mkdir()
        return directory

    def invoke(self, arguments):
        try:
            return subprocess.run(
                [str(self.binary), *map(str, arguments)], capture_output=True,
                text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self.fail(f"Cannot run CPU image CLI: {error}")

    def assert_success(self, process):
        self.assertEqual(process.returncode, 0,
                         f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}")

    def assert_cpu_status(self, report, input_size, output_size, filter_name):
        self.assertIsInstance(report, dict)
        self.assertEqual(report["schema_version"], "1.0.0")
        self.assertEqual(report["document_type"], "docksr_status")
        self.assertEqual(report["runtime_state"], "CPU_REFERENCE_ACTIVE")
        self.assertEqual(report["evidence"], "REAL_CPU")
        self.assertEqual(report["backend_name"], f"cpu-reference-{filter_name}")
        dimensions = {
            "input": {"width": input_size[0], "height": input_size[1]},
            "output": {"width": output_size[0], "height": output_size[1]},
        }
        self.assertEqual(report["dimensions"]["requested"], dimensions)
        self.assertEqual(report["dimensions"]["actual"], dimensions)
        self.assertEqual(report["frames_processed"], 1)
        self.assertIsNone(report["last_error"])
        self.assertEqual(report["npu"]["device_status"], "NOT_TESTED")
        self.assertEqual(report["npu"]["model_status"], "UNVALIDATED")
        cpu_ms = report["timings_ms"]["cpu"]
        self.assertIsInstance(cpu_ms, (int, float))
        self.assertNotIsInstance(cpu_ms, bool)
        self.assertTrue(math.isfinite(cpu_ms))
        self.assertGreaterEqual(cpu_ms, 0)
        self.assertIsNone(report["timings_ms"]["gpu"])
        self.assertIsNone(report["timings_ms"]["npu"])
        timestamp = report["updated_at_monotonic_ns"]
        self.assertIsInstance(timestamp, int)
        self.assertNotIsInstance(timestamp, bool)
        self.assertGreaterEqual(timestamp, 0)

    def scale(self, width, height, pixels, target, filter_name, header=None):
        directory = self.case_directory()
        source = directory / "source.ppm"
        output = directory / "scaled.ppm"
        status = directory / "status.json"
        if header is None:
            header = f"P6\n{width} {height}\n255\n".encode("ascii")
        original = header + pixels
        source.write_bytes(original)
        process = self.invoke([
            "--input", source, "--output", output,
            "--size", f"{target[0]}x{target[1]}", "--filter", filter_name,
            "--dump-status-json", status,
        ])
        self.assert_success(process)
        self.assertEqual(source.read_bytes(), original, "Scaling changed its source image")
        report = json.loads(process.stdout)
        self.assert_cpu_status(report, (width, height), target, filter_name)
        self.assertEqual(json.loads(status.read_text(encoding="utf-8")), report)
        self.assertEqual(stat.S_IMODE(status.stat().st_mode), 0o600)
        actual_width, actual_height, actual_pixels = read_ppm(output)
        self.assertEqual((actual_width, actual_height), target)
        return actual_pixels

    def test_nearest_three_times_expands_each_pixel_to_three_by_three(self):
        a, b, c, d = (3, 17, 91), (250, 8, 30), (11, 230, 47), (64, 128, 192)
        source = pack_rows([[a, b], [c, d]])
        expected = pack_rows([[a, a, a, b, b, b]] * 3 +
                             [[c, c, c, d, d, d]] * 3)
        self.assertEqual(self.scale(2, 2, source, (6, 6), "nearest"), expected)

    def test_identity_preserves_every_byte_for_both_filters(self):
        pixels = bytes(range(256)) * 3
        for filter_name in ("nearest", "bilinear"):
            with self.subTest(filter=filter_name):
                self.assertEqual(self.scale(256, 1, pixels, (256, 1), filter_name), pixels)

    def test_bilinear_known_center_edge_and_corner_pixels(self):
        source = pack_rows([
            [(0, 0, 0), (120, 60, 30)],
            [(60, 120, 90), (180, 180, 120)],
        ])
        expected = pack_rows([
            [(0, 0, 0), (60, 30, 15), (120, 60, 30)],
            [(30, 60, 45), (90, 90, 60), (150, 120, 75)],
            [(60, 120, 90), (120, 150, 105), (180, 180, 120)],
        ])
        self.assertEqual(self.scale(2, 2, source, (3, 3), "bilinear"), expected)

    def test_odd_aspect_resize_against_explicit_goldens(self):
        a, b, c = (0, 0, 0), (60, 30, 12), (120, 60, 24)
        d, e, f = (120, 120, 60), (180, 150, 72), (240, 180, 84)
        source = pack_rows([[a, b, c], [d, e, f]])
        goldens = {
            "nearest": pack_rows([[a, a, b, c, c], [d, d, e, f, f], [d, d, e, f, f]]),
            "bilinear": pack_rows([
                [(0, 0, 0), (24, 12, 5), (60, 30, 12), (96, 48, 19), (120, 60, 24)],
                [(60, 60, 30), (84, 72, 35), (120, 90, 42), (156, 108, 49), (180, 120, 54)],
                [(120, 120, 60), (144, 132, 65), (180, 150, 72), (216, 168, 79), (240, 180, 84)],
            ]),
        }
        for filter_name, expected in goldens.items():
            with self.subTest(filter=filter_name):
                self.assertEqual(self.scale(3, 2, source, (5, 3), filter_name), expected)

    def test_comments_and_whitespace_or_hash_pixel_bytes_are_preserved(self):
        cases = (
            (b"P6\n# comment before dimensions\n2 # width comment\n1\n255\n",
             b"\n #\r\t\x00"),
            (b"P6\r\n# CRLF header\r\n2 1\r\n255\r\n",
             b"\n #\xff\x00\x09"),
            (b"P6\n2 1\n255\r", b"\n #\xff\x00\x09"),
            (b"P6 2 1 255 ", b"#\n \x00\xff\r"),
        )
        for header, pixels in cases:
            with self.subTest(header=header):
                self.assertEqual(self.scale(2, 1, pixels, (2, 1), "nearest", header), pixels)

    def test_generate_produces_deterministic_nonuniform_real_images(self):
        for filter_name in ("nearest", "bilinear"):
            captures = []
            for repeat in range(2):
                with self.subTest(filter=filter_name, repeat=repeat):
                    directory = self.case_directory()
                    output = directory / "generated.ppm"
                    status = directory / "status.json"
                    process = self.invoke([
                        "--generate", "--output", output, "--size", "9x7",
                        "--filter", filter_name, "--dump-status-json", status,
                    ])
                    self.assert_success(process)
                    report = json.loads(process.stdout)
                    self.assert_cpu_status(report, (1280, 720), (9, 7), filter_name)
                    self.assertEqual(json.loads(status.read_text(encoding="utf-8")), report)
                    self.assertEqual(stat.S_IMODE(status.stat().st_mode), 0o600)
                    width, height, pixels = read_ppm(output)
                    self.assertEqual((width, height), (9, 7))
                    self.assertGreater(len(set(pixels)), 1)
                    captures.append(pixels)
            self.assertEqual(captures[0], captures[1])

    def test_malformed_ppm_inputs_fail_without_creating_output(self):
        valid_header = b"P6\n1 1\n255\n"
        malformed = {
            "empty": b"",
            "wrong_magic": b"P3\n1 1\n255\n\x00\x00\x00",
            "missing_header": b"P6\n1\n",
            "unterminated_comment": b"P6\n# no newline",
            "missing_raster_separator": b"P6\n1 1\n255",
            "truncated": valid_header + b"\x01\x02",
            "extra_pixel_byte": valid_header + b"\x01\x02\x03\x04",
            "trailing_whitespace": valid_header + b"\x01\x02\x03\n",
            "maxval_zero": b"P6\n1 1\n0\n\x01\x02\x03",
            "maxval_254": b"P6\n1 1\n254\n\x01\x02\x03",
            "maxval_65535": b"P6\n1 1\n65535\n\x01\x02\x03\x04\x05\x06",
            "zero_width": b"P6\n0 1\n255\n",
            "negative_height": b"P6\n1 -1\n255\n",
            "noninteger_dimension": b"P6\n1.0 1\n255\n\x01\x02\x03",
            "oversized_dimension": b"P6\n8193 1\n255\n",
            "oversized_pixel_count": b"P6\n8192 8192\n255\n",
            "integer_overflow": b"P6\n999999999999999999999999999999 1\n255\n",
        }
        for name, raw in malformed.items():
            with self.subTest(input=name):
                directory = self.case_directory()
                source, output = directory / "invalid.ppm", directory / "output.ppm"
                source.write_bytes(raw)
                process = self.invoke([
                    "--input", source, "--output", output,
                    "--size", "3x3", "--filter", "nearest",
                ])
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(output.exists(), "An invalid input produced an output image")
                self.assertEqual(source.read_bytes(), raw)

    def test_invalid_cli_arguments_fail(self):
        for bad_size in ("0x1", "1x0", "-1x3", "3x-1", "3", "3x4tail",
                         "8193x1", "1x8193", "8192x8192",
                         "999999999999999999999999999999x1"):
            with self.subTest(size=bad_size):
                directory = self.case_directory()
                output = directory / "output.ppm"
                process = self.invoke([
                    "--generate", "--output", output, "--size", bad_size,
                ])
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(output.exists())

        directory = self.case_directory()
        source, output = directory / "source.ppm", directory / "output.ppm"
        source.write_bytes(b"P6\n1 1\n255\n\x01\x02\x03")
        valid = ["--generate", "--output", output, "--size", "3x3"]
        cases = (
            [],
            ["--output", output, "--size", "3x3"],
            ["--generate", "--size", "3x3"],
            ["--generate", "--output", output],
            [*valid, "--input", source],
            [*valid, "--filter", "invalid"],
            [*valid, "--filter", "nearest", "--filter", "invalid"],
            [*valid, "--unknown-option"],
            [*valid, "extra-positional"],
            [*valid, "--filter"],
            [*valid, "--input"],
            [*valid, "--dump-status-json"],
            ["--generate", "--output", "", "--size", "3x3"],
            ["--input", directory / "missing.ppm", "--output", output, "--size", "3x3"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                process = self.invoke(arguments)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(output.exists())

    def test_existing_output_is_preserved(self):
        directory = self.case_directory()
        source, output = directory / "source.ppm", directory / "existing.ppm"
        original_source = b"P6\n1 1\n255\n\x01\x02\x03"
        sentinel = b"Existing user file: preserve these exact bytes.\n"
        source.write_bytes(original_source)
        output.write_bytes(sentinel)
        process = self.invoke([
            "--input", source, "--output", output,
            "--size", "3x3", "--filter", "nearest",
        ])
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertEqual(source.read_bytes(), original_source)

    def test_output_cannot_overwrite_its_input(self):
        directory = self.case_directory()
        source = directory / "source.ppm"
        original = b"P6\n1 1\n255\n\x01\x02\x03"
        source.write_bytes(original)
        process = self.invoke([
            "--input", source, "--output", source,
            "--size", "3x3", "--filter", "bilinear",
        ])
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(source.read_bytes(), original)

    def test_status_dump_can_replace_an_existing_snapshot(self):
        directory = self.case_directory()
        status = directory / "status.json"
        first_report = None
        for repeat, filter_name in enumerate(("nearest", "bilinear")):
            output = directory / f"new-{repeat}.ppm"
            process = self.invoke([
                "--generate", "--output", output, "--size", "3x3",
                "--filter", filter_name, "--dump-status-json", status,
            ])
            self.assert_success(process)
            report = json.loads(process.stdout)
            self.assert_cpu_status(report, (1280, 720), (3, 3), filter_name)
            self.assertEqual(json.loads(status.read_text(encoding="utf-8")), report)
            self.assertEqual(stat.S_IMODE(status.stat().st_mode), 0o600)
            if first_report is None:
                first_report = report
            else:
                self.assertNotEqual(report["backend_name"], first_report["backend_name"])

    def test_unrelated_existing_status_contents_are_preserved(self):
        directory = self.case_directory()
        status = directory / "unrelated.json"
        sentinel = b'{"unrelated":"existing user document"}\n'
        status.write_bytes(sentinel)
        status.chmod(0o600)
        process = self.invoke([
            "--generate", "--output", directory / "new.ppm", "--size", "3x3",
            "--filter", "nearest", "--dump-status-json", status,
        ])
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(status.read_bytes(), sentinel)

    def test_self_test_succeeds(self):
        directory = self.case_directory()
        status = directory / "self-test.json"
        process = self.invoke(["--self-test", "--dump-status-json", status])
        self.assert_success(process)
        report = json.loads(process.stdout)
        self.assertEqual(report["runtime_state"], "CPU_REFERENCE_ACTIVE")
        self.assertEqual(report["evidence"], "REAL_CPU")
        self.assertEqual(report["frames_processed"], 0)
        self.assertEqual(json.loads(status.read_text(encoding="utf-8")), report)
        self.assertEqual(stat.S_IMODE(status.stat().st_mode), 0o600)
        self.assertEqual(list(directory.iterdir()), [status])

    def test_long_argument_error_is_reported_as_error_with_zero_frames(self):
        process = self.invoke(["--" + "x" * 1100])
        self.assertEqual(process.returncode, 2)
        report = json.loads(process.stdout)
        self.assertEqual(report["runtime_state"], "ERROR")
        self.assertEqual(report["frames_processed"], 0)
        self.assertEqual(report["last_error"]["code"], "CLI_ARGUMENT_ERROR")
        self.assertLessEqual(len(report["last_error"]["message"]), 1024)


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    ImageCliTests.binary = Path(sys.argv[1]).resolve()
    if not ImageCliTests.binary.is_file():
        print(f"CPU scaler binary does not exist: {ImageCliTests.binary}", file=sys.stderr)
        return 2
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ImageCliTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
