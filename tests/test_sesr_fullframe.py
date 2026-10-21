"""Independent placement/dependency goldens; generated fixtures are not SESR."""
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np
import onnx
from onnx import TensorProto as T, helper as h, numpy_helper

from import_sesr import ImportFailure, PINNED_IDENTITY
from onnx_reference import CpuReferenceSession, ReferenceError
from sesr_fullframe import (FrameProcessor, TilingError, array_hash, owned_pattern,
                           receptive_field, reflected_indices, run_fullframe, tile_plan)


def dependency_fixture():
    """Original valid topology; zero weights test structural bounds only."""
    nodes = [h.make_node("Transpose", ["input"], ["nchw"], perm=[0, 3, 1, 2])]
    weights = []

    def conv(source, output, kernel, cin=12):
        name = output + "_weight"
        weights.append(numpy_helper.from_array(np.zeros((12, cin, kernel, kernel), np.float32), name))
        nodes.append(h.make_node("Conv", [source, name], [output], name=output,
                                 kernel_shape=[kernel, kernel], pads=[kernel // 2] * 4,
                                 strides=[1, 1], dilations=[1, 1]))

    conv("nchw", "head", 5, 3)
    source = "head"
    for index in range(7):
        output = "body" + str(index)
        conv(source, output, 3)
        source = output
    conv(source, "tail", 5)
    conv("head", "shortcut", 5)
    nodes += [h.make_node("Add", ["tail", "shortcut"], ["sum"]),
              h.make_node("Relu", ["sum"], ["relu"]),
              h.make_node("DepthToSpace", ["relu"], ["upscaled"], blocksize=2, mode="CRD"),
              h.make_node("Transpose", ["upscaled"], ["output"], perm=[0, 2, 3, 1])]
    graph = h.make_graph(nodes, "owned_structural_dependency_fixture",
        [h.make_tensor_value_info("input", T.FLOAT, [1, 256, 256, 3])],
        [h.make_tensor_value_info("output", T.FLOAT, [1, 512, 512, 3])], weights)
    model = h.make_model(graph, opset_imports=[h.make_opsetid("", 17)], ir_version=9)
    onnx.checker.check_model(model)
    return model


def small_runtime_fixture(path):
    scales = numpy_helper.from_array(np.array([1, 2, 2, 1], np.float32), "scales")
    bias = numpy_helper.from_array(np.array(0.125, np.float32), "bias")
    graph = h.make_graph([
        h.make_node("Resize", ["input", "", "scales"], ["enlarged"], mode="nearest",
                    coordinate_transformation_mode="asymmetric", nearest_mode="floor"),
        h.make_node("Add", ["enlarged", "bias"], ["output"])],
        "owned_reusable_session_fixture", [h.make_tensor_value_info("input", T.FLOAT, [1, 2, 2, 3])],
        [h.make_tensor_value_info("output", T.FLOAT, [1, 4, 4, 3])], [scales, bias])
    model = h.make_model(graph, opset_imports=[h.make_opsetid("", 17)], ir_version=9)
    onnx.save_model(model, path)


class SubpixelPlacementFixture:
    """Contract-only producer: independent of ONNX and the tiling algorithm."""
    np = np
    input_shape, output_shape = (1, 256, 256, 3), (1, 512, 512, 3)
    input_dtype, output_dtype = np.dtype("int8"), np.dtype("int8")

    def __init__(self):
        self.successful_runs = 0
        self.last_inference_ms = 0.0
        self.input_addresses, self.output_addresses = set(), set()

    def run(self, tensor, output_buffer=None):
        self.input_addresses.add(tensor.ctypes.data)
        self.output_addresses.add(output_buffer.ctypes.data)
        # Each 2x2 block has unique subpixels; incorrect halo or parity crops
        # cannot accidentally pass as they could with nearest-only output.
        base = tensor[0].astype(np.int16)
        for dy in range(2):
            for dx in range(2):
                output_buffer[0, dy::2, dx::2] = np.clip(base + dy * 2 + dx, -128, 127).astype(np.int8)
        self.successful_runs += 1
        return output_buffer


class FullFrameTests(unittest.TestCase):
    def test_structural_receptive_field_tracks_maximum_branch(self):
        result = receptive_field(dependency_fixture(), onnx)
        self.assertEqual(result["halo_input_pixels"], 11)
        self.assertEqual(result["receptive_field_input_pixels"], 23)
        self.assertEqual(result["usable_core_input_size"], 234)
        self.assertEqual(result["scale"], 2)
        self.assertEqual(result["full_variable_size_model_equivalence"], "NOT_TESTED")

    def test_unproved_spatial_semantics_reject(self):
        for attribute, value in (("strides", [2, 2]), ("dilations", [2, 2]), ("pads", [0, 0, 0, 0])):
            model = dependency_fixture()
            node = next(n for n in model.graph.node if n.op_type == "Conv")
            keep = [a for a in node.attribute if a.name != attribute]
            del node.attribute[:]
            node.attribute.extend(keep + [h.make_attribute(attribute, value)])
            with self.subTest(attribute=attribute), self.assertRaises(TilingError):
                receptive_field(model, onnx)
        for operation, attribute, value in (("Transpose", "perm", [0, 2, 1, 3]),
                                             ("DepthToSpace", "blocksize", 3)):
            model = dependency_fixture()
            node = next(n for n in model.graph.node if n.op_type == operation)
            keep = [a for a in node.attribute if a.name != attribute]
            del node.attribute[:]
            node.attribute.extend(keep + [h.make_attribute(attribute, value)])
            with self.subTest(operation=operation), self.assertRaises(TilingError):
                receptive_field(model, onnx)
        model = dependency_fixture()
        next(n for n in model.graph.node if n.op_type == "Conv").domain = "unreviewed.custom"
        with self.assertRaises(TilingError):
            receptive_field(model, onnx)

    def test_fixed720p_manifest_and_independent_coverage(self):
        plan = tile_plan(1280, 720, 11)
        self.assertEqual(len(plan), 24)
        first, last = plan[0], plan[-1]
        self.assertEqual((first.input_origin_x, first.input_origin_y, first.crop_x, first.crop_y), (-11, -11, 22, 22))
        self.assertEqual((last.source_x, last.source_y, last.source_width, last.source_height), (1170, 702, 110, 18))
        self.assertEqual((last.output_x, last.output_y, last.output_width, last.output_height), (2340, 1404, 220, 36))
        for width, height, sx, sy in ((1280, 720, 0, 0), (1280, 720, 13, 17),
                                      (1, 1, 233, 233), (235, 235, 0, 0)):
            coverage = np.zeros((height * 2, width * 2), np.uint8)
            for index, tile in enumerate(tile_plan(width, height, 11, shift_x=sx, shift_y=sy)):
                self.assertEqual(index, tile.tile_id)
                self.assertGreater(tile.crop_width, 0)
                self.assertGreater(tile.crop_height, 0)
                self.assertLessEqual(tile.crop_x + tile.crop_width, 512)
                self.assertLessEqual(tile.crop_y + tile.crop_height, 512)
                coverage[tile.output_y:tile.output_y + tile.output_height,
                         tile.output_x:tile.output_x + tile.output_width] += 1
            self.assertTrue(np.all(coverage == 1))

    def test_reflection_matches_independent_scalar_walk(self):
        for size in (1, 2, 7, 234, 720, 1280):
            for origin in (-244, -11, 0, 700, 1270):
                expected = []
                for index in range(origin, origin + 256):
                    if size == 1:
                        expected.append(0)
                        continue
                    while index < 0 or index >= size:
                        index = -index if index < 0 else 2 * size - 2 - index
                    expected.append(index)
                np.testing.assert_array_equal(reflected_indices(np, size, origin), expected)

    def test_crop_placement_subpixels_edges_and_buffer_reuse(self):
        for width, height, sx, sy in ((1, 1, 0, 0), (13, 7, 13, 17), (235, 235, 0, 0),
                                      (475, 257, 13, 17), (1280, 720, 0, 0)):
            with self.subTest(extent=(width, height), shift=(sx, sy)):
                source = owned_pattern(np, width, height)
                before = array_hash(source)
                reference = SubpixelPlacementFixture()
                processor = FrameProcessor(reference, width, height, {"halo_input_pixels": 11})
                output, ledger, plan = processor.process(source, shift_x=sx, shift_y=sy)
                # Direct coordinate oracle does not use tile locations/crops.
                for dy in range(2):
                    for dx in range(2):
                        expected = np.clip(source.astype(np.int16) + dy * 2 + dx, 0, 255).astype(np.uint8)
                        np.testing.assert_array_equal(output[dy::2, dx::2], expected)
                self.assertEqual(before, array_hash(source))
                self.assertEqual(reference.successful_runs, len(plan))
                self.assertEqual(len(reference.input_addresses), 1)
                self.assertEqual(len(reference.output_addresses), 1)
                self.assertEqual(ledger["inference_input_logical_bytes"], len(plan) * 196608)
                self.assertEqual(ledger["inference_output_logical_bytes"], len(plan) * 786432)
                self.assertEqual(ledger["host_copy_count"], len(plan) * 2)
                self.assertEqual(ledger["crop_bytes"] + ledger["stitched_output_bytes"], len(plan) * 786432)
                self.assertEqual(ledger["tile_overlap_pixels"] + ledger["padding_input_pixels"],
                                 ledger["redundant_input_pixels_vs_frame"])
                self.assertFalse(ledger["accounting_categories_are_additive"])
                if width == 1280 and height == 720:
                    self.assertEqual(ledger["caller_visible_image_materialization_read_bytes"], 18542592)
                    self.assertEqual(ledger["caller_visible_image_materialization_write_bytes"], 18542592)
                    self.assertEqual(ledger["tile_overlap_pixels"], 170940)
                    self.assertEqual(ledger["padding_input_pixels"], 480324)
                self.assertFalse(ledger["npu_executed"])
                self.assertIsNone(ledger["physical_ddr_traffic_bytes"])

    def test_geometry_and_retained_source_guards(self):
        for dimensions in ((0, 1, 11), (1281, 720, 11), (1, 721, 11), (10, 10, 128), (True, 2, 11)):
            with self.subTest(dimensions=dimensions), self.assertRaises(TilingError):
                tile_plan(*dimensions)
        with self.assertRaises(TilingError):
            reflected_indices(np, 0, 0)
        processor = FrameProcessor(SubpixelPlacementFixture(), 256, 256, {"halo_input_pixels": 11})
        with self.assertRaises(TilingError):
            processor.process(np.zeros((256, 256, 3), np.float32))
        with self.assertRaises(TilingError):
            processor.process(processor.input_tile[0].view(np.uint8))

    def test_reusable_actual_cpu_session_preallocated_output_and_oracle(self):
        with tempfile.TemporaryDirectory(prefix="docksr-owned-session-") as directory:
            model = Path(directory) / "owned.onnx"
            small_runtime_fixture(model)
            session = CpuReferenceSession(model, layout="NHWC", initialize=False)
            self.assertIsNone(session.session)
            source = np.arange(12, dtype=np.float32).reshape(1, 2, 2, 3) / 16
            expected = np.repeat(np.repeat(source, 2, axis=1), 2, axis=2) + np.float32(0.125)
            output = np.empty((1, 4, 4, 3), np.float32)
            self.assertIs(session.run(source, output_buffer=output), output)
            identity = session.session
            np.testing.assert_array_equal(output, expected)
            np.testing.assert_array_equal(session.run(source), expected)
            self.assertIs(session.session, identity)
            self.assertEqual(session.successful_runs, 2)
            self.assertEqual(session.session.get_providers(), ["CPUExecutionProvider"])
            with self.assertRaises(ReferenceError):
                session.run(source[:, :, ::-1], output_buffer=output)
            with self.assertRaises(ReferenceError):
                session.run(source, output_buffer=np.empty(output.shape, np.int8))
            readonly = np.empty(output.shape, np.float32)
            readonly.flags.writeable = False
            with self.assertRaises(ReferenceError):
                session.run(source, output_buffer=readonly)
            shared = np.empty(48, np.float32)
            with self.assertRaises(ReferenceError):
                session.run(shared[:12].reshape(source.shape), output_buffer=shared.reshape(output.shape))

    def test_wrong_model_identity_rejects_before_native_session(self):
        with tempfile.TemporaryDirectory(prefix="docksr-model-rejection-") as directory:
            root = Path(directory)
            model = root / "wrong.onnx"
            model.write_bytes(b"x" * PINNED_IDENTITY.size_bytes)
            with mock.patch("sesr_fullframe.CpuReferenceSession") as constructor:
                with self.assertRaises(ImportFailure):
                    run_fullframe(model, root / "new-output")
                constructor.assert_not_called()
            self.assertFalse((root / "new-output").exists())


if __name__ == "__main__":
    unittest.main()
