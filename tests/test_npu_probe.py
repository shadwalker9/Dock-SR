"""Read-only probe preparation never becomes physical inference evidence."""
from __future__ import annotations
import copy
import gzip
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

    def test_laboratory_inventory_allowlists_cpu_and_discovers_unmeasured_sensors(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            files={'proc/cpuinfo':'vendor_id : AuthenticAMD\nmodel name : owned-cpu\nserial : PRIVATE-CANARY\n',
                   'proc/sys/kernel/osrelease':'review-kernel',
                   'boot/config-review-kernel':'CONFIG_DRM_ACCEL=y\nCONFIG_AMD_IOMMU=y\n# CONFIG_IOMMU_SVA is not set\n',
                   'sys/class/hwmon/hwmon0/name':'amdgpu',
                   'sys/class/hwmon/hwmon0/power1_input':'123000000',
                   'sys/class/hwmon/hwmon0/power1_label':'SoC',
                   'proc/101/comm':'gamescope\n','proc/102/comm':'steam\n'}
            for name,value in files.items():
                p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
            before={str(p.relative_to(base)):p.read_bytes() for p in base.rglob('*') if p.is_file()}
            value=report(base)
            after={str(p.relative_to(base)):p.read_bytes() for p in base.rglob('*') if p.is_file()}
        self.validator.validate(value)
        lab=value['laboratory']
        self.assertEqual(before,after)
        self.assertNotIn('PRIVATE-CANARY',json.dumps(lab))
        self.assertEqual(lab['cpu_identity']['fields']['model name'],'owned-cpu')
        self.assertEqual(lab['kernel_config']['symbols']['CONFIG_DRM_ACCEL'],'y')
        self.assertEqual(lab['kernel_config']['symbols']['CONFIG_IOMMU_SVA'],'n')
        self.assertIsNone(lab['kernel_config']['symbols']['CONFIG_DRM_ACCEL_AMDXDNA'])
        self.assertEqual(lab['gamescope_steam_processes']['counts'],{'gamescope':1,'steam':1})
        sensor=lab['sensor_inventory']['sensors'][0]
        self.assertEqual(sensor['unit'],'uW')
        self.assertEqual(sensor['measurement_status'],'NOT_RUN')
        self.assertEqual(sensor['power_scope'],'UNKNOWN')
        self.assertNotIn('watts',sensor)

    def test_bounded_compressed_kernel_config_and_corruption(self):
        with tempfile.TemporaryDirectory() as root:
            fs=probe.docksr_detect.FileSystem(root);p=Path(root)/'proc/config.gz';p.parent.mkdir()
            p.write_bytes(gzip.compress(b'CONFIG_DRM_ACCEL_AMDXDNA=m\n'))
            value=probe.kernel_config(fs,{'status':'absent'})
            self.assertEqual(value['symbols']['CONFIG_DRM_ACCEL_AMDXDNA'],'m')
            p.write_bytes(b'broken-gzip')
            self.assertEqual(probe.kernel_config(fs,{'status':'absent'})['status'],'unavailable')
            p.write_bytes(gzip.compress(b'x'*1_048_577))
            value=probe.kernel_config(fs,{'status':'absent'})
            self.assertEqual(value['attempts'][0]['status'],'too_large')

    def test_missing_preflight_capabilities_have_reasons(self):
        with tempfile.TemporaryDirectory() as root:value=report(root)
        lab=value['laboratory']
        self.assertEqual(lab['kernel_config']['reason'],'NO_READABLE_BOUNDED_KERNEL_CONFIG')
        self.assertEqual(lab['xrt_smi_capabilities']['status'],'missing_tool')
        self.assertEqual(lab['sensor_inventory']['sensors'],[])
        self.assertIsNone(lab['gamescope_steam_processes']['counts'])
        self.assertEqual(value['physical_test_status'],'NOT_RUN')

    def test_graphics_inventory_requires_explicit_opt_in(self):
        with patch.object(probe.docksr_detect.CommandRunner,'run',return_value={'status':'ok'}) as run:
            self.assertEqual(probe.InventoryRunner().run(['vulkaninfo'])['status'],'not_run')
            run.assert_not_called()
            self.assertEqual(probe.InventoryRunner(True).run(['vulkaninfo'])['status'],'ok')
            run.assert_called_once()

    def test_runtime_module_version_is_metadata_only(self):
        process=subprocess.CompletedProcess([],0,stdout=b'{"version":"1.20.1","providers":["CPUExecutionProvider"]}',stderr=b'')
        with patch.object(probe.subprocess,'run',return_value=process):
            value=probe.runtime_inventory(True)
        self.assertEqual(value['module_version'],'1.20.1')
        self.assertFalse(value['provider_registration_is_execution'])

    def test_device_permission_inventory_never_opens_a_node(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);p=base/'dev/accel/accel0';p.parent.mkdir(parents=True);p.write_text('owned node fixture');p.chmod(0o640)
            value=report(base)
        self.assertEqual(value['laboratory']['device_permissions'][0]['mode'],'0640')
        self.assertFalse(value['laboratory']['device_permissions'][0]['opened'])
        self.assertFalse(value['npu_inference_verified'])


if __name__=='__main__':unittest.main()
