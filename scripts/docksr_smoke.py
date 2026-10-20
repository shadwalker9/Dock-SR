#!/usr/bin/env python3
"""Offline, relocatable Dock SR smoke launcher; Python 3.10+ standard library."""
# A relocated bundle is verified before importing any of its optional content.
# Re-execute in Python isolated mode first, so an added json.py/selectors.py in
# the bundle cannot run merely by shadowing a standard-library import.
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    import posix
    posix.execv(sys.executable, [sys.executable, "-I", "-B", *sys.argv])

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import stat
import subprocess
import tarfile
import tempfile
import time


MAX_JSON = 1_048_576
MAX_CAPTURE = 524_288
ROLES = {"launcher", "cpu_scaler", "preview", "vulkan_benchmark", "shader", "detector", "schema", "fixture", "notices", "runtime_requirements", "documentation"}
BACKENDS = {"none", "cpu-reference-nearest", "cpu-reference-bilinear", "cpu-reference-self-test", "vulkan-reference-nearest", "vulkan-reference-bilinear"}
STATES = {"STARTING", "CPU_REFERENCE_ACTIVE", "GPU_BASELINE_ACTIVE", "SOFTWARE_VULKAN", "MOCK_NPU_ACTIVE", "FALLBACK", "ERROR", "BYPASS"}
EVIDENCE = {"NONE", "REAL_CPU", "REAL_GPU", "SOFTWARE_VULKAN", "SIMULATED"}


class SmokeError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SmokeError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _json(data: bytes):
    if len(data) > MAX_JSON:
        raise SmokeError("JSON_TOO_LARGE")
    return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(SmokeError("NONFINITE_JSON")))


