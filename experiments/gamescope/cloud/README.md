# Isolated Debian cloud dependencies

This is experimental build tooling for the tested Debian 13 x86_64 cloud. It is
**not** a SteamOS/Bazzite installer. It writes only to a non-Git laboratory root
under `/workspace` or `/tmp`; it never invokes `apt`, package maintainer scripts,
root installation, driver deployment or system Gamescope replacement.

```sh
bash experiments/gamescope/cloud/setup_environment.sh /workspace/DockSR-gamescope-lab
. /workspace/DockSR-gamescope-lab/env.sh
```

The setup reuses the retained DockSR cloud/preview toolchain and intentionally
selects lavapipe. Never carry that software ICD override into target benchmarks.
Processes are not retained; the virtual probe starts and stops its own isolated,
authenticated Xvfb session. See the parent laboratory instructions for the pinned
source, patch application, build options and runtime acceptance gates.

`dependencies.lock.json` and `sid-dependencies.lock.json` record exact Debian
artifacts, versions, byte lengths and SHA-256 values. Their creation used the
host Debian archive keyring to verify official HTTPS `InRelease` signatures,
then the signed `Packages.xz` hash and every package hash. Reproduction replays
these reviewed artifact locks in trixie-then-sid order, preserving TLS and hash
checks; it does not resolve a newer suite or pretend to re-authenticate an old
lock with today's moving index. A package removed from the official repository
is a reproducibility blocker, not permission to change its expected hash.

The signed live-index resolution mode remains available for an explicitly
reviewed dependency refresh. Exact replay and non-mutating artifact checks are:

```sh
python3 experiments/gamescope/cloud/prepare_deps.py \
  --root /workspace/DockSR-gamescope-lab \
  --restore-lock experiments/gamescope/cloud/dependencies.lock.json \
  --restore-lock experiments/gamescope/cloud/sid-dependencies.lock.json \
  --verify-only
```

Only extracted `.pc` metadata is relocated: hardcoded `/usr` include/library
paths and SDL's required multiarch include path. Library/header bytes remain
unchanged. Runtime packages are explicitly retained for development symlink
resolution; an installed host runtime alone does not satisfy a missing runtime
file within the isolated prefix. Notices remain in `prefix/usr/share/doc`.
No `.deb`, dependency library, model, report, or full upstream checkout is
redistributed by these source files.

The external Debian sid `wlroots-0.20` version **0.20.2-1** satisfies the pinned
Gamescope source's declared `>=0.20.0,<0.21.0` external dependency range. This is
an explicit variant from its `d783533489e1f75d6886c2ab5c5960090ef268f8` gitlink,
whose official GitLab fetch was denied. It must never be described as that
exact submodule source. Matching isolated dependencies include Wayland1.26.0,
wayland-protocols1.49, libdrm2.4.134, xkbcommon1.13.1 and libdisplay-info0.3.0.
Meson1.9.1 is separately wheel-hash-pinned; the retained cloud setup supplies
CMake/Ninja/glslang. Building successfully does not establish runtime Vulkan
support, visible output, physical GPU acceleration or NPU execution.
