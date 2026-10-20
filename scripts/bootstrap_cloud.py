#!/usr/bin/env python3
"""Prepare isolated Dock SR host/Vulkan tools on the Debian 13 cloud image.

No system package installation, drivers, models or application service startup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request


TOOL_REQUIREMENTS = """cmake==3.31.10 --hash=sha256:2f766bb46367e5e0559fa33184653754bce044583a06014dcaebf8e6dff8a1f1
ninja==1.11.1.4 --hash=sha256:096487995473320de7f65d622c3f1d16c3ad174797602218ca8c967f51ec38a0
"""


def run(*arguments):
    subprocess.run([str(item) for item in arguments], check=True)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def verified_download(package, cache):
    url = package["url"]
    if urllib.parse.urlsplit(url).scheme != "https":
        raise RuntimeError("Package source must use HTTPS")
    destination = cache / Path(urllib.parse.urlsplit(url).path).name
    if destination.is_file() and digest(destination) == package["sha256"]:
        return destination
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, prefix="download-", delete=False) as output:
            temporary = Path(output.name)
            with urllib.request.urlopen(url, timeout=60) as response:
                shutil.copyfileobj(response, output, length=1024 * 1024)
        if digest(temporary) != package["sha256"]:
            raise RuntimeError("SHA-256 mismatch for " + package["name"])
        temporary.replace(destination)
        return destination
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-only", action="store_true")
    parser.add_argument("--venv", type=Path, default=Path("/workspace/.venvs/docksr-host"))
    parser.add_argument("--prefix", type=Path, default=Path("/workspace/.local/docksr-vulkan"))
    parser.add_argument("--cache", type=Path, default=Path("/workspace/.cache/docksr-cloud"))
    args = parser.parse_args()
    release = platform.freedesktop_os_release() if platform.system() == "Linux" else {}
    if release.get("ID") != "debian" or release.get("VERSION_ID") != "13" or platform.machine() != "x86_64":
        parser.error("This helper supports the Debian 13 x86_64 cloud image; see docs/development.md for other hosts.")
    for tool in ["python3", "g++", "dpkg-deb"]:
        if not shutil.which(tool):
            parser.error("Missing base-image prerequisite: " + tool)
    repo = Path(__file__).resolve().parents[1]
    args.cache.mkdir(parents=True, exist_ok=True)
    args.venv.parent.mkdir(parents=True, exist_ok=True)
    python = args.venv / "bin/python"
    if not python.is_file():
        run("python3", "-m", "venv", args.venv)
    with tempfile.TemporaryDirectory(dir=args.cache) as directory:
        requirements = Path(directory) / "host-tools.txt"
        requirements.write_text(TOOL_REQUIREMENTS)
        run(python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
            "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "--require-hashes", "-r", requirements)
    run(python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
        "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "--require-hashes",
        "-r", repo / "requirements-dev.lock")
    if not args.host_only:
        args.prefix.mkdir(parents=True, exist_ok=True)
        lock = json.loads((repo / "tools/cloud-packages.lock.json").read_text())
        for package in lock["packages"]:
            archive = verified_download(package, args.cache)
            run("dpkg-deb", "--extract", archive, args.prefix)
        dependency_check = subprocess.run(
            ["ldd", str(args.prefix / "usr/lib/x86_64-linux-gnu/libvulkan_lvp.so")],
            text=True, capture_output=True, check=False)
        if dependency_check.returncode or "not found" in dependency_check.stdout:
            raise RuntimeError("Software Vulkan has missing base-image dependencies:\n" + dependency_check.stdout + dependency_check.stderr)
    runtime = args.cache / "runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    runtime.chmod(0o700)
    environment = args.cache / "env.sh"
    lines = ["# Source this file in shells that build/run the cloud checks.",
             "export PATH=" + shlex.quote(str(args.venv / "bin")) + ':"$PATH"',
             "export XDG_RUNTIME_DIR=" + shlex.quote(str(runtime)),
             "export MESA_SHADER_CACHE_DIR=" + shlex.quote(str(args.cache / "mesa-cache"))]
    if not args.host_only:
        sdk = args.prefix / "usr"
        lines.insert(1, "export PATH=" + shlex.quote(str(sdk / "bin")) + ':"$PATH"')
        lines += ["export DOCKSR_VULKAN_ROOT=" + shlex.quote(str(sdk)),
                  "export LD_LIBRARY_PATH=" + shlex.quote(str(sdk / "lib/x86_64-linux-gnu")) + ':"${LD_LIBRARY_PATH:-}"',
                  "export VK_ICD_FILENAMES=" + shlex.quote(str(sdk / "share/vulkan/icd.d/lvp_icd.json"))]
    environment.write_text("\n".join(lines) + "\n")
    print("Host tools prepared. Activate with: source " + shlex.quote(str(environment)))
    print("No target AMD runtime, game integration or performance gain has been validated.")


if __name__ == "__main__":
    main()
