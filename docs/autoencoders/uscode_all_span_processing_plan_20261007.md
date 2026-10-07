# US Code span processing plan

Process every source occurrence in the pinned US Code span cache through an explicit inventory, source resolution and task disposition. Reuse existing source bytes, embeddings, checkpoints, compiler observations and research controls. Add learned reconstruction and formal checking as independently measured stages. Every span must be accounted for; successful capture, generated IR, reviewed legal meaning and checked proofs have separate completion criteria.

The first campaign covers the cache at [revision 765176c6db79ba65c1697c21dead43666350b730](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/tree/765176c6db79ba65c1697c21dead43666350b730). Expansion to new upstream sections or cache revisions creates a new inventory generation. This plan schedules no model training or numerical processing by itself.

## The processing denominator

The repository has 6,016 files totaling 4,870,101,925 bytes. Its eight Dataset Viewer configurations overlap and exclude a substantial modal-parser namespace. Scan original pinned files and manifests; use the Viewer to explore, rather than as the authoritative corpus inventory.

| Source or view | Count | Meaning for this campaign |
| --- | ---: | --- |
| Archived resume checkpoint | 443,904 span records plus one metadata record | Starting occurrence ledger; first census must verify unique IDs and exact source joins |
| Archived queue states | 22,379 sealed and 421,525 gap | Historical operational statuses; neither establishes completion for new decoders |
| Verified existing source Parquet | 60,077 section records, 374,277,662 bytes | Reuse the local exact source generation |
| Paired v1 | 4,888 observations in 611 bundles | Source/compiler/legacy-vector observations; repeated model observations remain separate |
| Paired goals and artifacts | 4,740 goals and 10,091 artifacts | Deferred work and evidence, not additional source spans |
| Census v2 and v3 | Viewer reports 26,952 and 1,184 rows | Reconcile original rows and their source/run identities |
| Modal parser namespace | Producers report 443,904 parsed rows and 639,347 formula occurrences | Independently stream its 120 JSONL shards and join IDs; parser coverage is a separate stage |
| Readable formula audit | 56 observations, 45 captured documents, 11 unavailable documents, 372 formula occurrences | Fixed failure audit, not a corpus completion statistic |

The queue's legacy `pending_count=3,820,263` is not a count of remaining distinct spans. Its metadata reports 60,068 processed documents; investigate its nine-row difference from the verified source's 60,077 sections. Resolve discrepancies explicitly before publishing a final denominator. Identical citations or text can belong to different source CIDs, so text-only deduplication would lose source occurrences.

The source revision is `justicedao/ipfs_uscode@5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`, with verified Parquet SHA-256 `4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8`. The historical ID algorithm accumulates sentence ordinals within groups of 64 valid source documents. Replay that grouping independently of current worker batch size; retain CID, release, shard/row identity, extraction version, offsets and sentence ordinal.

## What the research already supplies

