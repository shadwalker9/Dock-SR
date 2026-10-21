# DSR013-P SteamOS update, disable and recovery plan

This is an unexecuted acceptance protocol for a primary-use gaming device.
**Update persistence and rollback are NOT_TESTED.** No reboot/update, suspend
stress, host modification or fault injection is executed by these instructions.

| Component | Intended location / ownership | After normal SteamOS update |
| --- | --- | --- |
| DockSR worker, controller and settings | Versioned user-space/XDG tree, no autostart by default | Check manifest, permissions, dynamic-loader/GLIBC/GLIBCXX and runtime compatibility; rebuild if ABI changed |
| Models and reference inputs | Owner-controlled data tree, outside source | Recheck hashes; no model mutation or bundled licensing assumption |
| Compiled model/runtime caches | Owner-controlled cache, tuple-specific namespace | Invalidate on changed model/options/runtime/compiler/driver/firmware or unknown compatibility; preserve old evidence; never trust cache by filename alone |
| Evidence | Private owner-controlled state directory | Preserve immutable before/after records and source revision; do not publish |
| Kernel, amdxdna, firmware, device permissions and host XRT | SteamOS-owned layer A | Rediscover binding/config/loaded versions, nodes/ACL/access/memlock and ioctl/plugin compatibility; user-space package cannot repair these |
| Presentation/compositor and session | SteamOS-owned; integration deferred | Revalidate session lifetime/graphics capability after change; never overwrite shipping Gamescope |

Future activation policy: **fail closed for NPU, leave ordinary gaming usable**.
The planned worker must compare the observed host/runtime/model/options
fingerprint against a reviewed compatible tuple and refuse activation on change,
missing evidence or incompatible cache. A version number alone is insufficient.
This milestone implements inventory/checklist validation, **not that future
physical-worker startup guard**. No backend currently starts an NPU. Ordinary
gaming should not depend on DockSR; the experimental user-space controller must
remain optional. Existing GPU/CPU fallback references stay available, but a
seamless in-game NPU-to-GPU fallback is not yet implemented/proven.

## Before and after an approved normal update

1. Save passive preflight, exact device/SteamOS build/channel/kernel/config,
   binding/firmware/XRT/plugin/runtime identities, approved user-tree manifest,
   access/memlock, model/input/reference hashes, source revision, cache key and
   approved launch options. No personal identifiers or broad environment dumps.
2. Save a representative baseline gaming timing/stability record under fixed
   settings, resolution, power profile and thermal/battery conditions. Where
   available, add independently scoped power. Missing readings remain unknown.
3. Stop DockSR and keep autostart disabled before the owner performs a normal
   approved OS update. Do not suppress or freeze SteamOS updates for DockSR.
4. Rediscover after the update in ordinary user mode. Compare the entire tuple;
   record changed/unknown fields as unverified. Do not run an old compiled cache
   against a changed runtime as an experiment to see whether it crashes.
5. Re-establish H0, then separately approved H1 correctness/placement/context,
   H2 persistent complete-frame service and H3 matched GPU timing/stability.
   Revalidate any previously relied-on H4 stages. A preserved binary or a single
   successful launch does not establish update survival.
6. If any prerequisite fails, leave DockSR disabled, classify the failure and
   compare ordinary gaming to baseline. No speculative repairs, restarts of
   Steam services, reboot or module reloads. Diagnose within the affected layer.

## Disable/removal and future host rollback

For Option1, stop only the DockSR-owned worker/controller using its reviewed
lifecycle (bounded cancellation, await executor quiescence, do not free in-use
buffers). Remove any approved DockSR-only launcher reference. Archive evidence,
then remove only files enumerated under its owner-verified versioned install,
config/data/cache/state manifest; reject links/paths outside that tree. No broad
`rm -rf`, system package removal or compositor/session kill command is prescribed.
Verify no DockSR child/launcher remains and ordinary gaming still starts with its
original settings. The actual manifest, uninstaller and removal test are future
work, not a claimed proven rollback.

For Option2, the analogous scope is the explicitly named container/image/volume;
never remove unrelated containers. For any future Option3 host change, approval
must contain the exact device/build-specific change, elevation, risk, backups,
supported restoration commands and known-good recovery access. If those are
unknown, **do not modify the host**. Valve recovery/reimage can be destructive;
do not invoke it as an automatic fallback. The owner separately approves any
reboot, recovery media, external boot, reimage or repair. We have not verified
the actual device's rollback mechanism or exercised it.

Acceptance evidence must include same-device before/after records for a normal
update and separately demonstrated disable/removal without loss of ordinary
gaming. Scope any resulting support claim to the observed tuple/update path,
not all SteamOS versions. A SteamOS-update regression never justifies freezing
the owner's system. See [deployment options](steamos-deployment-decision.md).
