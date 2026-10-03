# Longer source spans and bounded decoder distillation

The goal is to reconstruct increasingly long, complete source spans into the
appropriate typed IR. Source length, embedding dimension, decoder output length,
and target expressiveness are four separate constraints. A larger output cap
alone cannot teach a single-rule codec to represent a paragraph containing
several obligations, exceptions, definitions, and references.

The additive [length-trial planner](../../ipfs_datasets_py/logic/formalization/autoencoder/decoder_length_trial.py)
records those constraints without loading a model. The separate
[development numerical owner](../../ipfs_datasets_py/logic/formalization/autoencoder/decoder_distillation_experiment.py)
continues private decoder copies with reference supervision and optional,
explicitly diagnostic same-codec distillation. Neither replaces published
loaders, qualifies a teacher, or grants native proof authority. The historical
8D linguistic path remains separate from its optional learned formula sidecar.

## What the existing paths actually support

| Path | Existing behavior | Limitation relevant to longer spans |
| --- | --- | --- |
| Historical 8D linguistic model | Preserves its parser/features and checkpoint identity | Eight coordinates are not an eight-token context window; the exact producer and readout contract determine supported input |
| Copied 8D neural formula donor | Separate learned sidecar with its original grammar and 64-token output ceiling | Its two archived training examples are synthetic diagnostics, not held-out evidence or a general linguistic decoder replacement |
| 384D Legal source decoder | Verified GTE-small vectors and one canonical deontic rule | The original transfer donor has a 512-token output ceiling, but its target validator still requires exactly one rule |
| 384D domain v4 experiment | Separate transferred domain heads; optional frozen residual projection and persistent conditioning | Its inherited 64-token output bound and checkpoint schema differ from the Legal transfer donor |
| 768D factorized student | Copied 384D and 8D heads connected by four trainable interface tensors | The heads retain separate codecs and ceilings; a 768D input does not create a larger learned decoder |

The separate local 768D interface preparation records zero ready rows among 18 selected
training inputs and no fitted aligned starting generation. Its numerical trainer
is implemented, but those preparation receipts contain zero optimizer updates.
Local native encoder receipts must exist before these rows can become usable.
No 384D coordinate padding, vector truncation, fabricated receipts, or weight
download substitutes for the missing inputs.

The transfer batch has 16 primary training targets of exactly 40 tokens and two
auxiliary training targets of exactly 16 tokens, including BOS and EOS. Repeating
training with output caps 64, 128, 256, and 512 does not turn these into a
long-target curriculum. A single sealed trained state can instead be evaluated
at those caps to measure termination, exactness, invalid outputs, and cost.
That is a decoder stopping-budget comparison, not a capacity or source-length
learning result.

## Build a source-length curriculum from complete evidence

Use the existing [coherent source spans](../../ipfs_datasets_py/logic/formalization/coherent_spans.py)
to retain exact source bytes, UTF-8 and character offsets, heading context,
list parents, and paragraph lead-ins. Its `build_coherent_spans` groups structural
units and preserves oversized atomic sentences. `max_chars` is a structural
packing control, not proof that a tokenizer input fits. The older
[text span selector](../../ipfs_datasets_py/logic/formalization/text_spans.py)
retains exact offsets but uses a simple punctuation policy with known abbreviation
limits; it should not be treated as a semantic clause parser.

A first registered curriculum can use source-token upper bounds 16, 32, 64,
128, 256, and 512. Count tokens using the pinned producer's actual tokenizer,
including its required special tokens. Record the common source IDs and each
lane's individual token counts: different tokenizers do not produce comparable
counts merely because their models share the same source. Never truncate a
sentence, strip an exception, or add unrelated padding to force a bin.

Partition document revisions and their linked/overlapping spans before creating
bins or deriving a vocabulary. All excerpts, retrieved supporting context,
paraphrases, and targets from one leakage group remain in the same split. Fit
normalization and vocabularies on training only. Tuning selects a predeclared
recipe; a fresh test cohort stays sealed until every candidate checkpoint and
recipe is fixed. The existing exposed development panels are regression data,
not a fresh test cohort.

Start with shorter complete training examples and add longer bins according to
a predeclared schedule. Retain examples from earlier bins to measure forgetting;
eventually train on every eligible row. Compare against a shuffled all-length
control with the same parent, trainable parameters, valid-token budget, optimizer
step budget, batch policy, and evaluation schedule. Report actual wall time as
well. These controls separate ordering effects from simply doing more work.
Keep one optimizer state throughout a curriculum: calling a fresh-fit API at
each stage would reset Adam moments and test a different intervention.

The current [384D source embedder](../../ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_384.py)
rejects inputs beyond the pinned GTE-small 512-token limit before encoding. That
limit remains unchanged. The 768D producer has a separately pinned input profile;
its declared capacity does not establish available assets, produced embeddings,
or long-span decoder quality. Over-limit documents need an explicit chunked
baseline with retained dependencies and a separately validated composition step.
Chunk success does not establish whole-document success.

## Preserve context and target coverage

For unresolved referents, definitions, temporal anchors, and scope, reuse
[`BoundedContextIndex` and `prepare_context_bundle`](../../ipfs_datasets_py/logic/formalization/context_resolution.py).
They retain source hashes and selectors, filter the in-memory BM25 index before
scoring by partition, and bound graph traversal and neighboring excerpts.
Retrieved context proposes evidence; it does not fill missing semantics by fiat.

The [remote sparse adapter](../../ipfs_datasets_py/logic/formalization/context_retrieval_adapters.py)
verifies fetched source bytes and filters returned candidates by partition, but
explicitly does not establish index partition isolation. A fresh holdout design
must use a partition-isolated index or retain this ranking-leakage limitation.
[Context bindings](../../ipfs_datasets_py/logic/formalization/context_slot_bindings.py)
and [link obligations](../../ipfs_datasets_py/logic/formalization/context_link_obligations.py)
preserve explicit assumptions and citations. A temporary fixture or conditional
Lake result does not discharge the assumed source interpretation.

Longer Legal targets need genuine representational coverage. The current
[`legal_formula_codec._rule`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_codec.py)
and Legal branch of
[`source_training_v2.validate_target`](../../ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py)
accept exactly one rule. The existing
[`ExtendedLegalIR`](../../ipfs_datasets_py/logic/legal_ir/extended_contracts.py)
can hold bounded sequences of definitions, policies, and norms; it is not already
a supported learned decoder target. Wiring such a complete target requires a
new codec/owner with explicit ancestry and validation. Do not select one easy
rule from a longer source and score the paragraph as fully reconstructed.

Intent already has richer source AST and native-document routes; UI has complete
native documents plus explicit modal declarations. Their authored native
coverage does not mean the current trained model can emit those targets. The
recent complete UI examples require 575–759 target tokens, exceeding the
unchanged 64-token learned domain decoder. Each modality needs its own target
inventory, supported grammar, projections, and source-fidelity checks.

## Preparation API and migration boundary

Prepare one plan per explicit lineage and output head:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_length_trial

plan = decoder_length_trial.prepare_trial(
    lineage, rows,
    split_manifest=decoder_length_trial.split_manifest(rows),
    output_limits=(64, 128, 256, 512, 1024),
    objective="reference_ce",
)
```

`LINEAGE_FIELDS` and `ROW_FIELDS` in the module are the closed public input
inventories. A lineage binds domain, lane, dimension, runtime, representation,
checkpoint, full codec payload and digest, reserved-token IDs, original decoder
ceiling, owner maximum, and unchanged encoder context. Rows bind source and
normalized-source hashes, target hash, group/split, complete token IDs, input
readiness, and input digest. Cross-split group, source, or input-vector reuse is
rejected. A train-fitted vocabulary must bind exactly the training IDs and may
not contain nonreserved tokens absent from training.

Every requested cap and every row remains in the report. A target must include
BOS, its complete content, and a unique final EOS; padding or target truncation
is refused. Missing native inputs and quarantined rows remain explicit blockers.
`training_admission` describes metadata readiness of training rows only;
`convergence_evaluation_ready` additionally requires nonempty, ready validation.
Neither establishes that learning or convergence occurred. Test readiness does
not grant or withhold training permission; test rows are never fitted.

Limits above the inherited ceiling are blocked without an explicit migration.
A migration binds the old checkpoint/runtime/limit, a distinct new owner and
checkpoint, new limit within the declared owner maximum, unchanged codec and
encoder context, and equal inherited-tensor hashes. These are structural checks,
not authenticated tensor preservation. The numerical owner must independently
verify the actual bytes. Changing a metadata number cannot migrate an old
checkpoint or raise encoder context. `validate_trial` replays the complete plan
against the original rows, lineage, split manifest, and options.

The planner can include test token metadata for post-fit coverage reporting.
A pre-fit fresh-holdout workflow must not supply those test targets: seal the
cohort externally and materialize them only after checkpoints and recipes are
fixed. The planner always reports `fresh_holdout: false` and
`convergence_proven: false`; it does not own a sealed-test lifecycle.

## Source curriculum API and the bounded development driver

The separate [source curriculum planner](../../ipfs_datasets_py/logic/formalization/autoencoder/source_length_curriculum.py)
checks complete source components, their original leakage groups, actual token
receipts, and complete ordered target coverage. Use captured full-source
embedding results to adapt the authored paragraphs:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import source_length_curriculum

rows = source_length_curriculum.paragraph_rows(
    authored_rows_with_embedding_results,
    tokenizer_sha256=tokenizer_manifest_sha256,
    tokenizer_profile_id=pinned_tokenizer_profile,
    encoder_context_tokens=512,
    codec_sha256=codec_sha256,
)
plan = source_length_curriculum.prepare_curriculum(
    rows,
    tokenizer={
        "profile_id": pinned_tokenizer_profile,
        "sha256": tokenizer_manifest_sha256,
        "encoder_context_tokens": 512,
    },
    source_bins=(16, 32, 64, 128, 256, 512),
    output_limit=512,
    expected_codec_sha256=codec_sha256,
    expected_rows_sha256=source_length_curriculum.digest(rows),
)
```

The rows digest must also be retained in the external immutable run manifest;
recomputing a digest alone does not establish provenance. `validate_curriculum`
replays the plan against those original rows and options. The adapter preserves
character and UTF-8 byte selectors, original component source/target hashes,
split membership, and ordered target component IDs. Unicode target hashes use
the original paragraph producer's escaped-JSON serialization. A synthetic
paragraph group cannot conceal cross-split reuse of an original component.

`TOKEN_RECEIPT_FIELDS` specifies the closed token receipt. It binds the exact
source, tokenizer identity, unchanged context bound, untruncated token count,
and actual forward count. Counts include special tokens; masked batch padding
is excluded. Missing receipts, artificial source padding, omitted source text,
over-limit targets, and incompatible components remain explicit blocked rows.
All selected rows stay in the denominator. An overall ready plan requires ready
training and validation rows with no blockers.

The plan supplies cumulative `training_ids`, `new_training_ids`, and per-stage
validation IDs. Its `fixed_all_length_validation_ids` is the appropriate fixed
selection panel for this experiment. Empty bins and unchanged cumulative stages
are reported without inventing training progress. Every ready training row must
appear in the final stage. `requires_optimizer_continuity_between_stages` is a
planning requirement; the planner executes no optimizer and claims no learning.

The [long-span development driver](../../scripts/ops/autoencoder/benchmark_long_span_decoder.py)
uses [authored paragraph preparation](../../scripts/ops/autoencoder/prepare_legal_paragraph_curriculum.py)
to combine complete independent Legal rules within their original split. It
retains every clause and target rule, then runs the verified local GTE encoder
on each entire paragraph. It captures untruncated tokenizer inputs and actual
forward inputs, checks the local asset manifest, and retains the fixed
512-token encoder context. It downloads no model weights.

The registered preparation uses 1, 2, 4, and 8 clauses. The preliminary source
length range is 9–72 tokens; actual pinned-tokenizer counts from the run are
authoritative. Complete targets contain respectively 40, 73, 139, and 271 tokens.
These are authored conjunctions of independent rules from exposed material,
not natural long statutes or a fresh holdout. A 16-clause validation composition
is unavailable because that split supplies only ten independent slots. A
16-clause training target would need 535 tokens and exceed the inherited
512-token decoder budget; a separately identified experimental generation with
an explicitly declared larger output budget, such as 1024, would be required.
This would not raise encoder context or migrate the old published loader.

The actual numerical comparison is reference CE versus reference CE plus
diagnostic teacher KL, with the same initial weights, complete targets, source
curriculum, and fixed all-length validation panel. Both arms freeze
`projection_down` and `projection_up` and train the condition, recurrent decoder,
and output parameters. This isolates decoder adaptation while retaining the
inherited feature reconstruction. It does not jointly retrain the projection.
One AdamW instance, scheduler, and random stream continue through all cumulative
stages; moment-state hashes record continuity. Selected checkpoints must improve
reference CE without regressing the configured baseline/selected generation
counts or the initial reconstruction bound. Those numerical checks supplement
the complete-target and source-fidelity reports; they do not confer native
qualification.

Run configuration and immutable source/asset manifests are required by the
driver; `python3 scripts/ops/autoencoder/benchmark_long_span_decoder.py --help`
lists its bounded options. Execute it through the campaign's existing resource
reservation and supervision infrastructure. A direct driver invocation alone
does not establish a global storage reservation. Actual training results and
throughput are pending; preparation and unit tests are not convergence evidence.

## Distillation and measurable learning

The reference-only control trains against the complete original training
references. Diagnostic KD additionally binds a detached teacher's checkpoint,
head, codec, distribution, identical reference-prefix digest, original logits,
and explicit per-token mask. An all-excluded training head is blocked. Different
heads never merge vocabularies or logits. Greedy inference remains temperature
zero; the diagnostic KL uses temperature one, a separate loss calculation.
Unqualified teacher distributions remain diagnostics and cannot become production
supervision merely because their KL decreases.

The separate local GTE interface prototypes use reference CE and fresh AdamW on
four interfaces while checking 26 inherited tensors remain unchanged. They do
not already perform full decoder KD or retain optimizer resume state, and they
are not shipped by this change. The new development numerical owner implements
its own detached same-codec KL and explicit training controls. Separate
experimental generations may explore decoder continuation; their states must
never be relabeled as published checkpoints.

