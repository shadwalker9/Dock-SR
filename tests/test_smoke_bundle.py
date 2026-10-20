"""Relocation/integrity/privacy tests using already built binaries, no installs."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_smoke_bundle as builder
import docksr_smoke as smoke

BUILD_DIR = None


class ProjectionTests(unittest.TestCase):
    def test_status_paths_arbitrary_backend_and_private_messages_are_removed(self):
        report = json.loads((ROOT / "tests/fixtures/runtime_cpu.json").read_text())
        report.update(runtime_state="ERROR", backend_name="secret-token-user-identity",
                      last_error={"code": "PRIVATE_SERIAL_1234", "message": "/home/private-user/token-secret"})
        report["private_environment"] = "credential-secret"
        safe = smoke.sanitize_status(report)
        text = json.dumps(safe)
        for private in ("secret-token", "private-user", "PRIVATE_SERIAL", "credential-secret"):
            self.assertNotIn(private, text)
        self.assertEqual(safe["backend_name"], "other")
        self.assertEqual(safe["frames_processed"], report["frames_processed"])

    def test_inventory_never_exports_raw_tool_output_paths_or_serials(self):
        report = {"report_type": "docksr_detection", "host": {"kernel_release": {"status": "ok", "value": "6.8.0-private-user"}},
                  "tools": {"vulkan_summary": {"status": "ok", "stdout": "SERIAL-secret /home/alice API_TOKEN=hidden"}},
                  "device_nodes": {"dri": {"status": "present", "nodes": [{"path": "/home/alice"}]}}}
        safe = json.dumps(smoke.inventory_summary(report))
        for private in ("private-user", "SERIAL-secret", "/home/alice", "API_TOKEN", "hidden"):
            self.assertNotIn(private, safe)

    def test_inconsistent_or_real_npu_status_is_rejected(self):
        report = json.loads((ROOT / "tests/fixtures/runtime_cpu.json").read_text())
        for field, value in (("evidence", "REAL_NPU"), ("evidence", "REAL_GPU"), ("frames_processed", -1)):
            candidate = copy.deepcopy(report)
            candidate[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(smoke.SmokeError):
                smoke.sanitize_status(candidate)

    def test_command_capture_and_time_are_bounded(self):
        with self.assertRaisesRegex(smoke.SmokeError, "COMMAND_OUTPUT_LIMIT"):
            smoke.run_bounded([sys.executable, "-c", "import sys;sys.stdout.write('x'*600000)"], timeout=5)
        with self.assertRaisesRegex(smoke.SmokeError, "COMMAND_TIMEOUT"):
            smoke.run_bounded([sys.executable, "-c", "import time;time.sleep(5)"], timeout=0.05)


@unittest.skipIf(BUILD_DIR is None, "Run test_smoke_bundle.py with the existing build directory")
class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="docksr-smoke-tests-")
        cls.base = Path(cls.scratch.name)
        cls.pristine = cls.base / "pristine"
        builder.build_bundle(BUILD_DIR, cls.pristine)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=self.base)
        self.directory = Path(self.temp.name)
        self.bundle = self.directory / "moved bundle with spaces"
        shutil.copytree(self.pristine, self.bundle)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        return subprocess.run([sys.executable, "-B", str(self.bundle / "docksr-smoke"), *map(str, args)],
                              capture_output=True, text=True, timeout=50, cwd=self.directory)

    def test_relocated_cpu_selftest_and_status_are_real_cpu(self):
        status = self.directory / "status.json"
        result = self.invoke("--self-test", "--dump-status-json", status)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["evidence"], "REAL_CPU")
        self.assertEqual(report["frames_processed"], 0, "In-memory self-test must not claim published frames")
        self.assertIsNone(report["dimensions"]["actual"])
        self.assertIsNone(report["timings_ms"]["gpu"])
        self.assertEqual(json.loads(status.read_text())["evidence"], "REAL_CPU")
        self.assertEqual(stat.S_IMODE(status.stat().st_mode), 0o600)
        again = self.invoke("--self-test", "--dump-status-json", status)
        self.assertEqual(again.returncode, 0, "Existing own status must support safe atomic replacement")
        smoke.verify_bundle(self.bundle)

    def test_manifest_has_hashes_roles_and_no_absolute_source_path(self):
        manifest = smoke.verify_bundle(self.bundle)
        self.assertNotIn(str(ROOT), json.dumps(manifest))
        self.assertEqual(manifest["runtime"]["target_abi_validation"], "UNTESTED")
        self.assertTrue(manifest["runtime"]["binaries"]["bin/docksr-scale"]["needed"])
        for entry in manifest["files"]:
            self.assertEqual(entry["sha256"], smoke.sha256(self.bundle / entry["path"]))
        self.assertFalse(any(".so" in entry["path"] or "model" in entry["path"] for entry in manifest["files"]))

    def test_modified_missing_unexpected_files_and_directories_are_rejected(self):
        path = self.bundle / "share/docksr/reference.ppm"
        original = path.read_bytes()
        path.write_bytes(original + b"x")
        with self.assertRaises(smoke.SmokeError): smoke.verify_bundle(self.bundle)
        path.write_bytes(original)
        path.unlink()
        with self.assertRaises(smoke.SmokeError): smoke.verify_bundle(self.bundle)
        path.write_bytes(original); path.chmod(0o600)
        unexpected = self.bundle / "unexpected"
        unexpected.write_text("extra")
        with self.assertRaises(smoke.SmokeError): smoke.verify_bundle(self.bundle)
        unexpected.unlink(); unexpected.mkdir()
        with self.assertRaises(smoke.SmokeError): smoke.verify_bundle(self.bundle)

    def test_symlinks_hardlinks_and_escaping_manifest_paths_are_rejected(self):
        path = self.bundle / "share/docksr/reference.ppm"
        path.unlink(); path.symlink_to(self.pristine / "share/docksr/reference.ppm")
        with self.assertRaises(smoke.SmokeError): smoke.verify_bundle(self.bundle)
        path.unlink(); os.link(self.pristine / "share/docksr/reference.ppm", path)
        with self.assertRaises(smoke.SmokeError): smoke.verify_bundle(self.bundle)
        path.unlink(); shutil.copyfile(self.pristine / "share/docksr/reference.ppm", path); path.chmod(0o600)
        manifest_path = self.bundle / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["path"] = "../escape"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(smoke.SmokeError): smoke.verify_bundle(self.bundle)

    def test_existing_bundle_status_and_archive_are_preserved(self):
        with self.assertRaises(RuntimeError): builder.build_bundle(BUILD_DIR, self.bundle)
        for flag, name in (("--dump-status-json", "status.json"), ("--diagnostics-export", "existing.tar.gz")):
            target = self.directory / name
            target.write_bytes(b"owner file")
            result = self.invoke("--self-test", flag, target) if flag == "--dump-status-json" else self.invoke(flag, target)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), b"owner file")

    def test_private_sanitized_diagnostics_archive(self):
        status = json.loads((ROOT / "tests/fixtures/runtime_cpu.json").read_text())
        status.update(runtime_state="ERROR", last_error={"code": "PRIVATE_SERIAL", "message": "/home/secret-owner/API_TOKEN-value"})
        status_path = self.directory / "local status.json"
        status_path.write_text(json.dumps(status))
        archive_path = self.directory / "diagnostics.tar.gz"
        result = self.invoke("--diagnostics-export", archive_path, "--status-json", status_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(stat.S_IMODE(archive_path.stat().st_mode), 0o600)
        with tarfile.open(archive_path, "r:gz") as archive:
            self.assertEqual(set(archive.getnames()), {"bundle.json", "status.json", "self-test.json", "inventory.json"})
            for member in archive.getmembers():
                self.assertTrue(member.isfile()); self.assertEqual(member.mode, 0o600)
                self.assertEqual(member.uname, ""); self.assertEqual(member.gname, "")
                payload = archive.extractfile(member).read().decode()
                for private in ("PRIVATE_SERIAL", "secret-owner", "API_TOKEN-value", str(ROOT)):
                    self.assertNotIn(private, payload)
                json.loads(payload)

    def test_symlink_outputs_and_arbitrary_preview_arguments_are_rejected(self):
        owner = self.directory / "owner"
        owner.write_text("preserve")
        alias = self.directory / "alias.tar.gz"; alias.symlink_to(owner)
        self.assertNotEqual(self.invoke("--diagnostics-export", alias).returncode, 0)
        self.assertEqual(owner.read_text(), "preserve")
        self.assertNotEqual(self.invoke("--preview", "--input", "/private/file").returncode, 0)

    def test_unexpected_python_module_is_rejected_before_it_can_execute(self):
        marker = self.directory / "unexpected-module-ran"
        for name in ("json.py", "__future__.py", "os.py"):
            with self.subTest(module=name):
                injected = self.bundle / name
                injected.write_text(f"open({str(marker)!r},'w').write('executed')\n")
                result = self.invoke("--self-test")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists(), "Unmanifested module ran before bundle verification")
                injected.unlink()

    def test_builder_rejects_a_symlinked_binary(self):
        fake_build = self.directory / "build"
        (fake_build / "bin").mkdir(parents=True)
        (fake_build / "bin/docksr-scale").symlink_to(BUILD_DIR / "bin/docksr-scale")
        destination = self.directory / "new rejected bundle"
        with self.assertRaises(RuntimeError): builder.build_bundle(fake_build, destination)
        self.assertFalse(destination.exists())

    def test_bundle_permissions_do_not_depend_on_a_private_shell_umask(self):
        destination = self.directory / "bundle-from-umask-022"
        previous = os.umask(0o022)
        try:
            builder.build_bundle(BUILD_DIR, destination)
        finally:
            os.umask(previous)
        smoke.verify_bundle(destination)
        self.assertEqual(stat.S_IMODE((destination / "share").stat().st_mode), 0o700)

    def test_atomic_export_preserves_a_destination_created_during_collection(self):
        destination = self.directory / "raced-export.tar.gz"
        real_link = os.link
        def concurrent_owner_file(source, target, **kwargs):
            Path(target).write_bytes(b"concurrent owner file")
            return real_link(source, target, **kwargs)
        with patch.object(smoke.os, "link", side_effect=concurrent_owner_file):
            with self.assertRaises(FileExistsError):
                smoke.export_diagnostics(self.bundle, smoke.verify_bundle(self.bundle), destination, None)
        self.assertEqual(destination.read_bytes(), b"concurrent owner file")
        self.assertEqual(list(self.directory.glob(".docksr-export-*")), [])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tests/test_smoke_bundle.py EXISTING_BUILD_DIR")
    BUILD_DIR = Path(sys.argv.pop()).resolve()
    # unittest decorators are evaluated at import; required CLI tests now have their binary source.
    BundleTests.__unittest_skip__ = False
    unittest.main()
