"""Read-only detector behavior; no physical GPU or NPU is needed."""

from __future__ import annotations

import errno
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("docksr_detect", ROOT / "scripts/docksr_detect.py")
assert SPEC is not None and SPEC.loader is not None
detector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detector)


class MissingRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv):
        self.calls.append(list(argv))
        return {"status": "missing_tool", "argv": list(argv)}


class DetectionTests(unittest.TestCase):
    def test_absent_paths_and_missing_tools_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = MissingRunner()
            report = detector.detect(detector.FileSystem(directory), runner, "2026-01-01T00:00:00Z")
        self.assertEqual(report["device_nodes"]["accel"]["status"], "absent")
        self.assertEqual(report["host"]["kernel_release"]["status"], "absent")
        self.assertEqual(report["tools"]["xrt_smi_version"]["status"], "missing_tool")
        self.assertEqual(runner.calls, [["xrt-smi", "--version"], ["vulkaninfo", "--summary"], ["lspci", "--version"]])
        self.assertFalse(report["npu_ready"])
        self.assertIsNone(report["capabilities"]["vulkan_external_buffer"]["supported"])

    def test_visible_nodes_and_driver_are_inventory_not_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "proc/sys/kernel/osrelease": "fixture-kernel\n",
                "dev/accel/accel0": "",
                "dev/dri/renderD128": "",
                "sys/module/amdxdna/version": "fixture-driver-version\n",
                "sys/class/accel/accel0/device/vendor": "0x1022\n",
                "sys/class/accel/accel0/device/device": "0x17f0\n",
                "sys/class/accel/accel0/device/firmware_version": "fixture-fw\n",
                "sys/bus/pci/devices/0000:00:01.0/vendor": "0x1022\n",
                "sys/bus/pci/devices/0000:00:01.0/device": "0x17f0\n",
                "sys/bus/pci/devices/0000:00:01.0/class": "0x118000\n",
            }
            for name, text in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            (root / "sys/bus/pci/devices/0000:00:01.0/driver").symlink_to("../../../../bus/pci/drivers/amdxdna")
            report = detector.detect(detector.FileSystem(root), MissingRunner())
        self.assertEqual(report["device_nodes"]["accel"]["status"], "present")
        self.assertFalse(report["device_nodes"]["accel"]["nodes"][0]["opened"])
        self.assertEqual(report["host"]["kernel_release"]["value"], "fixture-kernel")
        self.assertTrue(report["sysfs"]["pci"]["amd_devices"][0]["bound_to_amdxdna"])
        self.assertEqual(report["sysfs"]["accel"]["devices"][0]["fields"]["firmware_version"]["value"], "fixture-fw")
        self.assertFalse(report["hardware_validated"])
        self.assertFalse(report["npu_ready"])
        for capability in report["capabilities"].values():
            self.assertEqual(capability["status"], "unrun")
            self.assertIsNone(capability["supported"])

    def test_permission_failures_are_not_absence_or_unsupported(self):
        class PermissionFileSystem(detector.FileSystem):
            def entries(self, path):
                if path == "/dev/accel":
                    return {"status": "permission_denied", "errno": errno.EACCES}
                return {"status": "absent", "errno": errno.ENOENT}

        with tempfile.TemporaryDirectory() as directory:
            report = detector.detect(PermissionFileSystem(directory), MissingRunner())
        self.assertEqual(report["device_nodes"]["accel"]["status"], "permission_denied")
        self.assertFalse(report["npu_ready"])
        self.assertIsNone(report["capabilities"]["npu_execution"]["supported"])

    def test_filesystem_retains_actual_permission_errors(self):
        fs = detector.FileSystem("/fixture")
        with patch.object(Path, "open", side_effect=PermissionError(errno.EACCES, "fixture")):
            self.assertEqual(fs.read_text("/sys/module/amdxdna/version")["status"], "permission_denied")
        with patch.object(Path, "iterdir", side_effect=PermissionError(errno.EACCES, "fixture")):
            self.assertEqual(fs.entries("/dev/dri")["status"], "permission_denied")

    def test_listed_but_unreadable_node_is_not_reported_present(self):
        class PermissionFileSystem(detector.FileSystem):
            def entries(self, path):
                return {"status": "ok", "names": ["accel0"]}

            def inspect(self, path):
                return {"status": "permission_denied", "errno": errno.EACCES}

        result = detector._nodes(PermissionFileSystem("/fixture"), "/dev/accel", ("accel",))
        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["nodes"][0]["status"], "permission_denied")

    def test_successful_vulkan_summary_does_not_prove_buffer_support(self):
        class SummaryRunner:
            def run(self, argv):
                return {"status": "ok", "argv": list(argv), "returncode": 0,
                        "stdout": "VK_EXT_external_memory_dma_buf\nfixture GPU", "stderr": "", "truncated": False}

        with tempfile.TemporaryDirectory() as directory:
            report = detector.detect(detector.FileSystem(directory), SummaryRunner())
        self.assertEqual(report["tools"]["vulkan_summary"]["status"], "ok")
        self.assertEqual(report["capabilities"]["vulkan_external_buffer"]["status"], "unrun")
        self.assertIsNone(report["capabilities"]["vulkan_external_buffer"]["supported"])
        self.assertFalse(report["npu_ready"])

    def test_only_amd_pci_inventory_is_selected_without_assuming_support(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for address, vendor in [("0000:00:01.0", "0x1022"), ("0000:00:02.0", "0x8086")]:
                device = root / "sys/bus/pci/devices" / address
                device.mkdir(parents=True)
                (device / "vendor").write_text(vendor)
            report = detector.detect(detector.FileSystem(root), MissingRunner())
        devices = report["sysfs"]["pci"]["amd_devices"]
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device"]["status"], "absent")
        self.assertFalse(devices[0]["bound_to_amdxdna"])


class CommandRunnerTests(unittest.TestCase):
    def test_missing_executable(self):
        with patch.object(detector.shutil, "which", return_value=None):
            result = detector.CommandRunner().run(["xrt-smi", "--version"])
        self.assertEqual(result["status"], "missing_tool")

    def test_start_permission_failure(self):
        with patch.object(detector.shutil, "which", return_value="/fixture/xrt-smi"), patch.object(
            detector.subprocess, "run", side_effect=PermissionError(errno.EACCES, "fixture")
        ):
            result = detector.CommandRunner().run(["xrt-smi", "--version"])
        self.assertEqual(result["status"], "permission_denied")

    def test_timeout_is_distinct(self):
        with patch.object(detector.shutil, "which", return_value="/fixture/vulkaninfo"), patch.object(
            detector.subprocess, "run", side_effect=subprocess.TimeoutExpired("vulkaninfo", 0.5)
        ):
            result = detector.CommandRunner().run(["vulkaninfo", "--summary"], timeout=0.5)
        self.assertEqual(result["status"], "timeout")

    def test_failed_command_does_not_mean_unsupported_hardware(self):
        completed = subprocess.CompletedProcess(["vulkaninfo"], 1, "", "fixture device denied")
        with patch.object(detector.shutil, "which", return_value="/fixture/vulkaninfo"), patch.object(
            detector.subprocess, "run", return_value=completed
        ) as run:
            result = detector.CommandRunner().run(["vulkaninfo", "--summary"])
        self.assertEqual(result["status"], "command_failed")
        self.assertEqual(result["returncode"], 1)
        self.assertEqual(run.call_args.kwargs["timeout"], 10.0)
        self.assertFalse(run.call_args.kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
