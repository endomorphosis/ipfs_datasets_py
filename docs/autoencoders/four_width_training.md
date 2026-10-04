# Training the separate 8D, 384D, 768D and 4096D decoders

The four-width request first needs a representation and decoder readiness check.
The October 4 comparison trains separate Legal formula sidecars for the available
8D, 384D and 768D source representations. The 4096D lane still requires a trusted
native input producer and an explicitly compatible decoder. Its embedding
throughput receipts and synthetic decoder controls are not trained checkpoints.

## Representations and scope

| Width | Source representation | This comparison |
| --- | --- | --- |
| 8 | Historical linguistic feature hash | Separate learned formula sidecar; preserves the linguistic teacher |
| 384 | Local pinned GTE-small semantic embeddings | Separate formula sidecar |
| 768 | Local pinned multilingual GTE semantic embeddings | Separate formula sidecar |
| 4096 | Local Leanstral language-model representation | Native-owner integration and matching source inputs still required |

The first three lanes use existing cached vectors for identical source texts.
They have different source producers, so their comparison is not an isolated
dimensionality ablation. Source-independent token-decoder tensors are inherited;
source routes are initialized separately. The residual projection remains a
frozen identity. Its zero reconstruction error is not a learned accomplishment.
These runs train source conditioning and formula reconstruction, not the native
embedding encoders or the historical linguistic teacher.

Encoder context and decoder output limits remain 512; generation uses temperature
zero. No model weights are downloaded. Training uses an explicit immutable
snapshot of the workspace package and authenticated extension files. The import
inventory rejects other trees, including the editable HACC install. The current
workspace compiler gates are checked separately from that historical snapshot.

## Fixed training comparison

Run `scripts/ops/autoencoder/benchmark_multidimension_modality_training.py` with
`--phase preflight` before `--phase training`. Both phases require
`--dependency-root`, `--extension-root`, `--manifest`, `--plan` and a fresh
`--output` directory. The manifest binds the earlier frozen context, the exact
width-specific baseline states and inputs, and later exposed source exclusions.
Use the resource guardian in the evidence directory rather than launching an
unreserved campaign.

The fixed recipe has one seed (1729), three widths and two arms per width:

- `source-head-lr10` replays the earlier baseline, including initialization,
  selected/final predictions and non-timing numerical evidence.
- `aux-used113` adds a 0.05-weight modality loss over six independently sampled
  training clauses per update. It retains the full 32-token vocabulary.

Each completed fit has 340 optimizer updates, 2,440 paragraph presentations,
225,840 target-token presentations and 25,600 original source-value labels. The
auxiliary arm adds 2,040 clause presentations. Both use the same 48 training
paragraphs and 48 development paragraphs, containing one, two, four or eight
clauses. Existing learning-rate, clipping, scheduler and selection policies
remain in place. The development fidelity gate can reject a candidate even when
its cross-entropy decreases.

Only the 113 clauses already used by the training paragraphs participate in the
auxiliary loss. Their source, complete target and wording-style metadata are
authenticated against the original 180-clause bank. Only the selected 113 vectors
are rebound to the exact native-width cache. No vectors are padded or converted,
and no 180-vector native bank is claimed for 8D or 768D. Original test/canary
identity and text exclusions apply to all widths; vector exclusions apply where
same-width vectors exist. The derivation receipt records that coverage explicitly.

Selected and final attempted states are retained separately. Every endpoint has
nine controls: development, training, zero condition, source shuffle, cross-length
shuffle, context-only shuffle, context reversal, context rotation and recurrent
residual disabled. State exports are numerical snapshots without optimizer state;
they are not resumable training checkpoints.

## Held-out regression and evidence

The separate R6 48-paragraph authored cohort is already exposed historical
regression data, not a fresh holdout. Postfit scoring must persist all source-only
predictions before loading that cohort's reference labels. It may report greedy
exact reconstruction, scalar fidelity and full-vocabulary teacher-forced
cross-entropy; it cannot change checkpoint selection or restart training.
The entry point is `scripts/ops/autoencoder/evaluate_multidimension_modality_holdout.py`
with `--phase evaluation` and the same five explicit path arguments. Its own
manifest binds all completed fits, saved preprocessing and separate source and
reference artifacts. Training and evaluation have separate frozen source folders
and resource guardians.

