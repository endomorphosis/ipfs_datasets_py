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

## Additional head training and native 4096D preparation

These follow-ups train formula-sidecar decoders and projections over fixed source
representations. They do not fine-tune the native semantic encoders or replace
the historical 8D linguistic teacher. Context and decoder output limits remain
512 tokens, temperature remains zero, and fidelity selection is unchanged.
Exact authored reconstruction, lower loss, syntax validity and successful native
execution are distinct from semantic qualification. None is a Lake admission.
No checkpoint in these follow-ups is promoted as formalizing federal law.

### Matched 8D auxiliary objectives

`benchmark_object_auxiliary_continuation.py` compares no auxiliary loss, a
modality auxiliary loss at 0.05, and an object auxiliary loss at 0.05. All three
start from the same saved 8D endpoint, use the existing architecture and fresh
optimizer, and complete 170 updates. The two auxiliary arms receive the same
six source identities per update: 1,020 presentations each. Targets, ordinary
losses, original development selection and all nine control panels are retained.
The no-auxiliary endpoint reproduces its recorded R10 counterpart exactly.

| Auxiliary objective | Final training exact / 48 | Final development exact / 48 | Generated training objects / 180 | Generated development objects / 180 | Fit seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| None | 12 | 1 | 116 | 97 | 25.88 |
| Modality, 0.05 | 12 | 1 | 114 | 96 | 26.47 |
| Object, 0.05 | 14 | 1 | 119 | 94 | 25.51 |

All three retain their initial selected checkpoint. The object objective improves
some in-sample reconstruction while reducing development object accuracy. Its
raw object-head development accuracy also falls from 88 to 84/180 relative to
the no-auxiliary arm, despite slightly lower raw object cross-entropy. This is
not evidence that the 8D fidelity gap is solved. Each fit presents 1,220 decoder
rows, giving 47.14, 46.09 and 47.83 presentations/second respectively. Those
rates include in-call development evaluations, not resource admission or the
separate control-panel measurements. The full guarded phase takes 241.99 seconds
and releases normally. Saved evidence is under
`workspace/test-logs/decoder-object-auxiliary-20261004`.

### New authored style observation and selected-parent continuation

A separate authored style cohort contains 48 paragraphs, 180 unique clauses and
216 unique paragraph/clause source strings. It uses the
`actor_normative_status`, `gerund_normative_subject` and `norm_noun_subject`
template families. Verified local 384D/768D encoders produce its fixed source
vectors under the existing 512-token limit; no weights are downloaded. Its first
observation of the preselected R10 higher-rate endpoints gives 19/48 exact for
384D and 46/48 for 768D. These are authored examples, not a statutory holdout or
legal semantic validation. After that observation, the cohort is exposed and
subsequent scores are regression measurements.

`benchmark_selected_checkpoint_continuation.py` then starts from those exact R10
selected states and runs 170 further updates per width. Before updates, restored
tensors and original development predictions must match the parents exactly.
The optimizer and plateau scheduler start fresh at base learning rate 0.0001,
with the inherited non-action head multiplier of ten. The 384D arm keeps the
existing used113 modality auxiliary loss; the 768D arm keeps its previous losses.
The recipe is fixed rather than tuned in response to the style scores. Both
widths retain 48/48 exact on original development and select their final states
at epoch 40.

| Width | Original development token CE, parent → continuation | Exposed style exact / 48 | Exposed style token CE, parent → continuation | Fit seconds | Decoder presentations/second |
| --- | --- | --- | --- | ---: | ---: |
| 384 | 0.003976 → 0.002534 | 19 → 20 | 0.029584 → 0.030021 | 38.16 | 31.97 |
| 768 | 0.003655 → 0.002472 | 46 → 46 | 0.005471 → 0.004246 | 47.79 | 25.53 |

Selected and final style outputs agree within each width. The 384D gain is one
corrected modality: 137→138/180, with action accuracy unchanged at 178/180.
Its slightly worse cross-entropy makes the result mixed. The 768D modality and
action counts stay at 178/180 and 180/180, with improved cross-entropy. None of
these observations proves general convergence or a global minimum.

