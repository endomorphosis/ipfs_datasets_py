# F18 conditions full-span delta checkpoints and continuation

The existing [optimizer owner](../../../../optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v1.py)
owns these APIs. F18/F15, weighted CE, masked KL and the published margin kernel
retain their original owners and bytes. This is a caller-owned numerical primitive:
use a fresh original source/native/resource admission for each model operation.
No callback, bool, environment flag or cached lease descriptor grants admission.
Returned `admitted`, `formalized`, `promoted`, `qualified`, semantic-review and
model-gain flags remain false.

**Current outer v2 status:** [implemented and prepared; current 27-case authored qualification pending capacity](../../../../../docs/autoformalization/evidence/legal-ir-f18-outer-v2-saved-consumer-20261029.json). Existing numerical and zero-step parity proofs remain source-bound and separate. No new TRAIN rate, retained fit, numerical-dispatch or legal/Lean grant follows.

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
The later 632-case result below closes the selected initial parity gate. The separate controller, matched-pair and saved-output results below close the selected binding, fixed-fit and parent-relative scoring gates. No reconstruction or margin advantage was measured; retained comparator and statutory gates remain open.

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
qualify their 2026-10-27 source generation. All 194,812 head scalars, complete greedy/formal
rows and joint rows match retained final F18; no training update or label scoring ran.
Checkpoints remain bound to their exact source generation. The earlier zero-step
delta and 39-case result retain their older source pins and separate scope.
The original controller, completed matched pair and saved-output comparison have separate qualifications below. The comparison supplies parent-relative weak-label diagnostics; retained comparator and statutory gates remain open.


## Closed original trainer controller

Use scripts/ops/legal_ir/run_owned_validation.py with --trainer-request, --expected-request-sha256 and --resource-ledger for the explicit owned-f18-conditions-training-request/v1 branch. The validation request/default path remains separate. A request never grants admission: the normal selected source tree constructs the unchanged genuine DaemonResourceReservation, bound to its existing scheduler and storage roots.

mode=native_probe requires compute=null and performs zero payload/model/forward/update work after the actual offline READY/RUN gate. mode=paired_fit uses only the fixed original worker entry; it accepts no arbitrary argv, callable or resource factory. compute has exactly input_descriptors, initial_parity, runtime_contract, population_manifest (each a bounded path/bytes/sha256 metadata reference), max_steps_per_arm=32 and max_seconds_per_arm=32 (exact integers). It fixes arms0/.25 and the existing input/policy roots; outer original admission is still required.

The owner retains a real pipe through compute so parent loss revokes the isolated child group. Source/request hashes and heartbeat renewals are polled once per second with forced boundary checks; local process/RSS checks remain faster. This is cooperative isolated-process-group observation, not containment of arbitrary escaped descendants or a kernel quota. Initial and final source hashes, READY identity/network facts, start/release/terminal journal entries and native/group cleanup are recorded. Ambiguous prior starts and incomplete cleanup require original recovery; no automatic retry is granted. Retained failure storage is independent of source/native closure.

Each complete arm saves its four-tensor checkpoint and full training report, restores once for source-only632 capture and writes raw/joint files under exports/f18-paired. The complete pair-output-freeze.json precedes any independent reference scoring. Partial deadlines persist partial artifacts, return nonzero and retain the original claim for explicit recovery. All authority/promotion flags stay false.

The separate original-owned matched pair reports 64 updates and frozen candidate outputs. Reuse the frozen matched-arm comparison below and its separate original-owned saved-output result; another fit or capture is unnecessary for this comparison.

## Frozen matched-arm comparison

Use `compare_f18_frozen_matched_arms` in the existing
[`formula_generation_metrics.py`](../../../../optimizers/logic_theorem_optimizer/formula_generation_metrics.py)
owner. It calls the original `compare_free_running_formulas` for complete weak-label
IR and preserves the original raw and joint producer envelopes. Supply `arms`,
`targets`, explicit ordered `expected_ids`, `expected_source_sha256`,
`retention_ids`, `permission_ids` and `unscored_ids`. The fixed arms are `parent`,
`coefficient_0` and `coefficient_025`, each with ten ordered panels and all 632
source IDs. There are 624 explicit compiler weak-label targets, 72 explicit
conditions-present retention IDs, 32 explicit single-rule permission IDs and eight
unscored sources. Membership and missing outputs are never inferred from targets.

