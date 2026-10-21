#!/usr/bin/env python3
"""Offline lifecycle/power analysis of the existing hardware-evidence contract.

No collection or execution occurs. Validating supplied evidence is not an
attestation of physical execution, placement, presentation or image quality.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics

from frame_payload import UINT64_MAX, _multiply
from npu_probe import write_new_private
from validate_gate0 import _pairs, validate_record

STAGES = ('submitted_ns', 'started_ns', 'completed_ns', 'validated_ns',
          'consumed_ns', 'presented_ns')
MAX_RECORD_BYTES = 16 * 1024 * 1024


def read_record(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError('Benchmark record exceeds 16 MiB')
    return json.loads(data, object_pairs_hook=_pairs)


def distribution(values):
    ordered = sorted(values)
    result = {'count': len(values), 'unit': 'ms', 'min': min(values, default=None),
              'max': max(values, default=None), 'percentile_method': 'NEAREST_RANK',
              'insufficient_samples': []}
    for label, percent, minimum in [('p50', 50, 2), ('p95', 95, 20), ('p99', 99, 100)]:
        result[label] = ordered[math.ceil(percent * len(ordered) / 100) - 1] if len(ordered) >= minimum else None
        if len(ordered) < minimum:
            result['insufficient_samples'].append(label)
    return result


def energy(power, start, end, clock, presented, presentation_status):
    result = {'status': 'UNAVAILABLE', 'reason': None, 'scope': None,
              'energy_j': None, 'energy_per_presented_frame_j': None,
              'energy_per_frame_reason': None, 'method': 'TRAPEZOID_LINEAR_EDGE_INTERPOLATION'}
    if power is None:
        result['reason'] = 'MISSING_SENSOR'
        return result
    result['scope'] = power['scope']
    samples = power['samples']
    times = [x['timestamp_ns'] for x in samples]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Power timestamps must increase strictly')
    for key, condition in [('UNKNOWN_SCOPE', power['scope'] == 'UNKNOWN'),
                           ('UNKNOWN_SENSOR_SOURCE', power['sensor_source'] is None),
                           ('CLOCK_UNALIGNED', power['clock_domain'] != clock),
                           ('BATTERY_COMPARISON_INCONCLUSIVE', power['battery_state'] != 'STABLE_AC'),
                           ('INSUFFICIENT_POWER_COVERAGE', len(samples) < 2 or not times or times[0] > start or times[-1] < end)]:
        if condition:
            result['reason'] = key
            return result
    joules = 0.0
    for left, right in zip(samples, samples[1:]):
        a, b = left['timestamp_ns'], right['timestamp_ns']
        lo, hi = max(a, start), min(b, end)
        if hi <= lo:
            continue
        if b - a > power['max_gap_ns']:
            result['reason'] = 'INSUFFICIENT_POWER_COVERAGE'
            return result
        slope = (right['watts'] - left['watts']) / (b - a)
        watts_lo = left['watts'] + slope * (lo - a)
        watts_hi = left['watts'] + slope * (hi - a)
        joules += (watts_lo + watts_hi) * 0.5 * ((hi - lo) / 1e9)
    result.update(status='CALCULATED_FROM_SUPPLIED_SAMPLES', energy_j=joules)
    if presentation_status != 'RECORDED':
        result['energy_per_frame_reason'] = 'PRESENTATION_UNKNOWN_OR_NOT_RUN'
    elif not presented:
        result['energy_per_frame_reason'] = 'ZERO_VALID_PRESENTED_FRAMES'
    else:
        result['energy_per_presented_frame_j'] = joules / presented
    return result


def analyze(record):
    validate_record(record, 'hardware')  # Reuse evidence/backend/placement guards.
    run = record.get('benchmark_run')
    if not isinstance(run, dict):
        raise ValueError('A benchmark_run extension is required')
    if record['model_id'] is None or record['model_sha256'] is None:
        raise ValueError('Benchmark model identity is required')
    for shape in (record['input_shape'], record['output_shape']):
        if shape is None or len(shape) != 4 or shape[0] != 1:
            raise ValueError('Benchmark requires batch-one rank-four tensors')
        channel_axis = 1 if run['tensor']['layout'] == 'NCHW' else 3
        if shape[channel_axis] not in (3, 4):
            raise ValueError('Declared RGB/RGBA tensor layout disagrees with shape')
        size = 4 if run['tensor']['dtype'] == 'float32' else 1
        for dimension in shape:
            if type(dimension) is not int or not 1 <= dimension <= 8192:
                raise ValueError('Tensor dimension outside 1..8192')
            size = _multiply(size, dimension, 'Tensor bytes')
    start, end = run['observation_start_ns'], run['observation_end_ns']
    if end <= start:
        raise ValueError('Observation interval must increase')
    frames, seen, queue_events = run['frames'], set(), defaultdict(int)
    counts = {stage[:-3].upper(): 0 for stage in STAGES}
    inference_ms, presented_times = [], []
    complete_frames = validated_frames = tiles = misses = due = 0
    for frame in frames:
        # One session per run, matching Worker: frame IDs do not reset on a
        # configuration change. Re-labelling a generation cannot count twice.
        identity = frame['frame_id']
        if identity in seen:
            raise ValueError('Duplicate frame identity')
        seen.add(identity)
        previous, stopped = None, False
        for stage in STAGES:
            t = frame[stage]
            if t is None:
                stopped = True
                continue
            if stopped or not start <= t <= end or (previous is not None and t < previous):
                raise ValueError('Invalid lifecycle prefix, timestamp ordering or observation bounds')
            previous = t
            counts[stage[:-3].upper()] += 1
        if frame['submitted_ns'] is None or frame['deadline_ns'] <= frame['submitted_ns']:
            raise ValueError('Frame requires submission and a later deadline')
        cancel = frame['cancelled_ns']
        if cancel is not None and (frame['started_ns'] is not None or not frame['submitted_ns'] <= cancel <= end
                                   or not (frame['dropped'] or frame['fallback'])):
            raise ValueError('Cancellation must terminate an unstarted dropped/fallback request')
        queue_events[frame['submitted_ns']] += 1
        if frame['started_ns'] is not None:
            queue_events[frame['started_ns']] -= 1
        elif cancel is not None:
            queue_events[cancel] -= 1
        expected = run['expected_tiles_per_frame']
        if not 0 <= frame['validated_tiles'] <= frame['completed_tiles'] <= expected:
            raise ValueError('Invalid tile completion/validation counts')
        if frame['started_ns'] is None and frame['completed_tiles']:
            raise ValueError('Tile completion before execution')
        if frame['dropped'] and frame['presented_ns'] is not None:
            raise ValueError('Dropped frame cannot be presented')
        if frame['validated_ns'] is not None and not frame['fallback'] and frame['validated_tiles'] != expected:
            raise ValueError('Validated neural frame is missing tiles')
        if run['presentation_status'] != 'RECORDED' and frame['presented_ns'] is not None:
            raise ValueError('Unrecorded presentation cannot contain presented events')
        tiles += frame['completed_tiles']
        if tiles > UINT64_MAX:
            raise ValueError('Tile accounting overflow')
        if frame['completed_ns'] is not None:
            if not frame['fallback']:
                inference_ms.append((frame['completed_ns'] - frame['started_ns']) / 1e6)
            complete_frames += int(frame['completed_tiles'] == expected and not frame['fallback'])
        validated_frames += int(frame['validated_ns'] is not None and not frame['fallback'])
        if frame['presented_ns'] is not None:
            presented_times.append(frame['presented_ns'])
        if frame['deadline_ns'] <= end:
            due += 1
            misses += int(frame['completed_ns'] is None or frame['completed_ns'] >= frame['deadline_ns'])
    queued = peak = 0
    for t in sorted(queue_events):
        queued += queue_events[t]  # Simultaneous events are combined, no invented sub-tick ordering.
        if queued < 0:
            raise ValueError('Queue underflow')
        peak = max(peak, queued)
    presented_times.sort()
    intervals_ms = [(b - a) / 1e6 for a, b in zip(presented_times, presented_times[1:])]
    if any(value <= 0 for value in intervals_ms):
        raise ValueError('Presentation timestamps must be distinct')
    seconds = (end - start) / 1e9
    recorded = run['presentation_status'] == 'RECORDED'
    if not recorded:
        counts['PRESENTED'] = None
    slow = sorted(intervals_ms, reverse=True)[:math.ceil(len(intervals_ms) / 100)]
    low = 1000 / statistics.mean(slow) if len(intervals_ms) >= 100 else None
    result = {
        'schema_version': '1.0.0', 'document_type': 'docksr_benchmark_analysis',
        'experiment_id': run['experiment_id'], 'run_id': run['run_id'],
        'evidence': 'SIMULATED' if record['record_purpose'] == 'SCHEMA_EXAMPLE' else record['evidence'],
        'actual_backend': record['backend_kind'], 'hardware_execution_attested': False,
        'presentation_status': run['presentation_status'],
        'observation_seconds': seconds, 'lifecycle_counts': counts,
        'completed_full_frames_per_s': complete_frames / seconds,
        'validated_full_frames_per_s': validated_frames / seconds,
        'tile_completions_per_s': tiles / seconds,
        'presented_frames_per_s': len(presented_times) / seconds if recorded else None,
        'frame_time_ms': distribution(intervals_ms), 'inference_latency_ms': distribution(inference_ms),
        'inference_latency_scope': 'NONFALLBACK_REQUEST_START_TO_COMPLETION_HOST_CLOCK',
        'one_percent_low_fps': low, 'one_percent_low_definition': '1000 / mean(slowest ceil(N*0.01) presentation intervals in ms); minimum N=100',
        'queue_final_depth': queued, 'queue_growth_per_s': queued / seconds, 'queue_max_depth': peak,
        'deadline_due_requests': due, 'deadline_misses': misses,
        'deadline_miss_rate': misses / due if due else None,
        'dropped_frames': sum(x['dropped'] for x in frames), 'fallback_frames': sum(x['fallback'] for x in frames),
        'power': energy(run['power'], start, end, run['clock_domain'], len(presented_times), run['presentation_status']),
        'raw_evidence_refs': run['raw_evidence_refs'],
        'limitations': ['Supplied evidence is not independently attested.',
                       'Neural throughput excludes fallback; valid presented counts include declared fallback.',
                       'Frame-time distribution uses consecutive presentation intervals, not render-service duration.',
                       'No timestamps from different clock domains are subtracted.',
                       'Configured power limits are metadata, not measured watts.'],
    }
    return result


def compare_pairs(pairs):
    """Paired run differences, never averages of percentiles labelled as pooled."""
    rows, seen, run_ids, conditions = [], set(), set(), None
    for baseline, experiment in pairs:
        left, right = analyze(baseline), analyze(experiment)
        a, b = baseline['benchmark_run'], experiment['benchmark_run']
        if a['comparison_role'] != 'BASELINE' or b['comparison_role'] != 'EXPERIMENTAL' or a['pair_id'] != b['pair_id']:
            raise ValueError('Expected matching baseline/experimental pair')
        if a['pair_id'] in seen:
            raise ValueError('Duplicate pair ID')
        seen.add(a['pair_id'])
        if a['run_id'] == b['run_id'] or a['run_id'] in run_ids or b['run_id'] in run_ids:
            raise ValueError('Paired runs must have distinct unreused run IDs')
        run_ids.update((a['run_id'], b['run_id']))
        keys = ('condition_id', 'platform', 'source_extent', 'output_extent', 'power_profile', 'configured_power_limit_w')
        signature = {key: a[key] for key in keys}
        if signature != {key: b[key] for key in keys} or (conditions is not None and signature != conditions):
            raise ValueError('Paired comparison conditions differ')
        conditions = signature
        power_a, power_b = a['power'], b['power']
        same_sensor = power_a is not None and power_b is not None and all(power_a[k] == power_b[k] for k in ('scope', 'sensor_source', 'battery_state'))
        energy_a = left['power']['energy_per_presented_frame_j']
        energy_b = right['power']['energy_per_presented_frame_j']
        fps_a, fps_b = left['presented_frames_per_s'], right['presented_frames_per_s']
        rows.append({'pair_id': a['pair_id'],
                     'baseline_evidence': left['evidence'], 'experimental_evidence': right['evidence'],
                     'presented_fps_delta': fps_b - fps_a if fps_a is not None and fps_b is not None else None,
                     'energy_per_frame_j_delta': energy_b - energy_a if same_sensor and energy_a is not None and energy_b is not None else None})
    if not rows:
        raise ValueError('At least one pair required')
    # Conservative two-sided Student-t 95% critical values for <=30 independent
    # pairs. Larger sets use the df30 bound rather than understate uncertainty.
    critical = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
                2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101,
                2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052,
                2.048, 2.045, 2.042)
    summaries = {}
    for metric in ('presented_fps_delta', 'energy_per_frame_j_delta'):
        values = [r[metric] for r in rows if r[metric] is not None]
        mean = statistics.mean(values) if values else None
        interval = None
        if len(values) == len(rows) and len(values) >= 3:
            margin = critical[min(len(values) - 2, 29)] * statistics.stdev(values) / math.sqrt(len(values))
            interval = [mean - margin, mean + margin]
        summaries[metric] = {'paired_samples': len(values), 'mean_pair_difference': mean,
                             'confidence_interval_95': interval,
                             'uncertainty': 'ASSUMES_INDEPENDENT_REPRESENTATIVE_PAIRS' if interval is not None else 'UNAVAILABLE_INSUFFICIENT_COMPLETE_PAIRS'}
    return {'document_type': 'docksr_paired_benchmark_analysis', 'hardware_execution_attested': False,
            'contains_simulated_data': any('SIMULATED' in (r['baseline_evidence'], r['experimental_evidence']) for r in rows),
            'pairs': rows, 'summaries': summaries, 'quality_equivalence_verified': False,
            'note': 'Conditions are declared by the experimenter; this does not attest matched quality or establish a product advantage.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path, nargs='?')
    parser.add_argument('--paired', nargs=2, type=Path, action='append', metavar=('BASELINE', 'EXPERIMENTAL'))
    parser.add_argument('--output', type=Path, help='New private JSON outside Git; omit for stdout')
    args = parser.parse_args(argv)
    try:
        if bool(args.record) == bool(args.paired):
            raise ValueError('Choose a record or one/more --paired baseline experimental pairs')
        result = compare_pairs([(read_record(a), read_record(b)) for a, b in args.paired]) if args.paired else analyze(read_record(args.record))
        if args.output:
            write_new_private(args.output, result)
        else:
            print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, ImportError, RecursionError) as error:
        print(json.dumps({'status': 'FAILED', 'error': str(error)[:512], 'hardware_execution_attested': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
