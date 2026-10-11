# US Code span processing: reused census and bounded archive reconciliation

The new archived-target path reuses the original source, queue and all **18,342**
saved census occurrences, then resumes within a source section in a fresh CLI
execution. The bounded result accounts for **24,191 observed occurrences**, with
**2,806 exact archived target joins** and **21,385 outside-target observations**.
The source scan and archive reconciliation remain incomplete. No native
autoencoder pilot, model training, semantic reconstruction or formal proof ran.

This advances the [comprehensive processing plan](https://github.com/endomorphosis/lift_coding/blob/4bad33cb1d1f63d3f3011c96f1e19f186163dd24/implementation_plan/docs/68-uscode-all-span-processing-plan-2026-10-07.md)
and preserves the [published October 7 intake findings](https://github.com/endomorphosis/lift_coding/blob/c7a9e8d6725a110f6bd3b299acbb3ab434870fce/implementation_plan/docs/69-uscode-span-intake-progress-2026-10-07.md).

## Measured scope and reuse

The archive remains `justicedao/uscode-autoformal-span-cache` at
`765176c6db79ba65c1697c21dead43666350b730`: **443,904 distinct archived span IDs**
and one metadata row. Source bytes remain the existing
`justicedao/ipfs_uscode@5016b86a273ce5e4ffd066c5ae9f5fe494dd417e` Parquet.
The new manifest pins both exact artifact hashes, the original extraction code,
the new pager/controller, paging bounds and the immutable old seed snapshot.
The source has 60,077 physical Parquet records. Archived IDs and full regenerated
source occurrences are different denominators; the complete source-occurrence
count is not established by this window.

| Accounting | Original reused seed | Seed plus first page | After fresh CLI resume |
| --- | ---: | ---: | ---: |
| Observed source occurrences | 18,342 | 18,406 | 24,191 |
| Exact archived ID + hash + legal-ID joins | 2,165 | 2,172 | 2,806 |
| Outside-target observations | 16,177 | 16,234 | 21,385 |
| Archived IDs awaiting source scanning | 441,739 | 441,732 | 441,098 |
| First uncommitted section/span cursor | 128:0 | 128:64 | 199:64 |

The **5,849 additional occurrences**, including **641 new exact archived joins**
and **5,208 additional outside-target observations**, came from 129 new committed pages: one page
after seed verification and 128 pages after fresh CLI execution. Section and span
offsets are zero-based. Cursor `199:64` leaves the remainder of section 199 pending.
The frozen result has no WAL and `complete_source_scan=false`.

This is explicitly an **archived-target inventory**. Every physical candidate
whose ID occurs in an archived span row is retained, including conflicts and
invalid/hash/citation-mismatched bindings. Other candidates receive durable
aggregate counts, length cohorts, ordered digests and bounded identity-only
examples. Their complete identities are not stored; this result is therefore
not a complete all-source occurrence inventory. Outside-target observations are
not automatically new text, duplicates or missing work. Historical extraction
hashes normalized sentence bytes; original legal-section bytes remain available
in the pinned artifact.

## Durable execution and measurement

The additive pager/controller preserves the original groups of 64 valid source
documents. It commits target rows, aggregate accounting, digests and the
section/span cursor together. Seed reuse authenticates the stopped old database,
manifest and report, reconstructs every saved occurrence against the source, and
imports the verified prefix atomically. It does not rewrite the old census.
Real-CID blank-text citation fallbacks retain historical ordinals but have
explicit nonstatutory provenance; null-CID metadata consumes no document ordinal.

The real attempt used pages of at most **64 spans / 4,194,304 serialized bytes**,
an 8,388,608-byte complete-section bound and one CPU slot. Its output cap was
240,000,000 bytes within a **256,000,000-byte reservation**. Final retained
attempt storage was **4,009,757 bytes at the guardian's finalization inventory**.
The later final-resource receipt and post-finalization lease observation brought
the independently measured stopped-directory total to **4,014,922 bytes**. The owned process group stopped, the
resource claim and scheduler lease were released, and no foreign claim was
released by this work.

Linux `getrusage(RUSAGE_SELF)` reported **844,372 KiB = 864,636,928 bytes** maximum
RSS. This is the process-lifetime high-water mark across the seeded and fresh
execution, not an isolated stage or process-group peak. The outer admission was
**1,536 MiB**; the **768 MB DuckDB setting** limits DuckDB-managed memory and is
not a cap on the entire Python/Arrow phase. Admission and sampled enforcement
remain cooperative rather than a kernel quota. This bounded window does not
establish full-corpus storage, memory or runtime fit.

The owner regression suite passed **78 controls**, followed by **19 final
controller controls** after report-flag closure. Integrated acceptance also passed
**375 intake controls and 70 Source384 source-binding controls**. Controls cover within-section
restart, rollback, exact seed bindings, seed cursor/completion tampering,
unchanged old files, duplicate physical occurrences, conflicts and bounded
refusal. Independent review passed **28 checks with zero findings**. A separately
paged replay rebuilt all 24,191 descriptors and both ordered digests, compared
every old census row and every retained target, and verified seed/first-page/final
accounting. It also verified stopped processes, released owned resources and the
unchanged foreign ledger. Cold resume used `os.execv` into a fresh Python
interpreter, retaining the same OS PID/birth; no second OS process was claimed.

The current datasets integration preserves the concurrent published Unicode
source-binding fix `5d5769f0` through merge `25c8687`. All seven runtime-owner file
hashes still match the actual run's `56f4a65` implementation after that merge.
Publishing this contribution must retain that history and the original assets.

Frozen operator evidence resides in
`external/ipfs_datasets/workspace/test-logs/uscode-span-continuation-20261011/archived-reconciliation-01/`:
`results/manifest.json`, `results/seed-and-first-page-report.json`,
`results/report.json`, `command.json`, `child-exit.json`, `resources-final.json`
and lease observations. The controller source is separately versioned
`uscode-archived-target-reconciliation/v1`; reports explicitly set
`semantic_reconstruction_measured=false` and `proof_authority=false`.

## Model and routing invariants

Existing source assets, embeddings, decoder weights and releases remain intact.
The research survey rehashed ten checkpoint files and eight cache/preprocess/donor
assets against their earlier receipts. This run changed no ModelManager or Hub
model registration. The routing plan keeps LegalIR, CodebaseIR, SecurityIR and
IntentIR in separate inventories/catalogs and model repository identities, each
with parallel **8D, 384D and 768D** paths. This is a namespace requirement, not a
claim that all twelve cells have qualified trained models.
Reuse requires matching family, dimension role, encoder revision, input/context
hash, schema/version, decoder task, codec/profile and checkpoint hashes.
Semantic IR, legal-text reconstruction and formal-logic projection heads stay
separately attributable. Legal spans primarily enter LegalIR; the other families
require their own source and target contracts.

The retained native 768D multilingual producer still uses a **512-token ceiling**.
The base model's **8,192-token capacity** does not establish long-context decoder
coverage or larger output geometry. The earlier 768D dual-donor initialization
already copied **26 learned decoder tensors (27,142 parameters)** from the
original 8D/384D donors, with zero optimizer updates in that preparation
generation. Reuse that authenticated initialization and its separate native
interface boundaries. Reference-supervised interface fitting and teacher-output
distillation are different experiments. Teacher-output qualification remains
outstanding: authenticate genuinely aligned embeddings and learned outputs,
separate previously exposed data from confirmation, and gate promotion on
source-only fidelity plus retained behavior. Legacy mock 8D
vectors and compiler-conditioned observations cannot become learned teachers.

## Next stages and acceptance gates

| Stage | Concrete work and acceptance |
| --- | --- |
| Review and integrate | 375 intake and 70 Source384 controls, plus 28 independent actual-result checks, pass. Publish source and compact evidence into current main while preserving concurrent Unicode source-binding history and frozen native-model source trees. Verify published files at immutable commits and the root datasets gitlink. |
| Complete archived reconciliation | Authenticate the stopped current generation, then clone it into a fresh owned attempt and continue from `199:64` under unchanged source/code/seed/paging pins. Preserve frozen results; each phase's sole writer and copied storage must be charged to its own admission. Reauthenticate inputs and resource state each time. Every archived row must obtain an exact source mapping or an explicit final unresolved disposition; publish counts independently of model success. |
| Full-source inventory | Select and qualify immutable bounded occurrence shards if a complete outside-target identity inventory is required. Preserve physical occurrences and historical aliases; aggregate-only archive reconciliation cannot substitute for that deliverable. Measure varied sections before proposing a full-run resource reservation. |
| Historical evidence joins | Validate bounded paired-v1/v2 and modal table bodies against canonical source bindings. Preserve compiler origins, guidance conditioning, duplicates, failures and mock-vector status; descriptor closure alone is insufficient. |
| Native asset routing and pilot | Extend cache reading to eligible bounded batches while preserving existing replay controls. Require representable task/schema/output-codec/span geometry before inference: the original 32-value, eight-clause, 512-output-token Legal decoders do not establish general statutory coverage. Measure real tokenizer lengths and input/output limits, then run source-only 8/128/1,024-span pilots using authenticated compatible checkpoints. Keep unsupported, missing-cache, context-needed and overflow dispositions visible. |
| Qualified learning and proof indexing | Define representable targets and leakage/exposure groups before new fits. Reuse the existing 768D dual-donor initialization, fit its native interface under separately declared reference supervision when qualified, and add teacher-output distillation only after aligned learned teacher pairs pass qualification. Retain per-family/schema/task checkpoints and require fresh confirmation before promotion. Reviewed logic and proof entries bind source/context/model/compiler/checker dependencies and actual checker receipts. |

An individual candidate or section that exceeds its configured bound is refused
without advancing its cursor. It remains pending until a reviewed larger profile
or streaming interface is available. Technical retries are bounded, source
conflicts remain explicit, and STOP/restart preserves committed work while
terminating only owned process groups. Changed source/code/model/task pins create
new generations rather than silently reusing an old `sealed` status.

Exact legal-text bytes, semantic IR equality, reviewed legal meaning and formal
proof success remain separate measurements. Lossless source custody supports
the requested `legal text -> LegalIR -> legal text` evaluation, but source copying,
IR transport and successful compilation do not measure learned reconstruction.
The byte-exact task must retain original raw UTF-8, source offsets and any declared
residual side channel needed to restore normalized-away formatting. Record whether
reconstruction uses a learned text head, a residual route or source retrieval;
score those routes separately. Historical normalized sentence hashes cannot stand
in for byte-roundtrip originals.
Keep a lossless source-reference/raw-span-offset or residual/source-anchor head
separate from the learned semantic IR and learned text heads, with its own decoder
task/checkpoint attribution. This preserves original bytes while allowing each
learned reconstruction task to be evaluated honestly.

Compact reproducible evidence is indexed in `index.json` in the campaign artifact
package; the complete stopped source database stays local and is bound by the
independent review hash. No source Parquet, embedding cache or model weights are
duplicated in the source-code evidence package.
