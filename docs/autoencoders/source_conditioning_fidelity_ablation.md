# Source conditioning and semantic reconstruction: next controlled ablation

This is an implementation and experiment specification, not a completed training
result. The audit used released datasets commit
`a7e7a228e28dcf45e18af9c82544611f1ef16e60`. No model was trained, checkpoint
changed, source context enlarged, or model promoted while preparing this plan.
The historical 8D linguistic decoder remains separate and unchanged.

## What the existing evidence shows

The [Intent/UI comparison evidence](../implementation/reports/evidence/intent-ui-coverage-20261002/results.json)
compared two unchanged GRU training seeds with a structured scalar readout. Each
domain used 96 training, 24 tuning and 24 sealed test compositions. Every varying
lexical value occurred in training. Complete compositions were disjoint, but
semantic groups and grammar were shared: these were authored composition tests,
not an independently labelled corpus or unseen-vocabulary evaluation. All those
test rows are now exposed and must be labelled regression data in future work.

The preserved outputs at
`workspace/test-logs/intent-ui-coverage-20261002/comparison-r1/` give:

| Reader | Intent exact / 24 | Intent scalar correctness / 24 | UI exact / 24 | UI scalar correctness / 24 |
| --- | ---: | --- | ---: | --- |
| GRU seed 3517 | 3 | actor 24, action 24, modality 7, object 8 | 3 | ID 24, presentation 24, privacy 15, role 6 |
| GRU seed 3518 | 8 | actor 19, action 24, modality 23, object 11 | 2 | ID 24, presentation 18, privacy 8, role 6 |
| Structured ridge | 24 | all four fields 24 | 24 | all four fields 24 |

All these outputs were native-valid; validity alone did not preserve their
source meaning. The sources explicitly state the failed fields. Ridge's exact
readout from the same 384D embeddings is evidence against missing source
information being the principal explanation **on this fixed-vocabulary panel**.
It does not prove a GRU capacity limit or general source understanding. Ridge's
inherited projection is frozen, so its success is not an improvement in
autoencoder embedding reconstruction.

The four GRU `training-metrics.json` receipts show 448, 1,000, 785 and 472 epochs,
respectively. Three stopped on validation patience and one on epoch budget;
none stopped on its 30-second numerical deadline. Selected teacher-forced
tuning token cross-entropies were approximately 0.0747, 0.0431, 0.0723 and 0.1242.
Low mean token loss therefore coexisted with wrong semantic values. Intent seed
3517's test embedding MSE was approximately 0.00118 despite only 3/24 exact
targets; the ridge projection's approximately 0.00444 MSE coexisted with 24/24
exact targets. Embedding reconstruction and symbolic fidelity must be reported
separately, not substituted for one another.

The [earlier scalar-weighted v2 comparison](source384_fidelity_training_v2.md)
also failed to improve its smaller fresh test panel. Its field-preservation and
embedding gates rejected later candidates whose continuous loss improved while
individual semantic fields deteriorated. That evidence supports testing a
better decoder signal; it does not justify relaxing those gates or selecting
hyperparameters from an exposed test.

## A specific, testable decoder hypothesis

[`modal_latent_formula._model`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py)
sets the initial hidden state to `tanh(condition(projected_embedding))`.
`next_logits` subsequently gives the GRU only the preceding token embedding and
its recurrent hidden state. The source condition is not supplied anew at each
step. The [domain trainer](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py)
teacher-forces the full canonical JSON token sequence; its many predictable
syntax and key tokens contribute to the average token loss.

Weak source retention at later values is a plausible explanation for the
modality/object/privacy/role errors. It is a hypothesis, not an established
causal diagnosis; actor errors and differences between seeds remain recorded.
The controlled intervention is to supply the same learned source condition at
every decoder step, without adding source-parser outputs, reference targets,
retrieved complete targets, larger hidden states or larger context windows.

Create a **new versioned 384D checkpoint/runtime owner** with two explicit modes:

1. Initial-only control: the existing initial hidden-state conditioning.
2. Persistent-condition candidate: the same initial hidden state plus the
   learned source condition concatenated to each token embedding before the GRU.

Keep original recurrent weights and shared initial parameters identical by seed.
Initialize the candidate's additional GRU input columns to zero so its initial
function matches the control; record the additional parameter count and tensor
mapping. Both modes must perform identical teacher-forced training and
target-free greedy inference transformations. A runtime must reject a checkpoint
with a different architecture/mode, source pin, domain or tensor shape. Existing
v1, v2, structured-readout and 8D checkpoints must not be relabelled or rewritten.

