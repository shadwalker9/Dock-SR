"""Owned-byte fixtures test import safety; they are not AMD model validation."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import import_sesr as importer


class ImportSesrTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="docksr-owned-import-")
        self.directory = Path(self.temp.name)
        self.source = self.directory / "owned-fixture.bin"
        self.data = b"Owned byte fixture; deliberately not an ONNX or AMD model.\n"
        self.source.write_bytes(self.data)
        self.destination = self.directory / "new-import"
        self.identity = importer.ArtifactIdentity(
            "owned-test-fixture-not-amd", "owned-fixture-v1", "owned-fixture.bin",
            "https://example.invalid/owned-test-fixture", len(self.data),
            hashlib.sha256(self.data).hexdigest(), "owned_test_fixture_bytes_only")

    def tearDown(self):
        self.temp.cleanup()

    def import_owned(self, **kwargs):
        return importer._import_verified(kwargs.get("source", self.source),
                                         kwargs.get("destination", self.destination),
                                         kwargs.get("identity", self.identity))

    def test_owned_fixture_import_receipt_hash_and_private_modes(self):
        receipt = self.import_owned()
        self.assertEqual(receipt["classification"], "VERIFIED_LOCAL")
        self.assertEqual(receipt["model_id"], "owned-test-fixture-not-amd")
        self.assertEqual(receipt["verification_scope"], "owned_test_fixture_bytes_only")
        self.assertEqual(receipt["artifact"]["actual_sha256"], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(receipt["artifact"]["actual_size_bytes"], len(self.data))
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual((self.destination / self.identity.filename).read_bytes(), self.data)
        self.assertEqual(json.loads((self.destination / "verification.json").read_text()), receipt)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        self.assertEqual({path.name for path in self.destination.iterdir()}, {self.identity.filename, "verification.json"})
        for path in self.destination.iterdir(): self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(receipt["graph_inspection"], "NOT_RUN")
        self.assertEqual(receipt["cpu_reference"], "NOT_RUN")
        self.assertFalse(receipt["npu_executed"])
        self.assertFalse(receipt["hardware_execution_verified"])
        self.assertFalse(receipt["license_clearance_verified"])
        self.assertEqual(receipt["source"]["original_retrieval"], "NOT_ATTESTED")

    def test_size_and_hash_mismatches_leave_no_destination(self):
        for data, code in ((b"short", "SIZE_MISMATCH"), (b"x" * len(self.data), "HASH_MISMATCH")):
            with self.subTest(code=code):
                self.source.write_bytes(data)
                with self.assertRaises(importer.ImportFailure) as raised: self.import_owned()
                self.assertEqual(raised.exception.code, code)
                self.assertFalse(self.destination.exists())

    def test_missing_source_and_missing_parent_do_not_create_output(self):
        self.source.unlink()
        with self.assertRaises(FileNotFoundError): self.import_owned()
        self.assertFalse(self.destination.exists())
        self.source.write_bytes(self.data)
        missing = self.directory / "missing-parent" / "import"
        with self.assertRaises(FileNotFoundError): self.import_owned(destination=missing)
        self.assertFalse(missing.parent.exists())

    def test_existing_directory_file_and_dangling_symlink_never_overwrite(self):
        self.destination.mkdir()
        canary = self.destination / "owner.txt"
        canary.write_text("preserve")
        with self.assertRaisesRegex(importer.ImportFailure, "new directory"): self.import_owned()
        self.assertEqual(canary.read_text(), "preserve")
        canary.unlink(); self.destination.rmdir()
        self.destination.write_text("owner-file")
        with self.assertRaises(importer.ImportFailure): self.import_owned()
        self.assertEqual(self.destination.read_text(), "owner-file")
        self.destination.unlink()
        self.destination.symlink_to(self.directory / "missing")
        with self.assertRaises(importer.ImportFailure): self.import_owned()
        self.assertTrue(self.destination.is_symlink())

    def test_source_symlink_fifo_and_directory_are_rejected(self):
        link = self.directory / "link"
        link.symlink_to(self.source)
        with self.assertRaises(OSError): self.import_owned(source=link)
        fifo = self.directory / "pipe"
        os.mkfifo(fifo, 0o600)
        with self.assertRaisesRegex(importer.ImportFailure, "regular"): self.import_owned(source=fifo)
        with self.assertRaisesRegex(importer.ImportFailure, "regular"): self.import_owned(source=self.directory)
        self.assertFalse(self.destination.exists())

    def test_parent_symlinks_traversal_and_writable_destination_parent_reject(self):
        link = self.directory / "link-parent"
        link.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(importer.ImportFailure): self.import_owned(destination=link / "new")
        with self.assertRaises(importer.ImportFailure): self.import_owned(source=link / self.source.name)
        with self.assertRaises(importer.ImportFailure):
            self.import_owned(destination=self.directory / "unused" / ".." / "new")
        self.directory.chmod(0o777)
        try:
            with self.assertRaisesRegex(importer.ImportFailure, "not group/world writable"): self.import_owned()
        finally: self.directory.chmod(0o700)

    def test_git_directory_and_linked_checkout_markers_reject(self):
        checkout = self.directory / "checkout"
        checkout.mkdir(mode=0o700)
        marker = checkout / ".git"
        for as_file in (False, True):
            if as_file: marker.write_text("gitdir: /unrelated/metadata\n")
            else: marker.mkdir()
            with self.subTest(linked_checkout=as_file), self.assertRaises(importer.ImportFailure) as raised:
                self.import_owned(destination=checkout / "model-import")
            self.assertEqual(raised.exception.code, "DESTINATION_INSIDE_GIT")
            marker.unlink() if as_file else marker.rmdir()
        with self.assertRaises(importer.ImportFailure) as raised:
            self.import_owned(destination=ROOT / "results" / "must-not-import-test")
        self.assertEqual(raised.exception.code, "DESTINATION_INSIDE_GIT")
        self.assertFalse((ROOT / "results/must-not-import-test").exists())

    def test_generic_helper_rejects_unsafe_or_oversized_identity(self):
        for kwargs in ({"filename":"../escape"}, {"filename":"verification.json"},
                       {"size_bytes":1048577}, {"size_bytes":True}, {"sha256":"not-a-hash"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(importer.ImportFailure):
                self.import_owned(identity=replace(self.identity, **kwargs))

    def test_git_metadata_destination_name_rejects_before_creation(self):
        destination = self.directory / ".git"
        with self.assertRaises(importer.ImportFailure) as raised:
            self.import_owned(destination=destination)
        self.assertEqual(raised.exception.code, "DESTINATION_INSIDE_GIT")
        self.assertFalse(destination.exists())

    def test_empty_readonly_cloud_guard_is_not_a_git_checkout(self):
        marker = self.directory / ".git"
        marker.mkdir(mode=0o555)
        try:
            self.assertEqual(self.import_owned()["model_id"], "owned-test-fixture-not-amd")
        finally: marker.chmod(0o700)

    def test_partial_write_failure_cleans_only_created_files(self):
        original = importer._write_new
        def fail_receipt(directory_fd, name, data, created_files):
            if name == "verification.json": raise OSError("owned injected failure")
            return original(directory_fd, name, data, created_files)
        with patch.object(importer, "_write_new", side_effect=fail_receipt):
            with self.assertRaises(OSError): self.import_owned()
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_concurrent_owner_file_that_blocks_write_is_preserved(self):
        original = importer._write_new
        def add_owner_receipt(directory_fd, name, data, created_files):
            if name == "verification.json":
                descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
                with os.fdopen(descriptor, "wb") as stream: stream.write(b"owner-file")
            return original(directory_fd, name, data, created_files)
        with patch.object(importer, "_write_new", side_effect=add_owner_receipt):
            with self.assertRaises(FileExistsError): self.import_owned()
        self.assertEqual((self.destination / "verification.json").read_bytes(), b"owner-file")
        self.assertEqual(list(self.destination.iterdir()), [self.destination / "verification.json"])

    def test_bytes_hashed_are_the_bytes_written_if_source_changes_later(self):
        original = importer._write_new
        def change_source(directory_fd, name, data, created_files):
            self.source.write_bytes(b"changed after verification")
            return original(directory_fd, name, data, created_files)
        with patch.object(importer, "_write_new", side_effect=change_source): receipt = self.import_owned()
        self.assertEqual((self.destination / self.identity.filename).read_bytes(), self.data)
        self.assertEqual(receipt["artifact"]["actual_sha256"], hashlib.sha256(self.data).hexdigest())

    def run_cli(self, source=None, *extra):
        return subprocess.run([sys.executable, str(ROOT / "scripts/import_sesr.py"),
                               str(self.source if source is None else source), "--destination", str(self.destination), *extra],
                              text=True, capture_output=True, timeout=10)

    def test_real_cli_fixed_pin_rejects_html_lfs_pointer_and_wrong_hash(self):
        for data, code in ((b"<html>download error</html>", "SIZE_MISMATCH"),
                           (b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 107131\n", "SIZE_MISMATCH"),
                           (b"x" * 107131, "HASH_MISMATCH")):
            with self.subTest(code=code):
                self.source.write_bytes(data)
                result = self.run_cli()
                self.assertEqual(result.returncode, 1, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "ERROR")
                self.assertEqual(report["error"]["code"], code)
                self.assertFalse(report["npu_executed"])
                self.assertFalse(self.destination.exists())
        self.assertEqual(importer.PINNED_IDENTITY.size_bytes, 107131)
        self.assertEqual(importer.PINNED_IDENTITY.sha256, "63d2600fa41b21c2326d1740f75486f24e0b791c490ea73a898bf64fdd429ab1")
        self.assertNotEqual(self.run_cli(None, "--expected-sha256", self.identity.sha256).returncode, 0)

    def test_real_cli_missing_file_returns_sanitized_json_and_no_execution(self):
        result = self.run_cli(self.directory / "missing-secret-name")
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["error"]["code"], "IMPORT_IO_ERROR")
        self.assertNotIn("missing-secret-name", result.stdout)
        self.assertEqual(report["graph_inspection"], "NOT_RUN")
        self.assertEqual(report["cpu_reference"], "NOT_RUN")
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
