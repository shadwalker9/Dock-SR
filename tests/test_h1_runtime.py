"""Actual CPU execution of an OWNED resize fixture; not AMD model/NPU evidence."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import onnx
from onnx import helper as H, numpy_helper as N, TensorProto as T

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import h1_probe as h


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.model = self.directory/'OWNED_NOT_SESR.onnx'
        nodes = [H.make_node('Cast',['input'],['float'],to=T.FLOAT),
                 H.make_node('Resize',['float','','scales'],['enlarged'],mode='nearest',coordinate_transformation_mode='asymmetric',nearest_mode='floor'),
                 H.make_node('Cast',['enlarged'],['output'],to=T.INT8)]
        graph = H.make_graph(nodes, 'OWNED_FIXED_SHAPE_TEST_NOT_AMD',
            [H.make_tensor_value_info('input',T.INT8,list(h.INPUT))],
            [H.make_tensor_value_info('output',T.INT8,list(h.OUTPUT))],
            [N.from_array(np.array([1,2,2,1],np.float32),'scales')])
        raw = H.make_model(graph,opset_imports=[H.make_opsetid('',17)],ir_version=9).SerializeToString()
        self.model.write_bytes(raw)
        # Only unit-test the reusable session boundary. Production pin policy is
        # unchanged and would reject this owned fixture; no evidence is emitted.
        with patch.object(h.import_sesr,'_read_verified',return_value=(raw,hashlib.sha256(raw).hexdigest())):
            self.session = h.PersistentTileSession(self.model,'cpu-reference')
        self.session.initialize(self.directory)

    def tearDown(self):
        self.session.close(); self.temp.cleanup()

    def test_persistent_buffer_reuse_and_independent_oracle(self):
        session = self.session.session
        output = np.empty(h.OUTPUT,np.int8)
        for seed in (0,1,255,2**32-1):
            tensor = h.deterministic_input(np,seed)
            self.session.run(tensor,output)
            expected = np.repeat(np.repeat(tensor,2,axis=1),2,axis=2)
            np.testing.assert_array_equal(output,expected)
            self.assertIs(self.session.session,session)
        self.assertEqual(self.session.session.get_providers(),['CPUExecutionProvider'])

    def test_input_conversion_and_rgb_decode(self):
        tensor = h.deterministic_input(np,0)
        self.assertEqual(tensor.reshape(-1)[:4].tolist(),[-128,-91,-54,-17])
        self.assertTrue(tensor.flags.c_contiguous)
        rgb = np.clip(tensor.astype(np.int16)+128,0,255).astype(np.uint8)
        self.assertEqual(rgb.reshape(-1)[:4].tolist(),[0,37,74,111])
        self.assertFalse(np.array_equal(tensor,h.deterministic_input(np,1)))

    def test_wrong_input_shape_and_dtype(self):
        output=np.empty(h.OUTPUT,np.int8)
        for tensor in (np.zeros((1,3,256,256),np.int8),np.zeros(h.INPUT,np.uint8)):
            with self.assertRaises(h.reference.ReferenceError):self.session.run(tensor,output)

    def test_wrong_or_nonwritable_output(self):
        tensor=h.deterministic_input(np,0)
        for output in (np.empty(h.INPUT,np.int8),np.empty(h.OUTPUT,np.uint8)):
            with self.assertRaises(h.ProbeError):self.session.run(tensor,output)
        output=np.empty(h.OUTPUT,np.int8);output.flags.writeable=False
        with self.assertRaises(h.ProbeError):self.session.run(tensor,output)

    def test_effective_provider_fallback_rejected(self):
        with patch.object(self.session.session,'get_providers',return_value=['AzureExecutionProvider','CPUExecutionProvider']):
            with self.assertRaises(h.ProbeError):self.session.run(h.deterministic_input(np,0),np.empty(h.OUTPUT,np.int8))

    def test_separate_cpu_session_agreement(self):
        golden=h.reference.CpuReferenceSession(self.model,layout='NHWC')
        try:
            self.assertIsNot(golden.session,self.session.session)
            tensor=h.deterministic_input(np,17);output=np.empty(h.OUTPUT,np.int8)
            self.session.run(tensor,output)
            np.testing.assert_array_equal(output,golden.run(tensor))
        finally:golden.session=None


if __name__=='__main__':unittest.main()
