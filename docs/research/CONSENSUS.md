# Current engineering consensus

[Research hub](README.md) | [Sources and limits](SOURCES.md)

These decisions are provisional and revisable through reproducible evidence.
Confidence describes the engineering rationale, not a physical performance
result. R-008 is unavailable; its later handoff outline is not primary evidence.
All target-hardware validation below remains **NOT_TESTED**.

## C-001 — SteamOS first

- Source: owner v2.2/v2.3; supersedes R-009's Ubuntu-first suggestion.
- Decision/reason: accept the actual primary-use Z2 Extreme SteamOS environment.
- Alternative: Ubuntu-first or replacing the gaming OS; diagnostic only with
  separate approval, not a substitute for SteamOS support.
- Confidence: high as product direction; compatibility unknown.
- Revisit: owner changes target; inspect shipping build before technical choices.
- Implementation: readiness/preflight and deployment plan; no target installation.
- Hardware validation: NOT_TESTED.

## C-002 — NPU-first, GPU-assisted

- Source: R-007, retained by R-009; supersedes R-005's preferred tiny-guide product.
- Decision/reason: investigate learned reconstruction on dedicated NPU capacity;
  GPU prepares/resolves/composes rather than assuming spare GPU compute.
- Alternatives: GPU-only or compact guidance; retain as research contingencies.
- Confidence: moderate hypothesis for useful gaming performance.
- Revisit: poor compiler mapping, quality, complete-frame service or shared-power cost.
- Implementation: CPU contracts/references, no physical integrated pipeline.
- Hardware validation: NOT_TESTED.

## C-003 — Preserve GPU-only fallback

- Source: R-005–007 and owner reliability/NPU-MVP requirement.
- Decision/reason: optional acceleration must not make ordinary gaming depend on
  an experimental worker; keep existing conventional reconstruction available.
- Alternative: mandatory NPU path; unacceptable failure coupling.
- Confidence: high reliability principle, no seamless game fallback proof.
- Revisit: improve fallback quality/selection from observed failures; do not waive
  verified NPU contribution for the first usable NPU version.
- Implementation: CPU/GPU references and worker deadlines; game integration pending.
- Hardware validation: NOT_TESTED.

## C-004 — Host-stage initial inference

- Source: R-005, R-007, R-009; AMD deployment APIs [S-001](SOURCES.md).
- Decision/reason: isolate correctness/placement/service from speculative imports.
- Alternative: require Vulkan-to-Vitis zero-copy before any useful experiment.
- Confidence: high for diagnostic simplicity; total cost unknown.
- Revisit: H2/H3 establish useful compute and measured staging dominates the budget.
- Implementation: CPU host buffers and H1 preparation; no physical transport proof.
- Hardware validation: NOT_TESTED.

## C-005 — Persistent session, reusable buffers and compatible caches

- Source: R-007/009, AMD deployment [S-001](SOURCES.md).
- Decision/reason: exclude repeated initialization from warm service and avoid
  unnecessary allocation; record cold compilation/cache behavior separately.
- Alternative: new session/process per tile; retain only as a measured lab baseline.
- Confidence: high design rationale, unmeasured AMD savings.
- Revisit: installed API/lifetime constraints or unstable/mismatched caches.
- Implementation: reusable CPU session; H1 laboratory rather than native daemon.
- Hardware validation: NOT_TESTED.

## C-006 — Unchanged SESR-M7 2× for physical proof

- Source: R-005–007/009, AMD model/example [S-003](SOURCES.md).
- Decision/reason: use the existing hash-verified INT8 NHWC256→512 model and CPU
  golden before training/exporting or changing shapes.
- Alternative: start with a custom model or treat the fixed2× artifact as native3×.
- Confidence: high artifact/reference identity; XDNA compilation not established.
- Revisit: reproducible unsupported graph/runtime result, investigated without mutation.
- Implementation: inspector, actual CPU tile/full-frame outputs, halo11/core234/24 tiles.
- Hardware validation: NOT_TESTED.

