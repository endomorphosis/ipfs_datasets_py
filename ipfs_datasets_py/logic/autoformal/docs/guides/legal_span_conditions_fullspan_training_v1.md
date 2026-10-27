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
The later 632-case result below closes that selected initial parity gate. The later controller and matched-pair results close the selected binding and fixed-fit gates. Independent full-IR/per-ID retention and all 32 permission decisions remain next.

## Source-only capture from the four-tensor runtime

`captured_inference(runtime, checkpoint, rows, **kwargs)` reuses one runtime
returned by `restore_optimizer`. It performs no restore or optimizer update.
Pass the same checkpoint-validation keyword arguments used for restoration.

```python
runtime = profile.restore_optimizer(torch, loaded, **kwargs)
source_rows = [{"id": row_id, "source_text": text, "latent": vector}]
capture = profile.captured_inference(runtime, loaded, source_rows, **kwargs)
```

Each call accepts 1–128 unique source IDs and exactly the three displayed fields;
label, target and reference fields are refused before model forwards. The original
source tokenizer and greedy decoder remain the readout owners. The packet includes
complete original greedy rows and same-forward `joint-source-span-scores/v1` heads.
Use the existing `joint_span_selection.select_joint_spans` for the independent
joint readout. No extra model forward is needed for capture or joint selection.

The same runtime supports successive chunks. Counter deltas belong to each call;
the cumulative count remains on the runtime. The 168-row TRAIN panel therefore
uses chunks of 128 and 40 without resetting counters or restoring another model.
Model, optimizer, config, source bindings, RNG, grad mode, hooks and callable
witnesses are checked around capture. The witness is an in-memory consistency
check and grants no execution or semantic authority.

For the retained initial-parity gate, persist and freeze all new raw/joint outputs
before opening any retained final-F18 comparison outputs. Compare complete head
values in binary32, complete greedy rows and joint rows with original source-ID
and text-hash joins. Keep this compatibility result separate from reference-label
scoring, paired training, source meaning and four-width evaluation.

The [45-case capture qualification](../../../../../docs/autoformalization/evidence/legal-ir-f18-source-capture-qualification-20261027.json)
and [separate 632-case authentic parity](../../../../../docs/autoformalization/evidence/legal-ir-f18-initial632-parity-20261027.json)
qualify the current source generation. All 194,812 head scalars, complete greedy/formal
rows and joint rows match retained final F18; no training update or label scoring ran.
Checkpoints remain bound to their exact source generation. The earlier zero-step
delta and 39-case result retain their older source pins and separate scope.
The original controller now has the separate zero-model qualification below. Actual matched fitting still needs its own finite original request, followed by output freezing and separately admitted scoring.


## Closed original trainer controller

Use scripts/ops/legal_ir/run_owned_validation.py with --trainer-request, --expected-request-sha256 and --resource-ledger for the explicit owned-f18-conditions-training-request/v1 branch. The validation request/default path remains separate. A request never grants admission: the normal selected source tree constructs the unchanged genuine DaemonResourceReservation, bound to its existing scheduler and storage roots.

mode=native_probe requires compute=null and performs zero payload/model/forward/update work after the actual offline READY/RUN gate. mode=paired_fit uses only the fixed original worker entry; it accepts no arbitrary argv, callable or resource factory. compute has exactly input_descriptors, initial_parity, runtime_contract, population_manifest (each a bounded path/bytes/sha256 metadata reference), max_steps_per_arm=32 and max_seconds_per_arm=32 (exact integers). It fixes arms0/.25 and the existing input/policy roots; outer original admission is still required.

The owner retains a real pipe through compute so parent loss revokes the isolated child group. Source/request hashes and heartbeat renewals are polled once per second with forced boundary checks; local process/RSS checks remain faster. This is cooperative isolated-process-group observation, not containment of arbitrary escaped descendants or a kernel quota. Initial and final source hashes, READY identity/network facts, start/release/terminal journal entries and native/group cleanup are recorded. Ambiguous prior starts and incomplete cleanup require original recovery; no automatic retry is granted. Retained failure storage is independent of source/native closure.

Each complete arm saves its four-tensor checkpoint and full training report, restores once for source-only632 capture and writes raw/joint files under exports/f18-paired. The complete pair-output-freeze.json precedes any independent reference scoring. Partial deadlines persist partial artifacts, return nonzero and retain the original claim for explicit recovery. All authority/promotion flags stay false.

The separate original-owned matched pair reports 64 updates and frozen candidate outputs. The next adapter belongs in the existing `formula_generation_metrics.py` owner, reusing `compare_free_running_formulas`; preserve original readouts and defer quality claims until independent post-freeze scoring.
