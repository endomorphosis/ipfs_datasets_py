# Autoencoder/Codex Guidance Roadmap TODOs

- Queue run id: `autoencoder-codex-guidance-roadmap-20260523`
- Queue path: `workspace/todo-queues/autoencoder-codex-guidance-roadmap-20260523.jsonl`
- TODO count: `7`
- Intended daemon role: `codex` / `program_synthesis`
- Bundle key: `autoencoder-critic-codex-loop-v1`

## Run Hint

```bash
.venv-cuda/bin/python -m ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner --loop-role codex --run-id autoencoder-codex-guidance-roadmap-20260523-codex --queue-run-id autoencoder-codex-guidance-roadmap-20260523 --duration-seconds 3600 --max-items 7 --codex-bundle-mode semantic --codex-apply-mode apply_to_main --codex-commit-mode none
```

## Validation Commands

- `.venv-cuda/bin/python -m pytest -q tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py`
- `.venv-cuda/bin/python -m pytest -q tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py tests/unit_tests/logic/modal/test_modal_codec.py`

## Feature Requests

### 1. `repair_autoencoder_backlog_compaction`

- TODO id: `autoencoder-roadmap-001-clear-stale-backlog`
- Target: `logic.optimizer.backlog`
- Scope: `loss`
- Objective: Add a safe backlog-maintenance path that compacts duplicate autoencoder_sgd TODOs, retires obsolete failed_validation SGD noise, preserves completed program-synthesis evidence, and reports before/after queue counts without destroying historical artifacts.
- Acceptance criteria:
  - A command or supervisor method can compact a queue file into representative autoencoder_sgd TODOs.
  - Historical program_synthesis completed/failed evidence remains inspectable.
  - Queue summary reports retired, compacted, preserved, pending, and failed_validation counts.
- Evidence:
  - Previous dry-run collapsed 1118 autoencoder_sgd backlog entries into 12 representatives.
  - Most pending items were improve_encoder_decoder_reconstruction single-sample duplicates.

### 2. `separate_autoencoder_sgd_from_codex_todos`

- TODO id: `autoencoder-roadmap-002-separate-sgd-and-codex`
- Target: `logic.optimizer.supervisor`
- Scope: `loss`
- Objective: Make autoencoder_sgd TODOs explicitly transient optimizer work while program_synthesis TODOs remain durable Codex work orders; ensure supervisor summaries, queue claiming, and status counters expose both lanes separately.
- Acceptance criteria:
  - Autoencoder SGD TODOs are generated, applied, validated, completed or discarded without becoming Codex packets.
  - Codex TODOs are only emitted for persistent residual clusters after SGD/local deterministic attempts.
  - Summary fields show autoencoder_sgd pending/failed/completed separately from program_synthesis.
- Evidence:
  - The daemon currently has both optimizer_role values but historical queue noise made them easy to confuse.
  - Codex workers should not claim internal SGD nudges.

### 3. `add_autoencoder_residual_repair_router`

- TODO id: `autoencoder-roadmap-003-residual-repair-router`
- Target: `logic.optimizer.residual_router`
- Scope: `loss`
- Objective: Implement a deterministic residual-to-repair router that maps cross entropy, cosine/reconstruction, LegalIR view loss, prover failure, graph projection loss, and deontic slot loss into concrete target components and program_synthesis scopes.
- Acceptance criteria:
  - cross_entropy_loss routes to modal registry/parser cue repairs.
  - cosine_loss and reconstruction_loss route to IR decompiler/frame slot repairs.
  - legal_ir_view_cross_entropy_loss routes to bridge/view coverage repairs.
  - prover, graph, and deontic losses route to external_provers, knowledge_graphs, and deontic scopes respectively.
- Evidence:
  - The current loss generator has direct mappings, but residual introspection needs a stable router for Codex TODO quality.
  - CEC, TDFOL, ZKP, deontic, frame, and KG pathways should appear when their residuals persist.

### 4. `emit_codex_todos_from_stable_residual_clusters`

- TODO id: `autoencoder-roadmap-004-stable-residual-clusters`
- Target: `logic.optimizer.residual_clusterer`
- Scope: `loss`
- Objective: Create a residual clusterer that emits Codex TODOs only when the same residual signature appears across multiple samples or repeated cycles after local SGD, with compact evidence, sample ids, citations, metrics, and target validation commands.
- Acceptance criteria:
  - Clusters include support_count, residual signatures, top family/embedding features, target component, and semantic_bundle_key.
  - One-off sample memorization attempts stay in autoencoder_sgd and do not become Codex work.
  - Completed Codex work suppresses near-duplicate future cluster TODOs.
- Evidence:
  - Previous runs produced hundreds of near-duplicate TODOs; stable clustering should reduce duplicate Codex calls.
  - Existing introspection already exposes top residual and feature contribution evidence.

### 5. `improve_codex_semantic_ast_bundling`

- TODO id: `autoencoder-roadmap-005-semantic-ast-bundling`
- Target: `logic.optimizer.codex_bundler`
- Scope: `loss`
- Objective: Use embeddings/vector indexing plus program_synthesis_scope/target file lanes to bundle related Codex TODOs while preventing merge conflicts across AST scopes.
- Acceptance criteria:
  - Related TODOs in the same AST scope and target component are bundled up to max_items.
  - Different write lanes run in parallel without target-file conflicts.
  - Bundle reports explain anchor TODO, semantic similarity, vector similarity, fill reason, and scope lock.
- Evidence:
  - The daemon already has vector_bundle and semantic_bundle paths; this should make them first-class for residual cluster TODOs.
  - Low parallelism should still stay productive by bundling larger semantically related work packets.

### 6. `enforce_validation_delta_acceptance_for_codex_patches`

- TODO id: `autoencoder-roadmap-006-validation-delta-acceptance`
- Target: `logic.optimizer.validation_gate`
- Scope: `loss`
- Objective: Make Codex patch finalization require either targeted metric improvement on the claimed cluster or a deterministic validation fix with no holdout regression; record metric deltas in queue metadata and summaries.
- Acceptance criteria:
  - Patch metadata records baseline and post-apply targeted metrics for claimed TODOs.
  - Patches that only move code without improving the targeted failure are requeued or failed_validation with a clear reason.
  - Validation commands are selected from TODO target component and residual loss type.
- Evidence:
  - Previous failed patches often regressed tests or made syntax changes without targeted metric improvement.
  - Acceptance should be tied to the residual cluster the TODO represents.

### 7. `upgrade_autoencoder_trainable_feature_model`

- TODO id: `autoencoder-roadmap-007-trainable-autoencoder-upgrade`
- Target: `logic.optimizer.autoencoder`
- Scope: `loss`
- Objective: Add a guarded path for a wider/deeper trainable autoencoder layer or stronger linear feature projection after the routing/queue quality gates are clean, with GPU support, regularization, warm-start persistence, and holdout validation.
- Acceptance criteria:
  - The default path remains deterministic/explainable, but an experimental PyTorch-backed model can train on feature hashes.
  - Training uses CPU/GPU device selection, validation split, early stopping, and regularization to avoid memorization.
  - The supervisor reports whether lower cross entropy/cosine/reconstruction loss came from generalizable feature weights rather than sample memory.
- Evidence:
  - Current autoencoder is feature-level deterministic, not a hidden-layer neural net.
  - The observed plateau likely comes from weak generalizable feature updates plus strict holdout gating, not just lack of layers.