The evaluator persists all four source-only greedy prediction panels before
opening style references. The score phase uses the saved predictions and a
separate teacher-forced loss calculation; it cannot train or select a checkpoint.
Greedy generation takes approximately 0.00782 and 0.00914 seconds per span for
384D and 768D selected states, on 48 spans each. These times exclude encoder
production, scoring, model restoration, admission and accounting. Inputs are
warm cached representations, worker count is one, bridge names are `[]`, provers
are off and the legal-IR metric disk cache is off. No bridge-on evaluate occurs.

The guarded training phase takes 198.25 seconds and its maximum sampled process
group RSS is 1,055,072,256 bytes, from nine samples under a 1.5 GiB reservation.
The successful exposed evaluation takes 63.99 seconds including its guardian;
its maximum sampled RSS is 798,687,232 bytes. These are sampled observations,
not continuously measured peaks. Successful attempts release their leases and
accounted storage. The evaluation retains a pre-import command-path failure and
a separate preadmission ValueError; neither executes a model. The failure-time
configuration and actor of the latter are not established. Saved evidence is
under `workspace/test-logs/decoder-selected-continuation-20261004`, with the
source-cache study under `decoder-fresh-normative-style-r2-20261004`.

### Private native owner, memory limits and failed V2 pilot

The new private CPU backend copies the authenticated local llama.cpp revision
and changes only the loader's eager mapping argument from true to false. It
disables eager model prefetch and CPU extra buffers without changing the shared
checkout, service or existing backend. The resulting profile is explicitly
`leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2`; equivalence
with the older batch profile is not assumed.

`leanstral4096_authorized_worker.cpp` emits an entry receipt and waits before
loading the model. The full owner verifies the held model descriptor and content,
executable and actual executable library mappings, and bounded process/cgroup
membership before authorizing load. The worker later requires a closing
acknowledgment so mappings and operation identity can be rechecked while it is
still alive. CPU execution, actual native output width and complete untruncated
tokens must be observed; a caller-written receipt cannot open the gate.

The private build completes in 137.95 seconds, or 453.76 seconds with admission
and accounting. It runs under a 2 GiB hard cgroup limit with swap disabled; kernel
memory charge peaks at 866,152,448 bytes, with no OOM event. Kernel charge is not
process RSS. The declared four-process build estimate was exceeded by the
observed five-process compiler chain, and sparse guardian RSS samples miss the
compiler peak; neither limitation is hidden. Seven compiled negative protocol
controls pass without valid model authorization. They do not exercise a real
embedding or the successful closing handshake. The first build's rejection of
CMake library symlinks is retained; the revised isolated packaging uses regular,
byte-identical library alias copies. No native compiler or linker flags are
changed by that packaging fix.

The subsequent two-source V2 full-forward pilot verifies the local model content
and authorizes the worker, but stops at the combined owner/native 8 GiB RSS
limit before emitting any vector. Owned cleanup succeeds. It performs zero
4096D training updates and supplies no validated embedding output. Disabling
eager prefault alone therefore does not establish an acceptable resident-memory
profile. File-backed pages can contribute to process RSS even when their cgroup
charge belongs elsewhere. The hard cgroup limit and the independent RSS guard
remain enforced. Build and failure evidence live under
`native4096-low-resident-r2-20261004` and
`native4096-four-width-20261004` in `workspace/test-logs`.

### Native 4096D head pilot and retained failures

The final guarded run produces three real 4096D vectors: two original training
clauses and a repeat of the first after clearing the KV state. The repeat L2
difference is 0. It verifies the entire local 67.1 GB model,
actual executable/library mappings, source/token bindings, CPU observations,
36 synchronized layer completions per row, and the closing acknowledgment.
The exact profile is `leanstral4096:cpu1:last:l2:single-sequence:tokens512:layer-reclaim:v3`. This work does not modify the shared service.

