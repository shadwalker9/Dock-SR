#!/usr/bin/env python3
"""Execute the native worker's real CPU bridge and reject false receipts.

Usage: SDK_PYTHON tests/test_worker_reference.py COMPILED_NATIVE_BINARY [-v]
All image/model bytes are owned fixtures in private temporary directories.
This is a host reference test, never frame presentation or NPU evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import espcn_fixture as fixture
import onnx_reference as reference
from jsonschema import Draft202012Validator

BINARY = Path(sys.argv.pop(1)).absolute() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None


def private_write(path, data):
    path.write_bytes(data)
    path.chmod(0o600)


class NativeCpuBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = Draft202012Validator(json.loads((ROOT / "schemas/inference-worker.schema.json").read_text()))
        cls.validator.check_schema(cls.validator.schema)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="docksr-worker-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.base.chmod(0o700)
        self.np, _, _, _ = reference.dependencies()
        self.model = self.base / "model.onnx"
        private_write(self.model, fixture.make_model(height=2, width=3).SerializeToString(deterministic=True))
        self.model_hash = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.input = fixture.sentinel_input(2, 3)
        self.input_path = self.base / "input.raw"
        private_write(self.input_path, self.input.tobytes())
        self.executor = ROOT / "scripts/cpu_worker_executor.py"
        self.work = self.base / "job"

    def run_bridge(self, *, replacements=None, executor=None, work=None):
        arguments = {
            "--python": sys.executable, "--executor": str(executor or self.executor),
            "--model": str(self.model), "--model-sha256": self.model_hash,
            "--input": str(self.input_path), "--input-shape": "1,3,2,3",
            "--output-shape": "1,3,6,9", "--dtype": "float32", "--layout": "NCHW",
            "--work-dir": str(work or self.work), "--session-id": "current-session",
            "--frame-id": "43", "--generation": "7", "--trace-id": "exact-trace-43",
        }
        arguments.update(replacements or {})
        command = [str(BINARY)]
        for key, value in arguments.items():
            command += [key, str(value)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        record = json.loads(completed.stdout)
        if "request" in record:
            self.validator.validate(record["request"])
            self.validator.validate(record["result"])
            self.validator.validate(record["backend_result"])
        return completed, record

    def fake_executor(self, body):
        path = self.base / "controlled_executor.py"
        private_write(path, ("import os\nos.umask(0o077)\n" + body).encode())
        return path

    def mutating_executor(self, body):
        return self.fake_executor(
            "import argparse, sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "import cpu_worker_executor as executor\n"
            "p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--request');a=p.parse_args()\n"
            "executor.execute(Path(a.model),Path(a.request))\nwork=Path(a.request).parent\n" + body)

    def assert_rejected(self, completed, record):
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(record.get("consumed", False))
        self.assertFalse(record.get("backend_valid", False))
        self.assertEqual(record["physical_npu"], "NOT_RUN")
        if "result" in record:
            self.assertFalse(record["result"]["valid"])
            self.assertEqual(record["result"]["evidence_class"], "NOT_RUN")
            self.assertFalse(record["result"]["npu_inference_verified"])
            self.assertEqual(record["outstanding_requests"], 0)

    def test_real_current_cpu_result_matches_independent_oracle(self):
        completed, record = self.run_bridge()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        for field in ("backend_valid", "completed", "consumed", "released", "child_started", "child_stop_acknowledged"):
            self.assertTrue(record[field], field)
        self.assertEqual(record["outstanding_requests"], 0)
        self.assertEqual(record["presentation"], "NOT_RUN")
        self.assertEqual(record["worker_rejection_reason"], "")
        self.assertEqual(record["output_sha256_source"], "TRUSTED_CPU_EXECUTOR_RECEIPT")
        self.assertTrue(record["backend_result"]["valid"])
        result = record["result"]
        self.assertEqual(result["evidence_class"], "REAL_CPU")
        for key in ("session_id", "frame_id", "configuration_generation", "model_sha256", "trace_id"):
            self.assertEqual(result[key], record["request"][key])
        expected = fixture.scalar_fixture_oracle(self.input)
        actual = self.np.frombuffer((self.work / "output.raw").read_bytes(), dtype="float32").reshape(expected.shape)
        self.np.testing.assert_array_equal(actual, expected)
        self.assertEqual(record["output_sha256"], hashlib.sha256(expected.tobytes()).hexdigest())
        cpu = json.loads((self.work / "cpu-evidence.json").read_text())
        self.assertEqual(cpu["successful_inference_calls"], 2)
        self.assertEqual(len(cpu["inference_samples_ns"]), 2)
        self.assertTrue(cpu["repeated_outputs_equal"])
        self.assertEqual(result["inference_duration"], sum(cpu["inference_samples_ns"]))
        ledger = result["ledger"]
        self.assertEqual((result["logical_bytes"], ledger["source_logical_bytes"]), (720, 72))
        self.assertEqual((ledger["inference_input_logical_bytes"], ledger["inference_output_logical_bytes"]), (144, 1296))
        self.assertEqual((result["copy_count"], ledger["host_copy_count"], ledger["host_copy_bytes"]), (4, 4, 1440))
        self.assertEqual(ledger["host_copy_scope"], "FOUR_RAW_FILE_PAYLOAD_TRANSFERS_ONLY")
        self.assertEqual(ledger["allocation_high_water_bytes"], 792)
        self.assertGreaterEqual(ledger["submit_to_complete_duration"], result["inference_duration"])
        self.assertIsNotNone(ledger["complete_to_consume_duration"])
        self.assertIsNone(ledger["gpu_upload_bytes"])
        self.assertIsNone(ledger["physical_ddr_traffic"])
        self.assertEqual(ledger["runtime_internal_copy_status"], "UNKNOWN")
        self.assertEqual(self.work.stat().st_mode & 0o777, 0o700)
        for path in self.work.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, str(path))

    def test_nhwc_boundaries_are_real_and_contiguous(self):
        private_write(self.model, fixture.make_model(height=2, width=3, layout="NHWC").SerializeToString(deterministic=True))
        self.model_hash = hashlib.sha256(self.model.read_bytes()).hexdigest()
        nhwc = fixture.sentinel_input(2, 3, layout="NHWC")
        private_write(self.input_path, nhwc.tobytes())
        completed, record = self.run_bridge(replacements={"--input-shape": "1,2,3,3", "--output-shape": "1,6,9,3", "--layout": "NHWC"})
        self.assertEqual(completed.returncode, 0, completed.stdout)
        expected = self.np.array(fixture.scalar_fixture_oracle(self.input).transpose(0, 2, 3, 1), order="C")
        self.assertEqual((self.work / "output.raw").read_bytes(), expected.tobytes())
        self.assertEqual(record["request"]["buffer_stride"], [72, 36, 12, 4])

    def test_wrong_model_hash_cannot_become_cpu_success(self):
        completed, record = self.run_bridge(replacements={"--model-sha256": "0" * 64})
        self.assert_rejected(completed, record)
        self.assertIn("MODEL_HASH_MISMATCH", (self.work / "child.log").read_text())
        self.assertEqual(record["result"]["ledger"]["host_copy_count"], 1)
        self.assertEqual(record["result"]["ledger"]["host_copy_bytes"], 72)

    def test_wrong_output_signature_is_rejected_before_inference(self):
        completed, record = self.run_bridge(replacements={"--output-shape": "1,3,5,9"})
        self.assert_rejected(completed, record)
        self.assertIn("MODEL_SIGNATURE_MISMATCH", (self.work / "child.log").read_text())

    def test_nonzero_child_cannot_complete_a_frame(self):
        completed, record = self.run_bridge(executor=self.fake_executor("raise SystemExit(9)\n"))
        self.assert_rejected(completed, record)
        self.assertTrue(record["child_stop_acknowledged"])
        self.assertEqual(record["result"]["fallback_reason"], "CPU_PROCESS_FAILED")

    def test_zero_exit_without_receipt_is_not_success(self):
        completed, record = self.run_bridge(executor=self.fake_executor("raise SystemExit(0)\n"))
        self.assert_rejected(completed, record)

    def test_wrong_frame_receipt_cannot_be_consumed(self):
        executor = self.mutating_executor("p=work/'receipt.txt';lines=p.read_text().splitlines();lines[2]='44';p.write_text('\\n'.join(lines)+'\\n')\n")
        completed, record = self.run_bridge(executor=executor)
        self.assert_rejected(completed, record)
        self.assertEqual(record["result"]["fallback_reason"], "CPU_RECEIPT_MISMATCH")

    def test_provider_relabel_cannot_claim_npu_execution(self):
        executor = self.mutating_executor("p=work/'receipt.txt';lines=p.read_text().splitlines();lines[19]='REAL_NPU';lines[20]='VitisAIExecutionProvider';p.write_text('\\n'.join(lines)+'\\n')\n")
        completed, record = self.run_bridge(executor=executor)
        self.assert_rejected(completed, record)

    def test_modified_raw_output_is_rejected(self):
        executor = self.mutating_executor("p=work/'output.raw';data=bytearray(p.read_bytes());data[0]^=1;p.write_bytes(data)\n")
        completed, record = self.run_bridge(executor=executor)
        self.assert_rejected(completed, record)
        self.assertEqual(record["result"]["fallback_reason"], "CPU_OUTPUT_MISMATCH")

    def test_truncated_receipt_is_rejected(self):
        executor = self.mutating_executor("(work/'receipt.txt').write_text('DOCKSR_CPU_RESULT_V1\\n')\n")
        completed, record = self.run_bridge(executor=executor)
        self.assert_rejected(completed, record)

    def test_timeout_stops_and_reaps_the_actual_child(self):
        executor = self.fake_executor("import time,sys\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index('--request')+1]).parent/'child.pid';p.write_text(str(os.getpid()));time.sleep(30)\n")
        started = time.monotonic()
        completed, record = self.run_bridge(executor=executor, replacements={"--timeout-ms": "200"})
        self.assert_rejected(completed, record)
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(record["child_timed_out"])
        self.assertTrue(record["child_stop_acknowledged"])
        pid = int((self.work / "child.pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_request_deadline_caps_longer_configured_timeout(self):
        executor = self.fake_executor("import time\ntime.sleep(30)\n")
        started = time.monotonic()
        completed, record = self.run_bridge(executor=executor, replacements={"--timeout-ms": "10000", "--deadline-ms": "20"})
        self.assert_rejected(completed, record)
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(record["result"]["ledger"]["deadline_missed"])

    def test_existing_or_git_output_is_preserved(self):
        self.work.mkdir(mode=0o700)
        private_write(self.work / "owner.txt", b"preserve")
        completed, record = self.run_bridge()
        self.assert_rejected(completed, record)
        self.assertEqual((self.work / "owner.txt").read_bytes(), b"preserve")
        forbidden = ROOT / "results" / "bridge-must-not-create"
        self.assertFalse(forbidden.exists())
        completed, record = self.run_bridge(work=forbidden)
        self.assert_rejected(completed, record)
        self.assertFalse(forbidden.exists())

    def test_invalid_input_types_and_tensor_bounds_do_not_block(self):
        private_write(self.input_path, b"short")
        completed, record = self.run_bridge()
        self.assert_rejected(completed, record)
        self.input_path.unlink()
        os.mkfifo(self.input_path, mode=0o600)
        completed, record = self.run_bridge()
        self.assert_rejected(completed, record)
        self.input_path.unlink()
        self.input_path.symlink_to(self.model)
        completed, record = self.run_bridge()
        self.assert_rejected(completed, record)
        completed, record = self.run_bridge(replacements={"--input-shape": "1,3,8192,8192"})
        self.assert_rejected(completed, record)


if __name__ == "__main__":
    if BINARY is None or not BINARY.is_file():
        raise SystemExit("Supply the compiled native worker-reference binary")
    unittest.main()
