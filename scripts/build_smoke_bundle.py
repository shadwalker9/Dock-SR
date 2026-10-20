#!/usr/bin/env python3
"""Assemble a private, relocatable smoke bundle; no installation or network."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys

from docksr_smoke import sha256, verify_bundle


ROOT = Path(__file__).resolve().parents[1]


def public_command(argv):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        raise RuntimeError("Read-only source provenance command failed")
    return result.stdout.strip()


def source_provenance():
    head = public_command(["git", "rev-parse", "HEAD"])
    if not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise RuntimeError("Source HEAD is unavailable")
    dirty = bool(public_command(["git", "status", "--porcelain", "--untracked-files=normal"]))
    fingerprint = hashlib.sha256()
    paths = []
    for name in ("CMakeLists.txt", "requirements-dev.lock"):
        if (ROOT / name).is_file():
            paths.append(ROOT / name)
    for directory in ("include", "src", "shaders", "scripts", "schemas", "tests", "tools", "docs"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and
                     "__pycache__" not in path.parts and path.suffix in (".py", ".cpp", ".hpp", ".h", ".json", ".md", ".txt", ".comp", ".sh", ".lock"))
    for path in sorted(set(paths)):
        if path.is_symlink():
            raise RuntimeError("Source fingerprint refuses symlinks")
        fingerprint.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        fingerprint.update(bytes.fromhex(sha256(path)))
    return {"source_head": head, "source_dirty": dirty, "source_tree_sha256": fingerprint.hexdigest(),
            "fingerprint_scope": "Application source/build/test/schema/tool/docs files, excluding caches and Git internals; no absolute paths."}


def inspect_elf(path):
    with path.open("rb") as stream:
        header = stream.read(64)
    if len(header) < 64 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != 62:
        raise RuntimeError("Bundle binaries must be ELF64 little-endian x86_64")
    result = {"format": "ELF64", "machine": "x86_64", "runtime_libraries_bundled": False,
              "abi_inspection": "unavailable", "needed": [], "maximum_symbol_versions": {}}
    executable = shutil.which("readelf")
    if executable:
        dynamic = subprocess.run([executable, "--dynamic", "--wide", str(path)], capture_output=True, text=True, timeout=10, check=True).stdout
        versions = subprocess.run([executable, "--version-info", "--wide", str(path)], capture_output=True, text=True, timeout=10, check=True).stdout
        if re.search(r"\((?:RPATH|RUNPATH)\)", dynamic):
            raise RuntimeError("Rebuild smoke executables without embedded library search paths")
        result["needed"] = sorted(set(re.findall(r"\(NEEDED\).*\[([A-Za-z0-9_.+-]+)\]", dynamic)))
        for prefix in ("GLIBC", "GLIBCXX", "CXXABI"):
            values = re.findall(r"\b" + prefix + r"_([0-9]+(?:\.[0-9]+)+)\b", versions)
            result["maximum_symbol_versions"][prefix] = max(values, key=lambda value: tuple(map(int, value.split(".")))) if values else None
        result["abi_inspection"] = "readelf"
    return result


def build_bundle(build_dir: Path, output: Path, include_preview=False, include_bench=False):
    if output.exists() or output.is_symlink():
        raise RuntimeError("Bundle output already exists")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise RuntimeError("Bundle parent must be an existing directory")
    sources = [(build_dir / "bin/docksr-scale", "bin/docksr-scale", "cpu_scaler", True),
               (ROOT / "scripts/docksr_smoke.py", "docksr-smoke", "launcher", False),
               (ROOT / "scripts/docksr_detect.py", "share/docksr/docksr_detect.py", "detector", False)]
    if include_preview:
        sources.append((build_dir / "bin/docksr-preview", "bin/docksr-preview", "preview", True))
    if include_bench:
        sources.append((build_dir / "bin/docksr-bench", "bin/docksr-bench", "vulkan_benchmark", True))
    shader = build_dir / "src/vulkan/scale.comp.spv"
    if include_bench and not shader.is_file():
        raise RuntimeError("Vulkan benchmark requires its compiled shader")
    if (include_preview or include_bench) and shader.is_file():
        sources.append((shader, "share/docksr/scale.comp.spv", "shader", False))
    sources.extend((path, "share/docksr/schemas/" + path.name, "schema", False) for path in sorted((ROOT / "schemas").glob("*.schema.json")))
    sources.extend((ROOT / "docs" / name, "docs/" + name, "documentation", False)
                   for name in ("device-day.md", "MAINTAINER_CONTINUITY.md"))
    binary_metadata = {}
    for source, target, role, binary in sources:
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or source.is_symlink() or info.st_nlink != 1:
            raise RuntimeError("Bundle input must be a regular non-symlink file")
        if binary:
            binary_metadata[target] = inspect_elf(source)
    provenance = source_provenance()
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    try:
        entries = []
        def write(name, payload, role, executable=False):
            destination = output / name
            for relative in reversed(destination.relative_to(output).parents):
                if str(relative) != ".":
                    directory = output / relative
                    directory.mkdir(mode=0o700, exist_ok=True)
                    directory.chmod(0o700)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(destination, flags, 0o700 if executable else 0o600)
            os.fchmod(fd, 0o700 if executable else 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
            entries.append({"path": name, "sha256": sha256(destination), "size": destination.stat().st_size,
                            "mode": "0700" if executable else "0600", "role": role})
        for source, target, role, binary in sources:
            write(target, source.read_bytes(), role, binary or role == "launcher")
        write("share/docksr/reference.ppm", b"P6\n2 1\n255\n\x00\x0a\x14\x64\x6e\x78", "fixture")
        write("NOTICES.txt", (
            "Dock SR private pre-hardware smoke bundle.\n"
            "Included application code, generated shader and test fixture are project code.\n"
            "No project distribution license has been selected; this notice grants no blanket license.\n"
            "No system libraries, Vulkan drivers, models, proprietary resources or private reports are bundled.\n"
            "Host dependency licenses remain with their respective providers. This is not a release.\n"
            "Manifest SHA-256 checks detect local drift; they are not signatures or proof of authenticity.\n"
        ).encode(), "notices")
        requirements = {"schema_version": "1.0.0", "platform": "Linux x86_64", "python": ">=3.10",
                        "binaries": binary_metadata, "target_abi_validation": "UNTESTED",
                        "preview": "Existing X11/XWayland display and host X11 libraries; no display configured by launcher.",
                        "vulkan": "Existing host Vulkan loader and compatible driver if requested. No ICD or loader search environment is forced.",
                        "scope": "REAL_CPU smoke capability; software/physical Vulkan, physical displays and target NPU require separate evidence."}
        write("RUNTIME_REQUIREMENTS.json", (json.dumps(requirements, indent=2) + "\n").encode(), "runtime_requirements")
        files_identity = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
        manifest = {"schema_version": "1.0.0", "bundle_type": "docksr_smoke", "bundle_id": files_identity,
                    "build_platform": {"system": platform.system(), "machine": platform.machine()},
                    "provenance": provenance, "files": entries, "runtime": requirements,
                    "limitations": ["Relocatable artifacts do not establish target ABI or physical-display compatibility.",
                                    "No NPU inference, zero-copy, game integration, FPS improvement or power result is claimed."]}
        (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (output / "MANIFEST.json").chmod(0o600)
        verify_bundle(output)
        return manifest
    except BaseException:
        shutil.rmtree(output)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--include-preview", action="store_true")
    parser.add_argument("--include-bench", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = build_bundle(args.build_dir.resolve(), args.output_dir.absolute(), args.include_preview, args.include_bench)
        print(json.dumps({"bundle_id": manifest["bundle_id"], "files": len(manifest["files"]), "target_abi_validation": "UNTESTED"}))
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        print("Bundle creation failed: verify required built binaries/docs, input integrity, and a new output directory.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
