# Preserved 8D teacher to current 384D formula training

[`legacy_teacher_distillation.py`](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_teacher_distillation.py)
prepares screened compiler weak labels produced alongside the preserved 8D
teacher for the current 384D model's existing formula objective. It does not
transfer numerical weights, pad teacher vectors, or attach the teacher's
decoder to the student. The legacy linguistic model remains independently
trainable; the current model trains its own residual projection and latent
formula decoder. See [joint formula training](modal_joint_formula_training.md)
for the objective and checkpoint layout.

The formula target is attributed to the canonical compiler. Agreement with
that target is a diagnostic, not independent semantic fidelity or legal gold.
The student core still consumes parser-derived features. Its learned formula
generation therefore does not establish source-text-only formalization.

## Inputs and pins

Prepare these artifacts before calling the adapter:

1. Teacher rows from `LegacyLinguisticTeacher.distillation_row`, retained in a
   complete local artifact with its file SHA-256. Keep rejected observations
   too: they contain historical IR, numerical output and screening reasons.
2. Separate `current_v2.LegalSample` inputs with 384 finite embedding values,
   their encoder identity and source-bound parser IR. IDs, exact source text,
   citation and source SHA-256 must match the corresponding teacher rows.
3. The expected teacher `linguistic_identity_sha256` and canonical compiler
   producer `producer_sha256`, selected explicitly for the campaign. A digest
   copied from an untrusted row is not an independently established pin.
4. An explicit train/tuning/holdout assignment. Tuning and holdout calls require
   `excluded_source_texts` from earlier splits; also pass their sample IDs.

For semantic embedding runs, use
`autoencoder_embedding_runtime.produce_native_embedding_receipt` and verify the
result through `load_embedding_production_receipt`. The existing offline
provider uses the locally pinned GTE-small revision
`17e1f347d17fe144873b1201da91788898c639cd`; missing assets or oversized token
inputs fail without downloads or truncation. The preparation adapter checks
embedding shape and sample consistency, **not** native embedding production.
Synthetic embeddings can test the adapter but do not become verified semantic
inputs merely by passing it.

## Preparation and training

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_teacher_distillation import prepare_teacher_distillation

common = dict(
    expected_teacher_identity_sha256=teacher_identity_sha256,
    expected_producer_sha256=producer_sha256,
    teacher_artifact_sha256=full_teacher_artifact_sha256,
)
train = prepare_teacher_distillation(
    train_samples, train_teacher_rows, split="train", **common,
)
tuning = prepare_teacher_distillation(
    tuning_samples, tuning_teacher_rows, split="tuning",
    excluded_source_texts=[sample.text for sample in train_samples],
    excluded_sample_ids=[sample.sample_id for sample in train_samples],
    **common,
)

# Persist both receipts and inspect every rejected disposition before training.
train_receipt, tuning_receipt = train.receipt, tuning.receipt
training_inputs, training_targets = train.training_inputs()
tuning_inputs, tuning_targets = tuning.training_inputs()
result = student.train_generalizable_projection(
    training_inputs,
    validation_samples=tuning_inputs,
    formula_targets=training_targets,
    validation_formula_targets=tuning_targets,
    epochs=20, max_seconds=60,
)
```

Here `student` is an explicit `current_v2.Autoencoder`; reserve resources and
set `torch.set_num_threads(1)` in the calling process as required by the joint
trainer. The registry alternative is `open_runtime("legal_ir", "current_v2")`
followed by `runtime.train(...)` with the same samples and targets. Preparation
performs no training, checkpoint load, upload or publication.

Each preparation call accepts at most 256 samples and 256 teacher rows,
bounded to 4 MiB per row and 32 MiB total serialized input. Teacher rows may be
reordered, but joins must be unambiguous. Duplicate IDs, duplicate normalized
source text and overlap with excluded splits abort the batch. Missing, extra,
malformed or screened-out teacher rows produce explicit rejection receipts.
Constitution and unknown-corpus rows cannot supply formula targets.

An accepted row requires the teacher's `compiler_supervised_formula=True`,
`historical_formula=False`, a matching candidate disposition with no screening
reasons, and consistent compiler/cycle evidence. The legacy `feature_target`
remains unused. Changing a mask alone cannot promote a rejected observation.
The returned target contains only the existing closed fields
`id`, `source_text`, and `canonical_ir`.

The receipt preserves the original row's canonical JSON digest, caller-supplied
artifact digest, source/producer/model bindings, masks, student sample digest
and temporal sidecars. This is internal consistency evidence; artifact
membership, producer authenticity and current teacher weights are not newly
attested. Keep the complete teacher artifact alongside it. Receipt and target
accessors return fresh copies. `training_inputs()` checks that the original
student samples have not changed after preparation, then returns copies.

The formula head supports one `typed_deontic_rule_v1` rule. Its temporal atoms
are trained, but sidecar fields such as `temporal_kind` and `quantity` remain
in the receipt and are **not encoded by this head**. This does not cover every
required legal logic family. All admission, formalization and semantic
qualification flags remain false; only an actual Lake build supplies Lean
build evidence, and a schema build does not prove source-law equivalence.

Temporal consistency accepts the exact sidecar value and, specifically for
`within_duration`, the canonical `within <value>` atom. It preserves both
inputs unchanged. A matching source phrase must retain the declared kind;
minimum duration recognizes the parser's `at least` and `minimum of` forms.
Other temporal prefixes are not stripped or treated as interchangeable, and
quantity mismatches reject the row. This is a consistency check, not a proof
of semantic equivalence.

## Checkpoint compatibility

The student formula checkpoint retains its own vocabulary, residual projection,
GRU parameters, optimizer moments and cursor. It binds the current lineage,
384D dimension, exact core state, configuration and listed implementation
sources. Load it with its exact SHA-256 and the same core/profile. Resume uses
the original training/tuning manifests and optimizer configuration; omit new
`formula_options` on resume. Training-target vocabulary is fitted only on the
training split, so unknown tuning atoms fail rather than silently expanding it.

Source or checkpoint guards may reject older artifacts after implementation
changes. Do not bypass those guards, rewrite stored hashes or overwrite the
archived teacher. Create a separately identified compatible branch and retain
the old source/checkpoint artifacts for replay. The preparation receipt is a
sidecar and does not introduce a new checkpoint format.

## Bounded end-to-end diagnostic

From the canonical `external/ipfs_datasets` checkout, use a fresh output
directory and a fresh process:

```bash
PYTHONPATH="$PWD" IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0 \
  python3 scripts/ops/legal_ir/validate_teacher_student_transfer.py \
  --output-directory workspace/test-logs/teacher-student-transfer-new-run \
  --epochs 250
