# One interface, explicit model versions

`ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry`
provides local `list_runtimes`, `describe_runtime`, `prepare_targets`,
`open_runtime`, `open_formal_decoder`, `build_native_runtime`, and `load_version` entry points. A bound
runtime has `describe()`, `train()`, `infer()`, and `decode_formal_logic()` methods. Domain and runtime
version are always explicit; an embedding width or a dataset metadata field
never chooses executable code.

| Domain | Runtime version | Input and implementation | Interface support |
| --- | --- | --- | --- |
| `legal_ir` | `legacy_v1` | Frozen ddf6b794 numerical runtime; explicit 8D vectors | Train, evaluate, load local JSON checkpoint with expected SHA-256 |
| `legal_ir` | `legacy_v1_optimized` | Opt-in descendant of the same 8D lineage; streamed transaction norms | Same API and objective as legacy, separate runtime profile |
| `legal_ir` | `current_v2` | Current numerical runtime; explicit 384D vectors; raw-decoder default | Train, evaluate, load local JSON checkpoint with expected SHA-256 |
| `legal_ir` | `source_conditioned_formula_v1` | Fresh source-GRU/attention/formula-GRU model; source strings | Token-CE training, source-only inference, checkpoint and owner-registry exact Adam resume |
| `security_ir`, `intent_ir`, `ui_ux_ir` | `native_v1` | Native compiler projection features; full-batch Adam v1 | Prepare, train, infer, register candidate, reload and resume |
| `security_ir`, `intent_ir`, `ui_ux_ir` | `native_v2` | Existing streamed minibatch Adam v2 | Read-only inference/formal readout through `open_formal_decoder`; common training/registry opening still fails explicitly |

The legacy runtime/profile distinction preserves the teacher lineage while
allowing an optimization to be selected separately. The frozen runtime remains
available for comparison. Legacy vector provenance is still diagnostic unless
independently established. The current profile does not establish semantic
embedding provenance merely by requiring 384 dimensions.

Native v2 is listed because it already exists in the repository. Its different
state schema and minibatch step counters cannot be relabeled as v1. A contract
and registry resume adapter must be implemented before the common training
interface can use it. Direct native v2 callers retain their existing API.
The [formal-output API](formal_logic_decoders.md) supports a separate read-only
v2 session with an explicitly bound state, feature space and decoder head.

Every runtime descriptor now includes `qualification_requirements`. These are
[versioned requirements](logic_output_requirements.md), including the eight-family
floor, actual Lake schema checks and decoder-aware losses. They report outstanding
gaps and confer no validation or admission. Existing feature-state identities remain
unchanged; their structural training does not acquire missing validators.

## Inspect and select

Run from the canonical repository with `PYTHONPATH` set to that directory.
This is essential where a bare import would select the separate HACC install.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes

for entry in runtimes.list_runtimes():
    print(entry["runtime_id"], entry["state_schema"], entry["capabilities"])

legacy = runtimes.open_runtime(
    "legal_ir", "legacy_v1", checkpoint=existing_local_checkpoint,
    expected_sha256=expected_checkpoint_sha256, compute_device="cpu",
)
current = runtimes.open_runtime("legal_ir", "current_v2", compute_device="cpu")
```

For `legacy_v1`, `legacy_v1_optimized`, and `current_v2`, legal
`infer(samples, **options)` delegates to the selected facade's `evaluate`
and returns its existing metric object. `train(samples,
validation_samples=..., **options)` delegates to its projection trainer. All
existing bridge names, prover flags, sample-memory settings, deadlines, update
backends, and objective controls remain explicit options. Neither method adds
a learned formula decoder or changes the legal qualification policy. Loading
requires an existing local checkpoint and its exact hash; it downloads nothing.
`decode_formal_logic` is a separate explicit path: legal compiler-guided ASTs or
native expressions read from reconstructed feature scores. Neither path is an
independent learned text-to-formula model.

The separate `source_conditioned_formula_v1` has a different source-text input
and checkpoint schema. Its `infer()` calls source-only formula generation, and
its `train()` receives source/rule pairs. Read the
[learned formula guide](learned_legal_formula_training.md) for exact signatures,
limits, token loss, checkpoint and registry resume. It is not a legacy weight
migration or a new qualification route.

`describe()` reports a SHA-256 identity for the listed runtime source files.
This describes those files, not the entire dependency tree or a complete source
provenance attestation. Native candidate identity is the existing persisted
`ModalityContract`, including numerical implementation, target codec, adapter,
feature basis, objective, projections and validator requirements. The facade's
own source receipt is observational and does not replace that contract.

## Train, record a version, and resume native IR features

Create actual typed domain inputs before target preparation:

```python
intent_target = runtimes.prepare_targets(
    "intent_ir", "native_v1", document=intent_ir_document,
)
ui_target = runtimes.prepare_targets(
    "ui_ux_ir", "native_v1", document=ui_roundtrip_document,
    # Device/projection inputs may be supplied when available.
)
security_target = runtimes.prepare_targets(
    "security_ir", "native_v1", code_unit=code_unit,
    source_bytes=exact_source_bytes, typed_inputs=typed_code_logic_evidence,
    requested_kinds=("program",),
)
```

These functions retain each domain's own logic families, expressions, native
profiles, projection roles and qualification gaps. Security evidence still
requires exact source bytes and typed projections. Intent roles are not
collapsed into legal deontic families. UI structural/compiler observations do
not become device-validation evidence when device inputs are absent.

For a complete authored-input example, see the existing
[native feature quickstart](native_feature_quickstart.md). The shared lifecycle
below replaces its separate training and registry calls. `training_targets` and
`tuning_targets` must contain disjoint source identities. Choose actual
projection IDs from the prepared targets; do not invent generic replacements.

```python
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry

runtime = runtimes.build_native_runtime(
    "ui_ux_ir", "native_v1", training_targets,
    projection_ids=["ui_ux_ir:flogic"],
    ir_schema="ui_ux_ir/my-input-schema-v1", latent_width=4,
)
result = runtime.train(
    training_targets, validation_samples=tuning_targets,
    epochs=2, learning_rate=0.02, max_seconds=60,
)
inference = runtime.infer(tuning_targets)
assert inference["training_executed"] is False
formal_candidates = runtime.decode_formal_logic(tuning_targets)

root = Path("workspace/my-native-versions")
root.mkdir(parents=True, exist_ok=True)
with AutoencoderRegistry(root / "registry.duckdb", root / "artifacts") as registry:
    first = runtime.register_candidate(registry, root / "candidate-001")

with AutoencoderRegistry(root / "registry.duckdb", root / "artifacts") as registry:
    resumed = runtimes.load_version(
        registry, first["version_id"], domain="ui_ux_ir", version="native_v1",
    )
    resumed.train(training_targets, validation_samples=tuning_targets,
                  epochs=2, learning_rate=0.02, max_seconds=60)
    second = resumed.register_candidate(registry, root / "candidate-002")
    assert registry.get_version(second["version_id"])["parent_version_id"] == first["version_id"]
```

Register each candidate before starting another training call. The interface
rejects a second call while a candidate is pending, preserving its exact parent
and report. Candidate directories must be fresh. Inference may inspect a pending
candidate without training or promotion. `state` returns a copy, so callers
cannot change internal Adam moments through the returned object.

New native runtimes fit structural decoder metadata from the original training
targets and persist it alongside weights. The formal candidate has a distinct
variant binding both the numerical contract and decoder head. Original numeric
checkpoints remain loadable; their formal method reports `decoder_head_required`.
Use `with_formal_decoder=False` for an explicitly numeric-only new runtime.
See [formal decoder persistence](formal_logic_decoders.md#native-expression-reconstruction-and-persistence).

Reload verifies the content-derived registry version ID, artifact bytes/hash,
closed envelope, immutable variant manifest, modality contract, numerical state,
report identity, and immediate parent's state hash. Loading one domain's model
under another domain fails even if the vector shapes happen to match. The
installed adapter and numerical implementation must still match the contract;
source changes require an explicit new compatible runtime/contract or a separately
validated migration. The tuning identity and Adam settings remain governed by
the underlying native trainer. Native v1 epochs are additional epochs on resume;
do not substitute native v2's total-epoch/minibatch semantics.

## Boundaries

This interface uses the existing local, single-owner DuckDB registry. It does
not add a native-domain Quack transport, Arrow weight store, fleet worker, sparse
replay protocol, or Hugging Face upload/download path. Those capabilities are
absent from its descriptors. Existing legal fleet services are not redirected.
Use the established domain contracts as the boundary when adding these transports.
Runtime sessions are private to one worker; the common API does not make mutable
models or `NativeRuntime` thread-safe. The registry retains its single owner and
short transactions. Parallel workers must exchange artifacts with that owner,
not share a DuckDB connection or a mutable session.

Structural feature reconstruction and cosine losses remain numerical evidence.
All interface descriptors and native candidates retain `qualified=false`,
`admitted=false`, `formalized=false`, and `promotion_performed=false`. Only the
existing source-bound `lake build <Lib>` path can establish a Lean admit.

The accompanying tests exercise actual typed target preparation for Security,
Intent and UI/UX; train/infer; DuckDB close/reopen; parent-linked resume with Adam
state equal to uninterrupted training; cross-domain/version rejection; source
and metadata mismatches; and both legal facades with explicit local checkpoints.
They use small authored inputs and synthetic legal vectors, not a semantic
qualification dataset or an end-to-end legal-IR speed benchmark.