## C-007 — Native3× remains production-model research

- Source: R-007, deferred by R-009; ESPCN principle [S-008](SOURCES.md).
- Decision/reason: low-resolution convolutions then DepthToSpace3 match exact
  720p→4K geometry; RGB final channels are27, not an assumed generic channel count.
- Alternatives: SESR2× plus GPU1.5× transition, reparameterized networks, tiny guides.
- Confidence: moderate architectural hypothesis; quality/INT8/compiler unknown.
- Revisit: measured quality, operator support, locality or whole-frame cost fails.
- Implementation: owned untrained FLOAT32 graph fixture, no production weights.
- Hardware validation: NOT_TESTED.

## C-008 — Worker proof before further presentation integration

- Source: R-006's separation of ownership plus later owner v2.2/v2.3 ordering.
- Decision/reason: prove genuine inference before coupling failures to Gamescope.
- Alternatives: continue presentation-first lab or game-specific DLL injection.
- Confidence: high scope/risk decision; eventual integration point provisional.
- Revisit: H1/H2 correctness/service and transport budget support integration.
- Implementation: existing pinned patch builds; runtime blocked, no neural presentation.
- Hardware validation: NOT_TESTED.

## C-009 — Import is not zero-copy inference

- Source: R-005/009; XRT, ORT and Intel references [S-004–006](SOURCES.md).
- Decision/reason: distinguish export, BO import, EP importer, tensor binding,
  actual consumption, synchronization and end-to-end benefit; hidden copies matter.
- Alternatives: infer shared-tensor support from a DMA-BUF FD, provider or version.
- Confidence: high boundary distinction; Vitis importer UNKNOWN.
- Revisit: installed provider demonstrates each H4 stage with correct shared I/O.
- Implementation: staged contracts/plans only; no zero-copy implementation.
- Hardware validation: NOT_TESTED.

## C-010 — Bound and measure concurrency

- Source: R-009 HYP-006/007; existing worker ownership/deadline contract.
- Decision/reason: test1→2→stable3 tile inference requests; separately record frames
  resident and session count. Select by complete-frame age/service and GPU cost.
- Alternative: unbounded queue or choosing a winner by tile throughput alone.
- Confidence: moderate optimization hypothesis, high need for bounded ownership.
- Revisit: no gain beyond variance, latency/memory/queue growth or GPU contention.
- Implementation: two-slot default worker preserved; no speculative third-slot change.
- Hardware validation: NOT_TESTED.

## C-011 — Matched whole-device benefit is the efficiency criterion

- Source: R-005/006/009, owner goals and existing H0–H6 plans; R-008 outline unrechecked.
- Decision/reason: compare identical workload/settings/quality at fixed approved
  power profile, with actual scoped energy and presented frames where measurable.
- Alternatives: isolated TOPS, kernel time, configured TDP or unmatched FPS claims.
- Confidence: high methodology; power/quality instrumentation pending.
- Revisit: refine representative workloads, sensors and acceptance from actual data.
- Implementation: offline paired analysis and gate plans; no measured gaming advantage.
- Hardware validation: NOT_TESTED.

## C-012 — Minimal reversible deployment

- Source: owner v2.2/v2.3; R-006/009 constraints; SteamOS readiness/update plan.
- Decision/reason: prefer unprivileged user-space if the host supports it; preserve
  ordinary gaming and updates. Refuse speculative NPU activation on incompatible hosts.
- Alternatives: privileged installer, frozen updates or replacing kernel/firmware/OS.
- Confidence: high protection principle; actual packaging/update survival unknown.
- Revisit: unavoidable host prerequisite requires a separately approved exact plan
  and supported rollback; absence of such a plan means stop.
- Implementation: read-only discovery and proposed lifecycle; no installer/rollback proof.
- Hardware validation: NOT_TESTED.