The detached report keeps every requested scored ID in the denominator, complete
full-IR/facet results, per-ID retention transitions and all 32 permission decisions
for both raw and joint readouts. Source hashes, ordered IDs, missing or duplicate
outputs and raw/joint occurrence joins are checked. Invalid envelope or coverage
declarations invalidate evaluation rather than silently dropping rows. Generation
declarations are checked for consistency. The pure API does not prove roster,
source or weak-label origin, freeze timing or model behavior.

The [source qualification](../../../../../docs/autoformalization/evidence/legal-ir-f18-frozen-matched-scoring-20261027.json)
records 82 authored pure cases, preserving all 47 prior cases and adding 35 controls,
with 246 passing phases. No Torch, native admission, dataset payload, model or
provider ran in that cohort. Two separate independent saved-consumer fixtures
verify complete accounting and refusal of a late corrupted capture before any
reference opens. The separate original-owned saved-output run below compares the actual frozen
matched pair. This diagnostic is relative to final F18 parent and closes no
separate N11/F15/F16/F17/F19 comparator gate.
Compiler weak labels remain unreviewed; semantic, training/gold, promotion, corpus,
Lean and native-task authority stays false. The original numerical profile and
its refusal-only `score_frozen_cases` are unchanged.

### Retained saved-output result

The separate saved-only validation verified all 60 frozen capture files
(48,323,901 bytes) before opening reference bodies: 20 retained final-F18 files
and 40 candidate files. All 19 selected source pins stayed unchanged; original
source/native/storage custody closed with zero live child processes or RSS. It
ran no model forward, optimizer update or provider call. This original validation
is separate from the 82-case author cohort and the two consumer fixtures.

| Readout | Final F18 parent | Coefficient 0 | Coefficient 0.25 |
| --- | --- | --- | --- |
| Complete IR /624 compiler weak labels | 405 raw; 428 joint | 405 raw; 428 joint | 405 raw; 428 joint |
| Conditions-present TRAIN retention /72 | 70 raw and joint | 70 raw and joint | 70 raw and joint |
| Target-P modality retention /32 | 32 raw and joint | 32 raw and joint | 32 raw and joint |
| Raw abstentions | 117 | 117 | 117 |
| Joint abstentions | 18 | 19 | 19 |

The32/32 measure requires the predicted rule-modality list to equal `[P]`.
Complete-IR exactness is scored separately; this supplies no legal-permission
correctness claim.

All 624 per-ID full-IR gain and loss sets are empty for both candidates and both
readouts; aggregate equality hides no exact-match turnover. The two persistent
TRAIN failures affect conditions in
`matched-temporal-train-condition_exception_duration-0-p-absent` and
`matched-temporal-train-condition_exception_duration-0-p-present`. Both candidates
add a joint abstention on
`targeted-loss-authored_dev-actor_duration_name-0-f-absent`; the parent decoded it
already incorrectly on actor and conditions. Joint modality matches decline from
547/624 to 546/624. Fresh DEV and TEST each remain 0/36 complete-IR matches in all
three arms and both readouts; the eight law snippets remain unscored.

The engineering comparison completed successfully and measured no reconstruction
gain or margin advantage. Preserve candidate status. The later fixed-case diagnosis below records persistent TRAIN ranking and DEV retained-domain failures. A separately versioned TRAIN-only recipe and the original retained comparator gates remain next. This diagnosis grants no held-out
tuning or additional fit. Compiler weak labels do not establish statutory meaning,
reviewed gold, four-width quality, corpus/Lean admission or scientific-task success.

## Validated joint producer route and fixed-case diagnosis

The [fresh qualification and diagnosis](../../../../../docs/autoformalization/evidence/legal-ir-f18-conditions-ranking-diagnosis-20261028.json) adds a producer-route guard to the same metric owner. Original joint status must be `selected` or `abstained`. Already-`decoded`, missing or other joint statuses invalidate provenance and receive no exact-IR or permission credit. Raw `decoded` rows retain their original route and all seven-facet semantics. A fresh 90-case, 270-phase run passed in 7.232 seconds with 26 source pins and complete original cleanup. The older 82-case source-595 qualification and whole 624-row outcome stay separate.