Report fit wall time and paragraph presentations per second per width/arm. Inputs
are warm cached embeddings. These measurements use one CPU worker, bridge names
`[]`, prover evaluation disabled, and the legal-IR metric disk cache disabled.
No bridge-on evaluate is executed, so there is no bridge-on throughput or
legal-IR-target improvement claim.

The authored codec, syntax checks, compiler fixtures, losses and saved states grant
no admission. Admission requires `lake build <Lib>` on the relevant Lean output.
This experiment does not promote a production model, establish global convergence,
cover every logic family or mark any Constitution span formalized.

## Measured outcomes on October 4

All six fits completed their budgets. The table compares the final attempted
baseline with the final auxiliary candidate, not necessarily the selected state.
Each exact count is out of 48 paragraphs. Regression is the previously exposed
R6 cohort, separate from the development data used for selection.

| Width | Development exact | Regression exact | Regression token cross-entropy | Fit seconds, baseline / auxiliary |
| --- | --- | --- | --- | --- |
| 8 | 1 → 1 | 0 → 0 | 0.75135 → 0.75329 | 46.43 / 43.10 |
| 384 | 47 → 48 | 30 → 28 | 0.02968 → 0.02953 | 60.68 / 65.50 |
| 768 | 46 → 44 | 47 → 48 | 0.01840 → 0.01616 | 87.57 / 92.17 |
| 4096 | Not trained | Not evaluated | Not measured | Not measured |

Only the 384D auxiliary candidate passed the private development selection gate,
at epoch 80. Every other fit retained its initial selected state; their table
entries describe rejected final attempts. In particular, the 768D regression gain
does not override its development regression. Its development action accuracy
dropped from 178/180 to 175/180 while modality accuracy stayed 180/180. The 384D
regression cross-entropy decreased slightly even though exact reconstruction fell.
Loss alone is insufficient to select a faithful decoder.

Training throughput was 52.55/56.61, 40.21/37.25 and 27.86/26.47 paragraph
presentations per second for 8D, 384D and 768D respectively (baseline/auxiliary).
Corresponding wall seconds per presentation were 0.01903/0.01767,
0.02487/0.02685 and 0.03589/0.03777. These are one-seed observations on a shared
host; they establish neither a repeatable speedup nor convergence.

The training child took 547.53 seconds including initialization, state exports
and original control panels; its full resource-guarded phase took 580.59 seconds.
The highest of 29 sampled process-group RSS observations was 1,536,991,232 bytes
(about 1.43 GiB), below its 4 GiB reservation. This is a sampled maximum, not a
certified peak or whole-machine memory measurement. The twelve-panel regression
evaluation took 24.18 seconds in the child and 62.69 seconds including its guardian.

The two new runners passed 70 focused tests. Real three-width initialization
preflight and the three current-workspace compiler gates passed. An independent
saved-data training audit checked all 18 states, 108 original control panels,
full-vocabulary loss arithmetic and exact historical baseline replay: 2,092,659
checks, zero final findings. An initial audit compared two wall-clock fields as
numerical baseline values; that audit-only correction and the initial findings
are retained. No model, tolerance or selection gate changed to pass the audit.
The separate regression audit passed 4,591 checks with zero findings, covering
all twelve saved predictions, the reference-loading barrier and scoring evidence.

No production checkpoint was promoted. The 8D linguistic teacher and protected
restart12 checkpoint remain unchanged. The results support width-specific
experiments rather than a common auxiliary-loss default. The next fidelity work
must address the 8D source sidecar's weak reconstruction and the development versus
regression tradeoffs at 384D and 768D.

## What the 4096D lane still needs

