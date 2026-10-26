# Receipt-bound catalog generation v1

This additive integration takes a complete selected source population, original
native embedding receipts, source catalogs and an existing trained checkpoint.
It freezes receipt custody and source nominations before generating catalog
syntax from BOS. Every selected occurrence retains its own slot. The existing
CONTENT receipt caller and the separate prepared-runtime work remain unchanged.

The module is `ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_receipt_bound_catalog_generation_v1`.

```python
report = prepare_receipt_bound_catalog_generation_v1(
    population_raw, rows, checkpoint,
    expected_population_sha256=population_sha256,
    expected_checkpoint_sha256=checkpoint_sha256,
    max_new_tokens=2,
    source_resolver=source_resolver,
)
report_sha = receipt_bound_catalog_generation_sha256(report)
validation = validate_receipt_bound_catalog_generation_v1(
    report, population_raw, rows, checkpoint,
    expected_report_sha256=report_sha,
    expected_population_sha256=population_sha256,
    expected_checkpoint_sha256=checkpoint_sha256,
    max_new_tokens=2,
    source_resolver=source_resolver,
)
assert validation["generation_report"] == report
```

Inputs use the unchanged receipt-bound source caller's closed row schema:
`id`, `source_raw`, `catalog_raw`, `expected_source_sha256`,
`expected_catalog_sha256`, `source_request`, `expected_source_request_sha256`,
`input_id`, and `receipt_ref`. Source-request text must equal the original UTF-8
source bytes and retain the exact receipt input's physical source coordinates.
The caller accepts no free vector, supplied prefix, target, context override,
or decoder report. Independent hashes must come from the caller's retained
originals. This API neither acquires resources nor starts a supervisor: call it
inside the existing admitted validation or application owner.

## Preparation and preserved occurrences

The new `legal_compact_receipt_source_inventory_v1` helper extracts only the
legacy pure preparation loop. It reuses the unchanged legacy population/row
validators, checkpoint inspector and operation custody. It is an internal seam,
not a portable prepared model or generic callback controller. The legacy module
is pinned at `d91475f89dcba669ebc2a778f1dbc18f7eacbc955661f82f0a288de2bb3750f1`.
Its own CONTENT path is not invoked by this integration. A retained-report
regression compares the extracted pure inventory to the original CONTENT
result without re-executing its model.

Preparation loads unique original receipts through their public loader, keeps
all producer inputs and status commitments including inputs outside the
selected window, and preserves exact native float32 vector bits. It prepares
and publicly replays every source nomination, including rows with unavailable
conditioning. Equal text at distinct physical positions remains distinct.

The nested `source_inventory` retains the legacy embedded-only map. The new
`eligible_mapping` separately requires both an embedded vector and a nominated
context. `missing_input` and `token_limit_exceeded` retain null vectors;
ambiguous and unmatched contexts retain their own dispositions. No eligible
rows means pure inspection and zero model restores or forwards.

Each nominated catalog wrapper contains the complete nominated subset in
original catalog order. Signature and argument-role component bytes and hashes
are retained alongside the wrapper. The original source-catalog commitment is
separate from the nominated-context and inference-wrapper commitments. Aliases,
matching offsets, index maps and exclusions remain in the source reports.
Generation may select a subset of this catalog, but cannot shrink or replace
the catalog after observing output tokens. Complete candidate selections, when
present, retain the existing decoder's selected and unused symbol maps.

## Inference, replay and accounting

The existing public catalog continuation is the only numerical boundary.
Original inference starts with `[1]` and `prefix_origin="bos_seed"`; context
origin remains `caller_supplied_unverified`. Each eligible trajectory is adapted
through the existing batch adapter, which independently replays the complete
trajectory against the same whole original population. All aggregate inputs,
preparation records, earlier trajectories and adapters remain fenced through
final serialization.

For an eligible trajectory emitting N tokens, preparation records N original
and N mandatory adapter replay forwards. Public outer validation repeats this
whole preparation and returns a separate validation receipt. Its
`original_forward_count` is zero and its `replay_forward_count` and
`numerical_forward_count` both describe the same 2N calls. Its
`original_generation_forward_count` and the nested regenerated report describe
historical categories; do not add them again. Hashing a report executes no model.

Batch predictions retain all selected rows. Eligible incomplete trajectories
still have declared `generated` observations, with actual completion status in
the nested generation. Ineligible rows declare `abstained` with precise reasons.
The unchanged evaluator may assign `unverifiable_generation` before those
terminal categories because encoder authentication remains absent. Raw declared
statuses are retained. Reference rows are explicitly unavailable; no gold is
invented, and no comparison credit is granted.

## Bounds and failure handling

The profile retains 1–16 ordered unique selected rows, 1–12 newly emitted tokens
and at most 512 total IDs. It preserves the original 128 KiB population, 65,536
source bytes per row, 524,288 catalog bytes per row, 64 MiB checkpoint,
64 MiB unique receipt total and 192 MiB aggregate input bounds. The outer report
is bounded to 96 MiB, and individual nested continuation/adapter/evaluation
reports to 8 MiB. Actual complete serialized sizes are checked; no partial
report, truncation, retry or row removal is returned to satisfy a bound.

At the maximum eligible population and token allowance one preparation can
perform at most 384 forwards including replay. This is an API ceiling, not a
resource reservation. The enclosing existing owner must admit memory, CPU,
processes, storage and timeout and respond to external pressure. A failure,
cancellation or serialization overflow can follow numerical work. Preserve the
attempt and observed cost; no report does not mean zero work. The validator's
96 MiB envelope includes its nested report and can itself overflow after replay.

## Qualification and limits

The bounded qualification enrolls four genuine retained producer occurrences:
one nominated embedded statutory span, ambiguous and unmatched embedded rows
with equal text at different positions, and one genuine over-limit null vector.
A three-row all-ineligible selection retains all four producer inputs, proving
that the outside-window occurrence stays in the receipt inventory. No retained
native `missing_input` result exists; any serialized missing-input control must
remain explicitly counterfactual. Two emitted BOS tokens for the sole eligible
row, mandatory adaptation and outer validation permit eight actual GRU calls.
The test fixture records the actual result rather than assuming completion.

Receipt consistency is not independent encoder or runtime authentication.
Matching 384 dimensions does not establish compatibility between native GTE
vectors and the checkpoint's training conditioning. Source semantics, catalog
permissions, held-out status, legal accuracy, graph acceptance and Lean admission
remain unverified. All authority flags stay false and training/evaluation masks
are integer zero. This increment performs no encoder execution, optimization,
training, provider generation, GPU work, toolchain installation or publication.

The next substantive legal-data step is a reviewed statutory span/meaning-unit
crosswalk into entities, definitions and governing uses, with explicit losses
and provenance. Integration and bounded syntax execution do not establish that
legal interpretation. Larger prepared-runtime generation and matched training
experiments have separate owners and evidence cohorts.
