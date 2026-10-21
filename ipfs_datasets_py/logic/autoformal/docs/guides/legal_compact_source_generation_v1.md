# Source nomination to bounded compact generation

`logic/formalization/autoencoder/legal_compact_source_generation_v1.py` connects
the existing lexical source-context producer to the existing numerical compact
generator. It freezes the complete selected context inventory before any
numerical dispatch. No training, new grammar, encoder, database or supervisor is
introduced. Existing head/generation v1 remain unchanged.

## API and input custody

```python
prepare_source_generation_v1(
    population_raw, rows, checkpoint,
    expected_population_sha256=population_sha,
    expected_checkpoint_sha256=checkpoint_sha,
    max_new_tokens=3,
)
```

The population is independently hashed original UTF8 JSON in the existing
`legal-relational-batch-population/v1` schema: `schema`, `partition`,
`selection_sha256`, and ordered `rows` containing `id`, `source_sha256`,
`context_sha256`. This profile permits 1–16 unique selected occurrence IDs.
For this caller, the population's original `context_sha256` commits the exact
**catalog bytes**, while the generated compact context has its own separate
`content_context_sha256`. The caller never rewrites the original population.

Each input row is a closed dictionary with exactly these fields:

- `id`: matching the corresponding population occurrence in original order;
- `source_raw`, `catalog_raw`: immutable exact UTF8 bytes;
- `conditioning`: a plain finite 384-value list, each magnitude at most `1e8`;
- `expected_source_sha256`, `expected_catalog_sha256`: independent raw byte
  commitments, also equal to the population's source/catalog commitments;
- `expected_conditioning_sha256`: canonical sorted-key compact UTF8 JSON hash
  of the conditioning list, with nonfinite values forbidden.

The complete input order and population are checked. Missing, extra, duplicate
or reordered occurrences refuse the whole operation. Unknown row fields,
targets, labels and references are not accepted. Source bytes are bounded at
64 KiB, catalogs at 512 KiB, the original population at 128 KiB, checkpoint at
16 MiB and the complete captured input at 64 MiB. Every conditioning vector and
input identity is checked before numerical work, including skipped rows.
Checkpoint hash checking is structural before nomination; skipped rows never
cause numerical head restoration. A successful all-abstention call makes no
claim that the supplied checkpoint was restored or qualified.

`source_generation_sha256(report)` supplies a bounded canonical JSON report
identity. It does not replay generation or authenticate any semantic claim.
This increment adds no implicit numerical replay validator.

## Whole-population preparation before generation

The source-context owner's public preparation and original-input validation run
for every occurrence before the first generator call. Their complete reports,
independent report hashes and the full context inventory are frozen together.
Source/context bindings are checked after every downstream operation; changing
an original input or frozen disposition refuses the whole operation.

An ambiguous alias result produces an `unsupported` context-inventory row; no
match produces `unavailable`. Both produce a retained `abstained` prediction and
slot, with reason `source_context_ambiguous` or `source_context_unavailable`.
Neither calls the numerical head. A nominated row supplies its validated
compact context with origin `caller_supplied_unverified`.

This establishes ordering within this call, not authenticated catalog creation
time, absence of earlier target exposure, context permission or legal meaning.
All selected predicates must still occur in a valid decoded output under the
inherited grammar. Lexical selection is not an optimality/completability check.

## Numerical work and replay accounting

Each nominated row calls the existing generator with exactly `[1]` (BOS),
`prefix_origin='bos_seed'` and
`context_origin='caller_supplied_unverified'`. `max_new_tokens` must be a plain
integer from 1 through 8. This small integration cap is deliberately stricter
than the generator's 512-total-ID ceiling. A short forced grammar prefix is not
evidence of completed formalization or predictive legal quality.

The caller then invokes the existing generation-to-batch adapter once. That
adapter validates the original generation by performing one complete numerical
replay. The caller does not separately call the numerical replay validator.
Each slot and the aggregate `counts` record:

- `original_numerical_forward_count` from the original generator report;
- `adapter_replay_numerical_forward_count`, equal to that count after the fixed
  adapter successfully verifies identical complete replay;
- `total_numerical_forward_count`, their sum.

For a three-step nominated row, this is three original forwards and three
validation-replay forwards: six actual forwards and one predicted occurrence.
The replay is not a new independent sample. Complete original generation
reports and adapter wrappers remain in each generated slot. The generator's
actual terminal status, reason, selected IDs and raw argmax observations remain
unchanged, including `step_budget_exhausted` outcomes. `slots[*].status` means
`generated` or `abstained`; it does not replace the retained generator status.

Operational errors propagate. No malformed input, owner drift, interruption or
bound failure is relabeled as a successful partial population or fabricated
model outcome. Callers must retain their failure evidence and resource custody.
This module neither obtains nor releases CPU/process/storage reservations.

## Outputs and existing evaluation

The report schema is `legal-compact-source-generation/v1`; its profile is
`full-selected-source-nomination-bos-generation-384/v1`.
`complete_selected_source_generation` means processing of every selected slot
completed, including abstentions; it does not mean all formulas completed.

The report retains the unchanged population, whole source reports, context
inventory, original per-row generation and replay wrappers, full predictions,
status slots, numerical counts, source pins and canonical commitments. The
`pre_generation_sha256` commits an object containing `population_sha256`,
`source_reports_sha256` and `context_inventory_sha256`.

`settings_sha256` identifies this caller's settings and caps.
`generation_settings_sha256` separately identifies the exact existing
generator settings (`max_new_tokens`, `max_total_ids`, `prefix_origin`,
`context_origin`). The latter is retained unchanged in the combined prediction
generation declaration and every actual existing adapter result.

`predictions` uses the existing
`legal-relational-content-token-batch-predictions/v1` contract.
`context_inventory` uses
`legal-relational-content-context-inventory/v1` and retains every population row.
The tighter existing transport limits apply: 4 MiB for context inventory,
16 MiB for predictions and 64 MiB for the complete report. Overflow refuses;
no rows, contexts, scores or steps are silently truncated.

Reference-dependent evaluation stays outside this API. An evaluation caller can
serialize these returned transports and call the unchanged
`prepare_relational_content_context_evaluation_v1` with its original population
and separate reference transport. Its original CONTENT batch evaluation remains
the authority for population denominators and structural comparisons. The new
bridge does not add a competing evaluator or filter failed rows.

`encoder_sha256` remains null because conditioning has no authenticated source
encoder. The existing evaluator consequently retains `unverifiable_generation`
and awards no source-generation comparison credit. Hashing a caller vector or
successfully preparing source context does not justify inventing an encoder
identity. No compatibility is claimed for 768D or native4096 inputs.

`model_executed` is a local execution fact derived from successful original plus
replay forwards. `training_executed` and `compact_optimizer_executed` are false.
All semantic/training/permission authority fields remain false; both
`training_mask` and `evaluation_gold_mask` remain integer zero. The existing
head still has zero compact-content optimizer steps. No legal, source-held-out,
checkpoint-training or Lean qualification follows from this integration.
