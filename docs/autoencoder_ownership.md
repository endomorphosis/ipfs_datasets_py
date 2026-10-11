# Autoencoder ownership and security integration

`ipfs_datasets_py` owns reusable training, feature projection, corpus admission,
weight transfer, checkpoint formats, frozen inference, and Hub distribution.
The canonical security package is
[`logic/formalization/autoencoder/security`](../ipfs_datasets_py/logic/formalization/autoencoder/security).
It has no dependency on `ipfs_accelerate_py`.

`ipfs_accelerate_py` consumes those APIs. Its remaining adapters register
ModelManager capabilities, maintain supervisor/DuckLake observations, translate
training declarations into supervisor campaigns, and package benchmark runtimes.
Historical import paths are compatibility aliases, not duplicate trainers.

## Shared machinery and separate domains

Security training reuses the existing modal autoencoder numerical kernel,
gradient norm and batching code in `optimizers/logic_theorem_optimizer`.
Checkpoint manifests use the domain-neutral
[`CheckpointManifest`](../ipfs_datasets_py/logic/formalization/checkpoints.py).
Source screening is shared in
[`autoencoder/source_screening.py`](../ipfs_datasets_py/logic/formalization/autoencoder/source_screening.py).
The existing LegalIR, UI/UX IR and IntentIR implementations remain in datasets;
this move does not introduce a competing optimizer or rewrite their weights.

Compatible lexical rows can be copied from a pinned LegalIR checkpoint into an
isolated security initializer. Security input features, labels and formal views
retain separate identities. Sharing kernels or lexical weights does not make
legal and code logic heads interchangeable.

| Responsibility | Canonical security module |
| --- | --- |
| Reconstruction and candidate-head training | `codebase_autoencoder`, `codebase_autoencoder_security` |
| Immutable lexical weight transfer and published parent binding | `codebase_autoencoder_transfer`, `published_legal_initializer` |
| Source verification, canonical export and family splits | `security_cve_training_source`, `security_cve_canonical_export`, `security_cve_corpus` |
| Feature projection, portable export and frozen inference | `security_autoencoder_features`, `security_autoencoder_checkpoint` |
| Pinned download, cache and reviewed publication | `security_autoencoder_hub` |
| Source/model training declaration | `security_code_training_profile` |
| Explicit migration of qualified old packages | `checkpoint_migration` |

## Canonical imports

```python
from ipfs_datasets_py.logic.formalization.autoencoder.security.codebase_autoencoder import (
    train_codebase_autoencoder, validate_codebase_autoencoder,
)
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_autoencoder_checkpoint import (
    export_security_checkpoint, load_security_checkpoint, infer_security_checkpoint,
)
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_code_training_profile import (
    build_security_code_training_profile,
)
```

