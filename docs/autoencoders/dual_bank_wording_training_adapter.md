# Retain both wording banks through a private trainer adapter

The [balanced continuation](balanced_wording_continuation_20261007.md) found that
replacing the retained auxiliary bank lost previously correct modalities. The
parent already generated the new bank exactly. The new
`dual_bank_training_adapter` supplies the missing two-bank interface for a
controlled retention experiment, using the existing native384 embeddings and
selected parent weights. It does not itself acquire resources or run a fit.

The adapter lives alongside the original
[schedule and retention helper](../../scripts/ops/autoencoder/dual_bank_wording_replay/dual_bank_retention.py).
Its source and tests are additive; the original helpers and trainer remain
unchanged. The 8D teacher, 768D path, span decoder and prose tasks retain their
own models and measurements.

```python
from scripts.ops.autoencoder.dual_bank_wording_replay import dual_bank_training_adapter as dual

# Each helper is the separately configured authentic renderer/exclusion profile.
helper = dual.configure(
    helpers_by_role={"control": retained_helper, "balanced": balanced_helper},
    pairing=authenticated_pairing,
    original_rules=original90_rules,
)
inventory = dual.build_source_inventory(
    {"control": retained_source_inventory, "balanced": balanced_source_inventory},
    authenticated_pairing,
)
private_trainer = dual.configure_trainer(original_trainer, helper)
result = private_trainer.train(
    # Supply the original model, rows, references, contexts and training options.
    **original_training_arguments,
    paraphrase_modality_auxiliary={"source_inventory": inventory, "weight": 0.05},
)
```

The caller must authenticate its files and loaded numerical sources, restore the
exact retained checkpoint, establish resource admission and keep original
training/selection streams. The adapter's preparation validates each complete
source envelope through its own existing helper. Retained control13 and new
balanced16 exclusion inventories remain distinct. Prepared bank handles are
bound to the specific configuration and expose metadata without manufacturing a
combined 360-row bank.

## Cache and loss dispatch

Each bank prepares its own original immutable TensorCache. An adopted handle
shares the exact model, data, clause vectors, masks, targets, frozen buffers and
version witnesses. Only paired sampling orders and corresponding metadata are
rebound. The original cache and its full receipt remain unchanged and are
retained in the adopted receipt. The two caches are never concatenated.

At global update `t`, the selected bank receives its own local ordinal
`floor(t/2)`. The unchanged loss owner computes one mean six-clause cross entropy
against all 32 output values. Its authentic receipt retains its original schema
and local committed-step field inside a new dual-bank receipt. Retry calls at
the same global step reuse the same sources; forwards do not advance sampling or
prove an optimizer commit. Zero-weight graphs stay detached, and the positive
weight uses the original gradient path and clipping.

The 170-update schedule provides 85 updates and 510 clause presentations per
bank. Every one of the 180 sources in each bank appears two or three times; each
actual template receives 255 presentations, with 340 per modality overall.
Using the global ordinal directly within each bank would omit half the members
of its strata.

The private trainer import hook targets only its existing relative auxiliary
import. Other imports and omitted/None auxiliary paths retain their original
behavior. Returned training reports are reconciled from the inherited actual
`committed_updates`, which are appended after `optimizer.step`. Per-bank counts,
source exposures and template totals derive from those records. The obsolete
single-bank template summary is retained as explicitly inapplicable metadata;
its public counter is corrected. Truncated schedules remain incomplete. A genuine
zero-cache preparation timeout preserves the original partial report with zero
commits and `cache_prepared=False`.

Reconciliation checks schedule/bank/row/source/token/stratum bindings, local and
global ordinals, exact loss schemas, weight/gradient agreement and unqualified
flags. Ownership, cache mutation and contradictory selection/authority metadata
refuse. These are consistency checks, not cryptographic execution attestation.

## Completed verification and remaining fit

All 82 new controls and 54 existing schedule/owner controls pass, with no failures
or skips. Numeric tests use explicitly synthetic embeddings and a tiny model;
they run real CPU cache/loss operations without optimizer steps. Independent
review approved the final private dispatch, cache ownership, report bindings and
partial-result handling.

A separate probe rebuilt the complete schedule from the actual retained control
and balanced envelopes without importing Torch during preparation. It then
restored the original selected 384D auxiliary state, tensor SHA
`0b3c7c3b1a5581cd393d9bb8db1d24b87fe2cb9dff0be268aa2b5ed1f88b6594`,
and executed 170 detached source-head forwards using the same retained native
vectors. Each bank contributed 510 observations across all 180 sources. All 1,020
modality argmaxes were correct. Sampled mean source-modality CE was 0.02115916 for
retained wording and 0.01146664 for balanced wording; these repeated schedule
observations are not unique-source averages or teacher-forced formula-token CE.
Model state and RNG stayed unchanged; no encoder or optimizer ran. This probe
measures dispatch on an already trained parent, not a new reconstruction gain.

The next experiment still needs its reviewed launch/phase manifest, resource
reservation, matched control, exact checkpoint/recipe bindings and actual
training/evaluation. Use the existing `retention_gate` after unchanged selection
to check every original/retained/new TRAIN paragraph, all seven facets,
cardinality, omissions/extras/order/EOS and both complete source-bank readouts.
Keep exposed v3 and sealed labels posthoc. A rejected bank replacement stays
rejected; this adapter does not promote a checkpoint or admit a runtime.

No new checkpoint was created, registered or uploaded by these controls/probes.
Existing ModelManager and public Hub assets remain the parent. Any fitted
continuation needs its own task/schema/recipe/run checkpoint metadata and cannot
silently enter the original normative runtime. Natural-law semantic review,
nonempty qualifier support, exact prose reconstruction, fresh semantic holdouts,
native logic-family validation and proof admission remain separate work.
