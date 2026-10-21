# SteamOS, Bazzite and Linux integration map

DSR012-P checkpoint P-B, reviewed2026-10-21. This is source-backed architecture
research and a read-only inventory interface, not target compatibility or an
installation procedure. No device, daemon, service, driver, firmware or shipping
compositor was modified. R-008 was not available in the supplied materials; its
specific claims, including proposed IPU sensor fields, remain unverified.

## Sources and confidence

`DOCUMENTED` below means the cited upstream describes that layer, not that
DockSR executed it. `VERIFIED` would require local physical device evidence;
none of the three target OS stacks has that here. `PLAUSIBLE_UNVERIFIED` is an
engineering hypothesis; `UNKNOWN` identifies missing device/build information;
`BLOCKED` identifies a known missing prerequisite, not a blanket OS verdict.
Exact source pins and byte identities are recorded in [upstream notes](../notes/UPSTREAM.md).

- AMD Ryzen AI **1.8.0** Linux/model deployment docs describe current Linux NPU
  execution, Python3.12 and Ubuntu24.04-named XRT/plugin packages. Their support
  family/device tables must match the actual APU; a Z2 marketing name is not
  sufficient identification. This does not document SteamOS/Bazzite Vitis support.
- AMD xdna-driver source `bc5dd96b6a11fcdba0884c492f897c9e6ed5aa79`
  describes kernel/config requirements, matching XRT SHIM/plugin and firmware,
  Arch and Fedora packaging paths, and user memlock limits. An upstream in-tree
  driver can predate required plugin ioctls. Package presence alone is not enough.
- Valve Gamescope `aa289ea5977d8b21b92b0f246f0e8f0c225d180f` documents
  embedded DRM/KMS and nested desktop operation. DockSR's retained patch is
  separately pinned to `4d5b7f3c9e1b6d3ee41c5c460b835fe5e0fe71b3`.
- Bazzite docs `a0ac868202675862fd1f41b218964bf3abc08758` document
  Fedora Atomic deployments, package layering/reboot implications, rollback and
  container workflows. Their Git source was read because the docs website was
  inaccessible. This is not a claim that all current image variants use identical
  deployment tools or contain a compatible NPU stack.
- ChimeraOS gamescope-session-plus
  `73d2da84ace7f41006a0f85bd2fdb19ef593a464` is a **community session
  implementation**, not evidence of Valve's shipping session unit. Its wrapper,
  user unit and shell show one concrete lifecycle to compare on device.
- Decky loader `00cd202872b85868071b041c8f1b34e734147195` and template
  `90d0780e882a17f5714fc6de044c645f22608290` show frontend/backend calls,
  plugin processes and privilege handling. Flatpak/Distrobox sources document
  their respective isolation and host-integration limits.

Valve's public SteamOS tracker at `25e4843add550be450da0cdae9955926b01df4f2`
links official installation/repair and recovery guides. The FAQ/support pages
returned CONNECT403 here. Therefore the SteamOS3 read-only-root/update layout is
a project deployment assumption to verify on the device, not a newly verified
Valve implementation detail. The public steamos_kernel default ref
`798b216f18cf4d6c605503baf7e4329efd343f24` is not the owner's installed kernel;
absence of a guessed source path at that ref does not prove absent target support.

## OS structure, writable paths and recovery

Keep experiments under user-controlled XDG locations: versioned binaries under
`~/.local/lib/docksr/REVISION/`, optional launcher in `~/.local/bin`, settings in
`$XDG_CONFIG_HOME/docksr`, models in `$XDG_DATA_HOME/docksr/models`, runtime caches
in `$XDG_CACHE_HOME/docksr`, and owner-only diagnostics in `$XDG_STATE_HOME/docksr`.
Use standard XDG defaults when unset. These are proposed paths; verify ownership,
free space, execute/mount policy and persistence on each actual image. Runtime
control endpoints belong in a private0700 session directory under
`$XDG_RUNTIME_DIR`, with session identity, not a shared global socket.

Do not write `/usr/bin/gamescope`, package-manager libraries, `/boot`, firmware or
kernel settings to make a prototype run. Treat the shipping SteamOS root as
protected until its actual policy is inspected. A user-space tree is reversible
by retiring that version, but cannot supply a missing kernel driver or host
firmware. OS updates may change ABI, runtime, permissions and sessions; re-run
inventory after each update rather than assuming user-data persistence means
binary compatibility. Record the installed OS/kernel and recovery method first.
Valve's linked recovery workflow is not an authorized media-flashing operation.

