#!/usr/bin/env python3
"""Apply the pinned experimental Gamescope patch to an existing source checkout.

This helper performs no clone, build, installation, network request or service
startup. Hashes establish reproducible bytes, not a signature or license grant.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(tree: Path, *args: str, binary: bool = False):
    result = subprocess.run(["git", "-C", str(tree), *args], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout if binary else result.stdout.decode().strip()


def controlled_path(tree: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(p in ("", ".", "..", ".git") for p in parts.parts):
        raise ValueError(f"unsafe manifest path: {relative}")
    result = tree.joinpath(*parts.parts)
    current = tree
    for component in parts.parts:
        current /= component
        if current.is_symlink():
            raise ValueError(f"symlink in patch target: {relative}")
    return result


def verified_bytes(path: Path, expected: dict) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"expected regular file: {path}")
    data = path.read_bytes()
    if len(data) != expected["size_bytes"] or digest(data) != expected["sha256"]:
        raise ValueError(f"artifact hash/size mismatch: {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--check-applied", action="store_true",
                        help="verify patched file bytes; never mutate or claim runtime success")
    args = parser.parse_args()
    tree = args.checkout.resolve(strict=True)
    lock = json.loads((HERE / "upstream.lock.json").read_text())
    if tree == HERE.parents[1] or git(tree, "rev-parse", "--show-toplevel") != str(tree):
        raise ValueError("checkout must be the root of the separate Gamescope repository")
    if git(tree, "rev-parse", "HEAD") != lock["upstream"]["commit"]:
        raise ValueError("Gamescope HEAD differs from the immutable upstream pin")
    origin = git(tree, "remote", "get-url", "origin").removesuffix(".git").rstrip("/")
    if origin != lock["upstream"]["canonical_origin"]:
        raise ValueError("origin is not the pinned canonical Gamescope repository")

    patch_info = lock["patch"]
    patch = controlled_path(HERE, patch_info["path"])
    verified_bytes(patch, patch_info)
    header_info = lock["contract_header"]
    header_source = controlled_path(HERE, header_info["source"])
    header = verified_bytes(header_source, header_info)
    header_target = controlled_path(tree, header_info["destination"])

    if args.check_applied:
        for record in lock["files"]:
            verified_bytes(controlled_path(tree, record["path"]), record["patched"])
        verified_bytes(header_target, header_info)
        print(f"PASS: exact pinned Gamescope source, {len(lock['files'])} patched files and contract header verified; no build/render claim")
        return 0

    paths = [record["path"] for record in lock["files"]] + [header_info["destination"]]
    if git(tree, "status", "--porcelain=v1", "--untracked-files=all", "--", *paths):
        raise ValueError("patch-target paths contain existing changes; preserve them and use --check-applied if appropriate")
    for record in lock["files"]:
        target = controlled_path(tree, record["path"])
        if record["upstream"] is None:
            if target.exists():
                raise ValueError(f"refusing existing new-file target: {record['path']}")
        else:
            verified_bytes(target, record["upstream"])
    if header_target.exists():
        raise ValueError("refusing to overwrite an existing contract header")

    git(tree, "apply", "--check", str(patch))
    # This local development helper assumes a trusted owner workspace, not a
    # hostile same-UID filesystem. Exclusive creation still prevents overwrite.
    descriptor = os.open(header_target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(header)
        git(tree, "apply", str(patch))
    except BaseException:
        # Only remove the new header created by this invocation. Never reset the
        # checkout or erase user source to recover from an unrelated failure.
        if header_target.is_file() and not header_target.is_symlink() and digest(header_target.read_bytes()) == digest(header):
            header_target.unlink()
        raise
    for record in lock["files"]:
        verified_bytes(controlled_path(tree, record["path"]), record["patched"])
    print(f"PASS: applied {patch_info['sha256']} to {lock['upstream']['commit']}; build/render verification remains separate")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode(errors="replace").strip() if exc.stderr else str(exc)
        else:
            detail = str(exc)
        print(f"ERROR: {detail}", file=sys.stderr)
        raise SystemExit(1)
