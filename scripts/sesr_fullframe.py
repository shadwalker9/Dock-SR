#!/usr/bin/env python3
"""DSR011 complete-frame SESR CPU reference; unchanged model, no NPU/GPU.

Tiling/assembly extends the existing CpuReferenceSession. This is not another
model inspector or runtime. Outputs are private and must stay outside Git.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time

from import_sesr import PINNED_IDENTITY, _absolute, _check_parents, _read_verified
from onnx_reference import CpuReferenceSession, ReferenceError, _write


class TilingError(ValueError):
    pass


def array_hash(array):
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def receptive_field(proto, onnx):
    """Conservative structural bound for this graph's explicit spatial ops.

    Track activation dependencies, not node order or weight-quantizer paths.
    Unsupported spatial semantics fail rather than silently shrinking the halo.
    """
    initializers = {item.name for item in proto.graph.initializer}
    inputs = [item for item in proto.graph.input if item.name not in initializers]
    if len(inputs) != 1 or len(proto.graph.output) != 1:
        raise TilingError("Receptive-field proof requires single input/output")
    # (layout, LR radius, scale); constants have no image dependency.
    states = {inputs[0].name: ("NHWC", 0, 1)}
    constants = set(initializers)
    convolution_paths = []
    for node in proto.graph.node:
        if node.domain not in ("", "ai.onnx"):
            raise TilingError("Custom operator has unproved spatial dependency")
        attrs = {a.name: onnx.helper.get_attribute_value(a) for a in node.attribute}
        feature_inputs = [states[name] for name in node.input if name in states]
        if not feature_inputs:
            if node.op_type not in {"Constant", "QuantizeLinear", "DequantizeLinear", "Identity"}:
                raise TilingError("Unproved constant dependency: " + node.op_type)
            constants.update(node.output)
            continue
        op = node.op_type
        state = feature_inputs[0]
        if op == "Transpose":
            perm = list(attrs.get("perm", []))
            if state[0] == "NHWC" and perm == [0, 3, 1, 2]:
                state = ("NCHW", state[1], state[2])
            elif state[0] == "NCHW" and perm == [0, 2, 3, 1]:
                state = ("NHWC", state[1], state[2])
            else:
                raise TilingError("Unproved transpose/layout mapping")
        elif op == "Conv":
            kernel = list(attrs.get("kernel_shape", []))
            dilations = list(attrs.get("dilations", [1, 1]))
            pads = list(attrs.get("pads", [0, 0, 0, 0]))
            strides = list(attrs.get("strides", [1, 1]))
            if (state[0] != "NCHW" or state[2] != 1 or len(feature_inputs) != 1 or node.input[0] not in states or
                    len(kernel) != 2 or kernel[0] != kernel[1] or kernel[0] % 2 != 1 or
                    not 1 <= kernel[0] <= 31 or strides != [1, 1] or dilations != [1, 1] or
                    pads != [kernel[0] // 2] * 4 or attrs.get("auto_pad", b"NOTSET") not in (b"NOTSET", "NOTSET")):
                raise TilingError("Conv has unproved stride/dilation/padding/layout")
            state = ("NCHW", state[1] + kernel[0] // 2, 1)
            convolution_paths.append({"node": node.name, "kernel": kernel, "radius_after": state[1],
                                      "pads": pads, "strides": strides, "dilations": dilations})
        elif op == "Add":
            if any((x[0], x[2]) != (state[0], state[2]) for x in feature_inputs):
                raise TilingError("Residual branch layout/scale mismatch")
            state = (state[0], max(x[1] for x in feature_inputs), state[2])
        elif op == "DepthToSpace":
            block = attrs.get("blocksize")
            if state[0] != "NCHW" or state[2] != 1 or block != 2:
                raise TilingError("Only the proved final native2x pixel shuffle is supported")
            if attrs.get("mode", b"DCR") not in (b"CRD", b"DCR", "CRD", "DCR"):
                raise TilingError("Unproved pixel-shuffle channel order")
            state = ("NCHW", state[1], 2)
        elif op in {"QuantizeLinear", "DequantizeLinear", "Relu", "Identity"}:
            if len(feature_inputs) != 1 or node.input[0] not in states:
                raise TilingError("Pointwise dependency is not the data input")
            if any(name not in constants for name in node.input[1:] if name):
                raise TilingError("Dynamic quantization parameters are not spatially proved")
        else:
            raise TilingError("Unproved spatial operator: " + op)
        for name in node.output:
            states[name] = state
    output = states.get(proto.graph.output[0].name)
    if output is None or output[0] != "NHWC" or output[2] != 2:
        raise TilingError("Expected NHWC native2x graph output")
    halo = output[1]
    if not 0 <= halo < 128:
        raise TilingError("Unusable halo for fixed256 tile")
    return {"method": "conservative_structural_dependency_bound", "halo_input_pixels": halo,
            "receptive_field_input_pixels": 2 * halo + 1, "scale": 2,
            "tile_input_size": 256, "usable_core_input_size": 256 - 2 * halo,
            "convolution_paths": convolution_paths,
            "pointwise_ops_expand_neighborhood": False,
            "depth_to_space_mapping": "LR coordinate floor(HR coordinate / 2); no spatial expansion",
            "full_variable_size_model_equivalence": "NOT_TESTED"}


@dataclass(frozen=True)
class Tile:
    tile_id: int
    grid_x: int
    grid_y: int
    input_origin_x: int
    input_origin_y: int
    source_x: int
    source_y: int
    source_width: int
    source_height: int
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    output_x: int
    output_y: int
    output_width: int
    output_height: int


def tile_plan(width, height, halo, *, shift_x=0, shift_y=0):
    if any(type(v) is not int for v in (width, height, halo, shift_x, shift_y)):
        raise TilingError("Geometry must use exact integers")
    core = 256 - 2 * halo
    if not (1 <= width <= 1280 and 1 <= height <= 720 and 0 <= halo < 128 and
            0 <= shift_x < core and 0 <= shift_y < core):
        raise TilingError("Geometry/halo/shift exceeds bounded reference limits")
    result = []
    for gy in range(-shift_y, height, core):
        for gx in range(-shift_x, width, core):
            x, y = max(gx, 0), max(gy, 0)
            w, h = min(gx + core, width) - x, min(gy + core, height) - y
            result.append(Tile(len(result), gx, gy, gx - halo, gy - halo, x, y, w, h,
                               (halo + x - gx) * 2, (halo + y - gy) * 2, w * 2, h * 2,
                               x * 2, y * 2, w * 2, h * 2))
    return result


def reflected_indices(np, size, origin):
    """Reflect without duplicating the edge pixel, including negative indices."""
    if (type(size) is not int or not 1 <= size <= 1280 or type(origin) is not int or
            not -(1 << 62) <= origin <= (1 << 62)):
        raise TilingError("Reflection requires a bounded positive extent and integer origin")
    indices = np.arange(256, dtype=np.int64)
    if size == 1:
        indices.fill(0)
        return indices
    np.add(indices, origin, out=indices)
    period = 2 * (size - 1)
    np.remainder(indices, period, out=indices)
    for i in range(256):
        if indices[i] >= size:
            indices[i] = period - indices[i]
    return indices


def owned_pattern(np, width=1280, height=720):
    """Original arithmetic imagery only, never a game or quality dataset."""
    image = np.empty((height, width, 3), dtype=np.uint8)
    x = np.arange(width, dtype=np.int32)
    y = np.arange(height, dtype=np.int32)
    image[:, :, 0] = x[None, :] * 255 // max(1, width - 1)
    image[:, :, 1] = y[:, None] * 255 // max(1, height - 1)
    image[:, :, 2] = 20 + 200 * ((x[None, :] // 13 + y[:, None] // 11) % 2)
    image[height // 2:height // 2 + 1, :] = 255
    image[:, width // 2:width // 2 + 1] = 0
    for px in range(117, width, 234):
        image[:, px:px + 2] = (250, 80, 30)
    for py in range(117, height, 234):
        image[py:py + 2, :] = (40, 240, 100)
    # Original HUD-like bars/rectangular strokes span a tile boundary.
    if width > 270 and height > 80:
        image[30:34, 180:270] = 255
        image[30:70, 180:184] = 255
        image[66:70, 180:270] = 255
        image[44:56, 210:244] = (255, 200, 40)
    image[0, 0] = (255, 0, 0)
    image[0, -1] = (0, 255, 0)
    image[-1, 0] = (0, 0, 255)
    image[-1, -1] = 255
    return image


class FrameProcessor:
    """One reusable reference session and fixed caller-owned working buffers."""
    def __init__(self, reference, width, height, rf):
        self.reference, self.np = reference, reference.np
        self.width, self.height, self.rf = width, height, rf
        self.halo = rf["halo_input_pixels"]
        tile_plan(width, height, self.halo)  # Bounds before any frame allocation.
        np = self.np
        if (reference.input_shape != (1, 256, 256, 3) or reference.output_shape != (1, 512, 512, 3) or
                reference.input_dtype != np.dtype("int8") or reference.output_dtype != np.dtype("int8")):
            raise TilingError("Frame processor requires the established INT8 NHWC2x tile signature")
        self.encoded = np.empty((height, width, 3), dtype=np.int8)
        self.input_tile = np.empty(reference.input_shape, dtype=np.int8)
        self.output_tile = np.empty(reference.output_shape, dtype=np.int8)
        self.indices = np.empty((256, 256), dtype=np.int64)
        self.coverage = np.empty((height, width), dtype=np.uint8)
        self.output = np.empty((height * 2, width * 2, 3), dtype=np.uint8)

    def process(self, source, *, shift_x=0, shift_y=0):
        np, ref = self.np, self.reference
        if (not isinstance(source, np.ndarray) or source.dtype != np.uint8 or
                source.shape != (self.height, self.width, 3) or not source.flags.c_contiguous):
            raise TilingError("Input must be contiguous bounded RGB8 with the configured extent")
        if any(np.may_share_memory(source, array) for array in
               (self.encoded, self.input_tile, self.output_tile, self.output)):
            raise TilingError("Retained source must not alias reusable working buffers")
        started = time.perf_counter_ns()
        plan = tile_plan(self.width, self.height, self.halo, shift_x=shift_x, shift_y=shift_y)
        self.coverage.fill(0)
        encode_started = time.perf_counter_ns()
        np.subtract(source, 128, out=self.encoded, dtype=np.int16, casting="unsafe")
        encode_ms = (time.perf_counter_ns() - encode_started) / 1_000_000
        x_indices = {t.input_origin_x: reflected_indices(np, self.width, t.input_origin_x) for t in plan}
        y_indices = {t.input_origin_y: reflected_indices(np, self.height, t.input_origin_y) for t in plan}
        # Duplicate keys release the previous same-size vector immediately.
        input_flat = self.encoded.reshape((-1, 3))
        inference_ms, preparation_ms, stitch_ms = [], 0.0, 0.0
        physical_input_pixels = 0
        before_calls = ref.successful_runs
        for tile in plan:
            preparing = time.perf_counter_ns()
            xi, yi = x_indices[tile.input_origin_x], y_indices[tile.input_origin_y]
            for row in range(256):
                np.add(xi, int(yi[row]) * self.width, out=self.indices[row])
            # Validated reflected indices are inbounds. clip avoids take's
            # documented output buffering for mode='raise'; hidden internals
            # remain unmeasured, never a zero-copy claim.
            np.take(input_flat, self.indices, axis=0, out=self.input_tile[0], mode="clip")
            preparation_ms += (time.perf_counter_ns() - preparing) / 1_000_000
            ref.run(self.input_tile, output_buffer=self.output_tile)
            inference_ms.append(ref.last_inference_ms)
            stitching = time.perf_counter_ns()
            x, y, w, h = tile.source_x, tile.source_y, tile.source_width, tile.source_height
            if bool(np.any(self.coverage[y:y + h, x:x + w])):
                raise TilingError("Overlapping output core placement")
            cropped = self.output_tile[0, tile.crop_y:tile.crop_y + tile.crop_height,
                                       tile.crop_x:tile.crop_x + tile.crop_width]
            target = self.output[tile.output_y:tile.output_y + tile.output_height,
                                 tile.output_x:tile.output_x + tile.output_width]
            np.add(cropped, 128, out=target, dtype=np.int16, casting="unsafe")
            self.coverage[y:y + h, x:x + w] = 1
            stitch_ms += (time.perf_counter_ns() - stitching) / 1_000_000
            physical_input_pixels += (max(0, min(self.width, tile.input_origin_x + 256) - max(0, tile.input_origin_x)) *
                                      max(0, min(self.height, tile.input_origin_y + 256) - max(0, tile.input_origin_y)))
        if not bool(np.all(self.coverage)):
            raise TilingError("Source coverage has unwritten output cores")
        duration_ms = (time.perf_counter_ns() - started) / 1_000_000
        calls = ref.successful_runs - before_calls
        if calls != len(plan):
            raise TilingError("Inference call count differs from tile manifest")
        count = len(plan)
        input_bytes = count * self.input_tile.nbytes
        output_bytes = count * self.output_tile.nbytes
        arrays = {"source_rgb8": source.nbytes, "encoded_frame_int8": self.encoded.nbytes,
                  "input_tile_int8": self.input_tile.nbytes, "output_tile_int8": self.output_tile.nbytes,
                  "gather_index_grid_int64": self.indices.nbytes, "coverage_uint8": self.coverage.nbytes,
                  "stitched_rgb8": self.output.nbytes,
                  "reflected_index_vectors": sum(v.nbytes for v in x_indices.values()) + sum(v.nbytes for v in y_indices.values())}
        # Existing shared validation creates at most one finite-mask at a time.
        validation_mask_bytes = max(self.input_tile.size, self.output_tile.size)
        ledger = {"source_logical_bytes": source.nbytes,
                  "tensor_preparation_read_bytes": source.nbytes + input_bytes,
                  "tensor_preparation_write_bytes": self.encoded.nbytes + input_bytes,
                  "host_copy_bytes": input_bytes + self.output.nbytes,
                  "host_copy_direction": "HOST_TO_HOST",
                  "host_copy_count": count * 2,
                  "accounting_categories_are_additive": False,
                  "inference_input_logical_bytes": input_bytes,
                  "inference_output_logical_bytes": output_bytes,
                  "tile_count": count,
                  "tile_overlap_pixels": physical_input_pixels - self.width * self.height,
                  "padding_input_pixels": count * 256 * 256 - physical_input_pixels,
                  "redundant_input_pixels_vs_frame": count * 256 * 256 - self.width * self.height,
                  "stitched_output_bytes": self.output.nbytes,
                  "crop_bytes": output_bytes - self.output.nbytes,
                  "crop_bytes_scope": "Discarded model-output capacity; view cropping does not copy these bytes",
                  "gpu_upload_bytes": 0,
                  "gpu_upload_bytes_scope": "No GPU operation exists in this CPU reference; not a transfer measurement",
                  "allocation_high_water_bytes": sum(arrays.values()) + validation_mask_bytes,
                  "submit_to_complete_duration": {"value": duration_ms, "unit": "ms", "classification": "OBSERVED_HOST"},
                  "complete_to_consume_duration": None,
                  "deadline_missed": None,
                  "copy_observation_scope": "Counted caller-visible gather and decode/crop/stitch operations; transformed payload bytes per materialization, not read+write DDR traffic",
                  "copy_operations": [{"kind": "tile_input_gather", "count": count, "bytes": input_bytes},
                                      {"kind": "decode_crop_stitch", "count": count, "bytes": self.output.nbytes}],
                  "caller_visible_image_materialization_read_bytes": source.nbytes + input_bytes + self.output.nbytes,
                  "caller_visible_image_materialization_write_bytes": self.encoded.nbytes + input_bytes + self.output.nbytes,
                  "materialization_scope": "Deduplicated logical image operands for source encoding, tile gather and crop/decode/stitch; excludes inference internals, index/coverage arrays and physical traffic",
                  "allocation_scope": "Accounted simultaneously-live named NumPy arrays plus shared finite-validation mask; excludes model/session/runtime/native allocator internals, source generation, hashes, file serialization and Python metadata",
                  "named_array_allocations_bytes": arrays,
                  "shared_validation_mask_peak_bytes": validation_mask_bytes,
                  "runtime_internal_allocation_high_water_bytes": None,
                  "physical_ddr_traffic_bytes": None,
                  "hidden_numpy_ort_copies": "UNKNOWN",
                  "buffer_reuse": {"initialized_sessions": 1, "input_tile_buffers": 1, "output_tile_buffers": 1,
                                   "input_and_output_reused_for_every_tile": True},
                  "timings_ms": {"frame_wall": duration_ms, "source_encoding": encode_ms,
                                 "tile_preparation": preparation_ms, "inference_sum": sum(inference_ms),
                                 "inference_samples": inference_ms, "crop_decode_stitch": stitch_ms},
                  "inference_call_count": calls, "presentation": "NOT_RUN", "npu_executed": False}
        return self.output, ledger, plan


def shifted_patch_check(reference, halo):
    np = reference.np
    probe = np.random.default_rng(0).integers(-128, 128, (258, 258, 3), dtype=np.int16).astype(np.int8)
    a = np.ascontiguousarray(probe[:256, :256][None])
    b = np.ascontiguousarray(probe[1:257, 1:257][None])
    out_a = reference.run(a)
    out_b = reference.run(b)
    lo, hi = 2 * (halo + 1), 2 * (256 - halo)
    aa = out_a[0, lo:hi, lo:hi]
    bb = out_b[0, lo - 2:hi - 2, lo - 2:hi - 2]
    diff = np.abs(aa.astype(np.int16) - bb.astype(np.int16))
    # One-pixel-insufficient halo, first common top strip; demonstrates this
    # graph's boundary sensitivity, not a universal result for every model.
    strip_lo, strip_hi = 2 * halo, 2 * (257 - halo)
    strip_a = out_a[0, strip_lo:strip_lo + 2, strip_lo:strip_hi]
    strip_b = out_b[0, strip_lo - 2:strip_lo, strip_lo - 2:strip_hi - 2]
    short = np.abs(strip_a.astype(np.int16) - strip_b.astype(np.int16))
    return {"generator": "numpy.default_rng(0).integers(-128,128,(258,258,3),dtype=int16).astype(int8)",
            "input_sha256": array_hash(probe), "patch_origins_xy": [[0, 0], [1, 1]],
            "safe_halo": halo, "safe_compared_components": int(diff.size),
            "safe_differing_components": int(np.count_nonzero(diff)), "safe_max_abs_int8_difference": int(diff.max(initial=0)),
            "one_less_halo": halo - 1, "one_less_compared_components": int(short.size),
            "one_less_differing_components": int(np.count_nonzero(short)), "one_less_max_abs_int8_difference": int(short.max(initial=0)),
            "scope": "Actual fixed-shape shifted patches; not variable-size full-frame equivalence"}


def run_fullframe(model, output_dir, *, samples=2, seam_check=True):
    if type(samples) is not int or not 2 <= samples <= 10:
        raise TilingError("Use2..10 complete-frame repeats")
    model, output_dir = Path(model), _absolute(output_dir)
    _check_parents(output_dir.parent, reject_git=True)
    parent = output_dir.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o022 or output_dir.exists() or output_dir.is_symlink():
        raise TilingError("Output must be new under a controlled outside-Git parent")
    if type(seam_check) is not bool:
        raise TilingError("Seam-check selection must be boolean")
    # Establish exact identity before any native runtime session is created.
    # Check the independently inspected bytes again before initialization in
    # case the local file changed between the bounded read and inspection.
    _read_verified(_absolute(model), PINNED_IDENTITY)
    reference = CpuReferenceSession(model, layout="NHWC", initialize=False)
    if reference.inspection["model"]["sha256"] != PINNED_IDENTITY.sha256:
        raise TilingError("Actual SESR hash differs from the pinned artifact")
    rf = receptive_field(reference.proto, reference.onnx)
    reference.initialize()
    source = owned_pattern(reference.np)
    processor = FrameProcessor(reference, 1280, 720, rf)
    processor.input_tile.fill(0)
    reference.run(processor.input_tile, output_buffer=processor.output_tile)
    warmup_calls = 1
    hashes, ledgers = [], []
    plan = None
    for _ in range(samples):
        output, ledger, plan = processor.process(source)
        hashes.append(array_hash(output))
        ledgers.append(ledger)
    if len(set(hashes)) != 1:
        raise TilingError("Repeated full-frame outputs differ")
    seams = {"status": "NOT_RUN"}
    if seam_check:
        # Keep a diagnostic baseline copy only outside the transaction ledger.
        baseline = processor.output.copy()
        shifted, shifted_ledger, _ = processor.process(source, shift_x=13, shift_y=17)
        row_difference = reference.np.empty((2560, 3), dtype=reference.np.int16)
        differing, maximum = 0, 0
        for row in range(1440):
            reference.np.subtract(baseline[row], shifted[row], out=row_difference, dtype=reference.np.int16)
            reference.np.abs(row_difference, out=row_difference)
            differing += int(reference.np.count_nonzero(row_difference))
            maximum = max(maximum, int(row_difference.max(initial=0)))
        patch_check = shifted_patch_check(reference, processor.halo)
        seam_pass = differing == 0 and patch_check["safe_differing_components"] == 0
        seams = {"status": "PASS" if seam_pass else "OBSERVED_DIFFERENCE",
                 "default_vs_shifted_grid": {"shift_xy": [13, 17], "compared_components": int(baseline.size),
                     "differing_components": differing, "max_abs_rgb8_difference": maximum,
                     "default_sha256": hashes[-1], "shifted_sha256": array_hash(shifted),
                     "additional_inference_calls": shifted_ledger["inference_call_count"],
                     "diagnostic_baseline_copy_bytes": baseline.nbytes,
                     "diagnostic_row_difference_buffer_bytes": row_difference.nbytes},
                 "shifted_patch_halo_check": patch_check,
                 "global_boundary_policy": "Reflect source indices (without duplicate edge) before neural evaluation; deliberately not hypothetical per-layer zero padding at original full-frame edges",
                 "full_variable_size_model_equivalence": "NOT_TESTED"}
        # Restore exact accepted default-grid output without another inference.
        reference.np.copyto(processor.output, baseline)
    report = {"schema_version": "1.0.0", "document_type": "docksr_sesr_fullframe_reference",
              "status": "PASS", "evidence_class": "REAL_CPU", "model": reference.inspection["model"],
              "input_extent": {"width": 1280, "height": 720}, "input_format": "RGB8",
              "output_extent": {"width": 2560, "height": 1440}, "output_format": "RGB8",
              "scale": 2, "native3x": False, "source_ownership": "Original synthetic arithmetic fixture",
              "input_sha256": array_hash(source), "output_sha256": hashes[0],
              "repeated_output_sha256": hashes, "bitwise_repeatable": True,
              "preprocessing": "RGB8 minus128 exactly, no sharpening/normalization; INT8 NHWC",
              "padding": "Reflect without repeating edge pixel; single-pixel extent repeats the sole pixel",
              "receptive_field": rf, "tile_count": len(plan), "tile_order": "row-major core grid",
              "tile_placements": [asdict(t) for t in plan],
              "source_coverage_pixels": 1280 * 720, "output_coverage_pixels": 2560 * 1440,
              "coverage_checks": "Every source core assigned once; complete coverage checked before publishing; independent placement/crop tests cover subpixels",
              "initialized_cpu_sessions": 1, "warmup_inference_calls": warmup_calls,
              "complete_frame_samples": samples, "total_inference_calls": reference.successful_runs,
              "session_initialization_ms": reference.initialization_ms,
              "frame_timings_ms": [x["timings_ms"]["frame_wall"] for x in ledgers],
              "frame_latency_quantiles": None,
              "quantile_note": "Only2..10 frame repeats; raw observations retained, no tail-latency claim",
              "transactions": ledgers, "seam_tests": seams,
              "provider_assignment": {"active": reference.session.get_providers(), "npu_executed": False},
              "tool_versions": {"numpy": reference.np.__version__, "onnx": reference.onnx.__version__, "onnxruntime": reference.ort.__version__},
              "physical_ddr_traffic": "NOT_RUN", "physical_npu": "NOT_RUN", "game_frames": "NOT_RUN",
              "quality_advantage": "NOT_TESTED", "presentation": "NOT_RUN"}
    output_dir.mkdir(mode=0o700)
    output_dir.chmod(0o700)
    try:
        _write(output_dir / "source.npy", lambda stream: reference.np.save(stream, source, allow_pickle=False))
        _write(output_dir / "output.npy", lambda stream: reference.np.save(stream, processor.output, allow_pickle=False))
        _write(output_dir / "report.json", lambda stream: stream.write((json.dumps(report, indent=2, allow_nan=False) + "\n").encode()))
    except BaseException:
        shutil.rmtree(output_dir)
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--skip-seam-check", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_fullframe(args.model, args.output_dir, samples=args.samples, seam_check=not args.skip_seam_check)
        print(json.dumps({k: report[k] for k in ("status", "evidence_class", "tile_count", "input_sha256", "output_sha256", "frame_timings_ms", "total_inference_calls")}, allow_nan=False))
        return 0
    except (ReferenceError, TilingError, OSError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)[:512], "npu_executed": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
