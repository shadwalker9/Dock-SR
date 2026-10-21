"""Owned synthetic metadata; no physical SteamOS/NPU success is represented."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import steamos_readiness as r
from jsonschema import Draft202012Validator

FIXTURES = ROOT / 'tests/fixtures/steamos-readiness'


def fixture(name='initial-plan.json'):
    return json.loads((FIXTURES / name).read_text())


class Runner:
    def __init__(self, status='missing_tool'):
        self.status = status
        self.calls = []

    def run(self, argv):
        self.calls.append(argv)
        return {'argv': argv, 'status': self.status, 'returncode': 7,
                'stdout': '/home/PRIVATE_CANARY host-PRIVATE_CANARY serial-PRIVATE_CANARY',
                'stderr': 'PRIVATE_CANARY'}


class ReadinessTests(unittest.TestCase):
    def test_schema_and_positive_fixtures(self):
        Draft202012Validator.check_schema(json.loads((ROOT / 'schemas/steamos-readiness.schema.json').read_text()))
        for name in ('initial-plan.json', 'hypothetical-h1.json'):
            self.assertEqual(r.validate(fixture(name))['status'], 'VALID')
        self.assertEqual(fixture('hypothetical-h1.json')['physical_test_status'], 'NOT_TESTED')

    def test_negative_fixtures(self):
        for name in FIXTURES.glob('invalid-*.json'):
            with self.subTest(name=name.name), self.assertRaises(ValueError):
                r.validate(json.loads(name.read_text()))

    def test_missing_nodes_and_tools(self):
        runner = Runner()
        with tempfile.TemporaryDirectory() as directory:
            record = r.discover(fs=r.docksr_detect.FileSystem(directory), runner=runner, tool_lookup=lambda _: None)
        r.validate(record)
        self.assertEqual(record['physical_test_status'], 'NOT_TESTED')
        self.assertEqual([row['status'] for row in record['inventory']['nodes']], ['absent', 'absent'])
        self.assertEqual([row['status'] for row in record['inventory']['commands']], ['missing_tool'] * 3)
        self.assertTrue(all(row['exit_status'] is None for row in record['inventory']['commands']))
        self.assertEqual(runner.calls, [list(v) for v in r.COMMANDS])

    def test_failed_tools_distinct_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            record = r.discover(fs=r.docksr_detect.FileSystem(directory), runner=Runner('command_failed'), tool_lookup=lambda _: '/home/PRIVATE_CANARY/bin/x')
        r.validate(record)
        self.assertTrue(all(row['exit_status'] == 7 for row in record['inventory']['commands']))
        self.assertNotIn('PRIVATE_CANARY', json.dumps(record))
        self.assertNotIn('/home/', json.dumps(record))

    def test_allowlisted_identity_no_shell_or_device_open(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = {'etc/os-release': 'ID=steamos\nVERSION_ID="3.8"\nBUILD_ID=20261021\nHOME_URL=/home/PRIVATE_CANARY\nNAME=PRIVATE_CANARY',
                     'proc/cpuinfo': 'vendor_id : AuthenticAMD\nmodel : 42\nSerial : PRIVATE_CANARY\nmodel name : PRIVATE_CANARY',
                     'proc/sys/kernel/osrelease': '6.16-valve', 'dev/accel/accel0': 'DO_NOT_OPEN',
                     'sys/bus/pci/devices/0000:04:00.1/vendor': '0x1022',
                     'sys/bus/pci/devices/0000:04:00.1/device': '0x1234'}
            for path, value in paths.items():
                p = base / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
            runner = Runner('timeout')
            original = Path.open
            def guarded(path, *args, **kwargs):
                self.assertNotIn('/dev/', str(path))
                return original(path, *args, **kwargs)
            with patch.object(Path, 'open', guarded), patch.object(r.npu_probe, 'runtime_inventory', return_value={'packages': {'onnxruntime': '1.20.1', 'onnxruntime-vitisai': None, 'onnxruntime-directml': None}}) as metadata:
                record = r.discover(fs=r.docksr_detect.FileSystem(base), runner=runner, tool_lookup=lambda _: None)
            metadata.assert_called_once_with(False)
        r.validate(record)
        self.assertEqual(record['os_family'], 'STEAMOS')
        self.assertEqual(record['inventory']['nodes'][0]['nodes'][0]['opened'], False)
        self.assertNotIn('PRIVATE_CANARY', json.dumps(record))
        self.assertEqual(set(row['status'] for row in record['areas'].values()), {'NOT_TESTED'})

    def test_missing_permissions_not_absence(self):
        class Denied(r.docksr_detect.FileSystem):
            def entries(self, path): return {'status': 'permission_denied', 'errno': 13}
        with tempfile.TemporaryDirectory() as directory:
            record = r.discover(fs=Denied(directory), runner=Runner('permission_denied'), tool_lookup=lambda _: None)
        r.validate(record)
        self.assertEqual(record['inventory']['nodes'][0]['status'], 'permission_denied')
        self.assertEqual(record['inventory']['commands'][0]['status'], 'permission_denied')

    def test_real_npu_claims_rejected(self):
        for field, value in (('npu_execution_claim', 'REAL_NPU'), ('evidence_class', 'REAL_NPU'), ('hardware_execution_verified', True)):
            record = fixture(); record[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): r.validate(record)

    def test_detection_or_documentation_cannot_promote_inference(self):
        record = fixture(); record['gates']['H1']['status'] = 'PASS'
        with self.assertRaises(ValueError): r.validate(record)
        record = fixture('hypothetical-h1.json'); record['evidence'][0]['category'] = 'PRIMARY_DOCUMENTATION'
        with self.assertRaises(ValueError): r.validate(record)

    def test_versions_unknown_fields_and_nonfinite(self):
        for field, value in (('schema_version', '2.0.0'), ('invented', True), ('read_only', False), ('generated_at_utc', 'yesterday')):
            record = fixture(); record[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): r.validate(record)
        record = fixture(); record['bad'] = float('nan')
        with self.assertRaises(ValueError): r.validate(record)

    def test_reference_integrity_and_failure_codes(self):
        record = fixture('hypothetical-h1.json'); record['evidence'].append(copy.deepcopy(record['evidence'][0]))
        with self.assertRaises(ValueError): r.validate(record)
        record = fixture(); record['failures'] = [{'code': 'PROVIDER_MISSING', 'status': 'SUSPECTED', 'evidence_refs': ['missing']}]
        with self.assertRaises(ValueError): r.validate(record)
        self.assertEqual(len(r.FAILURES), 13)

    def test_ubuntu_cannot_be_called_steamos(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'etc/os-release'; p.parent.mkdir(); p.write_text('ID=ubuntu')
            record = r.discover(fs=r.docksr_detect.FileSystem(directory), runner=Runner(), tool_lookup=lambda _: None)
        record['os_family'] = 'STEAMOS'
        with self.assertRaises(ValueError): r.validate(record)

    def test_round_trip_and_private_exclusive_output(self):
        value = fixture()
        self.assertEqual(r.validate(json.loads(json.dumps(value)))['status'], 'VALID')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'new.json'
            r.npu_probe.write_new_private(path, value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError): r.npu_probe.write_new_private(path, value)
            with self.assertRaises(ValueError): r.npu_probe.write_new_private(ROOT / 'must-not-write.json', value)
            os.chmod(directory, 0o755)
            with self.assertRaises(ValueError): r.npu_probe.write_new_private(Path(directory) / 'other.json', value)

    def test_cli_validation_duplicate_keys_and_size(self):
        cmd = [sys.executable, str(ROOT / 'scripts/steamos_readiness.py'), '--validate']
        good = subprocess.run([*cmd, str(FIXTURES / 'initial-plan.json')], capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            for raw in ('{"x":1,"x":2}', ' ' * 1_048_577, '[' * 2000 + ']' * 2000):
                path.write_text(raw)
                result = subprocess.run([*cmd, str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn(directory, result.stdout)
                self.assertEqual(result.stderr, '')

    def test_root_discovery_refused_before_collecting(self):
        with patch.object(r.os, 'geteuid', return_value=0), patch.object(r, 'discover') as collect, redirect_stdout(StringIO()) as output:
            self.assertEqual(r.main(['--output', '/tmp/never-created.json']), 1)
        collect.assert_not_called()
        self.assertNotIn('/tmp/', output.getvalue())

    def test_command_state_contradictions(self):
        with tempfile.TemporaryDirectory() as directory:
            record = r.discover(fs=r.docksr_detect.FileSystem(directory), runner=Runner(), tool_lookup=lambda _: None)
        record['inventory']['commands'][0]['exit_status'] = 0
        with self.assertRaises(ValueError): r.validate(record)

    def test_documentation_and_fixture_cannot_attest_compatibility(self):
        record = fixture('hypothetical-h1.json')
        record['physical_test_status'] = 'OBSERVED_ON_DEVICE'
        with self.assertRaises(ValueError): r.validate(record)
        record = fixture(); record['areas']['kernel']['status'] = 'SUPPORTED_BY_DOCUMENTATION'
        with self.assertRaises(ValueError): r.validate(record)

    def test_failure_needs_local_observation_not_documentation(self):
        record = fixture('hypothetical-h1.json')
        record['evidence'].append({'id': 'paper', 'category': 'PRIMARY_DOCUMENTATION', 'kind': 'OTHER', 'artifact': 'source.txt', 'sha256': '0'*64})
        record['failures'] = [{'code': 'GPU_NPU_CONTENTION', 'status': 'SUSPECTED', 'evidence_refs': ['paper']}]
        r.validate(record)
        record['failures'][0]['status'] = 'CONFIRMED'
        with self.assertRaises(ValueError): r.validate(record)

    def test_all_h1_categories_and_ladder_order_required(self):
        for kind in ('MODEL_IDENTITY', 'HARDWARE_RECORD', 'OPERATOR_ASSIGNMENT', 'ACTIVE_CONTEXT', 'CPU_REFERENCE', 'OUTPUT_COMPARISON'):
            record = fixture('hypothetical-h1.json')
            record['gates']['H1']['evidence_refs'].remove(kind.lower())
            with self.subTest(kind=kind), self.assertRaises(ValueError): r.validate(record)
        record = fixture('hypothetical-h1.json')
        for stage in r.STAGES[1:]:
            record['interop'][stage] = {'status': 'PASS', 'evidence_refs': ['hardware_record']}
        r.validate(record)
        record['interop']['EXTERNAL_TENSOR_BOUND']['status'] = 'UNKNOWN'
        with self.assertRaises(ValueError): r.validate(record)

    def test_hypothesis_ids_and_steam_prerequisite(self):
        rows = json.loads((ROOT / 'docs/r009-hypotheses.json').read_text())['hypotheses']
        self.assertEqual([row['id'] for row in rows], [f'HYP-{i:03}' for i in range(1, 13)])
        for row in rows:
            self.assertEqual(set(row), {'id','description','evidence_category','baseline','required_capability','measurement','falsification','stop_go','hardware_dependency','steamos_host_prerequisite','current_state'})
            self.assertTrue(row['steamos_host_prerequisite'])
            self.assertEqual(row['current_state'], 'NOT_TESTED')


if __name__ == '__main__':
    unittest.main()
