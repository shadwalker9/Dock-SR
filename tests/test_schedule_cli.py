"""Integration checks of the existing mock command's timing experiment entry."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()


class ScheduleCli(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([str(BINARY), "--schedule", *arguments],
                              text=True, capture_output=True, timeout=20)

    def test_json_summary_and_determinism(self):
        arguments = ("--fps", "40", "--service-ms", "20", "--gpu-ms", "0",
                     "--slots", "1", "--queue-capacity", "0", "--frames", "40", "--delay-frames", "0")
        first, second = self.run_cli(*arguments), self.run_cli(*arguments)
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, second.stderr)
        report = json.loads(first.stdout)
        self.assertEqual(report["evidence"], "SIMULATED")
        self.assertFalse(report["hardware_validated"])
        self.assertEqual(report["counts"]["presented_unique_results"], 40)
        self.assertEqual(report["counts"]["delivered_frames"], 40)
        self.assertIn("No hardware inference", first.stderr)
        self.assertIn("Submitted 40, completed 40, cancelled 0, dropped 0", first.stderr)
        self.assertIn("admission queue capacity 0, max 0, time-average 0.000", first.stderr)

    def test_throughput_ceiling_is_not_presentation_rate(self):
        result = self.run_cli("--fps", "60", "--service-ms", "20", "--gpu-ms", "0",
                              "--frames", "6", "--delay-frames", "0")
        self.assertEqual(result.returncode, 0, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["completed"], 5)
        self.assertEqual(report["counts"]["delivered_frames"], 6)
        self.assertEqual(report["counts"]["presented_unique_results"], 0)
        self.assertEqual(report["observations"]["completed_unique_per_second"], 50)
        self.assertTrue(report["service_model"]["demand_exceeds_assumed_capacity"])

    def test_invalid_and_overflow_inputs_return_json_nonzero(self):
        for arguments in (("--fps", "0"), ("--frames", "18446744073709551616"),
                          ("--frames", "100001"), ("--slots", "-1"), ("--gpu-ms", "nan"),
                          ("--execution", "npu"), ("--fps",), ("--unknown", "1"),
                          ("--fps", "45x"), ("--infer-every", "0")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["status"], "ERROR")

    def test_default_mock_behavior_is_preserved(self):
        result = subprocess.run([str(BINARY)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report["evidence_class"], "mock_state_machine")
        self.assertFalse(report["scenario_executed"])

    def test_help_explains_simulation_and_options(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("SIMULATED", result.stdout)
        self.assertIn("--delay-frames", result.stdout)


if __name__ == "__main__":
    unittest.main()
