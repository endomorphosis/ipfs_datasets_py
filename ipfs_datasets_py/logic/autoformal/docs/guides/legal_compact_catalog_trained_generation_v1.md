# Bounded trained catalog continuation

`legal_compact_catalog_trained_generation_v1` continues a supplied prefix through
the existing public `score_compact_catalog_trained_v1` and retains every complete
score receipt. It also provides original-input numerical replay and an adapter
for the existing catalog batch evaluator. The original trained checkpoint and
its training codec remain distinct from the catalog inference policy.

Source installation and this guide do not establish numerical qualification.
Use the exact separately retained admitted validation receipt for that claim.

## Public interfaces

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_catalog_trained_generation_v1 as generation,
)

settings = dict(
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_catalog_context_sha256=catalog_context_raw_sha256,
    max_new_tokens=2,
    prefix_origin="bos_seed",
    catalog_context_origin="caller_supplied_unverified",
)
report = generation.generate_compact_catalog_trained_v1(
    checkpoint, conditioning, [1], catalog_context_raw, **settings,
)
report_sha256 = generation.compact_catalog_trained_generation_sha256(report)

# The output commitment must be retained independently before validation.
validation = generation.validate_compact_catalog_trained_generation_v1(
    report, checkpoint, conditioning, [1], catalog_context_raw,
    expected_report_sha256=independently_retained_report_sha256, **settings,
)
adapter = generation.prepare_compact_catalog_trained_batch_prediction_v1(
    report, checkpoint, conditioning, [1], catalog_context_raw, population_raw,
    expected_generation_sha256=independently_retained_report_sha256,
    expected_population_sha256=population_raw_sha256,
    occurrence_id=occurrence_id,
    **settings,
)
```

The example calls validation and adaptation separately, so it performs two full
replays. Calling the adapter alone already performs its required one replay;
there is no need to call the validator first. Hashing a report computes its
self-address and performs no numerical replay or provenance authentication.

The checkpoint, conditioning and prefix use the unchanged scorer's ordinary
container contract: complete v2 checkpoint dictionary, 384 finite plain numbers
with magnitude at most `1e8`, and a nonempty plain-integer list of at most 512
IDs. Context is the exact complete bytes of the catalog wrapper with an
independent raw SHA-256. Boolean integers, empty prefixes and foreign container
types are refused. `max_new_tokens` is an exact integer from 1 through 12.

`prefix_origin` accepts `bos_seed`, `authored_fixture`, `target_derived_label` or
`caller_supplied_unverified`; `bos_seed` additionally requires exactly `[1]`.
Catalog origins accept the latter three values. Origin labels remain caller
declarations. Every supplied prefix other than `[1]` sets
`exposure.teacher_forcing` true. Either target-derived origin sets
`exposure.target_access` true; the adapter preserves both flags.

## Complete traces and stopping behavior

Each permitted step calls the unchanged public scorer once with the full current
prefix, original checkpoint, original conditioning and exact wrapper. There is
no direct numerical primitive, new model/session, hidden-state cache, grammar,
optimizer or training loop. The scorer supplies all 537 finite scores and uses
the existing catalog selector and lowest-ID tie rule.

`trace` retains every full scoring receipt, including both complete codecs, the
lexical bridge, checkpoint lineage, all logits, selection receipt, runtime flags
and source descriptors. Top-level `initial_prefix_ids`, `selected_token_ids`,
`raw_argmax_ids_by_step` and `generated_ids` distinguish supplied from emitted
IDs. The settings and their hash, original raw/canonical catalog commitments and
final public prefix/decode reports remain in the result. Training history and
optimizer metadata are retained declarations, not authenticated training.

| Generation status | Meaning |
| --- | --- |
| `complete` | This operation emitted at least one ID and the public catalog decoder accepted the complete resulting candidate. |
| `supplied_complete` | The supplied prefix was already complete; the trace contains one zero-forward scoring receipt. |
| `blocked` | The public grammar rejected the prefix or supplied another non-budget blocking reason. |
| `token_budget_exhausted` | The public prefix owner exhausted its local total-ID budget. The exact grammar reason is retained. |
| `step_budget_exhausted` | The prefix remained open after the caller's allowed new steps; reason is `max_new_tokens_reached`. |

After each selected ID, the public prefix owner checks termination before the
step allowance. Reaching EOS on the last permitted step therefore reports
`complete`. No extra scorer call is made merely to confirm that terminal state.
The final catalog decoder receives every resulting ID, including incomplete or
rejected sequences. It preserves unused catalog declarations and subset mappings
when a complete candidate exists.

A forced EOS still performs and counts one numerical forward. A supplied complete,
rejected or locally exhausted prefix performs zero forwards, restores no model,
and retains null `actual_runtime`. Its model/runtime verification flags remain
false. A declared checkpoint runtime does not become a live runtime observation
on these paths. Caller-supplied completed content is not learned reconstruction.

## Replay receipts and accounting

Generation reports use `legal-compact-catalog-trained-generation/v1` and
`bounded-trained-catalog-generation-384/v1`. Their `numerical_forward_count` and
`original_forward_count` describe the same original work; replay and reference
counts are zero. `score_call_count` additionally counts an initial zero-forward
receipt. These categories are not additive.

Validation returns a distinct
`legal-compact-catalog-trained-generation-validation/v1` receipt. It regenerates
from every original input and setting, compares the full report byte-for-byte,
and retains the matching report under `generation_report`. Its
`generation_sha256` identifies that report and `generation_regenerated` is true
only after the full comparison succeeds.

The validation and adapter counters distinguish current work from history:

- `original_generation_forward_count` references the original report's count;
  it is not newly executed work.
- `numerical_forward_count`, `numerical_replay_forward_count` and
  `replay_forward_count` all describe the same one replay performed by that call.
- `original_forward_count` and `reference_forward_count` are zero for those calls.
  `count_categories_overlap` is true.

The adapter's `generation_validation` contains its own mandatory replay receipt.
Its counters and the nested receipt describe the same execution. A separately
called validator or independent arithmetic reference is additional work that an
enclosing qualification ledger must count separately.

## Existing catalog batch transport

The adapter validates the complete independently pinned population before replay:
the existing closed `legal-relational-batch-population/v1` envelope, partition,
selection hash and every unique row's ID, source hash and source-context hash.
It accepts 1–64 selected rows under the existing 128 KiB population limit and
requires the selected occurrence to exist. Malformed unselected rows also refuse
the operation.

The returned `predictions` envelope has the existing
`legal-relational-catalog-token-batch-predictions/v1` schema, complete inference
codec/hash, one `prediction_row` and honest `decoder_declared` generation
metadata. `predictions_sha256` commits the whole envelope. The report also
retains original population bytes as `population_raw_utf8` and their raw hash.

The selected row's `source_sha256` and `context_sha256` remain exactly those of
the original population. Its separate `catalog_context_utf8` and
`catalog_context_sha256` bind the supplied wrapper. The adapter also exposes
`source_context_sha256` separately from `catalog_context_raw_sha256`; it never
substitutes a catalog hash for a source-context commitment.

`status="generated"` in the existing transport means IDs were supplied to its
decoder; it does not mean the sequence completed or succeeded. The full generation
status remains in the replayed trace. The existing batch owner decodes the IDs
and retains incomplete and invalid output. Actual generation exceptions yield
no adapter report. The enclosing caller must retain error, timeout, cancellation
and not-started observations under the existing declared-failure row contract,
without fabricating generated IDs.

Pass the complete original population, references and prediction observations
to `prepare_relational_catalog_batch_evaluation_v1`; its validator replays those
transports. Do not rebuild its accounting, select a favorable duplicate or omit
missing/unavailable/failed rows. This one-row adapter does not manufacture rows
for other occurrences or change the population denominator.

`encoder_sha256` stays null and `generation_comparison_qualified` stays false.
The existing evaluator treats the unverified `decoder_declared` envelope as
unverifiable generation, even after successful numerical replay. No authored
control label or encoder hash is invented to obtain comparison credit.

## Bounds, custody and limitations

Checkpoint and complete input limits are 64 MiB and 96 MiB. Context bytes are
capped at 512 KiB, each score at 4 MiB and each codec at 32 KiB. The complete
trace and every full returned report are independently capped at 8 MiB.
Validation/adaptation wrappers count toward that same whole-output limit; a
generation report that fits alone may fail when wrapped. No payload is dropped,
truncated or retried to make it fit. Overflow after completed numerical work
raises without exposing a successful partial result.

Ordinary-container item/depth limits, exact scalar types and whole serialized
sizes are checked. Original inputs, detached inputs and retained observations are
fenced around public calls and final serialization. The source guard pins this
module, the scorer's complete existing closure and the batch core/facade contract
sources. It checks physical snapshots, canonical import origins and the scorer's
own anchors. A secondary closing failure preserves the original exception and
adds a note. These are endpoint checks, not arbitrary loaded-code attestation.

An unsuccessful call cannot claim zero attempted numerical work merely because
no report returned. The enclosing admitted runner must retain actual started and
completed work, failures and resource cleanup. This module performs no automatic
retry or resource-policy mutation. Finite transport bounds do not replace owned
resource admission and pressure backoff.

All semantic, source-encoder, permission, training-history, legal-accuracy,
acceptance and proof authority stays false. Training and evaluation-gold masks
are exact integer zero; training/optimizer execution and restoration flags remain
false. Source nomination orchestration, authenticated vector production,
prepared inference optimization, architecture changes and legal/Lean admission
remain separately owned workstreams.
