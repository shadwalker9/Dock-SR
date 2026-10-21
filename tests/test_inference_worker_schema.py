#!/usr/bin/env python3
"""Validate native worker serialization and consumer arithmetic invariants.

Usage: test_inference_worker_schema.py COMPILED_NATIVE_TEST SCHEMA
Native callbacks in this test are simulated. Schema validation is not execution,
presentation or hardware attestation; actual CPU execution has a separate test.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator


def consistency_errors(document: dict) -> list[str]:
    """Check relationships that ordinary portable JSON Schema cannot express."""
    errors = []
    kind = document.get("document_type")
    sizes = {"uint8": 1, "int8": 1, "float32": 4}
    formats = {"RGB8": (3, "uint8"), "RGBA8": (4, "uint8"),
               "RGB_INT8": (3, "int8"), "RGBA_INT8": (4, "int8"),
               "RGB_FLOAT32": (3, "float32"), "RGBA_FLOAT32": (4, "float32")}

    def signature(shape, dtype, layout, extent, pixel_format):
        channels, required_dtype = formats[pixel_format]
        expected = ([1, channels, extent["height"], extent["width"]] if layout == "NCHW"
                    else [1, extent["height"], extent["width"], channels])
        if shape != expected or dtype != required_dtype:
            errors.append("output shape/layout/format/dtype mismatch")

    if kind == "docksr_inference_request":
        shape = document["tensor_shape"]
        size = math.prod(shape) * sizes[document["tensor_dtype"]]
        if size != document["buffer_size"] or size > 67108864:
            errors.append("input tensor logical byte mismatch/bound")
        stride = sizes[document["tensor_dtype"]]
        expected_strides = []
        for dimension in reversed(shape):
            expected_strides.append(stride)
            stride *= dimension
        if document["buffer_stride"] != list(reversed(expected_strides)):
            errors.append("input tensor is not declared contiguous byte strides")
        if document["deadline"] <= document["submit_timestamp"]:
            errors.append("deadline is not later than submit")
        channels = formats[document["source_format"]][0]
        if document["tensor_layout"] == "NCHW":
            height, width = shape[2], shape[3]
            if shape[1] != channels: errors.append("input channel count")
        else:
            height, width = shape[1], shape[2]
            if shape[3] != channels: errors.append("input channel count")
        tile = document["tile"]
        source = document["source_extent"]
        if tile is None:
            if source != {"width": width, "height": height}:
                errors.append("source and untiled input tensor extent differ")
        else:
            if (tile["source_x"] + tile["core_width"] > source["width"] or
                tile["source_y"] + tile["core_height"] > source["height"] or
                tile["core_width"] + tile["halo_left"] + tile["halo_right"] > width or
                tile["core_height"] + tile["halo_top"] + tile["halo_bottom"] > height or
                tile["output_width"] > document["expected_output_extent"]["width"] or
                tile["output_height"] > document["expected_output_extent"]["height"] or
                tile["output_x"] + tile["output_width"] > 8192 or
                tile["output_y"] + tile["output_height"] > 8192):
                errors.append("tile placement/halo/crop bounds")
        signature(document["expected_output_shape"], document["expected_output_dtype"],
                  document["expected_output_layout"], document["expected_output_extent"],
                  document["expected_output_format"])
        if math.prod(document["expected_output_shape"]) * sizes[document["expected_output_dtype"]] > 67108864:
            errors.append("expected output exceeds tensor bound")
    elif kind == "docksr_inference_result":
        signature(document["output_shape"], document["output_dtype"], document["output_layout"],
                  document["output_extent"], document["output_format"])
        ledger = document["ledger"]
        if document["copy_count"] != ledger["host_copy_count"]:
            errors.append("copy count disagrees with ledger")
        if document["valid"]:
            output = math.prod(document["output_shape"]) * sizes[document["output_dtype"]]
            if document["output_buffer_size"] != output or output > 67108864:
                errors.append("result output byte mismatch/bound")
            if document["logical_bytes"] < output or ledger["inference_output_logical_bytes"] < output:
                errors.append("valid output is missing logical payload accounting")
        if (ledger["submit_to_complete_duration"] is not None and document["inference_duration"] is not None
                and document["inference_duration"] > ledger["submit_to_complete_duration"]):
            errors.append("inference exceeds observed transaction duration")
        errors.extend(ledger_consistency(ledger))
    elif kind is None:
        errors.extend(ledger_consistency(document))
    return errors


def ledger_consistency(ledger):
    errors = []
    if (ledger["host_copy_count"] == 0) != (ledger["host_copy_bytes"] == 0):
        errors.append("copy count/bytes disagree")
    if ledger["crop_bytes"] > ledger["inference_output_logical_bytes"]:
        errors.append("crop exceeds produced output payload")
    if ledger["complete_to_consume_duration"] is not None and ledger["submit_to_complete_duration"] is None:
        errors.append("consume timing without completion timing")
    return errors


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    schema = json.loads(Path(sys.argv[2]).read_text())
    validator = Draft202012Validator(schema)
    validator.check_schema(schema)
    completed = subprocess.run([sys.argv[1], "--emit-json"], check=True, capture_output=True, text=True)
    documents = [json.loads(line) for line in completed.stdout.splitlines()]
    if len(documents) < 6:
        raise AssertionError("native worker did not emit the required independent observations")

    def errors(document):
        structural = list(validator.iter_errors(document))
        return structural if structural else consistency_errors(document)

    for index, document in enumerate(documents):
        failures = errors(document)
        if failures: raise AssertionError(f"native observation {index} invalid: {failures[0]}")
        if document.get("valid") and document.get("evidence_class") != "SIMULATED":
            raise AssertionError("unit callbacks were emitted as actual CPU/hardware execution")
    request = next(d for d in documents if d.get("document_type") == "docksr_inference_request" and d["tile"] is None)
    result = next(d for d in documents if d.get("valid") and d.get("document_type") == "docksr_inference_result")
    future = next(d for d in documents if d.get("document_type") == "docksr_future_backends")
    mutations = [
        (request, "missing model hash", lambda d: d.pop("model_sha256")),
        (request, "unknown metadata", lambda d: d.update(invented=True)),
        (request, "zero frame ID", lambda d: d.update(frame_id=0)),
        (request, "negative generation", lambda d: d.update(configuration_generation=-1)),
        (request, "short hash", lambda d: d.update(model_sha256="deadbeef")),
        (request, "ambiguous clock domain", lambda d: d.update(clock_domain="wall_clock")),
        (request, "wrong byte count", lambda d: d.update(buffer_size=d["buffer_size"]+1)),
        (request, "wrong stride", lambda d: d["buffer_stride"].__setitem__(0, 1)),
        (request, "bad deadline", lambda d: d.update(deadline=d["submit_timestamp"])),
        (request, "bad input channels", lambda d: d["tensor_shape"].__setitem__(3, 4)),
        (request, "wrong output shape", lambda d: d["expected_output_shape"].__setitem__(1, 3)),
        (request, "unsupported external ownership", lambda d: d.update(buffer_ownership="DMA_BUF")),
        (result, "NPU execution evidence", lambda d: d.update(evidence_class="REAL_NPU")),
        (result, "fake NPU backend", lambda d: d.update(backend_kind="VITIS_AI_NPU")),
        (result, "NPU device true", lambda d: d.update(npu_device_detected=True)),
        (result, "NPU runtime true", lambda d: d.update(npu_runtime_ready=True)),
        (result, "NPU inference true", lambda d: d.update(npu_inference_verified=True)),
        (result, "NPU consumption true", lambda d: d.update(npu_game_frames_consumed=True)),
        (result, "presentation true", lambda d: d.update(presented=True)),
        (result, "mock relabeled CPU", lambda d: d.update(evidence_class="REAL_CPU")),
        (result, "valid unavailable", lambda d: d.update(backend_kind="UNAVAILABLE", evidence_class="NOT_RUN")),
        (result, "valid fallback", lambda d: d.update(fallback_reason="HAS_ERROR")),
        (result, "output truncated", lambda d: d.update(output_buffer_size=d["output_buffer_size"]-1)),
        (result, "output RGB swap", lambda d: d.update(output_layout="NCHW")),
        (result, "copy count mismatch", lambda d: d.update(copy_count=1)),
        (result, "copy bytes without copy", lambda d: d["ledger"].update(host_copy_bytes=1)),
        (result, "missing inference accounting", lambda d: d["ledger"].update(inference_output_logical_bytes=0)),
        (result, "crop overflow", lambda d: d["ledger"].update(crop_bytes=2**64-1)),
        (result, "counter overflow", lambda d: d.update(logical_bytes=2**64)),
        (result, "claimed DDR measurement", lambda d: d["ledger"].update(physical_ddr_traffic=0)),
        (result, "claimed GPU upload", lambda d: d["ledger"].update(gpu_upload_bytes=0)),
        (result, "runtime zero-copy claim", lambda d: d["ledger"].update(runtime_internal_copy_status="ZERO_COPY")),
        (result, "simulation with real timing", lambda d: d["ledger"].update(timing_class="OBSERVED_HOST_CPU")),
        (result, "consume timing without completion", lambda d: d["ledger"].update(submit_to_complete_duration=None,complete_to_consume_duration=1)),
        (result, "inference longer than transaction", lambda d: d.update(inference_duration=1000)),
        (future, "unimplemented backend active", lambda d: d["backends"][0].update(status="ACTIVE")),
        (future, "future hardware inference", lambda d: d.update(npu_inference_verified=True)),
    ]
    for base, label, change in mutations:
        document = copy.deepcopy(base)
        change(document)
        if not errors(document): raise AssertionError(f"invalid mutation accepted: {label}")
    print(f"PASS: {len(documents)} serialized worker observations; {len(mutations)} negative schema/consistency cases; no hardware/presentation attestation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
