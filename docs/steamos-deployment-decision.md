# DSR013-P decision: SteamOS user-space first (PROVISIONAL)

The owner's primary-use SteamOS device is the acceptance environment. No system
installer is delivered. R-009's Ubuntu-first ordering is superseded by handoff
v2.2. All four options below are untested on that device.

| Option | Host changes / elevation | Compatibility and update sensitivity | Disable, removal and recovery | Missing evidence / primary-use suitability |
| --- | --- | --- | --- | --- |
| 1. Unprivileged relocatable worker | None if the installed driver, firmware, permissions, memlock and XRT pairing are already sufficient; no root | Match host kernel/plugin ABI and user-space loader/glibc/runtime; user tree may persist but host updates invalidate approval | Stop only DockSR child, await quiescence; disable launcher; retire the manifest-owned user tree and caches after preserving evidence; ordinary gaming uses its normal path | Exact SteamOS tuple, EP dependencies, packaging/model rights, update/removal and stability untested; preferred smallest disruption |
| 2. Container user-space worker | No automatic host changes; explicit device access authorization; rootless feasibility UNKNOWN; privileged container not approved | Container packages B only; host amdxdna/firmware/ioctls/permissions/memlock remain mandatory; libc/runtime/device pass-through and graphics IPC require proof | Stop scoped container, remove only its named image/volume according to reviewed manifest; no system-wide prune; restore original launcher | Working rootless device binding, synchronization, packaging and runtime support UNKNOWN; secondary choice if B cannot be relocated |
| 3. Minimal unavoidable host integration | Driver/firmware/permissions/XRT changes may require root; prohibited until exact command/risk/rollback receives owner approval | Highest coupling to Valve kernel/build, firmware and update mechanism; never replace distro blindly with Arch/Ubuntu recipes | Before execution, document precise previous artifacts/config and supported restoration for the observed OS; if rollback cannot be specified, do not proceed | Necessity and supported mechanism UNKNOWN; least suitable for a daily-use device, block rather than improvise |
| 4. Reference-environment diagnostic | Separate owner authorization for medium/boot/OS changes; no external boot, dual boot, partitioning or install authorized | AMD documentation can help isolate runtime vs SteamOS defects; results do not pass SteamOS gates | Review device-specific return-to-normal-boot and data preservation plan before any test; no generic recovery assumption | Diagnostic only; prefer available separate hardware; never the project's primary success criterion |

Choose **Option1 PROVISIONALLY**, contingent on H0 inspection. Begin with a
manually launched persistent native worker in a versioned user directory, no
autostart/service/compositor replacement. This is a deployment design; today's
CPU bridge still creates one process/session per job. Neither a persistent Vitis
backend nor a SteamOS binary bundle is implemented by this decision.

Keep host A, inference B, scheduling C and presentation D separate as described in
[readiness](steamos-first-readiness.md). Decky eventually controls status/settings
at low frequency; it is not tensor transport. Future runtime redistributions,
model weights and third-party notices need their own review. No LICENSE selected.

If H0 exposes an incompatible host driver or firmware, stop accelerator work,
keep ordinary gaming untouched and report the specific blocker. A container is
not a driver substitute. Propose the smallest supported remedy only after
device-specific evidence, with reversible commands and an explicit approval
request. Never disable security controls, updateability or protected-root policy.