## Same-budget development experiment

First use only previously exposed **training and tuning** data to test the
implementation and loss curves. This stage is development, never a new holdout
claim. Do not begin the fresh test until both modes and their selection policy
are frozen.

Use the following identical settings in the two modes:

| Setting | Predeclared value |
| --- | --- |
| Parent | Trained local Legal384 parent listed below; immutable |
| Hidden size / projection width | 32 / 8, inherited |
| Target token ceiling / temperature | 64 / 0 |
| Batch size / maximum epochs / numerical seconds | 16 / 1,000 / 30 |
| Learning rate / reconstruction weight | 0.003 / 0.1 |
| Scalar value weight / source normalization | 8 / none |
| Generated evaluation interval / patience | 10 / 120 |
| Learning-rate plateau policy | Existing v2 defaults, identical in both modes |
| Seeds | Two fixed seeds recorded before fitting either mode |

Reuse the [v2 objective and selection rules](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder_v2.py):
positive loss on every scalar value, retained key/syntax loss, raw embedding
reconstruction loss, native validation, free-running exact and per-path fidelity,
no scalar-path regression and the existing embedding nonregression bound.
Report rejected evaluations and their reasons. An incomplete or late evaluation
cannot select a checkpoint. No-token truncation, skipped family checks or
deadline-dependent scoring subsets are permitted.

If a deadline prevents useful fitting, report the failure and revise the next
experiment's **shared** budget before any fresh test exposure. Do not give only
the candidate additional epochs. Numerical time, preparation, evaluation,
serialization and total wall time are separate measurements; the current
numerical deadline is not a hard process limit for all preparation.

## Fresh split and leakage controls

Use a new authored panel, with source texts distinct from all earlier exposed
panels and independently checked labels within the existing accepted grammar.
Keep each domain at 96 training, 24 tuning and 24 test examples. Record the panel
generator, coordinate-only split manifest and source hashes before fitting.

For Intent, keep every modality contrast for one actor/action/object combination
in the same split. For UI, keep every presentation contrast for one
component/role/privacy combination in the same split. A 48-group panel with
three variants per group supports 32/8/8 groups. Balance all individual scalar
values across training and ensure each test value has training support. This
tests new combinations of known values; do not call it unseen-vocabulary or
freeform corpus generalization. Additional role/privacy and actor/object
minimal-pair diagnostics should be reported explicitly; the grouped split must
state which contrasts it holds together and must not claim all possible
contrast graphs are disjoint.

Fit vocabulary, value classes, normalization and all weights from training only.
Tuning may select checkpoints and the shared development recipe; it must not
create vocabulary or semantic classes. Reject overlap in IDs, normalized source
text, embeddings and declared semantic groups. Check the entire source against
the existing encoder ceiling without truncation. A target outside the unchanged
64-token ceiling is unsupported and remains in the denominator.

Before constructing any fresh test text, target or embedding, finish **all four
fits per domain** (two seeds, two modes), write immutable checkpoints and seal
their hashes, settings, selection results and producer pins. Only then
materialize the test once. Keep every raw prediction, EOS/truncation/error
disposition, per-field difference and ablation. No post-test model selection or
rerun may be presented as the same fresh comparison.

The neural input is exactly ID, original source provenance and its verified
384D embedding; labels never enter `Runtime.infer`. The rich Intent source audit
and strict UI source contract run only after prediction. They may reject a
candidate but cannot replace it with the parser's answer. Test zero source
condition, zero decoder/readout and shuffled embeddings with unchanged input
ordering and raw outputs; both the initial and persistent source paths must be
removed in the zero-condition ablation.

## Acceptance evidence and qualification

Report train/tuning learning curves and fresh exact counts, all scalar paths,
native/source-agreement counts, failures, embedding MSE/cosine, tokens and spans
per second, peak resident memory and wall time per span for each arm and seed.
Report numerator and denominator rather than only averages. Compare the same
rows and actual target-free generated outputs. The experiment supports a useful
improvement only if semantic reconstruction improves without moving errors into
other fields or violating the reconstruction gate; a loss decrease alone is
insufficient. Two small seeds do not establish global convergence or a global
minimum.

Preselect native-check row indices before viewing results. For those unchanged
learned candidates, request the full applicable family inventory through the
current source/native qualification path, retain unsupported or blocked rows,
and execute actual `lake build <Lib>` for eligible projections. A checked
projection has only its declared interpretation scope. Syntax, native validity,
source agreement, exact reference reconstruction and successful Lake builds
remain separate evidence. A vector, row, inferred candidate or compile is not
an admit. No automatic promotion, production replacement or whole-modality
qualification follows from this ablation.

