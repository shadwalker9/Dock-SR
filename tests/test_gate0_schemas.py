"""Future evidence fixtures test constraints; they never claim a device run."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_gate0 import validate_record


def fixture(name):
    return json.loads((ROOT / "tests/fixtures" / (name + ".json")).read_text())


class Gate0Schemas(unittest.TestCase):
    def setUp(self):
        self.provenance = fixture("gate0_provenance_unknown")
        self.hardware = fixture("gate0_hardware_synthetic_npu")

    def test_unknown_provenance_and_not_run_hardware(self):
        self.assertEqual(validate_record(self.provenance, "provenance")["status"], "VALID")
        result = validate_record(fixture("gate0_hardware_not_run"), "hardware")
        self.assertFalse(result["hardware_execution_verified"])

    def test_synthetic_future_shape_is_only_a_schema_example(self):
        self.assertIn("SYNTHETIC", self.hardware["fixture_notice"])
        result = validate_record(self.hardware, "hardware")
        self.assertFalse(result["hardware_execution_verified"])

    def test_declared_hash_cannot_be_presented_as_measured(self):
        self.provenance["artifact"]["sha256"] = "a" * 64
        with self.assertRaises(ValueError): validate_record(self.provenance, "provenance")

    def test_acquired_and_cleared_claims_require_more_evidence(self):
        for section, field, value in (("acquisition", "status", "ACQUIRED"), ("redistribution", "status", "verified")):
            record = copy.deepcopy(self.provenance)
            record[section][field] = value
            with self.subTest(section=section), self.assertRaises(ValueError): validate_record(record, "provenance")

    def test_unresolved_license_references_reject(self):
        self.provenance["licenses"]["model_weights"]["evidence_refs"] = ["not-observed"]
        with self.assertRaises(ValueError): validate_record(self.provenance, "provenance")

    def test_host_and_mock_execution_cannot_claim_real_npu(self):
        for environment in ("HOST_ONLY", "MOCK", "SIMULATION", "SOFTWARE_VULKAN", "NON_TARGET_PHYSICAL"):
            record = copy.deepcopy(self.hardware)
            record["execution_environment"] = environment
            with self.subTest(environment=environment), self.assertRaises(ValueError): validate_record(record, "hardware")

    def test_cpu_fallback_cannot_claim_real_npu(self):
        for backend in ("CPU", "GPU", "MOCK", "SIMULATION", "UNKNOWN"):
            record = copy.deepcopy(self.hardware)
            record["backend_kind"] = backend
            with self.subTest(backend=backend), self.assertRaises(ValueError): validate_record(record, "hardware")

    def test_device_detection_is_not_inference(self):
        self.hardware["npu_device"]["validation"] = "DETECTED"
        with self.assertRaises(ValueError): validate_record(self.hardware, "hardware")

    def test_ready_cannot_contain_inference_success_or_timing(self):
        record = copy.deepcopy(self.hardware)
        record.update(runtime_state="NPU_READY", evidence="NONE")
        record["npu_device"]["validation"] = "DETECTED"
        with self.assertRaises(ValueError): validate_record(record, "hardware")
        record.update(sample_count=0, successful_runs=0, samples_ms=[], model_validation=None,
                      npu_or_pipeline_ms_p50=None, npu_or_pipeline_ms_p95=None, npu_or_pipeline_ms_p99=None)
        self.assertEqual(validate_record(record, "hardware")["status"], "VALID")

    def test_wrong_identity_or_unverified_outputs_reject(self):
        for field, value in (("correct_output", False), ("non_identity", False), ("status", "UNVALIDATED")):
            record = copy.deepcopy(self.hardware)
            record["model_validation"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_record(record, "hardware")

    def test_critical_cpu_operator_and_missing_assignment_reject(self):
        for assignment in ("CPU", "UNASSIGNED"):
            record = copy.deepcopy(self.hardware)
            record["operator_assignment"]["nodes"][0]["assignment"] = assignment
            with self.subTest(assignment=assignment), self.assertRaises(ValueError): validate_record(record, "hardware")

    def test_sample_counts_quantiles_and_nonfinite_reject(self):
        for field, value in (("sample_count", 100), ("successful_runs", 100), ("npu_or_pipeline_ms_p99", 0.1), ("npu_or_pipeline_ms_p50", float("nan"))):
            record = copy.deepcopy(self.hardware)
            record[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_record(record, "hardware")

    def test_unknown_template_cannot_contain_fake_measurements(self):
        record = fixture("gate0_hardware_not_run")
        record["sample_count"] = 0
        with self.assertRaises(ValueError): validate_record(record, "hardware")

    def test_runtime_status_contract_still_refuses_real_npu(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "schemas/runtime-status.schema.json").read_text())
        record = fixture("runtime_cpu")
        record["runtime_state"], record["evidence"] = "NPU_ACTIVE", "REAL_NPU"
        self.assertFalse(Draft202012Validator(schema).is_valid(record))

    def test_checked_in_candidate_manifest_when_available(self):
        path = ROOT / "models/sesr-m7-256.provenance.json"
        self.assertTrue(path.is_file(), "Candidate provenance must be provided")
        result = validate_record(json.loads(path.read_text()), "provenance")
        self.assertFalse(result["license_clearance_verified"])


if __name__ == "__main__":
    unittest.main()
