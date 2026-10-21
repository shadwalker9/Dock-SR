"""Independent arithmetic/lifecycle goldens; all traces are synthetic."""
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import benchmark_analysis as analysis


def fixture(count=4):
    record = json.loads((ROOT / 'tests/fixtures/gate0_hardware_not_run.json').read_text())
    record.update(record_purpose='SCHEMA_EXAMPLE', fixture_notice='SYNTHETIC SCHEMA FIXTURE - not a hardware run or proof that any stated execution occurred.',
                  runtime_state='MOCK_NPU_ACTIVE', evidence='SIMULATED', backend_kind='MOCK',
                  execution_environment='SIMULATION', backend_name='deterministic-fixture',
                  model_id='owned-fixture', model_sha256='a' * 64,
                  input_shape=[1, 256, 256, 3], output_shape=[1, 512, 512, 3])
    frames = []
    for i in range(count):
        t = i * 250_000_000
        frames.append(dict(frame_id=i + 1, configuration_generation=1,
                           submitted_ns=t, started_ns=t, completed_ns=t + 10_000_000,
                           validated_ns=t + 11_000_000, consumed_ns=t + 12_000_000,
                           presented_ns=t + 250_000_000, cancelled_ns=None,
                           deadline_ns=t + 100_000_000, completed_tiles=24,
                           validated_tiles=24, fallback=False, dropped=False))
    record['benchmark_run'] = dict(
        experiment_id='known-answer', run_id='run', session_id='session', pair_id='pair',
        comparison_role='BASELINE', condition_id='same-quality-workload-declared',
        platform=dict(device='owned-fixture', os='synthetic', kernel='synthetic', software='synthetic', drivers='synthetic'),
        source_extent=dict(width=1280, height=720), output_extent=dict(width=2560, height=1440),
        tensor=dict(layout='NHWC', dtype='int8'), clock_domain='HOST_MONOTONIC', time_unit='ns',
        observation_start_ns=0, observation_end_ns=count * 250_000_000,
        configured_power_limit_w=35, power_profile='synthetic-35W-limit-not-measurement',
        presentation_status='RECORDED', expected_tiles_per_frame=24, frames=frames,
        power=dict(scope='WHOLE_DEVICE', sensor_source='synthetic-wattmeter', unit='W', clock_domain='HOST_MONOTONIC',
                   battery_state='STABLE_AC', max_gap_ns=count * 250_000_000,
                   samples=[dict(timestamp_ns=0, watts=10), dict(timestamp_ns=count * 250_000_000, watts=10)]),
        raw_evidence_refs=[dict(kind='RAW_SAMPLES', path='synthetic/trace.json', sha256='b' * 64)])
    return record


