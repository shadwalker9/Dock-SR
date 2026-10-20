# S004 workspace X11 dependencies

Verified 2026-10-19 on the existing Debian 13 x86_64 cloud image. Native Xlib is
the small preview-window foundation. These dependencies enable compilation and
software virtual-window checks; they do not establish a physical display, GPU,
SteamOS/Bazzite compatibility or NPU execution.

## Pinned packages and scope

Exact archive URLs, sizes, SHA-256 hashes and Depends fields are in
[`tools/preview-packages.lock.json`](../tools/preview-packages.lock.json).

| Package | Pinned version | Use |
|---|---|---|
| libx11-dev | 2:1.8.12-1 | Xlib headers and linker name |
| libx11-6 | 2:1.8.12-1 | Matching local target for the development library symlink |
| x11proto-dev | 2024.1-1 | X11 protocol and auxiliary headers; source package is xorgproto |
| xvfb | 2:21.1.16-1.3+deb13u4 | Optional software X server for window/event checks |
| xdotool | 1:3.20160805.1-5.1 | Optional window discovery and synthetic key events |
| libxdo3 | 1:3.20160805.1-5.1 | xdotool's additional shared library |

No XShm or other Xext APIs are required by the plain-Xlib foundation, so
libxext-dev is not added. The existing libXfont2 supplies built-in `fixed` and
`cursor` fonts; an actual window loaded `fixed` successfully, so xfonts-base is
not needed for these checks.

This is a small extraction set for the documented base image, not a complete
Debian dependency resolver or a portable runtime bundle. The image already has
libxcb1, libXau, libXdmcp, libXfont2, libpixman, libGL, libnettle, libaudit,
libselinux, libsystemd, libunwind, libXinerama, libxkbcommon and libXtst, plus
xserver-common, x11-xkb-utils (`/usr/bin/xkbcomp`) and xkb-data
(`/usr/share/X11/xkb`). The helper checks dynamic linkage and the keyboard data
before declaring the optional tools prepared. Unused XCB/Xtrans/SGML development
headers are deliberately outside this extraction set.

## Verification and licenses

The pre-existing APT configuration uses HTTPS Debian trixie/security sources
with `Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg`. The installed
`sqv` verifier independently validated both InRelease signatures. The
decompressed package indexes were then SHA-256/size-checked against the
authenticated Release payloads. Index hashes are recorded in the lock file.
`gpgv` is absent; no verification was bypassed to work around that absence.

The bootstrap downloads only the pinned HTTPS archives, checks exact size and
SHA-256, verifies package name/version/architecture, and runs `dpkg-deb --extract`
into `/workspace/.local/docksr-preview`. It never invokes package installation,
maintainer scripts, driver configuration or a system X server/service.

Complete copyright/license notices are retained under both the package's
extracted documentation where available and
`/workspace/.local/docksr-preview/share/docksr-preview/licenses/`. Shared
documentation such as Xvfb's xserver-common notice is copied from the existing
base image when its extracted symlink would otherwise dangle. Xlib/X server
notices include X.Org MIT/X11 and legacy component terms; xorgproto also contains
SGI terms. xdotool/libxdo use BSD-3-clause. Preserve the complete notices rather
than replacing them with this summary when preparing a later distribution.

## Reproduce and activate

For headers and the matching Xlib runtime only:

```sh
python3 scripts/bootstrap_preview.py
```

For virtual-window tests as well:

```sh
python3 scripts/bootstrap_preview.py --with-test-tools
source /workspace/.cache/docksr-cloud/env.sh
source /workspace/.cache/docksr-cloud/preview-env.sh
```

The existing `env.sh` supplies host/CMake/Vulkan tools. `preview-env.sh` adds the
workspace X11 paths and does not set DISPLAY, WAYLAND_DISPLAY or a Vulkan ICD.
Use these CMake arguments for the preview configuration:

```sh
-DX11_X11_INCLUDE_PATH=/workspace/.local/docksr-preview/usr/include
-DX11_X11_LIB=/workspace/.local/docksr-preview/usr/lib/x86_64-linux-gnu/libX11.so
```

For example, append them to the normal preview configure command with
`-DBUILD_PREVIEW=ON`. The helper refuses paths outside `/workspace` and refuses
an unrelated nonempty extraction prefix. Cached package hashes are rechecked;
running the same bootstrap a second time passed without downloading or changing
system packages.

## Window-test evidence and lifetime

An isolated CMake FindX11 program compiled against these headers/libraries and
ran under a real Xvfb process. It created a native window, loaded `fixed`, drew
text/pixels, verified a pixel using XGetImage, and accepted a `q` key from
xdotool. Both the client and Xvfb were terminated/waited; no service remains.
Local dependency-smoke evidence is at
`/workspace/.cache/docksr-preview-smoke/result.json`, with its source/build and
server log in the same directory. This program is a dependency check, not the
Dock SR preview acceptance test or a physical-GPU performance measurement.

For application tests, allocate a display using an inherited writable pipe:

```sh
Xvfb -displayfd FD -screen 0 1920x1080x24 -nolisten tcp -fp built-ins -noreset
```

Read the reported display number, set DISPLAY only in child test processes, and
always terminate/wait in cleanup. Avoid hardcoding a display number or assuming
`/tmp/.X11-unix` exists: this unprivileged image supports the abstract Unix socket
even when Xvfb logs that it cannot create the traditional socket directory.
TCP listening is disabled. A virtual-window PASS must remain separate from
physical-desktop, Gaming Mode and target-handheld results.
