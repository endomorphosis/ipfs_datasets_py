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
