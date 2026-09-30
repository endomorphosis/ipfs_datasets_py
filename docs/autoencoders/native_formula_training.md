# Decoder-aware native training and actual Lake checks

`native_formula_v1` is an explicit additional version for Intent, Security and
UI/UX. It learns a categorical decoder over compiler-prepared native structures.
The existing `native_v1`, `native_v2`, legacy 8D legal and current 384D legal
weights retain their original architectures and objectives. Legal source-only
formula generation remains `source_conditioned_formula_v1`.

This version addresses a specific training gap: numeric reconstruction can hide
an incorrect polarity or argument among many constant fields. Every variable
leaf path now has a categorical cross-entropy term. The objective averages those
terms, excluding constant fields, and backpropagates through the encoder and
output decoder. It is structural autoencoding, not independent raw-text
translation. There is no guarantee of a global minimum.

## Inputs and supported scope

Use the existing typed target producers through
`autoencoder_runtime_registry.prepare_targets(domain, "native_formula_v1", ...)`.
Choose projection IDs from their returned envelopes. The training corpus fixes
all of the following:

- Domain, projection descriptors, exact field paths, shapes and value vocabulary.
- Training and tuning manifests with disjoint source identities.
- Numerical implementation and native validator source hashes.
- Latent width, learning rate, batch size, seed, CPU float64 and Adam settings.

Every selected projection must have one fixed shape. Unknown path/value atoms,
changed list lengths, missing projections, mixed modalities, invalid native
records, or a corpus containing no variable categorical fields are rejected.
These cases need a different vocabulary or future presence/length decoder;
they are not silently truncated or replaced with compiler outputs. Nonselected
projections remain explicit in the checkpoint and report.

The current implementation is bounded to 256 rows per corpus, 2,048 features,
64 latent units, 32 samples per batch, and a 64 MiB checkpoint. Set
`torch.set_num_threads(1)` explicitly. Use separate processes for independent
candidates; this local diagnostic lineage has no distributed gradient merge,
Arrow codec, Quack worker adapter or Hugging Face exchange adapter yet. Do not
feed its checkpoint into the legal JSON/Arrow sparse-update codec.

## Train, infer and resume with the public interface

Run from the pinned dataset checkout with `PYTHONPATH="$PWD"` in a fresh process.
No model download is needed.

```python
import torch
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_decoded_schema import validate_decoded_outputs

torch.set_num_threads(1)
runtime = runtimes.build_native_formula_runtime(
    "ui_ux_ir", training_targets,
    validation_samples=tuning_targets,
    projection_ids=["ui_ux_ir:event_calculus"],
    latent_width=16, learning_rate=.01, batch_size=8,
)
trained = runtime.train(training_targets, validation_samples=tuning_targets,
                        epochs=20, max_seconds=60)
formulas = runtime.decode_formal_logic(tuning_targets)

with AutoencoderRegistry("control.duckdb", "artifacts") as owner:
    version = runtime.register_candidate(owner, "fresh-candidate-directory")
    restored = runtimes.load_version(owner, version["version_id"],
        domain="ui_ux_ir", version="native_formula_v1")
    assert restored.infer(tuning_targets) == formulas

checks = validate_decoded_outputs(
    restored, tuning_targets, output_directory="fresh-lake-directory",
    timeout_seconds=60,
)
```

The registry stores immutable candidates with exact numerical parents and compact
hash-bound variant manifests. Only one owner opens a DuckDB file. Registered
rows do not qualify or promote the candidate. Inference cannot run the optimizer.
A trained runtime requires registering its pending candidate before another
training call, so ancestry is explicit. A call stopped before any optimizer
update leaves the runtime unchanged and does not create an unregistrable pending
candidate.

Resume restores the latest weights, all Adam moments and steps, the deterministic
partial-epoch cursor and any pending tuning evaluation. The selected inference
weights are stored separately. Tuning selection ranks native-valid outputs,
exact projection matches, exact leaves, then cross-entropy. These discrete
observations select candidates; they are not advertised as differentiable syntax
or proof losses. A monotonic deadline is checked before batches and evaluations;
an in-flight operation and final serialization may finish after it.

