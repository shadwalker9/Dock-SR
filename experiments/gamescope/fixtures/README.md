These owned fixtures create **synthetic pixels, not a game**. The X11 client
holds a1280×720 opaque window and repeatedly commits the same deterministic
pattern. Its initial X11 geometry and the native adapter's imported extent must
both agree. Dynamic commits do not change the pattern or create frame-time data.

`capture_x11.c` finds the parent window by the experimental Gamescope PID and
exact3840×2160 extent, then captures actual X server window pixels using
`XGetImage`. PPM captures RGB only; they cannot validate alpha or HDR.
This opt-in diagnostic readback is outside the Gamescope filter path. Capturing
pixels adds CPU transfer/work and must not be included as a production-path
latency or efficiency measurement.

From the repository root, after preparing the isolated dependency environment:

```sh
. /workspace/DockSR-gamescope-lab/env.sh
python3 experiments/gamescope/run_virtual_probe.py --compile-only \
  --output /workspace/DockSR-gamescope-lab/fixture-build-check
python3 experiments/gamescope/run_virtual_probe.py \
  --output /workspace/DockSR-gamescope-lab/virtual-probe-001
```

Each output directory must be new. The probe uses an isolated0700 runtime
directory, a0600 MIT-cookie authority file, and Xvfb with TCP disabled. It checks
that a client lacking the cookie is rejected. It adds no global socket, uses no
`xhost`/`-ac`, and terminates only process groups it started.
Evidence destinations inside Git checkouts are refused, and captures cannot
overwrite an existing file or symlink. Requested extents are recorded separately
from actual compositor extents; the latter remain null until native frame
observations establish them.

Control commands use the explicitly private, pinned Gamescope control client.
The complete `ON 2` value travels as one argument to `docksr_lab`. The initial
CLI selection reserves bootstrap request1. ON2/BYPASS3/ON4 follow it, then
STATUS5; IDs are strictly monotonic.
Transport return values are not presentation acknowledgements: the probe waits
for next-frame effective generations, native dispatch/presentation observations,
and independent parent-window pixel hashes. Equal ON captures and a different
BYPASS capture are required for success. All NPU fields must remain false.

Successful output is `VIRTUAL_WINDOW` / `SYNTHETIC_LIVE_SWITCH_PASS`. It does not
establish physical GPU display, a live game, NPU execution, power efficiency,
quality improvement, or production readiness. CPU/software Vulkan must be
classified separately from physical hardware in the surrounding experiment.
