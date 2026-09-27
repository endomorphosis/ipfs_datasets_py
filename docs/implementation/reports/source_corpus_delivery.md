# Source-corpus queue, DuckLake delivery, and offline Hugging Face planning

Isolated local qualification passed on 2026-09-27. The fresh
`source-corpus-delivery-20260926-r3/capture-r3` capture passed all 783 tests, delivered all 62,931
source rows into native DuckLake, verified them after reopening, and planned the complete HF
package offline. Final byte guards passed and the reservation was released. No production service,
model training, live Hub publication, or legal formalization was performed. The
[audit](evidence/autoencoder_control_plane_plan/source-corpus-delivery-audit.json),
[tests](evidence/autoencoder_control_plane_plan/source-corpus-delivery-tests.json), and
[delivery receipt](evidence/autoencoder_control_plane_plan/source-corpus-delivery-delivery.json)
bind this qualification to the captured code and inputs.

This extends the [persistent source catalog](source_corpus_catalog.md) with a durable source-import
queue, an explicit source command profile over the existing Quack transport, native isolated
DuckLake tables, and a complete offline dataset publication plan. The [training control
plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md) and [federal-law
plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md) retain the separate requirements for
training, legal coverage, publication, and admission.

## Source scope and unchanged success rules

The input is the previously verified complete declared U.S. Code corpus package: 62,931 physical
rows, 62,839 unique eligible inputs, 59,511 groups, and 92 alias rows. All 103 package files total
263,671,066 bytes. The frozen source splits are 50,282 training, 6,358 validation, 3,147 canary, and
3,144 holdout rows. Physical embedding dispositions remain 51 embedded, 13 token-limit failures, and
62,867 unattempted. These describe source and producer records, not new model work.

Every source row retains its 33 original typed columns and physical ordinal. Published retrieval
claims inside `record_json` remain historical data; top-level `admitted=false`, `formalized=false`,
and `formalization_status=not_observed` remain explicit. A database row, complete import, native
snapshot, shared target, embedding, compiler output, or dataset plan does not admit a theorem. Only
`lake build <Lib>` is a Lean admit. The Constitution is not formalized, and this delivery does not
compile Constitution spans or mark them `roundtrip_ok`.

## Durable queue and bounded commands

[`SourceCorpusCatalog`](../../../ipfs_datasets_py/duckdb_control/source_corpus_catalog.py) adds
`reserve_registration`, `registration_status`, and `pending_registrations` using the existing
operation table. Reserving an exact dataset/manifest pair persists a pending intent without
resolving its package. The intent survives owner restart. Existing `register_export` performs the
eventual import and resumes its durable batch checkpoints; a receipt remains registration-time
evidence rather than a claim that the package is currently available.

[`SourceCorpusControl`](../../../ipfs_datasets_py/duckdb_control/source_corpus_control.py) accepts
an exact owner-issued scope of dataset/manifest bindings and readable version IDs. Its command
vocabulary is `RegisterSourceExport`, `ResolveSourceExport`, `ReadSourceVersion`, and
`ReadSourceRows`. Callers provide identifiers and descriptors, not filesystem paths, SQL, storage
policies, leases, trainer settings, or completion results. Principal-scoped durable operation IDs
prevent another configured scope from adopting an unrelated pending operation.

The explicit owner method `execute_pending(max_operations=...)` performs heavy package verification
and import outside the gateway pump. Busy owners return a bounded busy result. Each drain makes at
most one attempt per selected intent; failed work remains pending, and lost replies resolve the
durable operation before another explicit attempt. The bounded scan reports when its limit is
reached rather than claiming to have enumerated every pending operation.

[`SourceCorpusQuackGateway`](../../../ipfs_datasets_py/duckdb_control/source_corpus_quack.py) reuses
the existing transient inbox/reply gateway and request-bound wire codec. It requires explicit
prototype opt-in and an exact typed source controller. Only its transient transport database is
served. The source owner database and package files are not attached for arbitrary remote queries.
The existing model and campaign command profiles keep their separate authorization boundaries.

Source reads return at most 64 rows within a 96 KiB complete controller-result budget. This fits
inside the existing 128 KiB wire-reply bound; command envelopes retain their 64 KiB bound. A first
row that cannot fit returns the explicit `source_row_too_large` error. It is not truncated or
silently skipped. The local catalog and immutable package remain the path for complete wide-row
access. Native source-listener qualification and production activation remain pending.

