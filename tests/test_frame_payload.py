"""Independent byte-count goldens and safe CLI behavior for payload arithmetic."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from frame_payload import UINT64_MAX, build_report, calculate_payload, reconstruction_budget, text_summary


class FramePayloadTests(unittest.TestCase):
    def test_exact3_pipeline_budget_corrects_handoff_arithmetic(self):
        report = reconstruction_budget()
        self.assertEqual(report["source_logical_bytes"], 2764800)
        self.assertEqual(report["output_logical_bytes"], 24883200)
        self.assertEqual(report["minimum_read_plus_write_bytes_per_frame"], 27648000)
        # Explicit goldens: the v1.9 table incorrectly adds 9600 bytes/frame.
        self.assertEqual([r["minimum_read_plus_write_bytes_per_second"] for r in report["rates"]],
                         [1105920000, 1244160000, 1658880000])
        self.assertEqual(report["tile_input_logical_bytes"], 196608)
        self.assertEqual(report["tile_output_logical_bytes"], 1769472)
        self.assertEqual(report["no_overlap_tile_lower_bound"], 15)
        self.assertEqual(reconstruction_budget(tile=512)["no_overlap_tile_lower_bound"], 6)
        self.assertEqual(report["rates"][1]["delivery_period_ns"],
                         {"numerator": 1000000000, "denominator": 45})
        self.assertFalse(report["hardware_measured"])

    def test_pipeline_bounds_and_fractional_edge_tiles(self):
        report = reconstruction_budget(257, 257, scale=3, tile=256, fps=(40,))
        self.assertEqual(report["no_overlap_tile_lower_bound"], 4)
        self.assertEqual(report["output_logical_bytes"], 1783323)
        for kwargs in ({"scale": 0}, {"scale": True}, {"tile": 0},
                       {"tile": UINT64_MAX}, {"scale": UINT64_MAX}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                reconstruction_budget(**kwargs)

    def test_pipeline_cli_separates_calculation_from_measurement(self):
        result = self.run_cli("--reconstruction-budget")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["evidence"], "CALCULATED")
        self.assertEqual(report["document_type"], "docksr_reconstruction_budget")
        for extra in (("--preset", "720p-rgb8"), ("--format", "text")):
            self.assertNotEqual(self.run_cli("--reconstruction-budget", *extra).returncode, 0)

    def test_all_required_preset_sizes_and_rates(self):
        # Explicit byte goldens avoid deriving expected values from the utility.
        expected = {
            "720p-rgb8": (2764800, (110592000, 124416000, 165888000)),
            "720p-bgra8": (3686400, (147456000, 165888000, 221184000)),
            "1440p-rgb8": (11059200, (442368000, 497664000, 663552000)),
            "1440p-bgra8": (14745600, (589824000, 663552000, 884736000)),
            "4k-rgb8": (24883200, (995328000, 1119744000, 1492992000)),
            "4k-bgra8": (33177600, (1327104000, 1492992000, 1990656000)),
            "guide-int8": (230400, (9216000, 10368000, 13824000)),
        }
        report = build_report()
        self.assertEqual({row["name"] for row in report["payloads"]}, set(expected))
        for row in report["payloads"]:
            with self.subTest(name=row["name"]):
                size, rates = expected[row["name"]]
                self.assertEqual(row["logical_payload_bytes"], size)
                self.assertEqual([r["fps"] for r in row["rates"]], [40, 45, 60])
                self.assertEqual([r["logical_one_way_bytes_per_second"] for r in row["rates"]], list(rates))

    def test_copy_volume_includes_both_read_and_write(self):
        row = calculate_payload(3840, 2160, 3, 1, fps=(60,))
        self.assertEqual(row["rates"][0]["logical_copy_read_plus_write_bytes_per_second"], 2985984000)

    def test_custom_multibyte_channels_and_requested_rate_order(self):
        row = calculate_payload(7, 11, 5, 2, fps=[60, 40])
        self.assertEqual(row["logical_payload_bytes"], 770)
        self.assertEqual(row["rates"], [
            {"fps": 60, "logical_one_way_bytes_per_second": 46200,
             "logical_copy_read_plus_write_bytes_per_second": 92400},
            {"fps": 40, "logical_one_way_bytes_per_second": 30800,
             "logical_copy_read_plus_write_bytes_per_second": 61600}])

    def test_invalid_dimensions_reject_without_float_coercion(self):
        for bad in (0, -1, True, False, 1.0, "2", None, UINT64_MAX + 1):
            for index in range(4):
                dimensions = [1, 1, 1, 1]
                dimensions[index] = bad
                with self.subTest(value=bad, index=index), self.assertRaises(ValueError):
                    calculate_payload(*dimensions)

    def test_payload_rate_and_copy_overflows_reject(self):
        for dimensions in ((UINT64_MAX, 2, 1, 1), (UINT64_MAX // 60 + 1, 1, 1, 1),
                           (UINT64_MAX // 120 + 1, 1, 1, 1)):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                calculate_payload(*dimensions, fps=(60,))

    def test_largest_complete_rate_result_remains_exact(self):
        safe = UINT64_MAX // 120
        row = calculate_payload(safe, 1, 1, 1, fps=(60,))
        self.assertEqual(row["logical_payload_bytes"], 153722867280912930)
        self.assertEqual(row["rates"][0]["logical_copy_read_plus_write_bytes_per_second"], 18446744073709551600)

    def test_invalid_frame_rates_and_selection_reject(self):
        for bad in ((), (40, 40), (True,), (40.0,), (30,), None, "40"):
            with self.subTest(fps=bad), self.assertRaises(ValueError):
                calculate_payload(1, 1, 1, 1, fps=bad)
        for presets in ([], ["invalid"], ["guide-int8", "guide-int8"], [False]):
            with self.subTest(presets=presets), self.assertRaises(ValueError):
                build_report(presets=presets)
        with self.assertRaises(ValueError): build_report(presets=["guide-int8"], custom=(1, 1, 1, 1))

    def test_report_disclaims_hardware_and_summary_uses_exact_bytes(self):
        report = build_report(presets=["guide-int8"], fps=(60,))
        self.assertEqual(report["evidence"], "CALCULATED")
        self.assertFalse(report["hardware_measured"])
        self.assertIn("actual memory traffic", " ".join(report["assumptions"]).lower())
        text = text_summary(report)
        self.assertIn("230400 bytes/frame", text)
        self.assertIn("one-way 13824000 B/s; copy read+write 27648000 B/s", text)
        self.assertIn("do not prove lower latency or power", text)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/frame_payload.py"), *args],
                              capture_output=True, text=True, timeout=10)

    def test_cli_default_is_deterministic_json_and_text_is_available(self):
        first, second = self.run_cli(), self.run_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(len(json.loads(first.stdout)["payloads"]), 7)
        text = self.run_cli("--preset", "guide-int8", "--fps", "60", "--format", "text")
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn("guide-int8: 230400 bytes/frame", text.stdout)

    def test_cli_custom_invalid_and_overflow(self):
        custom = self.run_cli("--width", "7", "--height", "11", "--channels", "5", "--bytes-per-element", "2")
        self.assertEqual(custom.returncode, 0, custom.stderr)
        self.assertEqual(json.loads(custom.stdout)["payloads"][0]["logical_payload_bytes"], 770)
        for args in (("--width", "1"), ("--width", "-1"), ("--fps", "30"),
                     ("--width", "1.5"), ("--width", "9" * 100)):
            with self.subTest(args=args): self.assertNotEqual(self.run_cli(*args).returncode, 0)
        overflow = self.run_cli("--width", str(UINT64_MAX), "--height", "2", "--channels", "1", "--bytes-per-element", "1")
        self.assertEqual(overflow.returncode, 1)
        self.assertEqual(json.loads(overflow.stdout)["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
