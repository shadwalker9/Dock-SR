"""Host logic/serialization tests; mocks never establish physical execution."""
import copy
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import h1_probe as h
from validate_gate0 import validate_record


def job():
    return {'mode': 'cpu-reference', 'model': '/nonexistent/owned-test.onnx', 'readiness': None,
            'approve_physical_run': False, 'collect_xrt_context': False, 'warmup': 1, 'samples': 3,
            'seed': 0, 'timeout': 10, 'frame_id': 1, 'generation': 1, 'deadline_ns': 10**18,
            'run_id': 'h1-' + 'a' * 32}


def example():
    r = h.base_record(job())
    r.update(record_purpose='SCHEMA_EXAMPLE', fixture_notice='SYNTHETIC SCHEMA FIXTURE - not a hardware run or proof that any stated execution occurred.')
    return r


def metadata():
    return SimpleNamespace(model_bytes=b'OWNED_TEST_BYTES', input_shape=h.INPUT, output_shape=h.OUTPUT,
        input_dtype='int8', output_dtype='int8', ort=SimpleNamespace(get_available_providers=lambda: ['CPUExecutionProvider']))


class ProbeHostTests(unittest.TestCase):
    def test_hash_boundary_uses_original_pin(self):
        with patch.object(h.import_sesr, '_read_verified', return_value=(b'OWNED_TEST_BYTES', h.import_sesr.PINNED_IDENTITY.sha256)) as read, patch.object(h.reference, 'CpuReferenceSession', return_value=metadata()):
            session = h.PersistentTileSession('/unused/model.onnx', 'cpu-reference')
        self.assertEqual(read.call_args.args[1], h.import_sesr.PINNED_IDENTITY)
        self.assertEqual(session.model_hash, h.import_sesr.PINNED_IDENTITY.sha256)

    def test_wrong_hash_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong.onnx'
            path.write_bytes(b'x' * h.import_sesr.PINNED_IDENTITY.size_bytes)
            with patch.object(h.reference, 'CpuReferenceSession') as runtime, self.assertRaises(h.import_sesr.ImportFailure) as error:
                h.PersistentTileSession(path, 'cpu-reference')
            self.assertEqual(error.exception.code, 'HASH_MISMATCH')
            runtime.assert_not_called()

    def test_missing_model(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError): h.PersistentTileSession(Path(directory) / 'absent.onnx', 'cpu-reference')

    def test_missing_runtime_explicit(self):
        with patch.object(h.import_sesr, '_read_verified', return_value=(b'OWNED_TEST_BYTES', 'a'*64)), patch.object(h.reference, 'CpuReferenceSession', side_effect=h.reference.ReferenceError('OPTIONAL_DEPENDENCY_MISSING', 'test', not_run=True)):
            with self.assertRaises(h.reference.ReferenceError) as error: h.PersistentTileSession('/unused', 'cpu-reference')
        self.assertEqual(error.exception.code, 'OPTIONAL_DEPENDENCY_MISSING')

    def test_bad_graph_signature(self):
        for field, value in (('input_shape', (1,3,256,256)), ('output_shape', (1,768,768,3)), ('input_dtype', 'uint8')):
            meta = metadata(); setattr(meta, field, value)
            with self.subTest(field=field), patch.object(h.import_sesr, '_read_verified', return_value=(b'OWNED_TEST_BYTES', 'a'*64)), patch.object(h.reference, 'CpuReferenceSession', return_value=meta), self.assertRaises(h.ProbeError):
                h.PersistentTileSession('/unused', 'cpu-reference')

    def test_missing_vitis_provider_blocked_no_session(self):
        with patch.object(h.import_sesr, '_read_verified', return_value=(b'OWNED_TEST_BYTES', 'a'*64)), patch.object(h.reference, 'CpuReferenceSession', return_value=metadata()):
            session = h.PersistentTileSession('/unused', 'npu-candidate')
        with self.assertRaises(h.ProbeError) as error: session.initialize(Path('/unused'))
        self.assertEqual(error.exception.code, 'REQUESTED_PROVIDER_MISSING')
        self.assertIsNone(session.session)

    def test_vitis_initialization_exception_is_explicit(self):
        class ProviderError(Exception): pass
        meta = metadata()
        meta.ort = SimpleNamespace(get_available_providers=lambda: ['VitisAIExecutionProvider'],
                                   SessionOptions=lambda: (_ for _ in ()).throw(ProviderError('PRIVATE_CANARY')))
        with patch.object(h.import_sesr, '_read_verified', return_value=(b'OWNED_TEST_BYTES', 'a'*64)), patch.object(h.reference, 'CpuReferenceSession', return_value=meta):
            session = h.PersistentTileSession('/unused', 'npu-candidate')
        with self.assertRaises(h.ProbeError) as error: session.initialize(Path('/unused'))
        self.assertEqual(error.exception.code, 'REQUESTED_PROVIDER_SESSION_UNAVAILABLE')
        self.assertNotIn('PRIVATE_CANARY', str(error.exception))

    def test_provider_listing_and_session_creation_never_real_npu(self):
        for created in (False, True):
            r = example(); x = r['h1_run']
            x.update(mode='npu-candidate', requested_provider='VitisAIExecutionProvider',
                     available_providers=['VitisAIExecutionProvider'], provider_discovered=True,
                     provider_session_created=created, active_providers=['VitisAIExecutionProvider'] if created else [])
            validate_record(r, 'hardware')
            self.assertFalse(x['real_npu_verified'])
            x['real_npu_verified'] = True
            with self.assertRaises(ValueError): validate_record(r, 'hardware')

    def test_missing_placement_or_context_prevents_upgrade(self):
        for field in ('npu_placement_evidence_present', 'active_xrt_context_evidence_present'):
            r = example(); r['h1_run'][field] = True
            with self.subTest(field=field), self.assertRaises(ValueError): validate_record(r, 'hardware')
        r = example(); r['h1_run']['classification'] = 'REAL_NPU_VERIFIED'
        with self.assertRaises(ValueError): validate_record(r, 'hardware')
        r = example(); r['evidence'] = 'REAL_NPU'
        with self.assertRaises(ValueError): validate_record(r, 'hardware')

    def test_comparison_mismatch_cannot_pass(self):
        r = example(); x = r['h1_run']
        x['cpu_reference_agreement_pass'] = True
        x['comparison'].update(compared_samples=2, max_abs_error=1, cpu_repeats_equal=True,
                               output_sha256='a'*64, reference_sha256='b'*64)
        with self.assertRaises(ValueError): validate_record(r, 'hardware')

    def test_contradictory_provider_states(self):
        for changed in ({'provider_discovered': True}, {'provider_session_created': True}, {'requested_provider': 'VitisAIExecutionProvider'}):
            r = example(); r['h1_run'].update(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError): validate_record(r, 'hardware')

    def test_synthetic_host_ledger_cannot_authorize_candidate(self):
        path = ROOT / 'tests/fixtures/steamos-readiness/hypothetical-h1.json'
        j = job(); j.update(mode='npu-candidate', readiness=str(path), approve_physical_run=True)
        with self.assertRaises(h.ProbeError) as error: h.approved_host(j, {'inventory': None})
        self.assertEqual(error.exception.code, 'HOST_READINESS_UNREVIEWED_OR_CHANGED')

    def test_no_approval_before_dependency_or_session_loading(self):
        with self.assertRaises(h.ProbeError): h.approved_host(job(), {})

    def test_private_output_refuses_git_overwrite_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory); target = parent / 'existing'; target.mkdir()
            with self.assertRaises(FileExistsError): h.supervise(job(), target)
            parent.chmod(0o755)
            with self.assertRaises(h.ProbeError): h.supervise(job(), parent / 'new')
        with self.assertRaises(h.import_sesr.ImportFailure): h.supervise(job(), ROOT / 'must-not-exist')

    def test_actual_missing_model_cli_private_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            cmd = [sys.executable, '-I', str(ROOT/'scripts/h1_probe.py'), '--model', str(Path(directory)/'missing.onnx'), '--output-dir', str(output)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertNotIn(directory, result.stdout + result.stderr)
            record = json.loads((output/'hardware-evidence.json').read_text())
            validate_record(record, 'hardware')
            self.assertEqual(record['h1_run']['classification'], 'BLOCKED')
            self.assertEqual(record['last_error']['code'], 'MODEL_MISSING')
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir()))

    def test_timeout_reaps_worker_and_never_publishes_success(self):
        original = subprocess.Popen
        children = []
        def launch(_argv, **kwargs):
            worker_path = str(Path(_argv[-1]).parent / 'worker-evidence.json')
            code = 'import pathlib,time; pathlib.Path(' + repr(worker_path) + ').write_text("{\\"bogus_pass\\":true}"); time.sleep(30)'
            child = original([sys.executable, '-I', '-c', code], **kwargs)
            children.append(child); return child
        j = job(); j['timeout'] = 0.5
        with tempfile.TemporaryDirectory() as directory, patch.object(h.subprocess, 'Popen', side_effect=launch):
            code, record = h.supervise(j, Path(directory)/'timeout')
            self.assertTrue((Path(directory)/'timeout/unaccepted-worker-report.json').exists())
            self.assertEqual(json.loads((Path(directory)/'timeout/hardware-evidence.json').read_text())['evidence'], 'NONE')
        self.assertEqual(code, 124)
        self.assertEqual(record['last_error']['code'], 'TOTAL_TIMEOUT')
        self.assertIsNotNone(children[0].returncode)
        self.assertEqual(record['evidence'], 'NONE')

    def test_interrupt_reaps_worker(self):
        original = subprocess.Popen
        children = []
        def launch(_argv, **kwargs):
            child = original([sys.executable, '-I', '-c', 'import time; time.sleep(30)'], **kwargs)
            children.append(child)
            wait = child.wait
            calls = [0]
            def interrupted(*a, **kw):
                calls[0] += 1
                if calls[0] == 1: raise KeyboardInterrupt
                return wait(*a, **kw)
            child.wait = interrupted
            return child
        with tempfile.TemporaryDirectory() as directory, patch.object(h.subprocess, 'Popen', side_effect=launch):
            code, record = h.supervise(job(), Path(directory)/'interrupted')
        self.assertEqual(code, 130)
        self.assertIsNotNone(children[0].returncode)
        self.assertEqual(record['last_error']['code'], 'INTERRUPTED')

    def test_cli_invalid_bounds_before_output(self):
        for key, value in (('--timeout', 'nan'), ('--samples', '1'), ('--seed', '-1'), ('--generation', '0')):
            with self.subTest(key=key), redirect_stdout(StringIO()):
                self.assertEqual(h.main(['--model','missing','--output-dir','unused',key,value]), 2)

    def test_missing_schema_dependency_blocks_before_worker(self):
        import builtins
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == 'jsonschema': raise ImportError('PRIVATE_CANARY')
            return original(name, *args, **kwargs)
        with patch.object(builtins, '__import__', side_effect=missing), patch.object(h, 'supervise') as run, redirect_stdout(StringIO()) as output:
            self.assertEqual(h.main(['--model','missing','--output-dir','unused']), 2)
        run.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['error_code'], 'SCHEMA_DEPENDENCY_MISSING')
        self.assertNotIn('PRIVATE_CANARY', output.getvalue())

    def test_example_roundtrip_and_unknown_extension_fields(self):
        validate_record(json.loads(json.dumps(example())), 'hardware')
        r = example(); r['h1_run']['invented_attestation'] = True
        with self.assertRaises(ValueError): validate_record(r, 'hardware')

    def test_cpu_mode_timing_identity_and_analyzer_compatibility(self):
        from test_benchmark_analysis import fixture as benchmark_fixture
        from benchmark_analysis import analyze
        r = benchmark_fixture(2)
        r.update(runtime_state='CPU_REFERENCE_ACTIVE', evidence='REAL_CPU', backend_kind='CPU',
                 execution_environment='HOST_ONLY', model_id=h.import_sesr.PINNED_IDENTITY.model_id,
                 model_sha256=h.import_sesr.PINNED_IDENTITY.sha256, warmup_count=1,
                 sample_count=2, successful_runs=2, samples_ms=[10,10],
                 npu_or_pipeline_ms_p50=10, npu_or_pipeline_ms_p95=10, npu_or_pipeline_ms_p99=10,
                 model_validation={'status':'VALIDATED','correct_output':True,'non_identity':True,
                     'input_sha256':'a'*64,'cpu_reference_sha256':'b'*64,'npu_output_sha256':None,
                     'comparison':{'method':'max_abs_error','atol':0,'rtol':0,'max_abs_error':0,'passed':True},'evidence_refs':[]})
        x = example()['h1_run'];r['h1_run']=x
        x.update(classification='CPU_REFERENCE_PASS', model_verified=True, provider_discovered=True,
                 provider_session_created=True, available_providers=['CPUExecutionProvider'],
                 active_providers=['CPUExecutionProvider'], cpu_reference_agreement_pass=True)
        x['comparison'].update(compared_samples=2,max_abs_error=0,cpu_repeats_equal=True,
                               input_sha256='a'*64,output_sha256='b'*64,reference_sha256='b'*64)
        run = r['benchmark_run'];run.update(run_id=x['run_id'],session_id=x['run_id'],expected_tiles_per_frame=1,
            source_extent={'width':256,'height':256},output_extent={'width':512,'height':512})
        for f in run['frames']:f.update(completed_tiles=1,validated_tiles=1)
        self.assertEqual(analyze(r)['evidence'],'SIMULATED')
        for field, value in (('completed_ns',10),('configuration_generation',2),('frame_id',99)):
            bad=copy.deepcopy(r);bad['benchmark_run']['frames'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_record(bad,'hardware')


if __name__ == '__main__':
    unittest.main()
