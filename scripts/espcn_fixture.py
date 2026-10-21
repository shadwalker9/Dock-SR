#!/usr/bin/env python3
"""Owned UNTRAINED_MODEL_FIXTURE for the static exact-3x ONNX contract.

This is a deterministic format/layout experiment, not a quality model. Model
bytes stay outside Git; CPU execution uses the existing Gate-0 reference tool.
Optional ONNX/numpy dependencies are loaded only when this module is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import onnx_reference as reference
from import_sesr import _absolute, _check_parents

VERSION = "1.0.0"
CLASSIFICATION = "UNTRAINED_MODEL_FIXTURE"
SCALE = 3
OPSET = 17


def _arguments(mode, layout, height, width):
    if mode not in {"DCR", "CRD"} or layout not in {"NCHW", "NHWC"}:
        raise ValueError("Mode must be DCR/CRD and boundary layout NCHW/NHWC")
    if any(type(value) is not int or not 1 <= value <= 256 for value in (height, width)):
        raise ValueError("Fixture spatial dimensions are bounded to 1..256")


def make_model(*, mode="DCR", layout="NCHW", height=256, width=256):
    """Build from owned binary-exact fixture constants; no trained weights."""
    _arguments(mode, layout, height, width)
    np, _, onnx, _ = reference.dependencies()
    helper, tensor = onnx.helper, onnx.TensorProto
    first = np.zeros((6, 3, 1, 1), dtype=np.float32)
    for channel in range(6):
        first[channel, channel % 3, 0, 0] = 1 if channel < 3 else -1
    first_bias = np.arange(6, dtype=np.float32) / np.float32(16)
    final = np.zeros((27, 6, 1, 1), dtype=np.float32)
    for channel in range(27):
        final[channel, channel % 6, 0, 0] = np.float32((1 + channel % 3) / 8)
    final_bias = np.arange(27, dtype=np.float32) / np.float32(32)
    initializers = [onnx.numpy_helper.from_array(array, name=name) for name, array in
                    (("feature_weights", first), ("feature_bias", first_bias),
                     ("subpixel_weights", final), ("subpixel_bias", final_bias))]
    input_shape = [1, 3, height, width] if layout == "NCHW" else [1, height, width, 3]
    output_shape = [1, 3, height * SCALE, width * SCALE] if layout == "NCHW" else [1, height * SCALE, width * SCALE, 3]
    nodes = []
    if layout == "NHWC":
        nodes.append(helper.make_node("Transpose", ["input"], ["nchw_input"], perm=[0, 3, 1, 2]))
    nodes.extend([
        helper.make_node("Conv", ["input" if layout == "NCHW" else "nchw_input", "feature_weights", "feature_bias"], ["features"], kernel_shape=[1, 1]),
        helper.make_node("Relu", ["features"], ["activated"]),
        helper.make_node("Conv", ["activated", "subpixel_weights", "subpixel_bias"], ["subpixels"], kernel_shape=[1, 1]),
        helper.make_node("DepthToSpace", ["subpixels"], ["output" if layout == "NCHW" else "nchw_output"], blocksize=SCALE, mode=mode),
    ])
    if layout == "NHWC":
        nodes.append(helper.make_node("Transpose", ["nchw_output"], ["output"], perm=[0, 2, 3, 1]))
    graph = helper.make_graph(nodes, "docksr_owned_untrained_exact3_contract",
                              [helper.make_tensor_value_info("input", tensor.FLOAT, input_shape)],
                              [helper.make_tensor_value_info("output", tensor.FLOAT, output_shape)],
                              initializer=initializers)
    model = helper.make_model(graph, producer_name="DockSR owned fixture generator", producer_version=VERSION,
                              opset_imports=[helper.make_opsetid("", OPSET)], ir_version=8,
                              doc_string="UNTRAINED_MODEL_FIXTURE; deterministic format oracle, no quality or NPU claim")
    helper.set_model_props(model, {"classification": CLASSIFICATION, "trained": "false",
                                   "fixture_version": VERSION, "scale": "3", "layout": layout,
                                   "depth_to_space_mode": mode, "quantization": "NOT_VALIDATED"})
    onnx.checker.check_model(model, full_check=True)
    inferred = onnx.shape_inference.infer_shapes(model, strict_mode=True, data_prop=True)
    observed = [value.dim_value for value in inferred.graph.output[0].type.tensor_type.shape.dim]
    if observed != output_shape:
        raise ValueError("Inferred fixture output differs from exact-3x contract")
    return model


def write_fixture(destination, **kwargs):
    """Create a new private outside-Git model directory, never overwrite one."""
    destination = _absolute(destination)
    _check_parents(destination.parent, reject_git=True)
    info = destination.parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("Fixture parent must be user-owned and not group/world writable")
    if destination.name == ".git" or os.path.lexists(destination):
        raise ValueError("Fixture destination must be new and outside Git")
    model = make_model(**kwargs)
    data = model.SerializeToString(deterministic=True)
    _, _, _, inspector = reference.dependencies()
    inspection = inspector.inspect_bytes(data, filename="model.onnx")
    mode, layout = kwargs.get("mode", "DCR"), kwargs.get("layout", "NCHW")
    manifest = {
        "schema_version": "1.0.0", "document_type": "docksr_espcn_fixture",
        "classification": CLASSIFICATION, "generator_version": VERSION,
        "generator_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(data).hexdigest(), "model_size_bytes": len(data),
        "opset": OPSET, "ir_version": model.ir_version, "layout": layout,
        "depth_to_space_mode": mode, "scale": SCALE, "final_pre_shuffle_channels": 27,
        "operator_histogram": dict(Counter(node.op_type for node in model.graph.node)),
        "graph_signature": {"inputs": inspection["graph"]["inputs"], "outputs": inspection["graph"]["outputs"]},
        "shape_inference": "PASS", "ownership": "Original deterministic fixture constants; no third-party checkpoint or training data",
        "source_license": "Project formal license pending; this manifest does not select a license",
        "quality": "NOT_EVALUATED_UNTRAINED_FIXTURE", "quantization": "NOT_VALIDATED",
        "deployment_candidates": {"A8W8": "NOT_VALIDATED", "XINT8": "NOT_VALIDATED"},
        "physical_npu": "NOT_RUN", "npu_executed": False,
        "output_permissions": {"directory": "0700", "files": "0600"},
    }
    destination.mkdir(mode=0o700)
    destination.chmod(0o700)
    try:
        reference._write(destination / "model.onnx", lambda stream: stream.write(data))
        reference._write(destination / "manifest.json", lambda stream: stream.write((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()))
    except BaseException:
        shutil.rmtree(destination)
        raise
    return manifest


def sentinel_input(height=256, width=256, *, layout="NCHW"):
    """Owned signed dyadic RGB values make channel/subpixel mistakes visible."""
    _arguments("DCR", layout, height, width)
    np, _, _, _ = reference.dependencies()
    result = np.empty((1, 3, height, width), dtype=np.float32)
    for channel in range(3):
        for y in range(height):
            for x in range(width):
                result[0, channel, y, x] = ((x * 7 + y * 11 + channel * 37) % 31 - 15) / 8
    return result if layout == "NCHW" else convert_layout(result, source="NCHW", target="NHWC")[0]


def convert_layout(array, *, source, target):
    """Explicit owned host copy; count it rather than imply a free transpose."""
    np, _, _, _ = reference.dependencies()
    if source == target or {source, target} != {"NCHW", "NHWC"} or array.ndim != 4 or array.dtype != np.float32:
        raise ValueError("Use a rank-four FLOAT32 NHWC↔NCHW conversion")
    channel_axis = 1 if source == "NCHW" else 3
    if array.shape[channel_axis] != 3:
        raise ValueError("Fixture conversion requires three RGB channels")
    permutation = (0, 2, 3, 1) if source == "NCHW" else (0, 3, 1, 2)
    result = np.array(array.transpose(permutation), order="C", copy=True)
    return result, {"source_layout": source, "target_layout": target, "host_copy_count": 1,
                    "host_copy_bytes": array.nbytes, "read_logical_bytes": array.nbytes,
                    "write_logical_bytes": result.nbytes, "physical_ddr_bytes": None,
                    "input_strides_bytes": list(array.strides), "output_strides_bytes": list(result.strides)}


def scalar_pixel_shuffle(array, *, blocksize=3, mode="DCR"):
    """Independent indexed oracle: no reshape/transpose or ONNX execution."""
    np, _, _, _ = reference.dependencies()
    if mode not in {"DCR", "CRD"} or type(blocksize) is not int or not 1 <= blocksize <= 8 or array.ndim != 4:
        raise ValueError("Invalid scalar pixel-shuffle arguments")
    batches, channels, height, width = array.shape
    area = blocksize * blocksize
    if channels % area:
        raise ValueError("Pre-shuffle channels must be divisible by blocksize squared")
    colors = channels // area
    result = np.empty((batches, colors, height * blocksize, width * blocksize), dtype=array.dtype)
    for batch in range(batches):
        for color in range(colors):
            for y in range(height):
                for x in range(width):
                    for dy in range(blocksize):
                        for dx in range(blocksize):
                            offset = dy * blocksize + dx
                            channel = offset * colors + color if mode == "DCR" else color * area + offset
                            result[batch, color, y * blocksize + dy, x * blocksize + dx] = array[batch, channel, y, x]
    return result


def scalar_fixture_oracle(input_nchw, *, mode="DCR"):
    """Closed-form fixture convolutions then independently indexed shuffle.

    Deliberately does not read graph weights or call the model generator. A
    mistaken exported weight, RGB index or mode can therefore fail this oracle.
    """
    np, _, _, _ = reference.dependencies()
    if input_nchw.ndim != 4 or input_nchw.shape[0:2] != (1, 3) or input_nchw.dtype != np.float32:
        raise ValueError("Oracle expects FLOAT32 [1,3,H,W]")
    _, _, height, width = input_nchw.shape
    hidden = np.empty((6, height, width), dtype=np.float32)
    for feature in range(6):
        for y in range(height):
            for x in range(width):
                value = float(input_nchw[0, feature % 3, y, x])
                hidden[feature, y, x] = max((value if feature < 3 else -value) + feature / 16, 0)
    subpixels = np.empty((1, 27, height, width), dtype=np.float32)
    for channel in range(27):
        for y in range(height):
            for x in range(width):
                subpixels[0, channel, y, x] = float(hidden[channel % 6, y, x]) * ((1 + channel % 3) / 8) + channel / 32
    return scalar_pixel_shuffle(subpixels, blocksize=3, mode=mode)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("DCR", "CRD"), default="DCR")
    parser.add_argument("--layout", choices=("NCHW", "NHWC"), default="NCHW")
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--width", type=int, default=256)
    args = vars(parser.parse_args(argv))
    destination = args.pop("output_dir")
    try:
        print(json.dumps(write_fixture(destination, **args), allow_nan=False))
        return 0
    except (OSError, ValueError, reference.ReferenceError) as error:
        print(json.dumps({"status": "FAILED", "classification": CLASSIFICATION,
                          "error": str(error)[:512], "npu_executed": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
