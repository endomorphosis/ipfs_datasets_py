# Formula checkpoint exchange

`autoencoder_formula_exchange.py` exchanges the complete trained results for
`native_formula_v1` (Intent, Security, UI/UX) and
`source_conditioned_formula_v1` (Legal). It uses a separate codec from the
legacy 8-dimensional and current 384-dimensional modal autoencoders. Their
checkpoint formats and transport paths remain unchanged.

The result is an **unqualified, independent candidate branch**. Transfer does
not grant semantic correctness, execute Lake, promote a head, average weights,
or establish that remote training ran as reported. Content hashes establish
byte identity, not producer authentication. Use the existing local qualification
gates for any later admission. The Constitution remains unformalized.

## Local API

Run from the canonical workspace package with `PYTHONPATH` pointing there.
Native formula callers must set `torch.set_num_threads(1)` as required by their
existing training API. There is no hidden device selection, download, thread
pool, or global thread-setting side effect in this module.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    autoencoder_formula_exchange as exchange,
)

# parent_result and child_result are exact existing training/registration
# mappings: {"checkpoint": ..., "report": ...}.
anchor = exchange.stage_formula_anchor(parent_result, "out/formula-anchor")
update = exchange.stage_formula_update(
    parent_result, child_result, "out/formula-update",
)
loaded = exchange.load_formula_bundle(
    update["manifest_path"],
    parent_result=parent_result,
    expected_binding=exchange.formula_binding(parent_result),
)
assert loaded["result"] == child_result
assert loaded["replay_verified"]
assert not loaded["qualified"]
```

`stage_formula_anchor` stages a complete trained result, including its report.
`stage_formula_update` requires additional completed optimizer steps and the
checkpoint's exact numerical parent. Its immutable binding includes domain,
runtime, producer-source hashes, vocabulary, decoder structure, configuration,
and training/tuning manifests. These cannot change across an update.

Native checkpoints retain **latest weights, all Adam state, partial-epoch
cursor, pending evaluation, selected weights, and selected tuning metrics**.
Legal source-conditioned checkpoints retain the entire model, Adam state,
progress, and report; that lineage does not have a separate selected snapshot.
The parent's entire result, including report bytes, is bound. A different
report with identical weights is not the same transport parent.

Postimages replace changed JSON subtrees exactly, with preimage hashes. Small
sparse changes can remain individual cells; dense arrays use whole-subtree
postimages. Unchanged vocabulary and configuration are omitted from updates.
There is no floating-point delta subtraction/addition, lossy compression,
arithmetic averaging, or optimizer-state reset. Dense training can change nearly
every weight and moment: **a sparse update is not a promise of small bandwidth**.
Use `payload_bytes` and `full_result_bytes` in the staged receipt to measure it.

The load result exposes `result`, `binding`, `checkpoint_sha256`, `manifest`,
`manifest_artifact`, `snapshots`, and `replay_verified`. Loading and staging do
not change a registry. A worker can hand `result` to the corresponding existing
`native_formula_checkpoint.register_candidate` or
`legal_formula_checkpoint.register_candidate` through its single registry
owner, supplying the verified local parent version. A standalone transport
anchor may itself name a historical numerical parent; it does not erase that
parent or bypass registration's parent requirements.

## Explicit publication and receiving

```python
# Default dry run: performs local validation, makes no network call.
dry_run = exchange.publish_formula_bundle(
    update["manifest_path"], parent_result=parent_result,
)

# Only an authorized caller enables upload. No upload runs automatically.
published = exchange.publish_formula_bundle(
    update["manifest_path"], parent_result=parent_result, upload=True,
)
reference = published["formula_reference"]

# A receiving machine must explicitly opt into downloading and supply its
# trusted profile binding and exact local parent. The receiver never searches
# for or automatically downloads missing ancestors.
received = exchange.receive_formula_bundle(
    reference, "out/received-formula-update",
    parent_result=parent_result,
    expected_binding=exchange.formula_binding(parent_result),
    allow_weight_download=True,
)
assert received["result"] == child_result
```

Repository: `justicedao/uscode-autoformal-span-cache`; namespace:
`autoformal/uscode/formula-training`. Artifacts and manifests are content
addressed. References pin an immutable Hub commit. Publication reuses the
existing bounded Hub parent-commit CAS and remote hash/size verification.
It creates no branch head or best-model pointer. Concurrent publication can
require retry after a Hub parent-commit conflict; identical retries are
idempotent. Each worker stages into its own local directory.

Downloads use the existing bounded disk-streaming transport, then validate
canonical bytes, parent identity, postimage replay, and local producer sources.
Repeated receives verify and reuse retained files. Missing update parents fail
before fetching the weight payload. No legacy checkpoint resolver or patch
codec interprets these formula weights.

Caps are 72 MiB per complete result, 80 MiB per payload, 1 MiB per manifest,
65,536 postimages and 32 JSON nesting levels. Checkpoint-native limits also
apply. Memory is bounded but **not zero copy**: exact validation and replay
materialize JSON snapshots and the corresponding Torch checkpoint. Scheduling
must include that overhead; Arrow tensors are a separate future optimization.

## Validation and remaining fleet work

`tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_formula_exchange.py`
trains all four domains locally and verifies exact optimizer resume after
anchor/update reconstruction. It covers parent/config mismatch, authority
claims, corruption, bounds, overlapping postimages, repeated staging and
receiving, and explicit network opt-in. Hub publication and receiving tests
use injected in-memory fixtures; they neither upload nor download real weights.

This is the transport component, not a fleet scheduler. Assignment, owner
leases, CPU/memory admission, branch selection, and owner-controlled registry
registration remain responsibilities of the caller. An explicit anchor plus
the same sequence of exact updates gives machines identical selected branch
weights; independent concurrent branches do not automatically converge into
one global model. A numerical merge requires a separately tested optimizer
policy and fresh qualification evidence.
