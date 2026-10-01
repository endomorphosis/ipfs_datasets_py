# Four-domain native reconstruction training

The shared interface covers `intent_ir`, `security_ir`, `ui_ux_ir`, and `legal_ir`,
with independent weights, vocabularies, projections, provenance, and split
histories. It reconstructs supplied native logic features. The existing learned
source-language decoders remain separate; their formula fidelity is not measured
by this feature loss. Existing v1/v2 trainers, the 8D linguistic decoder, and the
384D latent-to-formula runtime are unchanged.

## Run training and inference

Use the pinned package checkout, with thread limits set before importing Torch
or NumPy. A bare editable import can resolve to HACC instead.

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
export PYTHONPATH="$PWD"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export CUDA_VISIBLE_DEVICES=''
```

```python
from pathlib import Path
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    domain_family_training_prepared as training,
)

result = training.train_domain_family_autoencoder(
    "intent_ir", training_rows, tuning_rows,
    output_dir=Path("workspace/my-intent-candidate").resolve(),
    numerical_backend="prepared",  # explicit; default remains "v2"
    requested_families=None,        # inventory all 40; fit actual ready targets
    epochs=12, latent_width=16, minibatch_size=32,
    learning_rate=.001, denoising=.05, ridge=.001,
    patience=4, seed=1729, max_seconds=120,
)
assert result["report"]["status"] == "complete", result["report"]["family_error"]
inferred = training.infer_domain_family_autoencoder(result["descriptor"], evaluation_rows)
assert inferred["training_steps"] == 0
```

Directories must be fresh, absolute paths. Every input row is a closed mapping:

```python
{
    "source_id": "immutable-row-identity",
    "group_id": "document-or-application-group",
    "split": "train",  # validation/tuning for selection; test only for inference
    "inputs": {...},
}
```

| Domain | Required native `inputs` |
|---|---|
| Intent | `document`: complete rich AST; `source_text`: exact instruction accepted by the native grammar. Optional `context` and `supplemental_inputs`. |
| Security | `code_unit`: native `CodeUnit`; `source_bytes`: exact body; `typed_inputs`: native `CodeLogicEvidence` records. Optional `supplemental_inputs`. |
| UI/UX | `ui_training_row`: validated DOM/ARIA, verified interface descriptor and binding, declared behavior and event provenance. Optional `supplemental_inputs`. |
| Legal | `document`: `CanonicalRoundTripIR`, `ModalIRDocument`, or `MultiViewLegalIRReport`; `source_text`: exact source. Optional `supplemental_inputs`. |

Labels, model scores, or family names do not substitute for typed inputs.
Supplementary models use `TypedFamilyEvidence` and its exact source join.
Unverified events remain supplied observations. A UI timeout cannot become an
untimed state transition by dropping its timing semantics.

`prepare_domain_family_rows(...)` runs preflight without fitting.
`load_domain_family_recipe(descriptor)` verifies metadata and model provenance.
`infer_domain_family_autoencoder(...)` reads saved weights only. This API does
not generate source formulas, populate a supervisor, publish to the Hub, or
promote a model. Existing Security joint/source and Intent aligned-source
training entry points remain intact; source-stage options cannot silently enter
this structural-only API.

For continuation, supply the previous recipe as `parent_descriptor` and a new
output directory. Domain, backend, projection basis, fixed tuning panel,
producer versions, and historical source/group separation must match. Intent
also quarantines complete AST and tokenized full-source aliases, while allowing
known atoms in new compounds. Bare numerical checkpoints cannot be adopted by
this recipe without their domain split history. The low-level prepared trainer
can separately inherit complete compatible v1/v2 numerical heads.

Continuation currently starts fresh Adam; it is not an optimizer-cursor resume.
`max_seconds` bounds the existing optimization phase, not target preparation,
serialization, or the complete call. The atom cache has 8,192 entries per call,
not a total RSS byte cap. Workers should own separate candidate directories.
These APIs do not create another DuckDB writer or change sparse publication.

## Objective and optimization

Loss averages MSE plus `0.1 * cosine_loss` within each native projection, then
within each family, then across families. Missing targets are masked.
Population-frequency correction preserves this weighting in minibatches.

V2/prepared first fit a training-only ridge correction to decoder blocks.
Tuning can select improved families independently while the encoder is fixed.
Joint Adam refinement uses 75% clean and 25% denoised reconstruction, warmup,
cosine learning-rate decay, clipping, and tuning patience. A candidate must
improve aggregate tuning loss without regressing any selected family. Held-out
rows do not enter vocabulary fitting, updates, or selection.

Prepared execution caches structural atom serialization and prepares minibatch
masks/family denominators once. It avoids detailed metrics discarded by the
training loop. Loss arithmetic, gradients, selection, and retained tensors match
v2 exactly in the paired tests. Temperature, context and proof gates are unchanged.

## Logic coverage

The catalog contains 40 canonical families. Existing target adapters have
potential native routes for 15 Intent, 9 Security, 8 UI/UX, and 6 Legal families.
Successful source-bound native evidence is still required. Registry presence
elsewhere in `logic/` is not enough to establish domain training support.

`logic.formalization.autoencoder.family_coverage_audit.audit_family_training_coverage`
accepts separate training/tuning/held-out reports, actual numerical training and
inference receipts, and explicit `required_families` and `required_profiles`:

```python
required_profiles = [{"family_id": "transition_system", "profile": "tla_plus"}]
```

The audit inventories all 40 families, validates producer pins and split
identities, checks native/numerical coverage, and counts unknown atoms. Missing
fitting evidence cannot pass the numerical floor. This is receipt-consistency
validation, not checkpoint execution or authentication; retain actual execution
receipts with it. It does not establish source semantics or qualification.

Do not expand aliases into extra coverage. An older Legal `cec`/`dcec` alias maps
to `event_calculus`; it cannot satisfy a required `dcec` family. Likewise
`tdfol/temporal_first_order` does not establish every temporal/deontic composition.
A generated TLA+ artifact is not a TLC verification.

Exact profile audits found `transition_system/tla_plus` targets in Intent and
UI/UX. Security's trained profile is `transition_system/action_system`; an
embedded TLA artifact does not establish a separate trained TLA+ projection.
Legal's `tdfol/temporal_first_order` profile is present structurally. Complete
DFOL and cognitive-CEC compositions remain unverified. Separate retained profile
audits add these distinctions without changing the frozen experiment.

The authored panel exercised all ready projections in these families:

| Domain | Numerically trained and covered on held-out features |
|---|---|
| Intent | first_order, deontic, dcec, tdfol, frame_logic, program, temporal, transition_system, datalog, horn_chc, higher_order |
| Security | program, transition_system, temporal, separation_logic, hyperproperty |
| UI/UX | frame_logic, event_calculus, tdfol, dcec, transition_system, temporal |
| Legal | deontic, frame_logic, tdfol |

Other requested families remain explicit in the frontier. The complete coverage
floor is false for all four panels. Legal does not establish the complete FOL,
DFOL, TFOL, TDFOL, cognitive CEC, DCEC, frame and propositional floor. More native
evidence/adapters are needed; missing formulas are not fabricated.

## Held-out reconstruction

Each domain has 24 training, 8 tuning, and 8 held-out authored rows. Related
actor/action pairs and both variants stay together across splits. These are four
held-out composition groups, not eight independent real-world documents. All
actors and actions already occur in training.

All 24 candidates (four domains, three seeds, reference/prepared) were frozen
before any held-out target was generated. Each fit used 24 epochs, 96 updates,
batch 6 and latent width 8. This width is for an auxiliary feature head; it does
not replace either legal autoencoder lineage.

| Domain | Initial objective | Trained mean objective | Reduction | Distinct held-out feature vectors |
|---|---:|---:|---:|---:|
| Intent | 0.0001352171 | 0.0001278817 | 5.42% | 8/8 |
| Security | 0.0001615739 | 0.0001612234 | 0.22% | **2/8** |
| UI/UX | 0.0005844967 | 0.0005419430 | 7.28% | 8/8 |
| Legal | 0.0000130895 | 0.0000104714 | 20.00% | 8/8 |

No measured family regressed against the training-only initializer. Reference
and prepared weights, histories, selection and held-out results matched exactly.
The quality gain is training versus initialization, **not** prepared versus v2.
Unknown held-out atoms are omitted by this feature codec; Security's collision
makes its small improvement weak evidence of generalization. These are not exact
typed-declaration, formula-generation, or source-decoder reconstruction scores.

“Unknown” means absent from the retained basis, including training atoms removed
by the 4,096-feature budget; it does not necessarily mean novel held-out content.
Intent retains 4,096 of 13,100 distinct training atoms and UI/UX 4,096 of 5,494.
Security retains all 1,693 training atoms, but unseen composite names still make
its eight held-out sources collapse to two vectors. Held-out atom occurrences
excluded by the retained basis are Intent 64.40%, Security 3.24%, UI/UX 10.15%,
Legal 0%; Intent already excludes 64.28% of training atom occurrences.

For Intent, Security and UI/UX, calibration supplied the selected weights;
subsequent Adam updates did not beat the per-family tuning gate. Legal selected
epochs 19, 21 and 22. More executed updates are not automatically more useful
training. Normal runs retain the smaller default patience; this comparison used
equal complete budgets to isolate implementation throughput.

The held-outs are now exposed development data. Do not reuse them as a fresh
canary or select further candidates using these results. No model was promoted.

## Throughput and reproduction

The short comparison includes validation, feature preparation, optimization,
serialization and reload in each timed numerical call. Native target generation
runs once and is shared between arms. CPU runs are warm on a shared host, one
worker, float64 heads, OMP/MKL/OpenBLAS limits one, CUDA hidden. No embedding
weights were loaded.

| Domain | Reference row presentations/s | Prepared row presentations/s | Mean wall speed ratio |
|---|---:|---:|---:|
| Intent | 402 | 388 | 0.964 (slower) |
| Security | 1,307 | 1,376 | 1.047 |
| UI/UX | 686 | 774 | 1.126 |
| Legal | 3,255 | 3,357 | 1.031 |

Each arm presents 576 training rows. Fixed setup costs matter on short jobs:
backend selection remains explicit and the default stays v2. A separate longer
Intent diagnostic with six projections, 24 training/2 tuning rows and 1,024
updates measured 2,221 to 2,486 row presentations/s (1.120 mean wall ratio).
That is a different family/sample set, not a replacement for this full panel.

A subsequent **training-only** throughput run used the same four-domain
development specification and full family inventory, 256 epochs and 1,024
updates per arm. Three alternating pairs per domain produced:

| Domain | Reference row presentations/s | Prepared row presentations/s | Throughput gain |
|---|---:|---:|---:|
| Intent | 994 | 1,085 | 9.2% |
| Security | 2,419 | 2,547 | 5.3% |
| UI/UX | 1,557 | 1,727 | 10.9% |
| Legal | 5,723 | 6,216 | 8.6% |

All retained weights, loss/selection histories, saved inference and actual-update
continuations matched. Each domain requested 40 families; only its actual ready
projections received loss. No held-out target was prepared, read or scored in
this later run; it supplies no additional quality evidence. The short Intent
regression remains valid. Peak RSS was 914 MB for this sequential benchmark.

```bash
python3 scripts/ops/autoencoder/benchmark_domain_training_throughput.py \
  --output-directory /absolute/fresh/throughput \
  --epochs 256 --repetitions 3 --minibatch-size 6
