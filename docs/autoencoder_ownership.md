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