The worker releases only its own authenticated read-only model mappings after
completed layers. It neither changes model bytes nor evicts the shared file cache.
Two subsequent guard failures are retained: this backend floors idle performance
counters at one and leaves ordinary CPU buffer device pointers null. The fixed
accounting retains raw counts/timings and derives only the provably idle branch.
CPU evidence uses exact registered CPU buffer-type identity; unknown buffers stay
unknown, known non-CPU buffers fail, and positive recognized CPU evidence is required.
A real tiny CPU graph exercises that path before the final model run. These are
compatibility fixes, not relaxed semantic or resource thresholds.

A separate 4096D-to-GRU formula head then completes 20 AdamW updates
on the two training clauses, starting from copied donor token/recurrent weights
and newly initialized source-conditioning paths. Training token cross-entropy
changes 2.79595 → 1.56058,
and exact training reconstruction changes 0 → 0/2.
Final zero-source CE is 0.342045 and rotated-source
CE is 1.56308. This pilot has no holdout,
selection or promotion. It is not architecture parity with the factorized
8D/384D/768D heads, encoder fine-tuning, or production `embed_rows()` readiness.
Its saved weights omit optimizer state and are not an exact optimizer resume.

The zero-source control is substantially better than the conditioned model, and
both conditioned training rows remain inexact. Consequently, this run establishes
actual native execution and decoder updates; it does **not** establish useful
source conditioning, reconstruction fidelity, or convergence. Improving and
evaluating this head is a remaining training gap.

The head fit takes 0.141951 seconds for 40 row
presentations. The owned embedding operation takes 97.527 seconds
for three requested rows, including 82.221 seconds
hashing the full model; the native child takes 15.304
seconds including initialization and ownership checks. That is
32.509 seconds per requested row including the repeat and
integrity work, not a steady-state forward benchmark. Maximum sampled combined
Python/native RSS is 1,091,571,712 bytes under the unchanged
8 GiB RSS and cgroup limits. Page-cache warmth is uncontrolled. One CPU worker,
bridge names `[]`, provers off, metric disk cache off, and no bridge-on evaluate.
All successful resources release; failed claims remain charged and archived.
Evidence is in `workspace/test-logs/native4096-layer-reclaim-pilot-r3-20261004`.

The campaign storage allocation was separately raised from 140 to 145 GB under
the ledger lock, using the user's existing allocation authorization. All 427
reservation records and tracked roots were preserved, and no reservation was
active during the migration. The original frozen resource owner remains intact;
new guardians bind the exact new owner copy. This is disk allocation, not an
increase to native RAM, encoder context or qualification thresholds. The migration
receipt is `native4096-four-width-20261004/resource-cap/receipt.json`.


## Source conditioning and field-head update rates

These opt-in experiments address the remaining 8D/4096D gaps without changing
production defaults. The 384D/768D selected checkpoints are preserved. They train
decoder heads over frozen source representations; the historical 8D linguistic
teacher and protected restart12 checkpoint remain unchanged. All codec, context,
selection and admission constraints above still apply.

### Native 4096D matched conditioning comparison

`native4096_conditioning_experiment.py` and
`benchmark_native4096_conditioning.py` compare three fresh heads against the same
copied GRU/token prior. A single authenticated native operation produces the two
original TRAIN clauses plus an A/B/A reset repeat. Each arm receives the same
live owner capability and completes 200 updates. No serialized receipt can
substitute for that capability. The first 20 baseline updates reproduce the previous real losses and
predictions; a separate numerical control also verifies exact 20-update tensor
parity. The new native vectors match the prior operation exactly.

The source-scaled arm divides source-weight learning rate by the maximum L1 norm
of the centered, radius-normalized TRAIN vectors. This input-only statistic is
34.218689, giving a source-weight rate of approximately 0.000029224 instead of
0.001. Source bias and copied-prior rates stay 0.001. The scaling limits the
initial Adam activation jump; it is not a bound on all later adaptive updates.
The third arm combines this scaling with a 40-step frozen-prior phase and a
training-loss plateau scheduler. No plateau reduction triggers in this run.

| Arm | Token CE at update 20 | Final conditioned CE | Final zero-source CE | Final swapped-source CE | Final exact / 2 | Fit seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Unscaled joint fit | 1.560576 | 0.018791 | 0.032571 | 0.048023 | 2 | 1.502 |
| Source-scaled joint fit | 0.140675 | 0.015291 | 0.025506 | 0.085754 | 2 | 1.369 |
| Source-scaled, frozen-prior warmup and plateau | 1.919495 | 0.026482 | 0.026882 | 0.027370 | 2 | 1.349 |

