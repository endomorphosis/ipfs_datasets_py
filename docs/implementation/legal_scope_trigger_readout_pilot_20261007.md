# Frozen-donor learned-trigger readout pilot — October 7, 2026

The completed bounded comparison improves O/P/F class exactness on a fresh
64-positive authored panel from **19/64** for the frozen donor to **29/64** with
a global residual readout and **47/64** with a predicted-trigger residual
readout. Exact emitted proposals are **11/64**, **17/64** and **30/64**;
whole-proposal exactness among the 32 nonempty-condition cases is **4/32**,
**7/32** and **12/32**. These are experimental construction targets, not reviewed
statutory gold or measurements of legal accuracy.

The implementation is
[`legal_scope_trigger_readout.py`](../../ipfs_datasets_py/logic/formalization/autoencoder/legal_scope_trigger_readout.py).
It adds a residual three-class readout to the exact selected kernel-3 checkpoint
from the [earlier source occurrence pilot](legal_scope_span_decoder_pilot_20261007.md).
The donor and its full Adam state stay frozen. Only 4,355 adapter parameters are
fitted in each arm; total model parameters are 26,685 in each. The global control
uses the mean donor encoded token states before `global_projection`. The other
arm uses normalized soft interval coverage `P(S <= t) * P(E >= t)` from the
**donor-predicted** modality endpoints on real tokens. It uses no oracle span,
class keyword lookup, source parser, native latent vector or reference at
inference. The two arms share exactly initialized adapter tensors, with a zero
final projection; initial donor core outputs and logits match on the measured
16-row batch.

Only the O/P/F class readout changes. Support, modality-occurrence and other
endpoint heads, optional-presence heads and caller attachment remain with the
frozen donor and existing proposal owner. Positive support refusals and
structural blocks therefore remain obstacles. The five occurrence facets are
modality, actor, action, optional object and optional opaque condition. `rule`
or `statement` attachment is an explicit caller premise, **not a learned label**.
Source meaning/context remain unreviewed and unresolved; all five admission
masks are zero and `formal_output` is null. No Lake execution or Lean admission
is claimed. Existing 8D, 384D, 768D and other model lineages, caches and default
runtime selections are preserved.

## Fresh authored corpus and fitting protocol

The fresh corpus contains 512 supported and 512 unsupported TRAIN sources,
64 supported and 64 unsupported selection sources, and 64 supported and 64
unsupported final sources. Each unsupported derivative shares its positive
parent source group and caller premise: 512 TRAIN groups and 64 groups in each
evaluation split. All 1,280 source strings and source identities are new, with
normalized actor/action/object/condition inventories disjoint across these
splits and from all splits of the earlier 1,280-source corpus. Semantic heads
are also checked, so freshness is not obtained just by changing a prefix.
Eight word-order templates and modal aliases are deliberately shared. Unicode,
multiword facets, repeated actor/object occurrences and four optional-object/
condition cells remain represented; each evaluation cell has 16 positives.
Half-open Unicode character anchors are captured during construction.

Unsupported categories are modal deletion, token-local modal anagram, extra
exception and second rule, with 16 of each in final. Anagrams preserve token
order, spaces, UTF8 byte length and the changed token's byte multiset, using
separate TRAIN, selection and final permutations. These are outside the declared
single-rule engineering grammar, not legally false statements. Unsupported
references have no structural target or negative class label. Construction
review and transport validation do not establish independent legal review.

Both adapter arms use seed 24603, AdamW learning rate 0.003, zero weight decay,
gradient clipping 5.0, and the same 240-update schedule. Each scheduled batch
contains eight supported and eight unsupported input records. The adapter
encodes and optimizes on the eight positives only; it does not encode or train
on the eight negatives. Across both arms this is **7,680 input-record
presentations, 3,840 encoded positive presentations and 3,840 ignored negative
records**, with 480 actual optimizer updates. Per arm the corresponding counts
are 3,840, 1,920 and 1,920, with 240 updates. This is adapter fitting with a
frozen donor, not full-donor Adam continuation or a new support-head fit.

