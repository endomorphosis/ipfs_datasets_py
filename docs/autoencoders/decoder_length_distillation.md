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
