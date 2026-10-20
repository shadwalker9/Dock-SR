#!/usr/bin/env python3
"""Bounded, deterministic CPU-only ONNX reference inference for Gate-0A.

Optional ONNX/numpy/ONNX Runtime dependencies are imported only when this tool
is used. No remote code, custom operator library, provider plugin or external
tensor file is loaded. This is not an untrusted-model execution sandbox.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import time


MAX_ELEMENTS = 16_777_216
MAX_TENSOR_BYTES = 67_108_864
NUMERIC_TYPES = {1: "float32", 2: "uint8", 3: "int8", 4: "uint16", 5: "int16",
                 6: "int32", 7: "int64", 10: "float16", 11: "float64", 12: "uint32", 13: "uint64"}


class ReferenceError(RuntimeError):
    def __init__(self, code, message, *, completed_cpu_run=False, not_run=False):
        super().__init__(message)
        self.code, self.completed_cpu_run, self.not_run = code, completed_cpu_run, not_run


def dependencies():
    try:
        import numpy as np
        import onnxruntime as ort
        import onnx
        import onnx_inspect
    except ImportError as error:
        raise ReferenceError("OPTIONAL_DEPENDENCY_MISSING",
            "Use the optional Gate-0 environment: python -m pip install --require-hashes -r requirements-gate0.lock",
            not_run=True) from error
    return np, ort, onnx, onnx_inspect


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            result.update(block)
    return result.hexdigest()


def bounded_shape(dimensions, dtype, override, label):
    if not isinstance(dimensions, list) or not 1 <= len(dimensions) <= 8:
        raise ReferenceError("UNSUPPORTED_RANK", f"{label} must have a known rank from 1 to 8")
    if override is not None and len(override) != len(dimensions):
        raise ReferenceError("SHAPE_OVERRIDE_RANK", f"{label} override rank differs from the graph")
    resolved = []
    for index, dimension in enumerate(dimensions):
        candidate = override[index] if override is not None else None
        if dimension["kind"] == "static":
            value = dimension["value"]
            if candidate is not None and candidate != value:
                raise ReferenceError("STATIC_SHAPE_OVERRIDE", f"{label} override cannot replace a static graph dimension")
        else:
            if candidate is None:
                raise ReferenceError("DYNAMIC_SHAPE_REQUIRES_OVERRIDE", f"{label} symbolic/unknown dimensions require an explicit bounded shape")
            value = candidate
        if type(value) is not int or not 1 <= value <= 8192:
            raise ReferenceError("SHAPE_BOUNDS", f"{label} dimensions must be integers in 1..8192")
        resolved.append(value)
    elements = math.prod(resolved)
    if elements > MAX_ELEMENTS or elements * dtype.itemsize > MAX_TENSOR_BYTES:
        raise ReferenceError("TENSOR_BOUNDS", f"{label} exceeds the per-tensor reference limit")
    return tuple(resolved)


def synthetic_input(np, shape, dtype):
    values = np.arange(math.prod(shape), dtype=np.int64).reshape(shape) % 251
    if dtype.kind == "f":
        return np.ascontiguousarray(values.astype(dtype) / dtype.type(250))
    if dtype.kind == "u":
        return np.ascontiguousarray((values % min(251, int(np.iinfo(dtype).max) + 1)).astype(dtype))
    return np.ascontiguousarray(np.clip(values - 125, np.iinfo(dtype).min, np.iinfo(dtype).max).astype(dtype))


def _validate_array(np, array, shape, dtype, label):
    if not isinstance(array, np.ndarray) or array.shape != shape or array.dtype != dtype:
        raise ReferenceError("TENSOR_SIGNATURE_MISMATCH", f"{label} shape/dtype differs from the declared graph-derived signature")
    if array.nbytes > MAX_TENSOR_BYTES or not bool(np.isfinite(array).all()):
        raise ReferenceError("NONFINITE_OR_OVERSIZED_TENSOR", f"{label} must contain finite bounded numeric data")


def _write(path, writer):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as stream:
        writer(stream)


def run_reference(model, output_dir, *, input_path=None, layout="UNSPECIFIED", shape=None,
                  output_shape=None, warmup=2, samples=3, atol=1e-6, rtol=1e-5,
                  require_nonidentity=True):
    model, output_dir = Path(model), Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise ReferenceError("OUTPUT_ALREADY_EXISTS", "Reference output directory must be new")
    if not output_dir.parent.is_dir() or output_dir.parent.is_symlink():
        raise ReferenceError("OUTPUT_PARENT_INVALID", "Reference output parent must be an existing non-symlink directory")
    if layout not in {"NCHW", "NHWC", "UNSPECIFIED"}:
        raise ReferenceError("INVALID_LAYOUT", "Layout is a caller declaration, limited to NCHW, NHWC or UNSPECIFIED")
    if type(warmup) is not int or not 0 <= warmup <= 100 or type(samples) is not int or not 2 <= samples <= 1000:
        raise ReferenceError("INVALID_RUN_COUNTS", "Use 0..100 warmups and 2..1000 measured repeats")
    if type(atol) not in (float, int) or type(rtol) not in (float, int) or not math.isfinite(atol) or not math.isfinite(rtol) or atol < 0 or rtol < 0:
        raise ReferenceError("INVALID_TOLERANCE", "Comparison tolerances must be finite and nonnegative")
    if not model.exists():
        raise ReferenceError("MODEL_MISSING", "No model artifact was available to execute", not_run=True)
    np, ort, onnx, inspector = dependencies()
    try:
        model_bytes = inspector.read_model_bytes(model)
        inspection = inspector.inspect_bytes(model_bytes, filename=model.name)
    except Exception as error:
        raise ReferenceError("MODEL_INSPECTION_FAILED", "Model could not be safely inspected before execution") from error
    graph = inspection["graph"]
    if inspection["external_data"] or inspection["custom_domains"] or graph["subgraph_count"] or graph["function_count"]:
        raise ReferenceError("UNSUPPORTED_MODEL_FEATURE", "External data, custom domains, subgraphs and local functions are rejected before runtime loading", not_run=True)
    # Reject training graphs and sparse initializers too; this bounded first
    # runner does not need their extra signatures or execution semantics.
    proto = onnx.load_model_from_string(model_bytes)
    if proto.training_info or proto.graph.sparse_initializer:
        raise ReferenceError("UNSUPPORTED_MODEL_FEATURE", "Training information and sparse initializers are outside this runner's scope", not_run=True)
    initializer_names = {tensor.name for tensor in proto.graph.initializer}
    inputs = [value for value in graph["inputs"] if value["name"] not in initializer_names]
    outputs = graph["outputs"]
    if len(inputs) != 1 or len(outputs) != 1:
        raise ReferenceError("SINGLE_IO_REQUIRED", "This reference tool supports exactly one runtime input and one output", not_run=True)
    for value in (inputs[0], outputs[0]):
        if value["kind"] != "tensor" or value.get("dtype_code") not in NUMERIC_TYPES:
            raise ReferenceError("UNSUPPORTED_TENSOR_TYPE", "Only ordinary numeric tensor I/O is supported", not_run=True)
    input_dtype, output_dtype = (np.dtype(NUMERIC_TYPES[value["dtype_code"]]) for value in (inputs[0], outputs[0]))
    input_shape = bounded_shape(inputs[0]["dimensions"], input_dtype, shape, "Input")
    expected_output = bounded_shape(outputs[0]["dimensions"], output_dtype, output_shape, "Output")
    if layout != "UNSPECIFIED" and len(input_shape) != 4:
        raise ReferenceError("LAYOUT_RANK_MISMATCH", "NCHW/NHWC declarations require a rank-four input; no transpose is performed")
    if input_path is None:
        tensor = synthetic_input(np, input_shape, input_dtype)
        source = {"kind": "synthetic", "pattern": "flat_arange_mod251; float:/250, unsigned:mod-range, signed:minus125-clipped", "file_sha256": None}
    else:
        path = Path(input_path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size > MAX_TENSOR_BYTES + 65536:
            raise ReferenceError("INPUT_FILE_UNSAFE", "NPY input must be a bounded regular non-symlink file")
        try:
            with path.open("rb") as stream:
                input_bytes = stream.read(MAX_TENSOR_BYTES + 65537)
            if len(input_bytes) > MAX_TENSOR_BYTES + 65536:
                raise ReferenceError("INPUT_FILE_UNSAFE", "NPY input grew beyond its byte limit")
            buffer = io.BytesIO(input_bytes)
            version = np.lib.format.read_magic(buffer)
            if version == (1, 0):
                header_shape, _, header_dtype = np.lib.format.read_array_header_1_0(buffer, max_header_size=16384)
            elif version == (2, 0):
                header_shape, _, header_dtype = np.lib.format.read_array_header_2_0(buffer, max_header_size=16384)
            else:
                raise ReferenceError("INPUT_FORMAT_UNSUPPORTED", "Only numeric NPY versions 1.0 and 2.0 are supported")
            # Validate header dimensions before numpy can allocate from them.
            if header_shape != input_shape or header_dtype != input_dtype or header_dtype.hasobject:
                raise ReferenceError("TENSOR_SIGNATURE_MISMATCH", "Input shape/dtype differs from the declared graph-derived signature; pickle is not accepted")
            buffer.seek(0)
            tensor = np.load(buffer, allow_pickle=False, max_header_size=16384)
        except ReferenceError:
            raise
        except Exception as error:
            raise ReferenceError("INPUT_LOAD_FAILED", "Input must be one numeric NPY array; pickle and archives are not accepted") from error
        source = {"kind": "npy", "pattern": None, "file_sha256": hashlib.sha256(input_bytes).hexdigest()}
    _validate_array(np, tensor, input_shape, input_dtype, "Input")
    tensor = np.ascontiguousarray(tensor)
    original_input_hash = hashlib.sha256(tensor.tobytes(order="C")).hexdigest()
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    options.enable_cpu_mem_arena = False
    deterministic_option = hasattr(options, "use_deterministic_compute")
    if deterministic_option:
        options.use_deterministic_compute = True
    initialized = time.perf_counter_ns()
    try:
        session = ort.InferenceSession(model_bytes, sess_options=options, providers=["CPUExecutionProvider"])
        session.disable_fallback()
    except Exception as error:
        raise ReferenceError("CPU_SESSION_UNAVAILABLE", "CPU ONNX Runtime could not initialize this graph; model-specific reference was not run", not_run=True) from error
    initialization_ms = (time.perf_counter_ns() - initialized) / 1_000_000
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise ReferenceError("PROVIDER_CONFIGURATION_MISMATCH", "CPU must be the only enabled execution provider")
    if len(session.get_inputs()) != 1 or len(session.get_outputs()) != 1 or session.get_inputs()[0].name != inputs[0]["name"] or session.get_outputs()[0].name != outputs[0]["name"]:
        raise ReferenceError("RUNTIME_SIGNATURE_MISMATCH", "Runtime I/O names/count differ from the inspected graph")
    baseline = None
    sample_times = []
    successful = 0
    for index in range(warmup + samples):
        started = time.perf_counter_ns()
        try:
            result = session.run([outputs[0]["name"]], {inputs[0]["name"]: tensor})[0]
        except Exception as error:
            raise ReferenceError("CPU_INFERENCE_FAILED", "The configured CPU provider failed to produce output", completed_cpu_run=successful > 0) from error
        duration = (time.perf_counter_ns() - started) / 1_000_000
        successful += 1
        try:
            _validate_array(np, result, expected_output, output_dtype, "Output")
        except ReferenceError as error:
            error.completed_cpu_run = True
            raise
        if baseline is None:
            baseline = result.copy()
        elif not np.array_equal(baseline, result):
            raise ReferenceError("CPU_REPEAT_MISMATCH", "Repeated identical CPU inputs did not produce bitwise-equal tensors", completed_cpu_run=True)
        if index >= warmup:
            sample_times.append(duration)
    if hashlib.sha256(tensor.tobytes(order="C")).hexdigest() != original_input_hash:
        raise ReferenceError("INPUT_MUTATED", "Runtime modified the retained input tensor", completed_cpu_run=True)
    assert baseline is not None
    same_shape = baseline.shape == tensor.shape
    unchanged = same_shape and np.array_equal(baseline, tensor)
    if require_nonidentity and unchanged:
        raise ReferenceError("IDENTITY_OUTPUT_REJECTED", "Output equals input; this does not establish a non-identity reconstruction proof", completed_cpu_run=True)
    ordered = sorted(sample_times)
    quantiles = {label: ordered[max(1, math.ceil(quantile * len(ordered))) - 1]
                 for label, quantile in (("p50", .50), ("p95", .95), ("p99", .99))}
    report = {"schema_version": "1.0.0", "document_type": "docksr_cpu_onnx_reference", "status": "PASS", "evidence": "REAL_CPU",
              "model": inspection["model"], "graph_signature": {"input": inputs[0], "output": outputs[0]},
              "tool_versions": {"python": platform.python_version(), "numpy": np.__version__, "onnx": onnx.__version__, "onnxruntime": ort.__version__},
              "provider_assignment": {"configured": ["CPUExecutionProvider"], "active": session.get_providers(), "basis": "Only the CPU provider is enabled; no per-node profiler assignment was collected.", "npu_executed": False},
              "session": {"execution_mode": "sequential", "intra_op_threads": 1, "inter_op_threads": 1, "graph_optimization": "disabled", "deterministic_compute_option": deterministic_option},
              "preprocessing": {"input_source": source, "layout": layout, "layout_source": "caller declaration" if layout != "UNSPECIFIED" else "not inferred", "transforms": "No resize, normalization, transpose or dtype conversion for loaded NPY; contiguous storage only.", "input_dtype": str(input_dtype), "input_shape": list(input_shape)},
              "output": {"dtype": str(output_dtype), "shape": list(baseline.shape), "finite": True},
              "comparison": {"atol": atol, "rtol": rtol, "rule": "abs(candidate-reference) <= atol + rtol*abs(reference)", "repeated_cpu_runs_bitwise_equal": True, "cross_provider_determinism": "NOT_TESTED", "nonidentity_required": require_nonidentity, "input_output_same_shape": same_shape, "identity_output": bool(unchanged), "identity_scope": "Direct shape/value equality only; not an image-quality or SR proof."},
              "runs": {"warmup_count": warmup, "sample_count": samples, "successful_inferences": successful, "failed_inferences": 0},
              "timings_ms": {"session_initialization": initialization_ms, "inference_samples": sample_times, "inference_summary": quantiles, "quantile_method": "nearest-rank; measured runs only", "npu": None, "power": None, "game_fps": None},
              "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "limitations": ["CPU reference only; no AMD runtime, physical NPU, GPU/NPU sharing or gaming throughput was tested.", "Graph I/O metadata does not establish intended natural-image preprocessing, model licensing or NPU operator compatibility.", "Model execution is bounded by accepted tensor metadata, not a sandbox against hostile internal allocations or native runtime defects."]}
    output_dir.mkdir(mode=0o700)
    output_dir.chmod(0o700)
    try:
        _write(output_dir / "input.npy", lambda stream: np.save(stream, tensor, allow_pickle=False))
        _write(output_dir / "output.npy", lambda stream: np.save(stream, baseline, allow_pickle=False))
        report["artifacts"] = {name: {"path": name + ".npy", "sha256": sha256(output_dir / (name + ".npy")),
            "tensor_bytes_sha256": hashlib.sha256(array.tobytes(order="C")).hexdigest()}
            for name, array in (("input", tensor), ("output", baseline))}
        _write(output_dir / "report.json", lambda stream: stream.write((json.dumps(report, indent=2, allow_nan=False) + "\n").encode()))
    except BaseException:
        shutil.rmtree(output_dir)
        raise
    return report


def parse_shape(value):
    if not re.fullmatch(r"[0-9]+(?:,[0-9]+){0,7}", value):
        raise argparse.ArgumentTypeError("Use comma-separated positive integer dimensions")
    return tuple(map(int, value.split(",")))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, dest="input_path")
    parser.add_argument("--layout", choices=("NCHW", "NHWC", "UNSPECIFIED"), default="UNSPECIFIED")
    parser.add_argument("--shape", type=parse_shape)
    parser.add_argument("--output-shape", type=parse_shape)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--atol", type=float, default=1e-6)
    parser.add_argument("--rtol", type=float, default=1e-5)
    parser.add_argument("--allow-identity", action="store_true")
    args = vars(parser.parse_args(argv))
    args["require_nonidentity"] = not args.pop("allow_identity")
    try:
        report = run_reference(**args)
        print(json.dumps(report, allow_nan=False))
        return 0
    except (ReferenceError, OSError, ValueError) as error:
        known = isinstance(error, ReferenceError)
        report = {"schema_version": "1.0.0", "document_type": "docksr_cpu_onnx_reference", "status": "NOT_RUN" if known and error.not_run else "FAIL",
                  "evidence": "REAL_CPU" if known and error.completed_cpu_run else "NONE", "error": {"code": error.code if known else "REFERENCE_IO_OR_ARGUMENT_ERROR", "message": str(error)[:512]},
                  "npu_executed": False}
        print(json.dumps(report, allow_nan=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