## A separate upstream action-contract data gap

The [new explicit Intent action head](intent_action_contract_training_384.md)
achieved 24/24 on its bounded authored composition test, with 0/24 after zeroing
the head or shuffling embeddings. It is a frozen-projection scalar readout,
distinct from the GRU. Its [actual finite native replay](../implementation/reports/evidence/intent-action-contracts-20261002/README.md)
checked one unchanged Security source against 24 contracts: one satisfied,
eight refuted and fifteen with no enabled input. Those are not 24 successfully
completed tasks. Its test is now exposed regression material.

The [training generator](../../scripts/ops/autoencoder/train_intent_action_contracts_384.py)
always uses `requires left > threshold`, and varies only the two nonrepeated
operand orders. The [codec](../../ipfs_datasets_py/logic/intent_ir/formalize/action_contracts.py)
also accepts right-side requirements, repeated operands and `requires true`.
The [fixed-schema reader](../../ipfs_datasets_py/logic/formalization/autoencoder/structured_source_384.py)
preserves training-constant fields in its template. The existing action checkpoint
therefore cannot predict a right-side requirement in that constant field; syntax
acceptance by the codec is not learned coverage. Repeated operands use known
classes but were not covered by that training/test panel. `true` changes the
native predicate/argument shape and is outside the fitted fixed-shape profile.

A separate, versioned data extension should train both requirement inputs and
all four ordered operand pairs, with balanced grouped train/tune/fresh-test
splits and unchanged post-generation source checks. Keep `true` unsupported for
that fixed-shape head, or implement and independently evaluate an explicit
separate learned shape profile. Do not change the concurrent author's scripts,
published checkpoint or inference defaults as part of this conditioning study.

Missing context remains different from a learned error: a permission-only
instruction does not state return effects; a UI component's four descriptive
fields do not state its timed event history. Extra epochs cannot legitimately
invent either. Rich/contextual sources, real corpus labels and additional
native constructors need their own source/data coverage work.

## Reproducibility assets and reviewed source pins

Available locally, verified without downloading:

- GTE-small snapshot: `/home/barberb/.cache/huggingface/hub/models--thenlper--gte-small/snapshots/17e1f347d17fe144873b1201da91788898c639cd`.
  Model bytes: 66,746,168; SHA-256 `9a1eb90bbac323ea08aa5629b624fe6ae75db121b904799c2266a1e2c2de22d2`.
  The run must additionally verify the complete existing tokenizer/config asset
  manifest, use local files only and retain actual tokenization provenance.
- Parent: `workspace/test-logs/holdout-throughput-release-20261001/current-holdout-r1/1729-original32-head.json`.
  Bytes: 1,678,190; SHA-256 `969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62`.

The following SHA-256 values identify reviewed files **at the released commit
above**, not a claim that every live file or transitive dependency is frozen:

| Repository path | SHA-256 |
| --- | --- |
| `ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py` | `ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36` |
| `ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py` | `66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6` |
| `ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder_v2.py` | `8026ee2788465835db399a2b33fd734451440370b70f75af3a0ba36467a4cf7f` |
| `ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_fidelity.py` | `d24a30a9584548be66b5324fb4bfe1b8cbb708b4350dd10937c2b258468ef6da` |
| `ipfs_datasets_py/logic/formalization/autoencoder/structured_source_384.py` | `3f9ca9ce7b4cf2a2d10d6aeb1fae78543c468133d2fa0df9fcb32f63f89e90f7` |
| `scripts/ops/autoencoder/train_intent_action_contracts_384.py` | `6c899a09541cf685455f04d0cbe54c432dcde6b7ab12d5b4bd7185f6ccb31530` |
| `tests/fixtures/logic/intent_ui_source_compositions_v1/panel.py` | `99a1ee0330e2a73e0f78051e8a6623605746b1c74b56f83fdbe6f484965bfc33` |

Any implementation run needs a new immutable source export, its own manifest,
explicit canonical-tree import checks and before/after checks of assets,
checkpoints and producer files. Preserve all prior evidence directories.

## First implementation and development result

The separate [v3 source-conditioned decoder](source_conditioned_decoder_v3.md)
implements both modes and records the eight-fit exposed-data comparison.
Persistent conditioning did not consistently improve exact reconstruction and
was not promoted. That comparison is development evidence only; this document's
fresh grouped-holdout protocol remains outstanding.
