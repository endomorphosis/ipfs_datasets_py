# Original checkpoint replay and text reconstruction

This experimental generation reuses the original published LegalIR, SecurityIR and IntentIR 384D checkpoints and their retained validation embeddings. It follows the metadata and cached-input adapters in `runtime_routing_handoff.md`. The accompanying JSON handoff records actual numerical outcomes, refused attempts and exact artifact receipts; passing import or adapter tests does not count as reconstruction.

## Numerical findings

All three successful runs loaded their authentic original weights and inferred five ordered, target-free inputs per family, selected before inference from the existing validation caches. They ran in separate finite CPU processes with no training, new embeddings, database writes or supervisor execution. All fifteen outputs passed the bound runtime's local grammar/schema checks; none matched the full retained IR exactly. These development rows do not establish independent teacher quality.

| Original 384D family | Replayed rows | Exact retained IR | Embedding MSE | Exact original text |
| --- | ---: | ---: | ---: | ---: |
| SecurityIR | 5 | 0/5 | 0.000765492 | Not emitted |
| IntentIR | 5 | 0/5 | 0.000700589 | Not emitted |
| LegalIR | 5 | 0/5 | 0.001233448 | 0/5 deterministic renderings |

Legal loading additionally verified its four-row saved numerical fixture against the original expected result digest. Those four rows establish loader/checkpoint consistency and are distinct from the five validation replay rows. The five predicted Legal IRs rendered successfully, but both literal UTF-8 and whitespace-normalized source equality were zero. Predictions changed actors/actions/objects, and three introduced a 20-day temporal qualification absent from their retained targets. This is a semantic error as well as a wording error.

The Legal formula codec also lacks atoms needed by all five retained targets: five actors, four actions and five objects are unrepresentable. Existing frozen output codecs therefore prevent exact IR on all fifteen selected rows across the three families. This finding concerns these explicit original published checkpoints and caches; it does not assert that every later candidate checkpoint has the same vocabulary.

Eight refused attempts remain preserved alongside the three successful runs. Their import/dependency failures have no reconstruction score. Some refused Legal loads restored model state before failing in optimizer initialization; a load that did not return is not evidence that no weight-loading operation occurred. The successful fixture and inference receipts are the evidence for completed loading. Full native effect/linker containment, source-disjoint teacher quality and serving-release qualification remain outside this bounded development experiment.

SecurityIR emitted the same subtraction/boolean fragment for all five targets, whose operators were addition, multiplication, less-than, greater-than and equality. IntentIR also changed critical semantics; one required dispatcher/classify/manifest target became permitted operator/save/report. These are semantic errors, rather than equality failures caused only by metadata. Grammar validity and a modest embedding loss do not imply source-faithful IR. Fix the current family-specific decoder's conditioning and vocabulary/target coverage before using it as a distillation teacher.

The original whole-string JSON-token vocabularies cannot express any of these ten retained targets: SecurityIR has unseen operand identifiers, and IntentIR has unseen actor/object names and several actions. Under the unchanged codec, exact reconstruction on this selected cohort has a representability ceiling of zero. Independent diagnostics also find wrong in-vocabulary operators, types and modalities; expanding coverage alone is insufficient. Add a checkpoint/cache vocabulary compatibility gate first. A derivative decoder can expand the lexical inventory with explicit old-token-to-new-token mapping that preserves existing learned rows, or introduce a separately qualified subword/reference decoder. Width/context scaling and more epochs with the frozen old codec cannot repair missing output tokens.

Build derivative codecs from training data and a declared open lexical scheme, such as grammar tokens plus byte/subword strings or typed source references. Adding exposed validation labels to a closed vocabulary and replaying them is not a generalization test. A lexical copy channel must declare source access explicitly and be scored separately from source-withheld learned recovery.

## What the measurements mean

Embedding reconstruction measures the mean squared difference between the 384 reconstructed coordinates and the original cached vector. Exact IR measures equality of the entire predicted serialized native target, joined by original row ID and authenticated source/vector digests. Legal text reconstruction compares the emitted prose against the original UTF-8 source, separately from whitespace-normalized equality. Abstentions, refusals and missing outputs remain in the attempted-row denominator.

The current numerical decoders predict IR tokens, rather than original prose tokens. Legal inference is parser-assisted. The optional Legal decompiler receives only the predicted canonical IR and a request ID; it generates deterministic canonical prose and has no learned model. That text comparison measures the composed numerical-IR/deterministic-renderer path. It does not establish source-free learned wording recovery, independent semantic correctness or teacher readiness.

The original Legal validation cache contains 120 distinct source strings and vectors but only 30 complete canonical targets. Every target is shared by four differently worded sentences. For example, the custodian/register/certificate target is shared by “The custodian must register the certificate.” and “The custodian is required to register the certificate.”, as well as two other styles. Canonical IR v1 retains seven semantic facets and sorts rules; it carries no original phrasing or layout. A single deterministic output conditioned only on each identical IR can match at most 30 of these 120 strings. This empirical limit applies to this cache and this input boundary, not to a decoder supplied with a separate surface channel.