Report complete free-running exactness, semantic fields, source agreement,
missing/extra statements, operator scope, EOS/overrun counts, reconstruction MSE,
and every applicable native logic-family result by source-length bin. Report
reference CE and diagnostic KL separately. Include all failed and unavailable
rows in coverage denominators. Record valid tokens and repeated row presentations
per second, end-to-end unique spans per second, peak memory, and resource waits.
A fixed-count native sample chosen before fitting supplements full output scoring;
it does not prove untested outputs or unsupported families.

Only an actual `lake build <Lib>` supplies Lean admission. A parser result,
reconstruction loss, target, prepared projection, or database row does not.
The strict source/family/Lean gates remain separate and unchanged. This work
does not formalize any Constitution span, claim a global minimum, or establish
that larger vectors or output budgets guarantee convergence.


## Recorded first longer-source experiment (2026-10-02)

The [complete receipt and archived outputs](../implementation/reports/evidence/decoder-source-curriculum-20261002/results.json)
record a successful bounded end-to-end replay after fixing a reporting-only
failure on a PyTorch virtual module filename. The failed attempt and its outputs
remain archived. Only its stopped, owned reservation was reconciled; no artifacts
or other reservations were removed. Both attempts selected identical tensor
hashes. The final focused suite passed **204 tests**.

This is an authored composition diagnostic: 48 training and 48 previously exposed
validation paragraphs, twelve per 1/2/4/8-clause group. Whole-source GTE inputs have
9–72 tokens; complete JSON targets have 40/73/139/271 tokens including BOS/EOS.
The existing 512-token encoder window and 512-token decoder ceiling stay fixed.
All 96 paragraphs were freshly embedded from their complete source, without
averaging old vectors, padding representations, downloading weights, or truncation.
The test corpus was not opened. This is not a natural US Code benchmark.

| 384D continuation arm | Validation reference CE before → selected | Exact paragraphs | Fit wall time | Optimizer updates |
| --- | --- | --- | --- | --- |
| Reference CE | 4.291244 → 0.563414 | 0/48 → 0/48 | 1.822 s | 68 |
| Reference CE + 0.25 diagnostic KL | 4.291244 → 0.976666 | 0/48 → 0/48 | 2.173 s | 68 |

Both arms used identical initial tensors, train/validation sets, seed, batch size,
and cumulative token bins ≤16/32/64/128, with four epochs per stage. Each processed
488 training-row presentations and 45,168 nonpadding target-token presentations.
One AdamW, RNG and plateau scheduler continued across all four stages. The original
feature projection stayed frozen; raw input reconstruction MSE was unchanged at
0.00164220226. Conditioning, recurrent decoder and output parameters were trained.
Selected states reloaded privately and reproduced every recorded generation.
These experimental exports have no restart optimizer state or production identity.

Every selected output was syntactically one canonical rule, but none preserved a
complete reference rule. Across validation there were **180 missing reference
rules and 48 extra generated rules per arm**. Exact reconstruction was 0/12 in
every clause-count group. All outputs reached EOS; no output cap was hit. Thus the
observed failure is not decoder truncation. Lower teacher-forced loss has not
established longer-span autoformalization or convergence. The diagnostic KD arm
provided no measured fidelity gain over reference training in this experiment.

Fresh local embedding generation took 4.239 s for 96 paragraphs (44.15 ms/span,
including model loading and asset checks). Selected-checkpoint validation took
about 1.24–1.26 ms/span, including separate teacher-forced CE, free-running output,
copy and integrity checks. Fit times include baseline/epoch validation and state
export; they are not unique-span inference throughput. The guardian's complete
child-cycle wall time was 67.503 s including storage inventory/admission, child
startup and monitoring; release accounting follows that measurement. The owned
output was 3.97 MB under a 25 MB reservation, one CPU and 4 GB memory. Repeated
filesystem accounting traversed roughly 1.5 million entries. This is a real
end-to-end cost beyond the small neural fit. These are CPU decoder timings,
not bridge-on Legal IR timings: no metric bridges or external provers ran, no
metric-cache shortcut was used, and no sample memory was consulted.

The first experiment’s checkpoint selection protects aggregate exact/EOS/failure counts and
initial reconstruction MSE. It does not yet protect each length group or each
semantic field during selection. Before promoting a length curriculum, add those
per-group guards and compare shuffled all-length training at matched valid-token
budgets. The next decoder ablation should test persistent source conditioning and
explicit clause-coverage supervision; a weak single-rule donor should not become
the authority for longer multi-rule outputs. Diagnostic KL shares a lexical codec,
but the teacher was never qualified on multi-rule reference prefixes.

The historical 8D linguistic teacher remains unchanged. Its bag-like feature hash
does not retain clause order; any use of source offsets to restore order must be
labeled as source-assisted composition. Its optional learned 8D head has a
different grammar and inadequate held-out data. The 768D local encoder assets and
native input receipts remain missing. No actual long-span training or convergence
claim is made for those lanes. For spans beyond a lane's fixed context, retain
coherent subspans plus explicit scope/reference obligations and validate their
composition; successful subspans alone never certify the document.

No model was promoted and no native logic-family or Lake admission was granted.
The independent-rule JSON experiment does not add missing definitions, references,
qualifiers, or other logic-family projections to published production decoders.


## Source-fidelity development owner

The separate [persistent-source adapter](../../ipfs_datasets_py/logic/formalization/autoencoder/decoder_distillation_experiment_v2.py)
and [Legal source-fidelity trainer](../../ipfs_datasets_py/logic/formalization/autoencoder/long_span_decoder_training.py)
address two weaknesses exposed by the first paragraph experiment: initial source
conditioning can be forgotten during generation, and aggregate token loss can
improve while whole clauses disappear. These are private experimental owners;
the original linguistic 8D model and production checkpoint loaders are unchanged.

`bind_persistent_model(raw_donor_body, dimension=384, conditioning="every_step")`
copies the inherited single-layer GRU and adds a zero-initialized 384×16 source
projection to its token embeddings. The `first_step` control has exactly the same
parameters and initialization but injects that residual only at the first BOS
position. It is an augmented control, not the unmodified historical model.
Both retain the original initial-hidden conditioning. Explicit per-sequence state
carries recurrent hidden values, projected source, and a consumed-prefix counter;
there is no mutable module-level source cache. Batched, interleaved, full-prefix,
and incremental decoding are tested for consistency. Generation uses temperature 0
and never reads reference targets.

The trainer accepts complete ordered multi-rule references alongside the numerical
rows and authenticates their exact lexical tokens before fitting. A supplied,
hash-identified single-rule validator checks each individual rule. This validates
rule syntax only; it does not prove source meaning or composition. The new
[fidelity scorer](../../ipfs_datasets_py/logic/formalization/autoencoder/decoder_source_fidelity.py)
reports actor, action, object, modality, conditions, exceptions, and temporal fields
for every original reference position, grouped by clause count. It also counts
ordered exact paragraphs, missing/extra/duplicate whole rules, syntax failures,
and EOS. Failed or missing generations retain their reference denominators.

Checkpoint selection requires per-length and per-field nonregression against both
the initial model and the current selected model, plus the unchanged initial
reconstruction-MSE bound. A candidate then needs an actual fidelity gain against
the incumbent or lower unweighted reference CE. Weighted training loss cannot
replace either criterion. The final complete attempted state and its predictions
remain available even when rejected; they are explicitly distinguished from the
selected state. No optimizer resume state is exported.

Two reference-supervised loss profiles are available in this owner. `reference_ce`
weights every nonpadding output token equally. `semantic_fields` weights every
scalar field value, including modality labels, by 4;
structural keys and punctuation by 0.25; empty-list absence markers and EOS by 1.
This is a complete loss-profile comparison, not an isolated scalar-weight change.
Padding and BOS carry no output loss. One AdamW, plateau scheduler, and shuffle
RNG continue across all cumulative source stages. The unqualified single-rule
donor supplies initialization only; its distributions do not supervise longer
multi-rule targets.

After selection is frozen, zero-conditioning and within-clause-count shuffled
input controls measure reliance on the source vectors. Zero-conditioning removes
both decoder source paths while retaining the original feature projection;
shuffling is explicitly an intentional source/vector provenance mismatch. Neither
control trains or selects a checkpoint. Different outputs under a control establish
source sensitivity, not source correctness.

The [frozen comparison driver](../../scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py)
requires a pinned donor, original complete paragraphs, actual cached embedding
receipts, curriculum inputs, and curriculum plan. It reconstructs the original
component offsets, source hashes, full target tokens, tokenizer counts, and split
checks before fitting. It rejects a manifest pointer that is absent from the input
hash inventory. Frozen dependency and extension trees are inventoried before and
after execution. It writes training reports and postfit `evaluation-*.json` files
to distinct immutable paths, then reloads selected tensors and checks their exact
generations. A source hash or import-tree mismatch aborts the comparison.

This version owns Legal rule facets only. Intent, UI, and Security require their
own target validators and fidelity inventories; their different logic families
are not reduced to these seven Legal fields. Native family and `lake build <Lib>`
gates remain separate and unchanged. Supporting dimensions 8/384/768 in synthetic
adapter protocol tests does not establish available real inputs or decoder quality
for those lanes.

## Recorded source-fidelity comparison (2026-10-02)
The [results and full evidence archive](../implementation/reports/evidence/decoder-source-fidelity-20261002/results.json)
contain eight complete fits: two matched-capacity conditioning modes, two loss
profiles, and seeds 1729/2718. Each performed **340 updates**, 2,440 training-row
presentations, and 225,840 valid target-token presentations. Each arm trained
24,832 parameters, including the same 6,144 new source-adapter parameters. The
original feature projection remained byte-identical. All arms completed their
predeclared 45-second fit budget without deadline termination.

The cohort remains 48 authored training and 48 previously exposed validation
paragraphs: twelve each at 1/2/4/8 clauses. Cached complete-source GTE-small384
vectors and captured untruncated input IDs were replayed and hash-checked; this
run did not execute the encoder. Actual source counts are 9–72 tokens; the earlier
prose maximum of 74 was corrected after checking all captured receipts. Encoder
context and output ceiling remain 512. No fresh test was opened.

| Conditioning | Loss | Seed | Final attempted reference CE | Final EOS / 48 | Fit seconds |
| --- | --- | --- | --- | --- | --- |
| first_step | reference_ce | 1729 | 0.227592 | 0 | 9.124 |
| first_step | semantic_fields | 1729 | 0.304418 | 48 | 7.928 |
| every_step | reference_ce | 1729 | 0.179563 | 0 | 10.248 |
| every_step | semantic_fields | 1729 | 0.218327 | 48 | 7.583 |
| first_step | reference_ce | 2718 | 0.234769 | 0 | 8.717 |
| first_step | semantic_fields | 2718 | 0.275647 | 48 | 8.284 |
| every_step | reference_ce | 2718 | 0.203798 | 1 | 9.900 |
| every_step | semantic_fields | 2718 | 0.212227 | 48 | 7.694 |

These are **rejected final-attempt metrics**, not selected-checkpoint gains. All
160 complete epoch evaluations failed at least one per-length fidelity guard;
all eight selected states remained at epoch 0, with reference CE 4.291244 and
**0/48 exact validation paragraphs**. Initial selected training exactness was
1/48 and did not improve. Every selected state reloaded to identical tensors and
reproduced its original generations. Original donor bytes were unchanged.

The final reference-CE candidates produced unterminated sequences in 47–48 of 48
rows despite lower teacher-forced loss. The field-weighted candidates reached EOS
and passed individual-rule syntax in all 48 rows, but emitted only one rule per
paragraph. Three arms had 180 missing reference rules and 48 extra wrong rules;
the every-step/field-weighted arm at seed 1729 matched one complete rule, leaving
179 missing and 47 extra. Each clause-count bin still had zero
exact paragraphs. Field weighting improved termination in this small comparison;
neither conditioning mode established source-faithful longer outputs. Increasing
the output ceiling would not fix the wrong single-rule outputs or prove that the
unterminated sequences contain the required meaning.

The postfit zero/shuffle controls are preserved for the selected states. Because
all selected states are initialization, these controls characterize the donor
with a zero-valued added adapter. They must not be cited as evidence about the
trained persistent pathway. The separate final-attempt tensors and complete raw
predictions remain available for further diagnosis without model promotion.
All references in this panel have empty conditions, exceptions, and temporal
lists; agreement on those empty fields establishes no nonempty-qualifier coverage.

Each fit took 7.58–10.25 seconds, including baseline and 20 full validation passes,
state snapshots, and report creation. That corresponds to about 22,000–29,800
repeated target-token presentations/second, not unique legal spans/second.
Selected-state evaluation took 80.44–86.18 ms for 48 paragraphs, or 1.676–1.795
ms/span, including teacher-forced CE and free-running decoding plus copy/integrity
checks. The successful guardian child cycle took 113.636 seconds including
admission, startup, and monitoring; with final accounting the guardian took
129.864 seconds. Observed peak child RSS was 678,436,864 bytes; interval sampling is not a continuous
peak measurement. The attempt retained 44,216,864 bytes under a 100 MB reservation,
one CPU slot, one process slot, and 4 GB memory; its reservation was released.

These are CPU decoder diagnostics, **not bridge-on Legal IR timings**. No metric
bridges ran (names `[]`), prover evaluation was false, workers were 1, and no Legal
IR metric cache or sample-memory scoring was used. Paragraph embeddings were warm
cached inputs. No new native logic-family or Lake build ran, and no qualification,
formalization, Constitution round trip, or teacher-distillation authority resulted.

Two operational failures are preserved. The first admission requested five process
slots inherited from an earlier launcher and timed out without starting a model;
the actual cached-vector workload needs one. Its exact unused reservation was
closed by an explicit audited administrative reconciliation with no process or
scheduler authority remaining, unchanged storage cap, and unchanged foreign
claims. The second attempt completed its first fit but collided with `training.json`
when writing the postfit training evaluation; disjoint `evaluation-*.json` paths
and regression tests fixed that. Its stopped owned claim was reconciled through
the existing recovery API. The successful retry changed only report naming, used
the same sealed recipe, and preserved all failed outputs. The final focused suite
passed **293 tests**.

