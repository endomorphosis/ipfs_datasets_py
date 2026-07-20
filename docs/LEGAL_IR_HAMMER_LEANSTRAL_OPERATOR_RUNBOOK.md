# Legal IR Hammer/Leanstral Operator Runbook

This runbook operates the expanded hammer/Leanstral optimization path for the
legal text compiler, decompiler, multi-view LegalIR metrics, autoencoder, and
Codex repair loop. The safety rule is simple: model output may propose work,
but deterministic verification authorizes trusted training signal, and a
supervised fixed-canary gate authorizes representation promotion.

Run commands from the `ipfs_datasets_py` repository root. Paths below are
repository-relative unless stated otherwise.

## Trust Boundaries

Do not collapse these four artifact classes into one "guidance" label:

| Artifact class | How to identify it | Authority and permitted use |
| --- | --- | --- |
| Deterministic compiler/decompiler repair | Version-controlled changes under `ipfs_datasets_py/logic` or the deterministic integration layer, with a focused test and fixed-canary evidence | Executable implementation. It may be merged only after its task validation and rollout guardrails pass. A Codex patch is still only a candidate repair until those checks pass. |
| Trusted hammer/Leanstral guidance | A `HammerGuidanceArtifact` or verified candidate whose `trusted` state is backed by deterministic syntax, provenance, KG shape, backend proof, and configured reconstruction checks | May feed the trusted feature bus, autoencoder feature training, and bounded Codex TODO projection. Trust applies to the verified structured facts, not to the original generated prose or proof text. |
| Autoencoder-learned representation export | Schema `legal-ir-stable-autoencoder-feature-export-v1`, with an `export_id`, stable feature summaries, view-family weights, and `sample_memory_included: false` | Inert promotion input, not proof and not executable compiler behavior. It becomes activatable deterministic IR guidance only through a successful `legal-ir-learned-guidance-promotion-v1` report with complete fixed-canary and rollback evidence. |
| Untrusted Leanstral draft | Strict candidate JSON emitted before verification, including rejected candidates and free-form source model output | Proposal only. Never use as ground truth, a reconstruction target, a theorem, a compiler repair, or direct autoencoder training signal. Preserve it only for bounded audit/provenance needs. |

A verified Leanstral candidate does not retroactively make its raw draft
trusted. The verifier emits a separate structured guidance artifact containing
the facts that passed. Likewise, an autoencoder export can be stable and
source-free without being eligible for promotion.

## End-to-End Workflow

The normal operator sequence is:

1. Stop stale optimizer processes and confirm the checkout and taskboard are
   safe to use.
2. Parse the taskboard and inspect the dependency frontier.
3. Let the implementation supervisor finish dependency-ready deterministic
   tasks; validate and commit each prerequisite before dispatching dependents.
4. Dry-run, then execute one smoke cycle.
5. Inspect per-view metrics, hammer health, trust counts, TODO productivity, and
   the learned-representation promotion report. The smoke wrapper gates the
   resulting summary.
6. Run the one-hour hyperparameter sweep. Each trial is gated before selection.
7. Allow the selected configuration to enter the 24-hour run only when all
   gates pass; monitor the pipeline and final summary.
8. Activate only promoted guidance records whose report remains tied to the
   reviewed fixed canary and contains usable rollback metadata.

Any failed gate requires the operator to keep the workflow in canary-only
operation. Do not override a failure by copying a `promoted: true` flag into a
summary: the rollout gate recomputes metric direction and regression from
baseline and candidate values.

## Stop Active Runs

Stop any existing legal-IR optimizer processes before changing rollout
settings or starting a replacement run:

```bash
pkill -TERM -f 'legal-ir|uscode_modal|run_leanstral|logic_theorem_optimizer|modal_autoencoder' || true
pgrep -af 'legal-ir|uscode_modal|run_leanstral|logic_theorem_optimizer|modal_autoencoder' || true
```

Only the `pgrep` command itself should remain. This broad stop command is for a
host dedicated to this optimizer. On a shared host, inspect `pgrep` output and
terminate only the run IDs owned by this workflow.

## Preflight and Taskboard Validation