The local 4096D benchmark contains 800 different single-clause sources: none
matches the existing 239 paragraph/clause literals or the original 180-clause
auxiliary bank. Its fixed-batch repeats agree, but singleton-versus-batch L2
distance is approximately 0.146, exceeding the recorded 0.001 equivalence
tolerance. Those outputs cannot substitute for the missing same-source inputs.

Implement the native-owner verification contract in `source_embeddings_4096.py`
before enabling production: bind model content, native output width, pooling,
normalization, tokenizer, actual untruncated tokens, runtime/device and operation
lifetime. Coordinate access to the shared local model service; the old benchmark
restarts that service and is not an appropriate training producer. Then produce
the exact train/development/regression texts under a fixed verified profile and
choose a separate compatible decoder architecture. A larger supported-width tuple
or a caller-supplied provenance dictionary does not complete these steps.

The local run folder is
`workspace/test-logs/decoder-four-width-20261004`. It contains the sealed recipe,
readiness and representation audits, preflight, resource receipts and training
results. Final measured outcomes are recorded alongside the published evidence.

## Continuation and native producer follow-up

`scripts/ops/autoencoder/benchmark_formula_checkpoint_continuation.py` continues
the saved 8D baseline final attempt, 384D auxiliary selected state, and 768D
baseline final attempt. Each width has two preregistered learning-rate arms:
0.0001 and 0.001, with the existing non-action head multiplier of ten. Four
ten-epoch curriculum stages give 170 updates per arm. Targets, losses, auxiliary
sampling policy, 512-token limits and fidelity selection remain fixed. The
optimizer and scheduler start fresh; this is weight continuation, not an exact
optimizer resume. The representations remain cached, and the encoders and
historical 8D linguistic teacher are not fine-tuned by these formula-sidecar fits.

Before fitting, every restored parent's original development predictions must
match its saved outputs exactly. Separate postfit evaluation of the already
exposed R6 cohort cannot select a checkpoint or initiate another fit. The local
run folder is `workspace/test-logs/decoder-continuation-20261004`; it retains
failed preflights as well as successful attempts and resource receipts.

The new 4096D producer components are:

- `native/leanstral4096_worker.cpp` under the autoencoder package: a source-only
  CPU worker with separate vocabulary and full-forward modes, fixed single-source
  batching, last pooling, L2 normalization, token accounting and process cleanup.
- `scripts/ops/autoencoder/build_leanstral4096_worker.py`: builds against pinned
  existing native headers and CPU libraries without changing the shared backend.
- `source_embeddings_4096_native_owner.py`: a bounded, owned vocabulary-only
  operation. It never enables full-forward training or changes the shared service.
- `scripts/ops/autoencoder/probe_native_4096_sources.py`: under the resource
  guardian, builds the worker, runs compiled parser controls, and checks the 239
  exact existing paragraph/clause source strings. It submits no formulas or
  reference labels to the tokenizer.

Vocabulary-only loading does not initialize llama.cpp's runtime embedding-width
fields. Its receipt therefore reports those dimensions as null, alongside the
declared GGUF embedding metadata and actual untruncated token IDs. This distinction
must remain intact: successful tokenization is not an embedding, trained model,
semantic qualification, or Lake admission. The production `embed_rows()` gate
remains closed. The native run folder is
`workspace/test-logs/decoder-native-owner-20261004`.

Before a 4096D fit, a full-forward owner must verify the actual model content,
native output dimensions, device execution and operation lifecycle. It must then
produce same-source vectors under the fixed profile, release the large native
model, and train a separate compatible formula-sidecar lineage. The current
loader prefetches the 67 GB model; vocabulary-only success does not establish
enough memory headroom for this operation. Existing fixed-batch diagnostic
vectors, padded inputs and caller-written verification flags remain unsuitable.

### Continuation measurements

All six continuations completed 170 updates, for 1,020 new updates. Counts below
are exact paragraph reconstructions out of 48, compared with each chosen parent
endpoint. R6 is an already exposed regression cohort, not a fresh holdout. Values
after the arrow are the 0.0001 / 0.001 learning-rate arms' final attempts.