Bazzite's reviewed docs describe a transactional deployment and rollback path;
package layering creates another deployment and typically needs a reboot.
Layered dependencies can obstruct updates. Prefer an isolated user-space test
tree first; any host package/driver change needs a concrete owner-approved plan.
Do not prescribe switching an image between rpm-ostree and bootc from this map.

## Gaming session lifecycle and environment

The conceptual chain is:
`boot/display manager → gaming session → Gamescope → Steam UI → game/Proton → presentation`.
System services own boot/login and hardware policy. Session/user processes own
the compositor/client lifecycle; exact unit names and launcher scripts depend on
the installed distro. In the reviewed **community** session, the wrapper starts
`gamescope-session-plus@CLIENT.service` through `systemctl --user`; the unit binds
to `graphical-session.target` and uses `KillMode=mixed`. The session shell selects
Gamescope, creates session-local control paths, sources environment.d configuration
and starts the client. This is a source example to inspect, not a Valve service
installation recipe.

Gaming Mode uses an embedded compositor owning presentation resources; Desktop
Mode has a desktop compositor, where a separate nested Gamescope can be a window.
Gamescope's Wayland/Xwayland path supplies an X11 environment for relevant games;
Proton processes inherit the launch environment, while native Wayland clients
need separate compatibility evidence. Environment set in a later terminal does
not retroactively update already-running Steam, a user service or its children.
Pass a reviewed, minimal runtime environment when the future worker is spawned;
never carry the cloud lavapipe ICD override into hardware measurements.

Inspect installed units with read-only `systemctl --user cat UNIT` only after
discovering their actual names. Inspect process names and installed binary
versions without dumping command lines/environment or serial numbers. On
shutdown/crash/session changes, invalidate the old session/generation; pause
admission for suspend and re-inventory/reinitialize after resume or device loss.
A timeout does not prove producer/GPU quiescence or permit freeing active storage.

The first graphical experiment should be an explicitly invoked, separate nested
session from Desktop Mode, using the versioned private binary/runtime directory
and an owned fixture. Exit only that experiment to recover. Validate native
Vulkan/WSI requirements first; do not disable assertions, replace the gaming
session or launch another DRM owner blindly. Successful nested output would not
prove Gaming Mode, physical NPU work or a real game's compatibility.

## NPU dependency boundary

`host kernel/amdxdna → matching firmware/device node/ACLs/memlock → XRT base + XDNA plugin → vendor ORT/Vitis AI EP → native worker`.

Kernel, firmware policy and device permissions belong to host integration.
XRT/plugin, Python/ORT and model caches may be candidates for a user-space tree
only if loading, ABI, licensing and runtime discovery actually work there; the
vendor's documented package installation is not a proven portable deployment.
Do not copy Ubuntu libraries over Fedora/SteamOS system libraries. Verify exact
firmware/plugin/driver ioctl compatibility, not merely kernel version or
`/dev/accel` presence. Memlock can differ between a terminal and systemd-launched
worker. Changing limits, groups, udev rules or drivers is outside this session.
Provider registration and vendor quicktest do not satisfy SESR placement/output
comparison. Vulkan DMA-BUF support does not prove Vitis tensor binding.

| Capability | Ubuntu reference | Bazzite | SteamOS |
| --- | --- | --- | --- |
| Kernel XDNA driver | DOCUMENTED: AMD path/config; exact target UNKNOWN | PLAUSIBLE_UNVERIFIED: upstream Fedora path; image/kernel UNKNOWN | UNKNOWN: inspect shipping kernel/config/device |
| Firmware | DOCUMENTED: matched AMD package | UNKNOWN: installed image/version | UNKNOWN: installed image/version |
| XRT/plugin | DOCUMENTED: vendor Ubuntu packages | PLAUSIBLE_UNVERIFIED: upstream RPM build path, not a verified vendor stack | PLAUSIBLE_UNVERIFIED: upstream Arch path, not SteamOS acceptance |
| Vitis AI inference | DOCUMENTED: vendor Linux/family support; DockSR NOT_RUN | UNKNOWN: complete runtime/ABI/placement | UNKNOWN: complete runtime/ABI/placement |
| GPU presentation | DOCUMENTED: upstream nested/embedded modes | DOCUMENTED: Gaming Mode; DockSR NOT_RUN | DOCUMENTED: Gamescope design; shipping build/DockSR UNKNOWN |
| Reversible installation | PLAUSIBLE_UNVERIFIED: user tree; host changes separate | DOCUMENTED: deployment rollback; user tree proposed | PLAUSIBLE_UNVERIFIED: user tree; official recovery links only |
| Unprivileged workflow | DOCUMENTED: inference after host setup/ACLs; target NOT_RUN | PLAUSIBLE_UNVERIFIED: ACL/runtime limits | PLAUSIBLE_UNVERIFIED: ACL/runtime limits |