The implementation supervisor accepts only `todo`, `in_progress`, `blocked`,
and `completed`. Every task must have outputs, validation, and acceptance text,
and every dependency must resolve to another task ID in the same board. Run the
same fail-closed check used by the taskboard validation:

```bash
PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. \
  /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -c \
  "from pathlib import Path; from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_task_file; tasks=parse_task_file(Path('docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md')); ids={task.task_id for task in tasks}; assert len(tasks)>=34, len(tasks); assert all(task.acceptance and task.validation and task.outputs for task in tasks); assert all(dep in ids for task in tasks for dep in task.depends_on); assert not [task for task in tasks if task.status not in {'todo','completed','in_progress','blocked'}]; print('parsed', len(tasks), 'tasks')"
```

Then check the wrapper and repository state:

```bash
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh status
git status --short
```

`start` deliberately refuses a dirty checkout. Implementation worktrees are
created from `HEAD`, so completed prerequisites must be validated and committed
before dependent tasks are dispatched. Do not manually mark a task completed;
the implementation daemon owns lifecycle status updates after validation and
merge.

## Supervisor Handoff

Use the repository-local lifecycle wrapper for normal operation:

```bash
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh status
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh once
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh start
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh stop
```

`once` performs reconciliation only and does not start implementation. `start`
runs the implementation supervisor in the background. The wrapper reports its
state directory and log path; defaults are under
`workspace/hammer-leanstral-supervisor/`.

The implementation daemon can also run one bounded foreground reconciliation:

```bash
PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. \
  .venv-cuda/bin/python -m \
  ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon \
  --once \
  --todo-path docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md \
  --state-dir workspace/hammer-leanstral-supervisor \
  --state-prefix hammer_leanstral \
  --task-prefix '## PORTAL-'
```

Keep legal-IR implementation and tests in `ipfs_datasets_py`. Keep reusable
daemon routing, worker lifecycle, and generic task parser changes in
`ipfs_accelerate_py`.

## Smoke Run

First inspect the exact command and strict representation-gate settings:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh --dry-run
```

Then run one guarded hammer/Leanstral, autoencoder, and Codex cycle:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh
```

The defaults are one cycle with a ten-minute limit. If `codex` is unavailable,
the wrapper uses `packet_only` mode; generated repair packets are not executed
and remain candidates for later review.

To re-run only the gate against an existing summary:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh \
  --gate-only \
  --summary-path workspace/test-logs/<run-id>-autoencoder.summary
```

The wrapper defaults to requiring a representation promotion report, a
successful promotion, complete evidence, and zero regression for each
promotion-specific metric. Disabling one of these requirements is a diagnostic
or legacy-compatibility action, not a production promotion:

```bash
GATE_REQUIRE_SUCCESSFUL_REPRESENTATION_PROMOTION=false \
  scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh \
  --gate-only --summary-path workspace/test-logs/<summary>.summary
```

Record any such override with the run evidence and keep the result canary-only.

## Hyperparameter Sweep and 24-Hour Run

Dry-run the full command before allocating resources:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh --dry-run
```