Four authored controls cover literal rank 2 with gap 2, rank 45 outside the top eight, a DEV tie with no supplied gold, and refusal before opening a mismatched source. Their six selector calls ran in a separate original admission with 71 pins. The actual saved-only scope then authenticated 60 files before TRAIN labels, parsed 12 capture files, and ran exactly nine selector replays at unchanged `top_k=8` and `max_search_nodes=50000`. All complete cached joint records and original greedy observations reproduced; 73 source pins and original cleanup checks passed. Only canonical preparation of the original 168 TRAIN rows supplies label coordinates. DEV rows contain source data only, and no DEV gold is opened or supplied to selection.

| Conditions-present TRAIN case | Parent rank / best-minus-gold gap | Coefficient 0 | Coefficient 0.25 |
| --- | --- | --- | --- |
| `condition_exception_duration-0-p-absent` | 2 / 0.656990 | 2 / 0.452349 | 2 / 0.412020 |
| `condition_exception_duration-0-p-present` | 3 / 0.396683 | 2 / 0.193958 | 2 / 0.161106 |

Displayed float32 gaps are rounded; the capsule retains the exact scalar observations. All gold candidates remain in the top eight, gaps remain positive, and no active selected other facet overlaps gold conditions. Search completes without exhausting its budget. These observations support a residual TRAIN head-ranking interpretation; they supply no hidden-state or gradient proof. Both candidate DEV states reproduce `no_compatible_assignment_in_retained_domain`, while the parent selects. The authored tie fixture is a separate control path. This operation performs no whole 624-row rescore, new model load, forward, gradient, update or fit and establishes no accuracy gain.

The 90-case request uses actual source-pinned original launcher `0e302d2c`. Its recorded preflight handling event remains a limitation. The passing positive validation path transfers no qualification from `66a608dc` and does not qualify the new pre-owner-refusal branch.

### Prospective optimizer metadata contract, 2026-10-28

The [companion metadata owner](../../../../optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_optimizer_recipe_v1.py) exposes `build_optimizer_recipe` and `validate_optimizer_recipe`; `recipe_digest` aliases the original checkpoint digest. The [separate qualification](../../../../../docs/autoformalization/evidence/legal-ir-f18-optimizer-recipe-metadata-qualification-20261028.json) passed 160 pure cases (480 phases) in 16.339 seconds with no failures, errors, skips or guard denials. It keeps authenticated `donor_config` at learning rate 0.001 and the complete immutable v1 policy separate from detached `optimizer_recipe`. Only its explicit prospective learning rate changes. Validation rebuilds expectations from independent caller kwargs and compares literal bounded canonical JSON; outputs are detached and all 14 authority flags remain false.

No executable numerical profile, optimizer, checkpoint, restore, capture or original training request is implemented here, and no new rate is selected. Source hashes record continuity rather than physical input authenticity or whole-process attestation. This pure cohort opens no historical payload and imports no numerical library. Original source/resource custody, fresh 632-row parity and scientific gates remain separate.

### Recipe-bound numerical checkpoint and updates (v2)

The [v2 numerical owner](../../../../optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v2.py) exposes `build_checkpoint`, `validate_checkpoint`, `save_checkpoint`, `load_checkpoint`, `restore_optimizer` and `run_admitted_updates`. The [32-case genuine synthetic qualification](../../../../../docs/autoformalization/evidence/legal-ir-f18-v2-numerical-qualification-20261028.json) covers 96 phases, independent Adam math, original-objective trajectories and disk resume. V1/profile56 and the pure metadata owner remain unchanged.

Every call requires the same original `state`, `provenance`, `records`, `teacher`, `weights`, `expected_bindings`, `recipe`, independent `learning_rate` and `margin_weight`. `recipe` is validated against `provenance["config"]` and the independently supplied inputs before restoration or persistence. Its complete content is the checkpoint's `training_policy`. The new checkpoint schema is `conditions-fullspan-f18-four-tensor-checkpoint/v2`; a v1 checkpoint is refused. Donor config remains at 0.001; a fresh Adam is constructed directly at the recipe rate, with named moments restored only from a matching v2 checkpoint.

