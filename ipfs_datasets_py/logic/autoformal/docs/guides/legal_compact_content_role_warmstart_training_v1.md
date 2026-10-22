# CP128 role-objective warm start v1

The owner is `ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_role_warmstart_training_v1`. It forks the retained CP128 compact-content decoder into two explicit objective branches: `full537` and `scope_conditional`. Both inherit the same thirteen tensors and start with fresh Adam. The original role trainer, policy, checkpoint, prepared trainer and serving owners remain unchanged.

This profile covers the two exposed authored384 fixtures, their original vectors and contexts, the fixed537 codec and the inherited h0-only GRU. It supplies no compatibility for native GTE embeddings, other widths, other IR families, legal-text reconstruction, complete normative LegalIR, graph admission or Lean admission. Keep family, schema/version, decoder task, conditioning space and dimension inventories separate.

## API

| API | Contract |
| --- | --- |
| `create(cp128, *, expected_parent_checkpoint_sha256, expected_parent_policy_sha256, objective_kind)` | Validate the exact retained CP128 through its original owner; return a new plain checkpoint with inherited weights, empty named Adam and new progress0. No model or optimizer is constructed. |
| `policy(objective_kind)` | Return the closed new policy for `full537` or `scope_conditional`; both retain `semantic_priority` weights. |
| `policy_sha256(policy)` | Validate and canonically hash that exact new policy. |
| `checkpoint_sha256(checkpoint)` | Hash bounded ordinary checkpoint JSON. This helper does not establish checkpoint validity. |
| `inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256)` | Validate complete plain state, source bindings, parent, policy and lineage without constructing numerical state. |
| `training_row(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256)` | Return the original authored row selected by the new row cursor, including its conditioning, target IDs, original scope choices and unchanged position weights. |
| `restore(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256)` | Strictly restore all thirteen current tensors and the complete current named Adam state through the original numerical factories and state validators. |
| `objective(checkpoint, logits, *, expected_checkpoint_sha256, expected_policy_sha256)` | Return a differentiable scalar and an observation report. It performs no model forward, backward or optimizer step. |
| `pack(model, optimizer, checkpoint, progress, *, expected_checkpoint_sha256, expected_policy_sha256)` | Validate and pack exactly one additional actual named update, preserving the immutable CP128 and successor lineage. It performs no optimizer step. |

`objective` requires finite CPU float32 logits of shape `(1, 46, 537)` with gradients enabled. It rejects nonfinite coordinates before any scope masking, including coordinates excluded by the conditional objective. All46 positions are supervised, including EOS; PAD is excluded as in the original owner.

## Objective and optimizer boundaries

The unchanged semantic-priority inventory assigns weight1 to39 singleton positions, weight4.5 to six structural choices and weight1 to the predicate constructor. Both branches divide their weighted loss by67. Original role inventories and their original policy hashes remain intact inside the parent; the successor has a separate versioned objective policy and hash.

`full537` uses the original unmasked cross-entropy primitive with its gradient intact:

```text
sum_i(weight_i * CE(all537 logits_i, target_i)) / 67
```

`scope_conditional` uses the original allowed-scope normalization and supplies full537 loss only as a detached diagnostic. A singleton allowed set can have zero conditional loss and gradient; that is not an accuracy result. Differences between the two losses are not reconstruction improvement.

Both branches use the same original Adam defaults, learning rate0.001, batch size1, repeated population order and global gradient clip5. The existing finite progress validator admits at most2048 new updates; a separate admitted run must select its own smaller budget. This API does not dispatch a learning campaign.

## Checkpoint identity and resume

The successor schema is `legal-compact-role-warmstart-training-checkpoint/v1`, its policy schema is `legal-compact-role-warmstart-objective/v1`, and objective observations use `legal-compact-role-warmstart-objective-observation/v1`.

The sole admitted warm-start parent has canonical SHA256 `2c6b5201e1223c3c25adc07b11062180fbaf5f46ce3c078c5b96395f8d87225a`, policy SHA256 `578562275ac7497b52e564028f4dae560b444aca5d0e59275683f5134dfc51ed`, and weights SHA256 `d4e7c710a8aba4462aab575d9bbfb4278c1870fadaf304f80d0f341af4912c34`.

`warmstart_parent_checkpoint` retains that complete original checkpoint once. Its original basis, rows, contexts, inventories and historical Adam remain unchanged. `historical_parent_progress` records128 original updates and64 epochs; `historical_parent_optimizer_state_sha256` commits the retained moments. Those moments are never loaded as the successor optimizer. The new checkpoint starts with empty Adam and progress `{optimizer_steps: 0, epochs_completed: 0, row_cursor: 0}`.

Current `model_state`, `optimizer_state`, hashes and progress describe only the successor. `initial_checkpoint_sha256` commits its deterministic fresh-Adam start. `parent_checkpoint_sha256` commits its immediate successor parent and is distinct from `warmstart_parent_checkpoint_sha256`. For later steps, the parent hash is a lineage commitment rather than a replay of every historical update. Complete named parameter order, tensor shapes, moment inventories, moment steps, runtime and CPU RNG are validated. Compact checkpoint JSON is capped at4MiB; whole input custody retains the original24MiB limit. Oversize states are refused.

## Qualification boundary

The [closed mechanics evidence](../../../../../docs/autoformalization/evidence/legal-ir-cp128-warmstart-mechanics-20261022.json) records four physical restores and six physical test updates, including two saved-step replays. Both complete resumed checkpoints match their uninterrupted successors. The largest saved compact checkpoint measured 3228626 bytes under the unchanged4MiB cap. The maximum observed absolute analytical logit-gradient error was 7.3417638080108816e-09. Original source READ, native and storage custody are independently closed.

The finite mechanics contract contains six physical test updates: two unique new steps per objective arm and one saved-step replay per arm. Four physical restores cover the two fresh starts and two saved resumptions. Thus each final distinct lineage has two new steps; replay work must not be reported as additional learned progress. The test compares complete resumed checkpoints and the associated logits, losses, gradients and clipping observations.

This mechanics qualification is separate from a longer paired learning experiment and autonomous generation evaluation. Neither convergence, saturation nor reconstruction improvement follows from a passing gradient/resume check. The new checkpoint schema has no qualified inference consumer. Existing role serving/runtime owners intentionally reject it; do not relabel it as an old checkpoint or bypass their validators. A separately versioned consumer and qualification are required before evaluating generated successors.

Source-pinned owners, canonical loaded origins, ordinary input custody and closing runtime/RNG checks are part of every API. All authority flags remain false and training/gold masks remain0. Engineering updates on exposed fixtures do not establish statutory, source-held-out, legal-semantic or native GTE accuracy.
