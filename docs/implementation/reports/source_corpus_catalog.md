# Persistent owner-managed federal source catalog

Implemented and locally qualified, 2026-09-26. This extends the
[complete declared U.S. Code source export](autoencoder_uscode_corpus_export.md)
into durable DuckDB rows. The final guarded capture passed 432 tests and compared
all 62,931 stored rows after reopening. Native training validation remains deferred.

## Place in the end-to-end pipeline

The source exporter supplies a portable, byte-bound package of all declared
physical rows. The catalog owns a separate copy of that evidence and materializes
its 33 source columns plus an ordering column in a dedicated DuckDB database.
The model registry retains its existing schema and ownership. Corpus imports do
not share the model registry's database or transactions.

Dataset identity includes a namespace, declared source language, jurisdiction
and source profile. A version binds those labels to the exact package manifest.
Different versions coexist without an implicit mutable latest pointer; different
label bindings can share one physical release. A language label does not prove
translation or language detection. Source records remain separate from model
versions and optimizer updates.

One owner holds the catalog's process lock and uses the existing connection
policy for bounded transactions. Inputs are exact local package descriptors;
callers do not submit SQL or mutable table names. Materialized source data stays
in this database. Numeric training weights and shared target buffers remain
local to workers; source import does not put weights behind Quack.

## Durability and validation contract

A new release must pass the existing full package verifier. The owner keeps its
own byte-exact evidence copy without transferring ownership of the original
package. Import batches have deterministic ordinals and durable progress.
Incomplete releases remain invisible to normal reads. The final release record
is committed only after all stored rows have been compared with the verified
package.

Retrying the same operation with the same payload can recover its original
receipt after a lost response. A historical receipt is not a current file
availability assertion. Explicit version verification rechecks the owned
package and materialized rows. Conflicting payloads, foreign schemas, changed
source bytes and incomplete releases must fail rather than silently replace
an existing version.

Public reads paginate by ordinal with explicit row and byte limits. An oversized
row raises an error instead of disappearing from the source inventory. All
aliases, exclusions, split assignments and embedding dispositions retain their
physical membership. Source retrieval labels inside record JSON do not grant
legal admission: exported `admitted` and `formalized` remain false. Only
`lake build <Lib>` is a Lean admit. The Constitution is not formalized.

## Opportunity cost

| Choice | Benefit | Cost |
|---|---|---|
| Dedicated materialized DuckDB catalog | Persistent queries survive loss of the original export path; no filesystem SQL exposed | Additional storage for query rows |
| One owned package per physical release | Retains complete evidence after restart and supports portable delivery | A separate copy of the source package |
| Shared physical release across declared dataset labels | Avoids copying identical corpus rows for every label binding | Requires separate dataset/version and release identities |
| Bounded Arrow import batches | Avoids an SQL parameter for every cell | DuckDB still imports data into its own storage; no end-to-end zero-copy claim |
| Durable batch progress with hidden partial releases | Supports exact resume without exposing an incomplete source dataset | More transactions and progress records |
| Full stored-row verification before publication | Catches missing, reordered or changed materialized data | Additional source and database reads at a release boundary |

Qualification must measure complete import and reopen/verification time, actual
physical rows and bytes, memory observations and thread counts. File-cache state
must be disclosed. These operations are source I/O, not bridge-on evaluations,
held-out model results or legal admits.

## Following integrations

The catalog's exact version and package references can feed a dataset-specific
Quack profile, a durable DuckLake source-table adapter and a sealed Hugging Face
publication plan. Existing generic DuckLake ingestion defaults use hermetic
catalog state; current native history delivery handles model metadata events.
Neither proves corpus-table delivery. A production adapter still needs owned
file copies, transactional release markers and restart/lost-response validation.

Hugging Face delivery must include the complete portable package and manifest,
verify the remote commit, and run the source-package verifier after a pinned
download. No upload or production DuckLake activation is performed by this local
catalog. Official-source authentication, Constitution inventory, native training
qualification and Lake formalization remain separate work.