The next quality experiment needs explicit ordered-clause coverage and stronger
source grounding, with diagnostic controls on frozen attempted candidates as well
as selected ones. Possible separate, predeclared arms include a source-supervised
clause-count/stop objective and access to ordered encoder token features. Neither
may read validation targets during generation or relax the existing gates. More
steps, lower teacher-forced CE, a larger output cap, or a larger latent dimension
alone are not established solutions. The 8D linguistic teacher remains unchanged;
real 768D training still requires its missing verified local encoder inputs. No
trained state from this comparison was installed into a production lane.


## Rejected-state controls and source-count comparison (2026-10-02)

The [source-count evidence](../implementation/reports/evidence/decoder-cardinality-20261002/results.json)
continues the full-source experiment above. It adds diagnostics on the **trained,
rejected states**, a separate versioned source-count head, and a matched six-arm
training comparison. These are private Legal development owners, not production
checkpoint formats or new qualification routes. The historical 8D linguistic
teacher is untouched. Actual training here is 384D; verified local 768D encoder
inputs are still unavailable. There is no weight download or encoder context change.

The previous eight rejected candidates replayed their original validation predictions,
numerical metrics, and full fidelity summaries exactly. Postfit controls evaluate
conditioned training and validation, zero-condition validation, and source shuffles
within clause-count bins on both splits. A separate teacher-forced diagnostic holds
each complete reference prefix fixed and partitions NLL into actor, action, object,
modality, qualifiers, structural tokens, between-rule continuation, stopping, and EOS.
References are used for scoring and teacher-forced diagnostics, never supplied to
free-running generation. No diagnostic control participates in checkpoint selection.

Same-length source shuffling changes 36–41 of 48 generated validation sequences.
Matched-source reference CE is lower by 0.003918–0.005063 on validation and
0.012260–0.015389 on training. Most of that difference is in actor/action tokens;
object, modality, and boundary differences are very small. Zero conditioning changes
all 48 generated sequences. This establishes source sensitivity in the trained
candidates; **all eight still have zero exact validation paragraphs**. Sensitivity
is not fidelity. These previously exposed authored inputs are not a fresh holdout.

### Source-count head and unchanged selection

`decoder_cardinality_experiment.py` wraps the existing every-step source adapter
with a zero-initialized 32-class count head from its source-conditioned initial
hidden state. All arms add the same 1,056 count parameters to the existing 24,832
trainable decoder parameters; the inherited projection remains frozen. Count labels
are checked against complete training references by ID. They are training and
scoring supervision only; the generation API receives no reference count.

The three recipes are `no_count` (weight 0), `aux_count` (weight 0.25), and
`guided_count` (weight 0.25 plus causal stopping guidance), at seeds 1729 and 2718.
The guided variant recognizes complete rule boundaries in its own generated prefix
and adjusts the rules-list closing-bracket logit by centered source-predicted
stop-versus-continue odds. Invalid prefixes and counts outside the supported
boundary range receive no guidance. It does not force a valid document or closure.
This experimental mechanism has not earned production use.

`long_span_cardinality_training.py` preserves the original full-reference losses,
continuous AdamW state, scheduler, and per-length/facet selection guards. Count
accuracy cannot select a model. Missing clauses, extra clauses, modality/actor/
action/object fidelity, EOS, order, and reconstruction checks retain their previous
meaning. The script derives 340 updates and 225,840 nonpadding target-token
presentations from the actual curriculum before any arm runs. Each arm receives
2,440 row presentations across 80 epochs and the same 48 training / 48 validation
paragraphs, with 1/2/4/8 clauses. Complete source inputs use 9–72 tokens; complete
target lengths are 40/73/139/271 including BOS/EOS. Encoder context and decoder
output ceiling remain 512; generation is greedy, temperature 0.

Final **rejected-attempt** results from the corrected run:

| Arm / seed | Reference CE | Count correct | EOS | Parsed documents | Fit seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| no_count-1729 | 0.218327 | 12/48 | 48/48 | 48/48 | 9.042 |
| aux_count-1729 | 0.205258 | 12/48 | 48/48 | 48/48 | 8.313 |
| guided_count-1729 | 0.201351 | 10/48 | 48/48 | 48/48 | 8.914 |
| no_count-2718 | 0.212227 | 12/48 | 48/48 | 48/48 | 8.467 |
| aux_count-2718 | 0.199039 | 8/48 | 29/48 | 29/48 | 10.296 |
| guided_count-2718 | 0.282658 | 10/48 | 46/48 | 38/48 | 9.604 |

All six selected states remain at epoch 0, with **0/48 exact validation paragraphs**.
Every final attempted state also has 0/48 exact validation paragraphs. None was
promoted. EOS alone can precede malformed JSON, so it is reported separately from
parsed-document count. The count loss decreases substantially without useful count
discrimination: the trained count heads score 8–12/48, versus 12/48 for the uniform
head's class-1 argmax. None predicts eight clauses, even on the training panel;
training count accuracy is only 14–15/48 for the supervised variants. All count
controls and predictions are archived for both selected and last-complete states.

Within-length source shuffle **preserves the count class**. It is a clause-fidelity
control, not independent evidence of count generalization. Zero conditioning removes
both decoder and count source features, retaining learned count bias. Count CE or
better termination cannot substitute for correct ordered clause reconstruction.
All references here have empty condition, exception, and temporal lists; their
agreement does not establish nonempty-qualifier coverage or native logic-family support.

### Disabled-loss numerical drift and replay

The first six-arm run is retained as `training-r1`, but it failed comparison with
the previous trainer: adding `0 * count_loss` created zero-valued count-head gradients.
Their presence changed floating-point reduction order in global gradient clipping.
A synthetic 128-update reproduction first diverged at clipping step 9. The revised
owner still computes count CE for diagnostics, but adds its autograd branch only
when its coefficient is nonzero. Tests verify absent count-head gradients and Adam
state with guidance off, and exact inherited updates across 128 clipped steps under
both loss strategies. The corrected `training-r2` repeats the unchanged sealed
recipe; its two no-count arms reproduce the prior full 340-update inherited tensors,
predictions, and metrics exactly. The enabled arms are unchanged by the fix.
All frozen sources and failed-comparison evidence are retained. The focused suite
passes **553 tests**. Original donor checkpoint bytes remain unchanged.

### Running and inspecting the private experiments

The source entry points are
[`evaluate_rejected_decoder_controls.py`](../../scripts/ops/autoencoder/evaluate_rejected_decoder_controls.py)
and [`benchmark_decoder_cardinality.py`](../../scripts/ops/autoencoder/benchmark_decoder_cardinality.py).
Their shared [`decoder_fidelity_replay.py`](../../scripts/ops/autoencoder/decoder_fidelity_replay.py)
authenticates complete paragraph, embedding, tokenizer, source/component, split,
codec, and curriculum bindings before returning numerical models. Both CLIs require
`--dependency-root`, `--extension-root`, `--manifest`, `--plan`, and a fresh `--output`.
The manifest pins every loaded extension and input; the plan fixes the experiment.
Use the existing resource reservation layer before launching. The evidence archive
includes the exact guardians, command receipts, frozen extension trees, plans,
inputs, selected and rejected weights, full predictions, controls, and independent audit.
These private exports contain no optimizer-resume state and cannot replace a lineage
checkpoint in a production training worker.

Each arm writes `training.json`, `selected-state.json`, `last-attempt-state.json`,
and separately named `evaluation-*.json` under each state role. Saved tensors must
match the role's recorded digest before and after reload, and validation generation
must reproduce that role's original predictions. History retains aggregate count
metrics rather than copying all count predictions every epoch. Full row-level
predictions remain in baseline/selected/last reports and postfit artifacts.
Reports distinguish numerical evaluation time, total postfit time (including count
and fidelity scoring, serialization/reload), training-call time, and whole-arm time.
The final archive records guardian elapsed time through child exit and through final accounting;
isolated child wall time is not available from these receipts.

The corrected six fits total 54.638 seconds, or 8.313–10.296 seconds per arm,
including all validation/selection work. Numerical selected-state evaluation takes
93.2–101.3 ms per 48-span panel (1.941–2.110 ms/span). Rejected-state panels take
90.9–637.8 ms (1.894–13.288 ms/span); repeated decoding to the cap costs more.
Including postfit fidelity/count scoring, these validation panels take 147.0–694.2
ms. Whole arms, including state persistence and all eight postfit evaluations,
take 9.691–13.517 seconds. These are observed wall times, not a demonstrated speed
improvement over a different workload. The corrected guardian totals 112.254 seconds
including admission, monitoring, and final accounting, retaining 49,876,329 bytes;
its interval-observed peak child RSS is 727,945,216 bytes. The short rejected-state
control job did not persist an interval RSS sample, so no peak is claimed for it.

These are CPU decoder diagnostics, **not bridge-on Legal IR speed measurements**:
bridge names are `[]`, prover evaluation is false, workers are 1, metric disk cache
is disabled, and sample-memory scoring is unused. Paragraph embedding inputs are
warm cached; the encoder is not executed. A resource-owner compatibility audit
records the historical owner actually used and the newer owner's optional nested
lease additions separately; this campaign does not validate nested leases. The
storage cap is unchanged, all three owned reservations were released, and foreign
claims were preserved. No native family projection or `lake build <Lib>` ran here.
No Lean admission, Constitution round trip, formalization, or distillation-teacher
authority is granted by these results.

### Next controlled quality experiment

The recorded curriculum presents one-, two-, four-, and eight-clause rows 960, 720,
520, and 240 times respectively. Eight-clause rows enter only the last 120 of 340
updates. Full-panel validation CE worsens during the short-only first stage, causing
LR to halve from 0.001 to 0.0005 at epoch 20; it stays there through epoch 80. The
runs complete their budgets, so deadline starvation is not the explanation.

A narrow next experiment should preserve the decoder curriculum and all gates while
comparing current-stage count supervision with balanced, training-only all-length
count supervision from the beginning. Hold update budgets, initial weights, learning
rate policy, and loss coefficients fixed; record confusion matrices, entropy,
actual boundary corrections, and gradient norms. This tests exposure imbalance
without simultaneously changing the optimizer or the stopping formula.

Guidance also needs calibration evidence before rollout. A hypothetical head that
merely learns uniform support on observed counts `{1,2,4,8}` gives a first-rule
stop correction of `log(31/3)`, approximately +2.335, under the current uniform-32
centering. It can therefore strengthen premature closure without learning source
count discrimination. Actual boundary deltas were not recorded in this run, so
that is a mechanism to test, not an established cause. Ordered source-token features
or clause-addressed decoding remain a separate grounding experiment; lower CE,
larger output budgets, or count supervision alone have not solved source fidelity.


## Balanced auxiliary exposure comparison (2026-10-02)

The [balanced-exposure evidence](../implementation/reports/evidence/decoder-count-exposure-20261002/results.json)
tests the curriculum imbalance identified above. The new versioned owner is
[`long_span_count_exposure_training.py`](../../ipfs_datasets_py/logic/formalization/autoencoder/long_span_count_exposure_training.py),
with a frozen-input CLI in
[`benchmark_decoder_count_exposure.py`](../../scripts/ops/autoencoder/benchmark_decoder_count_exposure.py).
Existing owners and the original 8D linguistic teacher remain unchanged. Actual
training remains 384D; missing verified local 768D inputs are not fabricated or padded.

This is a paired, predeclared comparison of `current_stage` and `balanced_all`
auxiliary count supervision at seeds 1729 and 2718. The count coefficient is 0.25,
every-step source conditioning and field-weighted token loss are retained, and
stopping guidance is disabled in every arm. The inherited projection stays frozen;
vector reconstruction MSE is monitored but supplies no gradient to the trainable
decoder and count parameters in this comparison. All four fits use the same 48 training
and 48 previously exposed validation paragraphs, original full targets, decoder
curriculum, initialization, 340 AdamW updates, 2,440 decoder/count row presentations,
and 225,840 target-token presentations. Learning-rate policy and selection gates
are unchanged. Context and output ceilings remain 512, temperature remains 0,
and no encoder or weight download runs.

The control reuses the exact decoder minibatch and projected source for count loss.
The balanced arm draws a count minibatch of the same actual size from all training
lengths, with a private Python RNG and a class cursor that continues across partial
batches, epochs, and stages. It does not change the decoder's Torch shuffle stream
or feed the auxiliary rows' formula prefixes into the decoder. Each class receives
610 labels and exactly 85.0 total `sum(1/count_batch_size)` loss weight. The control
receives 960/720/520/240 labels for 1/2/4/8 clauses; actual loss mass differs slightly
by seed because shuffled 26-row stages end with two-row minibatches. Both label
counts and loss mass are audited, rather than assuming equal counts suffice.

Balanced count supervision reaches the shared source conditioner as well as the
count head. It exposes longer training sources and their count labels earlier;
only the decoder-token curriculum stays the same. Its separate count-source
projection costs additional computation. Matched update and label budgets do not
mean identical wall compute or an isolated head-only ablation.

The completed, **unselected final-attempt** results are:

| Arm / seed | Decoder reference CE | Count CE | Count correct | Eight-clause count recall | EOS | Fit seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| current_stage-1729 | 0.205258 | 1.528737 | 12/48 | 0/12 | 48/48 | 9.335 |
| balanced_all-1729 | 0.268161 | 1.427320 | 13/48 | 1/12 | 48/48 | 9.485 |
| current_stage-2718 | 0.199039 | 1.510180 | 8/48 | 0/12 | 29/48 | 10.789 |
| balanced_all-2718 | 0.203500 | 1.424489 | 15/48 | 2/12 | 24/48 | 10.360 |

Every arm still has **0/48 exact validation paragraphs**, and all selected checkpoints
remain at epoch 0. Both current-stage controls reproduce their published predecessor's
full tensors, Adam state summaries, numerical trajectories, predictions, and existing
controls exactly. Thus the comparison isolates auxiliary exposure rather than another
numerical control drift.

Balancing improved count accuracy by one and seven rows, and recovered one and two
of the twelve eight-clause counts. That improvement is limited: training count
accuracy is only 16/48 and 15/48, versus 15/48 and 14/48 in the controls. Decoder
reference CE worsened at both seeds; seed 2718 also lost five EOS completions.
The result supports a modest count-exposure effect, not faithful longer-span decoding,
convergence, or a qualified teacher. No checkpoint was promoted and no native family
or `lake build <Lib>` validation ran. Empty qualifier targets still do not test
nonempty conditions, exceptions, or temporal semantics. Constitution status is unchanged.