Run the default six ten-minute trials followed by a 24-hour optimizer loop:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh
```

Explicitly setting the defaults is useful in an operator record:

```bash
BASE_RUN_ID=legal-ir-hammer-leanstral-hparam24h-<timestamp> \
TRIAL_SECONDS=600 \
TRIAL_COUNT=6 \
FINAL_SECONDS=86400 \
CODEX_SCOPE_WORKERS=2 \
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh
```

The script delegates to `scripts/ops/logic/run_hparam_then_8h.sh`, changes the
final label to `24h`, supplies hammer/Leanstral daemon arguments, and installs
the strict rollout gate for both trial selection and the final run. The final
summary defaults to:

```text
workspace/test-logs/<base-run-id>-best-24h-autoencoder.summary
```

Monitor a named pipeline in a second terminal:

```bash
scripts/ops/logic/watch_hparam8h_pipeline.sh <base-run-id>
```

The watchdog reports stale summaries, missing processes, no-progress overruns,
and successful final-cycle verification. Its state and logs live under
`workspace/test-logs/`.

## Inspect the Run Summary

The canonical evidence is the JSON summary passed to the rollout gate. At
minimum, inspect these groups before promotion:

- Run health: `status`, `cycles`, `latest_stop_reason`, child exit codes.
- Deterministic IR: `latest_legal_ir_view_family_validation`,
  `latest_legal_ir_view_family_macro_score`, contract coverage and contract
  failure counts.
- Hammer: `latest_daemon_hammer_guidance`, proof success, reconstruction
  success, backend health, and trusted-guidance count.
- Source-copy safety: `latest_compiler_ir_source_copy_reward_hack_penalty` and
  per-view source-copy penalty.
- Repair productivity: `program_synthesis_seeded`, deduped, pending, claimed,
  and completed counts.
- Representation promotion:
  `latest_legal_ir_learned_guidance_promotion` or another report carrying
  schema `legal-ir-learned-guidance-promotion-v1`.

Use the gate itself for a normalized pass/fail report. For strict standalone
inspection, include the same promotion requirements used by the wrappers:

```bash
.venv-cuda/bin/python -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate gate \
  --summary-path workspace/test-logs/<run-id>-autoencoder.summary \
  --require-representation-promotion \
  --require-successful-representation-promotion \
  --require-complete-representation-evidence \
  --max-per-view-ir-metric-regression 0 \
  --max-symbolic-validity-regression 0 \
  --max-hammer-proof-rate-regression 0 \
  --max-reconstruction-rate-regression 0 \
  --max-source-copy-penalty-regression 0 \
  --max-todo-productivity-regression 0
