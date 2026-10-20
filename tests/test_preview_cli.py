#!/usr/bin/env python3
"""Startup failures must remain non-active and have zero completed outputs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()


class PreviewStartup(unittest.TestCase):
    def run_preview(self, *arguments):
        environment = os.environ.copy()
        environment.pop("DISPLAY", None)
        return subprocess.run([str(BINARY), *arguments], env=environment, text=True,
                              capture_output=True, timeout=10)

    def failed(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        status = json.loads(result.stdout)
        self.assertEqual(status["runtime_state"], "ERROR")
        self.assertEqual(status["evidence"], "NONE")
        self.assertEqual(status["frames_processed"], 0)
        self.assertIsNone(status["dimensions"]["actual"])
        self.assertIsNone(status["timings_ms"]["npu"])
        self.assertTrue(status["last_error"]["message"])

    def test_help_needs_no_display(self):
        result = self.run_preview("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("NOT GAME INTEGRATION", result.stdout)

    def test_bad_dimensions_rejected_before_startup(self):
        for value in ("0x0", "720x1080", "3840x999999999999999999", "-1x2"):
            with self.subTest(value=value):
                self.failed(self.run_preview("--size", value))

    def test_bad_image_does_not_claim_processing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.ppm"
            path.write_bytes(b"P6\n1280 720\n255\ntruncated")
            self.failed(self.run_preview("--input", str(path)))

    def test_absent_display_is_explicit(self):
        result = self.run_preview()
        self.failed(result)
        self.assertIn("No usable X11 display", result.stderr)

    def test_startup_failure_replaces_prior_own_status(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            result = self.run_preview("--dump-status-json", str(path))
            self.failed(result)
            self.assertEqual(json.loads(path.read_text()), json.loads(result.stdout))
            path.chmod(0o600)
            second = self.run_preview("--input", str(Path(folder) / "missing.ppm"), "--dump-status-json", str(path))
            self.failed(second)
            self.assertEqual(json.loads(path.read_text()), json.loads(second.stdout))


if __name__ == "__main__":
    unittest.main()