class BenchmarkAnalysisTests(unittest.TestCase):
    def test_known_statistics_and_energy(self):
        value = analysis.analyze(fixture())
        self.assertEqual(value['completed_full_frames_per_s'], 4)
        self.assertEqual(value['validated_full_frames_per_s'], 4)
        self.assertEqual(value['tile_completions_per_s'], 96)
        self.assertEqual(value['presented_frames_per_s'], 4)
        self.assertEqual(value['lifecycle_counts'], dict(SUBMITTED=4, STARTED=4, COMPLETED=4, VALIDATED=4, CONSUMED=4, PRESENTED=4))
        self.assertEqual(value['frame_time_ms']['p50'], 250)
        self.assertEqual(value['inference_latency_ms']['p50'], 10)
        self.assertIsNone(value['frame_time_ms']['p95'])
        self.assertIsNone(value['one_percent_low_fps'])
        self.assertEqual(value['power']['energy_j'], 10)
        self.assertEqual(value['power']['energy_per_presented_frame_j'], 2.5)
        self.assertFalse(value['hardware_execution_attested'])

    def test_nearest_rank_and_one_percent_low(self):
        values = analysis.distribution(list(range(1, 101)))
        self.assertEqual([values[x] for x in ('p50', 'p95', 'p99')], [50, 95, 99])
        record = fixture(101)
        run = record['benchmark_run']
        run['frames'][-1]['presented_ns'] += 250_000_000
        run['observation_end_ns'] += 250_000_000
        run['power'] = None
        value = analysis.analyze(record)
        self.assertEqual(value['one_percent_low_fps'], 2)
        self.assertEqual(value['frame_time_ms']['count'], 100)

    def test_guarded_trapezoid_clips_edges(self):
        p = fixture()['benchmark_run']['power']
        p['samples'] = [dict(timestamp_ns=0, watts=0), dict(timestamp_ns=1_000_000_000, watts=20)]
        value = analysis.energy(p, 250_000_000, 750_000_000, 'HOST_MONOTONIC', 2, 'RECORDED')
        self.assertAlmostEqual(value['energy_j'], 5)
        self.assertAlmostEqual(value['energy_per_presented_frame_j'], 2.5)

    def test_bad_clock_units_values_and_order_reject(self):
        mutations = [
            lambda r: r['benchmark_run'].update(time_unit='ms'),
            lambda r: r['benchmark_run']['frames'][0].update(completed_ns=-1),
            lambda r: r['benchmark_run']['frames'][0].update(started_ns=11_000_000),
            lambda r: r['benchmark_run']['power']['samples'][0].update(watts=float('nan')),
            lambda r: r['benchmark_run']['power']['samples'][0].update(watts=-1),
            lambda r: r['benchmark_run']['power'].update(unit='mW'),
            lambda r: r['benchmark_run']['power']['samples'][1].update(timestamp_ns=0),
            lambda r: r.update(input_shape=[1, 2**64, 3, 3]),
            lambda r: r['benchmark_run']['tensor'].update(layout='NCHW'),
            lambda r: r['benchmark_run']['frames'][0].update(frame_id=2**64),
        ]
        for mutate in mutations:
            record = fixture(); mutate(record)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                analysis.analyze(record)

    def test_unknown_missing_or_bad_power_stays_null(self):
        changes = [(None, 'MISSING_SENSOR'), ({'scope': 'UNKNOWN'}, 'UNKNOWN_SCOPE'),
                   ({'sensor_source': None}, 'UNKNOWN_SENSOR_SOURCE'),
                   ({'clock_domain': 'GPU_DEVICE_CLOCK'}, 'CLOCK_UNALIGNED'),
                   ({'battery_state': 'CHARGING'}, 'BATTERY_COMPARISON_INCONCLUSIVE'),
                   ({'battery_state': 'DISCHARGING'}, 'BATTERY_COMPARISON_INCONCLUSIVE'),
                   ({'max_gap_ns': 1}, 'INSUFFICIENT_POWER_COVERAGE'),
                   ({'samples': []}, 'INSUFFICIENT_POWER_COVERAGE')]
        for change, reason in changes:
            record = fixture()
            if change is None: record['benchmark_run']['power'] = None
            else: record['benchmark_run']['power'].update(change)
            value = analysis.analyze(record)['power']
            self.assertEqual(value['reason'], reason)
            self.assertIsNone(value['energy_j'])
            self.assertIsNone(value['energy_per_presented_frame_j'])

    def test_unknown_or_zero_presentation_prevents_energy_denominator(self):
        for status in ('UNAVAILABLE', 'NOT_RUN', 'RECORDED'):
            record = fixture(); record['benchmark_run']['presentation_status'] = status
            for f in record['benchmark_run']['frames']: f['presented_ns'] = None
            value = analysis.analyze(record)
            self.assertEqual(value['power']['energy_j'], 10)
            self.assertIsNone(value['power']['energy_per_presented_frame_j'])
            self.assertEqual(value['lifecycle_counts']['PRESENTED'], 0 if status == 'RECORDED' else None)

    def test_duplicate_and_incomplete_frames_reject(self):
        mutations = [lambda r: r['benchmark_run']['frames'].append(copy.deepcopy(r['benchmark_run']['frames'][0])),
                     lambda r: r['benchmark_run']['frames'][0].update(validated_ns=None),
                     lambda r: r['benchmark_run']['frames'][0].update(dropped=True),
                     lambda r: r['benchmark_run']['frames'][0].update(validated_tiles=23),
                     lambda r: r['benchmark_run'].update(presentation_status='UNAVAILABLE')]
        for mutate in mutations:
            record = fixture(); mutate(record)
            with self.assertRaises(ValueError): analysis.analyze(record)
        record=fixture()
        record['benchmark_run']['frames'][1].update(frame_id=1,configuration_generation=2)
        with self.assertRaisesRegex(ValueError,'Duplicate frame identity'):analysis.analyze(record)

    def test_queue_growth_deadlines_cancellation_and_fallback(self):
        record = fixture()
        for i, f in enumerate(record['benchmark_run']['frames']):
            f.update(submitted_ns=i * 1_000_000)
            for stage in analysis.STAGES[1:]: f[stage] = None
            f.update(completed_tiles=0, validated_tiles=0)
        frame = record['benchmark_run']['frames'][0]
        frame.update(cancelled_ns=4_000_000, dropped=True, fallback=True)
        result = analysis.analyze(record)
        self.assertEqual(result['queue_max_depth'], 4)
        self.assertEqual(result['queue_final_depth'], 3)
        self.assertEqual(result['deadline_miss_rate'], 1)
        self.assertEqual(result['fallback_frames'], 1)
        self.assertEqual(result['dropped_frames'], 1)
        self.assertEqual(result['completed_full_frames_per_s'], 0)
        self.assertEqual(result['tile_completions_per_s'], 0)

    def test_exact_deadline_is_missed_and_future_deadline_not_due(self):
        record = fixture()
        record['benchmark_run']['frames'][0]['deadline_ns'] = 10_000_000
        record['benchmark_run']['frames'][1]['deadline_ns'] = 2_000_000_000
        value = analysis.analyze(record)
        self.assertEqual(value['deadline_due_requests'], 3)
        self.assertEqual(value['deadline_misses'], 1)
        self.assertAlmostEqual(value['deadline_miss_rate'], 1/3)

    def test_mock_and_cpu_cannot_claim_npu(self):
        for backend in ('MOCK', 'CPU'):
            record = fixture(); record.update(backend_kind=backend, evidence='REAL_NPU', runtime_state='NPU_ACTIVE')
            with self.assertRaises(ValueError): analysis.analyze(record)

    def test_pairs_and_uncertainty_use_independent_deltas(self):
        pairs = []
        for i, watts in enumerate((9, 10, 11)):
            a = fixture(); b = copy.deepcopy(a)
            for record in (a, b): record['benchmark_run']['pair_id'] = 'pair-' + str(i)
            a['benchmark_run']['run_id'] = 'baseline-' + str(i)
            b['benchmark_run']['run_id'] = 'experimental-' + str(i)
            b['benchmark_run']['comparison_role'] = 'EXPERIMENTAL'
            for sample in b['benchmark_run']['power']['samples']: sample['watts'] = watts
            pairs.append((a, b))
        single = analysis.compare_pairs(pairs[:1])
        self.assertTrue(single['contains_simulated_data'])
        self.assertIsNone(single['summaries']['energy_per_frame_j_delta']['confidence_interval_95'])
        result = analysis.compare_pairs(pairs)['summaries']['energy_per_frame_j_delta']
        self.assertEqual(result['mean_pair_difference'], 0)
        margin = 4.303 * 0.25 / math.sqrt(3)
        self.assertAlmostEqual(result['confidence_interval_95'][0], -margin)
        self.assertAlmostEqual(result['confidence_interval_95'][1], margin)
        with self.assertRaises(ValueError): analysis.compare_pairs([pairs[0], pairs[0]])
        reused = copy.deepcopy(pairs[1])
        reused[0]['benchmark_run']['run_id'] = pairs[0][0]['benchmark_run']['run_id']
        with self.assertRaises(ValueError): analysis.compare_pairs([pairs[0], reused])
        pairs[0][1]['benchmark_run']['condition_id'] = 'different-scene'
        with self.assertRaises(ValueError): analysis.compare_pairs(pairs)

    def test_cli_private_output_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); root.chmod(0o700)
            path = root / 'record.json'; path.write_text(json.dumps(fixture()))
            output = root / 'analysis.json'
            self.assertEqual(analysis.main([str(path), '--output', str(output)]), 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(analysis.main([str(path), '--output', str(output)]), 1)
                path.write_text('{"duplicate":1,"duplicate":2}')
                self.assertEqual(analysis.main([str(path)]), 1)
            self.assertEqual(json.loads(output.read_text())['evidence'], 'SIMULATED')


if __name__ == '__main__':
    unittest.main()