### Diagnostics, optimizer evidence, and next work

Both selected and last-complete states now receive five postfit readouts: conditioned
training/validation, zero-condition validation, and within-length source shuffles on
training/validation. Per-row count logits, probabilities, entropy, and confusion matrices
are retained in the archive; history keeps aggregates. Same-length shuffling preserves
count class, so it cannot test independent count generalization. Fixed hypothetical
count-derived stopping corrections at k=1/2/4/8 are recorded but never applied to
generation or presented as observed decisions at generated rule boundaries.

The existing clipping operation supplies total preclip gradient-norm diagnostics,
without a second gradient calculation or a changed clipping reduction. The report's
`norm_exceeded_limit_steps` counts norms above the configured limit; it does not claim
to count every epsilon-adjusted scaling performed inside Torch. For seed 1729,
current-stage/balanced maximum norms are 100.36/7,599.26, with 127/130 of 340 norms
above the limit of 1.0. For seed 2718 they are 552.48/729.73, with 132/90 exceedances.
The 7,599 peak contributes about 89.8% of that run's sum of norms; removing that one
maximum leaves a mean around 2.55 instead of 24.89. This is evidence of a rare large
excursion, not uniformly larger gradients under balancing.

Pinned source inspection rules out a zero-initialization/L2-normalization singularity
in this path: preprocessing has mean zero and fixed scale one; the inherited projection
is a residual linear/tanh network, initial state is `tanh(condition(source))`, and the
added source residual is a direct linear term. There is no normalization of that
zero-initialized residual. Recurrent gradient amplification and interaction between
token/count objectives remain hypotheses. Aggregate statistics cannot identify the
spiking step, source rows, loss branch, or parameter group.

Before changing optimizer policy, the next diagnostic should capture step/stage/row
IDs, loss components, learning rate, and module-level gradient evidence for large
excursions while retaining a byte-identical control. Any stabilization experiment
must preserve complete sequence targets, source/facet gates, and the original teacher.
Count improvements must continue to be judged separately from ordered clause recovery;
source grounding remains the principal unresolved output requirement.

### Performance, reproducibility, and publication

The four fits took 9.335–10.789 seconds each, including all validation and selection
work; whole arms with persistence/reload and ten postfit readouts took 10.983–14.770
seconds. Final-attempt numerical evaluation of 48 paragraphs took 2.017–15.177 ms/span,
including reference CE, greedy decoding, and integrity/copy checks. Including fidelity,
count-posterior, and hypothetical-boundary scoring, total postfit time was
152.2–783.3 ms per 48-span panel.
The slower panels contain generations that continue to the fixed output limit.
These are observed decoder timings, not a measured bridge-on IR speed improvement:
bridge names are `[]`, prover evaluation is false, metric disk cache is disabled,
workers are 1, device is CPU, and sample-memory scoring is unused. Full paragraph
embeddings are warm cached inputs; no encoder runs.

The guardian took 138.360 seconds including admission, monitoring, and final accounting.
It retained 50,611,816 bytes under its 100 MB reservation; interval-observed peak child
RSS was 705,556,480 bytes. The reservation was released and the storage cap unchanged.
Launcher receipts distinguish cumulative guardian time from launch-return-through-reap
time, which still includes monitoring/accounting latency; isolated child execution
wall time is not inferred. The historical resource owner and current compatible root
admission path are recorded separately; no claim of testing nested leases is made.

A late diagnostic-field rename was caught by the freeze hash before any model started.
The prematurely queued first launcher was interrupted during pre-reservation accounting;
no attempt directory, child, or reservation remained. The corrected launcher validates
all frozen input, source, and plan hashes before admission. This operational receipt is
preserved alongside the successful run.

The frozen-source regression suite passes **646 tests**, and the independent arithmetic,
provenance, sampler, fidelity, replay, and resource audit passes **19,834 checks** with
zero final findings. Prior audit-harness binding/tolerance mistakes are preserved and
corrected without changing model results. The archive contains exact commands,
source snapshots, plans, original inputs, prior control artifacts, all selected/rejected
weights and outputs, sampler snapshots and digests, diagnostic readouts, tests, and audit.
The script uses the same five CLI path arguments as the preceding experiment, under
the existing resource reservation layer; its private exports are not resumable
production checkpoints and confer no qualification or formalization authority.

## Exact gradient-spike replay (2026-10-02)

The [gradient-trace evidence](../implementation/reports/evidence/decoder-gradient-trace-20261002/results.json)
localizes the large gradients without changing the prior four training recipes.
All four fits complete 340 updates, 2,440 decoder/count row presentations, and
225,840 valid target tokens. They reproduce all 80 archived epoch records, four
stage Adam summaries, selected/final parameter tensors, sampler digests, predictions,
and postfit controls from the balanced-exposure comparison. The predecessor did
not save every intermediate step tensor, so this comparison does not independently
establish equality of every one of those tensors. Synthetic 64-step tests separately
verify exact live-update parity with tracing enabled and disabled.

The new versioned owners are `long_span_gradient_trace_training.py` and
`decoder_gradient_replay.py`; the CLI is `benchmark_decoder_gradient_trace.py`.
Tracing is opt-in and records bounded scalar/module metadata after the existing
clip operation. It retains at most two committed events per arm with preclip norm
strictly above 50, ranked by norm with earliest-step tie breaking. Each event holds
cloned pre-update weights, complete Adam state/parameter groups, trainable ordering,
module modes, RNG state, ordered batch IDs and hashes, token-weight/count-target
bindings, and expected post-update digests. Tensor snapshots use tagged JSON that
preserves dtype, shape, dictionary key types, and `None` versus zero gradients;
loading them does not require pickle. An update abandoned at the deadline is saved
as uncommitted and cannot be replayed as successful.

The benchmark writes and reloads each packet before `replay_event(...)` restores
a private model and optimizer. It requires exact loss values, the original clip
norm and clipped-gradient digest, and the post-update weight **and Adam** digests.
Only then does it run separate token/count backward passes on fresh private
copies. Branch sums use declared float32 reconciliation tolerances, with float64
reporting; exact combined-step replay and approximate branch reconciliation are
different checks. All eight retained events pass both. The private diagnostic
updates are explicitly counted and never enter live training or model selection.
RNG restoration and final caller-integrity checks are included in replay timing
and its cooperative deadline.

### What the captured gradients show

| Arm / seed | Steps with norm >50 | Maximum preclip norm | Token-branch norm at maximum | Weighted count-branch norm | Fit seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| current_stage-1729 | 2 | 100.358 | 100.356 | 0.696 | 8.832 |
| balanced_all-1729 | 3 | 7,599.256 | 7,599.257 | 0.313 | 8.681 |
| current_stage-2718 | 4 | 552.476 | 552.476 | 0.706 | 10.331 |
| balanced_all-2718 | 4 | 729.729 | 729.729 | 0.300 | 10.378 |

All 13 steps above 50 occur in `source_le_32`, at epochs 22–29 after the first
curriculum transition. The eight retained steps are a deliberately selected tail,
not representative samples. At the largest event (zero-based step 50, epoch 23),
token-gradient norms are about 6,125.7 in the GRU, 3,619.2 in the source-to-embedding
residual, and 2,669.3 in target embeddings. The weighted count branch is only 0.313;
the frozen projection's reconstruction loss contributes no trainable gradient.
The float64 branch norm differs slightly from the exact float32 clipping norm due
to arithmetic precision, not a changed clip operation.

This identifies where the instantaneous gradient is large. It does not prove a
particular recurrent-Jacobian mechanism or show that count training cannot have
affected the preceding trajectory through the shared conditioner. Near-zero global
branch cosine also reflects largely disjoint parameter groups; the shared-condition
group can have appreciable alignment or conflict. A large event also occurs in a
batch containing only one- and two-clause targets, and later, longer stages have
much smaller maxima. A monotonic relationship between sequence length and gradient
instability is not established.

Source reconstruction is unchanged: **0/48 exact validation paragraphs in every
arm**, selected epoch 0, and no checkpoint promotion. These are previously exposed,
authored development panels; the fresh test is unopened. Conditions, exceptions,
and temporal qualifiers in these targets remain empty. The 8D linguistic teacher
is unchanged, and no actual 768D training ran because verified local inputs are
unavailable. No native family or `lake build <Lib>` validation ran in this numerical
diagnostic; nothing here grants Lean admission or Constitution formalization.

### Cost and reproduction

Detached observation takes 0.068–0.085 seconds per fit, as measured inside the
observer, including snapshot construction and its report. Persisting, reloading,
and replaying the two retained events takes another 0.327–0.357 seconds per arm
outside training. These measured components do not establish a causal wall-time
overhead against earlier runs with different machine load. Full fits, including
validation, achieve 235–281 row presentations/second and 21.8k–26.0k valid target
tokens/second; whole arms including artifacts and all ten controls take 10.66–14.87
seconds. All eight diagnostic replays are additional work, not training progress.

Final-attempt numerical validation takes 1.931, 1.953, 12.310, and 14.666 ms/span
in the table's order. Each panel contains 48 spans. Complete postfit panels, including
that numerical readout and fidelity/count diagnostics, take 149.9–759.8 ms. Device
is CPU, workers 1, bridge names `[]`, prover evaluation false, metric disk cache
disabled, and sample-memory scoring unused. Paragraph embeddings are warm cached
inputs; no encoder executes. No bridge-on evaluation was performed, so these are
not legal-IR bridge timing results.

The guardian completes in 92.267 seconds including admission, monitoring, and
final accounting. It retains 77,131,578 bytes within a 150 MB reservation; observed
peak child RSS is 710,619,136 bytes. The reservation is released and the storage cap
unchanged. Isolated child execution time is not inferred from the monitoring
receipt. Historical resource-owner compatibility is recorded separately from the
currently published optional nested-lease path, which this run does not exercise.

The regression suite passes **736 tests**, and a separate standard-library audit
passes **27,722 checks with zero findings**. The archive includes the sealed recipe,
five original inputs, frozen producers, tests, complete scalar traces, eight tagged
events and replay reports, all selected/rejected states and controls, and the exact
predecessor artifacts required to reproduce the parity checks. Use its
`validation/run_reserved.py --attempt <fresh-name>` in this workspace to invoke
the benchmark under the same reservation layer; do not reuse an existing attempt
directory. The benchmark takes `--dependency-root`, `--extension-root`, `--manifest`,
`--plan`, and `--output`. It authenticates the frozen canonical compiler/decompiler/
parser tree and all extension/input hashes before execution. Replay currently
supports this CPU, frozen-projection, quarter-weight count objective; event packets
are diagnostics, not general production resume checkpoints.

The next proposed stabilization comparison is two seeds with unchanged balanced
exposure versus a fixed learning-rate ramp for the first 20 updates after the first
curriculum expansion. The ramp would scale the existing scheduler rate from 0.1 to
1, preserving Adam moments, full-sequence backpropagation, clipping, and the matched
update/token budgets. It must record actual parameter-update norms and per-length
semantic/count/EOS results as well as gradient tails. This proposal has not run;
smaller spikes alone would not establish better reconstruction or justify promotion.

## First-expansion learning-rate ramp (2026-10-02)

The [paired transition experiment](../implementation/reports/evidence/decoder-transition-ramp-20261002/results.json)
tests that proposal. It reduces the peak gradients, but does **not** improve exact
source reconstruction or produce an eligible checkpoint. The ramp remains an
explicit experimental option; it is not enabled in production or in the prior owners.

`long_span_transition_training.py` adds `transition_schedule="unchanged"` or
`"first_expansion_ramp20"`. The candidate detects the first strict expansion of the
training-ID set and applies `0.1 + 0.9*j/19` for committed updates `j=0..19`.
Here the window is zero-based steps 40–59. The plateau scheduler's base rate is
already 0.0005 at step 40, so the first effective rate is 0.00005. Base and effective
rates are recorded separately; the base is restored after every update and before
the scheduler runs. Adam moments persist throughout. The ramp does not restart at
later stages, truncate targets, detach recurrent state, or change clipping.

The paired benchmark `benchmark_decoder_transition_ramp.py` uses only balanced
count exposure, seeds 1729 and 2718, and the same 48 training/48 exposed validation
paragraphs. Every arm completes 340 updates, 2,440 decoder/count row presentations,
and 225,840 valid target tokens. Encoder context and decoder output limit remain
512, temperature 0, count weight 0.25, and generation count guidance off. The
projection remains frozen. Both unchanged controls reproduce their published
predecessors' scalar gradient streams, epoch records, stage Adam summaries, final
weights, predictions, and postfit controls. Candidate/control results match before
the intervention starts. Later candidate states and Adam moments naturally differ
as their trajectories diverge.

### Quality and optimizer effects

These are **unselected final-attempt** results, not promoted checkpoints:

| Schedule / seed | Reference token CE | Count CE | Count correct | EOS | Syntax-valid | Peak preclip norm | Fit seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unchanged-1729 | 0.268161 | 1.427320 | 13/48 | 48/48 | 48/48 | 7,599.256 | 9.426 |
| ramp20-1729 | 0.202653 | 1.424621 | 15/48 | 20/48 | 20/48 | 242.007 | 10.178 |
| unchanged-2718 | 0.203500 | 1.424489 | 15/48 | 24/48 | 24/48 | 729.729 | 10.506 |
| ramp20-2718 | 0.273304 | 1.429722 | 15/48 | 48/48 | 46/48 | 80.905 | 8.991 |

All four arms have **0/48 exact validation paragraphs**, all 180 reference rules
missing, and selected epoch 0. Training-panel exact paragraph recovery is also
zero. At seed 1729 the ramp lowers teacher-forced CE while reducing successful
sequence termination; seed 2718 changes those measures in the opposite directions.
Two seed-2718 candidate outputs terminate but are still not syntax-valid. Reducing
the gradient tail therefore does not establish better generated semantics.

The source-fidelity gate rejects every evaluated checkpoint in both candidate
runs for `baseline/length=8/modality regressed`, with other field and syntax
regressions at some epochs. This is a substantive per-length semantic check;
aggregate loss or global field totals cannot override it. No gate was relaxed.

