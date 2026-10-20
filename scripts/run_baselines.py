#!/usr/bin/env python3
"""Run/validate six offline Vulkan controls and retain build/source provenance.

These are not game, NPU, quality or power benchmarks. Device classification
comes from each actual Vulkan result, including software-rendered runs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def source_record(repo):
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all"], text=True)
    paths = subprocess.check_output(["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    hashes = {}
    for raw in sorted(set(paths.split(b"\0")) - {b""}):
        relative = raw.decode("utf-8")
        path = repo / relative
        if path.is_file():
            hashes[relative] = sha256(path)
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {"head": head, "working_tree_status": status, "files_sha256": hashes, "fingerprint_sha256": fingerprint}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("build/bin/docksr-bench"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shader", type=Path)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    if not 0 <= args.warmup <= 1000 or not 1 <= args.iterations <= 10000:
        parser.error("warmup must be 0..1000 and iterations 1..10000")
    repo = Path(__file__).resolve().parents[1]
    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error("Benchmark executable missing; build it first")
    shader = (args.shader or binary.parent.parent / "src/vulkan/scale.comp.spv").resolve()
    if not shader.is_file():
        parser.error("Compiled shader missing; pass --shader for a custom build layout")
    sys.path.insert(0, str(repo / "tests"))
    from test_telemetry import validate_generated_benchmark
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite a previous run.
    before = source_record(repo)
    manifest = {
        "schema_version": "1.0.0", "kind": "offline_vulkan_reference_matrix",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": before,
        "binary": {"path": str(binary), "sha256": sha256(binary)},
        "shader": {"path": str(shader), "sha256": sha256(shader)},
        "limits": ["Not game, NPU, power or moving-image quality measurements.",
                   "Manual storage-buffer sampling is not an optimized texture/Gamescope scaler."],
        "runs": [], "status": "running",
    }
    manifest_path = output / "manifest.json"
    def save():
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    save()
    try:
        for size in ["1920x1080", "2560x1440", "3840x2160"]:
            for filter_name in ["nearest", "bilinear"]:
                directory = output / (size + "-" + filter_name)
                command = [str(binary), "--input", "1280x720", "--output", size,
                           "--filter", filter_name, "--warmup", str(args.warmup),
                           "--iterations", str(args.iterations), "--artifact-dir", str(directory)]
                started = datetime.now(timezone.utc).isoformat()
                result = subprocess.run(command, text=True, capture_output=True, timeout=180, check=False)
                row = {"command": command, "started_at_utc": started, "exit_code": result.returncode,
                       "stdout": result.stdout, "stderr": result.stderr}
                manifest["runs"].append(row)
                save()
                if result.returncode:
                    raise RuntimeError("Benchmark failed; see manifest: " + str(manifest_path))
                report_path = directory / "result.json"
                report = validate_generated_benchmark(report_path)
                if not report["correctness"]["passed"]:
                    raise RuntimeError("Pixel correctness failed: " + str(report_path))
                row.update(result_path=str(report_path), result_sha256=sha256(report_path),
                           evidence_class=report["evidence_class"],
                           correctness=report["correctness"], timings=report["timings"],
                           validation="schema_raw_samples_quantiles_image_hashes_pass")
                print(size, filter_name, report["evidence_class"], "PASS", flush=True)
                save()
        after = source_record(repo)
        manifest["source_unchanged_during_run"] = before["fingerprint_sha256"] == after["fingerprint_sha256"]
        if not manifest["source_unchanged_during_run"]:
            raise RuntimeError("Source files changed during the matrix; do not attribute it to the final source state")
        manifest["status"] = "passed"
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        raise
    finally:
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print("Validated six runs. Provenance: " + str(manifest_path))


if __name__ == "__main__":
    main()
