#!/usr/bin/env python3
"""Validate Gate-0 metadata, never attest hardware execution or license rights."""
import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite JSON number")
    if isinstance(value, dict):
        for item in value.values(): _finite(item)
    elif isinstance(value, list):
        for item in value: _finite(item)


def validate_record(record, kind):
    from jsonschema import Draft202012Validator, FormatChecker
    if kind not in ("provenance", "hardware"):
        raise ValueError("Unknown record kind")
    name = "model-provenance" if kind == "provenance" else "hardware-evidence"
    schema = json.loads((ROOT / "schemas" / (name + ".schema.json")).read_text())
    Draft202012Validator.check_schema(schema)
    _finite(record)
    error = next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record), None)
    if error:
        raise ValueError("Schema validation failed at /" + "/".join(map(str, error.absolute_path)))
    if kind == "provenance":
        date.fromisoformat(record["inspection_date"])
        references = record["evidence_references"]
        ids = [item["id"] for item in references]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate provenance evidence ID")
        for scope in [*record["licenses"].values(), record["redistribution"]]:
            if not set(scope["evidence_refs"]) <= set(ids):
                raise ValueError("Unresolved provenance evidence reference")
        artifact = record["artifact"]
        if artifact["sha256"] and artifact["advertised_sha256"] and artifact["sha256"] != artifact["advertised_sha256"]:
            raise ValueError("Actual artifact hash differs from advertised hash")
        if record["acquisition"]["status"] == "ACQUIRED" and not re.fullmatch(r"[0-9a-f]{40,64}", record["repository"]["revision"] or ""):
            raise ValueError("Acquired artifact requires an immutable repository revision")
    else:
        timestamp = record["timestamp"]
        if timestamp is not None and datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Hardware timestamp requires a UTC offset")
        samples = record["samples_ms"]
        if samples is not None:
            if record["sample_count"] != len(samples) or record["successful_runs"] != len(samples):
                raise ValueError("Measured sample and successful-run counts differ")
            if samples:
                ordered = sorted(samples)
                for percentile, field in ((50, "npu_or_pipeline_ms_p50"), (95, "npu_or_pipeline_ms_p95"), (99, "npu_or_pipeline_ms_p99")):
                    expected = ordered[max(0, math.ceil(len(ordered) * percentile / 100) - 1)]
                    if record[field] is None or not math.isclose(record[field], expected, rel_tol=1e-9, abs_tol=1e-9):
                        raise ValueError("Timing summary differs from nearest-rank raw samples")
        assignment = record["operator_assignment"]
        if assignment is not None:
            critical = [node for node in assignment["nodes"] if node["critical"]]
            for name, value in (("critical_cpu_nodes", "CPU"), ("critical_npu_nodes", "NPU"), ("critical_unassigned_nodes", "UNASSIGNED")):
                count = sum(node["assignment"] == value for node in critical)
                if assignment[name] is not None and assignment[name] != count:
                    raise ValueError("Operator assignment counts differ from node observations")
        if 'h1_run' in record:
            _validate_h1(record)
    return {"schema_version": "1.0.0", "document_type": "docksr_gate0_validation", "status": "VALID",
            "kind": kind, "hardware_execution_verified": False,
            "license_clearance_verified": False,
            "scope": "Structure and internal consistency only; not evidence that an observation occurred."}


def _validate_h1(record):
    """H1 is a fail-closed lab extension, never an alternate NPU attestation."""
    from import_sesr import PINNED_IDENTITY
    h = record['h1_run']
    cpu = h['mode'] == 'cpu-reference'
    expected = 'CPUExecutionProvider' if cpu else 'VitisAIExecutionProvider'
    if h['requested_provider'] != expected or h['provider_discovered'] != (expected in h['available_providers']):
        raise ValueError('H1 provider metadata contradicts the requested mode')
    if h['provider_session_created'] and (not h['provider_discovered'] or not h['active_providers'] or
            h['active_providers'][0] != expected or (cpu and h['active_providers'] != [expected])):
        raise ValueError('H1 session has unexpected provider fallback')
    if h['model_verified'] and (record['model_id'] != PINNED_IDENTITY.model_id or record['model_sha256'] != PINNED_IDENTITY.sha256 or
            record['input_shape'] != [1, 256, 256, 3] or record['output_shape'] != [1, 512, 512, 3]):
        raise ValueError('H1 model identity/signature is not the unchanged SESR artifact')
    c = h['comparison']
    agreement = (c['compared_samples'] > 0 and c['max_abs_error'] == 0 and c['cpu_repeats_equal'] is True and
                 c['input_sha256'] is not None and c['output_sha256'] is not None and c['output_sha256'] == c['reference_sha256'])
    if h['cpu_reference_agreement_pass'] != agreement:
        raise ValueError('H1 CPU agreement contradicts comparison evidence')
    if agreement and (not h['model_verified'] or not h['provider_session_created']):
        raise ValueError('H1 comparison cannot precede model/session validation')
    if h['classification'] == 'CPU_REFERENCE_PASS':
        if (not cpu or not h['provider_session_created'] or not h['model_verified'] or not agreement or
                record['evidence'] != 'REAL_CPU' or record['runtime_state'] != 'CPU_REFERENCE_ACTIVE' or
                record['backend_kind'] != 'CPU' or c['compared_samples'] != record['sample_count'] or
                record['sample_count'] < 2 or record['warmup_count'] is None or record['warmup_count'] < 1 or
                record['model_validation'] is None or record['model_validation']['correct_output'] is not True):
            raise ValueError('H1 CPU pass lacks a complete CPU execution result')
    elif record['evidence'] != 'NONE':
        raise ValueError('Unaccepted H1 candidate/error must not claim verified execution')
    if h['classification'] == 'INCONCLUSIVE' and (cpu or not agreement or not h['provider_session_created'] or
            h['h0_review_sha256'] is None or record['execution_environment'] != 'TARGET_PHYSICAL'):
        raise ValueError('H1 inconclusive candidate requires an actual approved attempt')
    if (h['placement_status'] == 'RAW_UNVERIFIED') != bool(h['placement_refs']):
        raise ValueError('H1 raw placement status/reference mismatch')
    if (h['context_status'] == 'RAW_UNVERIFIED') != bool(h['context_refs']):
        raise ValueError('H1 raw context status/reference mismatch')
    run = record.get('benchmark_run')
    if run is not None:
        frames = run['frames']
        if (run['run_id'] != h['run_id'] or run['session_id'] != h['run_id'] or run['expected_tiles_per_frame'] != 1 or
                len(frames) != record['sample_count'] or c['compared_samples'] != len(frames)):
            raise ValueError('H1 single-tile lifecycle identity/count mismatch')
        for index, frame in enumerate(frames):
            if (frame['frame_id'] != h['first_frame_id'] + index or frame['configuration_generation'] != h['configuration_generation'] or
                    frame['started_ns'] is None or frame['completed_ns'] is None or
                    not math.isclose((frame['completed_ns'] - frame['started_ns']) / 1e6, record['samples_ms'][index], abs_tol=1e-9)):
                raise ValueError('H1 frame identity or ns/ms request duration mismatch')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("provenance", "hardware"))
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        with args.record.open("rb") as stream: data = stream.read(1_048_577)
        if len(data) > 1_048_576: raise ValueError("Record exceeds 1 MiB")
        record = json.loads(data, object_pairs_hook=_pairs)
        result = validate_record(record, args.kind)
        code = 0
    except (OSError, ValueError, ImportError) as error:
        result = {"status": "ERROR", "error": str(error)[:512], "hardware_execution_verified": False}
        code = 1
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