The new diagnostic records actual parameter differences around every committed
optimizer step. Detached float32 snapshots are subtracted and accumulated in
float64, reporting per-module/global/trainable-only update norms, pre-update
parameter norms, and update-to-parameter ratios (`null` for a zero denominator).
These are measured changes in weights, not gradient norms multiplied by a nominal
learning rate. At the first ramp update, the trainable update norm falls from
approximately 0.04242 to 0.00424 for seed 1729 and 0.04228 to 0.00423 for seed 2718.
Across all 20 ramp updates, the sum of update norms falls from 0.79477 to 0.51265
and from 0.80446 to 0.51049 respectively. Those sums measure update path length,
not net parameter displacement. The overall reduction is not 90% because the
factor rises and subsequent gradients/moments change.

The original 7,599 gradient at step 50 produces an actual trainable Adam update
norm of about 0.04264, comparable to other transition updates under the existing
clipping. It does not produce a comparably exceptional weight jump. All 20 ramp
steps still exceed the clipping threshold. Over steps 60–339, summed update path
length increases from 6.047 to 6.107 and from 5.770 to 6.169; seed 2718's full-run
clipping-threshold exceedances also increase from 90 to 139. Smaller peak gradients
are therefore neither uniformly smaller subsequent updates nor evidence of more
efficient semantic learning.

Peak gradients fall by about 96.8% and 88.9%. For seed 2718, the candidate's
remaining maximum occurs at step 62, after the ramp ends. All eight retained
exceptional steps replay exactly, including their effective learning rates and
Adam state; separate loss-branch gradients reconcile. Capture happens before
restoring the scheduler base rate. The independent audit checks delta arithmetic,
frozen-zero movement, and captured pre-state norms. It does not reconstruct every
parameter delta independently from a post-state hash: the full measurement path
is also covered by source review, known-delta tests, and unchanged-control parity.

### Source grounding remains the gap

The sampled permission “The registrar is allowed to preserve the archive.” has
target actor `registrar`, action `preserve`, modality `P`, and object `archive`.
The unchanged seed-1729 model instead emits `deliver`, modality `F`, and `notice`.
The ramped seed-2718 model emits `publish`, modality `F`, and `notice`. The ramped
seed-1729 output repeats clauses and reaches the fixed output limit. These examples
are preserved with the complete expected and generated structured documents in
the archive; none counts as formalization.

Same-length source shuffling raises validation token CE by only about 0.0042–0.0048
in these final states, while zeroing source conditioning raises it much more.
That is evidence that conditioning affects the decoder, but it does not establish
correct binding of actor/action/modality/object or clause order. Same-length
shuffles preserve count class and cannot establish count generalization. The next
diagnostic should examine loss and source dependence at the meaningful field and
clause positions, separating correct-prefix prediction from free-running generation,
before another optimizer setting is promoted. Lower punctuation/structural loss
must not stand in for source-grounded rule recovery.

Concretely, that diagnostic should keep the existing weights fixed and measure
semantic-value token accuracy/log probability and stop-versus-continue errors by
rule position, under correct, within-length shuffled, and zeroed sources. It should
also locate the first divergence in the already generated outputs. Reference
prefixes belong only to the diagnostic; they must not enter normal generation or
qualification. This would separate failure to identify source values with a correct
prefix from errors that emerge during free generation. It has not yet run.

### Cost, scope, and reproduction

Fits take 8.991–10.506 seconds including the unchanged validation/selection work,
or 232–271 row presentations/second and 21.5k–25.1k valid target tokens/second.
Whole arms including persistence, exact replay, and ten postfit controls take
11.14–14.94 seconds. Update observation takes 0.094–0.105 seconds per fit and
gradient observation 0.067–0.145 seconds. Packet persistence/reload/replay adds
0.337–0.357 seconds per arm outside training. These component measurements do not
isolate causal overhead from machine-load differences.

In table order, numerical final-attempt evaluation takes 1.879, 14.344, 14.367,
and 2.026 ms/span on 48-span panels. Total postfit panels including that numerical
readout and fidelity/count diagnostics take 145.6–742.3 ms. Timing differences
partly reflect whether generation terminates or runs to the fixed output limit;
faster incorrect termination is not a qualified inference speed improvement.
Device is CPU, workers 1, bridge names `[]`, prover evaluation false, metric disk
cache disabled, sample-memory scoring unused, and full paragraph embeddings warm
cached. No encoder or bridge-on evaluation runs; these are not legal-IR bridge
timing results.

The guardian takes 86.654 seconds including admission, monitoring, and accounting.
It retains 92,424,376 bytes within a 200 MB reservation and releases the reservation;
interval-observed peak child RSS is 708,808,704 bytes. The 140 GB shared cap is
unchanged. Monitoring time is not presented as isolated child execution time.
Historical resource-owner compatibility and the unexercised newer nested-lease
path remain explicitly distinguished.

The full focused suite passes **794 tests**; the independent audit passes
**91,977 checks with zero findings**. The archive retains all scalar/update streams,
eight event packets and exact replays, selected/rejected states, original inputs,
source snapshots, tests, resource receipts, and raw predecessor dependencies.
The CLI uses the same five path arguments and frozen canonical-tree authentication
as the preceding experiment. Its archived guardian invokes it under the existing
reservation layer with a fresh attempt name; original workspace paths and the
shared dependency export are required, or must be restored using the archive's
original-path mapping. The evidence bundle is not a standalone installed runtime.

Only 384D numerical development training ran. The 8D linguistic teacher is
unchanged; verified local 768D inputs remain unavailable. These authored panels
are already exposed, the fresh test is unopened, and qualifier lists are empty.
No native family or `lake build <Lib>` qualification, checkpoint promotion,
distillation-teacher qualification, or Constitution formalization is claimed.

## Fixed-state source-value and boundary diagnostic (2026-10-02)

The follow-up to the transition-ramp experiment now runs in
`scripts/ops/autoencoder/benchmark_decoder_prefix_diagnostics.py`, using the
separate `decoder_prefix_diagnostics.py` numerical owner. It diagnoses the
existing 384D states without training, new generation, or weight selection.
The published evidence is in
`docs/implementation/reports/evidence/decoder-prefix-diagnostics-20261002/`.

Five numeric states are evaluated: the common selected epoch-zero baseline once,
then the four final rejected states. Before deduplication, all four selected
exports must have identical numeric states and match the predecessor's selected
tensor hashes. Each state receives the existing 48 training and 48 validation
rows under conditioned, within-length source-shuffle, and zero-condition controls:
30 forward-only panels. These are previously exposed authored development rows;
the fresh test remains unopened. Real local paragraph embeddings are reused, with
9–72 source tokens, fixed 512-token encoder context and decoder output limit.
The paragraph targets contain one, two, four, or eight complete rules.

The owner traverses each canonical reference document and annotates its tokens
by structural position. Actor, action, modality, and object values are distinct
from field keys, punctuation, empty qualifier lists, outer rule boundaries, and
EOS. The codec represents each quoted scalar value as one token. Every panel
contains 6,228 predicted positions, including 720 scalar values, 180 outer rule
boundaries, and 48 EOS positions. Conditions, exceptions, and temporal lists are
empty in this corpus, so their semantic coverage remains untested. Separate unit
tests exercise nonempty qualifier atoms, escaping, and key/value collisions.

The diagnostic supplies correct reference prefixes only for conditional
prediction. Full 32-way float32 logits, target log probabilities, strict-greater
ranks, first-tie argmax, and stop-versus-continue probabilities are retained for
every position. Ordinary free generation does not receive these prefixes.
Existing greedy outputs are read from 25 authenticated predecessor panels;
training/zero-condition generation was never recorded and is explicitly absent
for all five states. First-divergence analysis uses only actually emitted tokens
and explicit EOS receipts. It never invents EOS for output-limit failures.

### The semantic values still fail under correct prefixes

Validation results below use the ordinary source inputs. Each field has 180
reference values. “Continue” has 132 required decisions and “stop” has 48.
Boundary correctness means full-vocabulary argmax, not merely a binary choice.

| Final rejected state | Actor correct | Action correct | Modality correct | Object correct | All values | Continue | Stop |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unchanged, seed 1729 | 32 | 39 | 59 | 87 | 217/720 | 0/132 | 48/48 |
| ramp20, seed 1729 | 33 | 36 | 59 | 89 | 217/720 | 80/132 | 20/48 |
| unchanged, seed 2718 | 35 | 39 | 59 | 87 | 220/720 | 67/132 | 23/48 |
| ramp20, seed 2718 | 34 | 37 | 59 | 87 | 217/720 | 0/132 | 48/48 |

All four final states predict all 2,892 ordinary punctuation tokens and all 1,080
empty-qualifier tokens correctly under reference prefixes. Their overall token
accuracy is about 89.5–90.6%, but scalar-value accuracy is only 30.1–30.6%.
Training value accuracy is also poor: 272–285/720, or 37.8–39.6%. The common
epoch-zero baseline has 59/720 correct validation values and 72/720 training
values. Training clearly changes conditional predictions, but those changes do
not establish faithful source reconstruction or convergence.

The modality predictions reveal a specific collapse: every final state predicts
`F` at all 180 modality sites in both splits, despite training references containing
59 permissions, 66 prohibitions, and 55 obligations. Validation contains 65
permissions, 59 prohibitions, and 56 obligations. The reported modality accuracy
therefore comes entirely from predicting prohibition everywhere. This is a
failure to discriminate the source modality even under correct target prefixes.

In the four archived ordinary validation panels, 47–48 of 48 first divergences
occur at the action or actor value; the remaining cases are modality errors.
The first mismatch arrives after an average of 8.25–8.54 matching tokens. All
four still have zero exact validation paragraphs. Thus most observed failures
begin before a rule boundary, and poor value predictions persist even when the
preceding target tokens are supplied correctly. Count or EOS repairs alone cannot
explain away these failures.

Source conditioning does affect the model. Within-length source shuffling reduces
validation value correctness from 217–220 to 206–211/720 and raises semantic-value
negative log probability by 0.0370–0.0416. The corresponding training penalty is
larger, 0.1190–0.1364. Zero conditioning raises validation value loss from about
1.298–1.315 to 1.897–2.704 and reduces correct values to 12–187/720. These controls
show source sensitivity without proving correct association of each source clause
with its values. Same-length shuffles preserve the count labels and cannot test
source/count generalization. Reference-prefix conditioning can also expose useful
information from preceding target values; this remains a conditional diagnostic.

The next optimizer experiment should explicitly test source-to-value binding,
while retaining the existing semantic and boundary gates. It should keep the
current failed states as controls, measure value and clause-position losses
separately, and report the same source-shuffle comparison and target-free exact
reconstruction. Simply increasing the output budget or choosing the lower global
token CE is unsupported by this evidence. The production training policy and all
qualification thresholds remain unchanged.

### Reproduction and cost

The CLI takes `--dependency-root`, `--extension-root`, `--manifest`, `--plan`, and
`--output`. The archived freeze script authenticates the predecessor public
manifest/results against the pinned Git commit, binds 41 input artifacts and 20
extension sources, and verifies the focused test receipts. It retains the
canonical compiler/parser/decompiler tree check against the existing frozen
workspace export. The benchmark verifies each saved state role, tensor inventory,
numeric hash, original source assignment, and predecessor archive member before
executing a panel. All 25 available historical native token-CE values reproduce
exactly. The five unavailable generation panels receive new prefix diagnostics
only, with no generated prediction fabricated.

The 30 diagnostic calls take 7.214 seconds total, or 4.13–6.15 ms per span per
panel. Including compact raw-logit serialization, the panel total is 10.006
seconds; the comparison including state construction takes 10.176 seconds.
These are forward-only diagnostic timings, not target-free inference or training
throughput. The resource guardian takes 45.572 seconds including admission,
monitoring, and accounting. It retains 218,267,544 bytes within its 300 MB
reservation and releases the reservation. The shared 140 GB cap is unchanged;
a peak RSS measurement was not retained for this short run.

Device is CPU, workers 1, bridge names `[]`, prover evaluation false, and metric
disk cache disabled. Full paragraph embeddings are warm cached; sample-memory
scoring and encoder execution are unused. No bridge-on evaluation was performed,
so no bridge-on timing improvement is claimed. The focused suite passes 837 tests;
the independent arithmetic/provenance audit passes 392,488 checks with zero findings.
The evidence retains all 186,840 prediction positions and 5,978,880 logit values,
original references and inputs, saved states, prior outputs, source snapshots,
test receipts, and reservation accounting for arithmetic and provenance review.

The 8D linguistic teacher is untouched; verified local 768D inputs remain
unavailable. This diagnostic performs no training, native family validation, or
`lake build <Lib>`. It grants no admission, checkpoint promotion, source-semantic
qualification, or Constitution formalization. The archive is a development
evidence bundle with original-path mappings, not a standalone installed runtime.

## Frozen-source slot probes (2026-10-02)

The next diagnostic tests source information without any reference prefix. The
runner is `scripts/ops/autoencoder/benchmark_decoder_source_slot_probe.py`; its
small numerical owner is `decoder_source_slot_probe.py`. Evidence lives in
`docs/implementation/reports/evidence/decoder-source-slot-probe-20261002/`.
It fits separate diagnostic readouts while preserving all encoder, projection,
autoregressive decoder, and count-head weights. The existing decoder training
policy, lineage loading, output limits, and qualification gates are unchanged.

### What is fitted and how to use it

The numerical owner exposes three functions rather than requiring callers to
navigate the production autoencoder class:

- `fit_probe(feature_rows, references, feature_specification=..., ...)` accepts
  training features and complete reference documents only. It returns a `probe`
  and a fit `report`, including coefficients, training matrices, and normalization.
- `predict_probe(probe, feature_rows, ...)` accepts no references, source text,
  prefix tokens, or rule-count labels. It returns raw scores and all predicted
  slots plus an independent predicted count. Scores are not probabilities.
- `evaluate_probe(probe, feature_rows, references, source_features=..., control=...,
  ...)` scores those unmasked predictions and validates source assignments. It
  reports present-value, absent-slot, count, class-recall, and complete scalar-slot
  metrics separately. It does not construct or validate generated formulas.

A feature row has exactly `id`, `source_sha256`, and `features`. A feature
specification identifies the kind, dimension, and provenance. The CLI has the
same five path arguments as the previous diagnostic: `--dependency-root`,
`--extension-root`, `--manifest`, `--plan`, and `--output`. Its authenticated
source-only extractor receives source vectors and identities, with no target or
text fields. It extracts the actual projected 384-vector, initial hidden state
of width 32, and persistent source-to-token residual of width 16. It never calls
`next_logits`. Original weights, gradients, modes, trainability, inputs, and RNG
are checked for mutation. The inherited input transform remains unchanged.

