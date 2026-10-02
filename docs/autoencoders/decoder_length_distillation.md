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
length range is 9–74 tokens; actual pinned-tokenizer counts from the run are
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
9–74 tokens; complete JSON targets have 40/73/139/271 tokens including BOS/EOS.
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

The current checkpoint selection protects aggregate exact/EOS/failure counts and
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
