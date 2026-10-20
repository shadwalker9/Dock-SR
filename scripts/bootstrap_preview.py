#!/usr/bin/env python3
"""Extract pinned X11 preview prerequisites on the Debian 13 cloud image.

No system installation, driver changes or service startup. Optional Xvfb/xdotool
support virtual-window correctness checks, never physical-GPU performance claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def workspace_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == Path("/workspace") or not resolved.is_relative_to("/workspace"):
        raise ValueError("Preview setup paths must be inside /workspace")
    return resolved


def download(package: dict, cache: Path) -> Path:
    url = urllib.parse.urlsplit(package["url"])
    if url.scheme != "https" or url.hostname != "deb.debian.org" or url.query or url.fragment:
        raise ValueError("Only pinned HTTPS Debian archive URLs are accepted")
    expected = package["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid package SHA-256")
    destination = cache / Path(url.path).name
    if destination.is_file() and destination.stat().st_size == package["size"] and digest(destination) == expected:
        return destination
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, prefix="preview-download-", delete=False) as stream:
            temporary = Path(stream.name)
            with urllib.request.urlopen(package["url"], timeout=30) as response:
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > package["size"]:
                        raise RuntimeError("Package exceeded its signed-index size: " + package["name"])
                    stream.write(block)
        if temporary.stat().st_size != package["size"] or digest(temporary) != expected:
            raise RuntimeError("Package size/SHA-256 mismatch: " + package["name"])
        temporary.replace(destination)
        return destination
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def run(*argv, env=None) -> str:
    result = subprocess.run([str(item) for item in argv], check=True, text=True,
                            capture_output=True, timeout=30, env=env)
    return result.stdout.strip()


def check_linkage(path: Path, environment: dict[str, str]) -> None:
    output = run("ldd", path, env=environment)
    if "not found" in output:
        raise RuntimeError("Missing base-image runtime dependencies for " + str(path) + ":\n" + output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-test-tools", action="store_true", help="Also extract Xvfb, xdotool and libxdo3")
    parser.add_argument("--prefix", type=Path, default=Path("/workspace/.local/docksr-preview"))
    parser.add_argument("--cache", type=Path, default=Path("/workspace/.cache/docksr-cloud/preview-packages"))
    parser.add_argument("--activation", type=Path, default=Path("/workspace/.cache/docksr-cloud/preview-env.sh"))
    args = parser.parse_args()
    release = platform.freedesktop_os_release() if platform.system() == "Linux" else {}
    if release.get("ID") != "debian" or release.get("VERSION_ID") != "13" or platform.machine() != "x86_64":
        parser.error("This extraction helper supports the Debian 13 x86_64 cloud image only")
    for tool in ("dpkg-deb", "ldd"):
        if not shutil.which(tool):
            parser.error("Missing base-image prerequisite: " + tool)
    try:
        prefix, cache, activation = (workspace_path(value) for value in (args.prefix, args.cache, args.activation))
    except ValueError as error:
        parser.error(str(error))
    repo = Path(__file__).resolve().parents[1]
    lock_path = repo / "tools/preview-packages.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock["schema_version"] != "1.0.0":
        parser.error("Unsupported preview dependency lock schema")
    packages = [item for item in lock["packages"] if item["role"] == "build" or args.with_test_tools]
    marker = prefix / ".docksr-preview-prefix"
    if prefix.exists() and any(prefix.iterdir()) and not marker.is_file():
        parser.error("Refusing to populate a nonempty prefix without a Dock SR preview marker")
    prefix.mkdir(parents=True, exist_ok=True)
    marker.write_text("Dock SR preview extracted userspace tools, schema 1\n", encoding="utf-8")
    cache.mkdir(parents=True, exist_ok=True)
    licenses = prefix / "share/docksr-preview/licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    for package in packages:
        archive = download(package, cache)
        metadata = run("dpkg-deb", "--show", "--showformat=${Package}\n${Version}\n${Architecture}\n", archive).splitlines()
        if metadata != [package["name"], package["version"], package["architecture"]]:
            raise RuntimeError("Pinned archive metadata mismatch: " + package["name"])
        run("dpkg-deb", "--extract", archive, prefix)
        copyright_file = prefix / "usr/share/doc" / package["name"] / "copyright"
        if not copyright_file.is_file():
            # Some packages share documentation with an already installed base
            # package, e.g. xvfb -> xserver-common. Retain the full notice.
            resolved = copyright_file.resolve()
            copyright_file = (Path("/") / resolved.relative_to(prefix)
                              if resolved.is_relative_to(prefix)
                              else Path("/usr/share/doc") / package["name"] / "copyright")
        if not copyright_file.is_file():
            raise RuntimeError("Missing complete copyright notice for " + package["name"])
        shutil.copyfile(copyright_file, licenses / (package["name"] + ".copyright"))
        print("Verified and extracted " + package["name"] + " " + package["version"])
    sdk = prefix / "usr"
    library = sdk / "lib/x86_64-linux-gnu"
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = str(library) + (":" + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else "")
    check_linkage(library / "libX11.so", environment)
    if args.with_test_tools:
        for name in ("Xvfb", "xdotool"):
            check_linkage(sdk / "bin" / name, environment)
        if not Path("/usr/bin/xkbcomp").is_file() or not Path("/usr/share/X11/xkb").is_dir():
            raise RuntimeError("Virtual-window checks require the base image's x11-xkb-utils and xkb-data")
        print(run(sdk / "bin/xdotool", "--version", env=environment))
    activation.parent.mkdir(parents=True, exist_ok=True)
    activation.write_text("\n".join([
        "# X11 preview tools only. This does not select a DISPLAY or GPU driver.",
        "export DOCKSR_PREVIEW_ROOT=" + shlex.quote(str(sdk)),
        "export PATH=" + shlex.quote(str(sdk / "bin")) + ':"$PATH"',
        "export LD_LIBRARY_PATH=" + shlex.quote(str(library)) + '${LD_LIBRARY_PATH:+:"$LD_LIBRARY_PATH"}',
        "export CMAKE_PREFIX_PATH=" + shlex.quote(str(sdk)) + '${CMAKE_PREFIX_PATH:+:"$CMAKE_PREFIX_PATH"}',
        "export PKG_CONFIG_PATH=" + shlex.quote(str(library / "pkgconfig")) + '${PKG_CONFIG_PATH:+:"$PKG_CONFIG_PATH"}',
    ]) + "\n", encoding="utf-8")
    (prefix / "preview-installed.json").write_text(json.dumps({
        "schema_version": "1.0.0", "lock_sha256": digest(lock_path),
        "packages": [{key: package[key] for key in ("name", "version", "sha256")} for package in packages],
        "scope": "workspace userspace dependencies; no server started, no drivers installed",
    }, indent=2) + "\n", encoding="utf-8")
    print("Activate: source " + shlex.quote(str(activation)))
    print("CMake: -DX11_X11_INCLUDE_PATH=" + str(sdk / "include") + " -DX11_X11_LIB=" + str(library / "libX11.so"))
    print("Virtual X11 is correctness evidence only; physical GPU/window and target handheld remain separate checks.")


if __name__ == "__main__":
    main()