There are seven probes: one shared projected-384 readout, five conditioning-48
readouts for the previously saved states, and an intercept-only baseline. All
five projected-feature arrays must match, including their serialized hashes,
before the shared probe is fitted once. The projection's width-eight residual
branch is not an eight-dimensional bottleneck: its output remains 384-dimensional.
This experiment does not involve the separate historical 8D linguistic teacher.

The predeclared protocol uses float64 ridge regression with fixed `lambda=0.001`:
sum of squared one-hot errors across output heads, divided by the 48 training
rows, plus lambda times the squared coefficient norm. The intercept is
unpenalized. Feature means and one scalar RMS centered-row norm are computed from
training rows alone, making mean training row squared norm one for nonconstant
features. Constant/intercept features use scale one. The dual solve adds
`48 * 0.001` to the Gram diagonal. No validation-based regularization tuning or
checkpoint selection occurs. Normal-equation residuals certify this fixed convex
readout objective only; they do not establish an autoencoder's global optimum.

Each probe predicts eight ordered slots for actor, action, modality, and object,
including a structural `ABSENT` class, plus an independent count in 1–8. Value
inventories come from training references only; unseen validation values would
be recorded as out-of-inventory errors. Counts never truncate or mask the slot
predictions. Complete scalar-slot/count exactness therefore requires all 32 scalar
decisions, including absence beyond the actual rules, and the independent count
to match. Present-value accuracy uses the reference-present positions only and
is explicitly a conditional metric. Conditions, exceptions, and temporal
semantics remain unscored; these probes are not formula decoders.

Four controls run on both the existing 48 training and 48 exposed validation
rows, giving 56 panels. Within-length shuffling tests value associations while
preserving count labels. Cross-length shuffling sorts by count and identity,
then rotates by 12 rows; every assigned vector comes from a different count
class. It tests count association as well. The zero-feature control sets
normalized features to zero, equivalent to supplying the training feature mean.
It is an intercept-prior control, distinct from the historical zero-source
autoregressive decoder wrapper. No control changes the labels or original source
identities. All controls are evaluated after the fits, without refitting.

### Results: source information is accessible, but longer spans still fail

Each split has 720 present scalar values, 816 absent scalar slots, and 48 counts.
The same fixed recipe is used for every representation; none is selected for
deployment from these results.

| Probe features | Training values /720 | Validation values /720 | Validation count /48 | Validation scalar slots + count exact /48 |
| --- | ---: | ---: | ---: | ---: |
| Shared projected 384 | 608 | 281 | 38 | 6 |
| Selected epoch-zero conditioning 48 | 229 | 127 | 17 | 0 |
| Unchanged 1729 conditioning 48 | 241 | 130 | 20 | 0 |
| Ramp20 1729 conditioning 48 | 262 | 143 | 23 | 0 |
| Unchanged 2718 conditioning 48 | 264 | 141 | 21 | 0 |
| Ramp20 2718 conditioning 48 | 246 | 139 | 20 | 0 |
| Intercept only | 111 | 98 | 12 | 0 |

The projected-source probe reaches 39.0% present-value accuracy and 79.2% count
accuracy on exposed validation, compared with 17.6–19.9% values and 35.4–47.9%
counts from conditioning features. It recovers 28/59 prohibitions, 19/56
obligations, and 30/65 permissions, rather than predicting prohibition everywhere.
Nevertheless, its 608/720 training values versus 281/720 validation values show
a substantial development gap. Its six exact scalar/count matches are all
single-rule spans. The breakdown is 44/48 correct values for single rules,
48/96 for two rules, 70/192 for four rules, and 119/384 for eight rules. There are
zero exact multi-rule validation paragraphs and zero full Legal-IR qualifications.

For the projected-source probe, within-length shuffling reduces validation value
correctness from 281 to 210 while count correctness remains 38. Cross-length
shuffling reduces values to 119 and counts to 3; normalized-zero features give
the baseline 98 values and 12 counts. All zero-feature panels reproduce the
intercept-only predictions. No validation target falls outside the fitted value
inventories. These controls support a real association between projected features
and source labels, not faithful recovery of every ordered clause.

The lower conditioning-feature result is evidence about this linear readout,
with different feature dimensions and coefficient counts. It does not prove
that conditioning has irreversibly discarded all useful information: nonlinear
readouts, different regularization, and the autoregressive dynamics were not
tested here. The preceding prefix diagnostic also supplied gold prefix tokens
and had no `ABSENT` prediction heads, so its 30% value accuracy is not a directly
comparable reconstruction benchmark. No inference improvement is claimed for
the unchanged autoregressive decoder.

The supported next training experiment is a source-value supervision path that
retains access to the projected 384-vector, compared against the existing
conditioning path. It should train only on training rows, preserve all existing
source-fidelity and boundary gates, and measure both source-only class recall and
target-free formula reconstruction by span length. The probe's outputs are
diagnostic candidates, not automatically accepted teacher labels or replacement
formalization targets. Longer-span and qualifier coverage remain open gaps.

### Validation, provenance, and cost

All original input/state artifacts are bound to the previously published prefix
archive's member hashes. The freeze authenticates that public manifest/results
against Git, pins 16 inputs and 22 extension files, and preserves the canonical
frozen compiler/parser/decompiler tree. Ten feature-extraction records, seven
full fit records, and all 56 raw-score panels are retained. The 878-test suite
passes, including tests for source-only extraction, immutable model state,
training-only normalization, absent slots, unknown classes, control assignments,
and deadline failures. The independent audit passes 6,389 checks with zero
findings, recomputing scores and metrics and verifying the ridge normal equations
without another fit or neural forward. No pretrained weights were downloaded.

The seven fit calls take 0.346 seconds total; the ten source-only extractions take
0.186 seconds. The 56 evaluation calls take 4.616 seconds, including validation,
scoring, hashes, and report construction, or 1.04–4.91 ms per span per panel.
Panel time including serialization is 5.102 seconds; the full comparison takes
6.121 seconds. These are small diagnostic readout costs, not production decoder
training or autoregressive inference throughput. The guardian takes 45.637
seconds including admission, monitoring, and accounting, and retains 41,821,340
bytes within its released 100 MB reservation. The shared 140 GB cap is unchanged;
no peak RSS observation was retained for this short run.

Device is CPU, workers 1, bridge names `[]`, prover evaluation false, and metric
disk cache disabled. Paragraph embeddings are warm cached; encoder execution and
sample-memory scoring are unused. No bridge-on evaluation was performed. The 8D
teacher remains unchanged and verified local 768D inputs remain unavailable.
No decoder weights were trained or promoted, no new formula generation or native
family/Lake validation ran, and no span received admission or `roundtrip_ok`.
The Constitution remains unformalized.

## Causal source-value supervision (2026-10-03)

The source-value continuation completed after the workstation restart. Its
evidence directory is
`docs/implementation/reports/evidence/decoder-source-value-training-20261002/`;
the directory retains the experiment's original preparation date. Both unchanged
control fits exactly reproduce their historical final tensors, validation
history, exposures, and checkpoint-selection decisions. All six fits complete,
but every selected state remains epoch zero. No candidate improves accepted
formula reconstruction, and no production default or checkpoint is promoted.

### Model, training, and replay interfaces

The implementation is deliberately separate from the existing model owners:

- `source_value_decoder_experiment.bind_source_value_model(model, codec=...,
  feature_kind=..., max_rules=8, guidance=True)` privately copies the inherited
  cardinality decoder. `projected_source` reads the actual projected 384-vector;
  `inherited_conditioning` concatenates its initial hidden state of width 32 and
  persistent source-embedding residual of width 16. Neither path changes the
  encoder representation, context, or original checkpoint.
- `model.source_value_logits(projected)` returns raw scores shaped
  `[batch, 8, 4, vocabulary]`. Fields are actor, action, modality, and object, in
  that order. These are source-only predictions, without prefix or reference
  arguments. The new linear head starts at zero, preserving inherited decoder
  logits exactly. Its full-vocabulary outputs receive no legal-value mask.
- During autoregressive decoding, only the actual consumed prefix can identify
  a scalar-field colon and select its ordered rule slot. The corresponding
  source scores are added to the decoder logits. A strict lexical recognizer
  tracks real prefixes and is checked against the existing cardinality
  recognizer. An invalid prefix disables this guidance permanently. Slots beyond
  eight receive no residual; generation is neither truncated nor forced to
  close. The recognizer is not a semantic validator.
- `reference_source_values(...)` authenticates the complete reference document
  against its numerical target tokens before preparing auxiliary labels.
  Present scalar slots contain actual inherited vocabulary IDs; absent slots
  are ignored by this auxiliary loss. Conditions, exceptions, temporal fields,
  syntax, and termination still receive the unchanged full sequence loss.
- `long_span_source_value_training.train(...)` adds
  `source_value_weight=0.25` on the same decoder training batch, with no extra
  examples. It trains the inherited decoder and count head jointly with the new
  head, while the source projection remains frozen. It returns selected and
  last-complete states separately. Source-head metrics cannot select a state:
  the existing per-length, per-facet source-fidelity guards and reconstruction
  guards must still pass before fidelity or reference CE can rank a candidate.
- `bind_zero_condition_model(...)` removes the initial recurrent source,
  persistent source input, count-head source features, and scalar-head source
  features. Learned head biases remain source-independent priors. The original
  projection and generated-prefix history remain available for their respective
  reconstruction and causal-decoding roles.

The runner is `scripts/ops/autoencoder/benchmark_decoder_source_value_training.py`.
Like the preceding experiments, it takes `--dependency-root`, `--extension-root`,
`--manifest`, `--plan`, and a fresh `--output` directory. It authenticates the
frozen canonical parser/compiler/decompiler tree, donor, cached embeddings,
complete targets, predecessor evidence, and extensions before running. The
sealed recipe, private state exports, actual generated token IDs and IR,
per-update losses/exposures, and raw source/count logits are retained for replay
and arithmetic review. Private development exports are not production lineage
checkpoints or optimizer-resumable states.

The paired recipe has unchanged, conditioning-48, and projected-384 arms, each
with seeds 1729 and 2718. Every fit uses the same 48 training and 48 exposed
validation paragraphs, complete outputs of at most 512 tokens, temperature zero,
and four cumulative source-length stages of 20 epochs each. There are 340
optimizer updates, 2,440 decoder-row presentations, 225,840 target-token
presentations, and 2,440 balanced count-row presentations per fit. Each candidate
adds 25,600 present scalar labels from those same decoder batches. Count loss
weight remains 0.25; count boundary guidance remains off. AdamW, semantic-field
sequence loss, reconstruction loss, clipping at norm one, and the plateau
scheduler retain the prior recipe. Learning rate starts at 0.001 and ends at
0.0005 in all six fits. No gradient packets or per-update parameter snapshots are
added; compact update receipts retain the actual losses and committed exposure.

Selected and last-complete states each receive five post-fit panels: conditioned
training and validation, within-length source shuffles of both splits, and a
zero-source validation control. This yields 60 panels, each containing 48
paragraphs. Shuffles preserve reference identities and targets and alter only
the assigned source vectors. Neither controls nor validation labels train the
model. Validation has already been used repeatedly for development; the fresh
test remains unopened.

### Results: source readouts improve locally, but generation does not qualify

The following table reports **unselected final attempts**, not the epoch-zero
states retained by the gates. Exactness requires a complete ordered reference
document and EOS; the source-head column measures only reference-present scalar
slots. Each validation panel contains 180 reference rules and 720 scalar values.

| Arm / seed | Validation sequence CE | Validation EOS / syntax /48 | Validation exact /48 | Training exact /48 | Source head training /720 | Source head validation /720 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Unchanged /1729 | 0.268161 | 48 /48 | 0 | 0 | — | — |
| Conditioning48 /1729 | 0.228970 | 38 /38 | 0 | 1 | 324 | 228 |
| Projected384 /1729 | 0.209414 | 35 /35 | 0 | 3 | 379 | 245 |
| Unchanged /2718 | 0.203500 | 24 /24 | 0 | 0 | — | — |
| Conditioning48 /2718 | 0.272654 | 48 /48 | 0 | 2 | 327 | 224 |
| Projected384 /2718 | 0.202612 | 17 /17 | 0 | 2 | 377 | 248 |

Every one of the 20 validation checkpoints in every fit fails at least the
unchanged eight-rule modality guard. Other length/facet, EOS, and syntax
regressions also occur. Every selected state remains epoch zero with zero exact
training and validation paragraphs. The final candidates recover one to three
training paragraphs, all single-rule cases; no multi-rule training or validation
paragraph is exact. No complete validation reference rule is preserved in any
final attempt: all 180 remain missing under exact whole-rule matching.

Projected-source heads reach 34.0–34.4% validation scalar accuracy, versus
31.1–31.7% for conditioning heads. This small readout advantage does not transfer
to faithful generated documents. For projected-384, the 1/2/4/8-rule validation
bins recover respectively 28/48, 32/96, 63/192, and 122–125/384 scalar values.
Conditioning recovers 16–19/48, 31–32/96, 60–63/192, and 115–116/384. Longer-span
ordered binding remains weak, and all candidates have a substantial training
versus validation gap.

Controls constrain the interpretation. Conditioning-head validation scores are
228 and 224 with the real source, 229 and 229 after within-length shuffling, and
223 and 224 with zero source features. Projected-head scores are 245 and 248,
falling to 227 and 229 when shuffled and 231 and 229 when zeroed. The projected
heads therefore show some source association beyond their biases, while the
conditioning-head validation accuracy does not improve over these controls.
The heads predict all three modalities; projected-head recall is 22–24/59 for
prohibition, 9–10/56 for obligation, and 33–37/65 for permission. Generated IR
still loses rule identity and count, despite these nonconstant source readouts.
These scores cannot be compared directly with the earlier ridge probe: its
feature states, fitted objective, class supports, absent-slot supervision, and
count-exactness task differ.

A concrete validation example is “The registrar is allowed to preserve the
archive.” For `projected384-1729`, the source head predicts registrar, preserve,
prohibition, and archive: three scalar values are correct, but modality is not.
The actual generated IR is:

