# F18 conditions full-span delta checkpoints and continuation

The existing [optimizer owner](../../../../optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v1.py)
owns these APIs. F18/F15, weighted CE, masked KL and the published margin kernel
retain their original owners and bytes. This is a caller-owned numerical primitive:
use a fresh original source/native/resource admission for each model operation.
No callback, bool, environment flag or cached lease descriptor grants admission.
Returned `admitted`, `formalized`, `promoted`, `qualified`, semantic-review and
model-gain flags remain false.

A checkpoint persists the four full `start.weight`, `start.bias`, `end.weight`,
`end.bias` tensors and named Adam state. It reconstructs all 42 tensors against a
supplied donor; the 38 frozen tensors, including modality, are not duplicated.
Only conditions row 3 is active: 130 of 780 stored scalars. The other 650 values
must match the donor and their gradients/moments must be zero. At update zero,
Adam `parameters` is empty; afterward exactly four named entries contain typed
`step`, `exp_avg`, `exp_avg_sq`. All tensor values are finite exact binary32.

Supply the same inputs independently on every validation, save, load, restore
and continuation: `state`, `provenance`, all 168 prepared `records`, prepared F15
`teacher`, original row `weights`, `expected_bindings`, and explicit `margin_weight`.
Records retain mixed 72-present/96-absent membership; no tuning/evaluation input is
accepted. Whole-object teacher/weight digests and their row/order/mask joins are checked.

`expected_bindings` is a closed dictionary of exactly 15 fields:

| Field | Meaning |
| --- | --- |
| `schema` | `profile.BINDINGS_SCHEMA` |
| `donor_checkpoint_sha256` | Independently verified raw physical F18 checkpoint SHA |
| `donor_model_state_sha256` | Canonical full 42-tensor donor state digest |
| `donor_provenance_sha256` | Canonical supplied profile provenance digest |
| `source_parent_checkpoint_sha256` | Authenticated donor's parent checkpoint root |
| `source_parent_model_state_sha256` | Authenticated donor's parent model root |
| `context_contract_sha256` | Authenticated context-contract root |
| `training_manifest_sha256` | Original raw training-example manifest root |
| `prepared_training_records_sha256` | Separate digest of prepared 168 records |
| `teacher_checkpoint_sha256` | Original F15 teacher checkpoint root |
| `teacher_model_state_sha256` | Original F15 teacher state root |
| `teacher_capture_sha256` | Original exact detached F15 TRAIN capture root |
| `teacher_training_sha256` | Whole prepared teacher object digest |
| `row_weight_training_sha256` | Whole prepared row-weight object digest |
| `training_mask_certificate_sha256` | Canonical parsed certificate digest, not raw-file SHA |

The outer owner authenticates physical files, certificate and source provenance.
These references establish continuity and do not independently authenticate an
issuer or legal meaning. Raw-file and canonical-object digests need not coincide.
No initial-parity receipt is invented as a checkpoint prerequisite.

Within an operation admitted for the requested numerical work:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    legal_span_conditions_fullspan_training_v1 as profile,
)

kwargs = dict(state=state, provenance=provenance, records=records,
              teacher=teacher, weights=weights, expected_bindings=bindings,
              margin_weight=0.25)
checkpoint = profile.build_checkpoint(**kwargs)
profile.validate_checkpoint(checkpoint, **kwargs)  # pure; no model
ref = profile.save_checkpoint(checkpoint, path, **kwargs)  # pure persistence
loaded = profile.load_checkpoint(path, expected_sha256=ref['sha256'], **kwargs)
# Continuation creates its own model and optimizer restore.
updated, report = profile.run_admitted_updates(
    loaded, torch=torch, **kwargs, max_steps=2, max_seconds=32)
```

`checkpoint_policy(margin_weight=...)` returns the fixed recipe;
`checkpoint_digest(value)` uses the existing canonical digest. Persistence uses
exclusive 0600 creation, a 4 MiB checkpoint cap, strict regular-file/no-alias
checks, expected raw SHA, duplicate-key/nonfinite refusal and all supplied input
bindings. Loading never calls the legacy six-tensor loader or constructs Torch.

For source-only parity, use `runtime = profile.restore_optimizer(torch, loaded, **kwargs)`
in a scope admitted for that operation. Calling this and `run_admitted_updates`
constructs two model/optimizer runtimes; budget both restores.

`restore_optimizer` returns actual `torch`, `model`, copied `config`, `optimizer`,
`named`, `selected`, progress and checkpoint root. This preserves access for the
existing source-only decode/head-capture interfaces. Do not fabricate a legacy
six-Adam checkpoint to pass the old F18 decoder's validator. Restoration requires
CPU float32; a foreign default dtype is refused rather than changing caller defaults.

Continuation reuses original `_batch_indices`/`_advance_progress`: seed 1729,
batch 12, 14 batches per 168-row epoch, at most 32 cumulative updates. Each call has
`max_steps` 0..32 and finite `max_seconds` 0..32; its clock includes setup and checks
the deadline before batches. Partial calls report actual progress/reason instead
of invented completion. The original outer owner enforces its native timeout.
CPU RNG and incoming grad mode are preserved, gradients are enabled only within
the update scope, RNG-consuming recipes refuse, and the model exits in eval mode.
Frozen tensor, inactive scalar and named Adam-step/progress invariants are checked per update.

Reports, separate from the checkpoint, retain complete validated F18 CE/KL details,
margin diagnostics, pre-update row 3 logits/targets, batch identities and state roots.
They are bounded to 32 updates / 32 MiB. Parent/origin hashes establish lineage
integrity; they are not a proof that gradients were replayed.

The frozen generation has a fresh original-owned [39-case synthetic result](../../../../../docs/autoformalization/evidence/legal-ir-f18-four-tensor-persisted-resume-20261027.json)
and a separate [authentic zero-step roundtrip](../../../../../docs/autoformalization/evidence/legal-ir-f18-retained-zero-step-delta-roundtrip-20261027.json):
one original six-tensor Adam restore and one fresh four-tensor Adam restore, zero
forwards or updates, full 42-tensor root `2ed0` and frozen 38-tensor root `8562`.
The earlier 26-case mechanics cohorts remain distinct. These results supply no
new trained weights, 632-case parity, paired fitting, scoring or statutory accuracy.
Next compare source-only initial outputs against the final trained F18 across all
632 cases using retained trained captures, then obtain separate training-purpose
admission for matched 0/0.25 arms of 32 updates. Freeze both complete outputs before
independent raw/joint full-IR, per-ID retention and all 32 permission decisions.
