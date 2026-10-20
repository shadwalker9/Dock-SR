# R006-M1: experimental Gamescope filter laboratory

This source patch adds `-F docksr` to one pinned Gamescope revision. Its native
composition path implements exact 1280×720 → 3840×2160 nearest reconstruction
with a visible 48×48 cyan/magenta proof marker. It is a deterministic integration
sentinel, with no perceptual-quality or performance advantage established.

`upstream.lock.json` records the immutable upstream revision, patch/header
SHA-256 values, original/patched file hashes and dependency variant. The patch
must not be applied to installed/system Gamescope. No complete upstream source,
Gamescope binary, driver, model or runtime package is shipped here.

## Evidence and source identity

Source reapplication and file-integrity checks pass. Build and actual rendering
results are recorded separately in [project state](../../docs/PROJECT_STATE.md).
A configured build, filter parser, status label or contract-unit callback is
insufficient evidence of GPU dispatch, displayed pixels or a live game.

The native status `docksr_commit` is the starting DockSR checkpoint
`d7cc16e67f2138030c9cf0cbd29e57e9d4967bac`. It is a **base revision**, not a claim
that the binary was built from that clean checkpoint. Identify this experiment
using the full upstream SHA, the patch SHA-256, copied contract-header SHA-256
and actual build manifest together. The checked source pin is:

```
ValveSoftware/gamescope
4d5b7f3c9e1b6d3ee41c5c460b835fe5e0fe71b3
```

Physical GPU, physical display, XDNA2/NPU, game-performance, quality, efficiency
and SteamOS/Bazzite deployment gates remain separate. This experiment does not
waive the owner's verified-NPU requirement for the first usable version.

## Reproduce the source

Use a separate, non-system workspace and the official repository. Preserve any
existing checkout changes; the helper refuses to overwrite affected paths.
No extra Git worktree is needed. The clone/apply commands below assume a new
source directory; if the retained tree already exists, use `--check-applied`
instead of overwriting or reapplying it.

```sh
git clone --no-checkout https://github.com/ValveSoftware/gamescope \
  /workspace/DockSR-gamescope-lab/upstream
git -C /workspace/DockSR-gamescope-lab/upstream checkout --detach \
  4d5b7f3c9e1b6d3ee41c5c460b835fe5e0fe71b3
python3 /workspace/Dock-SR/experiments/gamescope/apply_patch.py \
  /workspace/DockSR-gamescope-lab/upstream
python3 /workspace/Dock-SR/experiments/gamescope/apply_patch.py \
  /workspace/DockSR-gamescope-lab/upstream --check-applied
git -C /workspace/DockSR-gamescope-lab/upstream submodule update \
  --init --recursive src/reshade subprojects/vkroots thirdparty/SPIRV-Headers
```

The helper verifies canonical origin, exact HEAD, patch/header hashes and
original target bytes before `git apply --check`. It copies the single owned
`docksr_lab.hpp` contract into the experimental tree. Existing modified,
tracked/staged, untracked or symlink target paths are rejected. Hash checks are
integrity controls, not signatures or a hostile same-user filesystem sandbox.
The helper does not fetch dependencies, build, start services or install files.

## Build dependency variant

The upstream wlroots gitlink is
`d783533489e1f75d6886c2ab5c5960090ef268f8`. Official GitLab access was denied
with CONNECT 403, and the exact revision was absent from the legitimate mirrors
checked. The cloud lab instead uses authenticated Debian sid
`libwlroots-0.20(-dev)` **0.20.2-1**, which satisfies Gamescope's declared
`>=0.20,<0.21` external dependency range. It does not reproduce that gitlink.
External libdisplay-info **0.3.0** likewise satisfies the declared range.

The patch also repairs narrow upstream nested-only build dependencies: reuse
available DRM metadata types, include libinput declarations used by touch
association, and link core libdrm for the existing syncobj timeline. When the
KMS backend is disabled, refresh selection uses the generic output rate,
display-sleep requests report that the DRM backend is unavailable, and a
DRM-only debug variable is not referenced. The enabled-DRM behavior is retained;
these corrections do not remove runtime Vulkan capability requirements.

The workspace-only cloud tooling and signed-index/package lock manifests are
under `cloud/`. Its metadata relocation applies only to extracted pkg-config
paths; it does not edit libraries, disable checks or install packages globally.
Use a supported native development toolchain on another distribution. Do not
copy this Debian dependency prefix onto Bazzite/SteamOS.

On the prepared cloud image:

```sh
. /workspace/DockSR-gamescope-lab/env.sh
meson setup /workspace/DockSR-gamescope-lab/build \
  /workspace/DockSR-gamescope-lab/upstream \
  -Ddrm_backend=disabled -Dsdl2_backend=enabled -Dpipewire=disabled \
  -Dinput_emulation=disabled -Davif_screenshots=disabled \
  -Drt_cap=disabled -Dbenchmark=disabled -Denable_openvr_support=false \
  -Denable_gamescope_wsi_layer=false -Denable_zenity=false
meson compile -C /workspace/DockSR-gamescope-lab/build -j2
meson test -C /workspace/DockSR-gamescope-lab/build --print-errorlogs
```

Tests remain enabled. No required Vulkan extension, upstream assertion or
version constraint may be removed to turn a runtime blocker into a pass.
Never run `meson install` over the operating-system compositor for this lab.

## Native data path and fallback

`commit_t::ShouldPreemptivelyUpscale` deliberately excludes DOCKSR. Composition
reads the imported 720p texture, writes one bounded GPU-owned 4K intermediate,
and uses the existing BLIT colour-management/alpha/overlay path and backend
presentation. This avoids reusing a preemptive cached sentinel across mode
generations. Native command-buffer references retain resources through GPU use;
there is no second frame scheduler or filter-path CPU image readback.

The proof supports only unrotated, full-frame, exact-3× 8-bit SDR RGB(A).
Geometry, YCbCr, HDR, format, unavailable-resource and inconsistent-control
conditions select LINEAR with an exact fallback reason. The marker retains
source alpha and bounds its RGB values by alpha. Source inspection and contract
fallback tests do not establish actual HDR/alpha or allocation-failure rendering.
All four NPU status fields are constant `false`.

The patch forces composition in the relevant Wayland/DRM/optional VR selection
paths. Whole-system overhead must later include composition versus direct
scanout, transfers, synchronization and presentation; shader time alone cannot
establish the requested lower-cost MVP.

## Live control and status

Set `DOCKSR_LAB=1` for the diagnostic control adapter. An explicitly declared
`DOCKSR_LAB_EVIDENCE=SOFTWARE_VULKAN` or `VIRTUAL_WINDOW` enables corresponding
observations; the environment declaration does not detect hardware or attest
pixels. Without that context the status remains `NOT_RUN`.

Use only the isolated lab compositor's mode-0700 `XDG_RUNTIME_DIR` and scoped
`GAMESCOPE_WAYLAND_DISPLAY`. The patch adds a registered command to Gamescope's
existing private execute protocol. It creates no new socket and promises no
stable stock-Gamescope API. The complete operation/ID is one argument:

```sh
gamescopectl docksr_lab 'ON 2'
gamescopectl docksr_lab 'BYPASS 3'
gamescopectl docksr_lab 'ON 4'
gamescopectl docksr_lab 'STATUS 5'
```

Initial `-F docksr` reserves bootstrap request ID1. Every accepted request ID
must increase, including STATUS. Commands are bounded and queued for the
compositor owner thread. A mutating request is initially `PENDING`; effective
generation changes only at a frame boundary. Transport acknowledgement is not
presentation acknowledgement. Observe native `DOCKSR_STATUS` JSON, next-frame
state and independent captured pixels together.

`docksr_lab.hpp`, `../../schemas/gamescope-lab.schema.json` and the C++/Python
contract tests distinguish backend existence/attachment, requested/effective
mode, dispatch and backend presentation. Counters count painted/submitted frame
observations, not unique source/game frames. Backend queue success is separate
from physical display feedback; SDL failures propagate instead of producing a
false presented acknowledgement. Headless `Present` cannot prove this filter.

## Synthetic probe

See [owned fixture instructions](fixtures/README.md). `run_virtual_probe.py`
uses authenticated TCP-disabled Xvfb, fixed 720p synthetic input, native status,
PID-scoped 4K window capture and ON/BYPASS/ON hash checks in one process session.
These are synthetic pixels, not a game. Diagnostic XGetImage captures are an
opt-in evidence operation separate from the GPU filter data path.

The status contract's unit observations use `CONTRACT_TEST`; they cannot be
relabeled as software-Vulkan, live-game, physical-GPU or NPU rendering evidence.

## Source and licensing boundaries

Touched upstream files cover filter identity/parser, native composition/shader,
backend composition decisions, scoped control, presentation-error propagation,
small nested-only include compatibility corrections and scaler-parser tests.
The existing protocol XML is unchanged. Preserve Gamescope's BSD-2-Clause and
bundled OpenColorIO/ReShade notices and review each dependency's terms before
any separately authorized distribution. DockSR original licensing is pending.
This source backup does not authorize release, a new public fork, system
Gamescope replacement, Decky submission or model/runtime redistribution.
