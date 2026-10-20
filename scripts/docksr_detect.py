#!/usr/bin/env python3
"""Read-only host inventory. Presence is evidence to investigate, not readiness.

No kernel modules are explicitly loaded, packages installed, or environment
values inventoried. The inventory code only stats device nodes; vulkaninfo may
initialize a userspace driver and open graphics devices. FileSystem and
CommandRunner are injectable for deterministic tests.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any, Sequence


SCHEMA_VERSION = "1.0.0"
MAX_TEXT = 65536


def _failure(exc: OSError) -> dict[str, Any]:
    if isinstance(exc, FileNotFoundError):
        status = "absent"
    elif isinstance(exc, PermissionError):
        status = "permission_denied"
    else:
        status = "error"
    # Do not copy arbitrary exception text (or environment values) into reports.
    return {"status": status, "errno": exc.errno}


class FileSystem:
    """Map Linux absolute paths under an optional fixture root."""

    def __init__(self, root: str | Path = "/") -> None:
        self.root = Path(root)

    def path(self, logical_path: str) -> Path:
        return self.root / logical_path.lstrip("/")

    def read_text(self, logical_path: str) -> dict[str, Any]:
        try:
            with self.path(logical_path).open("r", encoding="utf-8", errors="replace") as stream:
                value = stream.read(MAX_TEXT + 1)
            return {"status": "ok", "value": value[:MAX_TEXT].strip(),
                    "truncated": len(value) > MAX_TEXT}
        except OSError as exc:
            return _failure(exc)

    def entries(self, logical_path: str) -> dict[str, Any]:
        try:
            return {"status": "ok", "names": sorted(p.name for p in self.path(logical_path).iterdir())}
        except OSError as exc:
            return _failure(exc)

    def inspect(self, logical_path: str) -> dict[str, Any]:
        try:
            info = self.path(logical_path).stat()
        except OSError as exc:
            return _failure(exc)
        kind = "character" if stat.S_ISCHR(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode) else "other"
        return {"status": "present", "node_type": kind,
                "mode": format(stat.S_IMODE(info.st_mode), "04o"), "opened": False}

    def link_name(self, logical_path: str) -> dict[str, Any]:
        try:
            return {"status": "ok", "value": Path(os.readlink(self.path(logical_path))).name}
        except OSError as exc:
            return _failure(exc)


class CommandRunner:
    """Run public inventory/version commands with a deadline."""

    def run(self, argv: Sequence[str], timeout: float = 10.0) -> dict[str, Any]:
        executable = shutil.which(argv[0])
        if executable is None:
            return {"status": "missing_tool", "argv": list(argv)}
        try:
            process = subprocess.run(
                [executable, *argv[1:]], check=False, capture_output=True,
                text=True, errors="replace", timeout=timeout,
            )
        except PermissionError as exc:
            return {"status": "permission_denied", "argv": list(argv), "errno": exc.errno}
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "argv": list(argv), "timeout_seconds": timeout}
        except OSError as exc:
            return {"status": "error", "argv": list(argv), "errno": exc.errno}
        return {
            "status": "ok" if process.returncode == 0 else "command_failed",
            "argv": list(argv), "returncode": process.returncode,
            "stdout": process.stdout[:MAX_TEXT], "stderr": process.stderr[:MAX_TEXT],
            "truncated": len(process.stdout) > MAX_TEXT or len(process.stderr) > MAX_TEXT,
        }


def _nodes(fs: FileSystem, directory: str, prefixes: tuple[str, ...]) -> dict[str, Any]:
    listing = fs.entries(directory)
    if listing["status"] != "ok":
        return {"path": directory, **listing, "nodes": []}
    nodes = [{"path": directory + "/" + name, **fs.inspect(directory + "/" + name)}
             for name in listing["names"] if name.startswith(prefixes)]
    statuses = {node["status"] for node in nodes}
    status = next((candidate for candidate in ("present", "permission_denied", "error")
                   if candidate in statuses), "absent")
    return {"path": directory, "status": status, "nodes": nodes}


def _accel_sysfs(fs: FileSystem) -> dict[str, Any]:
    directory = "/sys/class/accel"
    listing = fs.entries(directory)
    if listing["status"] != "ok":
        return {"path": directory, **listing, "devices": []}
    devices = []
    for name in listing["names"]:
        if not name.startswith("accel"):
            continue
        base = directory + "/" + name
        fields = {field: fs.read_text(base + "/device/" + field)
                  for field in ("vendor", "device", "class", "firmware_version", "fw_version")}
        devices.append({"name": name, "path": base, "driver": fs.link_name(base + "/device/driver"),
                        "fields": fields})
    return {"path": directory, "status": "present" if devices else "absent", "devices": devices}


def _pci_inventory(fs: FileSystem) -> dict[str, Any]:
    directory = "/sys/bus/pci/devices"
    listing = fs.entries(directory)
    if listing["status"] != "ok":
        return {"path": directory, **listing, "amd_devices": []}
    devices = []
    unreadable = []
    for name in listing["names"]:
        base = directory + "/" + name
        vendor = fs.read_text(base + "/vendor")
        if vendor["status"] != "ok":
            unreadable.append({"address": name, "vendor": vendor})
            continue
        if vendor["value"].lower() not in ("0x1022", "0x1002"):
            continue
        driver = fs.link_name(base + "/driver")
        devices.append({"address": name, "vendor": vendor,
                        "device": fs.read_text(base + "/device"),
                        "class": fs.read_text(base + "/class"), "driver": driver,
                        "bound_to_amdxdna": driver.get("value") == "amdxdna"})
    return {"path": directory, "status": "ok", "amd_devices": devices,
            "unreadable_entries": unreadable}


def detect(fs: FileSystem | None = None, runner: CommandRunner | None = None,
           timestamp: str | None = None) -> dict[str, Any]:
    fs = fs or FileSystem()
    runner = runner or CommandRunner()
    commands = {
        "xrt_smi_version": ["xrt-smi", "--version"],
        "vulkan_summary": ["vulkaninfo", "--summary"],
        "lspci_version": ["lspci", "--version"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "docksr_detection",
        "generated_at_utc": timestamp or datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "host": {"kernel_release": fs.read_text("/proc/sys/kernel/osrelease"),
                 "kernel_version": fs.read_text("/proc/version"),
                 "os_release": fs.read_text("/etc/os-release")},
        "device_nodes": {"dri": _nodes(fs, "/dev/dri", ("card", "renderD")),
                         "accel": _nodes(fs, "/dev/accel", ("accel",))},
        "sysfs": {"accel": _accel_sysfs(fs), "pci": _pci_inventory(fs),
                  "amdxdna": {"module": fs.inspect("/sys/module/amdxdna"),
                              "version": fs.read_text("/sys/module/amdxdna/version"),
                              "srcversion": fs.read_text("/sys/module/amdxdna/srcversion")}},
        "tools": {key: runner.run(argv) for key, argv in commands.items()},
        "capabilities": {
            "vulkan_external_buffer": {
                "status": "unrun", "supported": None,
                "usage": "storage_buffer|transfer_src|transfer_dst",
                "handle_type": "dma_buf",
                "reason": "No native exact-usage VkBuffer external-memory query was executed. vulkaninfo --summary cannot establish buffer import/export compatibility.",
            },
            "cross_device_synchronization": {"status": "unrun", "supported": None,
                "reason": "No Vulkan/XRT cross-device synchronization experiment was executed."},
            "npu_execution": {"status": "unrun", "supported": None,
                "reason": "No model was compiled or executed; presence and version data cannot validate NPU execution."},
        },
        "npu_ready": False,
        "hardware_validated": False,
        "readiness_reason": "Inventory only. NPU execution, exact-buffer sharing, correctness, synchronization, and performance have not been validated.",
        "limitations": [
            "Absent paths describe visibility in this process/container, not necessarily the physical host.",
            "The filesystem inventory only stats device nodes. vulkaninfo may initialize drivers and open devices; this does not validate inference or buffer sharing.",
            "Missing optional sysfs version/firmware attributes mean unavailable metadata, not an unsupported device.",
            "vulkaninfo extension names and a successful summary are not exact external-memory support queries.",
            "No environment variable values or credential files are read.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write JSON to this file instead of stdout.")
    args = parser.parse_args(argv)
    output = json.dumps(detect(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
