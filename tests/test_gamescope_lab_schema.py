#!/usr/bin/env python3
"""Validate actual C++ contract serialization, including negative mutations.

Usage: test_gamescope_lab_schema.py COMPILED_CONTRACT_TEST SCHEMA
These observations come from explicit CONTRACT_TEST callbacks. Neither this
test nor a syntactically valid status document attests that pixels were drawn.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator


def consistency_errors(document: dict) -> list[str]:
    """Consumer arithmetic checks that portable JSON Schema cannot express."""
    errors = []
    if document["configuration_generation"] > document["requested_configuration_generation"]:
        errors.append("effective generation exceeds requested generation")
    if document["frame_seen_count"]:
        if document["last_frame_generation"] != document["configuration_generation"]:
            errors.append("last-frame generation does not match effective generation")
        if document["last_frame_id"] < document["frame_seen_count"]:
            errors.append("strictly increasing positive frame IDs cannot trail seen count")
    for field in ("frame_processed_count", "frame_presented_count", "fallback_count"):
        if document[field] > document["frame_seen_count"]:
            errors.append(f"{field} exceeds seen count")
    for field in ("frame_processed_count", "frame_presented_count"):
        if document["filter_frame_presented_count"] > document[field]:
            errors.append(f"custom presentations exceed {field}")
    if document["last_control_request_id"] > document["last_request_id"]:
        errors.append("mutating request ID exceeds last accepted request ID")
    if document["control_ack_state"] == "PENDING":
        if document["requested_configuration_generation"] <= document["configuration_generation"]:
            errors.append("pending mode requires a newer requested generation")
        if document["last_control_request_id"] == 0:
            errors.append("pending mode has no mutating request")
    return errors


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    validator = Draft202012Validator(json.loads(Path(sys.argv[2]).read_text()))
    validator.check_schema(validator.schema)
    result = subprocess.run([sys.argv[1], "--emit-json"], check=True, capture_output=True, text=True)
    documents = [json.loads(line) for line in result.stdout.splitlines()]
    if not documents:
        raise AssertionError("contract executable emitted no serialized observations")

    def errors(document):
        structural = list(validator.iter_errors(document))
        return structural if structural else consistency_errors(document)

    for index, document in enumerate(documents):
        failures = errors(document)
        if failures:
            raise AssertionError(f"emitted observation {index} invalid: {failures[0]}")
        if document["evidence_class"] not in ("CONTRACT_TEST", "SOURCE_INSPECTED", "BUILD_VERIFIED", "NOT_RUN", "BLOCKED", "FAILED"):
            raise AssertionError("unit callbacks were incorrectly emitted as execution/hardware evidence")

    baseline = next(d for d in documents if d["filter_output_presented"])
    mutations = {
        "missing required capture": lambda d: d.pop("capture_method"),
        "unrecognized property": lambda d: d.update(invented=True),
        "NPU device true": lambda d: d.update(npu_device_detected=True),
        "NPU runtime true": lambda d: d.update(npu_runtime_ready=True),
        "NPU inference true": lambda d: d.update(npu_inference_verified=True),
        "NPU game frames true": lambda d: d.update(npu_game_frames_consumed=True),
        "NPU string false": lambda d: d.update(npu_game_frames_consumed="false"),
        "real NPU evidence": lambda d: d.update(evidence_class="REAL_NPU"),
        "source-only rendering claim": lambda d: d.update(evidence_class="SOURCE_INSPECTED"),
        "contract mislabeled physical environment": lambda d: d.update(environment="physical_gpu"),
        "short source revision": lambda d: d.update(upstream_gamescope_commit="deadbeef"),
        "negative count": lambda d: d.update(frame_processed_count=-1),
        "uint64 count overflow": lambda d: d.update(frame_processed_count=2**64),
        "negative extent": lambda d: d["input_extent"].update(width=-1),
        "active non-4K extent": lambda d: d["output_extent"].update(width=1920),
        "presentation without dispatch": lambda d: d.update(filter_dispatched=False),
        "unattached dispatch": lambda d: d.update(backend_attached=False),
        "no frames but presented": lambda d: d.update(frame_seen_count=0),
        "stale last-frame generation": lambda d: d.update(last_frame_generation=0),
        "effective future generation": lambda d: d.update(configuration_generation=d["requested_configuration_generation"] + 1),
        "processing exceeds observations": lambda d: d.update(frame_processed_count=d["frame_seen_count"] + 1),
        "presentation exceeds observations": lambda d: d.update(frame_presented_count=d["frame_seen_count"] + 1),
        "custom presentation exceeds processing": lambda d: d.update(filter_frame_presented_count=d["frame_processed_count"] + 1),
        "fallback exceeds observations": lambda d: d.update(fallback_count=d["frame_seen_count"] + 1),
        "future mutating request ID": lambda d: d.update(last_control_request_id=d["last_request_id"] + 1),
        "pending without new generation": lambda d: d.update(control_ack_state="PENDING"),
        "future schema version": lambda d: d.update(schema_version="2.0.0"),
    }
    for name, mutate in mutations.items():
        document = copy.deepcopy(baseline)
        mutate(document)
        if not errors(document):
            raise AssertionError(f"invalid mutation accepted: {name}")
    print(f"PASS: {len(documents)} serialized contract observations; {len(mutations)} negative schema/consistency cases; no rendering or hardware proof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