def read_json(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_JSON:
        raise SmokeError("UNSAFE_JSON_INPUT")
    with path.open("rb") as stream:
        return _json(stream.read(MAX_JSON + 1))


def verify_bundle(root: Path) -> dict:
    """Detect drift against the local manifest, not cryptographic authenticity."""
    if root.is_symlink() or not root.is_dir():
        raise SmokeError("UNSAFE_BUNDLE_ROOT")
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise SmokeError("BUNDLE_ROOT_MUST_BE_PRIVATE")
    if stat.S_IMODE((root / "MANIFEST.json").lstat().st_mode) != 0o600:
        raise SmokeError("MANIFEST_MUST_BE_PRIVATE")
    manifest = read_json(root / "MANIFEST.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0.0" or manifest.get("bundle_type") != "docksr_smoke":
        raise SmokeError("INVALID_MANIFEST")
    provenance = manifest.get("provenance", {})
    if not isinstance(provenance, dict) or not all(
        isinstance(value, str) and re.fullmatch(pattern, value)
        for value, pattern in ((manifest.get("bundle_id"), r"[0-9a-f]{64}"),
            (provenance.get("source_head"), r"[0-9a-f]{40,64}"),
            (provenance.get("source_tree_sha256"), r"[0-9a-f]{64}"))
    ):
        raise SmokeError("INVALID_PROVENANCE_IDENTITY")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 128:
        raise SmokeError("INVALID_MANIFEST_FILES")
    expected = {"MANIFEST.json"}
    directories = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size", "mode", "role"}:
            raise SmokeError("INVALID_MANIFEST_ENTRY")
        name = entry["path"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", name):
            raise SmokeError("UNSAFE_MANIFEST_PATH")
        relative = PurePosixPath(name)
        if relative.is_absolute() or name != str(relative) or any(part in (".", "..") for part in relative.parts):
            raise SmokeError("UNSAFE_MANIFEST_PATH")
        if name in expected or entry["role"] not in ROLES:
            raise SmokeError("DUPLICATE_OR_UNKNOWN_MANIFEST_ENTRY")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise SmokeError("INVALID_MANIFEST_HASH")
        if type(entry["size"]) is not int or entry["size"] < 1 or entry["mode"] not in ("0600", "0700"):
            raise SmokeError("INVALID_MANIFEST_METADATA")
        expected.add(name)
        for parent in relative.parents:
            if str(parent) != ".":
                directories.add(str(parent))
    if hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest() != manifest["bundle_id"]:
        raise SmokeError("BUNDLE_IDENTITY_MISMATCH")
    actual_files = set()
    actual_directories = set()
    for folder, child_directories, files in os.walk(root, followlinks=False):
        for name in child_directories + files:
            path = Path(folder) / name
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                if stat.S_IMODE(info.st_mode) != 0o700:
                    raise SmokeError("BUNDLE_DIRECTORY_MUST_BE_PRIVATE")
                actual_directories.add(relative)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                actual_files.add(relative)
            else:
                raise SmokeError("BUNDLE_SYMLINK_OR_SPECIAL_FILE")
    if actual_files != expected or actual_directories != directories:
        raise SmokeError("BUNDLE_CONTENT_MISMATCH")
    for entry in entries:
        path = root / entry["path"]
        info = path.lstat()
        if info.st_size != entry["size"] or stat.S_IMODE(info.st_mode) != int(entry["mode"], 8) or sha256(path) != entry["sha256"]:
            raise SmokeError("BUNDLE_INTEGRITY_FAILED")
    required = {"docksr-smoke", "bin/docksr-scale", "share/docksr/docksr_detect.py", "share/docksr/schemas/runtime-status.schema.json"}
    if not required <= expected:
        raise SmokeError("BUNDLE_REQUIRED_FILE_MISSING")
    return manifest


def run_bounded(argv: list[str], timeout: float = 30.0) -> tuple[int, bytes, bytes]:
    """Bound the combined capture while draining both pipes; never invoke a shell."""
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    output = {"stdout": bytearray(), "stderr": bytearray()}
    selector = selectors.DefaultSelector()
    assert process.stdout is not None and process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + timeout
    failure = None
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                failure = "COMMAND_TIMEOUT"
                break
            for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    selector.unregister(key.fileobj)
                else:
                    output[key.data].extend(block)
                    if sum(map(len, output.values())) > MAX_CAPTURE:
                        failure = "COMMAND_OUTPUT_LIMIT"
                        break
            if failure:
                break
        if failure:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            raise SmokeError(failure)
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            raise SmokeError("COMMAND_TIMEOUT") from error
        return process.returncode, bytes(output["stdout"]), bytes(output["stderr"])
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _integer(value, minimum=0, maximum=18446744073709551615):
    return type(value) is int and minimum <= value <= maximum


def sanitize_status(value: dict) -> dict:
    """Project known runtime fields; drop arbitrary messages, names and paths."""
    if not isinstance(value, dict) or value.get("schema_version") != "1.0.0" or value.get("document_type") != "docksr_status":
        raise SmokeError("INVALID_STATUS_DOCUMENT")
    if value.get("runtime_state") not in STATES or value.get("evidence") not in EVIDENCE:
        raise SmokeError("UNSUPPORTED_STATUS_EVIDENCE")
    result = {
        "schema_version": "1.0.0", "document_type": "docksr_status",
        "runtime_state": value["runtime_state"], "evidence": value["evidence"],
        "backend_name": value.get("backend_name") if value.get("backend_name") in BACKENDS else "other",
        "frames_processed": value.get("frames_processed"), "dimensions": {}, "last_error": None,
        "npu": {}, "timings_ms": {}, "updated_at_monotonic_ns": value.get("updated_at_monotonic_ns"),
    }
    if not _integer(result["frames_processed"]) or not _integer(result["updated_at_monotonic_ns"]):
        raise SmokeError("INVALID_STATUS_COUNTER")
    for kind in ("requested", "actual"):
        item = value.get("dimensions", {}).get(kind)
        if item is None:
            result["dimensions"][kind] = None
        elif isinstance(item, dict):
            safe = {}
            for direction in ("input", "output"):
                dimensions = item.get(direction, {})
                if not isinstance(dimensions, dict) or not all(_integer(dimensions.get(axis), 1, 16384) for axis in ("width", "height")):
                    raise SmokeError("INVALID_STATUS_DIMENSIONS")
                safe[direction] = {axis: dimensions[axis] for axis in ("width", "height")}
            result["dimensions"][kind] = safe
        else:
            raise SmokeError("INVALID_STATUS_DIMENSIONS")
    npu = value.get("npu", {})
    if not isinstance(npu, dict) or npu.get("device_status") not in {"NOT_TESTED", "NOT_DETECTED", "DETECTED", "ERROR"} or npu.get("model_status") not in {"UNVALIDATED", "MISSING", "INVALID"}:
        raise SmokeError("INVALID_NPU_STATUS")
    result["npu"] = {key: npu[key] for key in ("device_status", "model_status")}
    timings = value.get("timings_ms", {})
    if not isinstance(timings, dict) or timings.get("npu") is not None:
        raise SmokeError("UNSUPPORTED_NPU_TIMING")
    for key in ("cpu", "gpu", "npu"):
        timing = timings.get(key)
        if timing is not None and (type(timing) not in (int, float) or not math.isfinite(timing) or timing < 0):
            raise SmokeError("INVALID_STATUS_TIMING")
        result["timings_ms"][key] = timing
    if value.get("last_error") is not None:
        result["last_error"] = {"code": "LOCAL_ERROR_REDACTED", "message": "Local diagnostic detail omitted to avoid exporting paths or private data."}
    expected = {"STARTING": "NONE", "CPU_REFERENCE_ACTIVE": "REAL_CPU", "GPU_BASELINE_ACTIVE": "REAL_GPU",
                "SOFTWARE_VULKAN": "SOFTWARE_VULKAN", "MOCK_NPU_ACTIVE": "SIMULATED"}
    if result["runtime_state"] in expected and result["evidence"] != expected[result["runtime_state"]]:
        raise SmokeError("STATUS_EVIDENCE_MISMATCH")
    requested, actual = result["dimensions"]["requested"], result["dimensions"]["actual"]
    if ((actual is not None and requested is None) or
        (result["frames_processed"] == 0 and (actual is not None or any(item is not None for item in result["timings_ms"].values()))) or
        (result["frames_processed"] > 0 and (actual is None or result["evidence"] == "NONE")) or
        (result["runtime_state"] in {"CPU_REFERENCE_ACTIVE", "GPU_BASELINE_ACTIVE", "SOFTWARE_VULKAN", "MOCK_NPU_ACTIVE"} and requested is None) or
        (result["runtime_state"] in {"ERROR", "FALLBACK"} and result["last_error"] is None) or
        (result["evidence"] == "REAL_CPU" and result["timings_ms"]["gpu"] is not None) or
        (result["evidence"] == "SIMULATED" and any(item is not None for item in result["timings_ms"].values()))):
        raise SmokeError("INCONSISTENT_STATUS_OBSERVATION")
    return result


def launcher_status(code=None):
    return {"schema_version": "1.0.0", "document_type": "docksr_status",
            "runtime_state": "ERROR" if code else "BYPASS", "evidence": "NONE", "backend_name": "smoke-launcher",
            "dimensions": {"requested": None, "actual": None}, "frames_processed": 0,
            "last_error": {"code": code, "message": "Smoke action failed; no successful backend execution is claimed."} if code else None,
            "npu": {"device_status": "NOT_TESTED", "model_status": "UNVALIDATED"},
            "timings_ms": {"cpu": None, "gpu": None, "npu": None}, "updated_at_monotonic_ns": time.monotonic_ns()}


def private_parent(path: Path):
    parent = path.parent
    info = parent.stat()
    if not parent.is_dir() or parent.is_symlink() or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise SmokeError("OUTPUT_PARENT_MUST_BE_PRIVATE")


def new_private_output(path: Path):
    if path.exists() or path.is_symlink():
        raise SmokeError("OUTPUT_ALREADY_EXISTS")
    private_parent(path)


def self_test(root: Path, status_path: Path | None = None):
    argv = [str(root / "bin/docksr-scale"), "--self-test"]
    if status_path is not None:
        # The existing C++ publisher safely replaces only its own 0600 status
        # documents; unrelated files, symlinks and hardlinks remain protected.
        private_parent(status_path)
        argv.extend(["--dump-status-json", str(status_path)])
    returncode, stdout, stderr = run_bounded(argv)
    status = sanitize_status(_json(stdout))
    if returncode != 0:
        raise SmokeError("CPU_SELF_TEST_FAILED")
    summary = bool(re.search(rb"^SELF_TEST_SUMMARY cases=4 published_images=0 frames_processed=0 PASS\r?$", stderr, re.MULTILINE))
    if not summary:
        raise SmokeError("CPU_SELF_TEST_SUMMARY_MISSING")
    if status["evidence"] != "REAL_CPU" or status["runtime_state"] != "CPU_REFERENCE_ACTIVE":
        raise SmokeError("CPU_SELF_TEST_EVIDENCE_INVALID")
    return status, {"status": "passed", "cases": 4, "evidence": "REAL_CPU",
                    "scope": "In-memory 720p to 1080p/2160p nearest/bilinear correctness; no published frames or game performance."}


def inventory_summary(value):
    safe_statuses = {"ok", "present", "absent", "permission_denied", "error", "missing_tool", "timeout", "command_failed"}
    def status(record):
        candidate = record.get("status") if isinstance(record, dict) else None
        return candidate if candidate in safe_statuses else "unknown"
    result = {"source_schema_version": "1.0.0", "sanitized": True, "npu_ready": False,
              "hardware_validated": False, "device_nodes": {}, "tools": {}}
    if not isinstance(value, dict) or value.get("report_type") != "docksr_detection":
        raise SmokeError("INVALID_INVENTORY")
    release = value.get("host", {}).get("kernel_release", {})
    result["kernel_release"] = {"status": status(release)}
    for kind in ("dri", "accel"):
        record = value.get("device_nodes", {}).get(kind, {})
        nodes = record.get("nodes", []) if isinstance(record, dict) else []
        result["device_nodes"][kind] = {"status": status(record), "visible_count": min(len(nodes), 128) if isinstance(nodes, list) else 0}
    for tool in ("xrt_smi_version", "vulkan_summary", "lspci_version"):
        result["tools"][tool] = {"status": status(value.get("tools", {}).get(tool, {}))}
    return result


def export_diagnostics(root: Path, manifest: dict, output: Path, status_path: Path | None):
    if not output.name.endswith(".tar.gz"):
        raise SmokeError("DIAGNOSTICS_REQUIRES_TAR_GZ")
    new_private_output(output)
    documents = {"bundle.json": {"schema_version": "1.0.0", "bundle_id": manifest["bundle_id"],
                  "source_head": manifest["provenance"].get("source_head"), "source_tree_sha256": manifest["provenance"].get("source_tree_sha256"),
                  "evidence_scope": "Bundle identity only; target physical GPU/NPU and ABI remain unvalidated."}}
    if status_path is not None:
        documents["status.json"] = sanitize_status(read_json(status_path))
    try:
        _, summary = self_test(root)
        documents["self-test.json"] = summary
    except (SmokeError, OSError, ValueError):
        documents["self-test.json"] = {"status": "failed", "evidence": "NONE", "detail": "Local failure details omitted."}
    try:
        code, stdout, _ = run_bounded([sys.executable, "-B", str(root / "share/docksr/docksr_detect.py")], timeout=40)
        if code != 0:
            raise SmokeError("INVENTORY_COMMAND_FAILED")
        documents["inventory.json"] = inventory_summary(_json(stdout))
    except (SmokeError, OSError, ValueError, TypeError, AttributeError):
        documents["inventory.json"] = {"sanitized": True, "status": "unavailable", "npu_ready": False,
                                       "hardware_validated": False, "detail": "No raw tool output was exported."}
    fd, temporary_name = tempfile.mkstemp(prefix=".docksr-export-", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            with tarfile.open(fileobj=stream, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
                for name, value in documents.items():
                    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = len(payload), 0o600, 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    archive.addfile(info, io.BytesIO(payload))
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard-link publication is atomic and never replaces a
        # concurrently appearing destination. The completed file is private.
        os.link(temporary, output, follow_symlinks=False)
        temporary.unlink()
        directory_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    root = Path(os.path.abspath(__file__)).parent
    try:
        manifest = verify_bundle(root)
        parser = argparse.ArgumentParser(description=__doc__)
        action = parser.add_mutually_exclusive_group(required=True)
        action.add_argument("--self-test", action="store_true")
        action.add_argument("--preview", action="store_true")
        action.add_argument("--diagnostics-export", type=Path)
        parser.add_argument("--dump-status-json", type=Path)
        parser.add_argument("--status-json", type=Path, help="Existing runtime status to sanitize into diagnostics.")
        parser.add_argument("--size", choices=("1920x1080", "3840x2160"), default="1920x1080")
        parser.add_argument("--filter", choices=("nearest", "bilinear"), default="bilinear")
        parser.add_argument("--backend", choices=("cpu", "vulkan"), default="cpu")
        args = parser.parse_args(argv)
        if args.status_json is not None and args.diagnostics_export is None:
            raise SmokeError("STATUS_INPUT_REQUIRES_DIAGNOSTICS")
        if args.diagnostics_export is not None:
            if args.dump_status_json is not None:
                raise SmokeError("DIAGNOSTICS_STATUS_OUTPUT_UNSUPPORTED")
            export_diagnostics(root, manifest, args.diagnostics_export, args.status_json)
            status = launcher_status()
        elif args.self_test:
            status, _ = self_test(root, args.dump_status_json)
        else:
            binary = root / "bin/docksr-preview"
            if not binary.is_file():
                raise SmokeError("PREVIEW_NOT_INCLUDED")
            command = [str(binary), "--size", args.size, "--filter", args.filter, "--backend", args.backend]
            if args.dump_status_json is not None:
                private_parent(args.dump_status_json)
                command.extend(["--dump-status-json", str(args.dump_status_json)])
            os.execv(binary, command)
            return 1
        print(json.dumps(status, sort_keys=True, allow_nan=False))
        return 0
    except (SmokeError, OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        code = error.code if isinstance(error, SmokeError) else "SMOKE_ACTION_FAILED"
        print(json.dumps(launcher_status(code), sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
