#!/usr/bin/env python3
"""Private, one-job CPU bridge for docksr-worker-reference.

This is a prototype transport adapter around CpuReferenceSession, not another
model inspector, provider selector, public IPC protocol or production worker.
Raw-file payload transfers are counted; NumPy/ORT internal copies are unknown.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

# -I is used by the native launcher. Add only this reviewed script directory,
# not the current directory, PYTHONPATH or a caller-controlled module path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import onnx_reference as reference


LIMIT = reference.MAX_TENSOR_BYTES
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


def fnv64(data):
    value = 14695981039346656037
    for byte in memoryview(data).cast("B"):
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f"{value:016x}"


def regular_bytes(path, limit):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size > limit:
        raise ValueError("Unsafe or oversized bridge file")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Bridge file grew beyond its limit")
    return data


def create(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def shape(text):
    if not re.fullmatch(r"[0-9]+(?:,[0-9]+){3}", text):
        raise ValueError("Only explicit rank-four bridge shapes are accepted")
    result = tuple(map(int, text.split(",")))
    if result[0] != 1 or any(not 1 <= x <= 8192 for x in result):
        raise ValueError("Invalid static tensor shape")
    return result


def execute(model, request_path):
    started = time.perf_counter_ns()
    parent = request_path.parent
    info = parent.stat()
    if parent.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Bridge directory must be owned mode0700")
    lines = regular_bytes(request_path, 4096).decode("ascii").splitlines()
    if len(lines) != 14 or lines[0] != "DOCKSR_CPU_REQUEST_V1":
        raise ValueError("Invalid fixed bridge request")
    (_, session_id, frame, generation, model_id, model_hash, trace_id,
     dtype_name, layout, input_dimensions, output_dtype_name,
     output_dimensions, input_size, input_fingerprint) = lines
    if not all(IDENTIFIER.fullmatch(v) for v in (session_id, model_id, trace_id)):
        raise ValueError("Invalid request identifier")
    if not HASH.fullmatch(model_hash) or not re.fullmatch(r"[0-9a-f]{16}", input_fingerprint):
        raise ValueError("Invalid request hash")
    if any(not re.fullmatch(r"[1-9][0-9]{0,19}", v) or int(v) >= 2**64 for v in (frame, generation)):
        raise ValueError("Invalid frame or generation")
    if layout not in {"NCHW", "NHWC"} or dtype_name not in {"int8", "uint8", "float32"} or output_dtype_name not in {"int8", "uint8", "float32"}:
        raise ValueError("Unsupported bridge signature")
    input_shape, output_shape = shape(input_dimensions), shape(output_dimensions)
    runtime = reference.CpuReferenceSession(model, layout=layout, initialize=False)
    np = runtime.np
    if runtime.inspection["model"]["sha256"] != model_hash:
        raise ValueError("MODEL_HASH_MISMATCH")
    if (runtime.input_shape != input_shape or runtime.output_shape != output_shape or
            str(runtime.input_dtype) != dtype_name or str(runtime.output_dtype) != output_dtype_name):
        raise ValueError("MODEL_SIGNATURE_MISMATCH")
    expected_input = math.prod(input_shape) * runtime.input_dtype.itemsize
    expected_output = math.prod(output_shape) * runtime.output_dtype.itemsize
    if not input_size.isdecimal() or int(input_size) != expected_input or max(expected_input, expected_output) > LIMIT:
        raise ValueError("Invalid bridge byte count")
    raw = regular_bytes(parent / "input.raw", LIMIT)
    if len(raw) != expected_input or fnv64(raw) != input_fingerprint:
        raise ValueError("INPUT_BUFFER_MISMATCH")
    original_input_sha = hashlib.sha256(raw).hexdigest()
    tensor = np.frombuffer(raw, dtype=runtime.input_dtype).reshape(input_shape)
    output = np.empty(output_shape, dtype=runtime.output_dtype)
    runtime.initialize()
    times = []
    first_hash = None
    for _ in range(2):
        runtime.run(tensor, output_buffer=output)
        digest = hashlib.sha256(memoryview(output).cast("B")).hexdigest()
        if first_hash is not None and digest != first_hash:
            raise ValueError("CPU_REPEAT_MISMATCH")
        first_hash = digest
        times.append(round(runtime.last_inference_ms * 1_000_000))
    if (original_input_sha != hashlib.sha256(raw).hexdigest() or
            original_input_sha != hashlib.sha256(memoryview(tensor).cast("B")).hexdigest()):
        raise ValueError("INPUT_MUTATED")
    if reference.sha256(model) != model_hash:
        raise ValueError("MODEL_CHANGED_DURING_EXECUTION")
    output_fingerprint = fnv64(output)
    create(parent / "output.raw", memoryview(output).cast("B"))
    elapsed = time.perf_counter_ns() - started
    initialization_ns = round(runtime.initialization_ms * 1_000_000)
    receipt = ["DOCKSR_CPU_RESULT_V1", session_id, frame, generation, model_id,
               model_hash, trace_id, output_dtype_name, layout, output_dimensions,
               str(expected_output), input_fingerprint, output_fingerprint, first_hash,
               "2", str(initialization_ns), str(sum(times)), str(expected_input + expected_output),
               str(elapsed), "REAL_CPU", "CPUExecutionProvider"]
    create(parent / "receipt.txt", ("\n".join(receipt) + "\n").encode("ascii"))
    record = {"schema_version": "1.0.0", "document_type": "docksr_cpu_worker_bridge",
              "session_id": session_id, "frame_id": int(frame),
              "configuration_generation": int(generation), "model_id": model_id,
              "model_sha256": model_hash, "trace_id": trace_id,
              "evidence_class": "REAL_CPU", "provider": "CPUExecutionProvider",
              "physical_npu": "NOT_RUN", "game_frame_presentation": "NOT_RUN",
              "input_shape": list(input_shape), "output_shape": list(output_shape),
              "input_dtype": dtype_name, "output_dtype": output_dtype_name, "layout": layout,
              "input_sha256": original_input_sha, "output_sha256": first_hash,
              "successful_inference_calls": runtime.successful_runs,
              "initialization_ns": initialization_ns, "inference_samples_ns": times,
              "child_total_ns": elapsed, "known_python_buffer_bytes": expected_input + expected_output,
              "runtime_internal_copies": "UNKNOWN", "runtime_internal_allocations": "UNKNOWN",
              "copy_scope": "four raw-file payload transfers across native/Python boundaries; not all process copies or DDR traffic",
              "per_job_process_and_session_initialization": True,
              "repeated_outputs_equal": True, "model_mutated": False}
    create(parent / "cpu-evidence.json", (json.dumps(record, indent=2, allow_nan=False) + "\n").encode())
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    try:
        execute(args.model, args.request)
        return 0
    except (reference.ReferenceError, OSError, ValueError, UnicodeError) as error:
        print(json.dumps({"status": "FAILED", "valid": False,
                          "code": getattr(error, "code", "CPU_BRIDGE_FAILED"),
                          "message": str(error)[:256], "physical_npu": "NOT_RUN"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
