#!/usr/bin/env python3
"""Read-only device-day inventory and an unexecuted Vitis AI probe plan.

Reuses docksr_detect and import_sesr. This command never creates an inference
session, compiles a model, imports memory, installs a driver or emits REAL_NPU.
Use hardware-evidence.schema.json for a later actual hardware measurement.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import docksr_detect
import import_sesr


class InventoryRunner(docksr_detect.CommandRunner):
    def run(self, argv, timeout=10.0):
        if argv[0] == "vulkaninfo":
            return {"status": "not_run", "argv": list(argv),
                    "reason": "This NPU preparation command does not repeat graphics probes."}
        return super().run(argv, timeout)


def runtime_inventory(inspect_python=False) -> dict[str, Any]:
    packages = {}
    for package in ("onnxruntime", "onnxruntime-vitisai", "onnxruntime-directml"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    result = {"packages": packages, "provider_listing_state": "NOT_RUN",
              "available_providers": [], "provider_registration_is_execution": False}
    if not inspect_python:
        return result
    # Loading the installed Python module is opt-in and bounded. Querying the
    # provider list neither requests Vitis AI nor creates an inference session.
    code = ("import json,onnxruntime as ort;"
            "print(json.dumps({'version':ort.__version__,"
            "'providers':ort.get_available_providers()}))")
    try:
        process = subprocess.run([sys.executable, "-I", "-c", code],
                                 capture_output=True, timeout=15, check=False)
        if process.returncode or len(process.stdout) > 16384:
            result["provider_listing_state"] = "UNAVAILABLE"
            return result
        value = json.loads(process.stdout)
        providers = value["providers"]
        if not isinstance(providers, list) or len(providers) > 128 or any(
                not isinstance(item, str) or not 1 <= len(item) <= 128 for item in providers):
            raise ValueError("invalid provider metadata")
        result["provider_listing_state"] = "LISTED"
        result["available_providers"] = providers
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        result["provider_listing_state"] = "UNAVAILABLE"
    return result


def model_identity(model=None):
    pin = import_sesr.PINNED_IDENTITY
    result = {"model_id": pin.model_id, "source_revision": pin.revision,
              "expected_sha256": pin.sha256, "expected_size_bytes": pin.size_bytes,
              "state": "NOT_SUPPLIED", "actual_sha256": None, "actual_size_bytes": None,
              "error_code": None, "execution_performed": False}
    if model is None:
        return result
    try:
        raw, digest = import_sesr._read_verified(import_sesr._absolute(model), pin)
        result.update(state="VERIFIED_LOCAL", actual_sha256=digest, actual_size_bytes=len(raw))
    except (import_sesr.ImportFailure, OSError) as error:
        result.update(state="FAILED", error_code=getattr(error, "code", "MODEL_READ_FAILED"))
    return result


def prepare(model=None, *, fs=None, runner=None, runtime=None, timestamp=None):
    inventory = docksr_detect.detect(fs=fs, runner=runner or InventoryRunner(),
                                    timestamp=timestamp)
    return {
        "schema_version": "1.0.0", "document_type": "docksr_npu_probe_preparation",
        "generated_at_utc": timestamp or datetime.now(timezone.utc).isoformat(),
        "scope": "READ_ONLY_INVENTORY_AND_UNEXECUTED_PROCEDURE",
        "physical_test_status": "NOT_RUN", "evidence_class": "VERIFIED_LOCAL",
        "hardware_execution_verified": False,
        "npu_device_detected": False, "npu_runtime_ready": False,
        "npu_inference_verified": False, "npu_game_frames_consumed": False,
        "inventory": inventory, "runtime": runtime if runtime is not None else runtime_inventory(),
        "model": model_identity(model),
        "planned_probe": {
            "provider": "VitisAIExecutionProvider", "target": "X2",
            "target_selection_state": "PLANNED_AFTER_SUPPORTED_DEVICE_RUNTIME_CHECK",
            "model_mutation": False, "provider_requested": False,
            "compiled_model_cache_identity": None,
            "operator_placement_status": "NOT_RUN", "cpu_partition_status": "NOT_RUN",
            "comparison_status": "NOT_RUN", "comparison_atol": None, "comparison_rtol": None,
            "initialization_duration_ms": None, "compilation_duration_ms": None,
            "warm_inference_samples_ms": [], "physical_npu_self_test_verified": False,
            "neural_result_consumed_in_presented_frame": False,
            "hardware_evidence_schema": "hardware-evidence.schema.json",
        },
        "external_memory": {
            "ort_interop_api_status": "UNKNOWN",
            "api_query_status": "NOT_RUN",
            "api_basis": "Python package/provider metadata does not query optional native OrtInteropApi.",
            "provider_importer_status": "NOT_RUN", "handle_type_status": "NOT_RUN",
            "memory_import_status": "NOT_RUN", "imported_memory_inference_status": "NOT_RUN",
            "vulkan_xrt_sharing_status": "NOT_RUN", "zero_copy_verified": False,
        },
        "limitations": [
            "Device inventory records visibility only; this command does not identify a physical target as validated.",
            "A registered provider is not operator placement, physical inference or a presented neural frame.",
            "X2 is a planned option only after the actual supported device/runtime is identified; no xclbin is selected.",
            "No unsupported C API is inferred from a version number or missing Python binding.",
            "Use the device-day procedure and existing hardware-evidence contract for actual target results.",
        ],
    }


def write_new_private(path, report):
    path = import_sesr._absolute(path)
    import_sesr._check_parents(path.parent, reject_git=True)
    if path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o077:
        raise ValueError("Output parent must be owner-controlled and mode0700")
    data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, help="Verify unchanged pinned SESR bytes; never execute them")
    parser.add_argument("--inspect-ort", action="store_true", help="Opt-in bounded Python provider-list query only")
    parser.add_argument("--output", type=Path, help="New owner-only JSON outside Git; parent must be0700")
    args = parser.parse_args(argv)
    try:
        report = prepare(args.model, runtime=runtime_inventory(args.inspect_ort))
        if args.output:
            write_new_private(args.output, report)
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report["model"]["state"] == "FAILED" else 0
    except (OSError, ValueError, import_sesr.ImportFailure):
        print("ERROR: unsafe/unavailable output or inventory input", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
