# SteamOS-first XDNA2 readiness — DSR013-P, contract v1.0.0

The primary target is **AMD Ryzen AI Z2 Extreme running SteamOS**. Other Linux
distributions are secondary development/diagnostic environments, never substitutes
for SteamOS acceptance. The owner handoff v2.2 overrides R-009's Ubuntu-first
recommendation. No physical SteamOS device has been tested: compatibility,
performance, update survival and rollback are **NOT_TESTED**.

## Four separate layers

| Layer | Responsibility | Current evidence |
| --- | --- | --- |
| A: SteamOS host | Exact PCI/APU identity; kernel/config, bound amdxdna, compatible firmware, device access, matching XRT SHIM/plugin and memlock | Target UNKNOWN; no host changes authorized |
| B: user-space inference | Compatible ORT/Vitis AI EP and dependencies, unchanged model, compiled caches, persistent worker | CPU references exist; physical Vitis worker not implemented |
| C: reconstruction/scheduling | Existing tiling, stable frame/session/generation identity, deadlines, bounded buffers, fallback, evidence | Host contracts tested; target timing unknown |
| D: gaming presentation | Gamescope/SteamOS transport and final neural-frame consumption | Deferred; existing experiment build-only |

A container can supply B, subject to ABI/licensing, but cannot supply a missing
or incompatible A. Neither an Arch recipe nor a sufficiently high kernel version
establishes SteamOS support. The exact installed build, configuration, firmware,
XRT/plugin ioctls and Vitis binary must work together. No `/opt/xilinx/xrt/setup.sh`
location or Ubuntu package manager/layout is assumed.

## Readiness matrix

All initial statuses below are **NOT_TESTED**. A cloud/fixture test does not change
them. `UNKNOWN` records an inspected but unresolved answer, not measured failure.

| Area / machine key | Evidence required to evaluate it |
| --- | --- |
| Exact APU/NPU / `device_identity` | CPU family/model/stepping and owner-confirmed product/APU; actual PCI vendor/device IDs and NPU binding, not marketing name alone |
| SteamOS / `steamos_build` | Allowlisted `/etc/os-release` ID, VERSION_ID, BUILD_ID, VARIANT_ID; release channel manually recorded if needed |
| Kernel / `kernel` | Release/architecture, selected kernel config; missing config is unknown, not disabled |
| Driver / `npu_driver` | Actual PCI binding, module version/srcversion if exposed; installed module/package/build provenance reviewed separately |
| Firmware / `firmware` | Installed path/version/hash and actual loaded/compatible firmware evidence; a visible directory is insufficient |
| Access / `device_access` | Relevant character nodes `/dev/accel/accelN`, `/dev/dri/cardN`/`renderDN`, modes and current-process access; permissions alone do not prove usable ioctls |
| XRT / `xrt` | Actual library, base and NPU plugin versions/provenance, paired driver support, platform visibility if approved |
| Vitis / `vitis_ep` | Actual runtime/module version and provider query in the intended environment; registration is not execution |
| Inference / `model_execution` | H1 unchanged-model identity, placement, simultaneous active context and declared CPU agreement; canonical hardware record |
| Updates / `update_survival` | Same-device before/after fingerprints and revalidation across an owner-approved normal update |
| Removal / `reversibility` | Demonstrated disable/removal of approved user-space experiment with ordinary gaming intact |
| Gaming / `gaming_impact` | Paired timing/stability and valid power evidence; standalone inference does not pass this area |

The versioned [schema](../schemas/steamos-readiness.schema.json) uses
`NOT_TESTED`, `SUPPORTED_BY_DOCUMENTATION`, `OBSERVED_ON_DEVICE`, `PASS`, `FAIL`,
`BLOCKED`, `UNKNOWN`, `NOT_APPLICABLE`. NOT_APPLICABLE needs an owner's/reviewer's
written rationale in referenced evidence; it cannot satisfy an essential PASS.
Documentation support is a source fact, not a target execution observation.

The checklist holds artifact-relative names and SHA256 references, not private
artifact bodies. `scripts/steamos_readiness.py --validate FILE` checks schema,
UTC timestamp, reference integrity, device/documentation distinctions, gate order,
H1 evidence categories, H4 prerequisites and SteamOS-only acceptance. Validation
does not open/execute referenced artifacts or attest their authenticity. Review
their hashes/content independently. Reject unknown schema versions and fields.