Bazzite is a reasonable **intermediate research target**, not a verified NPU
platform: it offers an Atomic rollback path, a documented gaming session and
container workflows, while its Fedora/userspace stack differs from the vendor
Ubuntu reference. Establish H1 on the supported reference before attributing a
later distro failure to DockSR's model or architecture.

## Preliminary native-worker lifecycle decision

| Arrangement | Advantages | Responsibilities/limits |
| --- | --- | --- |
| User systemd service | User-level supervision and logs | Session identity/environment, memlock, suspend/restart and socket authorization still required; no automatic access to renderer resources |
| Native child supervised by controller | Explicit session environment/lifetime, separate crash boundary | Controller must bound queues, reap/stop child and await real quiescence; persistent backend is future work |
| In-process Gamescope backend | Direct ownership boundary, fewer process transitions | Runtime ABI/crash/hang can affect compositor; shutdown/fence proof and packaging are harder |

Preliminary recommendation: a **persistent native child owned by a user
controller**, with a small session-local control channel and existing frame
identity/deadline contracts. It offers controlled startup and a crash boundary
without installing a daemon. This is a design recommendation only: the current
CPU lab bridge starts a process/session per job and does not implement this
future persistent backend. Reconsider a user service after actual runtime and
session lifecycle tests justify it. Local logs stay bounded/private; no telemetry
service is installed and no diagnostics are automatically exported.

## Decky and container boundaries

The reviewed template uses `@decky/api` `callable` frontend→Python methods and
events. The loader creates plugin processes; reviewed sandbox initialization
drops to the host user unless a root flag is requested. The loader itself may
run privileged, so do not equate Decky installation with unprivileged operation
or request a root plugin to work around missing NPU access. Future controls can
enable/disable, select modes, display truthful status/summaries and request a
consented diagnostic export. Per-frame tensors and inference stay in native
components. A plugin cannot independently replace Gamescope's renderer or fix
host kernel support. No frontend or Decky installation is implemented here.

Flatpak starts with restricted device/session access; `--device=dri` is graphics
access, not proof of `/dev/accel` availability. More device permissions still
cannot replace the host driver or prove provider import/renderer access.
Sandbox library ABI, display sockets, service access and NPU device policy must
be tested explicitly. It is not selected as the primary worker packaging format.
Distrobox shares host integration and can supply a userspace build/runtime
environment, but is not an independent kernel or strong isolation boundary.
An Ubuntu container on Bazzite cannot repair unsupported host amdxdna ioctls,
firmware or ACLs. Containerized Steam/Proton adds another graphics/process
boundary; matching names or sharing `$HOME` does not establish buffer sharing.

## Read-only preflight and physical-only unknowns

```sh
python scripts/npu_probe.py --model /private/sesr_nhwc_int8_256x256.onnx \
  --inspect-ort --output /private/NEW-preflight.json
```

This extends existing detection with allowlisted CPU identity, bounded kernel
configuration reads, node permissions, current-process memlock, firmware
visibility, xrt-smi help, module metadata, Gamescope version/process counts and
sensor-file discovery. Provider metadata is opt-in. `--inspect-vulkan` separately
opts into public Vulkan inventory, which may open devices and can be truncated;
it is not an exact external-buffer query or presentation test. Normal preflight
does not repeat graphics probes. Binary gpu_metrics is detected but never parsed
without validated version/length/units. Sensor presence stays unmeasured and
power scope UNKNOWN. No environment/command-line inventory is retained.

Actual APU IDs, installed OS/session versions, firmware in use, effective ACLs,
vendor provider loading, critical operator placement, numerical agreement,
driver recovery, suspend, Gaming Mode presentation and whole-device cost all
need the physical device. Inventory always preserves NOT_RUN/false execution
claims; inaccessible fields retain unavailable status/reasons. The next bounded
implementation is P-C's controlled H1/H2 execution harness, not a driver installer.
