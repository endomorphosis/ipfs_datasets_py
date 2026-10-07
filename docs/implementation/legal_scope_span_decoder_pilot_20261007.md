# Single-rule source occurrence decoder pilot, October 7

The completed bounded pilot adds an experimental raw-source head for the existing
`legal-scope-span-prediction/v1` transport. The ordered-byte arm produces **12/64
exact positive proposals**, compared with **5/64** for its matched kernel-1
control, and learns **59/64** versus **57/64** refusals on authored inputs outside
the declared profile. Positive reconstruction remains weak. These measurements
concern authored engineering targets, not independently reviewed law or statutory
accuracy.

The implementation is
[`legal_scope_span_decoder.py`](../../ipfs_datasets_py/logic/formalization/autoencoder/legal_scope_span_decoder.py).
It learns support, O/P/F class, optional-object and optional-condition presence,
and explicit start/end pointers for modality, actor, action, object and opaque
condition occurrences. Inference uses generic Unicode token boundaries and the
complete raw UTF8 token bytes; it uses no parser, keyword-to-modality lookup,
teacher, target lookup or native latent vector. Each emitted prediction enters
the existing source-scope proposal validator with an externally expected source
SHA256. Equal actor/object text at separate coordinates remains two occurrences.
The actual head accepts at most 96 tokens and 64 UTF8 bytes per token, without
truncation. The existing 512 context/output ceilings are not increased.

`rule` or `statement` attachment is an explicit caller premise. It is copied to
the proposal when a condition is present and becomes null when the condition is
absent. **Attachment is not learned or inferred from source meaning.** Conditions
remain opaque leaves; this experiment supplies no exception interpretation,
temporal semantics, nested qualifier tree, multiple-rule output or context
resolution. Proposal context and meaning remain unresolved, all five admission
masks are zero, and `formal_output` is null. There is no Lake execution or Lean
admission in this pilot.

## Corpus and matched protocol

The TRAIN split contains 512 supported sources and 512 unsupported sources;
selection and final each contain 64 supported and 64 unsupported sources.
Every positive has one negative in its source group: 512 TRAIN groups and 64
groups in each evaluation split, rather than 128 independent evaluation groups.
All 1,280 raw sources are unique. Source groups and normalized actor, action,
object and condition values are disjoint across splits. Eight declared word-order
templates and the O/P/F trigger inventory are deliberately shared. Half the
positives in each split have an object, and half have an opaque condition.
Unicode, multiword facets and repeated actor/object occurrences are included.
Character coordinates are captured while source segments are appended.

Unsupported references carry no structural target. Their four categories are
modal deletion, token-local modal anagram, extra exception and second rule;
each has 16 final cases. They mean outside this closed single-rule engineering
grammar, not legally false statements. Anagrams preserve token order, spaces,
UTF8 length and each changed token's byte multiset. TRAIN rotates the annotated
operator word left by one character, selection left by two, and final reverses
it. These permutations are mutually distinct and nonidentity. Kernel-1 byte
pooling lacks within-token order; the kernel-3 arm can learn local byte context.
Independent corpus review checks construction and source separation; it does
not establish independent legal review or a global unseen-law holdout.

Both arms use seed 24602, AdamW at learning rate 0.003 and weight decay zero,
the same 240-update schedule, batches of eight positives and eight negatives,
and support threshold 0.5. Each completes 3,840 row presentations, including
1,920 positive and 1,920 negative presentations. Structural losses are masked
on unsupported rows, and absent optional endpoint heads receive no gradient.

Initialization copies every common-shaped parameter from kernel 1 to kernel 3,
places its convolution weights in the kernel-3 centers and zeros the neighboring
weights. The first training batch has exactly matching initial logits; all
16 measured initial wire/proposal/blocker outputs match. Parameter counts are
21,562 and 22,330 respectively, so the ordered arm has 768 additional parameters.
This is a matched bounded comparison with an explicit capacity difference,
not a multiple-seed convergence result.

Checkpoints at updates 0, 120 and 240 are selected by exact positive proposals
plus learned negative refusals, then fewer unsupported emissions, more exact
positives and fewer updates. Both arm selections and checkpoint hashes are
durable before final references are parsed; both final prediction files are
also durable before their reference join. Final labels supply neither gradients
nor selection. The final panel is now exposed and must be treated as retention
in subsequent work.

## Complete final results

