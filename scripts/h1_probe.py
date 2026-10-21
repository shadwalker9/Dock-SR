#!/usr/bin/env python3
"""Bounded SESR H1 laboratory: persistent CPU reference or approved Vitis candidate.

Not a native product backend. Raw provider/context reports remain unverified until
device-specific adapters are validated. This version cannot emit REAL_NPU.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import uuid

# The supervisor starts this reviewed script with -I; never import from cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_sesr
import npu_probe
import onnx_reference as reference
import steamos_readiness
from cpu_worker_executor import regular_bytes
from validate_gate0 import _pairs, validate_record

ROOT = Path(__file__).resolve().parents[1]
INPUT = (1, 256, 256, 3)
OUTPUT = (1, 512, 512, 3)
PROVIDERS = {'cpu-reference': 'CPUExecutionProvider', 'npu-candidate': 'VitisAIExecutionProvider'}
MAX_RECORD = 1_048_576


class ProbeError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def artifact(directory, name, kind='OTHER'):
    return {'path': name, 'kind': kind, 'sha256': digest(regular_bytes(directory / name, 16 * MAX_RECORD))}


def save(directory, name, raw):
    reference._write(directory / name, lambda stream: stream.write(raw))


def base_record(job):
    schema = json.loads((ROOT / 'schemas/hardware-evidence.schema.json').read_text())
    record = {key: None for key in schema['required']}
    record.update(schema_version='1.0.0', document_type='docksr_hardware_evidence',
                  record_purpose='MEASUREMENT', target='Ryzen AI Z2 Extreme / XDNA2',
                  runtime_state='ERROR', evidence='NONE', backend_kind='UNKNOWN',
                  execution_environment='HOST_ONLY', timestamp=datetime.now(timezone.utc).isoformat(),
                  last_error={'code': 'NOT_COMPLETED', 'message': 'No accepted H1 execution result.'})
    record['h1_run'] = {
        'run_id': job['run_id'], 'mode': job['mode'], 'configuration_generation': job['generation'],
        'first_frame_id': job['frame_id'], 'requested_provider': PROVIDERS[job['mode']],
        'available_providers': [], 'active_providers': [], 'model_verified': False,
        'input_fixture': {'algorithm': 'RGB8_ARANGE37_PLUS_SEED_MOD256_V1', 'seed': job['seed']},
        'input_dtype': 'int8', 'output_dtype': 'int8', 'layout': 'NHWC',
        'environment_fingerprint': None, 'preflight_ref': None, 'h0_review_sha256': None,
        'cache_policy': 'NEW_PER_RUN', 'cache_identity': None,
        'provider_options': {}, 'classification': 'BLOCKED',
        'provider_discovered': False, 'provider_session_created': False,
        'npu_placement_evidence_present': False, 'active_xrt_context_evidence_present': False,
        'cpu_reference_agreement_pass': False, 'real_npu_verified': False,
        'placement_status': 'NOT_RUN', 'context_status': 'NOT_RUN',
        'placement_refs': [], 'context_refs': [],
        'comparison': {'atol': 0, 'rtol': 0, 'max_abs_error': None,
                       'compared_samples': 0, 'cpu_repeats_equal': None,
                       'input_sha256': None, 'output_sha256': None, 'reference_sha256': None, 'decoded_rgb8_sha256': None},
        'phase_ms': {key: None for key in ('model_validation', 'input_preparation', 'session_initialization',
                        'compilation', 'cache_loading', 'warmup', 'cpu_reference_initialization',
                        'cpu_reference_execution', 'output_processing', 'cpu_comparison',
                        'host_staging', 'provider_kernel', 'artifact_writing', 'evidence_serialization')},
        'timing_scope': 'HOST_REQUEST_INCLUDING_RUNTIME_STAGING_NOT_NPU_KERNEL',
        'verification_policy': 'FAIL_CLOSED_PENDING_DEVICE_REPORT_ADAPTERS',
    }
    return record


def deterministic_input(np, seed):
    rgb = ((np.arange(math.prod(INPUT), dtype=np.int64).reshape(INPUT) * 37 + seed) % 256).astype(np.uint8)
    return np.ascontiguousarray((rgb.astype(np.int16) - 128).astype(np.int8))


class PersistentTileSession:
    """Reusable single-request session/buffer boundary for a later H2 assembler.

    Caller owns frame IDs, generations and buffer lifetime; no concurrency or
    presentation is added. CPU policy/inspection are reused without alteration.
    """
    def __init__(self, model, mode):
        if mode not in PROVIDERS:
            raise ProbeError('INVALID_MODE')
        raw, model_hash = import_sesr._read_verified(import_sesr._absolute(model), import_sesr.PINNED_IDENTITY)
        self.mode, self.model_hash = mode, model_hash
        self.reference = reference.CpuReferenceSession(model, layout='NHWC', initialize=False)
        r = self.reference
        if (digest(r.model_bytes) != digest(raw) or r.input_shape != INPUT or r.output_shape != OUTPUT or
                str(r.input_dtype) != 'int8' or str(r.output_dtype) != 'int8'):
            raise ProbeError('MODEL_SIGNATURE_MISMATCH')
        self.available = r.ort.get_available_providers()
        if any(steamos_readiness.token(p) is None for p in self.available) or len(self.available) > 128:
            raise ProbeError('INVALID_PROVIDER_METADATA')
        self.session = None
        self.binding = None
        self.bound_buffers = None

    def initialize(self, directory):
        r = self.reference
        provider = PROVIDERS[self.mode]
        if provider not in self.available:
            raise ProbeError('REQUESTED_PROVIDER_MISSING')
        if self.session is not None:
            return
        if self.mode == 'cpu-reference':
            r.initialize()
            self.session = r.session
        else:
            try:
                options = r.ort.SessionOptions()
                options.intra_op_num_threads = options.inter_op_num_threads = 1
                options.add_session_config_entry('session.disable_cpu_ep_fallback', '1')
                options.log_severity_level = 3
                cache = directory / 'cache'
                cache.mkdir(mode=0o700)
                os.environ['XLNX_ONNX_EP_REPORT_FILE'] = str(directory / 'vitis-placement.json')
                provider_options = {'target': 'X2', 'cache_dir': str(cache), 'cache_key': self.model_hash,
                                    'enable_cache_file_io_in_mem': '0'}
                self.session = r.ort.InferenceSession(r.model_bytes, sess_options=options,
                    providers=[provider], provider_options=[provider_options])
                self.session.disable_fallback()
            except Exception as error:
                raise ProbeError('REQUESTED_PROVIDER_SESSION_UNAVAILABLE') from error
        self.check_provider()
        inputs, outputs = self.session.get_inputs(), self.session.get_outputs()
        if (len(inputs) != 1 or len(outputs) != 1 or inputs[0].name != r.inputs[0]['name'] or
                outputs[0].name != r.outputs[0]['name'] or tuple(inputs[0].shape) != INPUT or
                tuple(outputs[0].shape) != OUTPUT or inputs[0].type != 'tensor(int8)' or outputs[0].type != 'tensor(int8)'):
            raise ProbeError('RUNTIME_SIGNATURE_MISMATCH')

    def check_provider(self):
        active = self.session.get_providers()
        expected = PROVIDERS[self.mode]
        if expected not in active or active[0] != expected or (self.mode == 'cpu-reference' and active != [expected]):
            raise ProbeError('UNEXPECTED_PROVIDER_FALLBACK')
        return active

    def run(self, tensor, output):
        r, np = self.reference, self.reference.np
        reference._validate_array(np, tensor, INPUT, np.dtype('int8'), 'Input')
        if (not isinstance(output, np.ndarray) or not tensor.flags.c_contiguous or output.shape != OUTPUT or output.dtype != np.dtype('int8') or
                not output.flags.c_contiguous or not output.flags.writeable or np.may_share_memory(tensor, output)):
            raise ProbeError('TENSOR_SIGNATURE_MISMATCH')
        self.check_provider()
        if self.mode == 'cpu-reference':
            r.run(tensor, output)
        else:
            if self.binding is None or self.bound_buffers != (tensor.ctypes.data, output.ctypes.data):
                self.binding = self.session.io_binding()
                self.binding.bind_cpu_input(r.inputs[0]['name'], tensor)
                self.binding.bind_output(r.outputs[0]['name'], device_type='cpu', device_id=0,
                    element_type=np.int8, shape=OUTPUT, buffer_ptr=output.ctypes.data)
                self.bound_buffers = (tensor.ctypes.data, output.ctypes.data)
            try:
                self.session.run_with_iobinding(self.binding)
            except Exception as error:
                raise ProbeError('CANDIDATE_INFERENCE_FAILED') from error
        self.check_provider()
        reference._validate_array(np, output, OUTPUT, np.dtype('int8'), 'Output')
        return output

    def close(self):
        self.binding = self.bound_buffers = self.session = None
        self.reference.session = None


def approved_host(job, preflight):
    if not job['approve_physical_run'] or not job['readiness']:
        raise ProbeError('PHYSICAL_EXECUTION_NOT_APPROVED')
    raw = regular_bytes(Path(job['readiness']), MAX_RECORD)
    reviewed = json.loads(raw, object_pairs_hook=_pairs)
    steamos_readiness.validate(reviewed)
    if (reviewed['evidence_class'] != 'DEVICE_INVENTORY' or reviewed['physical_test_status'] != 'OBSERVED_ON_DEVICE' or
            reviewed['os_family'] != 'STEAMOS' or reviewed['gates']['H0']['status'] != 'PASS' or
            reviewed['inventory'] != preflight['inventory']):
        raise ProbeError('HOST_READINESS_UNREVIEWED_OR_CHANGED')
    if not any(pci['driver'] == 'amdxdna' for pci in preflight['inventory']['pci']):
        raise ProbeError('TARGET_DRIVER_NOT_BOUND')
    return digest(raw)


def start_context(directory, enabled):
    if not enabled:
        return None, 'NOT_RUN'
    try:
        fd = os.open(directory / 'xrt-context.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            child = subprocess.Popen(['xrt-smi', 'examine', '--report', 'aie-partitions', '--format', 'JSON'],
                stdout=stream, stderr=subprocess.DEVNULL)
        return child, 'PENDING'
    except FileNotFoundError:
        return None, 'MISSING_TOOL'


def execute(job, directory, record):
    h = record['h1_run']
    started = time.perf_counter_ns()
    # Verify pin before importing optional inference dependencies.
    try:
        raw, model_hash = import_sesr._read_verified(import_sesr._absolute(job['model']), import_sesr.PINNED_IDENTITY)
    except FileNotFoundError as error:
        raise ProbeError('MODEL_MISSING') from error
    h['model_verified'] = True
    h['phase_ms']['model_validation'] = (time.perf_counter_ns() - started) / 1e6
    record.update(model_id=import_sesr.PINNED_IDENTITY.model_id, model_sha256=model_hash,
                  input_shape=list(INPUT), output_shape=list(OUTPUT))
    preflight = steamos_readiness.discover()
    steamos_readiness.validate(preflight)
    npu_probe.write_new_private(directory / 'preflight.json', preflight)
    h['environment_fingerprint'] = fingerprint(preflight['inventory'])
    h['preflight_ref'] = artifact(directory, 'preflight.json')
    if job['mode'] == 'npu-candidate':
        h['h0_review_sha256'] = approved_host(job, preflight)
        record['execution_environment'] = 'TARGET_PHYSICAL'
    runtime = PersistentTileSession(job['model'], job['mode'])
    cpu = None
    context = None
    try:
        r, np = runtime.reference, runtime.reference.np
        record['runtime_version'] = steamos_readiness.token(r.ort.__version__)
        h['available_providers'] = runtime.available
        h['provider_discovered'] = PROVIDERS[job['mode']] in runtime.available
        if not h['provider_discovered']:
            raise ProbeError('REQUESTED_PROVIDER_MISSING')
        h['cache_identity'] = fingerprint({'model': model_hash, 'runtime': record['runtime_version'],
                                         'host': h['environment_fingerprint'], 'target': 'X2'}) if job['mode'] == 'npu-candidate' else None
        h['provider_options'] = {'target': 'X2', 'cache_dir': 'cache', 'cache_key': model_hash,
            'enable_cache_file_io_in_mem': '0', 'session.disable_cpu_ep_fallback': '1'} if job['mode'] == 'npu-candidate' else {}
        started = time.perf_counter_ns()
        runtime.initialize(directory)
        h['phase_ms']['session_initialization'] = (time.perf_counter_ns() - started) / 1e6
        h['provider_session_created'] = True
        h['active_providers'] = runtime.check_provider()
        started = time.perf_counter_ns()
        tensor = deterministic_input(np, job['seed'])
        output, golden = np.empty(OUTPUT, dtype=np.int8), np.empty(OUTPUT, dtype=np.int8)
        input_hash = digest(tensor.tobytes())
        h['comparison']['input_sha256'] = input_hash
        h['phase_ms']['input_preparation'] = (time.perf_counter_ns() - started) / 1e6
        started = time.perf_counter_ns()
        for _ in range(job['warmup']): runtime.run(tensor, output)
        h['phase_ms']['warmup'] = (time.perf_counter_ns() - started) / 1e6
        # Separately initialized/executed CPU baseline; not a cached candidate.
        started = time.perf_counter_ns()
        cpu = reference.CpuReferenceSession(job['model'], layout='NHWC')
        h['phase_ms']['cpu_reference_initialization'] = (time.perf_counter_ns() - started) / 1e6
        if digest(cpu.model_bytes) != model_hash: raise ProbeError('MODEL_CHANGED')
        started = time.perf_counter_ns()
        cpu.run(tensor, golden)
        golden_hash = digest(golden.tobytes())
        cpu.run(tensor, golden)
        if digest(golden.tobytes()) != golden_hash: raise ProbeError('CPU_REPEAT_MISMATCH')
        h['phase_ms']['cpu_reference_execution'] = (time.perf_counter_ns() - started) / 1e6
        h['comparison']['cpu_repeats_equal'] = True
        context, h['context_status'] = start_context(directory, job['collect_xrt_context'])
        frames, durations = [], []
        comparison_ns = output_ns = 0
        maximum = 0
        observation_start = time.perf_counter_ns()
        for index in range(job['samples']):
            begin = time.perf_counter_ns()
            runtime.run(tensor, output)
            completed = time.perf_counter_ns()
            difference = np.abs(output.astype(np.int16) - golden.astype(np.int16))
            error = int(difference.max())
            maximum = max(maximum, error)
            h['comparison']['max_abs_error'] = maximum
            if error: raise ProbeError('CPU_REFERENCE_MISMATCH')
            if digest(tensor.tobytes()) != input_hash: raise ProbeError('INPUT_MUTATED')
            validated = time.perf_counter_ns()
            comparison_ns += validated - completed
            decoded = np.clip(output.astype(np.int16) + 128, 0, 255).astype(np.uint8)
            processed = time.perf_counter_ns()
            output_ns += processed - validated
            durations.append((completed - begin) / 1e6)
            frames.append({'frame_id': job['frame_id'] + index, 'configuration_generation': job['generation'],
                'submitted_ns': begin, 'started_ns': begin, 'completed_ns': completed,
                'validated_ns': validated, 'consumed_ns': processed, 'presented_ns': None,
                'cancelled_ns': None, 'deadline_ns': job['deadline_ns'],
                'completed_tiles': 1, 'validated_tiles': 1, 'fallback': False, 'dropped': False})
        observation_end = time.perf_counter_ns()
        if context is not None:
            try:
                status = context.wait(timeout=10)
                h['context_status'] = 'RAW_UNVERIFIED' if status == 0 else 'COMMAND_FAILED'
            except subprocess.TimeoutExpired:
                context.kill(); context.wait(timeout=2)
                h['context_status'] = 'TIMEOUT'
        if h['context_status'] == 'RAW_UNVERIFIED':
            h['context_refs'] = [artifact(directory, 'xrt-context.json')]
        if (directory / 'vitis-placement.json').exists():
            h['placement_refs'] = [artifact(directory, 'vitis-placement.json', 'OPERATOR_ASSIGNMENT')]
            h['placement_status'] = 'RAW_UNVERIFIED'
        h['comparison'].update(compared_samples=len(frames), max_abs_error=maximum,
            output_sha256=digest(output.tobytes()), reference_sha256=golden_hash,
            decoded_rgb8_sha256=digest(decoded.tobytes()))
        h['cpu_reference_agreement_pass'] = True
        h['phase_ms'].update(cpu_comparison=comparison_ns / 1e6, output_processing=output_ns / 1e6)
        started = time.perf_counter_ns()
        for name, array in (('input.raw', tensor), ('output.raw', output), ('cpu-reference.raw', golden), ('output-rgb8.raw', decoded)):
            save(directory, name, array.tobytes())
        save(directory, 'samples.json', (json.dumps({'clock': 'HOST_MONOTONIC', 'unit': 'ns', 'frames': frames}) + '\n').encode())
        h['phase_ms']['artifact_writing'] = (time.perf_counter_ns() - started) / 1e6
        samples_ref = artifact(directory, 'samples.json', 'RAW_SAMPLES')
        record.update(backend_name=PROVIDERS[job['mode']], warmup_count=job['warmup'],
            sample_count=len(durations), samples_ms=durations, successful_runs=len(durations), failed_runs=0,
            measurement_provenance={'collector': 'docksr-h1-probe', 'collector_version': '1.0.0',
                'clock': 'HOST_MONOTONIC', 'timing_scope': 'PIPELINE', 'warmups_excluded': True, 'evidence_refs': [samples_ref]})
        ordered = sorted(durations)
        for percent, field in ((50, 'p50'), (95, 'p95'), (99, 'p99')):
            record['npu_or_pipeline_ms_' + field] = ordered[math.ceil(len(ordered) * percent / 100) - 1]
        inventory = preflight['inventory']
        platform = {'device': 'UNVERIFIED_APU_IDENTITY', 'os': json.dumps(inventory['os']['fields'], sort_keys=True),
                    'kernel': inventory['kernel_release'] or 'UNKNOWN', 'software': 'ORT ' + (record['runtime_version'] or 'UNKNOWN'),
                    'drivers': json.dumps(inventory['amdxdna'], sort_keys=True)}
        record['benchmark_run'] = {'experiment_id': 'H1_SINGLE_TILE_LAB', 'run_id': job['run_id'],
            'session_id': job['run_id'], 'pair_id': job['run_id'], 'comparison_role': 'BASELINE',
            'condition_id': job['mode'], 'platform': platform, 'source_extent': {'width': 256, 'height': 256},
            'output_extent': {'width': 512, 'height': 512}, 'tensor': {'layout': 'NHWC', 'dtype': 'int8'},
            'clock_domain': 'HOST_MONOTONIC', 'time_unit': 'ns', 'observation_start_ns': observation_start,
            'observation_end_ns': observation_end, 'configured_power_limit_w': None, 'power_profile': 'UNMEASURED_UNCHANGED',
            'presentation_status': 'NOT_RUN', 'expected_tiles_per_frame': 1, 'frames': frames,
            'power': None, 'raw_evidence_refs': [samples_ref]}
        if job['mode'] == 'cpu-reference':
            h['classification'] = 'CPU_REFERENCE_PASS'
            record.update(runtime_state='CPU_REFERENCE_ACTIVE', evidence='REAL_CPU', backend_kind='CPU', last_error=None,
                model_validation={'status': 'VALIDATED', 'correct_output': True, 'non_identity': True,
                    'input_sha256': input_hash, 'cpu_reference_sha256': golden_hash, 'npu_output_sha256': None,
                    'comparison': {'method': 'max_abs_error', 'atol': 0, 'rtol': 0, 'max_abs_error': maximum, 'passed': True},
                    'evidence_refs': [artifact(directory, 'cpu-reference.raw', 'CPU_REFERENCE')]})
        else:
            # Formats/attribution must be validated on the installed device, not
            # guessed from file existence, provider metadata or a test fixture.
            h['classification'] = 'INCONCLUSIVE'
            record['last_error'] = {'code': 'PHYSICAL_EVIDENCE_UNVERIFIED',
                                    'message': 'Placement/context artifacts require validated device-specific review; no NPU attestation.'}
    finally:
        if context is not None and context.poll() is None:
            context.kill(); context.wait(timeout=2)
        runtime.close()
        if cpu is not None: cpu.session = None


def worker(job, directory):
    os.umask(0o077)
    record = base_record(job)
    try:
        execute(job, directory, record)
    except (reference.ReferenceError, import_sesr.ImportFailure, OSError, ValueError, RuntimeError) as error:
        code = getattr(error, 'code', 'RUNTIME_OR_EVIDENCE_UNAVAILABLE')
        if not isinstance(code, str) or len(code) > 64: code = 'RUNTIME_OR_EVIDENCE_UNAVAILABLE'
        failure = code in ('CPU_REFERENCE_MISMATCH', 'INPUT_MUTATED', 'CPU_REPEAT_MISMATCH',
                           'TENSOR_SIGNATURE_MISMATCH', 'UNEXPECTED_PROVIDER_FALLBACK', 'RUNTIME_SIGNATURE_MISMATCH',
                           'CANDIDATE_INFERENCE_FAILED')
        record['h1_run']['classification'] = 'FAILED' if failure else 'BLOCKED'
        record['last_error'] = {'code': code, 'message': 'H1 execution did not satisfy the declared gates; raw exception text excluded.'}
    validate_record(record, 'hardware')
    if record.get('benchmark_run') is not None:
        from benchmark_analysis import analyze
        analyze(record)
    npu_probe.write_new_private(directory / 'worker-evidence.json', record)
    return {'CPU_REFERENCE_PASS': 0, 'BLOCKED': 2, 'INCONCLUSIVE': 3, 'FAILED': 1}[record['h1_run']['classification']]


def stop(child):
    if child.poll() is not None:
        # Compiler descendants may remain even if the direct worker exited.
        try: os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        return
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        try: child.wait(timeout=2)
        except subprocess.TimeoutExpired: raise ProbeError('WORKER_QUIESCENCE_UNCONFIRMED')
    try: os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError: pass


def supervise(job, directory):
    directory = import_sesr._absolute(directory)
    import_sesr._check_parents(directory.parent, reject_git=True)
    info = directory.parent.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProbeError('OUTPUT_PARENT_NOT_PRIVATE')
    directory.mkdir(mode=0o700)
    job['deadline_ns'] = time.perf_counter_ns() + int(job['timeout'] * 1e9)
    save(directory, 'job.json', (json.dumps(job, allow_nan=False) + '\n').encode())
    child = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), '--worker', str(directory / 'job.json')],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    error, code = None, 1
    try:
        code = child.wait(timeout=max(0, (job['deadline_ns'] - time.perf_counter_ns()) / 1e9))
    except subprocess.TimeoutExpired:
        error, code = 'TOTAL_TIMEOUT', 124
    except KeyboardInterrupt:
        error, code = 'INTERRUPTED', 130
    finally:
        stop(child)
    path = directory / 'worker-evidence.json'
    if error or not path.exists():
        if error is None: code = 1
        if path.exists(): path.rename(directory / 'unaccepted-worker-report.json')
        record = base_record(job)
        record['h1_run']['classification'] = 'FAILED'
        record['last_error'] = {'code': error or 'WORKER_FAILED', 'message': 'Worker did not deliver an accepted result; no inference success is inferred.'}
        validate_record(record, 'hardware')
    else:
        record = json.loads(regular_bytes(path, MAX_RECORD), object_pairs_hook=_pairs)
    validate_record(record, 'hardware')
    if (record['h1_run']['run_id'] != job['run_id'] or record['h1_run']['mode'] != job['mode'] or
            (code == 0) != (record['h1_run']['classification'] == 'CPU_REFERENCE_PASS')):
        raise ProbeError('WORKER_RECEIPT_MISMATCH')
    if record['h1_run']['classification'] in ('CPU_REFERENCE_PASS', 'INCONCLUSIVE'):
        c = record['h1_run']['comparison']
        inp = regular_bytes(directory / 'input.raw', math.prod(INPUT))
        out = regular_bytes(directory / 'output.raw', math.prod(OUTPUT))
        golden = regular_bytes(directory / 'cpu-reference.raw', math.prod(OUTPUT))
        rgb = regular_bytes(directory / 'output-rgb8.raw', math.prod(OUTPUT))
        expected_input = bytes(((i * 37 + job['seed']) % 256) ^ 128 for i in range(math.prod(INPUT)))
        translation = bytes(value ^ 128 for value in range(256))
        if (inp != expected_input or len(out) != math.prod(OUTPUT) or out != golden or rgb != out.translate(translation) or
                any(digest(raw) != c[key] for raw, key in ((inp, 'input_sha256'), (out, 'output_sha256'),
                    (golden, 'reference_sha256'), (rgb, 'decoded_rgb8_sha256')))):
            raise ProbeError('WORKER_ARTIFACT_MISMATCH')
        trace = json.loads(regular_bytes(directory / 'samples.json', MAX_RECORD), object_pairs_hook=_pairs)
        if trace['frames'] != record['benchmark_run']['frames']:
            raise ProbeError('WORKER_TRACE_MISMATCH')
    # Only the reaping/validation supervisor publishes an accepted final record.
    npu_probe.write_new_private(directory / 'hardware-evidence.json', record)
    return code, record


def main(argv=None):
    if argv is None and len(sys.argv) == 3 and sys.argv[1] == '--worker':
        path = Path(sys.argv[2])
        return worker(json.loads(regular_bytes(path, 16384), object_pairs_hook=_pairs), path.parent)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True, help='NEW directory outside Git; parent owner-controlled0700')
    parser.add_argument('--mode', choices=PROVIDERS, default='cpu-reference')
    parser.add_argument('--warmup', type=int, default=1)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--timeout', type=float, default=60, help='Overall worker deadline in seconds, includes compilation/reference/artifacts')
    parser.add_argument('--frame-id', type=int, default=1)
    parser.add_argument('--generation', type=int, default=1)
    parser.add_argument('--readiness', type=Path, help='Reviewed matching SteamOS H0 ledger, required for NPU candidate')
    parser.add_argument('--approve-physical-run', action='store_true', help='Use only after separate owner review/approval of this exact active test')
    parser.add_argument('--collect-xrt-context', action='store_true', help='Approved raw aie-partitions query; may include context/process identifiers, no automatic interpretation')
    args = parser.parse_args(argv)
    previous = signal.getsignal(signal.SIGTERM)
    try:
        if (os.geteuid() == 0 or not 1 <= args.warmup <= 10 or not 2 <= args.samples <= 1000 or
                not 0 <= args.seed < 2**32 or not math.isfinite(args.timeout) or not 1 <= args.timeout <= 600 or
                not 1 <= args.generation < 2**64 or not 1 <= args.frame_id <= 2**64 - args.samples or
                (args.collect_xrt_context and args.mode != 'npu-candidate')):
            raise ProbeError('INVALID_BOUNDS_OR_EXECUTION_MODE')
        try:
            import jsonschema  # Required for evidence validation; no provider import.
        except ImportError as error:
            raise ProbeError('SCHEMA_DEPENDENCY_MISSING') from error
        job = {key: value for key, value in vars(args).items() if key != 'output_dir'}
        job['model'] = str(import_sesr._absolute(args.model))
        job['readiness'] = str(import_sesr._absolute(args.readiness)) if args.readiness else None
        job['run_id'] = 'h1-' + uuid.uuid4().hex
        def interrupt(_signum, _frame): raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)
        code, record = supervise(job, args.output_dir)
        print(json.dumps({'classification': record['h1_run']['classification'], 'evidence': record['evidence'],
                          'error_code': (record['last_error'] or {}).get('code'), 'real_npu_verified': False}, sort_keys=True))
        return code
    except ProbeError as error:
        failed = error.code.startswith('WORKER_')
        print(json.dumps({'classification': 'FAILED' if failed else 'BLOCKED', 'error_code': error.code, 'real_npu_verified': False}))
        return 1 if failed else 2
    except (OSError, ValueError, ImportError, RecursionError):
        print(json.dumps({'classification': 'BLOCKED', 'error_code': 'INVALID_INPUT_OR_PRIVATE_OUTPUT', 'real_npu_verified': False}))
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
