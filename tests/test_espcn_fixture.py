"""Owned exact3x fixture tests: REAL_CPU contract, never quality or NPU."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import espcn_fixture as fixture
import onnx_reference as reference

SDK_AVAILABLE = all(importlib.util.find_spec(name) for name in ("numpy", "onnx", "onnxruntime"))


@unittest.skipUnless(SDK_AVAILABLE, "Optional Gate-0 SDK unavailable")
class Exact3FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        import onnx
        import onnx_inspect
        cls.np, cls.onnx, cls.inspector = np, onnx, onnx_inspect

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="docksr-exact3-")
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, *, mode="DCR", layout="NCHW", height=3, width=4, name="run"):
        directory = self.directory / name
        manifest = fixture.write_fixture(directory, mode=mode, layout=layout, height=height, width=width)
        source = fixture.sentinel_input(height, width, layout=layout)
        input_path = directory / "source.npy"
        reference._write(input_path, lambda output: self.np.save(output, source, allow_pickle=False))
        report = reference.run_reference(directory / "model.onnx", directory / "reference", input_path=input_path,
                                         layout=layout, warmup=1, samples=2)
        output = self.np.load(directory / "reference/output.npy", allow_pickle=False)
        return directory, manifest, report, source, output

    def test_generation_is_deterministic_owned_static_exact3(self):
        first = fixture.write_fixture(self.directory / "first")
        second = fixture.write_fixture(self.directory / "second")
        self.assertEqual(first["model_sha256"], second["model_sha256"])
        self.assertEqual((self.directory / "first/model.onnx").read_bytes(),
                         (self.directory / "second/model.onnx").read_bytes())
        self.assertEqual(first["classification"], "UNTRAINED_MODEL_FIXTURE")
        self.assertEqual(first["opset"], 17)
        self.assertEqual(first["operator_histogram"], {"Conv": 2, "Relu": 1, "DepthToSpace": 1})
        self.assertEqual(first["final_pre_shuffle_channels"], 27)
        self.assertFalse(first["npu_executed"])
        self.assertEqual(first["quantization"], "NOT_VALIDATED")
        observed = self.inspector.inspect_model(self.directory / "first/model.onnx")
        self.assertFalse(observed["custom_domains"])
        self.assertFalse(observed["external_data"])
        for key, shape in (("inputs", [1, 3, 256, 256]), ("outputs", [1, 3, 768, 768])):
            self.assertEqual([item["value"] for item in observed["graph"][key][0]["dimensions"]], shape)
        self.assertEqual(os.stat(self.directory / "first").st_mode & 0o777, 0o700)
        for file in (self.directory / "first").iterdir():
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_both_modes_match_independent_scalar_convolution_and_shuffle(self):
        values = []
        for mode in ("DCR", "CRD"):
            _, _, report, source, output = self.execute(mode=mode, name=mode)
            expected = fixture.scalar_fixture_oracle(source, mode=mode)
            self.np.testing.assert_array_equal(output, expected)
            self.assertEqual(output.shape, (1, 3, 9, 12))
            self.assertEqual(report["evidence"], "REAL_CPU")
            self.assertFalse(report["provider_assignment"]["npu_executed"])
            self.assertTrue(report["comparison"]["repeated_cpu_runs_bitwise_equal"])
            self.assertFalse(self.np.array_equal(output, fixture.scalar_fixture_oracle(source, mode="CRD" if mode == "DCR" else "DCR")))
            self.assertFalse(self.np.array_equal(output, output[:, [2, 1, 0], :, :]))
            self.assertFalse(self.np.array_equal(output, self.np.roll(output, 1, axis=3)))
            values.append(output)
        self.assertFalse(self.np.array_equal(values[0], values[1]))

    def test_hand_derived_shuffle_positions_are_not_a_second_runtime(self):
        pre = self.np.arange(27 * 2 * 3, dtype=self.np.float32).reshape(1, 27, 2, 3)
        dcr = fixture.scalar_pixel_shuffle(pre, mode="DCR")
        crd = fixture.scalar_pixel_shuffle(pre, mode="CRD")
        # output colour1/subpixel(dy=2,dx=1) at source(y=1,x=2).
        self.assertEqual(dcr[0, 1, 5, 7], pre[0, 22, 1, 2])
        self.assertEqual(crd[0, 1, 5, 7], pre[0, 16, 1, 2])
        for mode, output in (("DCR", dcr), ("CRD", crd)):
            self.assertEqual(output.size, pre.size)
            self.np.testing.assert_array_equal(self.np.sort(output.ravel()), self.np.sort(pre.ravel()))
            self.assertEqual(output[0, 2, 0, 0], pre[0, 2 if mode == "DCR" else 18, 0, 0])

    def test_nhwc_graph_boundaries_and_host_conversion_strides(self):
        for mode in ("DCR", "CRD"):
            _, manifest, _, nhwc, output = self.execute(mode=mode, layout="NHWC", height=2, width=5, name=mode)
            nchw, input_copy = fixture.convert_layout(nhwc, source="NHWC", target="NCHW")
            expected_nchw = fixture.scalar_fixture_oracle(nchw, mode=mode)
            expected_nhwc, output_copy = fixture.convert_layout(expected_nchw, source="NCHW", target="NHWC")
            self.np.testing.assert_array_equal(output, expected_nhwc)
            self.assertEqual(output.shape, (1, 6, 15, 3))
            self.assertEqual(manifest["operator_histogram"]["Transpose"], 2)
            self.assertTrue(nchw.flags.c_contiguous and expected_nhwc.flags.c_contiguous)
            self.assertFalse(self.np.shares_memory(nhwc, nchw))
            self.assertFalse(self.np.shares_memory(expected_nchw, expected_nhwc))
            self.assertEqual(tuple(nhwc.strides), (120, 60, 12, 4))
            self.assertEqual(tuple(nchw.strides), (120, 40, 20, 4))
            self.assertEqual(input_copy["host_copy_count"], 1)
            self.assertEqual(input_copy["host_copy_bytes"], nhwc.nbytes)
            self.assertEqual(output_copy["host_copy_bytes"], output.nbytes)
            self.assertIsNone(input_copy["physical_ddr_bytes"])

    def test_full256_contract_runs_both_modes_with_oracle(self):
        source = fixture.sentinel_input()
        for mode in ("DCR", "CRD"):
            _, _, _, actual_source, output = self.execute(mode=mode, height=256, width=256, name=mode)
            self.np.testing.assert_array_equal(actual_source, source)
            expected = fixture.scalar_fixture_oracle(source, mode=mode)
            self.np.testing.assert_array_equal(output, expected)
            self.assertEqual(output.nbytes, 7_077_888)
            self.assertEqual(tuple(output.strides), (7_077_888, 2_359_296, 3072, 4))

    def test_output_guard_and_invalid_arguments(self):
        directory = self.directory / "fixture"
        fixture.write_fixture(directory)
        original = (directory / "model.onnx").read_bytes()
        with self.assertRaises(ValueError):
            fixture.write_fixture(directory)
        self.assertEqual((directory / "model.onnx").read_bytes(), original)
        for parameters in ({"mode": "BAD"}, {"layout": "RGB"}, {"height": 0}, {"width": 257}, {"height": True}):
            with self.assertRaises(ValueError):
                fixture.make_model(**parameters)
        with self.assertRaises(ValueError):
            fixture.write_fixture(ROOT / "never_create_owned_model")
        bad = self.np.empty((1, 26, 2, 2), dtype=self.np.float32)
        with self.assertRaises(ValueError):
            fixture.scalar_pixel_shuffle(bad)
        with self.assertRaises(ValueError):
            fixture.scalar_pixel_shuffle(self.np.zeros((27, 2, 2)), mode="DCR")
        with self.assertRaises(ValueError):
            fixture.scalar_fixture_oracle(self.np.zeros((1, 2, 2, 2), dtype=self.np.float32))
        with self.assertRaises(ValueError):
            fixture.convert_layout(self.np.zeros((1, 3, 2, 2), dtype=self.np.uint8), source="NCHW", target="NHWC")


if __name__ == "__main__":
    unittest.main()