```

Exit code `0` and `"accepted": true` are both required. Warnings still require
operator review; they do not authorize bypassing a blocked promotion.

## Per-View Metrics

Review metrics separately for `deontic`, `frame_logic`, `tdfol`, `kg`, `cec`,
`external_provers`, and `decompiler`. A macro score can hide a regression in a
single view and is never sufficient promotion evidence.

| Metric | Preferred direction | Meaning |
| --- | --- | --- |
| `ir_cross_entropy_loss` | Lower | Deterministic compiler/decompiler IR loss |
| `ir_cosine_similarity` | Higher | Deterministic IR embedding agreement |
| `autoencoder_cross_entropy_loss` | Lower | Learned view-family prediction loss |
| `autoencoder_cosine_similarity` | Higher | Learned representation similarity |
| `symbolic_validity_success_rate` | Higher | Fraction satisfying deterministic symbolic checks |
| `hammer_proof_success_rate` | Higher | Fraction of submitted obligations proved |
| `reconstruction_success_rate` | Higher | Fraction reconstructed into the configured trusted native form |
| `source_copy_penalty` | Lower | Evidence of source-copy reward hacking |

The gate normalizes legacy aliases such as
`hammer_reconstruction_success_rate`, `structural_validity`, and
`source_copy_reward_hack_penalty`, but new evidence should use the canonical
names above.

The older aggregate fields remain useful for diagnosis:
`best_validation_ce`, `latest_validation_ce`, `best_validation_cosine`,
`latest_validation_cosine`, `best_validation_ir_ce`,
`latest_compiler_ir_ce`, `best_validation_ir_cosine`, and
`latest_compiler_ir_cosine`. Promotion decisions must use the paired per-view
baseline and candidate values, not aggregates alone.

## Representation Promotion Checklist

Treat a stable feature export as a candidate. Before activating any generated
guidance record, verify all of the following:

- The export schema is `legal-ir-stable-autoencoder-feature-export-v1`,
  `sample_memory_included` is `false`, and excluded categories cover raw source
  text, source spans, token features, sample identifiers, and sample memory.
- The promotion schema is `legal-ir-learned-guidance-promotion-v1`, status is
  `promoted`, `promotion_allowed` is true, and `block_reasons` is empty.
- `canary_evidence.canary_id` is non-empty, `fixed_sample_set` is true, and the
  baseline and candidate use the same sample set.
- Every represented view family has both baseline and candidate values for all
  eight metrics. Check all seven families for a full-family rollout.
- The gate independently reports no per-view IR, symbolic-validity, hammer,
  reconstruction, source-copy, or TODO-productivity regression beyond the
  explicitly approved tolerance.
- Each guidance record has a canonical `contract_id`, `view_family`, bounded
  `repair_lane_suggestions`, confidence, canary metric evidence, `export_id` or
  `source_export_id`, and `promotion_id`.
- Each record says `source: stable_autoencoder_feature_promotion`; no raw
  Leanstral text, proof prose, copied legal span, decoded embedding, or
  sample-specific memory is present.
- `rollback_metadata` includes an activation key, rollback ID, source export,
  previous promotion where applicable, and the disable action
  `remove_promoted_guidance_records`.
- TODO generation productivity does not regress; a representation that hides
  actionable verified failures is not promotable merely because similarity
  improved.

If any item is absent, keep the export inert and rerun the producer or fixed
canary. Do not synthesize missing evidence by hand.

## Rollout Gate Behavior and Triage

The gate rejects, among other conditions:

- failed summaries, fatal stop reasons, and non-zero child exit codes;
- validation or compiler-IR CE/cosine regression beyond configured tolerances;
- excessive absolute source-copy penalties;
- missing or unsuccessful representation promotion when strict mode is active;
- missing canary identity, incomplete per-family evidence, declared or
  recomputed metric regressions, and reduced TODO productivity;
- missing hammer cycle telemetry or unexpected hammer runtime failures;
- stalled TODO generation after the configured minimum cycles; and
- fatal backend availability when availability is explicitly required.

Common corrective actions:

| Failure family | Operator action |
| --- | --- |
| `missing_representation_*` or `representation_canary_*_missing` | Keep canary-only; regenerate a complete stable export and paired fixed-canary promotion report. |
| `representation_*_regression` | Do not promote; inspect the named view and metric, repair or retrain, then rerun the identical canary. |
| `representation_promotion_blocked` | Read `block_reasons`; fix the producer condition rather than changing the serialized status. |
| `source_copy_*` | Quarantine the candidate/export and inspect source-span leakage and decompiler structure. Similarity gains do not offset this failure. |
| `missing_hammer_cycle` or hammer runtime failure | Inspect `latest_daemon_hammer_guidance`, worker logs, timeouts, and backend translations. |
| `todo_generation_stalled` or productivity regression | Inspect recurring-failure clustering, dedupe counts, queue caps, allowed paths, and Codex execution mode. |
| Backend unavailable warning | Continue only in documented degraded mode, or provision the backend and repeat the run if that backend is required for the target contracts. |

Unavailable solvers may be represented as degraded backend health rather than a
crash. They become gate-fatal when the operator supplies
`--require-available-hammer-backend`. A proof from an available external
backend is still evidence, not automatically a trusted native proof; configured
reconstruction requirements remain in force.

## Rollback

If a promoted representation later fails a canary or production check:

1. Stop the affected optimizer run.
2. Identify the exact `promotion_id`, `activation_key`, `rollback_id`, and
   `previous_promotion_id` from `rollback_metadata`.
3. Apply the recorded `remove_promoted_guidance_records` disable action through
   the deployment-specific guidance registry and restore `canary_only` mode.
4. Preserve the failed summary, export, promotion report, and gate output for
   audit. Do not delete or rewrite the evidence.
5. Re-run the fixed canary after rollback and require the strict gate to pass
   before resuming the longer pipeline.

There is no generic runbook command that may guess which active registry to
mutate. If the deployment has not wired an activation registry, a promotion
report is review evidence only and must remain inactive.

## Parallelism Knobs

Use these environment variables to tune utilization:

- `CODEX_PARALLEL_SCOPES`: comma-separated AST/write scopes or `all`.
- `CODEX_SCOPE_WORKERS`: Codex workers per scope.
- `AUTOENCODER_BRIDGE_WORKERS`: bridge/prover evaluation workers.
- `DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS`: hammer backend workers.
- `LEANSTRAL_AUDIT_BATCH_SIZE`: Leanstral audit batch size.
- `LEANSTRAL_AUDIT_BATCH_USE_MESH`: enable or disable p2p mesh batching.

Raise Codex workers until validation failures or main-apply contention begin to
increase. Raise hammer and bridge workers only when those phases dominate cycle
time. Parallelism never changes allowed paths, trust requirements, or gate
thresholds.
