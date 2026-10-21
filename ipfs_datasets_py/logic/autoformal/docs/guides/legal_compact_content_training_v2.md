# Compact-content engineering training and exact resume, v2

Intended module:
`ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_training_v2`.
This is an additive successor to the weights-only v1 head. Staging this file is
not a training result, checkpoint qualification, or authorization to fit laws.

The owner reuses the existing residual projection, conditional GRU, Adam,
named-state export and finite tensor restoration in `modal_latent_formula`.
Only the compact target preparation and versioned lifecycle are new. The
existing compact token owner validates complete targets against supplied
contexts and retains its fixed **384 input coordinates, 537 tokens and 512
total target IDs**. Hidden width, projection width and token embedding width
remain the validated initial head's separate configuration values. This is
neither a 768D nor a native4096 adapter.

## Public API

```python
build_compact_content_training_v2(
    initial_checkpoint, population_raw, rows, *,
    expected_initial_checkpoint_sha256, expected_population_sha256,
    learning_rate=0.001,
)  # -> new zero-update v2 checkpoint

train_compact_content_v2(
    checkpoint, population_raw, rows, *,
    expected_checkpoint_sha256, expected_population_sha256,
    max_optimizer_steps, max_seconds=60,
)  # -> {"checkpoint": ..., "report": ...}

validate_compact_content_training_v2(
    checkpoint, *, expected_checkpoint_sha256,
)  # -> detached validated/restored checkpoint

compact_content_training_sha256(checkpoint)  # canonical JSON identity only
compact_content_training_bytes_v2(
    checkpoint, *, expected_checkpoint_sha256,
)  # -> validated canonical UTF8 JSON bytes, no newline
load_compact_content_training_v2(
    checkpoint_raw, *, expected_raw_sha256,
)  # -> validated/restored checkpoint
```

The module writes no files. The caller writes returned bytes to a fresh exclusive
path, fsyncs them under its existing storage owner, and supplies an independently
retained byte hash to load. Duplicate JSON keys, nonfinite values, cycles,
unknown fields, malformed tensors and mismatched pins are refused. Hashing is
not schema validation, execution attestation or permission. Validation restores
the initial v1 head and current model/Adam state but runs no forward pass or
optimizer update.

## Whole-population contract

`population_raw` is exact immutable UTF8 JSON, at most 128 KiB:

```json
{
  "schema": "legal-compact-content-training-population/v2",
  "origin": "authored_engineering_fixture",
  "partition": "engineering_training",
  "rows": [
    {
      "id": "fictional-occurrence-1",
      "source_group": "fictional-group-a",
      "source_sha256": "<exact source bytes hash>",
      "context_sha256": "<exact independently supplied context bytes hash>",
      "target_sha256": "<exact authored target bytes hash>",
      "conditioning_sha256": "<canonical JSON vector hash>"
    }
  ]
}
```

All fields are required and the objects are closed. There must be 1–16 rows,
unique nonempty occurrence IDs, and bounded nonempty source-group IDs. Shared
groups are retained; this API has no split or holdout and does not claim clone
independence. The exact original manifest bytes, including whitespace, are
committed and retained in the checkpoint. No favorable subset or changed order
is accepted on resume.

Each corresponding Python row has exactly these fields, in the same complete
population order:

```python
{
    "id": "fictional-occurrence-1",
    "source_group": "fictional-group-a",
    "source_raw": b"Authored fictional source text.",
    "context_raw": b"<existing compact context JSON>",
    "target_raw": b"<existing complete compact content JSON>",
    "conditioning": [0.0] * 384,
}
```

Source, context and target caps are respectively 64 KiB, 512 KiB and 16 KiB.
Every vector must contain 384 finite ordinary numbers of magnitude at most
`1e8`; booleans are rejected. Its original canonical JSON hash is checked before
conversion to the model's float32 representation. The exact inputs remain
available to the caller for independent readback. The checkpoint stores their
complete hash manifest, not their source/target bodies.

Every row and complete target is validated **before any optimizer step**. The
public token owner enforces exact content grammar, context references, all
declared predicates, and BOS/EOS framing. The caller must supply context
independently; the trainer never constructs or shrinks a context from a target.
Structural validation does not establish that this supplied context actually
predated a label. The fixture origin is a caller declaration, not authenticated
rights, semantics or authorization. A real statutory population is outside this
engineering contract and requires a separate eligibility/reviewed-target path.

## Training and resume semantics