`run_admitted_updates` preserves the original 168-row schedule, seed 1729, batch 12, 32 cumulative updates and 32-second call ceiling. It returns `(checkpoint, report)`. Reports separate actual optimizer rate from donor config rate and retain pre-update margin inputs and original CE/KL details. The original outer owner must freshly admit numerical work. The function is a bounded numerical primitive, not a resource or task admission API.

The numerical-only 32-case scope used the unchanged original R physical-v2 validation owner/plugin with normal W product imports. The public W validation frontend and its trainer branch were unchanged. That historical scope qualified no retained donor run, capture, 632-row parity or trainer-v2 mode; the later explicit v2 capture and parity results below advance those separate gates. V1 capture APIs still cannot consume a fabricated v1 view of this runtime. No experiment rate or retained fit is selected.

### Source-only capture from the v2 runtime

The same v2 owner now exposes `captured_inference(runtime, checkpoint, rows, **kwargs)`. Use the complete independently supplied checkpoint-validation kwargs, including `recipe`, `learning_rate` and `margin_weight`, from v2 restoration. `rows` contains only unique `id`, `source_text` and finite 384-value `latent` triples; each call accepts 1–128 rows. One restored runtime supports successive 128+40 chunks without another restore or optimizer update. The packet uses `conditions-fullspan-four-tensor-target-free-head-capture/v2`, while the unchanged score kernel retains `joint-source-span-scores/v1`.

Capture checks the actual v2 checkpoint/recipe, full42/four-Adam state, original module/parameter/callable/code identities, hooks, sources, native counters and caller context. It reuses the unchanged original decoder/tensor/greedy-verification helpers, performs one existing source forward per row and removes its temporary hook on exit. A failed admitted capture poisons that runtime for later capture; preflight input refusals perform no forward. This in-memory consistency witness grants no admission or physical authenticity.

The [separate qualifications](../../../../../docs/autoformalization/evidence/legal-ir-f18-v2-source-capture-parity-20261028.json) passed 52 genuine synthetic cases (156 phases) on the new source and fresh retained initial parity on all 632 rows. All 194,812 head scalars, complete greedy/formal outputs and joint records match final F18. Both original admissions closed compute, observed descendants, storage and source custody. No retained gradients/updates, scoring, experiment-rate selection or model promotion ran. These 2026-10-28 numerical/source-capture results retain their source bindings. The later trainer and current headroom/parity qualifications below have separate receipts; public physical-v2 frontend reconciliation remains open.

### Explicit v2 original-trainer request and pre-entry recovery

The existing `run_owned_validation.py` trainer branch accepts `owned-f18-conditions-training-request/v2`; `compute` adds only an explicit finite positive `learning_rate`. It accepts no arbitrary worker or caller recipe. After the original RUN boundary, immutable v1 helpers authenticate the donor and all15 bindings, and the worker verifies the exact closed v2 initial-parity metadata. The pinned pure recipe owner builds and validates both fixed margin0/0.25 recipes before arm creation or updates; each recipe is persisted and the same independent rate/recipe accompanies checkpoint build, update, save, reload and capture. Historical parity at0.001 selects no experiment rate.

V2 result/freeze/raw-panel envelopes retain `/v2`, and capture/inference packets retain their genuine v2 schemas. Original joint-score and joint-panel schemas remain unchanged. The existing `formula_generation_metrics` scorer has the separately qualified opt-in v2 consistency contract below. The run-specific outer freeze/recipe/context join implementation is now prepared; its current authored qualification remains pending capacity before retained comparison. Do not wrap v2 chunks in a v1 panel.

The [241-case pure/fake qualification](../../../../../docs/autoformalization/evidence/legal-ir-f18-v2-trainer-integration-recovery-20261028.json) preserves the prior105 controls, adds90 integration cases and46 recovery cases. It opens no retained payload or numerical library. The actual v2-request zero-model probe was refused by the original inventory-count bound before entry/grant/child, and supplies no native-probe or numerical-dispatch pass. Its manual source-close evidence preserves the earlier classifier refusal. The qualified successor recognizes only the exact pre-entry inventory refusal after typed source/exit/no-child/no-grant and original durable-state checks; unknown evidence still requires cleanup. It changes no inventory limit, root, budget or retry policy. The original READY/terminal/journal lifecycle schema remains v1 and request-hash bound. A future successful zero-model probe would still supply no v2 numerical-dispatch qualification.