## One verified package binding for two delivery paths

[`SourceCorpusBinding`](../../../ipfs_datasets_py/duckdb_control/source_corpus_binding.py) accepts
the captured version and a current package directory. Entering verifies the complete retained
package and independently recomputes the ordered row digest. It never opens the archived source
database or the historical package path stored in that version. Relocation therefore preserves
content identity.

The binding is local to its creating thread/process and context lifetime. Each `iter_rows()` pass
decodes bounded 64-row Arrow batches, preserves exact ordinals and all fields, and validates the
full digest and file closure on exhaustion. `verify_current()` rehashes the exact namespace before a
consumer's commit boundary. Public metadata is detached; this is neither a persistent cache nor an
authority token. DuckLake and HF planning share this validation path.

## Actual isolated DuckLake storage

[`IsolatedNativeSourceCorpus`](../../../ipfs_datasets_py/ducklake/source_corpus.py) reuses the
existing native history adapter's pinned local extension loader. There is no extension download,
automatic installation, autoload, unsigned extension acceptance, catalog migration, or production
namespace activation. The sink owns a fresh local catalog and `DATA_PATH` behind an exclusive lock,
with process, root, catalog, descriptor, extension, and schema guards.

`materialize_version(operation_id, binding)` streams typed source rows into DuckLake-owned Parquet.
It never transfers the immutable source package into DuckLake's file lifecycle. Native insert
batches are bounded to 4,096 rows and 8 MiB; the source binding still decodes 64-row pages. Larger
bounded inserts avoid requesting one native insert per source page. The capture produced 63
Parquet files; it did not compare alternative batch sizes or establish a file-count speedup.

Rows, release/version metadata, and the exact operation marker commit in one DuckLake transaction.
Native commit metadata binds the request to its snapshot. `lookup` checks marker, version, physical
uniqueness, complete ordered digest, and the unique native snapshot. A repeated operation must
reconcile exactly; a different request with the same operation ID fails. Multiple declared version
labels may share the same immutable physical release.

The r3 sink was configured with a 512 MiB output cap; the API default and permitted maximum remain
1 GiB. Native memory is configured separately at 512 MB. Namespace checks run after insertion
batches and at public boundaries; external resource supervision remains necessary.
Source/sink path overlap is rejected. Bounded native reads enforce ordinal ranges and detect missing
page endpoints; they do not repeat complete-package verification for every page.

## Offline HF plan and remaining publication work

[`plan_source_corpus_release`](../../../ipfs_datasets_py/huggingface/source_corpus_release.py) uses
the same binding and the existing publication profile/planner. It includes every immutable package
file and `source-export.json`, with exact sizes and digests, under a versioned dataset release
prefix. The plan omits private local paths and preserves the captured version without authenticating
its issuer.

The capture destination `example/source-corpus` is a fixture. No Hub client is contacted, no remote
inventory or parent commit is verified, and nothing is uploaded or downloaded. Publisher cost
defaults are illustrative, not a price quote. A root dataset card/configuration and Dataset Viewer
check remain separate work: the physical dataset split is `corpus`; frozen legal-training membership
is the `split` column and must not be regenerated by publication tooling.

## Opportunity cost and measured scope

The existing source database occupies 986,460,160 bytes, and its evidence package adds 263,671,066
bytes. This slice reuses the package and captured version; it does not make another approximately 1
GB source database or open the archived one. Native DuckLake necessarily writes a new managed
representation. Its size, commit overhead, and query time must justify the added storage.

Complete package verification and hashing cost I/O. They protect exact source, split, alias, and
producer bindings; skipping them is not an accepted speedup. HF planning currently enters a fresh
binding, so its verification cost repeats the earlier native source bind. Any future same-operation
reuse needs explicit lifetime and final-byte guards before being measured. Arrow batching here is
bounded materialization, not an end-to-end zero-copy or training-weight claim.

| Captured item | r3 result |
|---|---|
| Tests, failures, errors, skips | 783 / 0 / 0 / 0 |
| Pytest invocation / parent test phase | 261.990060 / 272.835547 seconds |
| Full package and source-row binding | 52.629700 seconds |
| Native materialization and close | 80.550202 seconds |
| Native reopen and complete verification | 24.508549 seconds |
| Independent complete native readback | 20.645744 seconds |
| 246 query calls included within readback | 18.101921 seconds |
| Complete offline HF plan | 52.479586 seconds |
| Delivery child / parent delivery phase | 234.844582 / 240.814480 seconds |
| Native rows / snapshot | 62,931 / 2 |
| Native sink files / bytes | 66 files, including 63 Parquet files / 197,307,549 bytes |
| Source/dependency/protected-byte guards | All passed; 7,787 source and 1,318 dependency files |
| Delivery child lifetime RSS high-water mark | 1,564,368,896 bytes; not phase-only |
| Whole audit / resource release | 594.111322 seconds / released |

