# Verified full reports in the U.S. Code daemon

Implementation update, 2026-09-25. Full-report reuse is opt-in. Native performance
qualification was invalidated by source drift; no speedup is established. The
Constitution remains unformalized. Only `lake build <Lib>` is a Lean admit.

## Why this boundary changed

The [target-only daemon measurement](autoencoder_daemon_shared_targets.md) made
initial evaluation faster but increased the complete daemon call from 93.382 to
106.976 seconds. Native target generation normally warms the multiview report
cache. Supplying just the targets left independent diagnostics to regenerate
those reports. That negative result remains the baseline for this follow-up.

The new artifact retains the full native reports and derives training targets
from their shared document objects. Training and diagnostics consume the same
verified selection. Predictions, losses, diagnostic aggregation, proof outcome
counts, grammar checks and candidate acceptance still run in their existing
consumers. No diagnostic success is inferred from the existence of a target.

## Implemented path

The [preparation builder](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_report_preparation.py)
generates reports once with the pinned producer configuration. It preserves
partial reports, explicit failures and adapters that return no report. Outer
timeouts remain missing outcomes. It publishes no bundle after source drift or
an unexpected producer exception. Source-record authority and complete corpus
membership remain the caller's responsibility.

The [report codec](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_report_bundle.py)
uses a versioned DAG representation of seven exact native report classes. It
preserves scalar values, container order and shared object identities, rejects
cycles and unknown classes, and verifies derived targets against the unchanged
target codec. File identities, sample/vector identities, producer settings and
source hashes are bound together. Existing target artifacts remain unchanged.
The v3 DAG format uses fixed positional node tags, flattened dictionary entries
and declared native field order. It keeps v2's repeated-long-string table; the
reader supports v1 and v2 too. A code-derived schema digest binds the node tags
and fields. Compact shapes and references are checked before native construction,
then normalized one node at a time through the existing validators. String values
remain exact; immutable scalar object identity is not claimed.
The limits include 64 MiB encoded report shards, 256 MiB selected DAG bytes,
256 MiB expanded-tree arithmetic per report and 64 MiB derived target bytes.
These byte bounds do not promise the same bound on Python resident memory.

The [report session](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_report_session.py)
validates the actual train/acceptance-validation union, hydrates one selection,
and checks provenance before persistence and at shutdown. A missing selected
report fails the session; it cannot become a fabricated target. Unsupported
custom consumers, bounded sample clones or different diagnostic bridge lists
retain the whole-cycle live path with a recorded reason. Bridge-off execution
does not open a report bundle. A failed provisional cycle suppresses its final
clean-shutdown checkpoint; previously validated writes are not rolled back.

The [runner](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py)
accepts four all-or-none options:

- `--autoencoder-report-bundle`
- `--autoencoder-report-bundle-sha256`
- `--autoencoder-report-bundle-bytes`
- `--autoencoder-report-snapshot-id`

They are mutually exclusive with the four target-bundle options. Paired mode
forwards them only to the autoencoder child. Both independent diagnostic calls
receive explicit reports; their original aggregation remains intact. This path
bypasses diagnostic cache reads and writes and records `explicit_reports` and
`supplied_report_count`, rather than counting artifact reuse as ordinary cache
hits. Base/bridge-off evaluation and asynchronous snapshot evaluation retain
their existing paths.

## Qualification

The final combined regression has 286 passing tests: 106 codec, 36 report-session,
14 preparation/harness, 29 existing target-session, 60 runner/reuse, 31 semantic
gate/pilot, and 10 historical wire-profile checks using explicit v2 fixtures.
Codec, runner and harness changes received independent read-only reviews. The
broader daemon suite supplies 240 additional distinct passes and one known
pre-existing failure: a default-bridge assertion expects six names while the
current registry contains seven. The registry was not changed. In total, 526
distinct tests pass. The required 31 semantic gate/pilot checks also passed again
after the external source change. The [validation receipt](evidence/autoencoder_control_plane_plan/daemon-shared-report-final-validation-20260925.json)
records file identities, tests, documentation links, retained failures, source
drift and protected-checkpoint checks.

The [native harness](../../../scripts/ops/legal_ir/benchmark_daemon_shared_reports.py)
prepares a fresh bundle, independently fingerprints original and decoded native
fields/types/order/aliases, then compares cold and shared actual daemon cycles.
Only its local source/vector loader is adapted; timed evaluation, projection,
diagnostics and persistence are native. Cold report capture happens after the
daemon timer and is tied to the actual optimizer target cache and recorded
document hashes. Whole child-process times include asymmetric evidence export
and must not be presented as a fair daemon throughput comparison.