The finite inventory headroom and actual current-source zero-model native probe have separate qualifications below. Next qualify the implemented thin outer v2 saved-comparison control when original capacity permits; numerical trainer dispatch and fresh training-purpose admission remain separate before a finite TRAIN experiment. Existing physical-v2 validation frontend support remains a separate operational gap; preserve the trainer branch when reconciling it.

### Explicit v2 saved-output consistency contract

Call `compare_f18_frozen_matched_arms(..., expected_training=context)` for v2 candidates. `context` is the closed `f18-frozen-matched-training-expectations/v2` declaration with exact source pins, original15 input bindings, independent TRAIN rate, original donor rate0.001 and both fixed candidate arms. Each arm supplies its expected checkpoint/model/recipe SHA256 and float margin0.0 or0.25. Checkpoint and recipe identities must differ between fixed arms; identical model-state hashes remain allowed. These are independent caller declarations, never expectations inferred from the capture being evaluated.

| Context field | Original outer consumer responsibility |
| --- | --- |
| Source and input commitments | Authenticate donor/source/teacher/masks and source closure independently; join all15 bindings to the frozen worker metadata. |
| TRAIN rate and arm margins | Join the separately preregistered request and complete validated recipes to fixed arms; historical parity at0.001 selects no rate. |
| Checkpoint/model/recipe identities | Verify original frozen descriptors and full recipe contracts before supplying expected hashes; this pure function does not open or validate those bodies. |
| Capture tuple and versions | The scorer checks each candidate panel/capture/inference version and every chunk's fiveidentity fields against caller expectations, including laterchunks and all8unscoredlaw sources. |

The result is `f18-frozen-matched-arm-fidelity/v2`, with detached expectations and a canonical context hash. `training_expectations_consistency_verified` describes the tuple comparison. Origin, physical checkpoint/recipe/source verification, freeze timing, semantic fidelity and admission remain false. Original parent/joint envelopes, seven-facet/full-rule accounting,632source/624target denominators,72conditions retention and32target-P decisions are preserved. Default genuine v1 behavior remains; a v2 inference cannot hide inside a v1 candidate wrapper.

The [200-case original-owned qualification](../../../../../docs/autoformalization/evidence/legal-ir-f18-v2-saved-scoring-20261028.json) requalifies90 old and110 new authored cases. It includes a compare-time import/file-access guard, version/tuple drift, malformed/literal-type expectations and adverse-accounting controls. The first purity setup failed before comparison because pytest still needed imports while installing guards; the corrected full cohort passed. Failed resource admissions, their original outcomes and administrative/recovery scopes remain separate. No real retained-v2 comparison or model training ran.

Before a physical comparison, qualify the prepared run-specific successor of the indexed saved-comparison control. It reuses only the exact archived streaming/closing helpers, never the old v1 main or `strip_score_storage`, and calls the canonical metric projection and scorer. Its contract authenticates all 60 complete raw/joint files before opening seven reference files and joins independent v2 recipe/checkpoint/freeze/source context. This implementation and its current pending authored qualification do not supply a genuine retained-v2 comparison.

### Public inventory headroom and current parity generation

The [2026-10-29 public source qualification](../../../../../docs/autoformalization/evidence/legal-ir-f18-inventory-headroom-parity-20261029.json) ports only the existing finite inventory bound and owning expectation from two million to four million entries. Public resource owner `da6c3596a413ba5c8dab14f9e06a6fc288d7eb9166d261a96abfdf96dd60130b` retains the 220GB cap, exact roots, strict scanner/accounting and explicit release rules. The private physical-validation hook was excluded. Resource bytes enter v1 and nested v2 checkpoint implementations, so this is a new operational/checkpoint generation even though numerical sources `56bd…`/`d80a…` and recipe source `d22b…` remain unchanged. Preserve all old checkpoints, donor bytes and historical receipts.

