#!/usr/bin/env python3
"""Run an authenticated, synthetic Gamescope ON/BYPASS/ON virtual-window probe.

This does not run a game, measure physical GPU/NPU performance, or install
Gamescope. Source the private dependency environment before invoking it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time


NPU_FIELDS = ("npu_device_detected", "npu_runtime_ready",
              "npu_inference_verified", "npu_game_frames_consumed")
INPUT = {"width": 1280, "height": 720}
OUTPUT = {"width": 3840, "height": 2160}


class ProbeError(RuntimeError):
    pass


def require_outside_git(path: Path) -> None:
    """Keep captures/logs outside source repositories, including linked trees."""
    for parent in (path, *path.parents):
        marker = parent / ".git"
        if marker.is_file() or (marker.is_dir() and any(marker.iterdir())):
            raise ProbeError(f"Evidence destination is inside a Git checkout: {parent}")


class StatusReader:
    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.fragment = ""
        self.observed: list[dict] = []

    def poll(self) -> list[dict]:
        with self.path.open(errors="replace") as stream:
            stream.seek(self.offset)
            self.fragment += stream.read()
            self.offset = stream.tell()
        lines = self.fragment.split("\n")
        self.fragment = lines.pop()
        found = []
        for line in lines:
            marker = "DOCKSR_STATUS "
            if marker not in line:
                continue
            payload = line.split(marker, 1)[1]
            try:
                value, _ = json.JSONDecoder().raw_decode(payload)
            except (ValueError, TypeError):
                raise ProbeError("Malformed native DOCKSR_STATUS JSON") from None
            if not isinstance(value, dict):
                raise ProbeError("Native status was not an object")
            if any(value.get(field) is not False for field in NPU_FIELDS):
                raise ProbeError("Native status omitted an NPU denial or asserted NPU activity")
            found.append(value)
        self.observed.extend(found)
        return found


def run(argv: list[str], *, env: dict, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env, check=True, capture_output=True,
                          text=True, timeout=timeout)


def require_tool(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise ProbeError(f"Required tool unavailable: {name}")
    return value


def compile_helpers(output: Path, env: dict) -> tuple[Path, Path]:
    sources = Path(__file__).resolve().parent / "fixtures"
    flags = shlex.split(run([require_tool("pkg-config"), "--cflags", "--libs", "x11"], env=env).stdout)
    compiler = require_tool("cc")
    binaries = []
    for name in ("synthetic_x11", "capture_x11"):
        binary = output / name
        command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                   str(sources / f"{name}.c"), "-o", str(binary), *flags]
        result = run(command, env=env)
        (output / f"{name}.build.log").write_text(result.stdout + result.stderr)
        binaries.append(binary)
    return binaries[0], binaries[1]


def ensure_running(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is not None:
            raise ProbeError(f"Owned process {process.pid} exited with {process.returncode}")


def wait_for(predicate, processes: list[subprocess.Popen], timeout: float, reason: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ensure_running(processes)
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise ProbeError(reason)


def stop_owned(process: subprocess.Popen) -> dict:
    # Every process here was started with start_new_session=True by this probe.
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=6)
    return {"pid": process.pid, "exit_code": process.returncode}


def fixture_identity(log: Path) -> dict | None:
    for line in log.read_text(errors="replace").splitlines():
        if "DOCKSR_FIXTURE " in line:
            return json.loads(line.split("DOCKSR_FIXTURE ", 1)[1])
    return None


def socket_name(runtime: Path) -> str | None:
    for candidate in sorted(runtime.glob("gamescope-*")):
        info = candidate.lstat()
        if stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid():
            return candidate.name
    return None


def native_state(reader: StatusReader, request_id: int, mode: str, generation: int) -> dict | None:
    for value in reversed(reader.poll()):
        if (value.get("last_control_request_id") != request_id or
                value.get("mode_requested") != mode or value.get("mode_effective") != mode or
                value.get("control_ack_state") != "PRESENTED"):
            continue
        current = value.get("configuration_generation", 0)
        if (current <= generation or value.get("last_frame_generation") != current or
                value.get("input_extent") != INPUT or value.get("output_extent") != OUTPUT or
                value.get("frame_presented_count", 0) <= 0):
            continue
        active = mode == "DOCKSR_ACTIVE"
        if (value.get("filter_selected") is active and
                value.get("filter_dispatched") is active and
                value.get("filter_output_presented") is active):
            return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gamescope", type=Path,
                        default=Path("/workspace/DockSR-gamescope-lab/build/src/gamescope"))
    parser.add_argument("--gamescopectl", type=Path,
                        default=Path("/workspace/DockSR-gamescope-lab/build/src/gamescopectl"))
    parser.add_argument("--output", type=Path, required=True,
                        help="New private output directory; never a tracked source directory")
    parser.add_argument("--timeout", type=float, default=45,
                        help="Seconds allowed per asynchronous startup/control phase")
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between1 and120 seconds")
    os.umask(0o077)
    output = args.output.resolve()
    try:
        require_outside_git(output)
    except ProbeError as error:
        parser.error(str(error))
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = dict(os.environ)
    processes: list[subprocess.Popen] = []
    handles = []
    reader = None
    report = {"schema_version": 1, "kind": "SYNTHETIC_NOT_GAME",
              "evidence_class": "NOT_RUN", "result": "BLOCKED",
              "physical_gpu": "NOT_RUN", "real_npu": False,
              "live_game": "NOT_RUN", "alpha_verified": False,
              "requested_input_extent": INPUT, "requested_output_extent": OUTPUT,
              "input_extent": None, "output_extent": None,
              "captures": [], "owned_process_cleanup": [],
              "phase": "helpers_compile", "g0c": "NOT_RUN", "g0d": "NOT_RUN"}
    try:
        fixture, capture = compile_helpers(output, env)
        report["helpers_compile"] = "PASS"
        if args.compile_only:
            report["result"] = "HELPERS_BUILD_ONLY"
            return 0
        report["phase"] = "graphical_prerequisites"
        for binary in (args.gamescope, args.gamescopectl):
            if not binary.is_file() or not os.access(binary, os.X_OK):
                raise ProbeError(f"Experimental executable unavailable: {binary}")
        report["executables"] = {
            name: {"path": str(binary.resolve()),
                   "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
            for name, binary in (("gamescope", args.gamescope),
                                 ("gamescopectl", args.gamescopectl))}
        xvfb = require_tool("Xvfb")
        xauth = require_tool("xauth")
        runtime = output / "runtime"
        runtime.mkdir(mode=0o700)
        authority = runtime / "Xauthority"
        authority.touch(mode=0o600)
        # Xvfb uses its own lock as the final arbiter; avoid occupied candidates.
        display_number = next((number for number in range(91, 191)
            if not Path(f"/tmp/.X11-unix/X{number}").exists() and
            not Path(f"/tmp/.X{number}-lock").exists()), None)
        if display_number is None:
            raise ProbeError("No unoccupied Xvfb display candidate")
        display = f":{display_number}"
        # The secret is never written to logs or reports; the authority file is0600.
        run([xauth, "-f", str(authority), "add", display,
             "MIT-MAGIC-COOKIE-1", secrets.token_hex(16)], env=env)
        env.update({"DISPLAY": display, "XAUTHORITY": str(authority),
                    "XDG_RUNTIME_DIR": str(runtime), "SDL_VIDEODRIVER": "x11",
                    "DOCKSR_LAB": "1", "DOCKSR_LAB_EVIDENCE": "VIRTUAL_WINDOW"})
        xvfb_log = (output / "xvfb.log").open("w")
        handles.append(xvfb_log)
        xvfb_process = subprocess.Popen([xvfb, display, "-screen", "0", "3840x2160x24",
            "-nolisten", "tcp", "-auth", str(authority)], env=env,
            stdout=xvfb_log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(xvfb_process)

        def display_ready():
            return subprocess.run([str(capture), "--check"], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3).returncode == 0
        wait_for(display_ready, processes, args.timeout, "Authenticated Xvfb unavailable")
        unauthorized = runtime / "empty-authority"
        unauthorized.touch(mode=0o600)
        bad_env = dict(env, XAUTHORITY=str(unauthorized))
        denied = subprocess.run([str(capture), "--check"], env=bad_env,
            capture_output=True, text=True, timeout=5)
        (output / "unauthorized-connection.log").write_text(denied.stdout + denied.stderr)
        if denied.returncode == 0:
            raise ProbeError("Xvfb accepted a client without the scoped MIT cookie")
        report["unauthorized_connection_rejected"] = True
        gamescope_log = output / "gamescope.log"
        game_log_handle = gamescope_log.open("w")
        handles.append(game_log_handle)
        command = [str(args.gamescope.resolve()), "--backend", "sdl",
                   "-w", "1280", "-h", "720", "-W", "3840", "-H", "2160",
                   "-C", "1", "-F", "docksr", "--", str(fixture)]
        report["gamescope_command"] = command
        compositor = subprocess.Popen(command, env=env, stdout=game_log_handle,
            stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(compositor)
        report["phase"] = "compositor_startup"
        report["gamescope_pid"] = compositor.pid
        identity = wait_for(lambda: fixture_identity(gamescope_log), processes,
                            args.timeout, "Synthetic client did not establish its720p window")
        if (identity.get("width"), identity.get("height")) != (1280, 720):
            raise ProbeError("Actual synthetic X11 window is not1280x720")
        report["fixture"] = identity
        report["fixture_window_extent"] = INPUT
        socket_value = wait_for(lambda: socket_name(runtime), processes, args.timeout,
                                "Scoped Gamescope private socket unavailable")
        control_env = dict(env, GAMESCOPE_WAYLAND_DISPLAY=socket_value)
        reader = StatusReader(gamescope_log)
        controls = []
        report["control_requests"] = controls

        def control(payload: str):
            result = run([str(args.gamescopectl.resolve()), "docksr_lab", payload], env=control_env)
            controls.append({"request": payload, "transport_exit": result.returncode,
                             "note": "Transport return alone is not an effective-state acknowledgement"})

        # CLI -F docksr reserves bootstrap request1. Do not reuse it.
        # The three mode mutations use2/3/4; final STATUS consumes5.
        report["phase"] = "live_switch"
        generation = -1
        session_id = None
        for label, operation, request_id, mode in (
                ("on-first", "ON", 2, "DOCKSR_ACTIVE"),
                ("bypass", "BYPASS", 3, "BYPASS"),
                ("on-again", "ON", 4, "DOCKSR_ACTIVE")):
            control(f"{operation} {request_id}")
            status = wait_for(lambda: native_state(reader, request_id, mode, generation),
                processes, args.timeout, f"No frame-presented acknowledgement for{operation}{request_id}")
            if session_id is None:
                session_id = status.get("session_id")
            if not session_id or status.get("session_id") != session_id:
                raise ProbeError("Compositor session identity changed during live switching")
            generation = status["configuration_generation"]
            # These become actual compositor extents only after its native
            # frame observation agrees; launch arguments alone are insufficient.
            report["input_extent"] = status["input_extent"]
            report["output_extent"] = status["output_extent"]
            # Only static owned pixels are drawn. Let the submitted window update
            # settle before asking the independent parent X server for its pixels.
            time.sleep(0.2)
            ensure_running(processes)
            image = output / f"{label}.ppm"
            result = run([str(capture), str(compositor.pid), "3840", "2160", str(image)],
                         env=env, timeout=20)
            metadata = json.loads(result.stdout)
            pixels = image.read_bytes()
            if not pixels.startswith(b"P6\n3840 2160\n255\n") or len(pixels) != 3840 * 2160 * 3 + 17:
                raise ProbeError("Capture did not contain exact3840x2160 RGB pixels")
            report["captures"].append({"label": label, "path": image.name,
                "sha256": hashlib.sha256(pixels).hexdigest(), "bytes": len(pixels),
                "native_status_before_capture": status, "capture": metadata})
        control("STATUS 5")
        hashes = [item["sha256"] for item in report["captures"]]
        report["phase"] = "pixel_verification"
        report["same_pid_and_session"] = True
        report["session_id"] = session_id
        report["distinct_on_bypass"] = hashes[0] != hashes[1]
        report["deterministic_on_roundtrip"] = hashes[0] == hashes[2]
        if hashes[0] == hashes[1] or hashes[0] != hashes[2]:
            raise ProbeError("Actual captured pixels did not establish distinct deterministic ON/BYPASS/ON")
        report["evidence_class"] = "VIRTUAL_WINDOW"
        report["result"] = "SYNTHETIC_LIVE_SWITCH_PASS"
        report["g0c"] = report["g0d"] = "PASS"
        report["phase"] = "complete"
        return 0
    except (ProbeError, OSError, subprocess.SubprocessError, ValueError) as error:
        report["error"] = str(error)
        if report["phase"] in ("live_switch", "pixel_verification"):
            report["result"] = "FAILED"
            report["g0c"] = "PARTIAL" if report["captures"] else "BLOCKED"
            report["g0d"] = "FAIL"
        elif report["phase"] == "compositor_startup":
            report["g0c"] = report["g0d"] = "BLOCKED"
        print(f"Virtual probe blocked/failed: {error}", file=sys.stderr)
        return 1
    finally:
        for process in reversed(processes):
            report["owned_process_cleanup"].append(stop_owned(process))
        for handle in handles:
            handle.close()
        log = output / "gamescope.log"
        if log.is_file():
            log_text = log.read_text(errors="replace")
            missing = sorted(set(re.findall(r"Missing required extension: (VK_[A-Za-z0-9_]+)",
                                            log_text)))
            if missing:
                report["blocker_code"] = "VULKAN_REQUIRED_EXTENSION_UNAVAILABLE"
                report["missing_required_extensions"] = missing
            selected = re.search(r"selecting physical device '([^']+)'", log_text)
            if selected:
                report["selected_vulkan_device"] = selected.group(1)
                software = any(word in selected.group(1).lower() for word in ("llvmpipe", "lavapipe"))
                report["selected_device_is_known_software"] = software
                report["software_vulkan_execution"] = (
                    "PASS" if software and report["result"] == "SYNTHETIC_LIVE_SWITCH_PASS" else "NOT_RUN")
            report["gamescope_log_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
        if reader:
            try:
                reader.poll()
            except ProbeError as error:
                report["final_status_error"] = str(error)
            (output / "status-observations.json").write_text(json.dumps(reader.observed, indent=2) + "\n")
        (output / "probe-report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(output / "probe-report.json")


if __name__ == "__main__":
    raise SystemExit(main())
