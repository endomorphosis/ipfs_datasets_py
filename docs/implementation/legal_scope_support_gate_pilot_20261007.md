# Matched support gates reject all fitted checkpoints

This opt-in experiment freezes the exact selected support/action MLP parent
`48559399bb22de0fe68908919d225d391880a38f4fab659026d526e19ffc9155`
and trains two support-only residuals. Both finish 240 actual optimizer calls,
but their update-120 and update-240 checkpoints fail the predeclared selection
floors. Both select the actual cold step-zero checkpoint. This is a completed
negative result: no selected prediction improvement or default replacement.

The previous [support/action pilot](legal_scope_support_action_pilot_20261007.md)
remains the parent lineage; the separately published native 384D two-bank replay
remains preserved, including the [checkpoint availability and reconciliation](../autoencoders/retained_wording_checkpoint_availability_20261007.md). Its native schema/format and runtime/teacher/proof admissions remain unqualified; these are separate task and checkpoint bindings. This model reads source text and does not consume 8D/384D/768D
legal latent vectors. All results remain occurrence proposals with zero admission
masks and null formal output, without reviewed law semantics or Lake admission.

## Matched representation and frozen custody

Both new Tanh heads have 97 inputs, hidden width 32 and 3,169 trainable parameters.
Their initial tensors are identical and their final projection is zero. Per-token
features concatenate the original frozen contextual states (64) and the original
ordered Conv 3 byte frontend's mean/max/log-byte-length features (33). The global
arm averages this bundle over all real tokens. The predicted-trigger arm pools
it using the existing normalized interval coverage P(S<=t)*P(E>=t) from frozen
modality pointers. Both compute the same bundle; only pooling changes. No new
byte encoder, word list, semantic parser, target span or reference feature runs.
The original encoder already preserves byte order.

Every parent tensor, parameter flag, module mode, configuration and original
checkpoint byte remains frozen, including the earlier trained class readout,
support head and action heads. After validating the original full checkpoint and
Adam state, the wrapper freezes its heads and uses a faithful frozen tensor path.
It does not call the old forward/assert/save contracts that require those heads
trainable. Complete snapshot guards check the new contract. Every raw class,
optional-presence and all five pointer outputs remains exact; wires and proposals
also match whenever both models emit. Support probabilities and emission statuses
are allowed to change. Conditions remain opaque and attachment is a caller premise.

## Fitting and selection

Each arm uses seed 24605, 240 AdamW calls, learning rate .003, zero weight decay
and gradient clip 5. Each call encodes eight supported plus eight unsupported
sources and fits support BCE over all 16. Across both arms this is 480 calls and
7,680 encoded source presentations. There is no class, presence or pointer loss,
no action update and no continuation of the parent's Adam. New full gate Adam
and integer progress are saved and restored strictly. Cold zero-step checkpoints
require exact seeded tensors and empty Adam, preventing a restarted trained head
from being described as unfitted.

The new bank has 512+512 TRAIN, 64+64 selection and 64+64 final rows. Its 1,280
normalized sources and 640 paired groups are excluded from all three earlier
banks together (3,840 sources/1,920 groups). Declared and observed facets,
semantic heads and content words are also disjoint across banks and splits.
All eight action lemmas occur in every template/split, with eight examples per
lemma/template on TRAIN and one on each evaluation. Eight templates, four null
cells, four negative categories, Unicode and repeated occurrences are recorded.
Grammar/modal aliases and corruption permutations remain deliberately shared.
Construction labels were mechanically reviewed by authors; this is authored
engineering evidence without independent legal gold or an authors-blind claim.

Selection considers actual updates 0/120/240. The measured baseline must emit
positive proposals and have positive whole successes. Eligible checkpoints must
have no more negative emissions, no fewer positive whole successes or emissions,
and no more positive learned refusals than that baseline. Rank first minimizes
negative emissions, then maximizes whole successes and learned negative refusals,
then prefers earlier updates. The actual step-zero artifact is always the fallback.
These are aggregate selection constraints; they neither guarantee individual-case
retention nor impose final/earlier-cohort performance guarantees.

| Selection, 64 supported +64 unsupported | Step | Whole exact | Positive emitted | Positive learned refusal | Negative emitted | Eligible |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Parent / both initial gates | 0 | 32 | 48 | 6 | 10 | yes |
| Global | 120 | 30 | 44 | 10 | 9 | no |
| Global | 240 | 30 | 45 | 9 | 9 | no |
| Predicted trigger | 120 | 33 | 49 | 5 | 11 | no |
| Predicted trigger | 240 | 32 | 47 | 8 | 10 | no |

