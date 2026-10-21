# Scope-trained compact384 model-only inference

This opt-in consumer accepts the intact `legal-compact-scope-training-checkpoint/v1` type produced by `legal_compact_content_scope_training_v1`. It validates the complete new checkpoint before using the existing model-only numerical session. It does not relabel the checkpoint, construct an old-format wrapper, restore Adam, train, or change either arm's weights or training inventories.

Both `full537` and `scope_conditional` checkpoints use the same lexical-scope inference policy. The objective kind records how the checkpoint was trained; inference neither computes that objective nor reweights its logits by the training position weights. This makes a future matched generation comparison possible without silently changing the selection policy between arms.

## Public API

```python
inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256)

generate(checkpoint, conditioning, prefix_ids, context_raw, *,
         expected_checkpoint_sha256, expected_policy_sha256,
         expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
```

`inspect` returns `legal-scope-trained-content-inference-inspection/v1`. It calls the new training owner's public inspector once, validating the objective, recomputed original and scope inventories, model/Adam commitments, progress and lineage. No model, optimizer or numerical runtime is constructed or verified by this inspection.

`generate` returns `legal-scope-trained-content-generation/v1`. It accepts a finite plain 384-element conditioning vector, independently hashed context bytes and a nonempty vocabulary-ID prefix. `max_new_tokens` must be a plain integer from 1 through 64; `prefix_origin="bos_seed"` requires `[1]`. Prefix and context origins use the existing prepared runtime's declared-origin vocabulary. The overall token limit remains 512. A future fixed four-slot call set starting at BOS with allowance 64 has at most four model allocations and 256 forwards; this module does not schedule or admit that call set.

Complete or blocked supplied prefixes return their terminal result without allocating a numerical model. Otherwise, one private `legal_compact_content_prepared_runtime_v3._PreparedModel` restores the intact new-schema model state. Every numerical step evaluates the entire current prefix under inference mode. There is no cross-call model cache, incremental hidden-state cache, optimizer construction, Adam-state restoration or gradient computation. The numerical session checks model weights, modules, conditioning, CPU RNG and runtime through completion and failure cleanup.

## Existing owners retained

The existing weighted runtime supplies bounded immutable-input capture, canonical dependency discovery, source fences, origin/input checks and common identity fields. Its old checkpoint inspector and old generation entrypoint are **not** called. The new training owner's public `inspect` validates the actual new checkpoint instead. That owner and its direct source dependencies are included in the enclosing fence and source receipt.

The same scope filter and token/selection module objects serve preparation and inference. Public scope-prefix reports bind the offered prefix, raw context and codec, retain their original token-prefix reports, and can only remove original choices. Each selection retains all 537 finite model scores, the refined allowed set, the local original-selector decision and the selected continuation. The unchanged token owner performs final typed decoding. No target label replaces an actual model prediction.

The consumer inherits the existing 16 MiB checkpoint, 24 MiB input and 8 MiB report bounds. Returned reports are ordinary detached JSON values. Canonical source bytes and physical origins are checked before, during and after operations; these finite checks do not attest arbitrary bytecode, third-party binaries or operating-system isolation.

## Identity and observations

Inspection and generation receipts include:

- The new checkpoint schema, profile and canonical hash; weights, codec, original donor, initial/immediate parent, progress and historical Adam-state hash.
- `objective_kind`, complete `objective_policy` and its hash.
- `inventories_sha256` and its explicit alias `baseline_inventories_sha256`, plus `scope_inventories_sha256`.
- `training_scope_policy` and `training_scope_policy_sha256`, separately from the inference `scope_policy` string and `scope_owner_pins`.
- `checkpoint_validator_schema`, `checkpoint_schema_conversion_performed=False`, inspection/restore/forward counts, source pins and explicit target-access/authority limits.

Generation also retains the supplied and selected IDs, complete score/selection trace, final prefix report, typed decoding, terminal status and reason. Status is `supplied_complete`, `complete`, `blocked` or `step_budget_exhausted`. Successful function return is distinct from a completed typed formula. A local original-selector observation on a scope-filtered prefix is not an independently generated baseline trajectory.

All authority fields remain false, and `training_mask` and `evaluation_gold_mask` remain zero. The structural validator reads exposed training references to recompute inventories, but the numerical model sees only conditioning and the supplied/generated prefix. Caller-supplied conditioning and context-origin labels do not authenticate a source encoder, permitted context or user intent.

## Qualification and remaining limits

This source adds a consumer; it does not itself claim that a new generation qualification has run. A bounded caller should check pure refusal and terminal paths without allocation, then record actual model allocation and forward hooks for its fixed slots, full scores and selected prefixes, unchanged weights, zero optimizer/gradient work, original source/native closeout and all terminal outcomes. The two retained two-step checkpoints and two authored rows can check this integration, but they cannot establish converged reconstruction or held-out generalization.

Scope filtering prevents some impossible predicate branches without proving global completability or EOS within the allowance. A valid typed result does not establish faithful legal meaning, graph admission or Lean validity. The consumer qualifies neither source-to-conditioning encoding nor 768D/4096D profiles. Earlier failed generation observations remain unchanged; a later trained reconstruction comparison must be independently fixed and account for preparation, failures and all exposed targets.