```

[`validate_teacher_student_transfer.py`](../../scripts/ops/legal_ir/validate_teacher_student_transfer.py)
uses a small authored panel with separate training, tuning, holdout and negative
controls. It produces native local 384D embeddings in a separate process,
reads the retained 8D teacher with its expected SHA-256, stores full teacher
rows and transfer receipts, then exercises student training, generated outputs,
save/reload, resume and generated-schema checks. `--phase embeddings` and
`--phase validate` allow the two phases to run separately. `--retained-teacher`
can change the local path, not the expected archived teacher identity.

Inspect `report.json`, `teacher-rows.json`, `*-transfer.json`, embedding
production evidence and the saved student formula files. Report generated
facet mismatches and abstentions even when schema checks pass. The authored
holdout is a wiring diagnostic, not independently reviewed legal gold. This
script runs with bridges off and reports `legal_ir_target_count=0`; its timings
must not be reported as bridge-on legal-IR evaluation speed. Use the receipt
from each executed run; the results below describe one fixed diagnostic only.

The checked-in [artifact manifest](../implementation/reports/evidence/teacher-student-improvements-20261001/artifact-manifest.json)
maps the original local paths to relative archive members and exact file hashes.
The accompanying [diagnostic bundle](../implementation/reports/evidence/teacher-student-improvements-20261001/teacher-student-artifacts.tar.gz)
retains full teacher observations, native embedding receipts and source texts,
student inputs, transfer receipts, both newly trained student heads, and generated
Lean sources/build logs. It excludes the archived teacher weights and the local
embedding model assets. These diagnostic heads remain unqualified.

## October 1, 2026 diagnostic results

The final [transfer receipt](../implementation/reports/evidence/teacher-student-improvements-20261001/teacher-student-transfer.json)
records a completed run with four training rows, four tuning paraphrases, four
compositional holdout rows and three excluded controls. The student used
separately produced native local 384D embeddings and a fresh, frozen sparse
core. Only the screened compiler weak labels supplied its formula targets;
the teacher's 8D vectors were not consumed as student inputs or objectives.

| Observation | Result |
| --- | --- |
| Adam optimizer steps | 250 in 3.903 seconds |
| Training formula token cross-entropy | 3.333612 → 0.00091494 |
| Training projected-embedding MSE | 0.04189765 → 0.00063105 |
| Exact generated rules versus weak labels | Training 4/4; tuning 4/4; holdout 0/4 |
| Full validation phase | 65.045 seconds |
| Separate native embedding production | 2.921 seconds |
| Peak validation-process RSS | 2.503 GiB |

Every holdout output selected the wrong actor. The other six canonical facets
matched their weak labels: modality, action, object, conditions, exceptions and
temporal atoms. Low training loss therefore did not establish compositional
generalization. These four exposed holdout examples are now diagnostic cases,
not a sealed evaluation set.

All 15 retained-teacher predictions matched between the preserved baseline and
the optimized view-reuse profile. The archived teacher checkpoint remained
unchanged; it was not trained by this run. The student's sparse core also
remained unchanged. Formula save/reload preserved predictions, and one resumed
optimizer step matched an uninterrupted step exactly. The checked formula head
had SHA-256
`910ce3da7d3db011e286f0762503e9a2c1a8d80996a292d2a39f3e255992eba7`.

Two actual `lake build DecoderSchema` executions passed for generated rule
instances, including one incorrect holdout output. Those checks establish the
structural schema and instance scope recorded in their receipts; they did not
detect the actor error or establish source-law equivalence. The separate
canonical `lake build Legal` gate is a different check. No row was semantically
qualified or admitted by this transfer run, and Constitution qualification
remains false. The supporting [test receipt](../implementation/reports/evidence/teacher-student-improvements-20261001/tests.json)
records 388 unique passing tests.

The run used no bridge names, no external provers, one legal-IR worker, disabled
metric disk caching and sample memory, and temperature zero. Its
`legal_ir_target_count` was zero, so these numbers are not bridge-on IR speed
measurements or evidence of global-minimum convergence.

The follow-up [actor composition experiment](actor_composition_evaluation.md)
compares a balanced actor/template curriculum with a confounded control, using
the same initialization, formula vocabulary and update budget. It reserves a
new evaluation partition before training and records full-rule and facet
scores. Both arms still scored 0/6 exact on that panel; balancing the data alone
did not solve the failure. Repeated hyperparameter tuning against either
exposed evaluation panel would not establish generalization.
