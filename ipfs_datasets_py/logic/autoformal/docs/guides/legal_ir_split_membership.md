# LegalIR split membership authorization

Use `legal_ir_eval_splits.authorize_legal_ir_split_use` or its operation-specific
wrappers before consuming a declared batch for training, hyperparameter
selection, representation promotion or TODO projection.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    require_training_split,
)

require_training_split(manifest, items=[{"sample_id": original_sample_id}])
```

Every supplied item must resolve at least one manifest member. Resolution uses
explicit `sample_ids` and `sample_id`/`id` first, then citation matching when IDs
are absent, then source-span matching if neither IDs nor citation resolve.
All resolved members must be permitted for the operation. A composite item
cannot hide a protected or unknown member behind an allowed member. An explicit
unknown ID remains an error even when a citation could match an allowed row.

An item with no resolvable member now raises `LegalIRSplitPolicyError` instead
of passing through an empty membership loop. Its `disallowed` diagnostics
contain `reason="sample_not_resolved_in_split_manifest"` and the zero-based
`item_index`. All unresolved items in a mixed batch are retained in the error.
Existing unknown-ID and protected-split diagnostics retain their formats.
Manifest leakage checks still run before operation-specific authorization.

The default `items=()` remains manifest-only validation for existing callers.
A fitting or retrieval wrapper must require its actual consumed population and
authorize that complete population before producing side effects. Checking a
manifest alone does not authorize an unspecified input batch.

The existing operation policy is unchanged:

| Operation | Allowed splits |
| --- | --- |
| Training | `train` |
| Hyperparameter selection | `validation` |
| Representation promotion | `canary` |
| TODO projection | `train`, `validation` |

Membership identifies declared split assignments. Bind the actual consumed
source and target bytes to those identities through compatible record/index
and target-snapshot contracts. This guard does not authenticate arbitrary
payloads carrying an allowed ID, qualify legal meanings, establish unseen
semantic dependencies or automatically wrap decoder trainers.

Reuse `SourcePartitions.authorize` for explicit source selections before
materialization and `CorpusIndex.authorize`/`verify_batch` for indexed records.
The combined target expressibility, review, exposure, dependency and consumer
boundary manifest remains a separate integration step. Unknown or unreviewed
labels retain their masks and coverage dispositions.

The enclosing workspace's `artifacts/legal-ir-split-membership-20261016-01/`
records the focused qualification. Its authored manifests exercise missing
membership, valid fallbacks and composites, protected members and preserved
manifest-only validation. No training labels or statutory decisions are created.
