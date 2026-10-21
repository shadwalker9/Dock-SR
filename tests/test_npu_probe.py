"""Read-only probe preparation never becomes physical inference evidence."""
from __future__ import annotations
import copy
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
sys.path.insert(0, str(ROOT / 'scripts'))
import npu_probe as probe
from jsonschema import Draft202012Validator


class MissingRunner:
    def run(self, argv):
        return {'status':'missing_tool','argv':list(argv)}


def report(root):
    return probe.prepare(fs=probe.docksr_detect.FileSystem(root),runner=MissingRunner(),
        runtime={'packages':{'onnxruntime':None,'onnxruntime-vitisai':None,'onnxruntime-directml':None},
                 'provider_listing_state':'LISTED','available_providers':['VitisAIExecutionProvider'],
                 'provider_registration_is_execution':False},timestamp='2026-10-20T00:00:00Z')


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator=Draft202012Validator(json.loads((ROOT/'schemas/npu-probe.schema.json').read_text()))
        cls.validator.check_schema(cls.validator.schema)

    def test_no_device_no_execution(self):
        with tempfile.TemporaryDirectory() as root:
            value=report(root)
        self.validator.validate(value)
        self.assertEqual(value['physical_test_status'],'NOT_RUN')
        self.assertFalse(value['hardware_execution_verified'])
        self.assertFalse(value['npu_runtime_ready'])
        self.assertEqual(value['planned_probe']['warm_inference_samples_ms'],[])

    def test_provider_registration_cannot_be_inference(self):
        with tempfile.TemporaryDirectory() as root:
            value=report(root)
        self.assertIn('VitisAIExecutionProvider',value['runtime']['available_providers'])
        for field in ('npu_device_detected','npu_runtime_ready','npu_inference_verified','npu_game_frames_consumed'):
            self.assertFalse(value[field])

    def test_visible_node_cannot_attest_target(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);(base/'dev/accel').mkdir(parents=True)
            (base/'dev/accel/accel0').write_text('fixture')
            value=report(base)
        self.assertEqual(value['inventory']['device_nodes']['accel']['status'],'present')
        self.assertFalse(value['npu_device_detected'])
        self.assertFalse(value['hardware_execution_verified'])

    def test_permission_inventory_is_preserved(self):
        class Denied(probe.docksr_detect.FileSystem):
            def entries(self,path):return {'status':'permission_denied','errno':13}
        with tempfile.TemporaryDirectory() as root:
            value=probe.prepare(fs=Denied(root),runner=MissingRunner(),runtime=report(root)['runtime'])
        self.assertEqual(value['inventory']['device_nodes']['accel']['status'],'permission_denied')
        self.assertEqual(value['physical_test_status'],'NOT_RUN')

    def test_unknown_interop_not_unsupported(self):
        with tempfile.TemporaryDirectory() as root:value=report(root)
        self.assertEqual(value['external_memory']['ort_interop_api_status'],'UNKNOWN')
        self.assertEqual(value['external_memory']['provider_importer_status'],'NOT_RUN')
        self.assertEqual(value['external_memory']['imported_memory_inference_status'],'NOT_RUN')

    def test_inventory_does_not_rerun_graphics(self):
        with patch.object(probe.docksr_detect.CommandRunner,'run',side_effect=AssertionError('must not launch')):
            value=probe.InventoryRunner().run(['vulkaninfo','--summary'])
        self.assertEqual(value['status'],'not_run')

    def test_model_identity_rejects_wrong_bytes_without_execution(self):
        with tempfile.TemporaryDirectory() as root:
            model=Path(root)/'wrong.onnx';model.write_bytes(b'wrong')
            value=probe.model_identity(model)
        self.assertEqual(value['state'],'FAILED')
        self.assertEqual(value['error_code'],'SIZE_MISMATCH')
        self.assertFalse(value['execution_performed'])

    def test_missing_runtime_metadata_is_not_provider_absence(self):
        with patch.object(probe.importlib.metadata,'version',side_effect=probe.importlib.metadata.PackageNotFoundError):
            value=probe.runtime_inventory()
        self.assertEqual(value['provider_listing_state'],'NOT_RUN')
        self.assertEqual(value['available_providers'],[])
        self.assertIsNone(value['packages']['onnxruntime'])

    def test_optional_provider_query_bounded_failure(self):
        with patch.object(probe.subprocess,'run',side_effect=subprocess.TimeoutExpired('fixture',15)):
            value=probe.runtime_inventory(True)
        self.assertEqual(value['provider_listing_state'],'UNAVAILABLE')

    def test_schema_rejects_invented_hardware_and_binding_results(self):
        with tempfile.TemporaryDirectory() as root:value=report(root)
        mutations=[('hardware_execution_verified',True),('npu_device_detected',True),
            ('npu_runtime_ready',True),('npu_inference_verified',True),('npu_game_frames_consumed',True),
            ('physical_test_status','PASS'),('evidence_class','REAL_NPU')]
        for key,new in mutations:
            candidate=copy.deepcopy(value);candidate[key]=new
            self.assertTrue(list(self.validator.iter_errors(candidate)),key)
        for section,key,new in [('inventory','npu_ready',True),('planned_probe','provider_requested',True),
            ('planned_probe','physical_npu_self_test_verified',True),
            ('planned_probe','neural_result_consumed_in_presented_frame',True),
            ('external_memory','memory_import_status','PASS'),('external_memory','zero_copy_verified',True)]:
            candidate=copy.deepcopy(value);candidate[section][key]=new
            self.assertTrue(list(self.validator.iter_errors(candidate)),key)

    def test_private_output_and_overwrite_refusal(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);base.chmod(0o700);path=base/'probe.json'
            value=report(base);probe.write_new_private(path,value)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            before=path.read_bytes()
            with self.assertRaises(FileExistsError):probe.write_new_private(path,value)
            self.assertEqual(before,path.read_bytes())

    def test_output_in_git_and_symlink_parent_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);base.chmod(0o700);(base/'.git').mkdir()
            with self.assertRaises(probe.import_sesr.ImportFailure):probe.write_new_private(base/'probe.json',report(base))
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);(base/'real').mkdir();(base/'alias').symlink_to(base/'real',target_is_directory=True)
            with self.assertRaises(probe.import_sesr.ImportFailure):probe.write_new_private(base/'alias'/'probe.json',report(base))


if __name__=='__main__':unittest.main()