```

Warm inference wall seconds/span (reference/prepared), including preparation
and reload: Intent 0.02970/0.03391; Security 0.00674/0.00569; UI/UX
0.01589/0.01306; Legal 0.00269/0.00256. Bridge names `[]`, legal-IR metric targets
`0`, prover evaluation false, metric disk cache false, sample memory unused,
workers one: **these are not bridge-on legal-IR evaluation timings**.

```bash
python3 scripts/ops/autoencoder/benchmark_domain_reconstruction.py \
  --phase prepare --output-directory /absolute/fresh/experiment
python3 scripts/ops/autoencoder/benchmark_domain_reconstruction.py \
  --phase fit --output-directory /absolute/fresh/experiment
# The fit prints the digest only after every candidate has completed.
python3 scripts/ops/autoencoder/benchmark_domain_reconstruction.py \
  --phase evaluate --output-directory /absolute/fresh/experiment \
  --freeze-sha256 <exact-printed-digest>
```

Source and input hashes, exact arm identities, completed update budgets and
one-shot markers guard the freeze. An interrupted benchmark needs a fresh output
directory. It is not the distributed resumable runner; existing fleet/Hub and
sparse-update services remain separate.

Development target preparation for 32 rows took Intent 1.426 s, Security
2.132 s, UI/UX 0.656 s, Legal 2.167 s. The separate canonical compiler gate took
0.05564 s/span for its three sentences. Different input paths must not be
combined into a corpus conversion rate.

## Lean and evidence limits

Separate authored native instances passed four actual `lake build DecoderSchema`
checks. The canonical minimum-duration path passed `lake build Legal`; deadline,
prohibition, minimum-duration and empty-vocabulary gates passed. No Mathlib or
downloads were used. Schema builds concern those authored instances, not learned
feature-head outputs, complete domain schemas, or source semantics. No
Constitution span is marked formalized or `roundtrip_ok`.

Future source-decoder work needs independent free-running formula/text holdouts.
The existing aligned Intent source continuation starts fresh Adam and checks its
deadline at epoch boundaries. Persisting moments, cursor and RNG state needs a
versioned continuation and an equal-budget fidelity comparison; this feature
benchmark does not supply that evidence.

The combined test run passed 246 tests. Four existing aligned-source tests were
skipped because their local legal-initialized development parent is absent from
the isolated export; those skipped tests do not establish source-decoder health.
All new preparation, training, continuation, coverage and benchmark tests passed.

Retained artifacts are under
`docs/implementation/reports/evidence/multidomain-training-20261001/`.
Measurements used a clean export of package commit `4425e503a` plus the additive
files in this change, with explicit `PYTHONPATH` and source hashes. Concurrent
uncommitted parser/compiler edits were not included or altered.
