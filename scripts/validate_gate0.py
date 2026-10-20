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
    return {"schema_version": "1.0.0", "document_type": "docksr_gate0_validation", "status": "VALID",
            "kind": kind, "hardware_execution_verified": False,
            "license_clearance_verified": False,
            "scope": "Structure and internal consistency only; not evidence that an observation occurred."}


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