| Width | Development exact | Exposed R6 exact | Fit seconds, low / high LR |
| --- | --- | --- | --- |
| 8 | 1 → 1 / 1 | 0 → 0 / 0 | 27.87 / 27.05 |
| 384 | 48 → 48 / 48 | 28 → 29 / 30 | 39.52 / 39.99 |
| 768 | 46 → 48 / 48 | 47 → 48 / 48 | 49.74 / 49.58 |
| 4096 | Not trained | Not evaluated | Not measured |

Both larger widths selected their final states at epoch 40. The 8D lower-rate
arm selected epoch 4; its final attempt was rejected. The higher-rate 8D arm
retained its parent. At learning rate 0.001, exposed R6 token cross-entropy fell
from 0.02953 to 0.02169 for 384D and from 0.01840 to 0.00383 for 768D. The 8D
continuations did not establish an exact-reconstruction improvement.

Each fit presented 1,220 decoder rows. Wall seconds per row presentation were
0.02285/0.02218, 0.03239/0.03278 and 0.04077/0.04064 for 8D, 384D and 768D
respectively. These include the training call's development evaluations. They
exclude resource admission, external control panels and the separate R6 evaluator.
Inputs were warm cached representations, with one CPU worker, bridge names `[]`,
provers off and legal-IR metric disk cache off. No bridge-on evaluate ran. These
are continuation measurements on one shared host, not a from-scratch speedup.

The full six-fit guarded phase took 436.82 seconds; the separate R6 evaluator
took 27.61 seconds, or 107.62 seconds with admission and accounting. Maximum
sampled training process-group RSS was 1,090,940,928 bytes under a 4 GiB
reservation. All successful reservations released normally. Earlier failed
setup attempts remain recorded and charged; the 140 GB campaign cap did not
change. A guardian-local adoption fix now reads the shared scheduler configuration
after the storage census, immediately before admission, and pins that one client.
It does not reset shared state or reacquire after a changed active lease.

The native 4096D vocabulary probe also completed: seven compiled parser controls
passed, and all 239 sources fit without truncation at 8–74 tokens. Vocabulary
loading and tokenization took 0.49041 seconds (0.00205 seconds per source), with
244,211,712 bytes maximum sampled child RSS. Build, controls and probe took
6.28 seconds; the guarded attempt took 70.66 seconds. OS cache warmth is
uncontrolled. These are tokenizer-preflight timings, not formalization or
embedding-inference throughput. The GGUF declares `deepseek2.embedding_length`
4096 and has no separate output-width declaration; runtime widths remain
unobserved. The existing model and all seven native controls produced zero
training vectors. Its independent saved-evidence audit passed 3,658 checks.

### Separate 8D object projection experiment

`isolated_object_clause_decoder_experiment.py` adds an opt-in 8D formula-sidecar
schema with a private 8-to-64 object projection, cloned from the existing shared
projection. It adds 576 parameters. Actor/modality and recurrent features keep
their existing paths; the readout, labels, loss reductions and selection gates
are unchanged. The strict trainer, action loss and boundary helper recognize the
explicit new schema. Existing schemas retain their previous behavior.

The guarded comparison in `workspace/test-logs/object-projection-r2-20261004`
ran 340 updates per arm. Original and isolated models reproduced the saved
initial predictions exactly before fitting. Final training exactness changed
9→10/48 and development exactness 1→2/48, but both arms retained their initial
selected checkpoint. The isolated head reduced raw training object accuracy
112→100/180 while increasing development object accuracy 91→98/180. Generated
development object accuracy increased 88→102/180; this mixed result does not
establish an object-learning improvement.

Fit wall time increased from 46.00 to 51.25 seconds for 2,440 decoder-row
presentations: approximately 0.01885 versus 0.02101 seconds per presentation.
The full guarded pair took 167.71 seconds. It used the same warm inputs,
one CPU worker, empty bridge list, disabled provers and disabled metric disk
cache. No separate R6 evaluation ran for this rejected experimental head.
It remains an explicit experiment, not a production default or a replacement
for the historical linguistic teacher.
