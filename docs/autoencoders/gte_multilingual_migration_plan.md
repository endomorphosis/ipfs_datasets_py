# 384D to 768D logic IR migration plan

This plan preserves the useful work from the GTE-small logic IR models while preparing a separate 768D lineage using `Alibaba-NLP/gte-multilingual-base`. The recommended sequence is to qualify a 384D source decoder, transfer its behavior on short sources, and then train and evaluate longer context. November 2026 is the proposed transfer month; the teacher quality gate controls when distillation begins.

Status: migration plan with initial preparation tools implemented. This document and its [work items](gte_multilingual_migration_work_items.json) specify the remaining work. See [preparation tools and the first audit](gte_migration_preparation.md) for implemented inventory/corpus checks and measured readiness counts. The [review record](gte_multilingual_migration_review.json) records the source files inspected and upstream revisions observed during planning. The checkout contains other active edits, so its Git commit alone is not a complete description of the inspected source.

## Target model and representation contracts

The target has **768 dimensions**, rather than 786, and supports **8,192 input tokens**. It is a 305M parameter multilingual embedding encoder, not a text generator. Its encoder capacity and context length do not define our IR decoder capacity or output limit. These specifications come from the [official model card](https://huggingface.co/Alibaba-NLP/gte-multilingual-base).

| Property | Current source producer | Proposed target producer |
| --- | --- | --- |
| Model | `thenlper/gte-small` | `Alibaba-NLP/gte-multilingual-base` |
| Dense width | 384 | 768 |
| Maximum input | 512 tokens including special tokens | 8,192 tokens including special tokens |
| Pooling | Mean | CLS |
| Vector normalization | L2 | L2 |
| Reference precision | CPU float32 receipts; separate CUDA inference path | Float32 reference; reduced precision is a separately measured profile |
| Overlength input | Explicit rejection in source inference | Explicit rejection or a named source segmentation policy |
| Model revision | `17e1f347d17fe144873b1201da91788898c639cd` | Observed candidate `9bbca17d9273fd0d03d5725c7a4b0f6b45142062` |
| External model code | Existing ordinary GTE-small loader | Separate `Alibaba-NLP/new-impl` code revision |

The target's [pooling configuration](https://huggingface.co/Alibaba-NLP/gte-multilingual-base/blob/main/1_Pooling/config.json) specifies CLS pooling. Its [model configuration](https://huggingface.co/Alibaba-NLP/gte-multilingual-base/blob/main/config.json) resolves implementation classes through `Alibaba-NLP/new-impl`. The observed code candidate is `40ced75c3017eb27626c9d4ea981bde21a2662f4`. Pin both repositories and hash the actual loaded code, tokenizer, configuration, and weights when producing the reference release. Observed revisions are planning inputs; no local target model has been loaded or qualified here.

The target permits shortened dense outputs, but its 384D output is a different vector space from GTE-small. Neither that prefix nor padded GTE-small vectors establishes interoperability. Native semantic IR schemas can remain shared even when their source vector spaces differ.

## Existing work and what its evidence establishes

Four existing training paths must remain separately identified:

| Path | Actual objective and input | Migration use |
| --- | --- | --- |
| GTE source decoder | Source embedding to generated typed IR or structured scalar fields | Primary 384D teacher and 768D student path |
| Legal sparse core and formula head | Parser-derived sample features and source embedding through a sparse numerical core, then latent-conditioned formula generation | Replay the full teacher and export supervision; head reuse requires its exact latent convention |
| Native family reconstruction | Compiler-derived compositional feature vectors to reconstructed features | Reuse typed target preparation, family inventory, and feature evaluation; this loss does not qualify a source decoder |
| Paired text and copy decoder | Custom lexical tokens to generated sequences, with recurrent and pointer attention heads | Reuse copy objectives, vocabulary transfer, and alignment diagnostics in a later decoder design |

[Complete training](../../ipfs_datasets_py/logic/formalization/autoencoder/complete_training.py) exposes distinct entry points for these roles. The native family bottleneck and paired-copy lexical widths are independent of the GTE source embedding dimension. The current paired-copy input ceiling is 192 lexical tokens; changing the embedding encoder will not lift it.

The [reconstruction experiments](reconstruction_training.md) report one Legal diagnostic with 24/24 exact training rules, token CE 0.004605, and only 2/6 exact tuning rules. That exposed panel is useful for regression, not an independent launch test. The [multidomain report](multidomain_reconstruction_training.md) separately records published native source decoders with 0/2 exact semantic held-out reconstructions in each of Intent, Security, and UI/UX, despite valid structure. Later complete-family feature results do not supersede those source-decoder results. A structured source decoder has stronger results on a narrow supported Security grammar, including remaining wording failures; its teacher scope must name that grammar explicitly.

The source corpus and retrieval windows are useful raw material. Their existence does not establish paired gold IRs or completed embedding coverage. For example, the [US Code delivery report](../implementation/reports/source_corpus_delivery.md) retained 62,931 physical rows but only 51 embedded rows, 13 token-limit failures, and 62,867 unattempted rows in that qualification. Begin with a current measured inventory of usable source, target, and embedding joins. Preserve authored diagnostic results as exposed development evidence. Directory labels containing `20261002` identify existing artifacts; this plan does not use those labels to infer an execution date.

## Preserve the reusable assets

| Asset | Required handling |
| --- | --- |
| Original documents and source units | Preserve exact bytes, document identity, character and UTF-8 byte selectors, source namespace, language, and parent relationships |
| Typed Legal, Intent, Security, and UI/UX targets | Retain canonical targets, family/profile identity, sidecars, target origin, and independent evidence |
| Source grouping and partitions | Preserve existing grouping; extend it to all related documents, variants, and translations before generating student data |
| Native schemas, codecs, validators, and consumers | Reuse under their existing interpretation and run targeted regressions |
| 384D vectors and receipts | Preserve as teacher inputs and paired alignment targets; generate new vectors from original text for the student |
| Trained compatible tensors | Copy with tensor inventory, exact parent hash, token identity mapping, and declared new-row initialization |
| Loss, training, and evaluation infrastructure | Reuse where its input assumptions remain valid; give changed objectives a new version |
| Runtime registry, checkpoint packaging, and publication contracts | Add explicit 768D versions and retain the existing 384D loader and defaults |

The source corpus is an integrity and provenance resource. Compiler weak labels, teacher predictions, native shape checks, source comparison, and actual proof-tool executions are different evidence types and remain distinct fields.

## October teacher qualification

WP01 captures the exact source and runtime contracts. WP02 qualifies a chosen teacher per domain and output profile. Legal is the default first transfer experiment, subject to the user's domain preference. The same infrastructure supports the other domains once they have a usable teacher or a supervised baseline.

Before candidate selection, register the supported input/output scope, tuning panel, independent evaluation groups, and acceptance criteria. The qualification report must include:

- Teacher-forced loss, free-running exact IR reconstruction, and per-field fidelity.
- Attempted sources, supported sources, abstentions, unsupported sources, and incorrect predictions as separate counts.
- Native syntax validity, source agreement, and actual tool execution as separate outcomes.
- Negation, deontic modality, exceptions, ordered operands, actor identity, temporal scope, and cross-reference errors.
- Results on new compositions, new wording, and source domains, alongside exposed regression panels.

Proposed pilot launch targets are at least 95% exact IR reconstruction on independently grouped examples within a declared narrow scope, at least 90% coverage of that scope, and no observed critical polarity, exception, or ordered-operand flips in the challenge set. These are planning targets, not measured results or a guarantee. Use at least 50 independent source/composition groups per initial scope, report uncertainty by group, and add a larger natural-source panel before adoption. Freeze the criteria before selecting candidates. A teacher with a narrower qualified scope can supervise that scope while the rest uses reference targets only.

Select checkpoints with tuning evidence. Freeze the selected model, transformations, vocabulary, and implementation before independent evaluation. If those evaluation examples later guide repairs, record them as exposed and create a fresh evaluation cohort for the next final decision. The student final cohort must remain sealed during teacher repairs and student selection. Canaries that share semantic groups with a test panel do not increase the count of independent groups.

Persist exact optimizer state only where the selected backend supports it. The joint formula trainer has resume contracts; the shared source trainer and structured classifier do not provide the same optimizer-resume capability. A new student starts a new optimizer and records that boundary.

## Transfer corpus and artifact contracts

WP03 creates a canonical source and reference dataset independently of teacher readiness. WP05 adds outputs from the frozen teacher only after its scope is established. Use content-addressed blobs and a manifest for large arrays and logits rather than duplicating them in every row.

| Record block | Required fields |
| --- | --- |
| Identity | Sample ID, domain, document ID, group ID, split, canonical source digest, language and source namespace |
| Source | Original artifact digest, exact selectors, source-unit type, parent ID, explicit context selectors, assembled-input digest and assembly policy |
| Reference | Canonical IR digest, target codec/profile, target origin, sidecars, evidence references, validation status |
| Teacher | Exact checkpoint and implementation digests, pipeline identifier, input transform, 384D input receipt, generated output, abstention reason and supervision mask |
| Student input | 768D vector reference, new producer receipt, model and code revisions, token-input digest, token count, vector-space ID |
| Distillation | Logit or field-probability reference, token identity mapping, temperature, conditioning-state reference, teacher disagreement and quality flags |

Suggested vector-space identity is `model@revision:code@revision:d768:pool=cls:norm=l2:input_policy=<policy>:precision=<profile>`. It is a proposed identifier format. Production schemas also need explicit closed fields; an opaque string alone does not validate a profile.

Before fitting, enforce unique identities, finite vectors, exact width/profile agreement, source and target joins, and absence of contradictory labels for identical numerical inputs. Exclude document IDs, groups, exact and normalized source hashes, and duplicate vectors across fitting and evaluation. Extend the existing grouped audit to connected families of related inputs: paraphrases, polarity variants, function-name variants, translations, repository versions, and CVE fix pairs. Quarantine related components discovered across established splits; do not silently move them or rewrite frozen membership. Similar target templates may occur across splits; source/template group policy must be stated rather than silently treating equal targets as independent evidence.

Teacher output is an additional label with a named origin. Never overwrite the reference target. Mask unsupported, unqualified, or contradictory teacher supervision; retain the excluded rows and reasons in coverage accounting. Confidence alone does not establish correctness. Restrict supervision exports and caches used for fitting or selection to train/tuning partitions. Score sealed evaluation only after candidate freeze; it never joins the fitting export. Export teacher probabilities on an explicitly named prefix policy with padding masks. Reference-prefix logits are target-conditioned training evidence; generated inference must run without those targets or prefixes. The embedding tokenizer and IR output vocabulary are different contracts.

Reuse the screening pattern in [legacy teacher preparation](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_teacher_distillation.py), but implement a new 384D teacher to 768D student contract. The legacy module currently binds an 8D compiler teacher to 384D students and is not a ready-made dimensional migration.

## Versioned embedding producer

WP04 creates a new producer; it can proceed while 384D quality improves. Use a float32 reference and compare the selected production profile against it. Record device, attention implementation, precision, padding, tokenizer, and batch policy. Cross-device inference is tested with tolerances; exact checkpoint replay uses a fixed execution profile.

Preflight actual token counts with special tokens and no truncation. The public target examples permit truncation, so our wrapper must explicitly detect overlength before encoding. Validate one-at-a-time versus batched output, padding invariance, normalization, finite outputs, dimensions, and offline loading of pinned model and external code assets. Correct dimensional slicing is `hidden[:, 0, :dimension]` when using the documented CLS representation; validate the wrapper against the upstream implementation rather than copying example indexing unchecked.

Review source text character/byte limits independently from token limits. Existing inference and row contracts cap text at different character lengths. A valid 8,192-token Unicode document can exceed one of those limits. Bound bytes, array sizes, runtime, and total tokens explicitly in the new schema.

The current receipt-set and USCode join contracts also pin GTE-small. New 768D data needs versioned receipt/join handling through the full corpus-to-worker path, not just a replacement embedding function.

## Short context knowledge transfer

WP06 first trains a bridge on identical sources that fit both tokenizers. The initial differentiable pilot uses a qualified raw-embedding sequence teacher from `source_training_v2`, a frozen multilingual encoder, and a learned 768 to 384 adapter:

```mermaid
flowchart LR
    S[Exact short source] --> E[Multilingual GTE encoder]
    E --> A[Learned 768 to 384 adapter]
    A --> T[Differentiable teacher preprocessing and decoder]
    T --> I[Typed IR candidate]
    R[Reference typed IR] --> L[Student training objective]
    T --> L
```

Start with a regularized affine adapter as a reproducible baseline; compare a small nonlinear adapter only after the baseline works. Fit adapter preprocessing on training data only. First freeze the inherited teacher tensors while retaining gradients with respect to adapter output, then allow selected downstream tensors to learn in a separate experiment. Verify nonzero finite gradients into the adapter through training logits. Keep the original teacher checkpoint immutable.

The adapter must reproduce the selected teacher's real input convention. The sequence source trainer centers and RMS-scales raw embeddings before projection; the structured source trainer projects first and normalizes projected features afterward. The published Legal runtime also has a sparse numerical core and parser-derived sample features. Replay that complete path when exporting its supervision, and report those extra inputs. A claim of source-embedding-only student behavior requires an input audit that excludes reference-derived features.

The sparse core performs Python/list and scalar conversions, and the structured runtime uses NumPy. Freezing their parameters does not make either pipeline differentiable. For these teachers, first fit an adapter to declared exported embedding/latent targets and measure downstream replay, or train a separate differentiable student from exported outputs. A differentiable replacement for their numerical path is a separate implementation with forward-replay fixtures and gradient checks. Do not attach a sparse-core-bound head directly to raw adapter vectors or imply that gradients cross the original core.

An adapted 384D vector is not a genuine GTE-small producer output. The new wrapper must validate and record its learned bridge, original 768D producer, teacher transform, and adapted vector space, and prohibit serialization that labels those outputs as genuine GTE-small embeddings. Existing numerical inference accepts caller-supplied finite 384D vectors without authenticating producer receipts; dimension checks alone do not establish provenance. The new package loader must enforce the wrapper's distinct contract.

WP07 compares a native 768D projection and conditioning branch. Copy compatible recurrent/output tensors, but initialize or explicitly transform the dimension-dependent layers in a new architecture. A supervised student with fresh decoder weights remains an essential baseline. The learned 384D bottleneck is a controlled first transfer experiment, not the final capacity claim.

| Tensor | Transfer when widths and vocabularies remain compatible |
| --- | --- |
| Projection down weight | New mapping required for a native 768D input |
| Projection down bias | Copy with unchanged projection width |
| Projection up weight and bias | New mapping required for a native 768D residual output |
| Conditioning weight | New mapping required for a native 768D input |
| Conditioning bias | Copy with unchanged hidden width |
| GRU recurrent weights and biases | Copy with unchanged token and hidden widths |
| Token embeddings and output weight/bias | Map rows by exact token identity; record initialization for new rows |
| Structured scalar classifier coefficients | Refit or transfer through the exact adapter/transform; do not silently pad coefficients |

The existing [domain transfer implementation](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py) supplies an auditable lexical mapping pattern. It currently enforces 384D. The [Security checkpoint migration helper](../../ipfs_datasets_py/logic/formalization/autoencoder/security/checkpoint_migration.py) rebinds compatible implementation identities; it does not change dimensions or embedding models.

## Training objectives and experiment matrix

For matched output vocabularies, the proposed sequence objective is:

```text
L = L_reference
  + lambda_KD * mean_valid_tokens(T^2 * KL(p_teacher(T) || p_student(T)))
  + lambda_state * L_matching_conditioning_states
  + lambda_relation * L_pairwise_similarity
  + lambda_reconstruction * L_declared_reconstruction
```

Use reference-prefix teacher-forced logits for the initial sequence KL experiment and evaluate free-running generation separately. Teacher and student must receive the same canonical reference prefix under the same output codec and token identities. Export prefix token IDs/digests, codec identity, padding/supervision masks, and whether probabilities are raw or grammar-masked. Mask rows with prefixes outside the teacher vocabulary. The Legal grammar codec and shared typed-JSON codec do not have interchangeable timesteps; token-row mapping alone cannot align different output tokenizations. Use hard typed outputs or separately aligned fields across those boundaries.

Start with `T=2` as a proposed candidate; compare `T=1` and retain the existing decoder's deterministic inference policy. Average over valid supervised tokens and account for the teacher mask. Structured classifiers use aligned field probabilities instead of sequence logits. If a teacher exposes only generated hard targets, label that experiment pseudo-label training, not soft-logit distillation.

Do not compute coordinate MSE between unrelated 384D and 768D vectors. Match adapter outputs to the teacher's declared coordinates, matching-width conditioning states, or pairwise relations. For normalized embedding reconstruction, report squared L2 error per vector and cosine error alongside the historical mean-coordinate MSE: raw MSE can fall mechanically as width increases. Preserve or version scale inversion in the current source trainer. Compare magnitudes and gradient contributions before fixing loss weights.

Tune a small, declared grid on tuning data; do not inherit the old gain or reconstruction multiplier blindly. Begin with reference loss plus adapter alignment, add KD, then evaluate optional state and relational terms one at a time. Reduce the KD weight after stabilization so validated references and new capacity can improve beyond teacher mistakes.

| Arm | Encoder and decoder | Question |
| --- | --- | --- |
| A | Frozen selected 384D teacher | What behavior and cost are being transferred? |
| B | Frozen 768D encoder with supervised fresh head | What is gained without teacher transfer? |
| C | Frozen 768D encoder, adapter, inherited frozen decoder | How much existing behavior can be preserved? |
| D | Adapter branch with selected downstream tuning and KD | Does distillation improve over C and supervised adaptation? |
| E | Native 768D head with compatible tensors transferred, with and without KD | Does removing the bridge bottleneck improve fidelity? |
| F | Best student with limited encoder fine-tuning | Is encoder tuning justified by a remaining measured gap? |

The encoder stays frozen through B to E. Encoder fine-tuning, adapters inside it, or contrastive training create a new producer/checkpoint identity and invalidate previous embedding caches. Use a separately sized experiment rather than an automatic next step.

Use at least three declared seeds for the main comparison, identical split and target manifests, and equal declared optimizer-update budgets within comparable decoder arms. Record unique examples, token presentations, wall time, and hardware separately; a frozen encoder and a tuned encoder have different compute budgets. Select on tuning data and evaluate frozen finalists once on the independent cohort.

## Long context and multilingual extension

WP08 introduces context in stages: 512, 1,024, 2,048, 4,096, and 8,192 tokens under the target tokenizer. Keep a short-source regression panel throughout. Test each stage against a baseline that processes the same source as bounded GTE-small units with explicit IR assembly. Bind the same document target, source/context access, and a declared assembly policy for both treatments; when the architecture requires different assembly, report that as a separate factor. Count all overlap, context, boundary-scoring, assembly, and generation work and retain every failure. Equal document identities alone do not establish equal access to definitions or scope. Improved coverage from accepting more text is separate from improved semantic accuracy.

Reuse [coherent spans](../../ipfs_datasets_py/logic/formalization/coherent_spans.py), [token windows](../../ipfs_datasets_py/logic/formalization/token_windows.py), and [source document routing](../../ipfs_datasets_py/logic/formalization/autoencoder/source_document.py). Existing context selectors are provenance and often stay outside the embedded payload. Build a named input-assembly policy that actually includes required headings, definitions, code context, or linked clauses and binds the resulting bytes. Recount tokens after assembly. Retrieval windows remain slices, not automatically complete modeling inputs or gold IR units.

Compare two representations: a whole-document CLS vector and hierarchical ordered clause/chunk vectors with source spans and a document decoder. The second is an architectural proposal. A single dense vector may omit identifiers or cross-clause scope needed for exact reconstruction. Retain the whole-document arm so the value of hierarchy is measured.

Long-context training requires independently supported document-level targets for definitions, later exceptions, entity reuse, cross-references, multiple rules, and ordered execution or temporal dependencies. Local 384D teacher outputs supervise only supported local units. Their concatenation does not establish a correct document target. Keep uncertain or unresolved references explicit.

Input length, IR output length, and IR structure have independent limits. The current sequence source decoder defaults to 512 output tokens with a 1,024-token configuration ceiling; the structured decoder requires a fixed tree, fixed array lengths, and training-derived scalar classes. Add a versioned variable-structure decoder or explicit typed-unit assembly for larger documents. Reuse pointer-copy, alignment, and coverage ideas for new literals, with a new token-state adapter and explicit source-copy evidence. Record assembly failures and truncated generations rather than scoring only surviving units.

The first English transfer does not qualify other languages. Current sentence chunking uses `pysbd.Segmenter(language="en")`, and weak Intent extraction and source-agreement grammars use English/ASCII lexical profiles. WP08 needs versioned language-specific segmentation, supported grammar/scope checks, and reviewed source/IR targets before claiming multilingual IR fidelity. Group translations with their originals. Track language, code versus prose, Unicode selectors, token budgets, mixed language, and names separately. Compare a supervised multilingual student with and without English-teacher supervision; preserve the pretrained multilingual representation if English specialization harms other languages. Sparse retrieval is an optional future comparison, separate from the first dense IR migration.

## Evaluation and resource gates

WP09 uses independently grouped source cohorts and preserves failures in every denominator. Publish exact IR accuracy and coverage per domain, logic family/profile, source type, language, and token-length band. Include uncertainty by group, unknown-class/atom rates, malformed IR, unresolved references, unsupported inputs, and generation overruns.

| Gate | Required evidence |
| --- | --- |
| G0 Source and data | Pinned implementation, original source joins, target origin, complete group exclusion, and reference profile |
| G1 Teacher | Declared supported scope and coverage, independent free-running fidelity, challenge outcomes, frozen checkpoint |
| G2 Producer | Correct revisions, CLS/normalization/width, no silent truncation, offline loading, reference numerical checks |
| G3 Short transfer | No more than a proposed 1 percentage point exact-accuracy regression against the qualified teacher on matched supported inputs; no increased critical scope error count; all failures retained |
| G4 Context expansion | Per-length document targets, no unintended short-source regression, measured gain over same-source chunked baseline, verified source assembly |
| G5 Adoption | New package loads and rejects incompatible profiles, old 384D regression fixtures pass, measured memory/latency fit the declared deployment budget |

G3 is a suggested pilot tolerance, to be frozen before student selection. Use paired group analysis; a tiny panel cannot establish noninferiority. Absolute source fidelity remains necessary even when teacher parity passes. A reference-supervised fallback without a qualified teacher needs a separately preregistered absolute source-fidelity and coverage threshold on reference targets; it cannot claim teacher noninferiority. Context expansion waits for the appropriate short-source fidelity gate in either branch. Gates apply independently to each output profile. Unsupported logic families remain explicit gaps.

Benchmark encoder loading, tokenization, embedding, decoder, qualification, and tool execution separately. Measure batch one and token-budgeted batches across length bands, padding waste, peak resident/accelerator memory, documents per second, tokens per second, and checkpoint/storage sizes. The local device reports NVIDIA GB10; capacity, free memory, kernels, and concurrency must be measured before selecting production profiles. Do not assume device-reported VRAM describes unified-memory capacity.

For one million vectors, float32 storage alone grows from 1.536 GB at 384D to 3.072 GB at 768D, excluding indexes and metadata. FP16/BF16 vectors use half that amount but require a measured precision profile. Maximum input length grows sixteenfold; attention compute and memory do not have a universal sixteenfold multiplier. Use efficient attention/unpadding only after compatibility tests. Cache frozen embeddings; invalidate them if the encoder or input policy changes.

## Implementation work packages

All names for future 768D modules below are proposed; current callable APIs are linked separately. Each package has an explicit dependency and completion criterion in the [work-item list](gte_multilingual_migration_work_items.json).

| Work package | Concrete implementation scope | Completion evidence |
| --- | --- | --- |
| WP01 Baseline inventory | Freeze source/checkpoint/producer identities and per-domain capability matrix | Reproducible teacher replay and complete input/tensor inventory |
| WP02 Teacher readiness | Improve selected 384D source models and evaluate fresh grouped cohorts | G1 report per supported profile |
| WP03 Canonical transfer corpus | Version grouped source/target/context manifests and exclusions | G0 audit with rejected joins and coverage counts |
| WP04 768D producer | New producer/runtime and receipt profiles, receipt sets, corpus joins | G2 reference fixtures and resource measurements |
| WP05 Teacher export | Frozen outputs/logits/fields and supervision masks | Replayed digests, explicit label origins and output mapping |
| WP06 Adapter transfer | New adapter model, teacher wrapper, short-source experiment runner | Arms B/C/D, teacher immutability and transform checks |
| WP07 Native 768D branch | Dimension-dependent tensors, shared decoder transfer, versioned optimizer state | Arm E and transfer versus fresh-weight ablations |
| WP08 Context and language | Explicit context assembly, ordered IR composition, staged cohorts | G4 reports and optional separate multilingual results |
| WP09 Evaluation and profiling | Paired grouped reports, source checks, actual consumer runs, resource budgets | Frozen finalist comparison, applicable G3/G4 outcomes, and resource evidence for G5 |
| WP10 Runtime and package | Explicit 768D dispatch, closed package schemas, offline loading, adoption documentation | Old/new compatibility tests and local package replay |

WP06's reference-supervised baseline needs WP03 and WP04; its teacher-transfer/KD branches additionally need WP02 and WP05. WP08 expands a student only after its applicable short-source fidelity gate passes. WP09 produces fidelity and resource evidence. WP10 consumes that evidence and completes G5 by producing and testing the local package; package creation does not depend on an already completed package-compatibility gate.

Place the new embedding producer and transfer contracts under the existing autoencoder/optimizer ownership boundaries. Add source-facing lazy entry points alongside `complete_training.py` and explicit versions in `autoencoder_runtime_registry.py`. Reuse native target contracts. Extend corpus and registry transport only after local artifact contracts work; changing a modality string does not make current fleet/HF/Arrow transport compatible.

Meaningful checks include producer profile rejection, wrong-width rejection, boundary token counts with specials, Unicode selector correctness, training-only normalization, teacher transform replay, vocabulary alignment, masked KD, unchanged teacher hashes, group leakage rejection, variable-output limits, and exact local reload. Check optimizer resume only where the new package claims that capability. Actual Lean/SMT/model-checker results remain separate from generated IR fidelity.

## October and November delivery sequence

| Period | Work and decision |
| --- | --- |
| October preparation | WP01 and WP03; improve WP02; specify and implement WP04 independently of teacher readiness |
| November 1 to 7 | Complete producer fixtures and corpus joins; freeze each ready teacher; run WP05 and small WP06 pilots |
| November 8 to 14 | Compare short-source arms B/C/D; begin WP07 after the adapter path is reproducible |
| November 15 to 21 | Compare E; extend the best suitable student through WP08; develop necessary variable-output contracts |
| November 22 to 30 | Freeze finalists, complete WP09, and prepare/replay WP10 local packages |

These are target dates and dependency milestones, not a promise that long-context quality will be established in one month. If G1 fails, continue reference-supervised 768D experiments and teacher repairs while keeping KD disabled for the unqualified scope. If G3 fails, diagnose representation and decoder transfer before expanding context. If G4 fails, retain the qualified short-context student and the explicit chunked baseline rather than adopting an unmeasured document path.

Publication and deployment are separate downstream actions. This plan ends at a concrete local package and adoption report; it does not schedule a job, alter a default model, or upload artifacts.

## Evidence and reproducibility

The companion [review record](gte_multilingual_migration_review.json) contains the inspected file hashes, repository commit, upstream metadata observations, and the limits of this planning review. Existing diagnostic results are linked through [reconstruction training](reconstruction_training.md), [multidomain reconstruction](multidomain_reconstruction_training.md), and the [source corpus delivery report](../implementation/reports/source_corpus_delivery.md). Re-run the inventory from a frozen implementation before executing the experiments because this workspace is actively changing.
