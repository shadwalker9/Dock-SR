#!/usr/bin/env python3
"""Exercise a moved Vulkan benchmark bundle using its packaged shader.

Usage: python3 tests/test_shader_relocation.py /path/to/docksr-bench /path/to/scale.comp.spv

Only real Vulkan execution is accepted; exit 77 means no usable Vulkan device.
The tests never change the input binary/shader or the original build tree.
For a stronger isolated-build check, supply a saved shader copy while that
build's original generated shader is temporarily unavailable.
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ShaderRelocationTests(unittest.TestCase):
    binary = None
    shader = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="docksr-shader-relocation-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        original = self.directory / "initial-location" / "bundle"
        (original / "bin").mkdir(parents=True)
        (original / "share/docksr").mkdir(parents=True)
        shutil.copy2(self.binary, original / "bin/docksr-bench")
        shutil.copy2(self.shader, original / "share/docksr/scale.comp.spv")
        (self.directory / "different-location").mkdir()
        self.bundle = self.directory / "different-location/moved-bundle"
        original.rename(self.bundle)

    def invoke(self):
        return subprocess.run([
            str(self.bundle / "bin/docksr-bench"),
            "--input", "3x2", "--output", "9x6", "--filter", "nearest",
            "--warmup", "0", "--iterations", "1",
            "--artifact-dir", str(self.directory / "artifacts"),
        ], capture_output=True, text=True, timeout=30, check=False,
            cwd=self.directory)

    def test_moved_bundle_executes_with_packaged_shader(self):
        process = self.invoke()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        report = json.loads((self.directory / "artifacts/result.json").read_text())
        self.assertIs(report["correctness"]["passed"], True)
        self.assertEqual(report["configuration"]["output_width"], 9)
        self.assertEqual(report["configuration"]["output_height"], 6)

    def test_missing_packaged_shader_cannot_borrow_build_shader(self):
        (self.bundle / "share/docksr/scale.comp.spv").unlink()
        process = self.invoke()
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("Cannot open packaged shader:", process.stderr)
        self.assertFalse((self.directory / "artifacts/result.json").exists())

    def test_corrupt_packaged_shader_is_rejected(self):
        (self.bundle / "share/docksr/scale.comp.spv").write_bytes(b"bad!")
        process = self.invoke()
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("Invalid or truncated SPIR-V shader", process.stderr)
        self.assertFalse((self.directory / "artifacts/result.json").exists())


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    ShaderRelocationTests.binary = Path(sys.argv[1]).resolve()
    ShaderRelocationTests.shader = Path(sys.argv[2]).resolve()
    if not ShaderRelocationTests.binary.is_file() or not ShaderRelocationTests.shader.is_file():
        print("Binary and shader inputs must exist", file=sys.stderr)
        return 2
    probe = subprocess.run([str(ShaderRelocationTests.binary), "--probe"],
                           capture_output=True, text=True, timeout=30, check=False)
    if probe.returncode == 77:
        print("SKIP: no usable Vulkan implementation", file=sys.stderr)
        return 77
    if probe.returncode:
        print(probe.stdout + probe.stderr, file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ShaderRelocationTests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
