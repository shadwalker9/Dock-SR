# DockSR research

[Overview](../../README.md) | [Current consensus](CONSENSUS.md) |
[Primary sources](SOURCES.md) | [Project status](../PROJECT_STATE.md)

DockSR investigates image reconstruction that could keep existing gaming devices
useful for longer. The primary target is **Ryzen AI Z2 Extreme running SteamOS**.
We want to learn whether dedicated NPU work can improve reconstruction while
preserving the GPU capacity and whole-device budget games need. Neither a model
benchmark nor an NPU capability listing establishes that benefit.

This hub contains original summaries of project research, not copies of private
papers. R-005, R-006, R-007, R-009 and R-010 were available for source review. **R-008's
original document was unavailable**: its entry below is the later owner handoff's
editorial outline, cross-checked against existing implementation plans, not an
independent summary of the missing paper. Not every upstream claim in the papers
has been independently reproduced. [Sources](SOURCES.md) distinguish documentary
support from DockSR measurements; later owner decisions supersede older proposals.

## Research timeline

| Research | Investigation and evolving conclusion | Current validation |
| --- | --- | --- |
| R-005 | AMD Linux runtime/model feasibility; actual execution versus provider discovery; Vulkan/XRT sharing versus inference-tensor import. Start with unchanged SESR and host staging. The paper preferred compact NPU guidance with GPU reconstruction for the product; R-007 later shifted that research priority. | Model inspection/CPU references and host scheduling exist; physical execution pending |
| R-006 | Linux presentation/deployment: separate Gamescope frame ownership, native inference and Decky control; avoid game-specific DLL injection as the universal path. The paper proposed a rendering lab first; that lab exists as build-only evidence, while current owner direction defers further presentation work until inference proof. | Pinned Gamescope patch builds; runtime/presentation acceptance blocked; no neural game frame |
| R-007 | INT8 feasibility and an NPU-first division of work; unchanged SESR-M7 2× for hardware proof, native3× low-resolution ESPCN-class networks for later production research. Temporal FSR inputs/weights cannot simply be assumed available to a final-frame compositor. | Actual SESR CPU reference; untrained FLOAT32 exact3× contract, no trained/quantized production model |
| R-008 | **Original missing; detailed contents not independently rechecked.** Later handoffs describe runtime/firmware coupling, host staging, reproducible H0–H6 gates and fixed-power comparisons. Treat this as an outline requiring reconciliation. | Existing gate/analysis preparation, not a physical result or verified account of the missing paper |
| R-009 | Cross-vendor memory sharing, hidden copies, compiler-aware tiles and bounded concurrency. Learn context/lifetime/copy visibility from Intel; do not infer identical AMD APIs. Prefer persistent sessions, buffers and cache reuse before speculative transport/custom engines. | Relevant source capabilities documented; AMD complete path and performance unmeasured |
| [R-010](R-010.md) | Emerging Linux runtime evidence retains Vitis conditionally; compares IRON/xdna-engine/Triton as deferred alternatives, distinguishes HSA/HIP sharing from Vulkan, adds caller/user-manager memlock and graduated H3 planning. | Source mechanisms and community observations; SteamOS/Z2 execution and benefit remain NOT_TESTED |

R-009 and the R-008 outline proposed an Ubuntu reference environment before
gaming distributions. **The owner superseded that order: SteamOS is the primary
physical validation environment.** Ubuntu is an optional, separately approved
diagnostic reference, never a required replacement OS or a SteamOS acceptance
result. See [readiness](../steamos-first-readiness.md).

## Architecture and implemented evidence

Current design: frame coordinator → GPU fallback or host-staged native NPU worker
→ GPU reconstruction/composition → future presentation integration. Decky would
control settings/status at low frequency; JavaScript/Python plugin calls do not
carry per-frame image tensors. A standalone Python H1 laboratory is distinct
from that eventual native product worker.

Read the [twelve revisable decisions](CONSENSUS.md),
[CPU full-frame reference](../fullframe-reference.md),
[bounded H1 laboratory](../h1-inference-harness.md),
[worker ownership contract](../inference-worker.md),
[H0–H4 experiment plan](../hardware-gates-steamos.md),
[benchmark definitions](../benchmark-laboratory.md) and
[twelve R-009 hypotheses](../r009-hypotheses.json). The existing Gamescope
experiment is documented [separately](../../experiments/gamescope/README.md).
Prepared experiments and CPU/software-rendering checks are not physical validation.

## What We Have Not Proven Yet

- No verified physical XDNA2 execution yet.
- No SteamOS compatibility established yet.
- No sustained24-tile NPU throughput measured.
- No measured NPU/GPU concurrent gaming benefit.
- No demonstrated zero-copy Vitis inference tensor path.
- No completed neural frame presentation in Gamescope.
- No trained production-quality native3× model.
- No measured FPS, image-quality or energy advantage for DockSR.
- No released, supported Decky-based product.

The first usable version requires verified NPU contribution. GPU fallback remains
essential for reliability but does not waive that acceptance criterion. Numerical
FPS/power/quality objectives in project documents remain targets, not promises.

## How to Continue This Research

Reproduce [development tests](../development.md) and the documented references.
Verify upstream runtime/API behavior against exact installed versions; report the
hardware/APU, OS/build, kernel, driver, firmware, runtime, model hash, settings,
evidence scope and failures. Share only owner-approved, privacy-reviewed benchmark
evidence. A provider list or synthetic fixture is not an NPU measurement.

To challenge a decision, identify its consensus ID, state a falsifiable hypothesis,
baseline, required capability, correctness/quality criterion, matched conditions,
measurement, uncertainty and stop rule. Propose the smallest reproducible
experiment through normal repository review. Keep hardware experiments separate
from installation or privileged-change requests. Measurements can change our
architecture; assumptions alone should not.

DockSR remains human-directed and AI-assisted; see the
[disclosure](../../README.md#ai-assisted-development-disclosure). Formal project
licensing and contribution terms are pending. Reading these summaries is not a
new grant of redistribution/forking rights; publicly accessible third-party code,
models and diagrams retain their own terms. No private papers, weights, figures
or runtime packages are redistributed here. Public release and licensing are
separate future owner decisions.
