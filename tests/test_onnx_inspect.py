"""Graph inspection tests use locally generated models and never run inference.

The optional ONNX package is needed for graph fixtures. The genuine
missing-dependency CLI check still runs without it.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import onnx
    from onnx import TensorProto, helper
except ImportError:
    onnx = None
    TensorProto = None
    helper = None


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "onnx_inspect.py"
TIMESTAMP = "2026-10-20T00:00:00Z"


def load_inspector():
    name = "docksr_onnx_inspect_under_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load the ONNX inspection script")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def invoke_cli(model, output, *, without_site_packages=False):
    interpreter_flags = ["-I", "-S"] if without_site_packages else []
    return subprocess.run(
        [sys.executable, *interpreter_flags, "-B", str(SCRIPT), str(model),
         "--output", str(output)], capture_output=True, text=True,
        timeout=30, check=False,
    )


class InspectorWithoutOnnxTests(unittest.TestCase):
    def test_cli_reports_a_genuine_missing_optional_dependency(self):
        with tempfile.TemporaryDirectory(prefix="docksr-onnx-missing-") as temporary:
            directory = Path(temporary)
            model = directory / "fixture.onnx"
            # A small protobuf field; this test must stop before graph parsing.
            model.write_bytes(b"\x08\x0a")
            process = invoke_cli(model, directory / "report.json", without_site_packages=True)
        self.assertNotEqual(process.returncode, 0)
        report = json.loads(process.stdout)
        self.assertEqual(report["status"], "ERROR")
        self.assertEqual(report["error"]["code"], "MISSING_DEPENDENCY")
        self.assertIn("onnx", report["error"]["message"].lower())
        self.assertNotIn("Traceback", process.stderr)

    def test_oversized_sparse_model_is_rejected_before_reading(self):
        inspector = load_inspector()
        with tempfile.TemporaryDirectory(prefix="docksr-onnx-size-") as temporary:
            model = Path(temporary) / "oversized.onnx"
            with model.open("wb") as stream:
                stream.truncate(128 * 1024 * 1024 + 1)
            with self.assertRaises(inspector.InspectionError) as raised:
                inspector.read_model_bytes(model)
            self.assertEqual(raised.exception.code, "MODEL_TOO_LARGE")


@unittest.skipIf(onnx is None, "Optional ONNX package is needed for local graph fixtures")
class OnnxInspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inspector = load_inspector()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="docksr-onnx-inspect-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    @staticmethod
    def model(graph, *, custom_opsets=()):
        return helper.make_model(
            graph, producer_name="DockSR-owned-test-fixture", ir_version=10,
            opset_imports=[helper.make_opsetid("", 13), *custom_opsets],
        )

    @classmethod
    def resize_model(cls):
        inputs = [helper.make_tensor_value_info("x", TensorProto.FLOAT, ["N", 3, 2, 2])]
        outputs = [helper.make_tensor_value_info("y", TensorProto.FLOAT, [None, 3, 4, 4])]
        initializers = [
            helper.make_tensor("roi", TensorProto.FLOAT, [0], []),
            helper.make_tensor("scales", TensorProto.FLOAT, [4], [1, 1, 2, 2]),
            helper.make_tensor("bias", TensorProto.FLOAT, [], [0.25]),
            helper.make_tensor("divisor", TensorProto.FLOAT, [], [2.0]),
        ]
        nodes = [
            helper.make_node("Resize", ["x", "roi", "scales"], ["scaled"], mode="nearest"),
            helper.make_node("Add", ["scaled", "bias"], ["biased"]),
            helper.make_node("Div", ["biased", "divisor"], ["y"]),
        ]
        graph = helper.make_graph(nodes, "resize-and-arithmetic", inputs, outputs,
                                  initializer=initializers)
        return cls.model(graph)

    @classmethod
    def external_model(cls, location="weights.bin", duplicate_key=None):
        tensor = TensorProto(name="weights", data_type=TensorProto.FLOAT,
                             dims=[1], data_location=TensorProto.EXTERNAL)
        for key, value in (("location", location), ("offset", "0"), ("length", "4")):
            tensor.external_data.add(key=key, value=value)
        if duplicate_key is not None:
            tensor.external_data.add(key=duplicate_key,
                                     value=location if duplicate_key == "location" else "0")
        graph = helper.make_graph(
            [helper.make_node("Add", ["x", "weights"], ["y"])], "external-weight",
            [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])],
            [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])],
            initializer=[tensor],
        )
        return cls.model(graph)

    def inspect(self, model, filename="fixture.onnx"):
        return self.inspector.inspect_bytes(model.SerializeToString(), filename=filename,
                                            timestamp=TIMESTAMP)

    def assert_scope(self, report):
        self.assertEqual(report["schema_version"], "1.0.0")
        self.assertEqual(report["document_type"], "docksr_onnx_inspection")
        self.assertEqual(report["status"], "INSPECTED")
        self.assertEqual(report["evidence"], "GRAPH_INSPECTION")
        self.assertEqual(report["scope"]["npu_compatibility"], "NOT_EVALUATED")
        self.assertIs(report["scope"]["inference_executed"], False)
        self.assertIs(report["scope"]["external_data_loaded"], False)

    def test_resize_arithmetic_metadata_hash_shapes_and_repeatability(self):
        model = self.resize_model()
        onnx.checker.check_model(model)
        raw = model.SerializeToString()
        first = self.inspect(model)
        self.assertEqual(first, self.inspect(model))
        self.assert_scope(first)
        self.assertEqual(first["inspected_at"], TIMESTAMP)
        self.assertEqual(first["model"], {
            "filename": "fixture.onnx", "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        })
        self.assertEqual(first["ir_version"], 10)
        self.assertIn({"domain": "", "version": 13}, first["opset_imports"])
        graph = first["graph"]
        self.assertEqual(graph["node_count"], 3)
        self.assertEqual(graph["initializer_count"], 4)
        self.assertEqual(graph["subgraph_count"], 0)
        self.assertEqual(graph["function_count"], 0)
        self.assertEqual(graph["inputs"], [{
            "name": "x", "kind": "tensor", "dtype": "FLOAT", "dtype_code": 1,
            "dimensions": [{"kind": "symbolic", "value": "N"},
                           {"kind": "static", "value": 3},
                           {"kind": "static", "value": 2},
                           {"kind": "static", "value": 2}],
        }])
        self.assertEqual(graph["outputs"][0]["dimensions"], [
            {"kind": "unknown", "value": None}, {"kind": "static", "value": 3},
            {"kind": "static", "value": 4}, {"kind": "static", "value": 4},
        ])
        self.assertEqual({(item["domain"], item["op_type"]): item["count"]
                          for item in first["operators"]},
                         {("", "Resize"): 1, ("", "Add"): 1, ("", "Div"): 1})
        self.assertEqual(first["initializers"]["count"], 4)
        self.assertEqual(first["initializers"]["total_elements"], 6)
        self.assertEqual(first["initializers"]["total_logical_bytes"], 24)
        self.assertEqual(first["external_data"], [])
        self.assertEqual(first["custom_domains"], [])
        self.assertEqual(first["tool_versions"]["onnx"], onnx.__version__)
        source = self.directory / "fixture.onnx"
        source.write_bytes(raw)
        self.assertEqual(self.inspector.inspect_model(source, timestamp=TIMESTAMP), first)

    def test_malformed_and_empty_models_have_structured_failures(self):
        missing_graph = onnx.ModelProto(ir_version=10).SerializeToString()
        for raw in (b"", b"\x80", b"\x0a\xff", b"not an ONNX protobuf", missing_graph):
            with self.subTest(raw=raw):
                with self.assertRaises(self.inspector.InspectionError) as raised:
                    self.inspector.inspect_bytes(raw, timestamp=TIMESTAMP)
                self.assertEqual(raised.exception.code, "INVALID_MODEL")
                self.assertTrue(str(raised.exception))

    def test_safe_external_weight_is_reported_without_reading_it(self):
        model = self.external_model()
        source = self.directory / "external.onnx"
        source.write_bytes(model.SerializeToString())
        weight = self.directory / "weights.bin"
        weight.write_bytes(b"This fixture must not be interpreted as tensor bytes.")
        original_open = Path.open
        original_builtin_open = builtins.open

        def guarded_open(path, *args, **kwargs):
            if path == weight:
                raise AssertionError("Graph inspection opened an external weight")
            return original_open(path, *args, **kwargs)

        def guarded_builtin_open(path, *args, **kwargs):
            if path in (weight, str(weight), str(weight).encode()):
                raise AssertionError("Graph inspection opened an external weight")
            return original_builtin_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open), patch.object(
            builtins, "open", guarded_builtin_open,
        ):
            report = self.inspector.inspect_model(source, timestamp=TIMESTAMP)
        self.assert_scope(report)
        self.assertEqual(len(report["external_data"]), 1)
        entry = report["external_data"][0]
        self.assertEqual(entry["location"], "weights.bin")
        self.assertEqual(entry["read_status"], "NOT_READ")
        self.assertEqual(entry["offset"], 0)
        self.assertEqual(entry["length"], 4)
        self.assertIsNone(entry["checksum"])
        self.assertIsNone(entry["size_bytes"])
        self.assertIsNone(entry["sha256"])
        weight.write_bytes(b"Different external bytes must not change graph metadata.")
        self.assertEqual(self.inspector.inspect_model(source, timestamp=TIMESTAMP), report)

    def test_unsafe_external_locations_and_duplicate_keys_are_rejected(self):
        unsafe = ("/etc/passwd", "../weights.bin", "nested/../../weights.bin",
                  "https://example.invalid/weights.bin", "file:///tmp/weights.bin",
                  "C:\\weights.bin", "..\\weights.bin", "nested\\weights.bin", "")
        for location in unsafe:
            with self.subTest(location=location):
                with self.assertRaises(self.inspector.InspectionError) as raised:
                    self.inspect(self.external_model(location))
                self.assertEqual(raised.exception.code, "UNSAFE_EXTERNAL_DATA")
        for key in ("location", "offset"):
            with self.subTest(duplicate_key=key):
                with self.assertRaises(self.inspector.InspectionError) as raised:
                    self.inspect(self.external_model(duplicate_key=key))
                self.assertEqual(raised.exception.code, "UNSAFE_EXTERNAL_DATA")

    def test_invalid_external_offsets_and_lengths_are_rejected(self):
        for key in ("offset", "length"):
            for value in ("-1", "not-an-integer", "1.5"):
                with self.subTest(key=key, value=value):
                    model = self.external_model()
                    for field in model.graph.initializer[0].external_data:
                        if field.key == key:
                            field.value = value
                    with self.assertRaises(self.inspector.InspectionError) as raised:
                        self.inspect(model)
                    self.assertEqual(raised.exception.code, "UNSAFE_EXTERNAL_DATA")

    def test_distinct_tensors_can_reference_the_same_safe_external_file(self):
        model = self.external_model()
        second = TensorProto()
        second.CopyFrom(model.graph.initializer[0])
        second.name = "weights_other"
        model.graph.initializer.append(second)
        report = self.inspect(model)
        self.assert_scope(report)
        self.assertEqual(len(report["external_data"]), 2)
        self.assertEqual({entry["tensor_name"] for entry in report["external_data"]},
                         {"weights", "weights_other"})
        self.assertTrue(all(entry["location"] == "weights.bin" and
                            entry["read_status"] == "NOT_READ"
                            for entry in report["external_data"]))

    def test_quantization_markers_do_not_claim_compatibility(self):
        graph = helper.make_graph(
            [helper.make_node("QuantizeLinear", ["x", "scale", "zero"], ["q"]),
             helper.make_node("DequantizeLinear", ["q", "scale", "zero"], ["y"])],
            "quantization-markers",
            [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 1, 2, 2])],
            [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 1, 2, 2])],
            initializer=[helper.make_tensor("scale", TensorProto.FLOAT, [], [0.125]),
                         helper.make_tensor("zero", TensorProto.UINT8, [], [128])],
        )
        annotation = graph.quantization_annotation.add(tensor_name="q")
        annotation.quant_parameter_tensor_names.add(key="SCALE_TENSOR", value="scale")
        annotation.quant_parameter_tensor_names.add(key="ZERO_POINT_TENSOR", value="zero")
        report = self.inspect(self.model(graph))
        self.assert_scope(report)
        quantization = report["quantization"]
        self.assertEqual(quantization["interpretation"], "DISCOVERED_MARKERS_ONLY")
        self.assertEqual(quantization["integer_initializer_count"], 1)
        self.assertEqual({node["op_type"] for node in quantization["nodes"]},
                         {"QuantizeLinear", "DequantizeLinear"})
        self.assertTrue(quantization["annotated_tensors"])

    def test_custom_operator_is_unresolved_inventory_not_npu_support(self):
        domain = "com.docksr.fixture"
        graph = helper.make_graph(
            [helper.make_node("FixtureOp", ["x"], ["y"], domain=domain)], "custom-op",
            [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])],
            [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])],
        )
        report = self.inspect(self.model(graph, custom_opsets=[helper.make_opsetid(domain, 1)]))
        self.assert_scope(report)
        self.assertIn(domain, report["custom_domains"])
        self.assertEqual({(entry["domain"], entry["op_type"]): entry["count"]
                          for entry in report["operators"]}, {(domain, "FixtureOp"): 1})
        self.assertIn("CUSTOM_DOMAIN_OPERATOR", {item["code"] for item in report["conditions"]})

    def test_nested_if_subgraphs_are_counted_recursively(self):
        branches = []
        for name, op_type, value in (("then", "Add", 1.0), ("else", "Div", 2.0)):
            branches.append(helper.make_graph(
                [helper.make_node(op_type, ["x", name + "_constant"], [name + "_value"])],
                name, [], [helper.make_tensor_value_info(name + "_value", TensorProto.FLOAT, [1])],
                initializer=[helper.make_tensor(name + "_constant", TensorProto.FLOAT, [1], [value])],
            ))
        graph = helper.make_graph(
            [helper.make_node("If", ["condition"], ["y"],
                              then_branch=branches[0], else_branch=branches[1])], "nested-if",
            [helper.make_tensor_value_info("condition", TensorProto.BOOL, []),
             helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])],
            [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])],
        )
        report = self.inspect(self.model(graph))
        self.assert_scope(report)
        self.assertEqual(report["graph"]["node_count"], 1)
        self.assertEqual(report["graph"]["total_node_count"], 3)
        self.assertEqual(report["graph"]["subgraph_count"], 2)
        self.assertEqual(report["initializers"]["count"], 2)
        self.assertIn("SUBGRAPHS_PRESENT", {item["code"] for item in report["conditions"]})
        self.assertEqual({(entry["domain"], entry["op_type"]): entry["count"]
                          for entry in report["operators"]},
                         {("", "If"): 1, ("", "Add"): 1, ("", "Div"): 1})

    def test_cli_writes_private_json_and_preserves_existing_output(self):
        source, output = self.directory / "fixture.onnx", self.directory / "report.json"
        raw = self.resize_model().SerializeToString()
        source.write_bytes(raw)
        process = invoke_cli(source, output)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assert_scope(report)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(report["model"]["sha256"], hashlib.sha256(raw).hexdigest())
        sentinel = output.read_bytes()
        second = invoke_cli(source, output)
        self.assertNotEqual(second.returncode, 0)
        second_report = json.loads(second.stdout)
        self.assertEqual(second_report["status"], "ERROR")
        self.assertEqual(second_report["error"]["code"], "OUTPUT_EXISTS")
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertEqual(source.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