The head accepts at most 8,192 source characters, 96 tokens and 64 UTF8 bytes
per token without truncation. It emits a structured occurrence prediction,
not an autoregressive formula with a 512-token output budget. Selection at
updates 0, 120 and 240 maximizes raw positive class exactness, then exact emitted
positive proposals, then prefers fewer updates. It selects global update 120
and predicted-trigger update 240; both arms nevertheless complete 240 updates.
Both selections and checkpoint hashes are durable before final references are
parsed, and all three final prediction files are durable before their reference
join. This is a runner-enforced numerical barrier, not an authors-blind claim.
Final references supply neither gradients nor selection. This final panel is
now exposed and must be retained as such in future work.

## Fresh final results

| Measurement | Frozen donor | Global readout | Predicted-trigger readout |
| --- | ---: | ---: | ---: |
| Selected adapter update | — | 120 | 240 |
| Adapter updates completed | 0 | 240 | 240 |
| Raw O/P/F class exactness | 19/64 | 29/64 | 47/64 |
| Exact emitted positive proposal | 11/64 | 17/64 | 30/64 |
| Exact whole proposal with nonempty condition | 4/32 | 7/32 | 12/32 |
| Positive proposal emitted | 43/64 | 43/64 | 43/64 |
| Positive learned refusal | 19/64 | 19/64 | 19/64 |
| Positive structural block | 2/64 | 2/64 | 2/64 |
| Raw all-five-span exactness | 49/64 | 49/64 | 49/64 |
| Learned unsupported refusal | 53/64 | 53/64 | 53/64 |
| Unsupported incidental block | 5/64 | 5/64 | 5/64 |
| Unsupported proposal emitted | 6/64 | 6/64 | 6/64 |

Raw class and span counts include all 64 positives, including refused or blocked
rows. Raw exact endpoints do not establish an exact emitted proposal. The frozen
raw modality, actor, action, object and condition spans are exact on 64/64,
61/64, 54/64, 61/64 and 63/64 respectively. Nonempty object and condition spans
are 29/32 and 31/32; totals include correct null cases. All six unsupported
emissions occur in the modal-anagram category. Neither readout reduces them.
The result supports this bounded feature comparison; one seed and a shared
authored grammar do not establish general legal-language performance or
convergence. Positive refusal and unsupported-emission learning require their
own later matched hypothesis and a new sealed final panel.

The frozen gate and endpoints allow at most 38/64 exact emitted positives on
this cohort. Modality errors among those 38 emission-ready rows are 27, 21 and
eight for donor, global and trigger readouts. The other 26 rows need changes to
nonclass behavior. For nonempty conditions the frozen ceiling is 14/32; trigger
gets 12/32. The gerund-agent template has incorrect action spans on all eight
positives, six refusals and two emitted proposals, so it remains 0/8 whole exact
despite five correct trigger classes. These posthoc diagnostics do not authorize
retuning the now-exposed final.

## Postfit retention on the earlier exposed source cohort

A separate read-only evaluation checked the selected adapters on the earlier
64-positive/64-unsupported cohort after the fresh run, with no optimizer updates
or checkpoint selection changes. Donor/global/trigger class accuracy is
25/64, 28/64 and 53/64; exact emitted proposals are 12/64, 15/64 and 29/64;
nonempty-condition whole exactness is 4/32, 9/32 and 13/32. All 128 donor
prediction dictionaries exactly replay the archived original panel, and nonclass
fields remain identical across the three new panels.

Aggregate gains do not mean every previous success is retained. The trigger
readout loses five formerly correct classes and two formerly exact whole
proposals, while gaining 33 classes and 19 whole proposals. The global control
loses 17 classes and eight whole proposals, while gaining 20 and 11. These
case-level losses stay visible. This earlier exposed cohort is posthoc retention
only, not fresh holdout or a fitting/selection input. The 384 evaluated panel
rows include 256 adapter and 128 donor rows; the evaluator's extra donor-logit
passes make 512 top-level forward invocations. No model is promoted by this check.