The learning rate and Adam hyperparameters are fixed within this version. The
adaptive legal optimizer does not implicitly apply to this new objective.
Changing that policy requires a new version and comparative quality evidence.

## Runnable training and schema-check command

Write a corpus JSON with exactly `training_targets`, `tuning_targets`, and
`projection_ids`. Each target is the full existing native envelope, including
its actual provenance. This CLI additionally limits tuning to 32 rows and
128 row/projection checks so the complete Lake report fits the bounded evaluator.
Larger native numerical batches require explicit evaluation partitioning. Then run:

```bash
PYTHONPATH="$PWD" python3 scripts/ops/autoencoder/train_native_formula.py \
  --domain ui_ux_ir --corpus /absolute/path/corpus.json \
  --output /absolute/path/fresh-run \
  --registry /absolute/path/control.duckdb \
  --artifact-root /absolute/path/artifacts \
  --epochs 20 --max-seconds 60
```

For resume, add `--parent-version <registered-version-id>` and use a fresh output
directory with the identical corpus. Architecture and optimizer settings come
from the verified parent. The command retains training metrics, the checkpoint,
registry receipt, actual decoded records and individual Lake projects/logs. Exit
status 2 means no optimizer update or incomplete schema checks; inspect the
retained report. It does not automatically publish to the Hub.

## What Lake establishes

`autoencoder_schema_lake` first replays the exact native owner validator, or the
canonical legal rule codec. It generates Lean structures and typed instances,
preserving scalar types, nulls, field presence, list order and multiplicity,
heterogeneous lists and exact floating-point bits. It executes the installed
Lean4.26.0 `lake build DecoderSchema` in a fresh bounded project. No Mathlib,
weights, toolchain download, arbitrary supplied Lean source or caller `passed`
flag is accepted.

`autoencoder_decoded_schema.validate_decoded_outputs` binds this check to actual
outputs of the new learned legal/native runtime and its loaded checkpoint.
Native source bindings refer to the exact provided model-input envelope; its
`source_digest` is not assumed to hash raw text. The stand-alone emitter accepts
only a caller-supplied checkpoint digest and labels that weaker binding.

A successful build establishes the emitted structural schema/instance typecheck.
It does **not** prove source meaning, all operators in a logic family, semantic
equivalence, or a theorem about legal duties or program behavior. Every semantic,
qualification, formalization and admission flag remains false. Serialized
receipts are retained audit evidence; only the in-process execution object can
be reverified as a fresh execution, and its files and producer/toolchain hashes
must still match.

## Evidence to inspect

Read `training_before` / `training_after` categorical loss, nonzero encoder/head
gradients, per-leaf and per-projection accuracy, invalid readout reasons,
selected versus latest optimizer steps, and omitted projection IDs. Tuning
structure overlap is reported even when source identities are disjoint.
Repeated authored structures test reconstruction and storage, not generalization.
A held-out panel must remain separate from fitting and selection.

The legal eight-family syntax gate now has separate CEC and propositional
validators. Their restricted projections retain explicit omitted semantics.
`family_coverage_gate` prevents all eight syntax passes, or a numeric-pattern
Lake proof, from being mistaken for complete semantic/schema coverage. It is
required by qualification, training disposition, distributed receipts and Hub
publication checks. Legacy receipts missing the coverage gate fail closed.

The full capability floor remains tracked in
[logic output requirements](logic_output_requirements.md). Remaining work includes
variable-shape and open-vocabulary decoders, independent native source encoders,
full mixed cognitive/event semantics, native validators for every applicable
code route, and held-out semantic qualification. No Constitution span is marked
formalized by this work.

The [installed end-to-end smoke](decoder_completion_smoke_20260930.md) records
actual outputs, losses, DuckDB resume, Lake receipts and the retained legal
exception failure.