This is a readiness ledger, **not a second inference evidence format**.
`npu_execution_claim=NOT_ATTESTED` and `hardware_execution_verified=false` are
fixed, even when historical gate evidence is referenced. REAL_NPU belongs only
in the existing [hardware-evidence contract](../schemas/hardware-evidence.schema.json),
with [physical gate requirements](hardware-gates-steamos.md) independently met.
Passing detection cannot promote inference, performance or whole-OS acceptance.

## Passive preflight

Run as the ordinary logged-in user from a reviewed source tree, with the project's
existing development dependencies already available. This command installs none:

```sh
mkdir -m 700 /tmp/docksr-discovery-NEW
python3 scripts/steamos_readiness.py --output /tmp/docksr-discovery-NEW/preflight.json
python3 scripts/steamos_readiness.py --validate /tmp/docksr-discovery-NEW/preflight.json
```

Use a fresh name and copy evidence privately if it must survive reboot; `/tmp`
is temporary. Output must be an explicit new file outside all Git checkouts,
with an existing owner-controlled0700 parent; file0600, no overwrite/symlink.
The output path is supplied by the user and is not echoed in JSON or errors.

Discovery reuses `docksr_detect.FileSystem`, `npu_probe.kernel_config`, runtime
**distribution metadata only**, and the existing private writer. It stats nodes
and checks access without opening them. It reads allowlisted OS/CPU fields,
numeric AMD PCI identity/binding, selected module/firmware attributes, memlock and
kernel config. Default commands are exactly `uname -r`, `uname -m`, `lspci -n`:
no hostname or named peripheral inventory. The latter retains numeric AMD lines
only. Each command records argv, outcome and actual exit status (null for missing,
interrupted or unlaunched tools); raw stdout/stderr and executable paths are
discarded. Failed tools and absent tools are different. Public commands are
bounded by the existing runner's deadline and retained-text limit; this is not a
sandbox for malicious executables found in PATH. Use a trusted environment.

No usernames, owner/group names, home paths, network identifiers, Steam data,
serial fields, process command lines or environment dumps are collected. The
script deliberately omits `uname -a`, raw `/proc/version`, raw `lspci -nn`, raw
os-release and arbitrary error text. Firmware filenames, runtime library paths
and exact provider/options remain separate reviewed H0 evidence, not guesses.

Discovery never invokes XRT, modinfo, Vulkan, ORT module imports, inference,
services, package managers or device validation; tool availability is a boolean.
It does not label the cloud as the target device. Even discovery on SteamOS
leaves all hardware gate statuses NOT_TESTED until independently evaluated.
There is no automatic failure diagnosis or repair.

Separate opt-in follow-up after reviewing the installed tool's documentation:
public XRT version/help/platform queries may open the device; provider listing
loads code in the selected environment. Preserve command/status privately and
review results. `xrt-smi validate` runs an active workload and requires a separate
owner-approved phase. Do not source an unreviewed setup script or raise memlock.

Owned [fixtures](../tests/fixtures/steamos-readiness/README.md) cover the no-device
plan, explicitly fictional H1 metadata and rejected contradictions. Tests do not
create a successful SteamOS measurement.

## Order and compatibility unknowns

1. Passive discovery, owner confirms exact device/APU and installed SteamOS build.
2. Review A and B without modification. Unproven host/runtime pairing blocks NPU
   activation; record absence vs permission denial vs unknown metadata separately.
3. Follow H0–H4 in [gate order](hardware-gates-steamos.md); persistent host staging
   precedes concurrency, GPU contention and any import experiment.
4. Apply [deployment](steamos-deployment-decision.md) and
   [update/removal](steamos-update-recovery.md) acceptance before calling SteamOS
   supported. Scope acceptance to the tested hardware/build/runtime tuple.

Does the shipping kernel bind this exact NPU? Is loaded firmware compatible?
Are devices accessible? Do XRT and Vitis run without host replacement? Which
files persist after updates? Can removal restore the normal user experience?
All remain UNKNOWN pending device evidence. The existing
[integration map](STEAMOS_INTEGRATION_MAP.md) supplies source-backed comparisons,
not answers about this device. Host H1/H2 runners, timed collectors and the full
hardware kit remain pending; this milestone supplies preparation contracts.