Global loses two earlier whole successes and removes one unsupported emission at
both trained steps. The local step-120 head loses one whole success, gains two,
removes two unsupported emissions and introduces three. At step 240 it loses two
whole successes and gains two; two negatives are removed and two introduced.
These saved-panel postfit paired diagnostics explain the rejection without
changing the predeclared rule or evaluating rejected heads on final references.
Improved clipped support BCE alone does not qualify a checkpoint.

Both selections/checkpoint hashes are durable before numerical parsing of fresh
final or earlier retention references. All 12 source-only panels for three models
and four cohorts are durable before their label joins. Inference denies all new
and old TRAIN constructors/helpers, the semantic parser and AdamW.step. Hash-only
reference reads and mechanically reviewed construction labels are disclosed;
this is a numerical barrier, not a syscall restriction or an authors-blind legal test.

## Selected fallback results and rejected TRAIN diagnostics

Only the selected cold gates are run on the final and earlier cohorts. Both are
exactly equivalent to the parent on the measured cores, so all paired selected
whole/negative gains and losses are zero. All 384 original parent dictionaries
on the three exposed earlier cohorts match their archived panels exactly.

| Selected parent/global/local results | Whole exact /64 | Raw action exact /64 | Unsupported emitted /64 | Frozen structural whole ceiling /64 |
| --- | ---: | ---: | ---: | ---: |
| New final | 38 | 61 | 13 | 41 |
| Earlier scope | 40 | 64 | 8 | 50 |
| Earlier trigger | 39 | 64 | 12 | 43 |
| Earlier support/action | 39 | 62 | 12 | 42 |

On the new final, all three have raw support TP/FN/FP/TN 59/5/16/48, positive
status counts 55 emitted/5 learned refusal/4 structural block, and negative
status counts 13 emitted/48 learned refusal/3 incidental block. Twelve emissions
are modal misspellings and one an extra exception. Unsupported means outside
this declared single-rule profile, not legally false.

Postfit saved TRAIN panels at actual update 240 give parent/global/local whole
exact 322/310/317 out of 512, unsupported emitted 112/108/99 out of 512 and
clipped support-probability BCE .426070/.405175/.349219. Modal-misspelling emissions
are 109/105/97 out of 128. The local arm improves training refusal and BCE while
losing positive proposals, and still emits most malformed-modal negatives.
These TRAIN diagnostics are separate from the selected zero-step final scores;
no fitting, checkpoint selection or new forwards occur in the postfit analysis.

## Validation, artifacts and remaining work

170 successful decoder/proposal test executions and 23 separate pure selector
fixtures pass. The original XML omitted filenames and had six name collisions;
a source-qualified collection-only ledger matches all 170 executed case names in
order against unchanged test files. Tests were not repeated to repair provenance.
Independent corpus, source, runner, protocol, result and resource reviews bind
actual artifacts. Read-only replay reproduces all 1,024 selected full outputs
with complete gate Adam, counters, parent bytes, tensors, modes, flags and CPU
Torch RNG unchanged, no reference loads or optimizer steps.

The byte-identical guardian retains its 23 historical pure tests (not rerun here),
admits the owned 2 CPUs/1,536-MiB/200-MB/one-child job, reaps the child and releases
only its own lease and disk claim. The prior failed 200-MB claim remains retained.
Thirty-five model-phase RSS samples peak at 817,844,224 bytes (about 780 MiB) with
maximum observed gap 1.074 seconds. These are sampled non-atomic group sums,
not an absolute peak, kernel quota or continuous coverage. The numerical runner
takes 25.82 seconds; admission/import/census/finalization have separate overhead.
All 109 published Git/LFS identities were verified; all 2,747 prior file
identities are preserved. All eight checkpoint containers download byte-exact,
and the downloaded selected aliases reproduce all 1,024 full outputs with no
updates. Hosted CI availability is recorded separately.

[Checkpoints and full evidence](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/ae5a6b555f66f9ea7cdf3f46a03c689d07485bb5/experiments/support-gate-20261007/run-01)
include all six original 0/120/240 research states and two selected-zero aliases.
Trained 120/240 states are explicitly selection-ineligible research artifacts;
they are not promoted or evaluated on the final panel. The release manifest maps
all bytes and roles. The frozen numerical producers remain unchanged afterward.

A future matched trial should test a trainable ordered-byte support branch with
positive-retention constraints and malformed-modal contrast pairs using TRAIN
only. Keep both frozen pointer outputs and the current rejection policy, predeclare
which parameters may change and create a new excluded final before fitting.
This is a hypothesis from a failed frozen-feature trial, not evidence of an
encoder-capacity diagnosis. Real US Code review, latent conditioning, quantified
and multiple-rule semantics, native-family lowering and `lake build legal`
qualification remain separate open requirements. No default registry or original
latent checkpoint is changed.