All three are exact on the two conditioned training clauses at the measured
100- and 200-update panels. At update 200, every zero-source panel is exact on
one clause and every swapped-source panel is exact on zero. Source scaling
lowers final training CE by 18.6% relative to the matched unscaled fit; the
staged intervention performs worse and is not adopted. This demonstrates
source-conditioned fitting of two authored clauses differing only in object
("archive"/"notice"). It does not demonstrate held-out fidelity, other logic
families, encoder convergence or a global minimum. No head is promoted.

For “The registrar may deliver the archive.” the source-scaled head emits:

```json
{"rules":[{"action":"deliver","actor":"registrar","conditions":[],"exceptions":[],"modality":"P","object":"archive","temporal":[]}]}
```

The second output changes only `object` to `notice`. This is the learned
restricted rule codec's output, not validation of the full legal logic families.

Each fit presents 400 decoder rows, taking approximately 0.00376, 0.00342 and
0.00337 seconds per presentation. These timings include control generation and
extra post-update loss measurements and are not comparable to the older
20-update pilot's leaner fit timing. The native operation takes 121.828 seconds
for three requested rows (40.609 seconds per row), including 88.299 seconds to
hash the existing 67.1 GB model. Native child time is 33.527 seconds. Maximum
sampled combined owner/native RSS is 1,082,535,936 bytes under the unchanged
8 GiB guards. The full guarded phase takes 255.101 seconds and releases normally.
One CPU worker, bridge names `[]`, provers off, metric disk cache off; native
page-cache warmth is uncontrolled. No bridge-on evaluate or Lake build runs.

The next 4096D validation needs source-disjoint training/development cohorts
covering actors, modalities and actions, using the same live native-owner gate.
The two-source result is insufficient for production or distillation promotion.
Evidence: `workspace/test-logs/native4096-conditioning-20261004`.

### 8D optimizer-rate follow-up

`benchmark_eight_dimensional_head_rate.py` tests a smaller learning rate for the
shared actor/modality/object head, without changing the historical 8D source
features, architecture, source normalization, losses or fidelity selection. Both
arms start from the same saved R9 final attempt and retain the same two-group
AdamW implementation. The base learning rate stays 0.001; the head multiplier
is ten for the baseline and two for the candidate. This also changes the
rate-scaled decoupled weight decay, while preserving the inherited scheduler
and proportional learning-rate floors. Each fit executes 170 updates and 1,220
paragraph presentations. Full vocabulary size remains 32, context and output
limits remain 512, and temperature remains zero.

Saved-data diagnostics find 113 distinct training clause vectors and 54 distinct
development vectors, with no exact collisions or cross-split literal overlap.
The parent's source projection is not initially saturated: none of its 7,232
training or 3,456 development activations has absolute tanh output at least
0.99. These checks do not establish semantic sufficiency. Object substitutions
remain weakly separated in the cached historical feature representation: 34
training archive/notice pairs have mean raw-vector L2 distance 0.01564. The
24 development pairs average 0.01615. This confirms the earlier source-head
geometry concern; it does not diagnose the preserved linguistic teacher itself.

| Head multiplier | Final training exact / 48 | Final development exact / 48 | Development token CE | Generated development objects / 180 | Fit seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10, baseline | 12 | 1 | 0.16349 | 97 | 28.12 |
| 2, candidate | 17 | 1 | 0.14803 | 88 | 27.56 |

The lower head rate reduces development token cross-entropy by approximately
9.5% relative to the paired final baseline. Its improvement against the original
parent CE of 0.14907 is approximately 0.7%. It fails to improve exact
reconstruction and loses object fidelity.
Both arms therefore retain their parent at selected epoch zero. The candidate
is not adopted as a training default. Its in-sample exact count does not
establish held-out improvement. The baseline reproduces the R11 selected and
final tensor hashes exactly, and both arms use identical decoder/count batches.