| Track | Measured result | Reuse and remaining gap |
| --- | --- | --- |
| Native 384D paragraph decoder | Original parent 31/48, retained continuation 33/48, dual replay 30/48 on exposed development wording; control and dual preserve 48/48 across three authored TRAIN cohorts | Preserve original weights, transforms, lexical32 codec and regression panels. These narrow targets have empty qualifiers and do not cover arbitrary statutory values |
| Exact parent comparison | Control gains two parent cases and loses none; dual loses one parent case and gains none | Keep retained continuation as a measured diagnostic baseline. Avoid declaring a new teacher from development scores alone |
| Native 768D cached replay | Genuine native producer and learned checkpoint exist; measured producer runs imposed a 512-token input ceiling, with retained sources measuring 12–111 multilingual tokens; current output geometry remains 512 tokens/eight clauses | Reuse matching caches and tensors. The model's 8,192-token ceiling is not validated long-document reconstruction |
| Raw source scope and support/action heads | Fresh authored positive proposals improve 28/64 to 37/64 linear and 39/64 MLP; unsupported emissions increase 7/64 to 11/64 and 12/64 | Reuse the trained byte/BiGRU and residual heads, with their refusal failures. Their 64-wide token features are a separate source interface, not a GTE latent width |
| Original legal text reconstruction | On the original authored empty-qualifier cohort, deterministic source-withheld rendering gives 48/48 IR equality and 0/48 original-text equality; no learned text decoder ran | Introduce an explicit lossless source route and a separate learned text decoder task |
| Historical span cache | Legacy `mock:stable-sha256/8` vectors and compiler guidance, including some target-conditioned historical guidance; no learned legal formula decoder | Retain diagnostics, failures and compiler artifacts. Do not relabel these vectors as native GTE embeddings or formulas as learned decoder outputs |
| Checkpoint availability | Nine retained raw files public; six fitted recipe/role bindings imported, with 678 prior ModelManager rows preserved and 684 after that transaction | Resolve immutable checkpoint bytes and actual task/profile/schema bindings before loading. Availability does not admit serving, teaching or proof |