## Reconstruction improvements

1. Keep canonical semantic LegalIR v1 and the original caches/checkpoints immutable. Introduce a separately versioned Legal surface profile for original lexical choices, modal phrasing, connectives, sentence order, punctuation and layout. Distinguish a lossless stored surface sidecar from a learned surface bottleneck: storing or retrieving the original text proves restoration, not neural reconstruction.
2. Add an explicit source-withheld learned text head. Its inputs are predicted semantic IR plus the declared predicted surface channel; its training targets are the original source tokens. It must receive no source text, source hash lookup, gold IR, cache lookup or restoration payload during evaluation. The existing JSON-token head remains a separate semantic task. A deterministic canonical renderer remains useful as a baseline.
3. Reuse original source/group/style/split/vector associations and compatible learned semantic projection/decoder parameters. Add new surface-specific parameters without overwriting inherited semantic weights. Train the surface objective separately, then combine text token loss, native IR token/facet losses and verified teacher distillation. Keep text losses and IR/embedding losses separately visible.
4. Measure original UTF-8 equality, whitespace-normalized equality, character/token edit distance, full native IR equality, critical legal facets and abstention/grammar validity independently. Record all attempted denominators, truncation and unsupported constructs. Conditions, exceptions, permissions/prohibitions, temporal relations and multi-rule documents require additional coverage; the selected first-style Legal/Intent smoke rows cover obligations only. Semantic equivalence requires a separate typed validation/proof contract.
5. Freeze source-disjoint evaluation before tuning or selecting teachers. Audit historical split exposure and group overlap. Retained validation replay is development evidence, even when exact reconstruction succeeds. A low training loss or exact checkpoint fixture match is insufficient to qualify a teacher.

## Reusing 8D and 384D work for 768D

Preserve separate CodebaseIR, SecurityIR, LegalIR and IntentIR inventories at each of 8D, 384D and 768D. Their input roles, token limits, span coverage, schema and decoders remain independent. An 8D structural latent is not an 8-coordinate GTE input; Codebase-owned SecurityIR payloads are not native CodebaseIR decoders. Encoder model ceilings do not qualify decoder span budgets.

Keep the inherited Legal 768D initialization, which already has separate authenticated 8D and 384D donor heads. Reuse compatible family-specific decoder/condition weights and each donor's own vocabulary. Align a new native 768D input connector against authentic cached 384D teacher features on the same source records before updating the inherited decoder. Retained 384D vectors remain teacher inputs; they cannot be padded or relabeled as 768D vectors. Authentic native 768D embeddings require a separately recorded derivative asset generation with the original source identities and producer revision.

Distill teacher native IR distributions or structured targets across explicitly mapped compatible schemas. Distill logits only where token meanings and vocabularies agree. A learned surface teacher can supervise the new surface head only after its independent quality gates pass. Keep the 8D semantic auxiliary head during alignment; unfreeze inherited decoder layers gradually after connector convergence. Use per-family replay/regression evaluation to retain 8D and 384D availability alongside each new 768D candidate. No distillation or new embedding generation occurred in this replay phase.

## Checkpoint source compatibility

The original fixed loaders authenticate exact implementation generations. This isolated replay restores two archived source files to match those original checkpoints. The archived UI codec predates the current strict complete-field codec and must not replace the production default. The archived Legal modal core's automatic worker call expects `worker_budget(kind="compiler")`; the current helper accepts no `kind`. Explicit `IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS=1` bounds this experiment but does not repair automatic parallelism.

Package each historical generation as an explicit checkpoint-SHA-selected canonical-module capsule in a separate process and source root. Preserve the modern UI codec in the normal application. Do not swap global modules inside a running application or repin an old checkpoint to new source. A modern runtime/package requires its own version and validated lineage. A separately reviewed worker-helper compatibility change can accept a validated compiler role, with unset/auto/explicit/clamping and resource-budget checks, before parallel workers are enabled.

## Codebase, stores and planner sequence

After numerical family quality is established, bind a native learned CodebaseIR decoder to the existing repository capture/compiler producer, retaining repository commit, source span, symbol and dependency identities. Formal candidates remain separate from checked proofs. Populate a proof cache only with typed logic, complete premise/dependency receipts and verified solver outcomes; invalidate affected entries when source, models, adapters, assumptions or solver versions change.

Maintain twelve independent cell inventories and physical DuckDB/DuckLake catalog/data/artifact destinations, plus family/dimension-specific Hugging Face repositories and immutable releases. A shared directory may route between them but cannot merge their schema, vector role or quality gates. Match IntentIR against the exact current CodebaseIR symbols and evidence before supervisor planning. Reobserve dependencies before effects; online CodebaseIR training creates budgeted candidates with their own source snapshot, evaluation and promotion gates.

Origin/main integration still requires comparing the reviewed consumer commits and authentic assets against a fresh remote snapshot in an isolated checkout. This archival replay generation is not a production replacement, published release or serving-head promotion.