```json
{"rules":[{"action":"deliver","actor":"registrar","conditions":[],"exceptions":[],"modality":"F","object":"notice","temporal":[]}]}
```

Thus even a source-head preference for the correct action and object can be
overcome by the combined autoregressive logits. For the same source,
`projected384-2718` repeats clauses until its 511-content-token limit, without
EOS. An eight-rule validation example beginning with the registrar's prohibition
on preserving a notice also becomes the single wrong rule shown above under
`projected384-1729`; all eight complete reference rules are missing. Raw examples
are retained under the corresponding arm's
`last-attempt/evaluation-validation.json`, including identities, expected IR,
actual tokens, parse errors, and generation status. No corrected or reconstructed
reference text is substituted for these outputs.

The useful next diagnostic is to separate the source residual's scalar margins
from inherited decoder margins at actual first greedy divergences, while also
retaining the rule-boundary failures. The current evidence does not justify
raising output/context limits, weakening the guards, treating readout scores as
teacher qualification, or promoting either new architecture. A controlled
readout-only fit with inherited weights frozen, followed by separate
auxiliary-only and generation-residual activation arms under the same gates,
could isolate the joint-training interaction. Those experiments have not run.

### Cost, validation, and restart recovery

Trainable parameter counts are 25,888 for the unchanged control, 76,064 for
conditioning-48, and 420,128 for projected-384. The larger head changes both
source access and parameter capacity; this comparison cannot isolate dimensional
information from capacity. Fit calls take 8.814/10.274 seconds for the unchanged
seeds, 9.771/9.320 for conditioning, and 11.315/12.339 for projected-384. The
larger source head does not provide a training-throughput improvement.

The six fit calls total 61.833 seconds. Post-fit persistence, reloads, evaluation,
and evaluation-file writes total 23.771 seconds. Final-attempt conditioned
validation calls take 3.06–18.87 ms per span, including numerical evaluation,
fidelity scoring, count/readout diagnostics, and control construction, but
excluding output-file writes. Output-limit loops materially affect these times;
they are not equal-length generation throughput. Device is CPU, workers one,
bridge names `[]`, prover evaluation false, and metric disk cache disabled.
Paragraph embeddings are warm cached; no encoder execution or sample-memory
scoring occurs. No bridge-on evaluate or faster legal-IR admission is claimed.

All 969 focused tests pass in 21.71 seconds. The independent audit passes 50,190
checks with zero findings over 136 raw artifacts. It recomputes raw source-head
affine/tanh scores from saved tensors, control assignments, objective arithmetic,
exposure counts, formula fidelity, strict selection decisions, provenance, and
state hashes without another training or generation run. Maximum independent
source-logit discrepancy is at most 3.58e-6. Historical unchanged-arm state and
gate parity also passes for both seeds.

The reboot replaced the ephemeral `/tmp/pytest-of-barberb` root inode and the
first admission refused that stale identity. Recovery updated only this identity
under the existing ledger lock and atomic writer, preserving all 368 reservation
records and retained claims and the shared 140 GB cap. The admitted guardian takes 189.212 seconds
including resource admission, monitoring, and final accounting. Peak polled RSS
is 915,525,632 bytes across five observations, within the 4 GiB memory reservation.
It retains 151,799,237 bytes, releases its 400 MB storage reservation, and ends
with total charged storage of 103,704,901,762 bytes under the unchanged cap.
The monitoring maximum is an observed sample, not an exact allocator peak.

The 8D linguistic teacher is untouched; verified local 768D inputs remain
unavailable. No weights were downloaded, encoder context increased, or Mathlib
imported. This exposed development experiment performs no native family
qualification or `lake build <Lib>`, and grants no admission, proof authority,
source-semantic qualification, or Constitution formalization. Its small authored
corpus has empty qualifier fields; it does not establish coverage of real legal
exceptions, temporal semantics, or all supported logic families.

## Actual-prefix attribution and frozen inherited decoder (2026-10-03)

The next two bounded experiments complete under the unchanged acceptance gates.
First, actual greedy replay identifies how inherited and source-head logits
combine at the earliest errors. Second, a controlled fit freezes the inherited
decoder, count head, and projection and trains only the new source head. Neither
experiment produces an accepted reconstruction improvement: all four new fits
select epoch zero and reconstruct zero complete validation paragraphs. Evidence
is in `docs/implementation/reports/evidence/decoder-source-value-margins-20261003/`.

### Actual greedy-prefix diagnostic

`decoder_source_value_margins.trace_predictions(...)` accepts the private model,
rows, references, codec, inherited input transform and lineage, authenticated
expected predictions, validator, and optional original rows/source assignments.
The target-free rollout helper receives only the model and source tensor. It
follows the original greedy policy, including stepping inactive batch members,
and must reproduce saved content tokens, stopping status, and EOS exactly.
References identify the first divergence only after a complete batch rollout;
they never supply prefixes or decisions to generation.

At every actual step, the owner checks that inherited logits plus the causal
source residual equal the combined logits exactly and that inherited recurrent
states match. Compact events retain consumed/emitted tokens, grammar context,
active or inactive guidance reasons, and component winners. Raw float32 vectors
are retained at the first divergence, first scalar site, and first rule boundary,
with duplicate captures merged. This distinguishes invalid-prefix or beyond-slot
inactivity from a zero or unhelpful active head without retaining full raw logits
at every step. The private copy preserves caller tensors, gradients, trainability,
modes, and RNG; cooperative deadlines include final integrity checks.

The runner `benchmark_decoder_source_value_margins.py` has the same five path
arguments as the preceding runners. It replays 18 authenticated panels: four
unselected final candidate states on training and validation, each with actual
and within-length shuffled sources, plus conditioned training/validation for one
representative zero-head epoch-zero state. All 864 row replays match. The archive
retains 134,456 emitted-step events and 1,971 deduplicated raw captures. Independent
numeric decomposition is verified at those retained captures; the remaining
steps have independent grammar/source metadata checks and the pinned owner's
decomposition assertion, not an independent recurrent-model rerun.

Across the four final candidate states' 192 conditioned validation rows, every
first error is a scalar value: 140 actions and 52 actors. The source head alone
prefers the reference value in 34 cases but the combined decoder emits another
value. In 24 cases the inherited decoder alone prefers the correct value but
the residual changes that choice. Both component winners are wrong in the other
134 cases. The initial zero head has a uniform vocabulary tie; its deterministic
PAD argmax is not a learned preference. These counts concern first divergences,
where all earlier generated tokens match the reference, rather than a score
computed by aligning references after an already divergent prefix.

For “The registrar is allowed to preserve the archive,” the projected-384 seed
1729 head prefers `preserve`, the inherited decoder prefers `publish`, and their
sum emits `deliver`, which is neither component's winner. At this first action
site, the `preserve` minus `deliver` margins are -1.410049 inherited, +0.766215
source, and -0.643834 combined. Conversely, for “The treasurer is allowed to
deliver the archive,” projected-384 seed 2718 has a correct inherited `deliver`
preference; its +0.409979 margin against `approve` is overturned by the source's
-0.426259 margin, leaving -0.016280 combined. A larger residual scale would
therefore help some errors and harm others. The diagnostic supports separating
source binding from joint-decoder adaptation, rather than simply increasing
source weight or output length.

### Source-head-only comparison

`source_value_freeze_experiment` applies and verifies the private freeze policy;
`benchmark_decoder_source_value_freeze.py` runs the paired comparison after
checking the completed diagnostic and its clean audit. The existing trainer,
semantic-field sequence loss, auxiliary weights, curriculum, optimizer recipe,
source assignments, and strict selection gates remain unchanged. Both source
heads start at zero on the same authenticated epoch-zero inherited decoder used
by the earlier joint fits. Only trainability changes: all inherited body tensors
remain byte-identical across all eight selected/final exports. Count losses and
balanced count-row exposure remain recorded, but the frozen count head and
conditioner receive no gradient update. This is not distillation from a qualified
teacher or a new source embedding representation.

The four fits each complete 340 updates, 2,440 decoder and count-row presentations,
225,840 target-token presentations, and 25,600 auxiliary scalar labels. All 40
post-fit control panels and all eight exports are retained. The table describes
unselected final attempts; each validation denominator is 48 paragraphs or 720
reference-present scalar values.

| Head / seed | Validation sequence CE | Training exact /48 | Validation exact /48 | Source head train /720 | Source head validation /720 | Validation shuffled /720 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Conditioning48 /1729 | 4.013346 | 1 | 0 | 312 | 230 | 230 |
| Projected384 /1729 | 4.003717 | 3 | 0 | 382 | 247 | 226 |
| Conditioning48 /2718 | 4.012458 | 1 | 0 | 312 | 228 | 228 |
| Projected384 /2718 | 4.002865 | 3 | 0 | 371 | 249 | 224 |

All final conditioned validation outputs reach EOS and pass syntax, but each
contains only one rule. All 180 complete reference rules remain missing under
exact whole-rule matching. The one to three exact training documents are all
single-rule cases; no multi-rule training or validation document is exact. All
20 validation checkpoints in each arm are rejected. The eight-rule modality
guard fails at 17, 19, 19, and 20 checkpoints respectively; other per-length
facet guards reject the remaining candidates. Selected training and validation
exactness remain zero. Preserving termination alone
does not solve longer-span semantics.

Sequence CE falls from the shared 4.291244 baseline, but remains much higher
than the prior joint fits' roughly 0.20–0.27 final losses. Freezing the initial
decoder also freezes its substantial sequence-prediction error. Projected heads
retain a modest validation source association: 247/249 correct versus 226/224
after shuffling and 232/228 with zero source features. Conditioning scores equal
their shuffle controls and are close to their 230/224 zero-feature scores.
Neither readout establishes full source fidelity. Projected heads recover
28/48, 32/96, 65–67/192, and 122/384 validation values in the 1/2/4/8-rule bins;
the longer-span gap remains. The two heads also have different parameter counts,
so their comparison is not a controlled test of feature dimension alone.

### Cost, validation, and retained evidence

The diagnostic runner takes 20.865 seconds, including panel writes. The four
head-only fit calls take 6.206, 6.434, 5.796, and 6.457 seconds, totaling 24.893
seconds; their paired joint fits took 42.745 seconds in total. Head-only fits do
less gradient work, particularly through the recurrent decoder, and train
50,176 or 394,240 parameters. This is a narrower experiment with unchanged
rejected checkpoint selection, not faster successful legal formalization.
Post-fit state persistence, reloads, evaluations, and writes add 10.599 seconds.
Device is CPU, workers one, bridge names `[]`, prover evaluation false, and
metric disk cache off. Paragraph embeddings remain warm cached and no encoder
forward or sample-memory scoring occurs. No bridge-on timing is claimed.

The focused suite passes 1,071 tests, with another 34 scheduler-adapter tests.
The 24 new diagnostic tests are included in that focused total. The diagnostic
audit passes 285,494 checks and the final training audit passes 36,106, both with
zero findings. An initial training-audit attempt had one incorrect expectation
about the shape of the runner's augmented decision receipt. Its failed receipt
and original program remain archived; a separate corrected auditor verifies the
exact augmented binding and reruns the arithmetic without retraining. Both audit
source versions are pinned, preserving the original diagnostic audit's source.

The first diagnostic admission failed before any model execution because its
local scheduler configuration differed from the active shared configuration.
A pinned adapter adopts the exact existing configuration for the local client;
it does not reset the shared scheduler or clear retained reservations. The failed
attempt, unused reservation release, adapter tests, and both successful admission
receipts are retained. The diagnostic guardian takes 59.672 seconds and retains
67,295,359 bytes within its released 300 MB reservation. The training guardian
takes 78.558 seconds and retains 117,028,635 bytes within its released 400 MB
reservation. Peak polled RSS is respectively 716,038,144 and 1,014,095,872 bytes;
these are sampled observations, not exact peaks. Final charged storage is
103,968,749,307 bytes under the unchanged 140 GB campaign cap.

The new evidence archive physically retains every new raw replay, fitted state,
generation/readout panel, audit, source/test closure, and recovery receipt.
Previously published inputs are referenced by original path, exact member name,
SHA-256, and byte length in `manifest.referenced_artifacts`. The required archive
dependency is the source-value-training evidence at Git commit
`491b15dd41b105e92817c6d2e0663983a0bb9f7e`; its exact repository/path and hashes
are recorded in `archive_dependencies`, and its public manifest/results are also
included. Thus this archive is explicitly **not standalone**: reproducible
replay requires that verified predecessor archive. Prior raw evidence is
preserved without uploading another copy.

No accepted state is promoted. The 8D linguistic teacher remains unchanged and
verified local 768D inputs remain unavailable. Neither experiment runs native
logic-family qualification or `lake build <Lib>`, grants admission, or formalizes
the Constitution. Fresh holdouts, populated qualifiers, realistic statute spans,
and faithful multi-rule generation remain open gaps. Further work must improve
source binding and sequence/cardinality behavior together while retaining the
existing fidelity and Lake gates.

## Projected-source count and scalar reconstruction experiment (2026-10-03)

This experiment tests joint sequence learning with direct source readouts after
the preceding source-head-only fits preserved syntax but generated only one rule
per validation paragraph. It uses the original authenticated 384D donor, the same
48 authored training paragraphs and 48 repeatedly exposed validation paragraphs,
and the existing strict selection rules. It is development work, not a fresh
holdout study, legacy 8D teacher update, or production decoder replacement.

### Why count guidance needs a training prior

The old cardinality head reads the source-conditioned initial hidden state and
centers its stopping correction on a uniform distribution over 32 count classes.
That correction adds `log(32-k)` to the stop-versus-tail log odds after rule `k`.
The actual training inventory has twelve paragraphs each with 1, 2, 4, or 8 rules.
Even a source-independent predictor matching those four equally frequent classes
would therefore receive a positive first-rule stopping correction of approximately
`log(31/3)`, rather than zero, under the uniform-32 reference.

A read-only diagnostic recomputes this hypothetical correction from the four
previous joint fits' saved validation count logits. Its mean at the first rule
is +2.228 to +2.237 across those fits. Centering the same saved logits on the
fixed smoothed training prior instead gives means from -0.0833 to -0.0746. These
are arithmetic comparisons at a fixed hypothetical boundary, **not new generated
outputs or evidence that reconstruction improved**. Those four prior fits had
boundary guidance disabled, so this correction was not the cause of their
observed errors. The finding prevents a misleading guidance-only follow-up.

