# Source campaign training jobs

Implementation report, 2026-09-26. Explicit
`autoencoder-training-job-v8` jobs connect the
[immutable produced-record projection](autoencoder_produced_record_projection.md)
to the existing worker, owner coordinator and offline daemon input handoff.
Successive bounded batches can share one registered model variant while keeping
their exact source assignments and original producer receipts. The full declared
source population remains in the campaign metadata, including exclusions and
unattempted inputs.

Validation status: **441 offline checks passed on their captured source snapshot;
combined same-source qualification is not established**. The test capture kept
all 7,759 package Python hashes and protected checkpoints unchanged. Three
external supervisor modules changed afterwards, and the guard rejected reuse
of that capture as a current-tree qualification. The corrected six-record artifact handoff and 48 archived job identities passed
in an independent capture. Its outer resource audit did not complete because
another pytest directory disappeared during the final named-root scan. Native training and inference validation remain
deferred. A later [prepared-input capture](autoencoder_prepared_campaign_inputs.md)
now provides a successful same-source offline qualification with 605 tests and
the archived six-record handoff. It does not rewrite the failed historical
aggregate described here or provide native training qualification.

The implementation is in
[`autoencoder_training_worker.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py),
[`autoencoder_campaign_job_inputs.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_job_inputs.py),
[`autoencoder_training_coordinator.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py)
and
[`autoencoder_daemon_corpus_inputs.py`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_corpus_inputs.py).
The [control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md)
and [federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md) retain
the broader training, publication and semantic coverage work.

The registered variant has one `source_campaign_binding`, containing exactly
three `{sha256, bytes}` descriptors:

| Shared variant root | Meaning |
|---|---|
| `source_inventory` | Complete declared physical source rows, dispositions and input identities |
| `source_partitions` | Frozen source groups and training, validation, canary and holdout assignments |
| `embedding_receipt_set` | Selected producer receipts and exhaustive attempted/unattempted accounting |

The root binding is immutable. Each job supplies exact descriptors for these
same roots, plus its own `produced_record_projection_artifact`, existing corpus
manifest, selected original `embedding_receipt_artifacts` and selected source
artifacts. Batch projections are not part of the shared variant binding.
Different batches may therefore use different successful producer leaves without
creating a new model variant per shard or rebuilding partitions from successful
embeddings. A corpus record continues to name its original producer leaf SHA;
the receipt-set SHA never replaces leaf provenance.

Adding or replacing a selected producer receipt changes the campaign root.
The caller must preseal the needed campaign or create an explicit campaign
revision. This change does not silently update a registered root. Independent
training attempts still receive separate run identities and output directories;
they do not concurrently mutate one weight dictionary or merge sparse patches
from unrelated parents.

The v8 schema requires all five new job fields: the three shared roots, the
produced-record projection and the selected receipt array. It also requires the
existing manifest, sources and explicit nonempty validation samples. Bounds
remain separate for campaign metadata and selected batch work:

| Scope | Maximum |
|---|---:|
| Each inventory, partition or receipt-set metadata root | 64 MiB |
| Produced-record projection | 4 MiB |
| Projected records | 256 |
| Selected producer receipt count | 256 |
| Selected producer receipt bytes, aggregate | 64 MiB |
| Selected source bytes, aggregate | 64 MiB |

Existing artifact and manifest validators apply their own lower limits where
applicable. Descriptors must match the projection's exact deduplicated closure;
missing, extra, duplicate or mismatched source/receipt references reject. An
unrelated producer leaf or source does not need to be staged merely because the
complete campaign references it.

Before selected artifact I/O, the worker loads the exact inventory, source
partitions, receipt set and projection. Projection construction authorizes both
ordered roles against the frozen source assignments. Training records must be
training members; validation records must be validation members. The manifest,
record summaries, dataset/split snapshots and explicit job sample order must
also match. Canary and holdout entries cannot enter this training projection.
Only after the complete metadata preflight succeeds does the worker read the
selected producer leaves and source files and compare exact records, vectors,
selectors and original provenance.

Owner staging follows the same order: verify the staged metadata, preflight
all roles, then verify the selected CAS files. The owner independently recomputes
the campaign verification and requires the worker completion receipt to match
its exact job fields and verification result. A successful integrity check does
not authenticate source authority, native embedding computation or held-out
generalization. The owner summary keeps promotion, held-out canary qualification
and admission false.

The existing `autoencoder-daemon-corpus-inputs-v1` wrapper can carry a v8 job.
Export uses the existing owner registration and immutable CAS path contract;
the offline consumer does not open the owner database or acquire a training
lease. It checks the exact job and variant binding, authorizes through worker
verification before reading selected source/leaf bytes, and retains boundary
guards for the wrapper, job, manifest, roots, projection and selected closure.
Persistent content changes and pathname replacement reject. These checks do
not constitute a filesystem transaction against a writer that changes and
restores bytes between observations.

V8 daemon summaries explicitly say
`job_schema_version="autoencoder-training-job-v8"` and
`embedding_input_storage="python_list"`. Checkpoint provenance has separate
campaign root, projection, manifest, receipt-array and source-array fields.
It cross-checks these descriptors with verified summaries and rejects legacy
single-production/index fields, Arrow input claims, mismatched descriptors,
unverified sessions and inflated authority/admission flags. Summary counters do
not enter the deterministic checkpoint provenance. The handoff remains a trusted
local descriptor, not an authenticated remote issuer or checkpoint promotion
authority.

Input vectors currently remain ordinary Python lists. V7's Arrow input format
binds one producer receipt and is deliberately not reused for a campaign with
multiple leaves. A future input format must explicitly bind the projection,
manifest and ordered record identities. Optional existing Arrow feature weights
are independent of input-vector storage: v8 can carry the existing weight
artifact and copy-on-write path without changing their contract. Existing
complete shared target snapshots and accepted sparse candidate storage also
remain available under their existing checks. This integration adds no new
whole-training zero-copy claim, native backend switch or qualification for their
combined use on a checkpoint.

No new SQL table or registry migration is needed for the campaign binding.
The existing generic variant manifest, run specification, input snapshot and
content-addressed artifact infrastructure carry it. Workers do not acquire a
DuckDB writer merely to read weights or selected inputs. This implementation
does not activate a live Quack listener, production DuckLake sink or Hugging Face
upload. The model publication package still needs an explicit transitive corpus
and campaign artifact closure before it can claim to publish these inputs.

Legacy serialization and persistence contract tests passed in the offline
capture. The separate archived-job probe verified exact canonical bytes and
SHA-256 identities for 48 jobs: v1–v7 counts are 8, 13, 14, 4, 2, 2 and 5. Old schemas
reject the new campaign fields, including explicit nulls. V8 rejects old index,
selection, single-production and Arrow input fields instead of manufacturing
legacy equivalents. Campaign-bound variants reject a legacy job downgrade.
The existing registry can represent separate model/language variants, but this
worker branch still accepts only corpus mode with the qualified English U.S.
Code frontend and the existing pinned 384-dimensional producer profile. It does
not qualify another language or the Constitution frontend.

There is a measurable preparation-cost opportunity, separate from training.
The preceding projection artifact probe spent **7.207382 seconds** loading and
revalidating the inventory, partitions and receipt set in three timed phases
(1.174363, 2.886917 and 3.146102 seconds). These are historical setup measurements, not the current v8 timings. Its fresh six-record batch
verification took 0.114167 seconds only after those roots were loaded. The
earlier run used one worker, one reserved CPU slot and uncontrolled OS page-cache
state; it was not claimed cold.

The captured integration preflighted roots for staged-artifact authorization
and loaded them again for full input verification. The
[prepared-input follow-up](autoencoder_prepared_campaign_inputs.md) now removes
that duplicate top-level decode within one owner operation, using a private
one-use context bound to the exact job and fresh metadata hashes at both ends.
A worker still verifies its own inputs, and daemon export still opens an
independently verified consumer. Nested codec revalidation remains unchanged;
there is no cross-job cache. Preparation costs must remain separate from
training, target hydration and serialization when deciding the next change.

| Captured campaign-integration evidence | Status |
|---|---|
| Test totals and regression receipt | 441 passed, zero failures/errors/skips; 106.913 s process wall time |
| Source/protected-checkpoint guard during tests | Passed; 7,759 package Python sources unchanged |
| Combined current-source qualification | Not established after three external supervisor edits |
| Archived artifact probe | Passed separately: three training and three validation records, one original receipt, isolated DuckDB staging/export/consumer |
| Archived job compatibility | 48 exact canonical identities across v1–v7 passed |
| Resource audit closeout | Unsuccessful final named-root scan; failed reservation retained, no release claimed |
| Native checkpoint comparison | Deferred by user |
| Training speedup or held-out gain | Not established |

The [component status receipt](evidence/autoencoder_control_plane_plan/campaign-jobs-component-status-20260926-r7.json)
records **`passed: false` for combined qualification**, with successful component
checks recorded separately. The [test capture](../../../workspace/test-logs/federal-corpus-audits/campaign-jobs-20260926/probe-r4/tests/campaign-jobs-tests-r1-receipt.json)
and [artifact probe](../../../workspace/test-logs/federal-corpus-audits/campaign-jobs-20260926/probe-r7/probe/campaign-report.json)
have different complete-package snapshots. The intervening edits were in
`logic/autoformal/supervisor_loop.py`, `supervisor_router.py` and
`supervisor_todo.py`; they were not changed by this integration. At status
recording, the probe package snapshot, test/helper files, archived input bytes
and protected checkpoints all still matched their recorded identities.

| Independent artifact-probe phase | Wall seconds |
|---|---:|
| Verify 48 archived job identities | 0.256113 |
| Decode exact six-record manifest | 0.008297 |
| Stage campaign and selected artifacts | 0.147619 |
| Worker input verification only | 7.627995 |
| Owner export, including consumer verification | 22.916466 |
| Open offline consumer after registry closes | 7.910115 |
| Derive checkpoint provenance | 0.000071 |

These are preparation phases, not per-span inference or bridge-on evaluation
times; no such measurement ran. The probe used one worker, bridge names run
`[]`, prover flag false and metric disk cache `0`. OS page-cache state was
uncontrolled, so this is not a cold-run claim. The registry used an explicit
opaque fixture base descriptor; no checkpoint loader, embedding runtime or
trainer ran. The source/vector artifacts were reused from the archived receipt.
The 250 MB artifact-attempt budget and 2,048 MiB memory bound were unchanged;
its failed final scan retains the reservation rather than declaring successful
resource closure. No new model quality or training throughput is established.

The first efficiency follow-up is now implemented and documented in the
[prepared-input report](autoencoder_prepared_campaign_inputs.md). Its capture-r1
passed 605 offline regressions with unchanged package/test/checkpoint guards
during the tests, then failed the artifact probe's final whole-package guard
after a concurrent `supervisor_loop.py` edit. Those logged A/B/B/A timing
observations remain unqualified. Fresh bounded capture-r2 now passed all 605
tests and the artifact probe on one unchanged 7,759-file package snapshot,
with protected checkpoints unchanged and explicit resource release. The
current-validator recomputation control versus actual owner reuse measured
median preparation of 15.518037 versus 7.864813 seconds, saving 7.653224 seconds
(1.973097×, approximately 49.3% lower wall time) with exact result equality.
There were only two observations per path; this is not training throughput or
a historical native benchmark. The
resource scanner also now tolerates confirmed deletion of previously discovered
descendants only in the shared nonstrict census. Strict owned-attempt checks,
named-root identities, type/permission guards, quotas and retained claims remain
enforced. Neither follow-up retroactively changes the failed combined result
above. Any further caching decision needs qualified phase and memory evidence;
the earlier probe's RSS samples above 500 MiB are a reason to measure retained
memory, not evidence that a larger cache is required.

The initial combined captures were retained as unsuccessful evidence. The first stopped
on pytest-created temporary symlinks inside the strict artifact directory; the
next two stopped on the explicit fixture-storage limit. The audit launcher was
also corrected to guard its entry point for multiprocessing spawn. The final
selection keeps every new v8 test and targets legacy persistence, sparse replay,
serialization, daemon and process-isolation contracts. It does not claim a pass
for the larger interrupted selections. Later artifact probes exposed two harness-only API mistakes: supplying a path
in a registry descriptor, and passing tagged manifest vector values directly
as job numbers. The corrected probe uses exact registry references and the
existing manifest decoder. No production verifier or resource limit
was weakened, and failed-attempt storage reservations remain recorded.

The new tests use explicit synthetic producer vectors and declarations to
exercise schema, owner, worker and daemon contracts. They are not native
embedding evidence. Test coverage is designed to include multiple original
leaves, successive batches under one variant, exact completion/provenance
bindings, role authorization before selected I/O, restart/idempotence, malformed
closures, corruption and legacy downgrade rejection. The component receipts establish only those contracts and the exact scopes
above; they do not repair the incomplete combined qualification.

The source campaign preserves the preceding published-corpus denominator; it
does not authenticate an official source release or establish complete federal
law coverage. Semantic support, independently held-out quality and actual Lake
proofs remain separate work. The Constitution remains unformalized and no span
may receive `roundtrip_ok`. Only `lake build <Lib>` supplies the required Lean
admission. No Mathlib import, weight download, temperature change or context
increase is part of this integration.
