#!/usr/bin/env python3
"""Bounded ONNX metadata inspection; never inference or NPU compatibility proof.

Usage: python scripts/onnx_inspect.py MODEL.onnx [--output NEW.json]
The optional ONNX package is imported only during inspection. The CLI parses in
an isolated, time/memory-bounded worker and never loads external tensor data.
Library callers can use read_model_bytes + inspect_bytes to inspect the same
bytes later passed to a runtime; run untrusted artifacts through the CLI worker.
No tensor values, model code, custom operators or shape inference are executed.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys

VERSION = "1.0.0"
MAX_MODEL_BYTES = 128 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_MESSAGES = 250_000
MAX_NODES = 100_000
MAX_DEPTH = 64
MAX_RANK = 64
MAX_TEXT = 1024
WORKER_TIMEOUT_SECONDS = 30
WORKER_MEMORY_BYTES = 1024 * 1024 * 1024
STANDARD_DOMAINS = {"", "ai.onnx", "ai.onnx.ml"}
QUANTIZATION_OPERATORS = {
    "QuantizeLinear", "DequantizeLinear", "DynamicQuantizeLinear", "QLinearConv",
    "QLinearMatMul", "ConvInteger", "MatMulInteger",
}
DTYPE_BITS = {
    "FLOAT": 32, "UINT8": 8, "INT8": 8, "UINT16": 16, "INT16": 16,
    "INT32": 32, "INT64": 64, "BOOL": 8, "FLOAT16": 16, "DOUBLE": 64,
    "UINT32": 32, "UINT64": 64, "COMPLEX64": 64, "COMPLEX128": 128,
    "BFLOAT16": 16, "FLOAT8E4M3FN": 8, "FLOAT8E4M3FNUZ": 8,
    "FLOAT8E5M2": 8, "FLOAT8E5M2FNUZ": 8, "UINT4": 4, "INT4": 4,
}
INTEGER_DTYPES = {"INT8", "UINT8", "INT16", "UINT16", "INT32", "UINT32", "INT64", "UINT64", "INT4", "UINT4"}


class InspectionError(Exception):
    def __init__(self, code, message, model=None):
        super().__init__(message)
        self.code = code
        self.model = model


def _text(value, path):
    if len(value) > MAX_TEXT:
        raise InspectionError("METADATA_LIMIT", f"Metadata text exceeds {MAX_TEXT} characters at {path}")
    return value


def _timestamp(value=None):
    return value if value is not None else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _tool_versions(onnx=None):
    return {"inspector": VERSION, "python": platform.python_version(),
            "onnx": getattr(onnx, "__version__", None), "protobuf": _package_version("protobuf")}


def _scope():
    return {"inference_executed": False, "npu_compatibility": "NOT_EVALUATED", "external_data_loaded": False}


def _error_report(error):
    return {"schema_version": VERSION, "document_type": "docksr_onnx_inspection",
            "status": "ERROR", "evidence": "GRAPH_INSPECTION", "model": error.model,
            "error": {"code": error.code, "message": str(error)[:MAX_TEXT]},
            "scope": _scope(), "tool_versions": _tool_versions(), "inspected_at": _timestamp()}


def read_model_bytes(path):
    """Read one explicitly supplied regular model file, with an enforced cap."""
    descriptor = None
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
        attributes = os.fstat(descriptor)
        if not stat.S_ISREG(attributes.st_mode):
            raise InspectionError("INVALID_MODEL", "Model input must be a regular file")
        if attributes.st_size > MAX_MODEL_BYTES:
            raise InspectionError("MODEL_TOO_LARGE", f"Model exceeds {MAX_MODEL_BYTES} bytes")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(MAX_MODEL_BYTES + 1)
        if len(data) > MAX_MODEL_BYTES:
            raise InspectionError("MODEL_TOO_LARGE", f"Model exceeds {MAX_MODEL_BYTES} bytes")
        if not data:
            raise InspectionError("INVALID_MODEL", "Model file is empty")
        return data
    except (OSError, ValueError) as error:
        raise InspectionError("MODEL_READ_ERROR", f"Cannot read model: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_onnx():
    try:
        return importlib.import_module("onnx")
    except ImportError as error:
        raise InspectionError("MISSING_DEPENDENCY", "Optional ONNX inspection dependency is unavailable; use the pinned Gate-0 environment") from error


def _walk_messages(root):
    stack = [("model", root, 0)]
    visited = 0
    while stack:
        path, message, depth = stack.pop()
        visited += 1
        if visited > MAX_MESSAGES or depth > MAX_DEPTH:
            raise InspectionError("GRAPH_LIMIT", "Protobuf message count or nesting limit exceeded")
        yield path, message
        children = []
        for field, value in message.ListFields():
            if field.type != field.TYPE_MESSAGE:
                continue
            if field.label == field.LABEL_REPEATED:
                children.extend((f"{path}.{field.name}[{index}]", child, depth + 1)
                                for index, child in enumerate(value))
            else:
                children.append((f"{path}.{field.name}", value, depth + 1))
        stack.extend(reversed(children))


def _dtype(onnx, code):
    try:
        return onnx.TensorProto.DataType.Name(code)
    except ValueError:
        return f"UNKNOWN_{code}"


def _value_info(onnx, value, path):
    name = _text(value.name, path + ".name")
    if not name or not value.HasField("type"):
        raise InspectionError("INVALID_MODEL", f"Value has no name or declared type at {path}")
    kind = value.type.WhichOneof("value")
    result = {"name": name, "kind": kind or "unknown", "dtype": None, "dtype_code": None, "dimensions": None}
    if kind == "tensor_type":
        tensor = value.type.tensor_type
        result.update(kind="tensor", dtype=_dtype(onnx, tensor.elem_type), dtype_code=tensor.elem_type)
        if tensor.HasField("shape"):
            if len(tensor.shape.dim) > MAX_RANK:
                raise InspectionError("GRAPH_LIMIT", f"Tensor rank exceeds {MAX_RANK} at {path}")
            dimensions = []
            for index, dimension in enumerate(tensor.shape.dim):
                representation = dimension.WhichOneof("value")
                if representation == "dim_value":
                    if dimension.dim_value < 0:
                        raise InspectionError("INVALID_MODEL", f"Negative static dimension at {path}")
                    dimensions.append({"kind": "static", "value": dimension.dim_value})
                elif representation == "dim_param":
                    dimensions.append({"kind": "symbolic", "value": _text(dimension.dim_param, f"{path}.dimension[{index}]")})
                else:
                    dimensions.append({"kind": "unknown", "value": None})
            result["dimensions"] = dimensions
    return result


def _external_reference(tensor, path):
    entries = {}
    for entry in tensor.external_data:
        key = _text(entry.key, path + ".external_data.key")
        if key in entries:
            raise InspectionError("UNSAFE_EXTERNAL_DATA", f"Duplicate external-data key at {path}")
        if key not in {"location", "offset", "length", "checksum"}:
            raise InspectionError("UNSAFE_EXTERNAL_DATA", f"Unsupported external-data key at {path}")
        entries[key] = _text(entry.value, path + ".external_data.value")
    location = entries.get("location", "")
    pieces = location.split("/")
    if (not location or location.startswith("/") or "\\" in location or ":" in location or
            any(piece in {"", ".", ".."} for piece in pieces) or
            any(ord(character) < 32 or ord(character) == 127 for character in location)):
        raise InspectionError("UNSAFE_EXTERNAL_DATA", f"Unsafe external-data location at {path}")
    numeric = {}
    for key in ("offset", "length"):
        value = entries.get(key)
        if value is None:
            numeric[key] = None
        elif not value.isascii() or not value.isdigit() or len(value) > 19 or int(value) > (1 << 63) - 1:
            raise InspectionError("UNSAFE_EXTERNAL_DATA", f"Invalid external-data {key} at {path}")
        else:
            numeric[key] = int(value)
    return {"tensor_path": path, "tensor_name": _text(tensor.name, path + ".name"),
            "location": location, **numeric, "checksum": entries.get("checksum"),
            "read_status": "NOT_READ", "size_bytes": None, "sha256": None}


def _tensor_statistics(onnx, tensor, path):
    if len(tensor.dims) > MAX_RANK:
        raise InspectionError("GRAPH_LIMIT", f"Initializer rank exceeds {MAX_RANK} at {path}")
    elements = 1
    for dimension in tensor.dims:
        if dimension < 0:
            raise InspectionError("INVALID_MODEL", f"Negative initializer dimension at {path}")
        elements *= dimension
    if elements > (1 << 63) - 1:
        elements = None
    dtype = _dtype(onnx, tensor.data_type)
    bits = DTYPE_BITS.get(dtype)
    logical = (elements * bits + 7) // 8 if elements is not None and bits else None
    if logical is not None and logical > (1 << 63) - 1:
        logical = None
    return {"path": path, "name": _text(tensor.name, path + ".name"), "dtype": dtype,
            "dtype_code": tensor.data_type, "dimensions": list(tensor.dims),
            "elements": elements, "logical_bytes": logical, "raw_data_bytes": len(tensor.raw_data),
            "serialized_proto_bytes": tensor.ByteSize(),
            "external": bool(tensor.external_data) or tensor.data_location == onnx.TensorProto.EXTERNAL}


def inspect_bytes(data, filename="model.onnx", *, timestamp=None):
    """Inspect supplied bytes; no external-data reads or inference are performed.

    The CLI additionally isolates this parser under OS memory/CPU/time limits.
    Direct API callers should use only trusted inputs or their own worker limits.
    """
    if not isinstance(data, bytes):
        raise InspectionError("INVALID_MODEL", "Model data must be bytes")
    if not data:
        raise InspectionError("INVALID_MODEL", "Model data is empty")
    if len(data) > MAX_MODEL_BYTES:
        raise InspectionError("MODEL_TOO_LARGE", f"Model exceeds {MAX_MODEL_BYTES} bytes")
    identity = {"filename": _text(str(filename), "model.filename"),
                "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    try:
        onnx = _load_onnx()
        try:
            model = onnx.load(io.BytesIO(data), format="protobuf", load_external_data=False)
        except Exception as error:
            raise InspectionError("INVALID_MODEL", "ONNX protobuf could not be parsed") from error
        if not model.HasField("graph") or model.ir_version <= 0 or not model.graph.output:
            raise InspectionError("INVALID_MODEL", "Model requires a graph, positive IR version and declared output")
        imports = []
        seen_domains = set()
        for item in model.opset_import:
            domain = _text(item.domain, "model.opset_import.domain")
            if domain in seen_domains or item.version <= 0:
                raise InspectionError("INVALID_MODEL", "Duplicate opset domain or nonpositive opset version")
            seen_domains.add(domain)
            imports.append({"domain": domain, "version": item.version})
        if not imports:
            raise InspectionError("INVALID_MODEL", "Model has no opset imports")
        imports.sort(key=lambda item: item["domain"])
        graphs, functions, nodes, tensors, annotations = [], [], [], [], []
        for path, message in _walk_messages(model):
            name = message.DESCRIPTOR.full_name.rsplit(".", 1)[-1]
            if name == "GraphProto":
                graphs.append((path, message))
            elif name == "FunctionProto":
                functions.append((path, message))
            elif name == "NodeProto":
                nodes.append((path, message))
                if len(nodes) > MAX_NODES:
                    raise InspectionError("GRAPH_LIMIT", f"Model exceeds {MAX_NODES} nodes")
            elif name == "TensorProto":
                tensors.append((path, message))
            elif name == "TensorAnnotation":
                annotations.append((path, message))
        conditions = []
        def note(code, message, path="model"):
            conditions.append({"code": code, "message": message, "path": path})
        operators = Counter()
        custom_domains = set()
        quantization_nodes = []
        for path, node in nodes:
            domain = _text(node.domain, path + ".domain")
            operation = _text(node.op_type, path + ".op_type")
            if not operation:
                raise InspectionError("INVALID_MODEL", f"Node has no operator type at {path}")
            operators[domain, operation] += 1
            if domain not in STANDARD_DOMAINS:
                custom_domains.add(domain)
                note("CUSTOM_DOMAIN_OPERATOR", "Custom-domain operator schema/execution is unresolved", path)
            elif not onnx.defs.has(operation, domain="" if domain == "ai.onnx" else domain):
                note("UNRESOLVED_OPERATOR_SCHEMA", "Operator is unknown to this inspector's ONNX schema registry", path)
            if operation in QUANTIZATION_OPERATORS or "quantiz" in operation.lower() or operation.startswith("QLinear"):
                quantization_nodes.append({"path": path, "name": _text(node.name, path + ".name"),
                                           "domain": domain, "op_type": operation})
        for path, function in functions:
            domain = _text(function.domain, path + ".domain")
            if domain not in STANDARD_DOMAINS:
                custom_domains.add(domain)
        external, initializer_tensors = [], []
        all_tensor_count = len(tensors)
        for path, tensor in tensors:
            if tensor.external_data or tensor.data_location == onnx.TensorProto.EXTERNAL:
                external.append(_external_reference(tensor, path))
            if ".initializer[" in path or ".sparse_initializer[" in path:
                initializer_tensors.append(_tensor_statistics(onnx, tensor, path))
        if external:
            note("EXTERNAL_DATA_NOT_READ", "External tensor dependencies were not opened, hashed or verified")
        if len(graphs) > 1:
            note("SUBGRAPHS_PRESENT", "Nested/training graphs are inventoried but their execution semantics are not validated")
        if functions:
            note("LOCAL_FUNCTIONS_PRESENT", "Local function bodies are inventoried but execution resolution is not validated")
        by_dtype = defaultdict(list)
        for tensor in initializer_tensors:
            by_dtype[tensor["dtype"]].append(tensor)
        def total(items, field):
            values = [item[field] for item in items]
            return sum(values) if all(value is not None for value in values) else None
        annotated = []
        for path, annotation in annotations:
            annotated.append({"path": path, "tensor_name": _text(annotation.tensor_name, path + ".tensor_name"),
                              "parameters": [{"key": _text(entry.key, path + ".key"),
                                              "value": _text(entry.value, path + ".value")}
                                             for entry in annotation.quant_parameter_tensor_names]})
        graph = model.graph
        report = {
            "schema_version": VERSION, "document_type": "docksr_onnx_inspection", "status": "INSPECTED",
            "evidence": "GRAPH_INSPECTION", "model": identity, "ir_version": model.ir_version,
            "opset_imports": imports,
            "graph": {"name": _text(graph.name, "model.graph.name"),
                      "inputs": [_value_info(onnx, value, f"model.graph.input[{index}]") for index, value in enumerate(graph.input)],
                      "outputs": [_value_info(onnx, value, f"model.graph.output[{index}]") for index, value in enumerate(graph.output)],
                      "node_count": len(graph.node), "total_node_count": len(nodes),
                      "initializer_count": len(graph.initializer), "sparse_initializer_count": len(graph.sparse_initializer),
                      "subgraph_count": max(0, len(graphs) - 1), "function_count": len(functions),
                      "subgraphs": [{"path": path, "name": _text(item.name, path + ".name"), "node_count": len(item.node)}
                                    for path, item in graphs if path != "model.graph"],
                      "functions": [{"path": path, "domain": _text(item.domain, path + ".domain"),
                                     "name": _text(item.name, path + ".name"), "node_count": len(item.node)}
                                    for path, item in functions]},
            "operators": [{"domain": domain, "op_type": operation, "count": count}
                          for (domain, operation), count in sorted(operators.items())],
            "operator_histogram_scope": "all_graphs_and_local_functions",
            "initializers": {"count": len(initializer_tensors), "total_elements": total(initializer_tensors, "elements"),
                             "total_logical_bytes": total(initializer_tensors, "logical_bytes"),
                             "by_dtype": [{"dtype": dtype, "count": len(items), "elements": total(items, "elements"),
                                           "logical_bytes": total(items, "logical_bytes")} for dtype, items in sorted(by_dtype.items())],
                             "tensors": initializer_tensors},
            "quantization": {"nodes": quantization_nodes,
                             "integer_initializer_count": sum(item["dtype"] in INTEGER_DTYPES for item in initializer_tensors),
                             "annotated_tensors": annotated, "interpretation": "DISCOVERED_MARKERS_ONLY"},
            "external_data": external, "custom_domains": sorted(custom_domains),
            "tensor_proto_count": all_tensor_count, "conditions": conditions,
            "scope": _scope(), "tool_versions": _tool_versions(onnx), "inspected_at": _timestamp(timestamp),
            "limitations": ["Metadata inspection does not perform inference, full ONNX semantic validation or NPU compatibility testing.",
                            "Logical tensor sizes and quantization markers do not establish runtime allocations or numerical behavior.",
                            "External tensor locations are syntax-checked only; their contents and filesystem resolution remain unverified."]}
        return report
    except InspectionError as error:
        error.model = identity
        raise
    except MemoryError as error:
        raise InspectionError("RESOURCE_LIMIT", "Inspection memory limit exceeded", identity) from error
    except Exception as error:
        raise InspectionError("INVALID_MODEL", f"Model metadata could not be inspected: {str(error)[:512]}", identity) from error


def inspect_model(path, *, timestamp=None):
    path = Path(path)
    return inspect_bytes(read_model_bytes(path), path.name, timestamp=timestamp)


def _encoded(report):
    data = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_REPORT_BYTES:
        raise InspectionError("REPORT_LIMIT", f"Inspection report exceeds {MAX_REPORT_BYTES} bytes")
    return data


def _worker(path):
    try:
        # Limits apply only to this isolated CLI worker, never to importing apps.
        import resource
        for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ[key] = "1"
        for kind, maximum in ((resource.RLIMIT_AS, WORKER_MEMORY_BYTES), (resource.RLIMIT_CPU, 25)):
            _, hard = resource.getrlimit(kind)
            value = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
            resource.setrlimit(kind, (value, value))
        report = inspect_model(path)
        sys.stdout.buffer.write(_encoded(report))
        return 0
    except InspectionError as error:
        sys.stdout.buffer.write(_encoded(_error_report(error)))
        return 1
    except Exception as error:
        sys.stdout.buffer.write(_encoded(_error_report(InspectionError("RESOURCE_LIMIT", str(error)[:MAX_TEXT]))))
        return 1


def _run_worker(path):
    command = [sys.executable, "-I"]
    if sys.flags.no_site:
        command.append("-S")
    command += [str(Path(__file__).resolve()), "--_worker", os.fspath(path)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=WORKER_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as error:
        raise InspectionError("RESOURCE_LIMIT", "Inspection worker exceeded its time limit") from error
    if len(result.stdout) > MAX_REPORT_BYTES:
        raise InspectionError("REPORT_LIMIT", "Inspection worker output exceeded its report limit")
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError) as error:
        raise InspectionError("RESOURCE_LIMIT" if result.returncode < 0 else "INSPECTION_WORKER_FAILED",
                              "Inspection worker did not return a complete report") from error
    if result.returncode != 0:
        issue = report.get("error", {})
        raise InspectionError(issue.get("code", "INSPECTION_WORKER_FAILED"),
                              issue.get("message", "Inspection worker failed"), report.get("model"))
    return report


def _write_new(path, data):
    descriptor = None
    created = False
    try:
        descriptor = os.open(os.fspath(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise InspectionError("OUTPUT_EXISTS", "Refusing to replace an existing inspection output") from error
    except OSError as error:
        if created:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise InspectionError("OUTPUT_WRITE_ERROR", f"Cannot write inspection output: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InspectionError("INVALID_ARGUMENT", message)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "--_worker":
        return _worker(argv[1])
    parser = _Parser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--output", type=Path, help="Write a new private JSON file; existing files are never replaced")
    try:
        arguments = parser.parse_args(argv)
        report = _run_worker(arguments.model)
        data = _encoded(report)
        if arguments.output:
            _write_new(arguments.output, data)
        sys.stdout.buffer.write(data)
        return 0
    except InspectionError as error:
        sys.stdout.buffer.write(_encoded(_error_report(error)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
