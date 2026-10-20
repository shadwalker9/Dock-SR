#!/usr/bin/env python3
"""Run an actual authenticated Xvfb window; never substitute a rendered mock.

Optional integration check. Exit 77 when Xvfb/xdotool are unavailable. A real
desktop/compositor, physical GPU, SteamOS and Bazzite remain separate gates.
"""
import argparse
import json
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import tempfile
import time


def eventually(operation, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = operation()
        if result:
            return result
        time.sleep(0.04)
    raise AssertionError(f"Timed out: {description}")


def read_status(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def ppm(path):
    data = path.read_bytes()
    magic, geometry, maximum, pixels = data.split(b"\n", 3)
    assert magic == b"P6" and maximum == b"255"
    width, height = map(int, geometry.split())
    assert len(pixels) == width * height * 3
    return width, height, pixels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args()
    xvfb, xdotool = shutil.which("Xvfb"), shutil.which("xdotool")
    if not xvfb or not xdotool:
        print("SKIP: actual-window checks need Xvfb and xdotool")
        return 77
    temporary = tempfile.TemporaryDirectory(prefix="docksr-window-") if not args.artifact_dir else None
    folder = Path(temporary.name) if temporary else args.artifact_dir.resolve()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    # A private MIT cookie; no listening TCP socket, no -ac/public X server.
    authority = folder / "Xauthority"
    cookie = os.urandom(16)
    fields = (b"", b"", b"MIT-MAGIC-COOKIE-1", cookie)
    authority.write_bytes(struct.pack("!H", 65535) + b"".join(struct.pack("!H", len(field)) + field for field in fields))
    authority.chmod(0o600)
    read_fd, write_fd = os.pipe()
    environment = os.environ.copy()
    environment["XAUTHORITY"] = str(authority)
    server_log = (folder / "xvfb.log").open("w")
    server = subprocess.Popen([xvfb, "-displayfd", str(write_fd), "-screen", "0", "1440x1000x24",
                               "-nolisten", "tcp", "-auth", str(authority), "-noreset"],
                              pass_fds=(write_fd,), stdout=server_log, stderr=server_log, env=environment)
    os.close(write_fd)
    app = None
    try:
        if not select.select([read_fd], [], [], 15)[0]:
            raise AssertionError("Xvfb failed to announce display; inspect xvfb.log")
        number = os.read(read_fd, 32).decode().strip()
        assert number.isdigit(), "Xvfb exited before announcing display"
        environment["DISPLAY"] = ":" + number
        status_path, capture_path = folder / "status.json", folder / "actual-window.ppm"
        source = folder / "raw-720.ppm"
        # Own controlled raw input: gradient plus fine checker regions, not a UI mock.
        raw = bytearray(1280 * 720 * 3)
        for y in range(720):
            for x in range(1280):
                offset = (y * 1280 + x) * 3
                raw[offset:offset + 3] = bytes((x % 256, y % 256, 255 if (x + y) % 2 else 0))
        source.write_bytes(b"P6\n1280 720\n255\n" + raw)
        source.chmod(0o600)
        stdout = (folder / "preview.stdout").open("w")
        stderr = (folder / "preview.stderr").open("w")
        command = [str(args.binary.resolve()), "--input", str(source), "--dump-status-json", str(status_path),
                   "--capture", str(capture_path)]
        app = subprocess.Popen(command, env=environment, stdout=stdout, stderr=stderr)

        def xd(*arguments):
            result = subprocess.run([xdotool, *map(str, arguments)], env=environment,
                                    text=True, capture_output=True, timeout=10)
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        def search():
            result = subprocess.run([xdotool, "search", "--name", "^Dock SR PREVIEW"],
                                    env=environment, text=True, capture_output=True, timeout=5)
            return result.stdout.strip().splitlines()[0] if result.returncode == 0 else None

        window = eventually(search, "executed preview window")
        initial = eventually(lambda: read_status(status_path), "first completed CPU output")
        assert initial["evidence"] == "REAL_CPU" and initial["frames_processed"] == 1
        assert initial["dimensions"]["actual"]["output"] == {"width": 1920, "height": 1080}

        # Actual X11 resize/toggle events: they must not run the scaler again.
        xd("windowsize", window, "1100", "820")
        xd("key", "--window", window, "d", "d", "a", "a", "z")
        xd("key", "--window", window, "c")
        eventually(capture_path.exists, "actual XGetImage capture")
        captured_width, captured_height, pixels = ppm(capture_path)
        assert (captured_width, captured_height) == (1100, 820)
        assert read_status(status_path)["frames_processed"] == 1
        # Z requests matched 1:1 output crops. Independently check real nearest
        # output pixels in left pane against the preserved raw input.
        pane_width = (captured_width - 54) // 2
        pane_height = min(pane_width * 9 // 16, captured_height - 410)
        crop_x, crop_y = (1920 - pane_width) // 2, (1080 - pane_height) // 2
        for px, py in ((25, 25), (113, 71), (300, 150)):
            sx = ((2 * (crop_x + px) + 1) * 1280) // (2 * 1920)
            sy = ((2 * (crop_y + py) + 1) * 720) // (2 * 1080)
            actual = ((132 + py) * captured_width + 18 + px) * 3
            expected = (sy * 1280 + sx) * 3
            assert pixels[actual:actual + 3] == raw[expected:expected + 3], "captured pixels did not pass through real nearest scaling"
        assert any(pixels[((132 + py) * captured_width + 18 + px) * 3:][:3] !=
                   pixels[((132 + py) * captured_width + pane_width + 36 + px) * 3:][:3]
                   for px, py in ((25, 25), (113, 71), (300, 150))), "nearest/bilinear A/B should differ"
        cpu_capture = folder / "actual-window-cpu-1080.ppm"
        capture_path.rename(cpu_capture)

        xd("key", "--window", window, "m")
        nearest = eventually(lambda: (value if (value := read_status(status_path)) and value["frames_processed"] == 2 else None), "method change")
        assert "nearest" in nearest["backend_name"]
        xd("key", "--window", window, "o")
        four_k = eventually(lambda: (value if (value := read_status(status_path)) and value["frames_processed"] == 3 else None), "4K output change")
        assert four_k["dimensions"]["actual"]["output"] == {"width": 3840, "height": 2160}
        xd("key", "--window", window, "v")
        vulkan = eventually(lambda: (value if (value := read_status(status_path)) and value["frames_processed"] == 4 else None), "Vulkan or explicit fallback", timeout=25)
        assert vulkan["npu"]["device_status"] == "NOT_TESTED" and vulkan["timings_ms"]["npu"] is None
        assert vulkan["evidence"] in ("REAL_GPU", "SOFTWARE_VULKAN", "REAL_CPU")
        if vulkan["evidence"] == "REAL_CPU":
            assert vulkan["runtime_state"] == "FALLBACK" and vulkan["last_error"]
        else:
            assert "vulkan" in vulkan["backend_name"]
        xd("key", "--window", window, "m")
        bilinear = eventually(lambda: (value if (value := read_status(status_path)) and value["frames_processed"] == 5 else None), "4K selected bilinear")
        assert "bilinear" in bilinear["backend_name"]
        assert bilinear["dimensions"]["actual"]["output"] == {"width": 3840, "height": 2160}
        xd("key", "--window", window, "c")
        eventually(capture_path.exists, "actual selected-backend 4K window capture")
        ppm(capture_path)
        xd("key", "--window", window, "o")
        final = eventually(lambda: (value if (value := read_status(status_path)) and value["frames_processed"] == 6 else None), "selected backend 1080p bilinear")
        assert final["dimensions"]["actual"]["output"] == {"width": 1920, "height": 1080}
        if final["evidence"] != "REAL_CPU":
            assert final["evidence"] == vulkan["evidence"]
        for line in (folder / "preview.stdout").read_text().splitlines():
            assert json.loads(line)["document_type"] == "docksr_status"
        # Only KeyPress is needed: sending KeyRelease after the app destroys its
        # window races xdotool's X_SendEvent against an already-closed window.
        xd("keydown", "--window", window, "q")
        assert app.wait(timeout=10) == 0
        stdout.close(); stderr.close()
        result = {"checks_passed": 6, "checks_failed": 0, "display": "authenticated Xvfb virtual X11",
                  "capture": str(capture_path), "cpu_1080_capture": str(cpu_capture),
                  "command": command, "four_k_status": bilinear, "final_status": final,
                  "limitations": ["No physical display/GPU or game integration is established.",
                                  "Preview timings are not game FPS or efficiency benchmarks."]}
        (folder / "window-result.json").write_text(json.dumps(result, indent=2) + "\n")
        print("PASS: 6 actual-window checks (launch/pixels/A-B/redraw/mode-size-backend/quit)")
        print(f"Executed-window capture: {capture_path}" if not temporary else "Temporary executed-window capture validated")
        return 0
    finally:
        os.close(read_fd)
        if app and app.poll() is None:
            app.terminate()
            try: app.wait(timeout=5)
            except subprocess.TimeoutExpired: app.kill(); app.wait(timeout=5)
        server.terminate()
        try: server.wait(timeout=5)
        except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=5)
        server_log.close()
        if temporary: temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
