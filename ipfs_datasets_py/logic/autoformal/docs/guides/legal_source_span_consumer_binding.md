# Source-span consumer input binding

`legal_span_consumer_binding` provides an explicit, local boundary for the
zero-latent `source_span_formula_v1` supervised input profile. Prepare a complete
ordered batch against independently supplied canonical SHA256 pins, then invoke
its consumer through `consume_source_span_binding`. The adapter checks the
original inputs again before calling the consumer with detached rows.

The input populations are:

| Input | Required contract |
| --- | --- |
| Rows | A nonempty ordered list of closed `{id, source_text, canonical_ir}` dictionaries, with unique IDs and distinct source texts. |
| Split manifest | The complete `LegalIRSplitManifest.to_dict()` representation, including its digest and guard. Assignments and examples cover the same IDs; the canonical partition and protection policy are retained. |
| Eligibility records | One ordered record per row, binding its ID, exact UTF8 source hash and canonical target hash, declared target origin, status, allowed operations and reason. |
| Exposure records | One ordered record per row, binding the same ID and hashes, a declared target-exposure disposition and a provenance reference. |

All four populations have separate expected canonical hashes. Use
`CheckpointContentGuard(value).sha256` to create a pin when sealing an input
manifest, and obtain that expected pin independently when consuming it. These
hashes use sorted compact ASCII JSON with finite numbers. They are distinct
from hashes of arbitrary JSON file bytes. Source hashes cover exact UTF8 text;
target hashes cover the canonical JSON value.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_consumer_binding import (
    prepare_source_span_consumer_binding,
    consume_source_span_binding,
)

binding = prepare_source_span_consumer_binding(
    rows,
    expected_rows_sha256=pins["rows"],
    split_manifest=manifest,
    expected_split_manifest_sha256=pins["split_manifest"],
    eligibility_records=eligibility,
    expected_eligibility_sha256=pins["eligibility"],
    exposure_records=exposure,
    expected_exposure_sha256=pins["exposure"],
    operation="training",
)
receipt = binding.receipt()
result = consume_source_span_binding(
    binding, rows,
    split_manifest=manifest,
    eligibility_records=eligibility,
    exposure_records=exposure,
    consumer=consume_authorized_training_rows,
)
```

The consumer is a caller-supplied function taking one detached ordered row list.
It runs only after integrity, expressibility and policy checks pass for the
whole batch. Existing decoder trainers do not acquire this behavior unless
their caller uses this boundary. The adapter performs no training, checkpoint
restoration or model execution itself.

The [bound training entry points](legal_source_span_bound_training.md) connect
this contract to the existing checkpoint builder and trainer. They validate both
batches and their shared split manifest, then check resume digests and counts
before restoring numerical state. Direct trainer calls remain separate.

Eligibility records have exactly these fields:
`id`, `source_text_sha256`, `canonical_ir_sha256`, `target_origin`, `status`,
`allowed_operations`, and `reason`. Origins are `authored_engineering_fixture`
or `model_generated_weak`. Status is `eligible`, `ineligible`, or `unknown`.
Allowed operations are a duplicate-free list drawn from `training` and
`hparam_selection`. A nonempty reason records the declaration's basis.

Exposure records have exactly these fields:
`id`, `source_text_sha256`, `canonical_ir_sha256`, `target_exposure`, and
`provenance_ref`. Training requires `declared_supervised_training`;
hyperparameter selection requires `declared_validation_scoring`. `unknown`
blocks consumption. These are caller declarations with provenance references;
the adapter does not authenticate a reviewer or reconstruct exposure history.

The existing split owner authorizes every explicit row ID. The row's normalized
content hash must also match the actual manifest example. Exact source and
target hashes remain separate commitments, so an allowed ID cannot substitute
different text or a different target after preparation. Complete manifest
roundtrip checks reject omitted defaults, discarded fields and inconsistent
digests or guards. Row order, complete sidecar populations and all pinned values
are checked again at consumption.

Representability comes from the existing span owner's audit and record
validator: one canonical rule, exact source-copy atoms, one atom per qualifier,
nonoverlapping token-aligned spans and the existing source limits. Unsupported
or declared ineligible members retain their IDs and reasons in the preparation
receipt and block the whole batch. The adapter never selects a supported subset
implicitly. Structural input errors and changed commitments raise an error.

Receipts grant no semantic, training-gold or evaluation-gold authority. A
validation batch under this profile is an engineering or disclosed weak-label
comparison. Passing targets to a supervised consumer does not establish blind
inference or process isolation. Reviewed statutory targets, field masks,
definition dependency closure, retrieval exposure enforcement, source-only
prediction exports and 384-dimensional latent batches require separate
compatible integration.

The enclosing workspace's
`artifacts/legal-source-span-consumer-binding-20261016-01/` records the bounded
fictional-fixture qualification and source capture. It creates no statutory
review decisions or new model results.
