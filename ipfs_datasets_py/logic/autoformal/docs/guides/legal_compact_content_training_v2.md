# Compact-content engineering training and exact resume, v2

Canonical implementation:
`ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_training_v2`.
This is an additive successor to the weights-only v1 head. Source presence alone
is not a training result, checkpoint qualification, or authorization to fit laws.

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

## Qualification and subsequent gates

The original two-row CPU protocol uses two independently authored fictional
source/catalog contexts and explicit labels, plus arbitrary 384D vectors. Run
two updates uninterrupted and compare them with one update → exclusive byte
save → hash-checked load → one update. This is **four actual updates across two
trajectories**, not two. Compare weights, Adam state, progress, runtime and
permanent lineage bit-for-bit; immediate parent hashes legitimately differ.
Retain observed actual optimizer calls, positive finite formula-to-projection
gradients, input immutability, all artifacts and refusal controls.

The existing [trained v2 scorer/generator](legal_compact_content_trained_runtime_v2.md)
and [operation-local prepared v3 consumer](legal_compact_content_prepared_runtime_v3.md)
already consume this checkpoint schema. Reuse those owners; a real source-producer
receipt still needs to be joined to the exact vector consumed. Do not relabel
this successor as a zero-step v1 head, fill an encoder identity with a decoder or
vector hash, or use arbitrary engineering vectors to claim autoformalization.
Statutory fitting additionally requires reviewed targets/contexts, source and
edition/rights provenance, group/exposure guards, independent holdouts and
qualification. Those gates, 768D/native4096 extensions and training quality
comparisons remain separate work.

The [four-row varied-population qualification](../../../../../docs/autoformalization/evidence/legal-ir-varied-compact-resume-20261023.json), completed2026-10-23, passed one selected case / three pytest phases. Four authored source groups share one independently constructed context; their target lengths are47,51 and65 total IDs. Five uninterrupted updates exactly match three updates followed by byte-save, hash-checked load and two resumed updates in model weights, named Adam state, population, runtime and progress. Immediate parent hashes legitimately differ. Final progress is five steps, one completed epoch and row cursor1.

Independent Torch observers recorded ten physical updates, twelve GRU forwards, nineteen model constructions, eighteen state restores and six Adam constructions. The two model-only BOS observations on the same third row contain1,074 saved scores; all paired scores and selections are exactly equal. Eighteen complete payloads totaling11,487,753 bytes were read back; original source/native/storage custody closed. This cohort does not repeat the old two-row campaign or exercise autonomous generation. Source-encoder authentication, permitted context, heldout accuracy, training gain and legal/graph/Lean admission remain unestablished; both eligibility masks remain zero.

## Persistent compact source-conditioning profile, v1

The separate numerical owner `legal_compact_content_persistent_v1` now reuses
`decoder_distillation_experiment_v2.bind_persistent_model` under an explicit
compact384/537 checkpoint and training contract. The original v2 source and
checkpoint profile above remain unchanged. This new profile is for the same
authored engineering population contract, with all authority flags false and
both training/evaluation masks zero. Its [closed two-mode qualification](../../../../../docs/autoformalization/evidence/legal-ir-compact-persistent-conditioning-20261023.json)
passed two cases / six phases,20 physical updates and38 forwards; these are five
unique trajectory steps per arm, each repeated through a3 + 2 resume. All46artifact
references, complete checkpoints, dense CE matrices and observed adapter updates
remain retained under the original source/native/storage owners.

The public API is `build_compact_content_persistent_v1`,
`compact_content_persistent_sha256`, `compact_content_persistent_bytes_v1`,
`load_compact_content_persistent_v1`, `train_compact_content_persistent_v1` and
`score_compact_content_persistent_v1`. Build accepts only a valid original v1
head and the unchanged complete population/row contract. It copies thirteen
body tensors, adds the zero-initialized `source_to_embedding.weight`, and creates
fresh Adam for all fourteen named parameters. The donor and initialized
persistent weights have separate permanent commitments. Genericv2/CP128
checkpoints or optimizer moments cannot be relabeled into this profile.

`conditioning_mode` is exactly `every_step` or `first_step`; `source_space` is
a nonempty caller-declared unverified string. Resume and model-only scoring
require independently supplied `expected_conditioning_mode` and
`expected_source_space` matching the checkpoint. A dimension or string match
does not establish native encoder compatibility. Both modes have identical
capacity and start from identical tensors; `first_step` learns a residual at
BOS and is distinct from the original initial-hidden-only donor.

