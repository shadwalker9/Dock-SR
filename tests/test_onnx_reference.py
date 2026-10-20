"""Owned local fixtures exercise real CPU ORT, not NPU/model-vendor behavior."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import onnx_reference as reference

SDK_AVAILABLE = all(importlib.util.find_spec(name) for name in ("numpy", "onnx", "onnxruntime"))


@unittest.skipUnless(SDK_AVAILABLE, "Optional Gate-0 SDK unavailable; install requirements-gate0.lock in a dedicated environment")
class CpuReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        import onnx
        import onnxruntime as ort
        cls.np, cls.onnx, cls.ort = np, onnx, ort

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="docksr-cpu-onnx-")
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def model(self, kind="resize", dimensions=None):
        np, onnx = self.np, self.onnx
        helper, TensorProto = onnx.helper, onnx.TensorProto
        dimensions = [1,3,2,3] if dimensions is None else dimensions
        output_dimensions = [1,3,4,6] if kind == "resize" else dimensions
        input_info = helper.make_tensor_value_info("raw", TensorProto.FLOAT, dimensions)
        output_info = helper.make_tensor_value_info("result", TensorProto.FLOAT, output_dimensions)
        initializers = []
        if kind == "resize":
            initializers = [onnx.numpy_helper.from_array(np.array([], dtype=np.float32), name="roi"),
                            onnx.numpy_helper.from_array(np.array([1,1,2,2], dtype=np.float32), name="scales"),
                            onnx.numpy_helper.from_array(np.array(.125, dtype=np.float32), name="correction")]
            nodes = [helper.make_node("Resize", ["raw","roi","scales"], ["resized"], mode="nearest", coordinate_transformation_mode="asymmetric", nearest_mode="floor"),
                     helper.make_node("Add", ["resized","correction"], ["result"])]
        elif kind == "nonfinite":
            initializers = [onnx.numpy_helper.from_array(np.array(0, dtype=np.float32), name="zero")]
            nodes = [helper.make_node("Div", ["raw","zero"], ["result"])]
        elif kind == "custom":
            nodes = [helper.make_node("NotARealOperator", ["raw"], ["result"], domain="docksr.untrusted")]
        elif kind == "external":
            initializer = onnx.TensorProto(name="outside", data_type=TensorProto.FLOAT, dims=[1])
            initializer.data_location = TensorProto.EXTERNAL
            initializer.external_data.add(key="location", value="../../never-load-this-data.bin")
            initializers = [initializer]
            nodes = [helper.make_node("Add", ["raw","outside"], ["result"])]
        else:
            nodes = [helper.make_node("Identity", ["raw"], ["result"])]
        graph = helper.make_graph(nodes, "owned_fixture_not_vendor_sr", [input_info], [output_info], initializer=initializers)
        imports = [helper.make_opsetid("", 13)]
        if kind == "custom": imports.append(helper.make_opsetid("docksr.untrusted", 1))
        model = helper.make_model(graph, opset_imports=imports, ir_version=8)
        path = self.directory / (kind + ".onnx")
        path.write_bytes(model.SerializeToString())
        return path

    def input_file(self, shape=(1,3,2,3), dtype="float32", nonfinite=False):
        value = self.np.arange(self.np.prod(shape), dtype=self.np.dtype(dtype)).reshape(shape)
        if nonfinite: value.flat[0] = self.np.nan
        path = self.directory / "raw.npy"
        self.np.save(path, value, allow_pickle=False)
        return path, value

    def run_fixture(self, model=None, name="output", **kwargs):
        return reference.run_reference(model or self.model(), self.directory / name,
                                       warmup=1, samples=3, **kwargs)

    def test_owned_resize_runs_on_cpu_with_independent_expected_pixels(self):
        model = self.model()
        input_path, raw = self.input_file()
        input_hash = reference.sha256(input_path)
        report = self.run_fixture(model, input_path=input_path, layout="NCHW")
        actual = self.np.load(self.directory / "output/output.npy", allow_pickle=False)
        expected = self.np.repeat(self.np.repeat(raw, 2, axis=2), 2, axis=3) + self.np.float32(.125)
        self.np.testing.assert_array_equal(actual, expected)
        self.assertEqual(report["evidence"], "REAL_CPU")
        self.assertEqual(report["provider_assignment"]["active"], ["CPUExecutionProvider"])
        self.assertFalse(report["provider_assignment"]["npu_executed"])
        self.assertIsNone(report["timings_ms"]["npu"])
        self.assertEqual(report["model"]["sha256"], reference.sha256(model))
        self.assertEqual(reference.sha256(input_path), input_hash, "Source input was modified")
        self.assertEqual(report["artifacts"]["output"]["sha256"], reference.sha256(self.directory / "output/output.npy"))
        self.assertEqual(report["runs"], {"warmup_count":1,"sample_count":3,"successful_inferences":4,"failed_inferences":0})
        self.assertGreaterEqual(report["timings_ms"]["session_initialization"], 0)
        self.assertEqual(len(report["timings_ms"]["inference_samples"]), 3)
        self.assertFalse(report["comparison"]["identity_output"])
        self.assertEqual(os.stat(self.directory / "output").st_mode & 0o777, 0o700)
        for artifact in (self.directory / "output").iterdir(): self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)

    def test_synthetic_runs_are_reproducible_in_separate_sessions(self):
        model = self.model()
        first = self.run_fixture(model, name="first")
        second = self.run_fixture(model, name="second")
        for artifact in ("input", "output"):
            self.assertEqual(first["artifacts"][artifact]["sha256"], second["artifacts"][artifact]["sha256"])
        self.assertTrue(first["comparison"]["repeated_cpu_runs_bitwise_equal"])
        self.assertEqual(first["comparison"]["cross_provider_determinism"], "NOT_TESTED")
        self.assertEqual(first["preprocessing"]["layout"], "UNSPECIFIED")

    def test_identity_rejected_unless_explicitly_allowed(self):
        model = self.model("identity")
        with self.assertRaisesRegex(reference.ReferenceError, "equals input") as raised:
            self.run_fixture(model)
        self.assertTrue(raised.exception.completed_cpu_run)
        self.assertFalse((self.directory / "output").exists())
        report = self.run_fixture(model, require_nonidentity=False)
        self.assertTrue(report["comparison"]["identity_output"])

    def test_nonfinite_input_and_output_are_rejected(self):
        path, _ = self.input_file(nonfinite=True)
        with self.assertRaisesRegex(reference.ReferenceError, "finite"):
            self.run_fixture(input_path=path)
        with self.assertRaisesRegex(reference.ReferenceError, "finite") as raised:
            self.run_fixture(self.model("nonfinite"))
        self.assertTrue(raised.exception.completed_cpu_run)
        self.assertFalse((self.directory / "output").exists())

    def test_loaded_shape_and_dtype_must_match_without_implicit_cast(self):
        for shape, dtype in (((1,3,2,2), "float32"), ((1,3,2,3), "uint8")):
            with self.subTest(shape=shape, dtype=dtype):
                path, _ = self.input_file(shape=shape, dtype=dtype)
                with self.assertRaisesRegex(reference.ReferenceError, "shape/dtype"):
                    self.run_fixture(input_path=path)

    def test_symbolic_dimensions_require_bounded_explicit_overrides(self):
        model = self.model("identity", ["batch",3,2,3])
        with self.assertRaisesRegex(reference.ReferenceError, "explicit bounded"):
            self.run_fixture(model)
        report = self.run_fixture(model, shape=(1,3,2,3), output_shape=(1,3,2,3), require_nonidentity=False)
        self.assertEqual(report["preprocessing"]["input_shape"], [1,3,2,3])

    def test_static_shape_override_and_allocation_bounds_are_enforced(self):
        with self.assertRaisesRegex(reference.ReferenceError, "static graph"):
            self.run_fixture(shape=(2,3,2,3))
        model = self.model("identity", ["n","c","h","w"])
        with self.assertRaisesRegex(reference.ReferenceError, "limit"):
            self.run_fixture(model, shape=(1,3,8192,8192), output_shape=(1,3,8192,8192))

    def test_external_data_and_custom_domains_rejected_before_runtime(self):
        for kind in ("external", "custom"):
            with self.subTest(kind=kind), patch.object(self.ort, "InferenceSession") as session:
                with self.assertRaises(reference.ReferenceError):
                    self.run_fixture(self.model(kind))
                session.assert_not_called()

    def test_object_npy_and_existing_output_are_not_loaded_or_overwritten(self):
        path = self.directory / "objects.npy"
        self.np.save(path, self.np.array([{"never":"unpickle"}], dtype=object))
        with self.assertRaisesRegex(reference.ReferenceError, "pickle"):
            self.run_fixture(input_path=path)
        output = self.directory / "output"
        output.mkdir(); (output / "owner").write_text("preserve")
        with patch.object(self.ort, "InferenceSession") as session:
            with self.assertRaisesRegex(reference.ReferenceError, "must be new"):
                self.run_fixture()
            session.assert_not_called()
        self.assertEqual((output / "owner").read_text(), "preserve")

    def test_malformed_model_missing_model_and_bad_run_arguments_fail(self):
        path = self.directory / "malformed.onnx"; path.write_bytes(b"not ONNX")
        with self.assertRaisesRegex(reference.ReferenceError, "safely inspected"):
            self.run_fixture(path)
        with self.assertRaises(reference.ReferenceError) as raised:
            self.run_fixture(self.directory / "missing.onnx")
        self.assertTrue(raised.exception.not_run)
        for arguments in ({"warmup":-1}, {"samples":1}, {"atol":float("nan")}, {"rtol":-1}):
            with self.subTest(arguments=arguments), self.assertRaises(reference.ReferenceError):
                reference.run_reference(self.model(), self.directory / "output", **arguments)

    def test_missing_sdk_reports_not_run_without_loading_model(self):
        model = self.model()
        result = subprocess.run([sys.executable,"-I","-S",str(ROOT / "scripts/onnx_reference.py"),str(model),
                                 "--output-dir",str(self.directory / "output")], capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "NOT_RUN")
        self.assertEqual(report["evidence"], "NONE")
        self.assertFalse(report["npu_executed"])
        self.assertFalse((self.directory / "output").exists())

    def test_npy_header_is_checked_before_allocation_or_runtime(self):
        path = self.directory / "oversized-header.npy"
        with path.open("wb") as stream:
            self.np.lib.format.write_array_header_1_0(stream, {
                "descr":"<f4", "fortran_order":False, "shape":(1_000_000_000,),
            })
        with patch.object(self.np, "load") as load, patch.object(self.ort, "InferenceSession") as session:
            with self.assertRaisesRegex(reference.ReferenceError, "shape/dtype"):
                self.run_fixture(input_path=path)
            load.assert_not_called()
            session.assert_not_called()


if __name__ == "__main__":
    if not SDK_AVAILABLE:
        print(json.dumps({"status":"NOT_RUN","reason":"Optional Gate-0 dependencies unavailable; install requirements-gate0.lock"}))
        raise SystemExit(77)
    unittest.main()