Separate original-owned scopes passed three existing resource cases/nine phases in 0.109 seconds, 52 genuine numerical/capture cases/156 phases in 65.967 seconds, and 242 pure controller/worker/recovery cases/726 phases in 4.772 seconds. All 80 pins in the final controller cohort remained unchanged; its original owner closed source, compute, processes and storage in 101.547436 seconds. These scopes are distinct from the historical 241-case qualification and its failed native probe.

Fresh retained v1 and v2 zero-step runs each compared 632 rows in 11 chunks, all 194,812 binary32 head scalars including signed zero, complete greedy/formal outputs and complete joint records. Both matched the final F18 baseline with zero retained gradients or optimizer updates. Each `paired_fit` request must bind `compute.initial_parity` to its own exact raw result descriptor indexed by the qualification above:

| Trainer route | Raw parity schema | Bytes | SHA256 |
| --- | --- | --- | --- |
| v1 | `retained-f18-four-tensor-initial632-parity-result/v1` | 31,655 | `738273e56a0bcad5e77825b7227e3a7df49861d02885df6165a7b3cb28bbaf92` |
| v2 | `retained-f18-four-tensor-initial632-parity-result/v2` | 31,777 | `1b564a1658aaee6b0449d3114697f08661239b9436b46a27fc225f19722e1cb3` |

The v1 worker now verifies the fresh raw-v1 schema, exact size/hash, complete 15-field input bindings, independent input/population/runtime commitments, six authenticated assets, donor roots and zero-step panel counts before fitting. The earlier v1 summary capsule and old raw receipt remain historical evidence and are refused as current `compute.initial_parity`; the earlier v2 raw receipt is also refused. A v2 receipt cannot substitute for v1. No retained fit, TRAIN rate, model gain, native-task retry or scientific/Lean admission occurred.

The actual zero-model native probe has the separate qualification below. The outer v2 join implementation is prepared, with current authored qualification pending original capacity. A finite TRAIN-only experiment still requires qualified numerical trainer dispatch, a predeclared objective/rate and fresh original training-purpose admission. Public physical-v2 validation frontend reconciliation remains separate.

### Current zero-model native probe and canonical metric view

The [separate 2026-10-29 qualification](../../../../../docs/autoformalization/evidence/legal-ir-f18-native-probe-metric-view-20261029.json) closes the actual zero-model original trainer lifecycle on the current source. A v2 request acquired the genuine native grant, launched its isolated child and crossed the verified READY/RUN barrier. All 53 source pins remained unchanged. The original owner closed source, native, process and storage custody in 169.0512 seconds; its final named-root inventory counted 2,088,443 entries under the same 220GB cap. The pinned probe branch reports zero checkpoint payload opens, model constructions, forwards, gradients and updates and returns before numerical dispatch. This does not qualify retained numerical training or activate a scientific task. The earlier inventory refusal remains preserved.

The canonical child argv now includes explicit `-B` before bootstrap: isolated Python ignores the environment bytecode setting. The existing before-bootstrap guard requires the interpreter flag. The strengthened existing lifecycle controls and full 242-case/726-phase pure cohort passed in 4.874 seconds with all 80 pins unchanged; original source/native/process/storage custody closed separately. This is distinct from the actual native probe and the earlier 242-case source generation.

Use `f18_metric_capture_view(raw)` in the existing `formula_generation_metrics` owner after the outer consumer authenticates the complete source file. It accepts the genuine parent capture, single trained v1/v2 captures and v1/v2 candidate panels. The returned literal JSON view preserves every schema, metadata/identity field, inference record and chunk order, replacing only each closed occurrence's `scores` value with `None`. It leaves the input unchanged and neither copies nor inspects discarded score payloads. Unknown wrapper/capture schemas, mixed wrapper/chunk generations, malformed occurrence keys and unsupported/cyclic metadata are refused; invalid inference identity and scope values are retained for canonical comparison refusal. Projection performs no file access, import, model execution or physical freeze/recipe/checkpoint authentication.