The new count prior has positive support for all 32 classes. If `n[k]` is the
number of original training paragraphs with count `k`, the fixed prior is
`pi[k] = (n[k] + 1/32) / (N + 1)`: a symmetric Dirichlet smoothing mass of exactly
one, declared before training. No validation labels fit or tune this prior.
The readout returns learned count residual logits plus serialized float32
`log(pi)`. After a complete rule in the decoder's own valid causal prefix, the
optional correction to the rules-list closing bracket is:

```text
log p(count = k | source) - log p(count > k | source)
  - log pi(count = k) + log pi(count > k)
```

The implementation subtracts two identically shaped, selected-relative
`logsumexp` terms. Zero learned count residuals therefore produce a bit-exact
zero boundary correction, including float32 rounding. This is a source-dependent
odds ratio relative to an empirical training prior, not a calibrated stopping
probability. The recurrent decoder also reads the source. No count class is
removed, and there is no hard count, forced continuation, forced closure, token
mask, or valid-syntax repair. Guidance is inactive at counts of 32 or more and
permanently disabled after an invalid recognized prefix.

### Entry points and training-only preprocessing

The private numerical owner is
[`projected_source_decoder_experiment.py`](../../ipfs_datasets_py/logic/formalization/autoencoder/projected_source_decoder_experiment.py),
with schema `projected-source-decoder-development/v1`. The runner is
[`benchmark_projected_source_reconstruction.py`](../../scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py).
It accepts the same authenticated `--dependency-root`, `--extension-root`,
`--manifest`, `--plan`, and `--output` arguments as the earlier experiments.

- `fit_source_normalization(feature_rows, kind=..., expected_training_ids=...,
  forbidden_validation_ids=..., training_rows_sha256=...)` accepts source-bound
  projected **training** vectors only. `none` is the identity transform.
  `center_rms` subtracts the training coordinate mean and divides by one global
  RMS of centered row L2 norms, matching the earlier frozen-source probe. A
  constant training feature set uses scale one. This is not per-coordinate
  standardization or a changed encoder representation.
- `fit_source_count_prior(training_count_rows, ...)` accepts the same training
  identity/source inventory and the authenticated training reference counts.
  It returns the fixed smoothed prior and its exact float32 logarithms.
- `bind_projected_source_model(persistent_model, codec=...,
  normalization_receipt=..., count_prior_receipt=..., guide_boundary=...,
  scalar_guidance=True)` privately copies the persistent-source decoder and
  adds independent linear count and scalar heads reading the actual projected
  384-vector. It exposes `project`, `count_logits`, `source_value_logits`,
  `start`, `next_logits`, and `describe`.
- `bind_zero_condition_model(model)` removes both initial and persistent
  recurrent source access and supplies zero normalized features to both heads.
  It retains learned head biases and the frozen count prior. In `center_rms`
  mode, the head control represents the training feature mean; in `none` mode
  it represents the raw feature origin. The two controls are labeled accordingly.

Both preprocessing receipts retain the exact training inventory, row/feature
digests, fitted statistics, split exclusion identities, and count histogram.
The new-schema training path also binds these receipts to the actual supplied
training/validation cohorts, including source hashes and row digests; internally
consistent receipts from a different cohort are rejected. The architecture
records both receipts. `source_mean`, `source_scale`, and
`count_prior_logits` are frozen state buffers; a state load that would replace
them with different values is rejected before model mutation. The inherited
autoencoder projection stays frozen. The sequence decoder, source-to-embedding
conditioner, projected count residual head, and full-vocabulary scalar head
remain jointly trainable.

Scalar scores cover eight ordered slots with actor, action, modality, and object
values. Their residual is applied only at the scalar site selected by the
decoder's already consumed lexical prefix. Qualifiers still receive the complete
sequence loss; no absent slot, reference count, reference prefix, or target token
is supplied to generation. The new count and scalar residual heads start at zero,
so all arms must reproduce the original donor's complete greedy training and
validation predictions before fitting. This initial generation parity does not
imply equality of the initial count loss: the count prior deliberately differs
from the historical uniform head.

### Fixed comparison and retained gates

The predeclared experiment has eight fits: `none` or `center_rms` normalization,
each with boundary guidance off or on, at seeds 1729 and 2718. Every arm uses the
original donor, rather than a previously selected or rejected fitted candidate.
Each fit retains 340 optimizer updates, 2,440 decoder and balanced count-row
presentations, 225,840 target-token presentations, and 25,600 present scalar
labels across the same 80 curriculum epochs. Batch size is eight, initial learning
rate is 0.001, and count/scalar auxiliary weights are both 0.25. The existing
semantic-field sequence loss, continuous AdamW/scheduler state, validation
interval, and per-length nonregression selection remain in force.

Within this new comparison the normalization and guidance axes are controlled.
A comparison with the older joint fits is broader: count source geometry, count
prior initialization, and the boundary reference distribution all change. It
must not be described as a one-setting ablation against the old architecture.
The head-only fits above also froze the sequence model, so their wall times are
not directly comparable measures of equal gradient work.

A source-inventory diagnostic clarifies what the unchanged validation split
tests. The training rules contain 15 distinct actor/action pairs; validation
contains five different pairs with no overlap. Every validation scalar class
does occur somewhere in training. Correct validation reconstruction therefore
requires combining familiar values into previously untrained actor/action
pairings, in addition to recovering clause count and order. This is useful
context for the observed actor/action errors, not proof of their sole cause.
The diagnostic changes no training rows or selection criteria; validation pairs
must remain excluded from training.

Every selected and last-complete attempted state is serialized, reloaded, and
evaluated using five postfit panels: ordinary training, ordinary validation,
zero-source validation, within-length shuffled-source validation, and
cross-length shuffled-source validation. Cross-length shuffling is a fixed
rotation between the balanced count bins. It changes only the input vectors;
original targets and source identities remain available to the scorer. The
within-length control tests scalar associations while deliberately preserving
count class. The cross-length control also tests the count association. Neither
is a fresh generalization dataset, and neither participates in fitting or
checkpoint selection. This panel catalog replaces the preceding experiment's
training-shuffle panel with cross-length validation; the difference is explicit.

Full autoregressive output fidelity remains decisive: EOS and parseable syntax
are distinct from correct rule counts, ordered actor/action/modality/object
values, missing/extra rules, and whole-paragraph exactness. Auxiliary count or
scalar accuracy and teacher-forced sequence CE cannot override a failed gate.
The authored references still have empty condition, exception, and temporal
lists. These runs cannot establish populated-qualifier fidelity, real statute
coverage, or correctness across all native logic-family projections.

The new owner has 46 synthetic tests covering training-only preprocessing,
initial bit-exact generation logits, positive count support, guidance direction
and gradients, frozen projection/buffer behavior, full-prefix versus incremental
decoding, interleaved requests, invalid prefixes, and source ablations. Its
synthetic dimensional-shape checks do not train or validate the historical 8D
linguistic teacher or a 768D semantic encoder. Actual fits are 384D only.
Encoder context and decoder output ceiling remain 512, temperature remains zero,
and no weights are downloaded. These development entry points confer no native
qualification or Lean admission; only an actual `lake build <Lib>` can establish
the latter. The Constitution remains unformalized.

### Completed reconstruction results

All eight fits completed the full 340-update budget and all 80 postfit panels.
Initial greedy predictions matched the original donor exactly in every arm.
The independent audit confirms the training-only fit statistics, frozen
projection and preprocessing buffers, saved-state bindings, output scoring, and
unchanged exposure/selection arithmetic. **Every selected state remains at epoch
zero, and every final attempt still has 0/48 exact validation paragraphs.** No
checkpoint is accepted or promoted.

The following table describes unselected last-complete attempts. Rule totals
count valid generated rules from the full-document scorer; malformed or
unparseable output is not repaired into successful formulas. Each validation
split contains 48 paragraphs and 180 reference rules.

| Normalization / guidance / seed | Sequence CE | Count correct /48 | Training exact /48 | Validation EOS / syntax /48 | Valid generated rules | Fit call seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| None / off /1729 | 0.199236 | 22 | 1 | 14 / 14 | 14 | 13.010 |
| None / on /1729 | 0.191651 | 21 | 3 | 48 / 48 | 112 | 12.364 |
| Center RMS / off /1729 | 0.206820 | 27 | 5 | 25 / 25 | 25 | 12.070 |
| Center RMS / on /1729 | 0.268138 | 23 | 2 | 48 / 26 | 26 | 11.513 |
| None / off /2718 | 0.186596 | 26 | 0 | 0 / 0 | 0 | 14.181 |
| None / on /2718 | 0.191581 | 23 | 4 | 48 / 48 | 85 | 11.820 |
| Center RMS / off /2718 | 0.211549 | 26 | 5 | 43 / 43 | 50 | 11.147 |
| Center RMS / on /2718 | 0.197750 | 24 | 6 | 48 / 48 | 110 | 11.173 |

Boundary guidance improves termination in all four matched comparisons, reaching
EOS on all 48 validation rows. With unnormalized features it also reaches full
syntax validity in both seeds, compared with 14 and zero valid documents without
guidance. But the normalized seed-1729 candidate terminates with only 26 valid
documents: the soft correction does not guarantee valid syntax. Neither
termination nor the larger number of generated clauses yields an exact
multi-rule training or validation paragraph. All exact training paragraphs in
the table contain one rule.

Even the three guided arms with 48/48 valid documents recover only 18–23 correct
ordered actor values, 18–22 action values, 26–33 modalities, and 42–56 objects out
of the 180 reference positions. Each arm still has zero exact whole-rule matches
on validation. The scorer consequently reports all 180 reference rules missing
under **exact rule matching**, even when a candidate emits 85–112 syntactically
valid rules. This is a semantic mismatch count, not a claim that no text or
clauses were generated. Empty qualifier agreement does not close that gap.

The source-only count heads recover 21–27/48 validation counts, compared with
12/48 for the zero-feature prior controls. Within-length shuffling preserves
those totals, as expected from its construction; cross-length shuffling reduces
them to 8–9/48. Thus the count readout uses a real association with the source,
but its accuracy remains insufficient and is not a selection criterion. The
earlier inherited-hidden-state count heads scored lower, but the broader
architecture/prior change prevents attributing this difference to feature
geometry alone.

The scalar head still has a large training/validation gap. These conditional
counts score only the 720 scalar positions present in the references; they are
not counts of generated correct formulas.

| Normalization / guidance / seed | Training /720 | Validation /720 | Within-length shuffle /720 | Zero feature /720 | Cross-length shuffle /720 |
| --- | ---: | ---: | ---: | ---: | ---: |
| None / off /1729 | 381 | 244 | 231 | 229 | 220 |
| None / on /1729 | 375 | 247 | 234 | 229 | 223 |
| Center RMS / off /1729 | 400 | 245 | 220 | 228 | 195 |
| Center RMS / on /1729 | 399 | 247 | 215 | 228 | 191 |
| None / off /2718 | 396 | 244 | 240 | 224 | 217 |
| None / on /2718 | 365 | 253 | 231 | 231 | 217 |
| Center RMS / off /2718 | 402 | 242 | 211 | 233 | 188 |
| Center RMS / on /2718 | 399 | 243 | 222 | 235 | 194 |

A supplemental saved-output diagnostic pairs the head's actor and action
predictions at the same reference-present slot. Only 5–7 of 180 such pairs are
jointly correct in each arm. The separate raw-JSON pair census is explicitly
broader than full syntax-valid formula scoring and must not replace the table
above. These diagnostics show why better stopping alone is insufficient; they
do not establish one cause for every error. Reliable binding of source values
to ordered clauses, including the held-out actor/action combinations, remains
the central unresolved reconstruction task.

### Validation, timing, and evidence scope

The frozen focused suite passes **1,183 tests**, including the previous 1,071
regression tests, 46 new model tests, and 66 runner/trainer tests. Another 34
scheduler-adapter tests pass. Pre-run readiness passes 187 checks; the independent
post-run audit passes **53,408 checks with zero findings**. Its scope is saved
state and source bindings, affine head arithmetic, fitted statistics, generated
token/grammar/facet/count scoring, and exposure/selection reconstruction. It
does not rerun recurrent generation, replay gradients, recompute the full token
CE, invoke external provers, or execute native family qualification or Lake.

All fits train 431,392 parameters while preserving the inherited projection.
The eight fit calls total 97.278 seconds, and postfit persistence, reloads,
controls, and output writes total another 36.131 seconds. Guardian wall time is
173.122 seconds, including resource accounting. The attempt retains 298,316,138
bytes within its released 800 MB reservation. Peak polled process-group RSS is
964,694,016 bytes under the 4 GiB allocation; polling does not establish the exact
peak. The campaign cap remains 140 GB.

For conditioned validation, the existing numerical evaluation API reports
0.00246–0.01740 wall seconds per span across these eight final states, with 48
samples per call. That interval includes numerical validation, teacher-forced
CE, target-free generation, copying, and identity checks, and excludes the
separate source-fidelity/head diagnostics and artifact writes. Generated lengths
and failure modes differ substantially, so faster invalid or shorter outputs
are not faster successful reconstruction. Device is CPU with one worker;
bridge names are `[]`, prover evaluation is false, and the legal-IR metric disk
cache is off. Embeddings are warm, verified cached vectors; no encoder forward
occurs. **This is not a bridge-on timing or an end-to-end statute conversion
speedup.**

Selected and rejected states, complete generated tokens, all control panels,
training receipts, exact preprocessing vectors/statistics, source snapshots,
test reports, audit programs, and resource receipts remain retained. The
[published evidence](../implementation/reports/evidence/decoder-projected-source-20261003/results.json)
separates this completed experiment from the historical comparison inputs and
the supplemental compositional diagnostics. Its archive physically includes the
original five inputs, prior public metadata and raw boundary-diagnostic inputs,
all new run outputs, 94 frozen producer sources, 31 test files, and the audit
programs and local arithmetic helper. It requires no nested predecessor archive
to recover those artifacts. Host Python packages and the execution environment
are not bundled; replay still requires compatible runtime setup and path
relocation. Improved count association and
termination are development findings; no full validation reconstruction,
convergence claim, teacher qualification, native logic-family validation, or
Lean admission follows from them.