Fit throughput is 43.38 versus 44.27 paragraph presentations per second.
These one-seed, shared-host observations are not a demonstrated speedup.
Development numerical evaluation takes approximately 0.00675 and 0.00714
seconds per span for the two final attempts, over 48 spans each, excluding
source-encoder production, control-panel scoring and admission. Inputs are warm
cached vectors, with one CPU worker, bridge names `[]`, provers off and metric
disk cache off. No bridge-on evaluate runs, and no legal-IR throughput is claimed.

All 36 selected/final control panels are retained. The guardian finishes in
141.50 seconds and releases normally, retaining 110,690,588 bytes under the
300 MB reservation. Maximum sampled process-group RSS is 1,075,511,296 bytes
under a 1.5 GiB reservation; this is not a continuously measured peak. Thirty
focused tests pass. The same-author arithmetic audit checks 83,422 conditions;
the independent saved-data audit passes 79,901 checks, including all 36 panels,
paired exposure, baseline replay and resource release.
Evidence is under `workspace/test-logs/decoder-eight-head-rate-20261004`.
No native encoder or protected teacher weights change. No new holdout, production
promotion, general convergence claim, logic-family qualification or Lake
admission results from this experiment.

### Preserved 384D/768D checkpoints and remaining coverage

No further larger-width fitting runs in this comparison. An independent audit
of the previously exposed style outputs finds 42 modality errors for 384D:
40 obligations become permissions and two become prohibitions. It also finds
two action errors, while actors and objects remain correct on all 180 clauses.
The 768D output has two permission-to-obligation errors in authorization wording.
These are aggregate observations of an already exposed cohort, not new holdout
results. The original development scores and selected checkpoints are preserved.

The next larger-width training comparison should add balanced paraphrases built
from original TRAIN rule tuples and reserve separate wording constructions for
evaluation. Evaluation sources and target labels must not become training rows.
Simply continuing the existing narrow wording distribution did not resolve this
gap. The independent census is saved in
`workspace/test-logs/decoder-next-source-review-20261004/exposed-style-review.json`.

The implementation, raw fits, controls, source/recipe manifests, independent
reviews and resource receipts from these follow-ups are published under
`docs/implementation/reports/evidence/decoder-conditioning-20261004`. That
archive references the preceding published evidence for unchanged encoders and
frozen dependencies. It includes no pretrained model weights. Only an actual
`lake build <Lib>` can provide Lean admission; none is claimed here, and the
Constitution remains unformalized.


## Balanced development and source optimization follow-up

This follow-up completes 740 decoder-head updates: 340 across two 8D arms and
400 across two 4096D arms. Source encoders and the historical 8D linguistic
teacher stay frozen. These are authored-fixture experiments, with different
cohorts and head architectures; their scores do not rank the widths against one
another. No new 384D or 768D head fit is included in this update count.

### Corrected 8D geometry and rejected covariance candidate

The previous geometry diagnostic omitted the frozen input center/RMS transform
before clause normalization. Actual training and inference already used the
correct preprocessing, so predictions, losses and selected weights are
unaffected. The corrected diagnostic follows the input transform, verified
identity residual projection, clause normalization, source affine projection
and tanh in their real order. Maximum absolute preactivation is 2.07906 on
training clauses and 1.90407 on development clauses. Both still have zero tanh
activations with absolute value at least 0.99. Old evidence is preserved; the
correction is recorded in `geometry-erratum.json`.

The historical codec maps both `lemma:archive` and `lemma:notice` to bucket 2,
with different positive contributions, before normalizing the complete feature
sum. Their complete vectors remain distinct, but the object difference is
small. This observation concerns this preserved feature representation, not
all possible 8D models or the fidelity of the historical linguistic decoder.

The new optional preconditioner computes an inverse covariance using only the
113 original TRAIN clause features after the real preprocessing path. Its trace
is normalized to 8 and its condition number is bounded by 32; the observed
condition number is 21.0394. It transforms only the source-projection gradient
before the existing global clip and AdamW step. It changes no forward function,
loss or selection gate, and the default training path remains unchanged.