The original-owned 231-case/693-phase pure metric qualification passed in 18.211 seconds: all 200 earlier cases plus 31 focused view controls, with the earlier test prefix preserved exactly. All 26 pins remained unchanged and the original owner closed source, native, process and storage custody in 112.9395 seconds. The controls cover all supported capture forms/chunks, metadata preservation, detachment, unread score payloads, purity, malformed shapes, unchanged canonical comparisons and adverse v2 identities including unscored law. No retained v2 outputs were compared.

### Prepared outer v2 saved consumer; qualification pending capacity

The [selected prepared-control evidence](../../../../../docs/autoformalization/evidence/legal-ir-f18-outer-v2-saved-consumer-20261029.json) captures five exact UTF-8 sources and hashes for review: archived reader, current saved consumer, authored fixture, shared prefix replay helper and hybrid suffix control. Product owners remain canonical; public code imports none of these workspace controls. Restoring that source bundle on another host requires explicit path/input mapping and appropriate fresh qualification.

The consumer protects seven independently declared reference paths before opening its plan or archived helper source. It binds the original request rate and parity-anchored input/provenance context, validates saved recipes/checkpoint/report joins with existing owners, streams all 60 complete capture files before reference release, and applies closing identity/hash checks. It uses `f18_metric_capture_view` and supplies independent `expected_training` to the existing scorer. Saved custody metadata consistency is distinct from independent native/kernel admission or producer freeze-history proof. The checkpoint-origin check is a bounded metadata projection using the prior donor42 commitment; full state reconstruction, numerical/gradient replay and statutory/Lean equivalence remain false. A diagnostic can exist before a later closing refusal, so success requires the actual original-owner exit and closure.

Current consumer `a003f73c…` is unchanged. Fixture `73badead…` corrects only case 17 to bounded noncanonical recipe bytes after the prior fixture observed 16 expected outcomes and then exceeded the unchanged 128 KiB input limit. Earlier fictional-READY and real-alias inventory failures remain retained. All three admitted failed attempts closed source/native/process custody and their own retained storage claims through original recovery. The current alias cases inject explicit stat fields at the unchanged reader boundary on real regular files; real filesystem-link behavior and alias inventory remain unqualified. No deliberate import/process/network/unowned-write denial injections ran in this inventory.

The corrected full request was refused before entry, claim or child. Its idle wrapper has a separate administrative source-close proof, not a canonical terminal or fixture pass. Both the unchanged 220 GB charged cap and filesystem reservation headroom must pass; full reservations stay charged during writes. Prepared original-owner batches are 32 MiB prefix16 read-only replay and 23 MiB hybrid suffix11. The suffix builds five fresh cases (17 and 21–24), replays six retained cases read-only (18–20 and 25–27), and reuses old shared parent/reference bodies. Both remain unstarted. Preserve independent stale-parity trust and all failed inputs; require separate actual source/native/process/storage closeouts before any composed 27-case result. This preparation selects no TRAIN rate and closes no numerical dispatch, retained-v2 scoring, model gain, semantic or Lean gate.

### Next goal within existing LIR-17

Improve the original TRAIN conditions ranking through an explicit new optimizer contract. These maintained subgoals use the existing programme and create no task IDs, queue, budget reset or native activation.