The [native commit](evidence/autoencoder_control_plane_plan/source-corpus-delivery-native-commit.json)
and [independent readback](evidence/autoencoder_control_plane_plan/source-corpus-delivery-native-query.json)
agree on the complete ordered digest
`9ba5939bc2eab013dfbcb115b66c351e3d03aa3935ccf43346a7b4d0cab33db3`, every original
field, and the unchanged split and embedding counts. The
[HF plan](evidence/autoencoder_control_plane_plan/source-corpus-delivery-huggingface-plan.json)
contains all 103 files and their exact 263,671,066-byte payload.

The reserved resource bounds were 800,000,000 bytes including a 150,000,000-byte fixture charge, 3,072 MiB
RSS, one CPU slot, and 1,200 seconds. Final owned bytes were 207,106,249 and charged attempt bytes
were 357,106,249. The [release receipt](evidence/autoencoder_control_plane_plan/source-corpus-delivery-release.json)
records released reservation `ca1cb9e2489a4eb282d88e7b83b2d094` and lease
`8e3cc9ec35e0479481ee3a153ff8690f`, with no live owned child processes. Earlier retained claims
remained unchanged. Accounting and polling are cooperative controls, not kernel quotas.

These are single-run storage observations with uncontrolled filesystem cache, one DuckDB thread,
one Arrow CPU thread, and one Arrow I/O thread. Metric disk cache was disabled. No bridge-on
measurement, prover execution, or native model training ran. Query time is already included in
readback time. The results do not establish per-span or bridge-on legal-IR speed, native training
memory improvement, or a before/after storage speedup.

## Captured code and publication boundary

Whole-source, dependency, harness, protected-input, and produced-artifact guards stayed equal
through the completed tests and delivery. The captured context includes eight explicitly excluded
paths: `entity_cache.py`, `supervisor_loop.py`, `meta_ontology.py`, the supervisor launch script,
and their four corresponding test files. Audit hooks and module-path checks proved these eight
paths were neither executed nor imported. Their concurrent feature work is not qualified here.

A further 29 frozen paths differ from the intended publication tree and remain unstaged context.
They were not covered by those eight execution-denial checks; this report does not claim they were
unexecuted. The source snapshots describe the capture environment. The selected reviewed code and
test bytes are qualified by this run; the entire publication candidate tree is not asserted to be
identical to the captured tree.

## Retained failures and next gates

The first delivery capture remains failed: 780 passed and one failed out of 781, with no skips. The
`root_symlink` case correctly rejected the aliased package, but the shared binding leaked
`CampaignPackageError` instead of translating it through its public error contract. The repair
normalizes that existing domain exception without accepting the alias or weakening package
verification. Two additional direct binder regression cases brought the retry count to 783.
The first receipt, source/test revisions, harness, and failed resource claim remain retained; its
full-data delivery phase did not run.

The [first failed audit](evidence/autoencoder_control_plane_plan/source-corpus-delivery-failed-r1-audit.json)
and [tests](evidence/autoencoder_control_plane_plan/source-corpus-delivery-failed-r1-tests.json)
remain failed. The [second audit](evidence/autoencoder_control_plane_plan/source-corpus-delivery-failed-r2-audit.json)
also remains failed: its [783 tests passed](evidence/autoencoder_control_plane_plan/source-corpus-delivery-failed-r2-tests.json)
with zero failures/errors/skips, but a dependency changed during the capture. Its dependency guard
rejected the run before full-data delivery. Both failed claims and receipts remain retained. R3
froze the new meta-ontology module/test as unexecuted context and passed every final guard; no
historical failure was reclassified.

Next, qualify an isolated native source Quack listener under the existing transport policy, then
implement reviewed remote upload/reconciliation, verify pinned downloaded package bytes, and check
Dataset Viewer configuration. Production DuckLake activation still needs its deployment gates.
Native training remains deferred. Held-out quality, official-source authentication, broader
federal-law coverage, Constitution formalization, and Lake admissions remain separate goals.