The requested bridge list is `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, `external_prover_router`; the prover flag is false and sample/adapter
workers are one. Metric disk cache is zero, and preparation bypasses multiview
process caching in a fresh process. OS caches and host contention are
uncontrolled. Preparation and the single-record diagnostic do not load a model
or use sample memory. A false prover flag does not disable every existing local
router/FLogic operation and does not imply Lake evidence.

The [first native attempt](evidence/autoencoder_control_plane_plan/daemon-shared-report-native-20260925.json)
stopped during preparation after 68.616 seconds. Four records returned all five
adapters, but encoding the fourth report exceeded the 64 MiB shard bound. The
first three encoded DAGs were 44,435,537, 20,434,663 and 47,055,426 bytes; the
fourth exact size was not returned. No bundle was published and neither daemon
arm ran. Source, harness and protected-checkpoint guards passed. The recorded
11.433 seconds of fingerprint overhead covers only completed attempts and is a
lower bound because the failed attempt was not timed in that harness revision.
This is a retained preparation failure, not a bridge-on speed measurement.

A [second native attempt](evidence/autoencoder_control_plane_plan/daemon-shared-report-native-20260925-r2.json)
also stopped at the fourth report's 64 MiB wire limit after 69.284 seconds. No
bundle or daemon arm ran. All source and checkpoint guards passed. Its complete
observer time was 15.891 seconds, including the 4.313-second failed attempt.
Repeated long-string interning was insufficient. The first three v2 report
sizes were 42,641,118, 19,588,113 and 45,481,485 bytes. The package's
`logic/autoformal/validator_profile.py` also changed between the independently
stable attempts, so their cross-run sizes are not a controlled codec-only
comparison.

The revised independent fingerprint uses its own explicitly
reported token/string accounting under the existing 256 MiB expanded-graph
budget; this is neither the wire-size limit nor an RSS estimate. It records time
for failed attempts too.

The [single-record wire profile](evidence/autoencoder_control_plane_plan/report-wire-profile-20260925.json)
then measured the rejected v2 report at exactly 73,409,020 bytes. A positional
representation of that same DAG used 63,161,052 bytes: 13.96% smaller and
3,947,812 bytes below the unchanged 64 MiB limit. Parsing and inverting its actual
serialized bytes reproduced the original bytes and SHA exactly. Dictionary
nodes accounted for 90.98% of original wire bytes; dictionary-pair flattening,
reference arrays and node framing explain the reduction. String pooling stayed
the same in this controlled comparison.

That diagnostic generated one record in 14.627 seconds under the original
15-second producer timeout, with all five requested adapters returned. Its
10.932-second codec call includes histogram and candidate/inverse work and is
not a production speed measurement. It preserved the original rejection, wrote
no report payload, and passed input/source/checkpoint guards. The compact format
requires a separately validated production implementation before bundle or
daemon qualification. No new daemon speedup is established.

The [v3 native attempt](evidence/autoencoder_control_plane_plan/daemon-shared-report-native-20260925-r3.json)
successfully prepared all six reports with all five adapters returned and passed
six exact native field/type/order/alias and derived-target roundtrips. Its
16,237,649-byte artifact references 205,507,402 encoded report bytes, with a
largest shard of 63,159,922 bytes. Preparation took 103.983 seconds, including
49.665 seconds of generation and 27.746 seconds of diagnostic fingerprinting.
The separate roundtrip audit took 50.369 seconds. These preparation costs must
be accounted for before claiming an amortized benefit.

The cold daemon then completed and persisted durably. Its post-timer export tied
all six cached reports to the actual optimizer targets, and six further exact
roundtrips passed. However, another process changed
`logic/autoformal/repair_intake.py` during the guarded interval. The final
[producer check](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_target_preparation.py)
raised `target producer code/runtime changed in resident process; start a fresh process`.
The shared arm never ran. This invalidates the native comparison and makes this
artifact unsuitable for a new consumer using the changed producer configuration.
The harness and protected checkpoint stayed unchanged; the guard was not relaxed.

For audit only, the invalidated cold attempt recorded these wall times:

| Scope | Samples | Seconds | Seconds/span |
|---|---:|---:|---:|
| Initial training bridge evaluation | 3 | 29.207 | 9.736 |
| Initial validation bridge evaluation | 3 | 27.806 | 9.269 |
| Final training bridge evaluation | 3 | 2.139 | 0.713 |
| Final validation bridge evaluation | 3 | 2.652 | 0.884 |
| Complete daemon including shutdown | 6 distinct | 94.038 | 15.673 |

Every optimizer evaluation had three legal-IR targets. Training sample memory
was true; validation was false. The compiler caches began empty in a private
working directory. Projection used the CPU `native` backend, one epoch, one
update family, one line-search attempt and a 180-second limit; it accepted zero
epochs and left the complete state identity unchanged. The 61.715-second cold
export and 54.847-second cold roundtrip audit happened after the daemon timer.
These are invalidated observations, not a new baseline or a speed comparison.

A fresh comparison needs a source-stable window of about 12 minutes covering
preparation, both daemon arms and graph audits. Cold/shared full-graph comparison,
shared daemon timing and shared daemon RSS remain unmeasured. Production input,
full-corpus coverage and held-out generalization are not established by this
six-record development fixture.

The subsequent [exact size-accounting change](autoencoder_report_size_accounting.md)
reduces same-artifact median selection from 5.828 to 4.679 seconds and encoding
from 4.623 to 3.498 seconds on one historical report, with exact outputs and all
guards passing in four counterbalanced forensic processes. It passes 396 focused
checks without changing any wire or validation limits. That is a codec result,
not a daemon measurement. The fresh r4 native attempt then stopped in preparation
after `logic/autoformal/repair_context.py` changed. All six reports returned five
bridges, but no bundle was published and no daemon arm ran. The retained failure
does not replace the earlier negative target-only baseline or establish a new
native throughput result.

## Opportunity cost and deployment sequence

Preparation is paid once per compatible report inventory. Every consumer still
pays verified loading and source checks. Frequent producer edits invalidate
reuse. Measure total preparation plus repeated daemon calls, resident memory
and complete acceptance behavior before enabling the option by default.
Full-report DAG sharing addresses graph duplication; it is not Arrow-backed
weights or a new DuckDB writer path.

A later [single-report forensic profile](autoencoder_report_hydration_profile.md)
preserves the normal stale-producer rejection and inspects the historical bytes
only. Exact decoding passes. Repeated scalar JSON-size calculations inside the
expanded-bound arithmetic dominate more than input reading/decompression under
cProfile. That identifies a narrow optimization experiment; it establishes no
native daemon speedup and changes no production validation policy.

The observed tens of megabytes of encoded report data per record also make
storage capacity a deployment gate. Measure bytes per verified source unit,
retained producer/model versions and working partitions before materializing a
corpus-wide report inventory. Use the existing owner leases and bounded artifact
retention to regenerate unneeded report caches; preserve source coverage and
proof evidence independently. Compressed artifact bytes, expanded graphs and
worker RSS are different costs. A smaller wire representation alone does not
establish lower training memory or faster complete cycles.

The remaining integration order is:

1. Supply verified production corpus/vector batches and partitioned report
   inventory through the existing owner/job manifests. Preserve legal/source
   split membership and report explicit gaps; random sampling must not silently
   shrink to cached coverage.
2. Connect complete daemon candidate submission/adoption to the existing DuckDB
   owner and Quack commands. First establish durable full-cycle identity with
   leases/fences and existing acceptance checks. Enable sparse persistence only
   after replay covers every cycle mutation; later TODO/guidance/compaction
   changes are not captured by the projection sink alone. Keep weight reads
   and optimizer loops local. The [production-adoption audit](autoencoder_daemon_production_adoption_audit.md)
   specifies this boundary and the input/snapshot constraints.
3. Evaluate optional mapped Arrow input/feature-weight tables at complete-cycle
   scope. Other weight families still use Python state. Choose concurrency from
   measured worker memory and throughput; current small-batch measurements do
   not justify automatically enabling Arrow or more workers.
4. Materialize durable history through the existing DuckLake outbox and prepare
   reproducible Hugging Face dataset/model releases with source, model, language,
   split, producer and proof provenance. Catalog rows and uploaded artifacts do
   not confer formalization or admission.

The [federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md) and
[control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md) retain
the broader authority, multilingual qualification, recovery and release gates.