The relevant source and findings are already integrated in datasets main. Preserve the [retained wording plan](https://github.com/endomorphosis/ipfs_datasets_py/blob/75f57f9eeff052a5718fd1f2c6a4b73de3784af8/docs/autoencoders/retained_wording_checkpoint_availability_20261007.md), the [support/action study](https://github.com/endomorphosis/lift_coding/blob/a1054e10e3f535360ebcfd844c876690cea7c604/implementation_plan/docs/67-support-action-residual-training-2026-10-07.md), and earlier raw/PCA/autoencoder controls as distinct experiments. Their cohorts and output contracts differ; their scores cannot be pooled.

## Source identities and storage

Create a canonical source-occurrence registry and separate immutable observation generations. A canonical source key binds source repository/revision, source artifact hash, CID, physical row identity, extraction algorithm, document group/ordinal and exact span bytes. Keep the original `span_id` as an alias with an audited mapping. Store exact UTF-8 source and surrounding context by content-addressed reference. A same-ID/different-source conflict receives an explicit conflict record and no silent overwrite.

Reuse identical physical source or embedding bytes through references while preserving every occurrence's source/context binding. Overlapping spans, duplicate sections, textual duplicates and version derivatives belong to leakage-equivalence groups for training/evaluation. Context/proof dependencies use a separate graph: unrestricted statutory crossreference edges could connect most of the corpus. Inspect giant components, keep copied/derived evaluation text and targets out of fitting, and declare whether shared unlabeled contextual material makes an evaluation transductive. These remain distinct occurrences in coverage counts.

| Store | Principal contents |
| --- | --- |
| Campaign inventory DuckDB | Source keys, historical ID aliases, manifest closure, conflicts, namespace coverage and scheduling |
| Family and dimension databases | Separate `legal_ir`, `security_ir`, `codebase_ir`, `intent_ir` cells at 8D, 384D and 768D; producer/codec/schema/task/run inventories |
| Immutable Parquet and CAS | Exact source/context bytes, native vector shards, outputs, complete traces, compressed evidence and batch manifests |
| Candidate logic index | Unreviewed IR, alternative interpretations, compiler/projection results and failures |
| Reviewed logic index | Source-bound interpretations with reviewer method, scope and unresolved dependencies |
| Proof index | Actual checker receipts, formal statements, assumptions and complete source/model/tool dependency keys |
| Supervisor goal database | Explicit repair/context/representation/implementation tasks, imported and leased separately |

Start with serialized DuckDB writes plus immutable Parquet/CAS. The current twelve-cell layout is `planned_not_created`; the isolated DuckLake adapter is metadata-only and `production=False`. Qualify a production DuckLake layout and its transaction/snapshot behavior in its own work item. Until then, never describe the proposed lake cells as deployed. Use one writer per physical DuckDB; workers return immutable result files to a controller/outbox.

US Code spans primarily enter LegalIR. CodebaseIR describes the implementation repository and its proof obligations; IntentIR describes objectives and planning constraints; SecurityIR needs its own applicable source/target contract. Their inventories can run concurrently without relabeling legal text as another family's training corpus. Family transfers require explicit mappings and independently measured results.

Use the following logical Hugging Face repository map. LegalIR384/768 repositories already exist; verify/reuse existing identities for other cells before creating any repository. These names express the planned twelve-cell inventory, not a claim that twelve trained releases are available. Preserve existing visibility and the aggregate LegalIR history.

| Family | 8D inventory | 384D inventory | 768D inventory |
| --- | --- | --- | --- |
| LegalIR | `Publicus/legal-ir-autoencoder-8d` | `Publicus/legal-ir-autoencoder-384d` | `Publicus/legal-ir-autoencoder-768d` |
| CodebaseIR | `Publicus/codebase-ir-autoencoder-8d` | `Publicus/codebase-ir-autoencoder-384d` | `Publicus/codebase-ir-autoencoder-768d` |
| SecurityIR | `Publicus/security-ir-autoencoder-8d` | `Publicus/security-ir-autoencoder-384d` | `Publicus/security-ir-autoencoder-768d` |
| IntentIR | `Publicus/intent-ir-autoencoder-8d` | `Publicus/intent-ir-autoencoder-384d` | `Publicus/intent-ir-autoencoder-768d` |

Within each cell, use immutable `checkpoints/<schema>/<task>/<profile>/<run>/<role>/` releases and a matching DuckDB/DuckLake namespace. Keep the raw-source 64-feature span heads in a separate task/feature-role inventory; do not assign them a fictitious GTE dimension. ModelManager indexes the precise release bindings and aliases.

Each checkpoint binding includes family, dimension role, native input/latent dimension, IR schema/version, decoder task, target codec/profile/format, encoder producer, actual training run/recipe, state role and file/tensor hashes. Keep semantic IR reconstruction, source-occurrence proposals, original-text reconstruction and FOL/TDFOL/other logic projections as separate tasks. Shared backbones are possible; per-task state and ablations remain separately attributable. Unknown schema/profile bindings stay unresolved rather than becoming a universal default.

## Phase zero inventory and source hydration

1. Freeze dataset/source revisions, source hashes, code generation, model release records and current resource policy. Verify manifest/file closure across paired v1, legacy censuses, outputs, modal shards, feature-pretraining artifacts and queued goals. Read metadata and projected columns first; do not hydrate all compressed artifacts.
2. Stream all ledger identity columns, verify unique keys and aliases, and distinguish the one metadata row. Replay historical extraction against the already verified source Parquet. Materialize exact source spans, explicit truncation/mismatch records and needed section context. Reconcile every occurrence, including unavailable or unresolvable sources.
3. Join all historical observations and goals to canonical sources without changing their producer, task or authority. Independently count modal JSONL rows/IDs and retain duplicate formula occurrences. Investigate the source-document count difference and legacy pending counter semantics.
4. Record exact native-cache availability by source/input hash and producer profile. Old vector dimension alone supplies no compatibility. Inventory real decoder assets and all known prior exposure before assigning groups to evaluation.
5. Freeze the full source denominator, connected groups and initial task disposition matrix. Export machine-readable counts, conflicts, unresolved reasons and source-policy lineage.

Exit criteria: every archived span record has a verified canonical source mapping or an explicit unresolved disposition; original IDs, observation history and excluded metadata are accounted for. The unique-source total is published only after the ID scan. No subset is silently removed because it is too long, unsupported, missing a reference or currently ineligible for a model.

The current card has no `license` field; record source and derived-asset policy facts separately rather than inferring legal restrictions. The older denied 21-release JusticeDAO pinset does not include this requested cache. Preserve its historical decision and define the requested cache's own source/transformation/task policy generation when selecting training rows or publishing derivatives. Public accessibility and a storage `train` label do not establish semantic supervision quality.

## Phase one processing compatibility

Reuse existing owners and extend only their missing interfaces:

| Implementation work item | Existing owner | Completion check |
| --- | --- | --- |
| Consume paired v1 and v2 with resumable acknowledgement | `logic/autoformal/span_cache_feed.py`, `paired_span_census.load_paired_census_bundle()` | Manifest schema dispatch, bounded listing/download/expansion, exact hash joins, discovery cursor advances only with durable page descriptors; failed bundles remain pending/unacknowledged at their pinned revision, with no skipped inputs |
| Preserve full source text | `span_cache.py`, `legacy_span_intake.iter_joined_section_batches()` | Eliminate silent legacy 32 KiB slicing across enqueue, census application, sealing, resume and publication; preserve exact-byte mismatch/overflow records and long/Unicode fixtures |
| Read arbitrary bounded native-cache batches | `gte_embedding_reuse.prepare_cached_embedding_reuse()`, `normative_cached_legal_ir_runtime.py` | Add a separately versioned reader; preserve the existing 216-receipt, batch-four replay unchanged |
| Establish decoder representability and task routing | `ir_decoder_profile_inventory.py` and each output codec | Explicit unsupported symbols, values, qualifier nesting, cardinality, context and output-length dispositions |
| Track generations and durable completion | Legacy CUDA controller, progress joins and publication outbox | Source/checkpoint/schema/task/producer/compiler keys; crash recovery with idempotent publication and no skipped rows |
| Capture actual learned outputs | `paired_span_census.py` v2 export | Retain exact generated tokens, checkpoint/source bindings, complete failures and formula origin |

The current `SpanCacheFeed` handles legacy exchanges; it cannot directly consume the current default paired files. The importer already supports paired bundles and provides a reusable validation path. The current native replay is a historical assay, not an arbitrary corpus adapter. Code changes should use meaningful fixtures for v1/v2 compatibility, overflow, identity conflicts, unsupported target geometry and interruption at each outbox boundary.

At this snapshot all 611 paired bundles are v1; no v2 files exist. Append new v2 observations with separate compatible viewer configurations. Preserve v1 as diagnostic history. Do not upgrade an old compiler artifact's origin to learned output. Export names, state transitions and file hashes must match the actual producer. Reading/importing goal packets defaults to a plan; publishing a goal does not enqueue or execute it.

## Phase two reusable embeddings and reconstruction contracts

For each span/task, reuse an embedding only when the encoder and tokenizer revisions, exact encoded source/context/template bytes, pooling, normalization, dtype, dimensions, token count and truncation/window policy agree. Record the vector SHA and source mapping. A matching source ID with different context is insufficient. Projected 8D vectors retain their projector/parent identity; existing hash-derived 8D vectors remain a diagnostic lane.

Run an explicit 8D feature/cache lane as well: authenticate existing genuine 8D features against their actual producer, or use a separately qualified learned projection with its parent encoder and projector hashes. Generate only missing 8D features under that declared profile, and only missing compatible native 384D/768D vectors in separately versioned producer jobs. Keep all prior caches. Use true native 768D encoding rather than padding or relabeling 384D coordinates. Shared source embeddings may be physically deduplicated only for identical encoder inputs and profiles; each family/task retains its binding.

Tokenize with the pinned producer tokenizer. Separate source input, contextual input and decoder output budgets. Initially use the measured 512-token producers. For longer sources, retain all bytes and either record an explicit overflow/context requirement or run a separately declared same-source chunked baseline. Bind chunk offsets, overlaps, source ownership, ordered rules and cross-chunk references. Do not accept only the first 512 tokens as a complete span.

Audit target representability before inference. The lexical32/eight-clause prototypes cannot represent arbitrary statutory names, qualifiers or full documents merely because the input embedding is larger. Introduce a versioned source-copy/byte/subword or pointer-based structured decoder where needed. Bind it to the intended LegalIR schema and a lossless serializer; keep old prototype checkpoints as regression assets.

Use three reconstruction routes:

- **Lossless source retrieval:** store exact source bytes plus extraction/offset references, and reconstruct the original span/section exactly. This verifies reversible storage and provenance, not learned text generation.
- **Semantic IR reconstruction:** emit all represented rules, qualifiers, exceptions, scope, entities and references. Score exact typed structure, each facet and independent source fidelity separately.
- **Learned original-text reconstruction:** train/evaluate a separately identified text head from declared IR/latent inputs. Compare UTF-8 byte equality and explicitly named normalized metrics; measure how much source evidence or copying the head receives.

A pure semantic IR may map multiple wordings to the same meaning. Original-wording recovery therefore needs a declared source-preservation contract or separately learned lexical information. Report canonical rendering and exact original text as different outputs. Avoid conflating retrieval with reconstruction from a compressed learned representation.

## Phase three stratified shadow processing

Run three bounded pilots after interface/source controls pass: 8 spans for transport, 128 for a stratified failure audit, then 1,024 for throughput and coverage. These are proposed batch totals. Start with one admitted model worker, one controller writer and at most two outstanding batches; size compiler pools against the live scheduler rather than physical core count.

Stratify by input length, title/section, operative clauses versus history/headings/citations, definitions, modality and negation, numeric restrictions, exceptions, multiple rules, nonempty conditions, crossreferences, Unicode and ambiguous/context-dependent statements. Include absent-modality and malformed-trigger negatives. Preserve repeated source occurrences and their dependency groups.

Compare frozen original/retained/dual 384D and compatible native 768D assets on their declared representable subsets. Keep compiler-only and legacy 8D diagnostic baselines. Evaluate raw-source trained heads independently; their pointer token states are not a substitute for global GTE embeddings. Do not score unsupported schemas as valid learned IR or silently drop them from the corpus dashboard.

Preserve historical target-conditioned observations with their conditioning flag; they cannot serve as source-only heldout predictions. Durably save new source-only, free-running predictions before reference joins: raw tokens and EOS, parsed/invalid outputs, source spans and association, omitted/extra/duplicate rules, critical logical fields, confidence/refusal and every failure. Keep teacher-forced loss as a separate diagnostic. Capture missing/oversize evidence explicitly with immutable identity and reason; complete capture needs the full permitted artifact or a lossless segmented artifact, not an unrecorded omission.

Review actual statutory pilot sources independently of existing synthetic construction labels. Record alternative interpretations, unsupported constructs and context requirements. Guided/direct compiler agreement, syntax validity, sparse-patch reconstruction and trained vector loss are useful controls but do not create gold labels. The existing readable audit includes obligations hallucinated from amendment fragments and omitted conditions; use those errors to define repair categories.

Before fitting, freeze scope-specific fidelity, critical-error, refusal/unsupported-emission and cost thresholds from the diagnostic pilot, with uncertainty reported by source group. Retention gates should include newly wrong cases and added unsupported emissions, and cannot be satisfied by rejecting all inputs. Exit criteria: source/input and output bindings are exact; representability, actual coverage and resource profiles are known; reviewers can reproduce field-level and whole-statement failures; negative emissions and refusals are reported alongside positive successes. Do not select a model using a newly exposed confirmation set and then describe it as a fresh holdout.

## Phase four reviewed learning and transfer

Freeze connected TRAIN/selection/confirmation groups and a prior-exposure ledger before fitting. Keep the previously exposed 48-paragraph synthetic development panel and earlier source-span panels as exposed retention controls. Newly reviewed real spans need a separate confirmation generation; retrieved compiler targets remain proposals until their source/meaning review qualifies the target scope.

Prioritize representability, modality/negation, condition/exception scope and unsupported-source refusal. The observed control 33/48 versus dual 30/48 and support/action 39/64 positives with 12/64 unsupported emissions do not justify promoting either alternate path as a general legal translator. Define retention at the whole-case and critical-field level, including newly wrong IDs and unsupported emissions, not only aggregate loss or average accuracy.

For the next controlled experiment, hold parent initialization, source vectors, data/groups, original decoder/count/used113 streams, optimizer budget and selector fixed. Change one declared factor. Separate replay bank composition from auxiliary chronology; evaluate a TRAIN-only distribution-preservation or contrastive objective and protect retained cases. Raw/PCA/autoencoder conditioning controls test whether learned representations improve legal reconstruction rather than merely vector reconstruction.

Initialize the 768D decoder with authenticated compatible learned 8D/384D parameters and codec/state mappings. Record copied tensor hashes and unmatched parameters; initialize new interfaces explicitly, initially freeze inherited heads and align on authentic same-source native pairs. Preserve 8D and 384D paths. Distillation targets require a validated donor scope; parameter reuse and reference-supervised alignment can start without falsely qualifying all donor outputs. Compare 8D-only, 384D-only, joint and compatible architecture controls under matched data/update budgets.

Reuse the trained raw-source support/action/trigger assets through a new declared interface if they help. Bind original source bytes, tokenization, source-token offsets, latent producer and span associations. Native pooled embeddings do not contain the existing pointer head's per-token states. Produce missing token features as an explicitly measured job; do not invent or duplicate caches. Freeze the pretrained source heads initially, and predeclare a refusal/per-case evaluation on new groups before using a posthoc parent-emission intersection policy.

Each new checkpoint retains its family/dimension/schema/task/codec/profile/run/role hashes, original assets and actual recipe. Include warm-start, distillation, reference labels and exact optimizer-continuation status separately. Register/publish actual saved endpoints after validated restoration; selected/last tensor aliases count as separate files/roles, not independent trained models.

## Phase five longer spans and all span rollout

Expand input bands of 512, 1,024, 2,048, 4,096 and 8,192 only after the preceding band's source and fidelity gates pass. Independently expand output budgets, cardinality and hierarchical document geometry. Evaluate same-source chunked and whole-context routes with complete document denominators, rule ownership and cross-section/context dependencies. A larger encoder ceiling alone does not increase learned output vocabulary or prove complete legal coverage.

After M0–M3 transport, source, routing and resource controls pass, enqueue the full frozen denominator for triage and its eligible diagnostic tasks. Full accounting does not depend on successful new training. Newly trained numerical generations require their own fidelity/retention acceptance; they do not overwrite the diagnostic campaign. Every span receives a terminal disposition for each declared task: completed candidate, reviewed success, unsupported, unrepresentable, needs context, source unresolved, token/output overflow or explicit error. Retryable technical failures remain active with bounded retries; uncertainty or legal disagreement is a durable repair goal. Track active, completed and deferred work separately.

Key work by canonical source/context hashes, IR family, dimension role, encoder/projector profile, checkpoint, schema/version, decoder task/codec, inference settings, compiler/projection generation and checker dependencies. The archived `sealed` flag cannot short-circuit work for a new model. Reuse a prior result only when the full key and artifact hash match.

Use content-based sharding and exclusive work leases with expiry/recovery. One controller commits source/model result rows and the durable publication outbox. Workers never share a write connection. Bound pending batches, downloaded bytes, expanded evidence, token counts and retained working-set bytes. STOP/restart cancels only owned process groups after identity checks, records completed outputs durably and resumes unfinished keys; preserve all foreign leases/claims and published observations.

Publish immutable batch manifests and validate remote files at the exact commit before eviction. Resolve uncertain commit outcomes before retrying. Retain every span's source binding, complete result or explicit failure, model/config/code hashes, timing and resource observations. A manifest-only publication is not evidence that its referenced output body was retained. Keep old records, add new v2 generations, and join both through the canonical occurrence registry.

## Proof indexing and supervisor planning

Convert reviewed LegalIR into explicitly versioned logic families. Track syntax/typing, source fidelity, comparison/equivalence and actual prover outcome separately. FOL/TDFOL/CEC/DCEC/Lean adapters need their own representation/assumption contracts; bridge names and requested targets are not successful checks. Record text fallbacks and incomplete translations explicitly.

The candidate index stores every generated proposal, including failed and conflicting alternatives. The reviewed index stores the source/meaning judgment and its scope. A proof entry binds the exact formal statement, assumptions, checker executable/version/config, library/ontology generation, receipt, and all source/context/model/projection dependencies. Lean admission requires an actual source-bound `lake build <Lib>` receipt under the declared toolchain, library and axiom policy; a raw compiler smoke is diagnostic. A checker can verify the encoded proposition while the translation remains unreviewed; neither result proves the other. Source/document, context, decoder, schema, ontology or checker changes invalidate or mark stale the affected derived entry.

IntentIR expresses coverage objectives, constraints and repair priorities against the current repository and inventory generation. CodebaseIR binds the scanner/decoder/validator implementation to its Git tree and actual tests/proof receipts. The `ipfs_accelerate_py` supervisor can plan data hydration, missing embedding jobs, reviewer tasks, codec repairs and proof obligations from these indexes. Failed/unknown obligations remain visible and cannot be treated as satisfied preconditions. Import deferred dataset goals explicitly; capability records without executable packets remain descriptive tasks. Planning, enqueueing, training, source edits and proving are separate actions.

Prioritize repairs using failure frequency, legal scope impact, dependency coverage and review effort, then apply them under a new source/model generation with retention checks. Dataset-wide complete accounting is the first milestone; complete formalization cannot be promised from the present evidence.

## Capacity estimates and operating limits

For 443,904 occurrences, one float32 vector per occurrence costs 681,836,544 bytes at 384D and 1,363,673,088 at 768D; an 8D projection adds 14,204,928 bytes. The combined floor is 2,059,714,560 bytes before clauses, context/token features, metadata, indexes, replicas and temporary files. These are arithmetic estimates, not measured cache requirements. Per-token 768D features at long contexts would be much larger; retain them selectively and use bounded producer batches.

A complete 4.870 GB Hub mirror and a new full vector store would consume more than the recently observed approximately 2.6 GB headroom under the existing 145 GB named-root policy. Recheck the live ledger/census before each phase; do not release others' retained claims or raise a cap implicitly. Reuse the verified local source and shared immutable assets, stage/download shards on demand, and evict only independently verified published replicas. Include campaign storage in resource accounting even if its physical path differs from older roots.

The planning host reports 20 logical CPUs and NVIDIA GB10; `nvidia-smi` reports N/A for total/free memory. Measure actual model, CPU/shared memory and accelerator allocations rather than interpreting N/A as free capacity. Preserve scheduler validation/proof reserves and use actual sampled resource evidence, with its measurement scope, to propose each profile. Begin conservatively and size 512→8,192 batches from measured peaks and headroom.

Estimate runtime from the 1,024-span pilot by length/construct band, eligible task count, cache hit rate, invalid/refused output rate, source hydration, encoder/decoder/compiler/checker work and publication time. The old 24-span mock/compiler sample is unsuitable for predicting native learned reconstruction over this corpus. Report p50/p95 latency, maximum observed memory, storage per span and throughput for each stage; include errors and excluded/unsupported cases in coverage. Budget full rollout as the sum of stages over their actual eligible denominators.

## Implementation order and acceptance

| Milestone | Concrete deliverable | Acceptance |
| --- | --- | --- |
| M0 inventory | Frozen source registry, namespace joins, connected groups and coverage manifest | All 443,904 archived records reconcile or have explicit dispositions; unique IDs and source generation are checked |
| M1 transport and source | Paired feed compatibility, lossless source adapter, durable generation queue/outbox | v1/v2, long Unicode sources, conflicts and crash/restart controls pass |
| M2 cached assets | Arbitrary bounded native-cache reader and task/codec routing | Existing 216 replay unchanged; only compatible caches reused; missing/unsupported states explicit |
| M3 statutory pilot | 8/128/1,024 shadow panels, independent review and measured resource model | Whole/source/negative/coverage metrics reproduce and new inference remains source-only |
| M4 targeted learning | Versioned representable decoder targets, controlled replay/refusal experiments and learned 768D initialization | Qualified TRAIN scope, retained cases, fresh confirmation and exact restored checkpoints |
| M5 full accounting | Resumable diagnostic/task generations after M0–M3; independent of M4 training success | Every occurrence/task has completed or explained disposition; durable artifacts and remote receipts reconcile |
| M6 logic and proof | Reviewed lowering and dependency-aware proof index/supervisor tasks | Source/semantic/checker claims remain distinct; actual proofs bind all dependencies |
| M7 long context and lake | Measured span/output expansions and separately qualified production DuckLake | Short-span retention, complete long-span coverage and real persistence checks pass |

The first implementation slice is M0 plus the M1 feed and nontruncating intake changes. It can begin without training a new model. Numerical pilots follow arbitrary-batch cache/routing controls; corrected real-span targets and 768D transfer follow those measurements. Reviewed TRAIN-only updates may run alongside processing as new immutable model generations: freeze each worker's checkpoint, separate its queue/cache keys, gate promotion on retention/fresh confirmation and never fit on confirmation labels or unreviewed predictions treated as gold. Publish the plan, implementation and compact evidence against current main while preserving frozen source trees and all parallel contributions.

## Source and survey references

- [Pinned dataset card](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/765176c6db79ba65c1697c21dead43666350b730/README.md) and original manifests/files at that revision.
- Local bounded census receipts: `dataset-census/coverage-findings.md`, `survey-receipt-index.json`, `progress-record-scope.json`, `existing-source-parquet-survey.json`, and `manifest-closure-survey.json`.
- Pipeline owners and concrete gaps: `pipeline-survey/pipeline-survey.json`.
- Parallel research and exact historical policy scope: `research-survey/research-survey.json`.
- [Original 384D semantic evaluation](https://github.com/endomorphosis/ipfs_datasets_py/blob/75f57f9eeff052a5718fd1f2c6a4b73de3784af8/docs/autoencoders/evidence/contextual-legal-runtime-20261006/384-semantic-ir-evaluation.json), [original text evaluation](https://github.com/endomorphosis/ipfs_datasets_py/blob/75f57f9eeff052a5718fd1f2c6a4b73de3784af8/docs/autoencoders/evidence/contextual-legal-runtime-20261006/384-original-text-evaluation.json) and the separately named 768D receipts verify the rendering-control scope.
- Existing dataset owners: `legacy_span_intake.py`, `paired_span_census.py`, `span_cache_feed.py`, `gte_embedding_reuse.py`, `normative_cached_legal_ir_runtime.py`, `ir_decoder_profile_inventory.py`, `ir_legal_text_roundtrip.py`, `autoencoder_uscode_inventory.py`, `autoencoder_source_partitions.py`, `autoencoder_embedding_receipt_set.py`, `autoencoder_uscode_corpus_rows.py` and its export helper.

The [published coverage survey](evidence/uscode-all-span-plan-20261007/coverage-findings.md) and [evidence index](evidence/uscode-all-span-plan-20261007/evidence-index.json) retain the dataset, pipeline and research findings and plan reviews. The compressed manifest-closure receipt records metadata/LFS identity checks; it does not claim every table body was downloaded.