## Resource and reproduction evidence

The successful physical run is
`workspace/test-logs/legal-trigger-readout-pilot-20261007-01/attempt-01`.
`results/training-results.json` has SHA256
`8bb4d85371ce1fca3c7f4f6f0eeef33e43469bfb1122206cde2d83c4c7d97705`.
Training uses CPU with two Torch threads and no CUDA initialization. The owned
leader exits zero, is reaped, and has zero live group processes. Its own CPU
lease and 200 MB disk reservation are released after durable cleanup. A bounded
current snapshot confirms that own lease absent; the earlier failed scope
pilot's separate 200 MB disk claim remains retained. Other claims are left
untouched, with no scheduler reset or automatic reconciliation.

The independent owned-group RSS sampler records 15 gated, **14 model-phase**
and two post-model observations. Model-phase sampled peak is **758,779,904 bytes
(723.6 MiB)**, with a maximum observed model-phase gap of **1.032 seconds**.
The model gate-permission-to-observed-leader-reap window is 13.635 seconds;
it includes imports and guardian polling, not isolated optimizer time. Requested
one-second waits include additional collection/fsync latency. These are sampled
summed process-group resident pages from a non-atomic `/proc` census: brief
peaks can be missed and shared pages can be counted across processes. There is
no absolute-peak, kernel memory-cap or continuous lease-coverage claim. Final
disk accounting checks the full claim before release and explicitly excludes
later terminal receipts.

The artifact lane is
[Publicus/legal-ir-autoencoder: experiments/trigger-readout-20261007/run-01](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/09ac0af19c801b53216f83c3544c8d54b763f091/experiments/trigger-readout-20261007/run-01).
The selected global checkpoint SHA256 is
`b9ce4e8e3fca1284060905d1892fc89cb15a36925436af528eae787cccbc6f9c`;
the selected predicted-trigger checkpoint SHA256 is
`6e4be3abad5eafa47cc8a496bea561a8b0ea4ccb54db27273278e82e88facd4f`.
Each custom `legal-scope-trigger-readout-checkpoint/v1` JSON checkpoint embeds
the exact donor JSON bytes, donor hash, adapter tensors, full adapter Adam state,
update count, mode, feature recipe and producer bindings. The donor SHA256 is
`9809ec3fd092536f8c4effb74d8a401dc5db9ff9a031952a1e3f92f9c7292c6e`.
The readout implementation SHA256 is
`983b69b8e293aa6211fd8322f9ba6bfe6fa5b8cb853c2d4d0cace1e7e5046344`.
Restore rejects changed producers/profile, donor bytes, parameter inventories,
shapes, nonfinite values and incompatible optimizer progress.

```python
import hashlib
import json
from pathlib import Path
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_trigger_readout as head

checkpoint = json.loads(Path("checkpoint.json").read_text())
model, optimizer, completed_updates = head.restore_trigger_readout_checkpoint(checkpoint)
model.eval()
source = "The clerk shall submit notice if notice arrives."
result = head.predict_trigger_readout(
    model, source, "rule",
    expected_source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
)
```

This API call is an experimental prediction/refusal/block example, not a scored
statutory translation. `save_trigger_readout_checkpoint`,
`make_trigger_readout_optimizer` and `train_trigger_readout_step` support explicit
reproduction and adapter resume. Exact model/full-Adam restoration passes in
the completed run. Separate read-only replay reproduces all **256/256** selected
final outputs while leaving donor, adapter, Adam state, mode and RNG unchanged,
with zero additional optimizer steps and no references opened. The combined
readout/donor/proposal test panel passes **93 cases**, with zero failures,
errors or skips. The guardian's **23 pure mock tests** also pass. These checks
validate bounded implementation and custody; they do not add a law-accuracy or
Lake result.