| Measurement | Kernel 1 control | Ordered kernel 3 |
| --- | ---: | ---: |
| Selected checkpoint update | 120 | 240 |
| Updates actually completed | 240 | 240 |
| Row presentations | 3,840 | 3,840 |
| Exact emitted positive proposal | 5/64 | 12/64 |
| Positive learned refusal | 20/64 | 18/64 |
| Positive structural block | 9/64 | 5/64 |
| Positive proposal emitted | 35/64 | 41/64 |
| Learned unsupported refusal | 57/64 | 59/64 |
| Unsupported incidental structural block | 2/64 | 1/64 |
| Unsupported proposal emitted | 5/64 | 4/64 |
| Exact positive or learned unsupported refusal | 62/128 | 71/128 |
| Raw all-five-span exactness | 35/64 | 47/64 |
| Raw O/P/F class exactness | 22/64 | 25/64 |

Raw head denominators include every positive, including refusals and structural
blocks. Correct pointers alone do not establish an exact emitted proposal.
The ordered arm has exact raw modality-occurrence spans on 64/64 positives,
but its O/P/F class is exact on only 25/64. Its raw actor, action, object and
condition spans are exact on 64/64, 50/64, 61/64 and 61/64 respectively.
Object and condition presence have three and two false negatives, with no false
positives. All unsupported emissions in both arms occur in the modal-anagram
category; the other three categories each have 16/16 learned refusals.

Among the 32 supported cases with a nonempty condition, exact whole proposals
are 1/32 and 4/32. The ordered raw nonempty object and condition spans are each
29/32; the 61/64 totals include 32 correct null cases. Modality classification and
positive refusals remain substantial obstacles to useful qualifier output.

The physical successful run is
`workspace/test-logs/legal-scope-span-pilot-20261007-01/attempt-02`.
`results/training-results.json` has SHA256
`6fadbc6a09d57e28eecd66bc7a0269a6581effc01d006819ed97c2483dcdcfe8`.
The earlier failed attempt is retained separately and does not contribute
optimizer updates to this successful run. Training uses CPU with two Torch
threads and no CUDA initialization. Resource observations do not measure
model-phase peak RSS or isolated throughput.

## Checkpoint API and retained evidence

The retained publication destination is
[Publicus/legal-ir-autoencoder: single-rule-scope-20261007/run-01](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/6a69f6cf05ffcaf911f7737086c706e06714b8d6/experiments/single-rule-scope-20261007/run-01).
It carries this experimental lane separately from existing model lineages.
The selected kernel-1 checkpoint is `checkpoints/bytekernel1/checkpoint.json`
(originally `checkpoint-120.json`), SHA256
`c803ac62a7ac7d65146b80c2c67d3ed038821355ec7df2532bf150606adab943`;
the ordered checkpoint is `checkpoints/bytekernel3/checkpoint.json`
(originally `checkpoint-240.json`), SHA256
`9809ec3fd092536f8c4effb74d8a401dc5db9ff9a031952a1e3f92f9c7292c6e`.
Use the publication's explicit source and artifact bindings rather than replacing
the frozen producer with an implicit latest implementation.

The custom JSON schema is `legal-scope-span-decoder-checkpoint/v1`. It stores
exact float32 model values, full Adam state, completed-update count, model mode,
closed architecture/input profile and producer pins. Restore rejects changed
producers, Torch versions, parameter inventories, shapes, nonfinite values,
optimizer state and mismatched update counters. Both selected checkpoints pass
exact model and full-Adam restoration in the completed run.

```python
import hashlib
import json
from pathlib import Path
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_decoder as head

checkpoint = json.loads(Path("checkpoint-240.json").read_text())
model, optimizer, completed_updates = head.restore_scope_span_checkpoint(checkpoint)
model.eval()
source = "The clerk shall submit notice if notice arrives."
result = head.predict_scope_span_decoder(
    model, source, "rule",
    expected_source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
)
```

This call returns an experimental prediction, refusal or structural block; the
example is not a scored statutory translation. `save_scope_span_checkpoint`,
`restore_scope_span_checkpoint`, `make_scope_span_optimizer` and
`train_scope_span_step` provide the explicit reproduction/resume interfaces.
The affected decoder/proposal/scope/preflight test panel passes 231 cases with
zero failures, errors or skips, including 28 new decoder cases. Tests cover real
gradient steps, exact resume, inactive-head isolation, Unicode/padding bounds,
tampered checkpoints and proposal refusal boundaries. They do not add a
real-law accuracy result.

The result motivates a later matched hypothesis: learn the O/P/F readout from
model-predicted trigger states or learned trigger attention while retaining
support and endpoint losses. The observed modality-class gap motivates this
design but does not prove its effect. Inference must remain source-only, with no
oracle endpoint, lexical lookup or target-assisted prefix. Such a study needs a
new protocol and freshly sealed final source groups before fitting. Existing
8D, 384D, 768D and 4096D checkpoints, normative cached-runtime owners and default
runtime selections remain preserved.