The pinned development training profile is in
[`configs/autoencoder/security_code_training_profile.json`](../configs/autoencoder/security_code_training_profile.json).
It selects the [Publicus CVE corpus](https://huggingface.co/datasets/Publicus/cvefixes-security-ir-graphrag)
and the [published LegalIR initializer](https://huggingface.co/datasets/justicedao/legal-ir-autoencoder-checkpoints)
by immutable revisions and hashes. It is a declaration, not a completed training
run or a promoted checkpoint.

## Existing checkpoints

Packages pin their implementation bytes. Moving an implementation changes those
pins even when numerical behavior stays the same. The loader still rejects an
old implementation binding. Use the explicit migration API for the reviewed
legacy pair:

```python
from pathlib import Path
from ipfs_datasets_py.logic.formalization.autoencoder.security.checkpoint_migration import (
    migrate_supervisor_security_checkpoint,
)

receipt = migrate_supervisor_security_checkpoint(
    package=Path("/absolute/old-package"),
    expected_manifest_sha256=admitted_old_manifest_sha256,
    output=Path("/absolute/new-package"),
)
checkpoint = receipt["destination"]
```

Migration checks the original manifest and exact reviewed producer pair, writes
a fresh package, and runs full schema, lineage, native-manifest and numerical
fixture validation. Only `config.json` and `release-manifest.json` change. The
seven tensors and all other payloads remain byte-identical. It does not retrain,
publish, alter LegalIR, or promote a supervisor pointer. Historical training
receipts still require their original qualified training implementation; their
source hashes are not silently rewritten.

## Code logic targets

The [code projection guide](security_code_logic_projection.md) documents program,
contract, transition, temporal, heap, separation and hyperproperty projections.
[`code_program_derivation.py`](../ipfs_datasets_py/logic/security_ir/code_program_derivation.py)
provides a guarded deterministic source-to-ProgramIR route for one simple Python
arithmetic function. It checks structure and exact source maps, states its input
assumptions, and emits candidate structural models without executing source or
claiming proved equivalence. Other syntax remains an explicit frontier.

The initial three-family CVE qualification has six before/after examples. All
six are fragments or combined changes unsupported by complete-module extraction.
They remain usable as separately labeled lexical observations; they do not
become verified formula targets. The supervisor's 15-task draft includes source
context recovery and model construction before projection, fitting, evaluation
and release. Stage execution and formula-head training remain unfinished.

The [end-to-end formalization checks](security_autoencoder_e2e.md) execute the
actual frozen model, preserve source coverage, compare model-off structural
outputs, and fail the learned-formula capability gate when no decoder exists.

## Experimental learned numerical CALL profile

[`numerical_selection_384.py`](../ipfs_datasets_py/logic/formalization/autoencoder/numerical_selection_384.py)
owns the separate, explicitly selected `numpy-unary-selection-384@1` profile.
It reuses `structured_source_384` to fit a new ridge classification head over
the exact frozen residual projection inherited from a trained LegalIR 384D
checkpoint. The Legal parent and the existing scalar SecurityIR checkpoint are
unchanged. This profile is not enabled by default in the supervisor.

Its source grammar permits module imports and one plain function with one to
four parameters, whose only statement returns imported `numpy.argmax` or
`numpy.argmin` applied to one positional parameter. Nested calls, assignments,
loops, keywords, rebinding and other function shapes are unsupported. In
particular, it does not decode the complete `largest-eigenval` functions.

Training targets are canonical `ProgramExpression` CALL fragments with callee
and parameter-position slots. Inference preserves the learned candidate, then
independently checks it against whole-file ProgramIR, import context and exact
function byte spans. A mismatch continues as an unqualified candidate; an
unsupported source raises `NumericalSelectionError`, which a broader supervisor
adapter must handle as a coverage frontier. Source-aligned fragments reference
the deterministic program, first-order and higher-order artifacts. Those
references are not learned whole-function reconstructions or numerical proofs.

Load this checkpoint through its explicit loader, supplying an independently
verified file digest and a vector from the pinned GTE-small embedding producer:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.numerical_selection_384 import (
    load_selection_checkpoint,
)

runtime = load_selection_checkpoint(checkpoint_path, expected_sha256=checkpoint_sha256)
result = runtime.infer([{
    "source_text": original_module_text,
    "path": "authored.py",
    "unit_id": None,  # Select the required singleton function; or supply its exact ID.
    "embedding": verified_gte_vector,  # 384 dimensions; original module text, without truncation.
}])
```

`prepare_selection_corpus` requires explicitly authored train/validation/holdout
rows and rejects source, normalized clone and group overlap between splits.
`train_selection_384` accepts only train/validation embedding IDs and an exact
Legal parent path/hash. `evaluate_selection_384` checks the full corpus manifest
and accepts only held-out embedding IDs after checkpoint selection. The
authorship field is a caller declaration requiring provenance review, not
independent evidence of corpus origin.

The 2026-10-11 development run used CUDA GTE-small embeddings and 24 rows in each
split: two-parameter training, three-parameter validation and four-parameter
holdout. Each split contains four operator/operand groups with six alias/name
variants per group. This measures a small signature holdout with known output
classes, not broad lexical or code generalization. No benchmark source was used
for this training run.

| Held-out condition | Exact, source-aligned CALL fragments |
| --- | ---: |
| Normal weights | 17/24 |
| Zero head | 6/24 |
| Zero inherited residual projection | 8/24 |
| Cyclic embedding shuffle, declared before fitting | 17/24 |
| Opposite-callee embedding swap, post hoc diagnostic | 1/24 |

The unchanged cyclic-shuffle score limits what that control establishes about
source dependence. The opposite-callee swap was a later diagnostic and was not
used for checkpoint selection. Four source-bound Lean definition modules passed
`lake build`; **zero source obligations were discharged**. Whole-function
reconstruction and benchmark performance were not measured by this experiment.

The resulting checkpoint SHA-256 is
`26ccc7cf8420e0ed6cbbe22603e09be0e3572fb32a1e489e877fc5081f506e03`.
It is published in the separate [development release](https://huggingface.co/Publicus/security-ir-autoencoder/tree/38666f43e998d55b5f4259e354286f5929027ba1/releases/20261011-numpy-unary-selection-384-development-v1)
at Hub revision `38666f43e998d55b5f4259e354286f5929027ba1`.
The release manifest SHA-256 is
`65980daba116f496019a8004a5980cf365761510dd143879106bd66775be6574`.
The prefix contains the authored corpus, saved embeddings, evaluations and an
offline `replay.py` that verifies file hashes and reproduces the four predeclared
holdout scores. This publication does not select or promote a default supervisor
checkpoint. Use the exact Hub revision, explicit loader and checkpoint digest.