Training retains the existing full537 way CE, ordered complete targets, one-row
batches, maximum16 updates per call and exact named Adam/runtime/population
resume. Both modes matched donor logits with a zero adapter, then showed real
nonzero adapter gradients and updates. The5 versus 3 + 2 traces reproduce complete
final checkpoint values apart from immediate-parent lineage. Closed controls
reject wrong modes/spaces/profiles, changed populations, malformed tensors or
Adam steps and duplicate JSON before updates.

Checkpoint transport performs complete structural/runtime checks without model
or Adam restoration. Training restores both; scoring restores model tensors
only and creates no optimizer or backward/update work. Prefix scoring returns
all 537 logits at each supplied position, preserves explicit per-sequence source
and consumed-prefix state, and supports a bounded incremental mode. The fixture
compares every position of the independently fixed `[1,3,4]` prefix within 1e-6.
This is raw prefix scoring, not grammar selection or autonomous generation.

Zero and shifted conditioning reports change both inherited and new source
paths. They are retained observations, not an isolated adapter effect or a
source-fidelity/accuracy measurement. Real-law fitting still requires reviewed
complete source/context/AST targets, permitted inference context, compatible
source-space evidence and grouped independent selection/evaluation. A compatible
autonomous typed consumer remains a separate implementation. No encoder capture,
held-out/statutory accuracy gain, graph admission or Lean qualification follows.

Qualification boundary for this publication: the linked receipt remains the original
P-generation two-case/six-phase qualification, with20 physical updates and38
forwards. Its existing imported numerical/test leaf sources match this selected
public baseline; the exact new owner and owning-test bytes are unchanged. The
historical `validation_pytest.py` qualification controller differs publicly and
is not ported here. The unused checkpoint-hub/target-compatibility/generation
frontier sources in the frozen forest are not added or replaced. This publication
performs no new tests, model operations or current public initializer/controller
qualification and introduces no autonomous or statutory accuracy claim.

## Explicit persistent forced-lookahead consumer, v2

The separate `legal_compact_content_persistent_runtime_v2` reuses the immutable
v1 serving projection and original checkpoint/model/runtime/RNG/parameter/close
helpers. It requires an explicit forced-suffix horizon0..16, keeps the100-new-ID
cap and one incremental model lifetime per nonempty call, and selects from all
537 raw scores through the separate v2 policy. It preserves the nested old
budget and raw-selector baselines. The intact validator still checks retained
checkpoint targets and Adam metadata; neither enters the numerical serving view.

The original two-mode/four-call fixture and independent BOS references are
reused. All four outputs must be exclusive, fsynced and rehashed before the
original target-comparison gate opens. Source/context/weights, fixture provenance
and exposed-versus-heldout status remain fixed. No fitting or re-encoding is
part of the policy intervention.

The separate [accepted consumer qualification](https://github.com/endomorphosis/ipfs_datasets_py/blob/main/docs/autoformalization/evidence/legal-ir-compact-persistent-forced-lookahead-generation-20261023.json) passed2 cases/6 phases and retained4 calls across2 exposed authored source rows and both conditioning modes, with unchanged weights/inputs,100-ID cap and horizon8. All4 outputs blocked: typed candidates, exact token-ID matches and exact compact-content matches remain0/4. Emitted lengths are31/31 for every_step and49/49 for first_step. Actual work was162 GRU forwards including2 independent BOS references,160 selections,6 model constructions/12 state installations and zero training/optimizer work. All4 outputs were durable before reference comparison; original source/native/storage custody closed. This delays the retained dead end without establishing a valid completion, conditioning winner or reconstruction gain. The pure portable's earlier combined-bundle-pending flag remains a historical cutoff; this accepted consumer and joint source selection supersede that queue state without changing the pure qualification scope.

The first v2 outer worker failed after two passing cases/six phases because it
compared the old eight-field saved summary against the new eleven-field summary.
Its independent late counters, callable bindings, reference-open observations
and checked compile-buffer archive were never written. That attempt remains
failed and unpromoted; its partial test-owned reports do not replace the missing
independent witnesses. The versioned observer correction independently derives
all old fields and all three v2 additions and enforces an exact closed schema.

A separate future observer improvement should persist independent counters,
callable bindings, reference-open observations and checked compile buffers
before fallible post-run summary checks, while retaining explicit failed status.
The minimal observer compatibility fix does not implement that refactor.

Local feasibility, typed/exact IR, source-meaning reconstruction, legal-text
reconstruction and exact source bytes retain separate metrics. Exposed fixture
results establish no heldout/legal quality, learning gain, graph or Lean
admission. Reviewed complete source/context/AST populations, native-space
compatibility, grouped independent evaluation and explicit new-schema batch/graph
intake remain separate next gates.