## Measured source I/O and retained evidence

Both attempts used the same exact 103-file package and all 62,931 physical rows.
The final change adds an upper ordinal bound before the wide row projection.
Three added functional cases verify missing window/end rows and byte-limited
continuation. Every row, frozen split, embedding disposition and ordered digest
remained identical. This is one before/after observation per implementation,
with uncontrolled filesystem cache state; it is not a cold-run or native-training
benchmark.

| Operation | Before range bound (s) | After range bound (s) |
|---|---:|---:|
| Import, owned copy, verification and close | 295.077 | 155.486 |
| Reopen and full verification | 207.027 | 80.539 |
| Independent complete readback and comparison | 83.791 | 21.146 |
| Bounded query calls within that readback | 74.085 | 11.611 |
| Complete CLI invocation, including import and reopen | 503.794 | 237.708 |
| Whole catalog child, including independent readback | 593.306 | 264.436 |

The bounded-query timing is included in independent readback, and the CLI timing
includes import and reopen; overlapping rows must not be summed. Import wall time
per physical source row was 0.004689 seconds
before and 0.002471 seconds after. Whole catalog
child time fell by 55.4% in this observation.
Neither operation compiles spans or evaluates bridges: no bridge names or provers
ran, no legal-IR targets were scored, and there is no new per-span or bridge-on
training speed claim. Metric disk cache was disabled; filesystem cache was
uncontrolled. DuckDB query threads, Arrow CPU threads and Arrow I/O threads were
all one.

The final database is 986,460,160 bytes and its complete
owned package is 263,671,066 bytes.
The child's observed lifetime RSS high-water mark was
997,044,224 bytes.
These observations include local source decoding and do not establish zero-copy
weights or increased training-worker capacity. The database stores wide source
records as well as text; sharing an identical physical release across language
labels avoids duplicating those rows and their package.

The final capture used a 1,500,000,000-byte reservation, a 150,000,000-byte fixture
charge, 3,072 MiB memory, one CPU slot and a 1,200-second deadline under the existing
60,000,000,000-byte campaign cap. It completed in
383.510 seconds and released reservation
`58c8e54dc95c4e38a53f7e15f807e106` with
1,412,262,387 charged bytes. The baseline
reservation `c9639e80fb2f4f36af44e137423a7267` is also released. Both captured
7,781 package sources and 1,304 dependencies with unchanged before/after guards.
Concurrent entity/supervisor edits were pinned as context, explicitly denied
execution, and remain outside this code publication.

The first admitted attempt passed the existing 392 cases but failed all 37 new
catalog cases because the existing SQL policy matched `LOAD ` inside an internal
column declaration. Renaming the columns preserved that policy. Its failed
receipts and reservation `626a02434b7b4c569415731a25d3b9f9` remain retained. A separate
harness typo was caught and stopped before reservation; that setup is preserved
under the first attempt's `pre-admission-aborted` directory.

Portable receipts: [final audit](evidence/autoencoder_control_plane_plan/source-corpus-catalog-audit-20260926-r3.json),
[432 tests](evidence/autoencoder_control_plane_plan/source-corpus-catalog-tests-20260926-r3.json),
[final import](evidence/autoencoder_control_plane_plan/source-corpus-catalog-catalog-20260926-r3.json),
[exact readback](evidence/autoencoder_control_plane_plan/source-corpus-catalog-query-20260926-r3.json),
[baseline audit](evidence/autoencoder_control_plane_plan/source-corpus-catalog-audit-20260926-r2.json),
[baseline import](evidence/autoencoder_control_plane_plan/source-corpus-catalog-catalog-20260926-r2.json),
and [retained failure](evidence/autoencoder_control_plane_plan/source-corpus-catalog-audit-20260926-r1.json).
Large database/package payloads remain local in
`workspace/test-logs/federal-corpus-audits/source-corpus-catalog-20260926-r3/capture-r3/catalog/`.
No database or model checkpoint is staged in Git.
