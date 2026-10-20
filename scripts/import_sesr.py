#!/usr/bin/env python3
"""Verify and privately import the exact pinned SESR artifact; never execute it.

No network, model parsing, inference or automatic tracked-manifest editing occurs.
The CLI has no override for its pinned identity. The private byte-import helper
also accepts explicit owned-fixture identities for unit tests.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys

VERSION = "1.0.0"


@dataclass(frozen=True)
class ArtifactIdentity:
    model_id: str
    revision: str
    filename: str
    source_url: str
    size_bytes: int
    sha256: str
    scope: str


PINNED_IDENTITY = ArtifactIdentity(
    "amd/sesr-m7-256x256-tiles-amdnpu",
    "edbe46281e894e31da3f42aa353db1e04a50f00a",
    "sesr_nhwc_int8_256x256.onnx",
    "https://huggingface.co/amd/sesr-m7-256x256-tiles-amdnpu/resolve/"
    "edbe46281e894e31da3f42aa353db1e04a50f00a/onnx-models/sesr_nhwc_int8_256x256.onnx",
    107131,
    "63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1",
    "pinned_model_artifact_bytes_only",
)


class ImportFailure(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _absolute(path):
    path = Path(path)
    if ".." in path.parts:
        raise ImportFailure("UNSAFE_PATH", "Parent traversal is not accepted")
    return Path(os.path.abspath(path))


def _check_parents(path, *, reject_git=False):
    """Check lexical ancestors without following symlink components."""
    for parent in reversed((path, *path.parents)):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ImportFailure("UNSAFE_PARENT", "Parent components must be real directories, not symlinks")
        if reject_git:
            marker = parent / ".git"
            has_marker = os.path.lexists(marker)
            if has_marker:
                marker_info = marker.lstat()
                # This cloud image has empty read-only .git guard directories
                # at /workspace and /tmp; native Git confirms they are not
                # repositories. Never ignore a file, symlink or metadata entry.
                empty_guard = (stat.S_ISDIR(marker_info.st_mode) and
                               not marker_info.st_mode & 0o222 and not any(marker.iterdir()))
                has_marker = not empty_guard
            if parent.name == ".git" or has_marker:
                raise ImportFailure("DESTINATION_INSIDE_GIT", "Model imports must remain outside Git checkouts")


def _read_verified(source, identity):
    _check_parents(source.parent)
    descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ImportFailure("SOURCE_NOT_REGULAR", "Artifact source must be a regular non-symlink file")
        if info.st_size != identity.size_bytes:
            raise ImportFailure("SIZE_MISMATCH", "Actual artifact size differs from the pinned expectation")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(identity.size_bytes + 1)
        if len(data) != identity.size_bytes:
            raise ImportFailure("SIZE_MISMATCH", "Artifact changed size while being read")
        digest = hashlib.sha256(data).hexdigest()
        if digest != identity.sha256:
            raise ImportFailure("HASH_MISMATCH", "Actual artifact SHA-256 differs from the pinned expectation")
        return data, digest
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_new(directory_fd, name, data, created_files):
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory_fd)
    info = os.fstat(descriptor)
    created_files.append((name, info.st_dev, info.st_ino))
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _import_verified(source, destination, identity):
    """Import bytes matching identity; callers must supply a trusted identity.

    This private generic helper allows owned test fixtures to exercise writes
    without presenting those bytes as an AMD model. It does not validate ONNX.
    """
    if (type(identity.size_bytes) is not int or not 1 <= identity.size_bytes <= 1048576 or
            not re.fullmatch(r"[0-9a-f]{64}", identity.sha256) or
            Path(identity.filename).name != identity.filename or identity.filename in ("", ".", "..", "verification.json")):
        raise ImportFailure("INVALID_IDENTITY", "Trusted artifact identity is malformed or exceeds the byte budget")
    source, destination = _absolute(source), _absolute(destination)
    if destination.name == ".git":
        raise ImportFailure("DESTINATION_INSIDE_GIT", "Git metadata paths cannot be model destinations")
    _check_parents(destination.parent, reject_git=True)
    if os.path.lexists(destination):
        raise ImportFailure("DESTINATION_EXISTS", "Destination must be a new directory; existing paths are never replaced")
    parent_info = destination.parent.lstat()
    if parent_info.st_uid != os.getuid() or parent_info.st_mode & 0o022:
        raise ImportFailure("UNCONTROLLED_PARENT", "Destination parent must be owned by the current user and not group/world writable")
    data, digest = _read_verified(source, identity)
    receipt = {
        "schema_version": "1.0.0", "document_type": "docksr_local_model_import",
        "status": "VERIFIED_LOCAL", "classification": "VERIFIED_LOCAL",
        "verification_scope": identity.scope,
        "model_id": identity.model_id, "repository_revision": identity.revision,
        "expected_source_url": identity.source_url,
        "source": {"method": "local_file_import", "path": str(source), "original_retrieval": "NOT_ATTESTED"},
        "artifact": {"filename": identity.filename, "actual_size_bytes": len(data),
                     "actual_sha256": digest, "matches_expected_identity": True},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "tool_versions": {"importer": VERSION, "python": platform.python_version()},
        "graph_inspection": "NOT_RUN", "cpu_reference": "NOT_RUN", "npu_executed": False,
        "hardware_execution_verified": False, "license_clearance_verified": False,
        "limitation": "Size/hash verification only; no ONNX validity, retrieval provenance, inference, NPU compatibility or rights attestation.",
    }
    encoded = (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    directory_fd = None
    created = False
    created_files = []
    try:
        actual_parent = os.fstat(parent_fd)
        if (actual_parent.st_dev, actual_parent.st_ino) != (parent_info.st_dev, parent_info.st_ino):
            raise ImportFailure("PARENT_CHANGED", "Destination parent changed during verification")
        os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
        created = True
        directory_fd = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        os.fchmod(directory_fd, 0o700)
        _write_new(directory_fd, identity.filename, data, created_files)
        _write_new(directory_fd, "verification.json", encoded, created_files)
        os.fsync(directory_fd)
    except BaseException:
        # Remove only still-matching files created by this attempt, not a
        # pre-existing or concurrently replaced child that made O_EXCL fail.
        if created and directory_fd is not None:
            for name, device, inode in created_files:
                try:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == (device, inode):
                        os.unlink(name, dir_fd=directory_fd)
                except OSError: pass
        if created:
            try:
                info = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
                owned = os.fstat(directory_fd) if directory_fd is not None else None
                if owned is not None and (info.st_dev, info.st_ino) == (owned.st_dev, owned.st_ino):
                    os.rmdir(destination.name, dir_fd=parent_fd)
            except OSError: pass
        raise
    finally:
        if directory_fd is not None: os.close(directory_fd)
        os.close(parent_fd)
    return receipt


def import_sesr(source, destination):
    return _import_verified(source, destination, PINNED_IDENTITY)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, required=True, help="New directory outside Git; parent must already exist and be controlled")
    args = parser.parse_args(argv)
    try:
        receipt = import_sesr(args.source, args.destination)
        print(json.dumps(receipt, sort_keys=True, allow_nan=False))
        return 0
    except (ImportFailure, OSError, ValueError) as error:
        report = {"status": "ERROR", "classification": "VERIFIED_LOCAL",
                  "error": {"code": error.code if isinstance(error, ImportFailure) else "IMPORT_IO_ERROR",
                            "message": str(error)[:512] if isinstance(error, ImportFailure) else "Local file import failed; no model execution occurred"},
                  "graph_inspection": "NOT_RUN", "cpu_reference": "NOT_RUN", "npu_executed": False,
                  "hardware_execution_verified": False, "license_clearance_verified": False}
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
