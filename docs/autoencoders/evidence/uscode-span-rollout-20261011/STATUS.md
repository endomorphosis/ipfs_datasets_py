# US Code processing status and remaining gates

Phase 04 stopped successfully and is independently accepted with **complete source
exhaustion**, with **3,840,988 cumulative source occurrences**, **64,969 exact
archived target joins** and **3,776,019 outside-target aggregate occurrences** at
**60077:0**. Its result review passed **22 checks with zero findings**. Archive-ID
mapping recovery, all-source identity coverage and model/reconstruction/proof
gates remain open. This document uses stopped metadata and does not inspect a
changing database. Phase 03 remains independently accepted with 22 checks and
zero findings.

The frozen [phase 02 milestone](PROGRESS.md) and its
[22-check result review](review/rollout-results-review.json) remain unchanged.
The [phase 03 result review](review/window-03-results-review.json) extends that
authenticated prefix without replacing its evidence.
The accepted [phase 04 result review](review/window-04-results-review.json) and
[stopped metadata snapshot](measured-run/phase-04/snapshot-receipt.json) preserve
the final bounded source window separately from its parents.
The [campaign summary](campaign-summary.json) consolidates these accepted
windows without summing their inherited prefixes.
They extend the [original all-span plan](https://github.com/endomorphosis/lift_coding/blob/4bad33cb1d1f63d3f3011c96f1e19f186163dd24/implementation_plan/docs/68-uscode-all-span-processing-plan-2026-10-07.md)
and the [first archived continuation](../uscode-span-continuation-20261011/PROGRESS.md).

## Source-window ledger

Each child starts from a byte-identical authenticated copy of its stopped parent.
Cumulative snapshots include inherited work and must not be summed. New-window
counts are the child's final accounting minus the verified parent accounting.

| Window | State | Cumulative source / targets / outside | New source / targets / outside | First uncommitted cursor |
| --- | --- | --- | --- | --- |
| October 7 seed | Preserved verified source census | 18,342 / 2,165 / 16,177 | Seed prefix | 128:0 |
| October 11 phase 01 | Frozen reviewed parent | 24,191 / 2,806 / 21,385 | 5,849 / 641 / 5,208 | 199:64 |
| October 11 phase 02 | Frozen; 22 review checks passed, zero findings | 209,740 / 24,110 / 185,630 | 185,549 / 21,304 / 164,245 | 2308:0 |
| October 11 phase 03 | Frozen; 22 review checks passed, zero findings | 1,460,896 / 60,025 / 1,400,871 | 1,251,156 / 35,915 / 1,215,241 | 24675:0 |
| October 11 phase 04 | Frozen; 22 review checks passed, zero findings | 3,840,988 / 64,969 / 3,776,019 | 2,380,092 / 4,944 / 2,375,148 | 60077:0; source exhausted |

The same pinned generation reconciles 443,904 distinct archived span IDs plus
one metadata row against the original US Code Parquet. The accepted phase 04
report leaves **378,935 archived IDs unresolved against this source generation**,
with one metadata row excluded and no IDs still labelled pending source scan.
Persisted matched physical occurrences and distinct matched archived IDs both
number 64,969 in this stopped snapshot;
these remain separate measures. Its ordered all-occurrence digest is
`3daf669ace67a6bd738ee967d6e00a96b9ac5492331e327962cc9bbc8ce566c1`;
the outside-target digest is
`7a03602a59f66303291eba4237f26195b3a898d9acca8889d21eafff812cf541`.
These digests bind canonical occurrence descriptors, including archive join
dispositions, within the pinned source/archive generation. They are not
archive-independent raw-source digests.

Archived-target occurrences are persisted individually. Outside-target sources
receive durable counts, length cohorts, ordered digests and bounded examples,
without a complete outside-target identity inventory. They are not automatically
missing gold or unprocessed work. Source exhaustion on this path leaves
complete all-source identity coverage as a separate deliverable. The stopped
phase 04 report sets `complete_source_scan=True` and
`complete_all_source_occurrence_inventory=False`. It accounts for all 60,077
physical source records, including nine empty/null-CID metadata sections; all
3,840,988 emitted occurrences have normalized-source provenance.

The observed full-generator total is **1,654 fewer** than the historical
conditional 3,842,642-span figure. No cause is assigned from this difference.
The older inferred 3,398,738 unexported-span figure is not the measured current
outside-target count of 3,776,019; their assumptions and denominators must not be
substituted. **Archive-ID recovery is the next source priority**, using
authenticated producer/context/release/
normalization/counter recipes and explicitly reviewed aliases. Unresolved IDs
are not automatically absent legal text or training-ready examples.

The [bounded identity forensics](review/identity-recovery-forensics.json),
SHA-256 `a7b82bc7a2efa6340bf6bc229b0d73c14a13bf2b2450a1c180902493fc62571d`,
found **no unresolved archived rows matching recorded source SHA-256 plus legal
ID in the preserved 18,342-row seed prefix**. It found no matched pairs or
evidence of mismatched identity bindings in that prefix; it created no aliases.
This does not establish an extraction-recipe mismatch, absence from the full
source, or a cause for the 1,654-count difference. Original source bytes were
not rescanned by that forensic comparison.

The original archive has no Arrow key/value metadata or explicit extraction
recipe/schema/model/encoder/context fields. Its metadata names the same source
blob path and records 60,068 documents, 22,379 sealed rows, 421,525 gap rows and
3,820,263 pending source spans. Sealed plus pending explains the historical
3,842,642 arithmetic, not its difference from the completed generator. Only
sealed rows carry an opaque code-identity digest; gaps have no code identity.
These old status counts establish neither original embedding applicability nor
formalization/proof authority. Recovery must first locate authenticated original
recipe/context evidence from preserved artifacts before proposing aliases.

## Bounded continuation and resource evidence

Phase 03 reused the unchanged execution tree at
`f0cf880ce5998b20f389874fea1eaddef64490df`, the phase 02 parent, original inputs,
seed and 64-span / 4 MiB paging profile. Its
[run plan](run-plan-03.json), [readiness](review/window-03-readiness.json) and
[review preparation](review/window-03-review-preparation.json) specify at most
**32,768 new pages**, a **2,097,152-candidate ceiling** and **1,500 seconds**.
Admission requested **1,536 MiB outer memory**, **768 MB DuckDB memory**,
**256,000,000 storage bytes**, a **240,000,000-byte controller output cap**, a
**128 MiB clone cap**, and one CPU/child slot, with no model or GPU work.

Phase 02 measured a **7,602,176-byte database increment** to a final
**11,546,624-byte database**. Guardian finalization inventoried **11,706,588
attempt bytes**; its later resources receipt and post-finalization bytes brought
the stopped attempt to **11,711,756 bytes**. Its separate child process measured
**754,864,128 bytes** kernel process-lifetime maximum RSS. The guardian's
**129.275 seconds** include admission and usage overhead; they do not measure
pure scanner throughput. DuckDB's setting is not a whole-process memory cap.

Phase 03 completed its bounded 32,768-page window with a final database of
**27,275,264 bytes**, adding **15,728,640 bytes** to the parent database.
Controller `output_bytes_before_report=27,293,234` excludes the final controller
report and guardian files. Guardian finalization inventoried **28,096,752 attempt
bytes**; the 4,387-byte resources receipt and 776 post-finalization bytes bring
the stopped attempt to **28,101,915 bytes**. The new child measured **773,428 KiB
= 791,990,272 bytes** process-lifetime self maximum RSS. Guardian child elapsed
time was **757.115 seconds**, including guardian overhead; independent result
review elapsed **256.542 seconds**. Neither is an isolated scanner benchmark.

Independent review preserved all 24,110 parent target rows, compared all 35,915
new targets, and rebuilt every one of the 1,251,156 new source observations with
a different 37-span page limit. It reproduced both cumulative digests through
24675:0, verified no WAL, authenticated original source/queue/seed and frozen
parent, and confirmed the child group stopped with its own resources released.
The accepted receipt SHA-256 is
`836b2896bd6c6c847841eb33f42d1ce630ca7085c411664eaca79e53d8aa29fe`.
Through phase 03, cumulative observations have normalized-source provenance; this
does not establish raw-byte reconstruction. Maximum observed normalized-span
length is 13,360 UTF-8 bytes / 13,316 Unicode characters. No tokenizer, numerical
model, semantic reconstruction or proof result was measured.

The phase 03 stopped guardian census reported **1,682,086,821 bytes headroom** under
the unchanged **145,000,000,000-byte global cap**. Fresh admission remains
required; this snapshot does not reserve future capacity. At observed phase 02
density, the pre-run phase 03 growth estimate was roughly 61–86 MB. The all-target-density
estimate was roughly 748 MB, above the admitted output cap. These estimates did
not establish whole-window or whole-corpus fit; the actual phase 03 increment
was 15.7 MB. Duplicate physical target occurrences are not bounded by distinct
archive IDs. New source-mapping or identity-inventory work needs a separately
bounded plan, reviewed readiness and fresh admission.

The launched [phase 04 plan](run-plan-04.json) specifies a fresh authenticated
clone of phase 03 with at most **65,536 new pages**, a **4,194,304-candidate ceiling**
and **1,800 seconds**, keeping the same source/code/profile and per-attempt
memory/storage/clone limits. At its starting cursor, 35,402 physical source records
remained; the plan did not promise source exhaustion. Its roughly
31–53 MB observed-density growth range and 1,514.23-second extrapolation are
planning estimates, not measured outcomes or scanner throughput. The
[phase 04 readiness receipt](review/window-04-readiness.json), SHA-256
`37e62d1566ba38ba72ab14417d1e660fd4429c2a0153d4098ed8b4e512133ab6`,
validated the stopped parent, original inputs and producer pins. The published
child identity confirmed launch. The prepared
[independent phase 04 review](review/window-04-review-preparation.json) ran after
successful stopped guardian notification and returned acceptance.

Phase 04's independently reviewed metadata reports a **30,158,848-byte final database**,
adding **2,883,584 bytes** to phase 03. Controller
`output_bytes_before_report=30,176,879` excludes its final report and guardian
files. Guardian finalization inventoried **31,579,468 attempt bytes**; the later
4,388-byte resources receipt and 776 post-finalization bytes bring the stopped
attempt to **31,584,632 bytes**. Its new child reports **824,544 KiB = 844,333,056
bytes** process-lifetime self maximum RSS and **1,321.911 seconds** guardian child
elapsed time, including guardian overhead. The reviewed cleanup receipt reports
return code zero, no surviving group processes and its own reservation released.
Independent review preserved all **60,025 parent target rows**, compared all
**4,944 new targets**, and rebuilt the **2,380,092 new source occurrences** using
a different 37-span page limit. Both ordered cumulative digests and the exhausted
cursor matched. Custody, no-WAL state and resource cleanup checks passed; review
elapsed **495.733 seconds**, which is separate from scanner and guardian runtime.
The accepted phase 04 review SHA-256 is
`79c0c03f839c5bf1a545d9b9e13b1892648058fc3911868443f366e660a50287`.

The phase 04 final guardian census records **674,809,450 bytes headroom** under
the unchanged 145 GB cap. This is a stopped snapshot, not a new reservation or
permission to expand a campaign. Maximum observed normalized-span size across
the completed generator is **35,263 UTF-8 bytes / 35,171 Unicode characters**;
byte coverage does not establish token representability. Numerical inference,
training, token counts, semantic reconstruction and proof authority all remain
false for this source-only generation. Execution-source bindings remain pinned
to `f0cf880ce`; post-run integration preserves incoming root history at
`83c9016146bda937bcee498475e556cbe32956c0` and the published native adapter merge
`928cb1e73e43f8e2e2e42fea16926d4b393b77fa` without changing the measured execution
generation. Source acceptance and campaign publication remain distinct steps.
The [post-run merge preservation receipt](review/merge-preservation.json) pins
datasets integration `c52453ba4ad3470efc73ecce33ce24363b113469`, containing both
the measured `f0cf880ce` work and published native `928cb1e` history. All nine
executed owner files match their measured working-file and Git bytes; incoming
root `83c9016` and accelerate `e57617a3` history is preserved. Canonical dirty
trees were not changed.

The accepted phase 04 metadata snapshot contains **eleven copied files /
1,425,784 bytes**, plus its **4,807-byte receipt**, for **1,430,591 bytes total**.
Its receipt SHA-256 is
`49d3f36bec9bdc7113537ac011387b75bb834d8da91971e7b20338c761c03066`.
It excludes database and spill content, opens no database and loads no model.
Frozen original databases, source assets and checkpoints remain retained in
their owned locations; the metadata package is not a full-source identity or
model artifact mirror.

Every stopped window must retain its committed cursor, authenticate inherited
target rows, independently rebuild all new source occurrences and both digest
extensions with different paging, and verify its own process group and resource
release. Bound failures must preserve a durable cursor and frozen parent;
publication waits for stopped artifacts and review. No source changes or main
publication occur while the active execution tree is running.

Retained originals and frozen predecessors remain charged. Keep one active
continuation and one staged clone at a time, explicitly budget the sum of
retained campaign databases, staging, spill, logs and receipts, and review any
larger aggregate campaign allowance against the same global cap. A parent above
the current clone ceiling requires explicit reviewed clone-budget admission.
If a growing clone chain no longer fits, plan immutable hashed occurrence shards
before expanding it; do not delete original assets, prune prior evidence, release
foreign claims or silently raise caps.

## Assets to reuse and separate registry cells

The source reconciliation invokes no tokenizer, autoencoder, training or proof
checker. Original embeddings and model assets remain available for reuse, and
the existing 768D warm initialization retains **26 copied donor tensors / 27,142
parameters**, initialized but unaligned. Reuse authenticated saved embeddings,
decoder checkpoints, the donor mappings and the warm state before generating
additional caches. A saved embedding can be reused only within its authenticated
producer/context profile; widening a vector or changing pooling does not create
a native embedding. Learned teacher qualification and fresh retention/fidelity
checks remain necessary before distillation promotion.

LegalIR, CodebaseIR, SecurityIR and IntentIR keep separate family, schema/version,
decoder-task and 8D/384D/768D namespaces. This is a compatibility and parallel-path
contract, not evidence that twelve trained compatible checkpoints and arbitrary
source runtimes are qualified. The retained native 768D producer still accepts
512 input tokens despite the base model's 8,192-token capacity; its output
geometry and codec bounds also need separate qualification.

Use a registry cell keyed by **IR family × dimension × schema/version × decoder
task**, with explicit encoder revision, tokenizer, context/chunk profile, codec,
logic target profile and checkpoint digest. Within one family, semantic JSON,
learned text reconstruction, raw-source restoration and FOL/TDFOL projection
remain different tasks. An ablation run also records donors, dataset/split hashes,
objective, seed, code revision and parent checkpoint rather than replacing the
default task head.

Each cell needs its own inventory and configured DuckDB/DuckLake database or
catalog, independently resumable lifecycle and Hugging Face manifest/checkpoint
namespace within its family-and-dimension repository root.
Shared immutable source assets may be referenced by hash without copying a full
vector mirror. Register authenticated preserved checkpoints in the
`ipfs_accelerate_py` model manager using the same cell identity and immutable
artifact hashes, with explicit initialized/trained/evaluated/qualified status.
Runtime selection still requires the task's qualification gates; registration
or public Hub upload does not establish training quality. Audit existing local,
registered and uploaded states first, and publish only stopped, reviewed assets
whose downloaded hashes and metadata agree. Missing cells stay explicitly
unavailable instead of borrowing a decoder with a similar dimension.

The following **twelve public repository roots are naming proposals** under the
existing dataset publisher's namespace. Their existence, current owners,
revisions and compatibility have not been audited here. First reconcile actual
repositories and model-manager registrations; preserve compatible existing
names and pinned assets rather than renaming or uploading duplicates solely to
match this proposal.

| IR family | Proposed 8D root | Proposed 384D root | Proposed 768D root |
| --- | --- | --- | --- |
| LegalIR | `justicedao/legal-ir-autoencoder-8d` | `justicedao/legal-ir-autoencoder-384d` | `justicedao/legal-ir-autoencoder-768d` |
| CodebaseIR | `justicedao/codebase-ir-autoencoder-8d` | `justicedao/codebase-ir-autoencoder-384d` | `justicedao/codebase-ir-autoencoder-768d` |
| SecurityIR | `justicedao/security-ir-autoencoder-8d` | `justicedao/security-ir-autoencoder-384d` | `justicedao/security-ir-autoencoder-768d` |
| IntentIR | `justicedao/intent-ir-autoencoder-8d` | `justicedao/intent-ir-autoencoder-384d` | `justicedao/intent-ir-autoencoder-768d` |

Inside a root, propose immutable paths
`schemas/<schema-id>/<schema-version>/tasks/<task-id>/profiles/<profile-digest>/runs/<run-id>/checkpoints/<checkpoint-sha256>/`.
Each checkpoint manifest records Hub repository and commit revision, decoder
weights/configuration/tokenizer/codec digests, exact source/split/cache references,
donor and parent hashes, code revision, training/evaluation receipts and lifecycle
status. A promoted alias points to one immutable manifest; it never overwrites a
checkpoint or mixes an ablation with its parent. A larger token profile or
expanded codec receives a new profile path even when compatible tensors are
copied from an existing decoder.

The full ModelManager cell descriptor records family, latent dimension and its
role, schema ID/version, decoder task, output format, producer revision/profile,
encoder hidden width, tokenizer, context/chunk profile, codec/logic profile and
checkpoint digest. Derive the cell key from a canonical versioned descriptor and
register a checkpoint under that key plus its artifact digest, with the same
immutable Hub revision and local custody references. Keep model width and IR
latent width explicit; neither inferred dimensions nor repository names determine
compatibility. Model availability, initialization, trained status, arbitrary-source
qualification, reconstruction fidelity and proof authority are separate fields.

Use the same family/dimension/schema/task/profile components in local inventory
paths, with a separately configured `inventory.duckdb` or DuckLake catalog per
cell and per-generation manifests for source rows, vectors, targets, runs and
proof bindings. Cross-cell reuse references immutable source/embedding/checkpoint
hashes and records its compatibility mapping instead of merging inventories or
padding vectors. Provisioning these namespaces remains a planned deliverable;
the table does not claim twelve trained models or twelve qualified runtimes.

The surveyed concurrent owner at
`artifacts/legal-native-cache-20261011-01` already implements
`arbitrary_native_source_cache.py` and `arbitrary_native_legal_ir_runtime.py`.
The [native-gap survey](review/parallel-native-gap-survey.json) and
[concurrent update](review/concurrent-survey-update.json) bind the observed
assets. Its eight-source data-only pilot had no targets and no qualified native
token/cache/representation runtime at survey time. Coordinate the next cache and
runtime preflight with that owner, review its contribution, and integrate its
additive adapter rather than implementing a second one. Reuse the published
casewise raw-source retention gate, which selected the frozen parent and rejected
all fitted endpoints. Its source-only results do not qualify a native semantic
decoder teacher.

The later [native-owner protocol review](review/native-owner-protocol-review.json),
observed at 02:31 UTC with SHA-256
`9ce3b3bedc6796b1d57760edd4730ef06791dfa2dd2a1f0b0caa18ee126cafa1`,
accepts only a pre-run source-only native384 readiness/frozen normative32 custody
protocol. It explicitly leaves target representability, semantic gold, legal
fidelity, source semantics and proof unqualified, and approves neither native768
nor learned8 execution. It does not establish completed native production or a
reconstruction improvement; subsequent stopped result receipts are required.
The packaged receipt is byte-identical to the reviewed owner asset; its
[copy custody record](review/native-owner-protocol-provenance.json) preserves the
original path, expected digest and unchanged before/after file signatures.

The frozen [midrun parallel survey](review/parallel-survey-midrun.json) records
the subsequently published [native adapter PR #1280](https://github.com/endomorphosis/ipfs_datasets_py/pull/1280)
at datasets merge `928cb1e73e43f8e2e2e42fea16926d4b393b77fa`, preserving its
`db432c5` parent history. Its completed retry produced **eight genuine native384
GTE-small inputs**, with **19–79 untruncated tokens**, and ran **two frozen
decoder passes / sixteen EOS-complete syntax outputs**. The saved result review
accepts source/cache/candidate consistency and cooperative resource cleanup;
these diagnostics used zero optimizer updates and created no new weights. They
establish no semantic gold, legal reconstruction fidelity, qualified teacher,
learned8/native768 execution or proof result. Canonical output syntax is separate
from statutory semantic correctness.

That result review explicitly reports `full_evidence_custody_clean=False`: the
exact admitted review body with digest
`5aaf410334fd1ca9be2ac061fd9807d266eff4f28247f6f3a677a66af060ca68`
was overwritten without retaining its bytes. Our separately preserved `9ce3b3`
pre-run protocol copy is a different receipt and cannot substitute for that
retry's admission gate. Phase 04 result review is now closed; post-run integration
should reuse the published additive
adapter while preserving incoming history and existing compatibility gates.
Require recovered exact admission custody, or a new bounded replay with all
admission inputs and review bytes pinned and retained, before production
promotion. Cache readiness and syntax diagnostics do not relax target
representability, legal fidelity, teacher or proof acceptance.

## Span, token and chunk planning

First measure source-only section/span UTF-8 bytes, Unicode characters, physical
offsets and historical extraction identities without loading a model. Byte/page
bounds limit extraction and persistence; they do not establish tokenizer or
decoder eligibility. Preserve every physical occurrence and bind any alias,
normalization map, source-context reference and child chunk to its parent source.
Do not collapse identical sentences from different physical locations.

After that inventory, the native-cache owner must count tokens with the exact
retained tokenizer and distinguish input content, surrounding context, special
tokens and target/output tokens. Produce a routing table for each registry cell:
fully eligible, missing compatible cache, fallback/nonstatutory source,
unsupported schema/task, needs context, input overflow, clause/codec overflow or
output overflow. Count all dispositions; a refusal must not disappear from the
denominator. A source-only record never counts as a trained or proven span.

Use the smallest qualified width/context cell able to represent the declared
task, while retaining explicit parallel 8D, 384D and 768D routes. Dimension does
not determine token capacity. Qualify increased 768D input profiles separately,
for example 512 → 1,024 → 2,048 → 4,096 → 8,192 tokens; these are proposed stages,
not available capacities. At each stage, pin truncation policy, attention/pooling,
normalization, chunk overlap and parent/child identity, then measure memory,
latency, target fidelity and retention on fixed and fresh controls.

Prefer section or structural clause boundaries with explicit inherited context
over silent truncation. If a provision needs definitions, cross-references or an
exception outside its span, either attach authenticated context or defer it.
Chunked inference must report source coverage, overlap handling and recombination
checks before claiming fidelity for the larger original provision. Keep output
geometry separate: the retained native replay's 512-token/eight-clause and
32-value codec limits cannot be solved by increasing encoder input length.
After cache production, inventory real-law actors, actions, qualifiers and
clause counts that the frozen codec/head cannot represent. Raw source-only
predictions may support diagnostics, but qualified reconstruction needs reviewed
source/context targets. An expanded codec or head receives a separate checkpoint
and task/profile identity, initialized from preserved compatible donors, with
coverage and fixed-replay retention measured before promotion.

## Ordered deliverables and independent acceptance gates

The same semantic IR may represent multiple original wordings. For example,
canonicalizing synonyms or clause order can preserve an obligation while losing
which words, punctuation and ordering the source used. Once that information is
absent, a decoder cannot choose the exact original wording from semantic content
alone. More dimensions or a longer encoder context can improve capacity but
cannot guarantee recovery of information excluded by the IR contract.

Declare exact-reconstruction inputs explicitly: lexical fields in the IR,
lossless raw-source/offset bindings or byte residuals may preserve the missing
information. Measure a separate **latent-only ablation**, a lexical-field route
and each permitted source/residual route on identical held-out sources. Report
full-span raw UTF-8 exact match and side-channel storage/dependencies for each,
alongside normalized-text and semantic fidelity. Source-reference restoration
can pass a lossless transport task without showing that the learned latent
decoder reconstructed wording. Distillation must preserve this task distinction
rather than treating source-assisted exactness as latent reconstruction quality.

| Gate | Concrete deliverable | Required acceptance before proceeding |
| --- | --- | --- |
| 1. Archive-ID recovery after accepted exhaustion | Prepare a separate bounded recipe/alias recovery generation for the 378,935 unresolved archived IDs, preserving phase 04 target rows and all-source aggregates. | Phase 04 custody, inherited rows, new-source replay and both ordered digests already passed through 60077:0 with all 60,077 physical records, 60,068 valid-document ordinals and nine null-CID metadata records accounted for. Every archived ID retains an exact mapping or explicit unresolved/conflicting disposition. Recipe recovery requires authenticated evidence and reviewed aliases; source exhaustion is distinct from every archive target matching. |
| 2. Full-source identity inventory | Add a separately versioned immutable occurrence-shard inventory for outside-target identities and historical aliases, referencing original raw source. | Hashes, ordered source coverage and counts reconcile to the completed census; duplicates remain distinct. Measure bytes per occurrence, shard size, replay throughput and retained-campaign/staging footprint before admitting the full inventory. The aggregate-only archived controller is not relabelled as this deliverable. |
| 3. Raw-source custody | Bind original raw UTF-8, section/byte offsets, normalized span identity and any normalization/residual mapping. | Raw-source restoration matches original bytes and source extent on Unicode, whitespace, punctuation, citation fallback and duplicate-location controls. A historical normalized sentence hash does not pass a raw-byte round trip. Fallback text is excluded from statutory training eligibility. |
| 4. Native cache and target preflight | Reuse the concurrent owner's arbitrary-source cache/runtime adapter and existing compatible native caches, with explicit routing dispositions per cell. | Exact source/context/vector/producer/checkpoint bindings, genuine tokenizer counts and target codec/clause/output representability pass before decoder or training invocation. Fixed normative replay remains a separate control; no held-out or arbitrary-source qualification is inferred from it. |
| 5. Qualified targets and pilots | Attach versioned semantic and text targets with authority/context and independent training/exposure split metadata; run admitted 8/128/1,024-source cohorts. | Reviewed target coverage and task representability are declared; near-duplicate section/provision exposures are separated from fresh confirmation. Count reviewed, eligible, trained, held-out and deferred spans independently. No source-only row is promoted to legal gold. |
| 6. Semantic IR fidelity | Evaluate generated IR using canonical schema/structure, field and clause matching plus reviewed legal-semantic checks. | Report complete generated-target exact match, parse/schema success, field/clause recall and precision, unsupported additions and casewise changes in scope, actors, conditions, modality, exceptions and references. Compare frozen parent and teacher baselines with fresh splits; low training loss or teacher-forced token accuracy does not substitute for generated semantic fidelity. |
| 7. Learned legal-text reconstruction | Train/evaluate a separate semantic-IR-to-text decoder head against its declared text target. | Report generated full-span exact match, character/token edits, omissions/additions and legal-semantic fidelity separately. Declare whether the target is normalized sentence text or original raw text. Source references/residuals are separate side channels, whose availability and contribution are measured. |
| 8. Raw-byte restoration | Provide lossless source-reference/offset/residual restoration as a distinct task, alongside the learned semantic/text route. | Byte-identical UTF-8 restoration and offset coverage pass against original raw bytes. Report side-channel bytes and ablations; reference restoration does not establish learned decoder reconstruction from the latent alone. |
| 9. Warm 768D training | Reuse the existing 26-tensor / 27,142-parameter warm state and compatible original assets. Reference-supervised native-interface fitting against reviewed, representable reference targets is a separate run/objective from later teacher-output distillation; no new random initialization is needed. | Both routes require authenticated warm-state/schema/task/profile bindings, exposure separation and per-case retention/fidelity checks. Reference fitting qualifies its reference targets and interface geometry without claiming teacher-output transfer. The later distillation route additionally requires qualified learned 8D/384D teachers, frozen teacher outputs and authenticated alignment mappings; incompatible or mock teachers remain diagnostics. Compare the frozen warm parent and fitted candidates, preserve per-cell checkpoints and reject degraded candidates without overwriting parent state. |
| 10. Logic projection and proof | Project qualified IR into separately versioned FOL/TDFOL/other logic tasks, then invoke the declared compiler and proof checker. | Projection well-formedness, source-to-IR and IR-to-logic coverage, explicit unsupported constructs and reviewed semantic obligations are measured independently. Proof status requires actual checker receipts and source/context/model/compiler/checker/dependency bindings. Parse success, compilation and conditional structural builds are not source-semantic proof. |

After accepted full source exhaustion, audit every still-unmatched archived ID against
its original producer, encoder input/context, source release, normalization and
span/counter recipe. Classify established source-generation differences,
extraction/normalization or ordinal differences, fallback provenance, conflicting
bindings and unresolved cases using authenticated evidence. These are proposed
diagnostic categories, not established causes of phase 04 unresolved IDs. Keep unresolved,
conflicting and refused archive-ID counts visible alongside matched physical
occurrences; source exhaustion does not license guessing a replacement ID.

The full-source immutable shards should index raw and normalized source hashes,
physical source CID, legal reference, source release and byte/section/span
location. Exact content hashes may identify multiple physical occurrences, so
context and physical binding remain necessary. Reviewed alias records can link
legacy IDs to current occurrences with an explicit relation, evidence, recipe
and reviewer/version, without rewriting either identity. Ambiguous mappings are
ineligible for training. Original embeddings may cross such an alias only after
the exact encoder input/context and complete producer/tokenizer/pooling/profile
custody are authenticated; a near string match or an isolated equal hash is
insufficient to reuse a contextual vector or establish a learned teacher.

Keep stage transitions durable: manifests list the exact input generation,
previous receipts, cell/profile, resource allowance and accepted/refused/deferred
counts. Commit outputs and progress together, cap retries, and retain failure
receipts without changing original assets. A different producer, chunk policy,
schema, source snapshot or decoder task creates a new generation rather than
rewriting the measurements of the previous one.

## Codebase and supervisor proof-index route

Apply the same custody and per-cell gates separately to CodebaseIR, SecurityIR
and IntentIR. A repository-under-test inventory binds commit/tree identity,
working-tree differences, file hashes and spans, parse/build environment and
dependencies. Incremental scans invalidate affected entries when those bindings
change. CodebaseIR describes the scanned source; IntentIR describes requested
behavior and must resolve its references against that exact inventory. SecurityIR
findings retain their own schema, assumptions and evidence.

The `ipfs_accelerate_py` supervisor may plan using source mappings, declared
obligations and typed unresolved states. Its proof cache/index must distinguish
candidate formalizations, projected obligations, checked proofs and source
semantic verification. On-the-fly CodebaseIR adaptation is admitted as its own
family/schema/task training run against the current repository generation,
with fixed/fresh checks and a separate checkpoint; it cannot mutate an inherited
proof's evidence or establish proof from training loss. Namespace these records
in the matching DuckDB/DuckLake inventory and expose incomplete coverage to the
symbolic planner rather than treating absent or stale entries as verified facts.
