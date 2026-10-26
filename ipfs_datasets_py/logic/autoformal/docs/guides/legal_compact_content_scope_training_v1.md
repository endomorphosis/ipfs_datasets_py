# Scope-denominator compact384 training state

This opt-in owner introduces `legal-compact-scope-training-checkpoint/v1` for a bounded comparison of `full537` and `scope_conditional` objectives. Both start from the exact retained `a98a6244…` donor and its two authored rows, preserve the original model weights and configuration, and start fresh Adam history. It does not consume the later step-128 checkpoints as initialization. Old checkpoint files and old consumers remain unchanged; the new schema must not be relabeled as an old weighted checkpoint.

The scope is pure creation, inspection and row preparation, plus actual restoration, a differentiable objective and packing one completed update. There is no training loop, prepared session, inference consumer, model download, resource admission, backward call or optimizer step in this module. The caller owns those actions and their finite accounting. A six-update development qualification is a separate caller task; this guide does not claim it has run.

## API and identity

`create(donor, population_raw, rows, *, expected_donor_sha256, expected_population_sha256, choice_weight=4, objective_kind="full537")` returns a flat new-schema checkpoint. Only choice weight 4 is supported; `objective_kind` is exactly `full537` or `scope_conditional`. `policy(choice_weight=4, *, objective_kind="full537")`, `policy_sha256(policy)` and `checkpoint_sha256(checkpoint)` provide distinct objective and checkpoint identities. The latter computes canonical identity without validating or restoring the checkpoint.

`inspect`, `training_row`, `restore`, `objective` and `pack` retain the existing weighted owner's call signatures and independently supplied checkpoint/policy hashes. `restore` returns `(model, optimizer)`; `objective(checkpoint, logits, *, expected_checkpoint_sha256, expected_policy_sha256)` returns `(loss, observation)`; `pack` accepts progress advancing exactly one actual Adam update. Each step commits to its immediate parent, while the initial checkpoint hash is recomputed from this owner's deterministic fresh state. A later parent hash is a commitment, not a replay of historical training.

The implementation reuses the pinned weighted owner's source/input context, donor and population validation, original decision inventories, row weighting, numerical loading, actual named model/Adam validation and state helpers. Its own flat validator is necessary because its schema, policies, scope inventories and initial-parent commitments differ. It never converts the new checkpoint to an old schema, calls an old checkpoint validator on a fabricated value, or monkeypatches an owner. Its source and scope-filter checks are composed with the original public-operation fence; numerical boundaries additionally preserve CPU RNG, runtime and offered logits.

## Two separate inventory meanings

`inventories` and `inventories_sha256` preserve the original complete target annotations and baseline allowed sets. Position weights are always derived from their original `decision_kind`: forced = 1 and choice = 4. Both rows contain 46 supervised positions, with a common weight sum of 67. This classification is not recomputed from the refined mask.

`scope_inventories` and its hash are additional commitments. For every complete teacher-forced target prefix, the public scope filter recomputes the allowed set, verifies the target remains admitted, and binds the original baseline prefix report, source/context/target/codec hashes, prefix IDs and filter policy. Each position retains both original and refined allowed sets, original decision kind and weight, removed IDs and the scope report hash. The two fixed rows each have 39 singleton allowed sets and 7 nontrivial ones. The validator recomputes both inventories and rejects caller-edited masks even if their enclosing hashes have been updated.

`training_row` returns the original conditioning, target IDs and `position_weights`, plus `baseline_inventory_sha256`, `scope_inventory_sha256`, `scope_allowed_token_ids`, `baseline_decision_kinds`, `objective_kind` and singleton/nontrivial counts. The checkpoint records `scope_policy` separately from `objective_policy`. Matching vocabulary coordinates do not mean that the old and new denominator policies are interchangeable.

## Numerical objective

The full objective uses the unchanged weighted kernel: per-position full537 cross entropy, multiplied by the original 1:4 weights, summed and divided by their sum of 67. The conditional objective changes only the softmax denominator: it masks coordinates outside the scope-allowed set with negative infinity before the same per-position cross entropy and reduction. All original 537 logits must first be finite CPU float32 tensors with the complete `[1, 46, 537]` teacher-forced geometry and gradients enabled.

Masking excludes forbidden coordinates from the differentiable loss. Singleton positions have exactly zero conditional loss and zero logit gradient, irrespective of model quality. Seven positions provide nontrivial conditional training signal in each row; the normalizer stays 67 rather than being renormalized over those seven positions. This is a deliberate matched-weight comparison, not an assertion that singleton tokens have been learned.

Observations retain `per_position_losses`, `weighted_loss`, `full537_per_position_losses`, `full537_weighted_loss`, all allowed sets, original weights and both inventory commitments. Full537 diagnostics in the conditional arm are computed without gradient tracking and do not enter its returned loss. Lower conditional losses cannot be compared directly with full537 losses as evidence of better reconstruction. The caller must measure BOS completion, exact reconstruction, scope/binder and modal behavior separately.

## Qualification limits

The two rows are fictional exposed training fixtures with authored 384-element conditioning. Source text is retained for provenance and checks, but only conditioning and target prefixes enter the caller's numerical model. The checkpoint grants no source-semantic, statutory, graph, Lean, training-gold, held-out or native authority. This module does not qualify the 768D or 4096D deployments.

Before any numerical use, the original source and native resource owners must admit a fixed caller. Useful qualification checks include pure malformed policy/mask/target refusals, exact donor-weight and fresh-Adam restoration, actual full537 logits and analytic logit gradients from the same backward pass, zero forbidden-coordinate gradients, one-step parent/moment identities and exact saved-checkpoint resume. Successful finite qualification would not establish a general training improvement or a new generation result. A prepared trainer and inference consumer for this schema remain separate, unimplemented integration work.