| 8D gradient policy | Updates | Final TRAIN exact / 48 | Final development exact / 48 | Development token CE | Development objects / 180 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Identity control | 170 | 12 | 1 | 0.163492 | 97 |
| TRAIN covariance inverse | 170 | 12 | 1 | 0.168503 | 93 |

Both arms retain their original parent at selected epoch zero. The covariance
candidate worsens development loss and object fidelity and is not adopted.
The identity arm reproduces the archived baseline tensors exactly. All nine
control panels are retained for each selected and final attempted endpoint.

Fit times are 25.93 and 25.20 seconds for 1,220 paragraph presentations per arm.
Development numerical evaluation takes 0.00619 and 0.00638 seconds per span over
48 spans, excluding source production and admission. The full guardian takes
160.67 seconds and releases normally; maximum sampled process-group RSS is
1,087,111,168 bytes under 1.5 GiB. These one-seed shared-host observations do not
establish a speedup. Sources are warm cached vectors, one CPU worker is used,
bridge names are `[]`, provers are off and metric disk cache is off.

### Broader 4096D reconstruction remains incomplete

A single authenticated native operation produces 12 original TRAIN clause
vectors, 12 exposed original-development vectors and one reset repeat. Both
splits cover all five actors and actions, all three modalities and both objects.
Selection is deterministic and independent of model scores. The original banks
have disjoint normalized source text, identities and actor/action combinations.
Development is an already exposed regression set, not a new holdout.

Two fresh heads receive 200 updates each, comparing the original source-weight
rate against TRAIN-input-L1 scaling. Normalization and rate scaling use TRAIN
vectors only. Development vectors and targets cannot affect updates, rate
selection or normalization, and no checkpoint is selected from their scores.

| 4096D source rate | Final TRAIN exact / 12 | TRAIN CE | Final development exact / 12 | Development CE | Development zero-source CE | Development rotated-source CE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original | 7 | 0.070717 | 0 | 0.137379 | 0.143009 | 0.174185 |
| TRAIN-input-L1 scaled | 1 | 0.109239 | 0 | 0.131200 | 0.138967 | 0.141804 |

The scaled rate modestly lowers development token CE but fits fewer TRAIN rules.
Neither arm reconstructs a development rule exactly. Its earlier two-source
training benefit therefore does not justify making it the default. The restricted
rule parser accepts 11/12 development outputs for the original rate and 12/12
for scaling. Final development actor/action/modality/object counts are only
4/12, 2/12, 6/12, 8/12 for the original rate and 3/12, 1/12, 4/12, 8/12 for
scaling. Shared rule syntax accounts for much of whole-sequence token loss;
low CE alone does not demonstrate correct logical fields.

Each fit presents 2,400 TRAIN rows and 93,600 target tokens, taking 1.430 and
1.413 seconds including scheduled control measurements. The native operation
takes 416.273 seconds for 25 rows, or 16.651 seconds per requested row including
the repeat and integrity work. This includes 95.115 seconds hashing the model
and 321.156 seconds in the native child. The full guardian takes 532.280 seconds
and releases normally. Maximum sampled combined owner/native RSS is
1,234,501,632 bytes under unchanged 8 GiB guards. Page-cache warmth is
uncontrolled; one CPU worker, bridge names `[]`, provers off and metric disk
cache off. This IO-sensitive run is not a matched speed comparison against the
previous three-row pilot. No bridge-on evaluate timing is measured.

### Balanced TRAIN paraphrases for 384D and 768D

`authored_training_paraphrases.py` derives 180 clauses in two fixed wording
families from the original 90 TRAIN rules and their 180 source records. Each
derivation retains the original IDs and source/target hashes. No development,
test or canary target is added to training. The resulting 48 paragraphs contain
1, 2, 4 or 8 clauses, with 12 paragraphs per length and balanced O/P/F counts.
Packing keeps different modalities of the same actor/action/object content out
of a single paragraph. The canonical target vocabulary remains all 32 tokens.

