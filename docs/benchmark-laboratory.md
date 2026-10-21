# Offline benchmark laboratory — DSR012-P checkpoint P-A

`scripts/benchmark_analysis.py` analyzes supplied traces. It neither collects
hardware measurements nor attests execution, placement, quality or presentation.
The existing `hardware-evidence.schema.json` remains the evidence contract:
its optional `benchmark_run` extension holds platform/software identity, paired
conditions, tensor precision/layout, image extents, power profile, raw artifact
references and lifecycle events. Existing records remain valid without it.
Do not create a second NPU-success schema or relabel CPU/mock observations.

## Input and reproduction

Use the existing host development Python environment with the hash-locked
`requirements-dev.lock` dependencies. The separate inventory command remains
standard-library-only unless its ORT module query is explicitly requested.

Use the existing hardware record fields for model SHA/ID, tensor shapes, runtime,
backend, driver and placement provenance. Put experiment/run/session/pair IDs,
device/OS/kernel/software descriptions and the observation interval in
`benchmark_run`. The schema defines the exact required fields. Unavailable
versions must be identified as unavailable, never guessed from a package name.
Raw trace samples remain inline in the input JSON; `raw_evidence_refs` also
identifies the original collector artifacts by relative path and SHA256. The
analyzer checks structure/consistency, not those files' authenticity or hashes.
Retain the original record alongside the analysis. No automatic upload occurs.

```sh
python scripts/benchmark_analysis.py /private/run.json \
  --output /private/NEW-analysis.json
python scripts/benchmark_analysis.py \
  --paired /private/baseline-1.json /private/experiment-1.json \
  --paired /private/baseline-2.json /private/experiment-2.json \
  --paired /private/baseline-3.json /private/experiment-3.json \
  --output /private/NEW-comparison.json
```

The output parent must be owned/private (0700), outside Git, and already exist.
New result files use0600; overwrite and symlink/Git destinations are refused by
the existing probe writer. Omit `--output` for local stdout. Input JSON is limited
to16MiB,10,000 frame records and100,000 power readings. Duplicate JSON keys,
nonfinite values and unknown fields are rejected. The legacy Gate-0 validator
CLI retains its1MiB intake limit; use the analysis CLI for larger trace records.

## Counts, clocks and statistics

Lifecycle is a monotonic prefix:
`SUBMITTED → STARTED → COMPLETED → VALIDATED → CONSUMED → PRESENTED`.
The single-session trace cannot repeat a frame ID, even across configuration
generations. A cancelled queued request needs an explicit cancellation time;
active execution is never inferred cancelled from an expired deadline.
Dropped frames cannot also be presented. Presentation can be `NOT_RUN` or
`UNAVAILABLE`, yielding null presented counts/rates rather than invented zeros.

All event timestamps use declared host/pipeline monotonic **integer nanoseconds**
in one clock domain. Mixed units are rejected, not guessed. Vulkan/NPU device
timestamps require a future calibrated collector before conversion to this
domain; generic API presence is insufficient. The observation contains the
entire submitted trace and starts with an empty queue. Events outside its bounds
are rejected; a queued remainder at the end is explicit backlog.

- Complete/validated neural-frame throughput counts unique nonfallback frames;
  validated frames require every declared tile. Tile rate counts completed
  tiles, including partial work on unsuccessful frames. Do not multiply tile
  throughput by frame rate or call partial work complete frames.
- Presented FPS counts valid presented records over the observation duration,
  including explicitly recorded fallback frames. Fallback/drop counts remain
  separate; a displayed fallback cannot masquerade as neural reconstruction.
- Frame-time samples are consecutive presentation intervals. They are distinct
  from render duration, request latency and physical display timing. Request
  latency is nonfallback start→completion on the host clock, including any work
  inside that scope; it is not an isolated NPU-kernel timer.
- p50/p95/p99 use nearest rank. Minimum sample counts are2/20/100 respectively;
  smaller distributions return null with an insufficient-sample flag. These are
  minimum reporting guards, not guarantees of stable tails.
- 1% low FPS is `1000 / mean(slowest ceil(N*0.01) intervals_ms)`, with at least100
  presentation intervals. It is not the mean of per-frame FPS or reciprocal p99.
- Queue depth combines simultaneous events without inventing sub-tick ordering.
  Growth is final queued count/observation seconds. Deadline rate uses requests
  whose deadlines have become due; completion at the deadline is late. Future
  deadlines are excluded from that denominator. Due cancelled/failed requests
  without completion count as unmet service deadlines; drop/fallback counts
  separately describe those failures.

Paired runs must share a pair ID and declared device/OS/software, workload/quality
condition ID, source/output extents and power profile. Pair and run IDs cannot repeat.
The tool returns individual deltas and mean paired differences; it never averages
run percentiles and labels them pooled. With at least three complete pairs, a
two-sided Student-t95% interval describes mean paired differences, assuming
independent representative pairs; otherwise uncertainty is unavailable. This
does not verify matched quality, thermal stability or experimental independence.
Predeclare those conditions; favor3–5 warmed, alternating A/B pairs before any
benefit claim. A single favorable run cannot establish a product advantage.

## Guarded energy

Power samples are finite nonnegative **watts**, timestamped in the same domain.
Trapezoidal integration interpolates observation edges and requires bracketing
samples with no in-window gap above the predeclared `max_gap_ns`. Select a gap
limit justified by the actual sensor cadence; a permissive limit is not evidence
of sufficient sampling. Unknown scope/source, clock mismatch, missing coverage,
charging/discharging or unknown battery state prevent an energy calculation.
The initial protocol accepts only stable AC observations; battery experiments
need a separately justified comparison protocol.

Energy per presented frame additionally requires recorded presentation and at
least one valid presented frame. Missing sensors/readings remain null, not zero.
The configured35W limit is metadata, not measured watts. `PACKAGE` energy is
scoped package energy; `NPU_FIRMWARE_ESTIMATE` is a firmware estimate, not isolated
rail power. Only a justified `WHOLE_DEVICE` source can support a whole-device
claim. Paired energy deltas require matching source/scope/battery state.

## Checkpoint and remaining harness

P-A provides offline analysis and synthetic known-answer/negative tests. P-B
extends [read-only preflight and Linux mapping](STEAMOS_INTEGRATION_MAP.md).

| Gate | Current command/interface | Actual status |
| --- | --- | --- |
| H0 | `scripts/steamos_readiness.py --output NEW.json`; legacy model/opt-in queries in `npu_probe.py` separate | Passive inventory implemented; target compatibility/inference NOT_TESTED |
| H1 | [Existing device-day procedure](npu-device-probe.md) | [Persistent H1 attempt](h1-inference-harness.md) implemented; physical proof adapters/measurements pending |
| H2 | CPU `scripts/sesr_fullframe.py` | CPU-only reference; physical persistent-session runner remains P-C |
| H3 | Matched GPU workload ± physical NPU | [DSR013-P protocol](hardware-gates-steamos.md); collectors/measurements pending |
| H4 | Eight-stage import/binding/synchronization ladder | [DSR013-P protocol](hardware-gates-steamos.md); implementation/measurements pending |
| H5 | Neural frame-linked Gamescope presentation | Existing lab build-only, runtime blocked |
| H6 | Matched quality/power user-value comparison | Protocol pending; no benefit established |

At40FPS,24-tile neural reconstruction demands960 tile completions/s sustainably.
This is an arithmetic requirement, not an NPU forecast. Checkpoints P-C/P-D/P-E
remain unimplemented in this bounded P-A/P-B session; do not call the whole
hardware laboratory ready or substitute metadata for physical results.