| Subgoal | Tasks and completion evidence |
| --- | --- |
| Versioned optimizer contract | Pure metadata construction/validation is complete in the separate 160-case contract. Keep v1/profile56 numerical source, checkpoint policy and HF weights immutable, with authenticated donor config at 0.001. A prospective rate belongs only in the detached optimizer recipe; fixture/parity rates select no experiment. Reuse the 32-case v2 mechanics, 52-case capture scope, current raw parity, 242-case trainer/recovery contracts, zero-model native probe and 231-case metric-view qualification. The outer consumer is implemented/prepared with current authored qualification pending capacity; numerical dispatch and finite TRAIN admission remain separate. |
| Source qualification and initial parity | Reuse the requalified 52-case v2 checkpoint/update/capture scope and separate fresh raw-v1/raw-v2 632-row zero-step parity for resource owner `da6c…`. Each preserves all 42 tensors, 38 frozen tensors including modality and complete original readout behavior. Use the exact route-specific raw descriptor above; preserve older source generations. Requalify changed execution sources. Changes to numerical sources, checkpoint implementation bindings or retained inputs also require appropriate initial parity before updates; the original donor/source/teacher/mask bindings and all 168 TRAIN rows remain fixed. |
| Saved comparison orchestration | Qualify the prepared consumer under original capacity using the bounded prefix16 and hybrid suffix11 scopes. Its implementation joins independent request/source/input/rate/recipe/checkpoint context, protects seven references and verifies all 60 complete capture files before release, then calls the canonical projection/scorer. Require actual owner closure and retain adverse outcomes. No current 27-case or genuine retained-v2 comparison is yet qualified. |
| Finite TRAIN-only admission | Seal one experiment bound to source and inputs, using TRAIN evidence only, with a predeclared objective, optimizer state, seed and step, time and storage limits. Review source preflight before launch and acquire fresh original training-purpose custody. Preserve partial and failed artifacts. Do not reset v1 optimizer budgets or rearm scientific cards. |
| Freeze and independent acceptance | Freeze every new output before reference readback. Score full IR, every per-ID gain and loss, retention on all 72 conditions-present TRAIN cases, and all 32 target-P modality checks (complete permission IR is scored separately). Close the original retained comparator no-loss gates under their own contracts. Keep adverse results and held-out exposure. Promotion, statutory and four-width claims require their relevant gates. |

The following immutable-publication description retains its original unscored release cutoff; the separate local comparison above does not change that release or promote a model.

## Published experimental candidate deltas

The [immutable release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/270a753c1f439ac106877e825d5f5a3577916510/releases/20261027-f18-four-tensor-conditions-pair-v1) contains two donor-dependent `conditions-fullspan-f18-four-tensor-checkpoint/v1` JSON deltas and a manifest/README. These are experimental unscored candidates, not standalone 42-tensor checkpoints or a promoted default.

| Arm | Margin coefficient | Immutable delta | SHA256 |
| --- | --- | --- | --- |
| arm-0 | 0.0 | [133639 bytes](https://huggingface.co/Publicus/legal-ir-autoencoder/resolve/270a753c1f439ac106877e825d5f5a3577916510/releases/20261027-f18-four-tensor-conditions-pair-v1/cells/arm-0/results/checkpoint.json) | `d5707c70643538f95ec4a0b1ece2f61dab4e20d9bd8dd0eca5ea5a81baef02b9` |
| arm-025 | 0.25 | [133618 bytes](https://huggingface.co/Publicus/legal-ir-autoencoder/resolve/270a753c1f439ac106877e825d5f5a3577916510/releases/20261027-f18-four-tensor-conditions-pair-v1/cells/arm-025/results/checkpoint.json) | `8db89f121d35aa82440255ff10a631402f868bb9cc02112d94515a762c82e709` |

Reuse the existing donor in `Publicus/legal-ir-autoencoder` at `c9cce4586dd96518088662fb12831173e98e36cc`, file `releases/20261015-modality-conditions-retention-v1/cells/modality-conditions-retention-ce/results/cell-checkpoint.json`, SHA256 `90031d084f2d86cf860c5fc95d2dae374dc254adec70bd85a90893f98c5a1555`. Preserve canonical profile SHA256 `56bd0a248a07de09519f95e5c4bae02ab9d8eb1134b483c257c1f7e7bcb07147` from [the bound source generation](https://github.com/endomorphosis/ipfs_datasets_py/tree/e8b4d34c4534c845a5b052ca6af05e47607feb9f). Load with the existing `load_checkpoint`/`restore_optimizer` APIs and their required independent donor/input bindings.

The [publication receipt](../../../../../docs/autoformalization/evidence/legal-ir-f18-four-tensor-hf-weight-publication-20261027.json) verifies opaque remote file bytes only; no model restore, inference, new training, independent score or legal/Lean qualification ran in this publication scope. Keep all 40 trained raw/joint outputs frozen and use the separate post-freeze scorer before any quality or promotion decision.

For the recorded publication operation, use the pinned virtual-environment SDK through an explicitly isolated Python process (`-I`). This avoids the original launcher's user-site dependency prefix while preserving normal virtual-environment site loading and the original admission boundary. The first import failure and its original storage recovery remain separate evidence; no remote commit was submitted by that failed attempt.