Initialization first invokes the unchanged public v1 head validator. The whole
initial v1 checkpoint, its complete hash, permanent initial weights hash, and
original donor/transfer ledger remain in every descendant. Current weights and
named Adam moments are separate. No donor optimizer is inherited. A v2 checkpoint
has a new schema, actual `progress.optimizer_steps`, and no misleading v1
`compact_training_steps=0` field. The v1 scorer/generator deliberately rejects it.

Training uses batch size one and the fixed population order, repeating at epoch
boundaries. Each complete target provides teacher-forced input `ids[:-1]` and
labels `ids[1:]`. The objective is compact-token cross-entropy, ignoring PAD;
this increment has no auxiliary reconstruction loss, label smoothing, target
sampling or tuning/selection. The formula gradient reaches the residual
projection through the existing model. Finite gradients are checked before
the existing Adam update, with global L2 clipping at 5. Adam uses its checked
default betas/epsilon and `foreach=False`; all named parameters retain exact
steps, first moments and nonnegative second moments.

At most 16 updates are requested per call and at most 100,000 cumulatively.
`max_seconds` is 0–300 and checked before each batch. It is a soft deadline:
preparation, restoration, in-flight work and closing checks are not interrupted.
The existing external resource owner still supplies admission, memory limits,
process bounds and cancellation. This module adds no scheduler or resource
authority. A zero-step or pre-batch-deadline result retains the entire original
checkpoint identity; it does not manufacture a new lineage edge.

For a real update, the immediate parent is the supplied v2 checkpoint hash.
The original v1 identity remains permanent. Progress is checked against the
population count: `epochs_completed = steps // count`, `row_cursor = steps %
count`. The complete parameter inventory/order, float32 values, Adam steps,
moments, optimizer configuration/policy and source pins are validated on load.
CPU float32, one Torch CPU thread, Python/runtime versions, Torch build metadata,
interop thread count, MKLDNN flag and deterministic-algorithm mode are bound.
The module never changes global thread, device, dtype or RNG policy.

Exact resume is a same-runtime engineering promise. A caller-supplied hash and
self-consistent checkpoint record are commitments, not independent evidence
that every claimed historical update was executed. Retain actual operation
reports and original artifacts. A deliberately rebuilt, fully rehashed lineage
requires external provenance review; this owner is not a signing authority.
An exception after an update does not return a successful partial result.
The outer owner must retain that failed attempt and any available diagnostics.

## Measurements and limits

Each report records actual updates, row IDs, pre-update teacher-forced losses,
label-token counts including EOS, per-batch clocks, finite gradient maxima and
parameter-change L2 norms/hashes for projection and decoder groups. The formula
gradient into the projection is measured separately. Reports do not compute a
holdout score or free-running generation quality.

`optimizer_seconds` sums complete batch preparation/forward/backward/update and
finite-check scopes. `optimizer_tokens_per_second` uses only those tokens and
that clock. `elapsed_seconds` starts at public training entry and ends before
final output serialization/custody checks; its exact scope is recorded. These
clocks overlap and must not be added. Initialization/other API calls are separate
work. Caller-level wall time is required for full-pipeline throughput.

Conditioning remains unverified caller-supplied data. Source text is bound by
hash but never enters a source encoder or this neural model. `encoder_sha256`
stays null. Every semantic/permission authority flag stays false, and both
`training_mask` and `evaluation_gold_mask` stay integer zero, even after real
updates. An actual update is not legal-gold qualification, source fidelity,
holdout improvement, graph admission or Lean acceptance.

## First qualification and subsequent gates

The proposed owned CPU fixture uses two independently authored fictional
source/catalog contexts and explicit labels, plus arbitrary 384D vectors. Run
two updates uninterrupted and compare them with one update → exclusive byte
save → hash-checked load → one update. This is **four actual updates across two
trajectories**, not two. Compare weights, Adam state, progress, runtime and
permanent lineage bit-for-bit; immediate parent hashes legitimately differ.
Retain observed actual optimizer calls, positive finite formula-to-projection
gradients, input immutability, all artifacts and refusal controls.

The next inference step needs an explicit trained v2 scorer/generator and a real
source-producer receipt joined to the exact vector consumed. Do not relabel
this successor as a zero-step v1 head, fill an encoder identity with a decoder or
vector hash, or use arbitrary engineering vectors to claim autoformalization.
Statutory fitting additionally requires reviewed targets/contexts, source and
edition/rights provenance, group/exposure guards, independent holdouts and
qualification. Those gates, 768D/native4096 extensions and training quality
comparisons remain separate work.