The wordings include “The rule forbids delivering the archive by the registrar.”
and “For the registrar, delivering the archive is forbidden by the rule.” These illustrate
the templates; they are authored TRAIN paraphrases, not model predictions or new
legal coverage. Every actual target is copied from the original TRAIN bank and
passes the restricted rule syntax validator. The second construction extends an
already exposed style, so literal separation does not imply an unseen linguistic
family. Ten declared source inventories, including raw splits, paragraph splits
and exposed R6/R8/v3 sources, are checked at paragraph and clause level.

`training_paraphrase_source_inputs.py` sends only closed source rows to the
existing verified local encoders. Its explicit TRAIN plan/report and 384D source
metadata distinguish these inputs from evaluation. The inherited setup reads
old experiment metadata; only original TRAIN labels reach the builder and no
labels enter the encoder calls. Each encoder produces 216 unique vectors: all
180 clauses plus the additional multiclause paragraphs. These are new local
forward results, with zero literal source overlap against the declared prior
inventories and zero exact vector overlap against the available prior caches.
The 384D vector check covers 911 unique prior vectors; the 768D check covers
671. No 768D R8 vector artifact exists in this inventory; it is not silently
included in the coverage claim.

| Encoder width | Unique source inputs | Native production seconds | Seconds per unique source |
| --- | ---: | ---: | ---: |
| 384D | 216 | 8.679 | 0.04018 |
| 768D | 216 | 26.969 | 0.12486 |

The complete driver takes 52.560 seconds; the outer guardian invocation takes
84.489 seconds, with 83.158 seconds measured inside its admission/accounting
body. Batch size is four with one CPU worker. Context
and output limits remain 512, bridge names are `[]`, provers and metric disk
cache are off. OS page-cache warmth is uncontrolled; no bridge-on evaluate runs
and these timings do not measure formalization or prove a speedup. Maximum
sampled process-group RSS is 2,716,860,416 bytes under the 4 GiB guard. The
successful attempt releases its reservation and retains 20,761,283 bytes.

`prepare_training_paraphrases.py` now validates the inherited context, producer
loads and source inventory before creating its output directory. Four lifecycle
controls cover success and initialization failures, and all 41 focused controls
pass. The first freeze was superseded before execution because its paragraph
packing could combine conflicting modality variants. Two guarded startup
failures are preserved: early directory creation and a missing exact parent
producer pin. Both occurred before encoder execution; their 250 MB disk claims
remain charged and their compute leases are released. The corrected fourth
freeze completes. No guard, storage cap or qualification rule is weakened.

Evidence is in `workspace/test-logs/decoder-training-paraphrases-r4-20261004`,
with all earlier attempts retained alongside it. Source rows, targets, original
TRAIN derivations, token observations, raw vectors, clause contexts and native
receipts are separate artifacts. This phase fits no normalizer or head, scores
no evaluation panel and changes neither selected larger-width checkpoint. The
next comparison must pair original-only and augmented TRAIN exposure under a
predeclared budget and unchanged development selection/control panels; these
prepared vectors alone are not a training improvement. The existing trainer binds
its preprocessing and count-prior receipts to the exact original cohort, so
concatenating rows would correctly fail. An explicit mixture interface must
retain that preprocessing provenance while authenticating the separate rows
and contexts used for optimization.

The 8D paths pass 137 focused/regression tests and 169,385 independent saved-data
checks; the 4096D paths pass 47 tests and 4,717 independent checks. Initial failed
test/audit attempts remain archived. Evidence is under
`decoder-eight-source-preconditioning-20261004` and
`native4096-balanced-cohort-20261004` in `workspace/test-logs`; the latter also
contains every final emitted TRAIN/development rule in
`decoded-balanced-examples.json`.

Encoder context and decoder output limits remain 512, temperature remains zero,
and no weights are downloaded. These fits provide no fresh-holdout gain,
convergence result, global minimum, full logic-family qualification or production
promotion. Restricted rule-codec parsing is not a Lake admit. Only an actual
`lake build <Lib>` can provide that admission; none is claimed here, and the
Constitution remains unformalized.

Code and complete evidence are published under
`docs/implementation/reports/evidence/decoder-generalization-20261004`.
The archive retains prior attempts, failed hypotheses, source manifests and
independent reviews, and references the preceding archive for unchanged frozen
dependencies. Pretrained weights and private native binaries remain external.
