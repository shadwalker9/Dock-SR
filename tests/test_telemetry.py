"""Validate telemetry contracts and reject misleading evidence classifications.

The checked-in fixtures are synthetic schema examples, never benchmark results.
Tests of actual generated JSON can import validate_report from this module.
"""

from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit(
        "Missing test dependency jsonschema. From the repository root run: "
        "python -m pip install --require-hashes -r requirements-dev.lock"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name):
    return json.loads((ROOT / "tests/fixtures" / name).read_text(encoding="utf-8"))


def validator(name):
    schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def validate_report(report, schema_name):
    """Raise ValidationError if a generated report violates the JSON contract."""
    validator(schema_name).validate(report)


def validate_vulkan_samples(report, artifact_directory):
    """Verify linked CSV values and nearest-rank summaries, never their provenance."""
    validate_report(report, "vulkan-benchmark.schema.json")
    base = Path(artifact_directory).resolve()
    samples_path = (base / report["artifacts"]["samples"]["path"]).resolve()
    if not samples_path.is_relative_to(base):
        raise ValueError("Sample artifact must remain within the run directory")
    with samples_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != report["artifacts"]["samples"]["columns"]:
            raise ValueError("CSV columns disagree with the declared artifact")
        rows = list(reader)
    configuration = report["configuration"]
    if len(rows) != configuration["measured_iterations"]:
        raise ValueError("CSV row count disagrees with measured iterations")
    metrics = {"host_dispatch_to_completion_ms": [], "gpu_dispatch_ms": []}
    for index, row in enumerate(rows):
        if int(row["sample_index"]) != index:
            raise ValueError("CSV sample indices must be contiguous and exclude warmups")
        frame = configuration["warmup_iterations"] + index if configuration["changing_frames"] else 0
        if int(row["input_frame_index"]) != frame:
            raise ValueError("CSV frame identity disagrees with the configured pattern")
        for name, values in metrics.items():
            if report["timings"][name] is None:
                if row[name] != "":
                    raise ValueError("Unavailable GPU timing must have an empty CSV field")
                continue
            value = float(row[name])
            if not math.isfinite(value) or value < 0:
                raise ValueError("CSV timings must be finite and nonnegative")
            values.append(value)
    if int(rows[-1]["input_frame_index"]) != configuration["final_input_frame_index"]:
        raise ValueError("Final capture frame disagrees with the last measured sample")
    for name, values in metrics.items():
        if not values:
            continue
        ordered = sorted(values)
        expected = {"min": ordered[0], "max": ordered[-1]}
        for label, quantile in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99)):
            expected[label] = ordered[max(1, math.ceil(quantile * len(ordered))) - 1]
        for label, expected_value in expected.items():
            actual = report["timings"][name][label]
            if not math.isfinite(actual) or not math.isclose(actual, expected_value, rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError(f"{name}.{label} disagrees with recorded nearest-rank samples")


def validate_generated_benchmark(result_path):
    """Validate a developer run's JSON, raw timings and image checksums.

    Return the parsed report. This checks artifact consistency, not independent
    pixel correctness, physical execution, or cryptographic provenance.
    """
    result_path = Path(result_path).resolve()

    def invalid_constant(value):
        raise ValueError(f"Non-JSON numeric constant: {value}")

    report = json.loads(result_path.read_text(encoding="utf-8"), parse_constant=invalid_constant)
    validate_vulkan_samples(report, result_path.parent)
    for name in ("input", "output"):
        artifact = report["artifacts"][name]
        image_path = (result_path.parent / artifact["path"]).resolve()
        if not image_path.is_relative_to(result_path.parent):
            raise ValueError("Image artifact must remain within the run directory")
        value = 14695981039346656037
        with image_path.open("rb") as stream:
            while block := stream.read(65536):
                for byte in block:
                    value = ((value ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
        if f"{value:016x}" != artifact["hash"]["value"]:
            raise ValueError(f"{name} image checksum disagrees with its report")
    return report


class TelemetryContractTests(unittest.TestCase):
    def test_all_schemas_are_valid_draft_2020_12(self):
        schemas = list((ROOT / "schemas").glob("*.schema.json"))
        self.assertGreaterEqual(len(schemas), 2)
        for path in schemas:
            with self.subTest(schema=path.name):
                validator(path.name)

    def test_absent_detection_fixture_is_valid(self):
        validate_report(load_fixture("detection_absent.json"), "detection.schema.json")

    def test_inventory_cannot_claim_npu_ready_or_hardware_validation(self):
        for field in ("npu_ready", "hardware_validated"):
            report = load_fixture("detection_absent.json")
            report[field] = True
            with self.subTest(field=field):
                self.assertFalse(validator("detection.schema.json").is_valid(report))

    def test_unrun_capability_is_unknown_not_false_or_supported(self):
        for value in (False, True):
            report = load_fixture("detection_absent.json")
            report["capabilities"]["vulkan_external_buffer"]["supported"] = value
            self.assertFalse(validator("detection.schema.json").is_valid(report))

    def test_detection_permission_failure_is_valid_and_distinct(self):
        report = load_fixture("detection_absent.json")
        report["device_nodes"]["accel"].update(status="permission_denied", errno=13)
        validate_report(report, "detection.schema.json")
        self.assertEqual(report["device_nodes"]["dri"]["status"], "absent")
        self.assertEqual(report["tools"]["xrt_smi_version"]["status"], "missing_tool")

    def test_software_benchmark_fixture_is_valid(self):
        validate_report(load_fixture("vulkan_software.json"), "vulkan-benchmark.schema.json")

    def test_cpu_cannot_be_labeled_hardware_evidence(self):
        report = load_fixture("vulkan_software.json")
        report["evidence_class"] = "vulkan_hardware"
        self.assertFalse(validator("vulkan-benchmark.schema.json").is_valid(report))

    def test_physical_gpu_label_does_not_enable_npu_or_game_metrics(self):
        report = load_fixture("vulkan_software.json")
        report["device"]["type"] = "integrated_gpu"
        report["evidence_class"] = "vulkan_hardware"
        validate_report(report, "vulkan-benchmark.schema.json")
        for metric in report["metrics"]:
            candidate = copy.deepcopy(report)
            candidate["metrics"][metric] = 60
            with self.subTest(metric=metric):
                self.assertFalse(validator("vulkan-benchmark.schema.json").is_valid(candidate))

    def test_virtual_gpu_requires_unknown_evidence(self):
        report = load_fixture("vulkan_software.json")
        report["device"]["type"] = "virtual_gpu"
        self.assertFalse(validator("vulkan-benchmark.schema.json").is_valid(report))
        report["evidence_class"] = "vulkan_unknown"
        validate_report(report, "vulkan-benchmark.schema.json")

    def test_missing_raw_samples_link_is_invalid(self):
        report = load_fixture("vulkan_software.json")
        del report["artifacts"]["samples"]
        self.assertFalse(validator("vulkan-benchmark.schema.json").is_valid(report))

    def test_no_timestamp_support_requires_null_gpu_timings(self):
        report = load_fixture("vulkan_software.json")
        report["timings"]["gpu_dispatch_ms"] = copy.deepcopy(report["timings"]["host_dispatch_to_completion_ms"])
        self.assertFalse(validator("vulkan-benchmark.schema.json").is_valid(report))

    def test_zero_measurement_run_cannot_be_valid_benchmark(self):
        report = load_fixture("vulkan_software.json")
        report["configuration"]["measured_iterations"] = 0
        self.assertFalse(validator("vulkan-benchmark.schema.json").is_valid(report))

    def test_raw_sample_summaries_are_checked_against_csv(self):
        report = load_fixture("vulkan_software.json")
        report["configuration"].update(changing_frames=False, final_input_frame_index=0)
        report["timings"]["host_dispatch_to_completion_ms"] = {
            "min": 1.0, "p50": 1.0, "p95": 3.0, "p99": 3.0, "max": 3.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            samples = Path(directory) / "samples.csv"
            header = ",".join(report["artifacts"]["samples"]["columns"]) + "\n"
            samples.write_text(header + "0,1.0,,0\n1,3.0,,0\n", encoding="utf-8")
            validate_vulkan_samples(report, directory)
            report["timings"]["host_dispatch_to_completion_ms"]["p50"] = 2.0
            with self.assertRaisesRegex(ValueError, "nearest-rank"):
                validate_vulkan_samples(report, directory)

    def test_nonfinite_or_missing_raw_samples_are_rejected(self):
        report = load_fixture("vulkan_software.json")
        report["configuration"].update(changing_frames=False, final_input_frame_index=0)
        with tempfile.TemporaryDirectory() as directory:
            samples = Path(directory) / "samples.csv"
            header = ",".join(report["artifacts"]["samples"]["columns"]) + "\n"
            samples.write_text(header + "0,nan,,0\n1,3.0,,0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finite"):
                validate_vulkan_samples(report, directory)
            samples.write_text(header + "0,1.0,,0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "row count"):
                validate_vulkan_samples(report, directory)

    def test_generated_run_rejects_a_mismatched_capture_checksum(self):
        report = load_fixture("vulkan_software.json")
        report["configuration"].update(changing_frames=False, final_input_frame_index=0)
        report["timings"]["host_dispatch_to_completion_ms"] = {
            "min": 1.0, "p50": 1.0, "p95": 3.0, "p99": 3.0, "max": 3.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "samples.csv").write_text(
                ",".join(report["artifacts"]["samples"]["columns"]) + "\n0,1.0,,0\n1,3.0,,0\n",
                encoding="utf-8",
            )
            (base / "input.ppm").write_bytes(b"synthetic mismatching image artifact")
            (base / "result.json").write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "input image checksum"):
                validate_generated_benchmark(base / "result.json")

    def test_mock_simulation_fixture_cannot_be_physical_evidence(self):
        report = load_fixture("mock_disabled.json")
        validate_report(report, "mock-state.schema.json")
        for field, value in (("hardware_validated", True), ("simulated", False),
                             ("unit", "milliseconds"), ("game_fps", 60)):
            candidate = copy.deepcopy(report)
            candidate[field] = value
            with self.subTest(field=field):
                self.assertFalse(validator("mock-state.schema.json").is_valid(candidate))

    def test_enabled_mock_requires_simulation_validation_and_execution(self):
        report = load_fixture("mock_disabled.json")
        report["profile_state"]["enabled"] = True
        self.assertFalse(validator("mock-state.schema.json").is_valid(report))
        report["scenario_executed"] = True
        report["profile_state"].update(active_profile="probe_720_1080", validation_status="validated")
        validate_report(report, "mock-state.schema.json")
        report["profile_state"]["validation_scope"] = "hardware"
        self.assertFalse(validator("mock-state.schema.json").is_valid(report))

    def test_runtime_cpu_fixture_is_valid_with_unmeasured_gpu_and_npu(self):
        report = load_fixture("runtime_cpu.json")
        validate_report(report, "runtime-status.schema.json")
        self.assertIsNone(report["timings_ms"]["gpu"])
        self.assertIsNone(report["timings_ms"]["npu"])
        self.assertEqual(report["npu"]["model_status"], "UNVALIDATED")

    def test_runtime_reserves_unverified_npu_states_evidence_and_timing(self):
        for field, value in (("runtime_state", "NPU_READY"),
                             ("runtime_state", "NPU_ACTIVE"), ("evidence", "REAL_NPU")):
            report = load_fixture("runtime_cpu.json")
            report[field] = value
            with self.subTest(field=field, value=value):
                self.assertFalse(validator("runtime-status.schema.json").is_valid(report))
        report = load_fixture("runtime_cpu.json")
        report["timings_ms"]["npu"] = 1
        self.assertFalse(validator("runtime-status.schema.json").is_valid(report))

    def test_runtime_software_vulkan_is_distinct_from_physical_gpu(self):
        report = load_fixture("runtime_cpu.json")
        report.update(runtime_state="SOFTWARE_VULKAN", evidence="SOFTWARE_VULKAN")
        report["timings_ms"].update(cpu=None, gpu=1.0)
        validate_report(report, "runtime-status.schema.json")
        report["evidence"] = "REAL_GPU"
        self.assertFalse(validator("runtime-status.schema.json").is_valid(report))
        report["runtime_state"] = "GPU_BASELINE_ACTIVE"
        validate_report(report, "runtime-status.schema.json")

    def test_runtime_frame_count_and_actual_output_must_agree(self):
        for value in (-1, 0, 18446744073709551616):
            report = load_fixture("runtime_cpu.json")
            report["frames_processed"] = value
            with self.subTest(value=value):
                self.assertFalse(validator("runtime-status.schema.json").is_valid(report))
        report = load_fixture("runtime_cpu.json")
        report["dimensions"]["actual"] = None
        self.assertFalse(validator("runtime-status.schema.json").is_valid(report))

    def test_runtime_cpu_error_preserves_truthful_prior_output_evidence(self):
        report = load_fixture("runtime_cpu.json")
        report.update(runtime_state="ERROR", last_error={"code": "output_write_failed", "message": "Synthetic error fixture"})
        report["timings_ms"]["cpu"] = None
        validate_report(report, "runtime-status.schema.json")
        report["runtime_state"] = "FALLBACK"
        validate_report(report, "runtime-status.schema.json")
        report["last_error"] = None
        self.assertFalse(validator("runtime-status.schema.json").is_valid(report))

    def test_runtime_cpu_failure_before_output_can_have_no_actual_dimensions(self):
        report = load_fixture("runtime_cpu.json")
        report.update(runtime_state="ERROR", evidence="NONE", frames_processed=0,
                      last_error={"code": "invalid_input", "message": "Synthetic invalid-input fixture"})
        report["dimensions"] = {"requested": None, "actual": None}
        report["timings_ms"] = {"cpu": None, "gpu": None, "npu": None}
        validate_report(report, "runtime-status.schema.json")

    def test_runtime_simulation_cannot_publish_physical_timings(self):
        report = load_fixture("runtime_cpu.json")
        report.update(runtime_state="MOCK_NPU_ACTIVE", evidence="SIMULATED")
        self.assertFalse(validator("runtime-status.schema.json").is_valid(report))
        report["timings_ms"]["cpu"] = None
        validate_report(report, "runtime-status.schema.json")

    def test_runtime_rejects_gpu_timing_from_cpu_and_invalid_dimensions(self):
        report = load_fixture("runtime_cpu.json")
        report["timings_ms"]["gpu"] = 1
        self.assertFalse(validator("runtime-status.schema.json").is_valid(report))
        report["timings_ms"]["gpu"] = None
        report["dimensions"]["requested"]["input"]["width"] = 0
        self.assertFalse(validator("runtime-status.schema.json").is_valid(report))


if __name__ == "__main__":
    unittest.main()
