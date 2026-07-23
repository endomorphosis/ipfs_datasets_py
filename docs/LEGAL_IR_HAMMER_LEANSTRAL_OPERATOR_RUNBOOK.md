# Legal IR Hammer/Leanstral Operator Runbook

This runbook covers the production rollout of the parallel legal-text compiler,
decompiler, Hammer/Lean reconstruction, Leanstral audit, autoencoder, and Codex
repair pipeline. Run all commands from the `ipfs_datasets_py` repository root.

The only production sequence is:

1. `short_smoke` — 600 seconds;
2. `one_hour_hparam` — six 600-second trials (3,600 seconds total);
3. `eight_hour_canary` — 28,800 seconds with the selected configuration; and
4. `twenty_four_hour_production` — 86,400 seconds with that same configuration.

The launcher refuses different durations. Each completed prefix is gated before
the next process starts. A missing, partial, reordered, duplicated, or malformed
snapshot blocks promotion. The production decision additionally requires the
complete four-stage sequence.

## Trust boundaries

Keep these artifacts separate throughout operation and incident handling:

| Artifact | Authority | Permitted use |
| --- | --- | --- |
| Deterministic compiler/decompiler patch | A version-controlled change with focused tests and frozen-canary evidence | Candidate executable repair. It is accepted only after validation and rollout gates pass. |
| Trusted Hammer/Leanstral guidance | Structured guidance that passed syntax, provenance, anti-copy, proof, and configured Lean reconstruction checks | May enter the trusted feature bus, bounded autoencoder training, and Codex TODO projection. |
| Stable autoencoder export | `legal-ir-stable-autoencoder-feature-export-v1`, source-free and with `sample_memory_included: false` | Inert candidate guidance. It is not a theorem or executable compiler behavior. |
| Promoted learned guidance | `legal-ir-learned-guidance-promotion-v1` tied to a complete fixed canary and rollback metadata | May be activated only while its reviewed rollout evidence remains valid. |
| Untrusted Leanstral draft | Candidate JSON or free-form model output before deterministic verification | Audit input only. Never use it as ground truth, a proof, a reconstruction target, or autoencoder training signal. |

Verification creates a new trusted structured artifact; it does not make raw
draft text trusted. A stable representation export likewise remains inert until
the independent promotion gate accepts it.

## Preflight

Use a clean, dedicated rollout host. The launcher checks for managed optimizer
processes before the smoke stage and after every stage. Any surviving
`uscode_modal_daemon_runner`, hparam helper, or legal-IR smoke process fails the
rollout as an orphan; the launcher never adopts or kills it automatically.

Inspect processes first:

```bash
pgrep -af 'uscode_modal_daemon_runner|run_hparam_then_8h|run_hammer_leanstral_smoke' || true
```

On a dedicated host, stop a known prior rollout gracefully and verify it exits:

```bash
pkill -TERM -f '<exact-prior-rollout-id>'
pgrep -af '<exact-prior-rollout-id>' || true
```

Do not use a broad `pkill` on a shared machine. Resolve each PID and run ID
before signaling it. Escalate to `KILL` only after logs and state are preserved
and the process has failed to honor `TERM` within its configured grace period.

Validate the taskboard and dependencies with the same parser used by the
implementation daemon:

```bash
PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. \
  /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -c \
  "from pathlib import Path; from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_task_file; tasks=parse_task_file(Path('docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md')); ids={task.task_id for task in tasks}; assert len(tasks)>=53; assert all(task.acceptance and task.validation and task.outputs for task in tasks); assert all(dep in ids for task in tasks for dep in task.depends_on); print('parsed', len(tasks), 'tasks')"
```

Then verify the checkout, supervisor, Python environment, free disk space, and
available accelerators:

```bash
git status --short
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh status
.venv-cuda/bin/python -c 'import torch; print(torch.__version__, torch.cuda.is_available())'
df -h workspace
```

Do not start a rollout from an unexplained dirty checkout. Record the baseline
commit (`git rev-parse HEAD`), host identity, CUDA/driver version, operator,
rollout ID, and any documented degraded backend before allocating resources.

## Dry run and identifiers

Choose one globally unique rollout ID and inspect all derived paths:

```bash
BASE_RUN_ID=legal-ir-hammer-leanstral-rollout-$(date -u +%Y%m%dT%H%M%SZ)
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh \
  --dry-run --base-run-id "${BASE_RUN_ID}"
```

The dry run does not create evidence or start a process. Confirm these values:

- `stage_sequence` lists the four stages in the required order;
- `smoke_seconds=600`, `hparam_seconds=3600`, `canary_seconds=28800`, and
  `final_seconds=86400`;
- representation promotion and complete evidence are required;
- Hammer guidance and trusted autoencoder training arguments are enabled; and
- snapshot, gate evidence, and production summary paths use the intended ID.

The default output set is:

```text
workspace/test-logs/<rollout-id>-rollout-snapshots.json
workspace/test-logs/<rollout-id>-rollout-gate.json
workspace/test-logs/<rollout-id>-rollout-evidence/
workspace/test-logs/<rollout-id>-best-24h-autoencoder.summary
```

Use `--snapshot-path` and `--evidence-output` when evidence must live on a
separate durable volume. The launcher refuses to overwrite an existing
manifest or evidence directory. Reusing an ID is not a resume mechanism; gate
an existing manifest or begin a new rollout with a new ID.

## Run the rollout

Start the full sequence in a persistent operator session:

```bash
BASE_RUN_ID=legal-ir-hammer-leanstral-rollout-<timestamp> \
CODEX_SCOPE_WORKERS=2 \
AUTOENCODER_DEVICE=cuda \
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh
```

Defaults use six ten-minute trials. `TRIAL_SECONDS` and `TRIAL_COUNT` may be
redistributed only when their product is exactly 3,600 seconds and the count is
between one and six; the standard six-by-ten-minute search is preferred for
comparability. Smoke, canary, and production durations cannot be changed.

The launcher performs these transitions:

```text
smoke summary -> prefix gate
  -> all hparam trial gates -> aggregate hparam snapshot -> prefix gate
  -> selected-config canary summary -> prefix gate
  -> same-config production summary -> complete gate
```

The hparam helper’s selected, expanded argument array is retained by the
launcher. The production process changes only the run ID and duration from the
canary invocation; it does not silently repeat the search or select a new
configuration.

The process exits nonzero at the first failed command or gate. It does not
continue to collect “more evidence” after a failed promotion decision.

### Standalone smoke diagnosis

The integrated launcher always owns the promotion smoke. For focused diagnosis
without beginning the rollout, use the smoke wrapper separately:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh --dry-run
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh
```

A standalone smoke is diagnostic and cannot be substituted into a production
manifest. To recheck its legacy summary gate:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh \
  --gate-only \
  --summary-path workspace/test-logs/<smoke-run-id>-autoencoder.summary
```

Disabling representation promotion, successful promotion, or complete canary
evidence is permitted only for legacy diagnosis. Such a result remains
canary-only and cannot authorize a later stage.

## Monitoring

In another terminal, watch processes, disk, GPU health, the pipeline log, and
manifest creation. Use the exact rollout ID to avoid observing another run:

```bash
pgrep -af '<rollout-id>'
watch -n 30 nvidia-smi
watch -n 30 df -h workspace
tail -F workspace/test-logs/<pipeline-log>
```

The legacy helper monitor can inspect the hparam/canary portion:

```bash
scripts/ops/logic/watch_hparam8h_pipeline.sh <rollout-id>
```

Treat these conditions as an incident, not as ordinary slow progress:

- no summary modification or completed cycle beyond the configured watchdog
  interval;
- a managed child absent while its stage is active, or present after it exits;
- increasing queue-lag p95, a permanently claimed TODO, or a queue that grows
  without accepted patches;
- a nonzero child exit, fatal stop reason, OOM, swap pressure, or repeated
  transient execution failure;
- trusted guidance with no corresponding trusted-feature-bus autoencoder
  receipt; or
- a changed fixed-canary identity, source digest, baseline revision, or sample
  set during a rollout.

Preserve logs and snapshots before terminating an unhealthy run. Never edit a
live summary to make a gate pass.

## Snapshot and gate evidence

The manifest schema is `legal-ir-hammer-leanstral-rollout-v1`. It contains the
rollout ID and an ordered `snapshots` array. Each snapshot embeds the source
summary and adds the stage contract:

- exact `stage`, `duration_seconds`, `snapshot_complete`, and successful
  `status`;
- `managed_processes` with name, PID, exit status, exit code, and explicit
  `orphaned: false`;
- per-family semantic, provenance, anti-copy, Hammer proof, Lean
  reconstruction, process-lifecycle, and queue-lag evidence;
- `trusted_feedback` counts and matching source/autoencoder digests;
- integer `accepted_patches` and positive `wall_clock_seconds`;
- queue-lag p95; and
- rollback artifact path, SHA-256, baseline revision, and restorability.

The hparam snapshot is aggregate evidence: quality and trusted-feedback
selection come from the winning gated trial, while accepted-patch and queue
telemetry cover all trial summaries. The gate compares accepted patches per
wall-clock hour, never raw totals from runs of different duration.

Every raw stage summary is copied into the rollout evidence directory before
the manifest is atomically replaced. Existing rollback artifacts are never
overwritten. A copied artifact’s digest, the recorded digest, and the manifest
must continue to agree.

Inspect the compact decision after each prefix and the final decision after
production:

```bash
jq '{rollout_id, stages: [.snapshots[].stage]}' \
  workspace/test-logs/<rollout-id>-rollout-snapshots.json
jq . workspace/test-logs/<rollout-id>-rollout-evidence/eight_hour_canary-gate.json
jq . workspace/test-logs/<rollout-id>-rollout-gate.json
```

Both process exit code `0` and JSON `"accepted": true` are required.

Recheck a complete manifest without starting work:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh \
  --gate-only \
  --snapshot-path workspace/test-logs/<rollout-id>-rollout-snapshots.json \
  --evidence-output workspace/test-logs/<rollout-id>-rollout-gate.recheck.json
```

For incident diagnosis, a strict ordered prefix can be rechecked explicitly:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh \
  --gate-only --allow-prefix \
  --snapshot-path workspace/test-logs/<rollout-id>-rollout-snapshots.json \
  --evidence-output workspace/test-logs/<rollout-id>-prefix-gate.recheck.json
```

`--allow-prefix` authorizes only the next named stage reported by the gate. It
never authorizes production from an incomplete sequence.

## Promotion checklist

Before acknowledging any prefix promotion, verify:

- all snapshots through the current stage are present once, in order, complete,
  successful, and have the exact duration;
- every LegalIR family has no hard semantic, provenance, anti-copy, Hammer
  proof, Lean reconstruction, process-lifecycle, or queue-lag regression;
- compiler/decompiler CE and cosine metrics are paired against the same frozen
  sample set, rather than hidden behind a macro average;
- source-copy penalty has not increased and no copied source span, raw draft,
  proof prose, decoded embedding, or sample memory entered learned guidance;
- trusted guidance count is positive, the autoencoder received it, and source
  and receipt digests match;
- managed children exited zero and no matching process remains alive;
- queue-lag p95 is within the absolute bound and has not regressed;
- accepted patches per wall-clock hour has not regressed from the preceding
  stage;
- rollback artifact paths exist, SHA-256 digests match, baseline revisions are
  recorded, and every record is restorable; and
- learned guidance remains linked to its fixed canary, export ID, promotion ID,
  activation key, rollback ID, and disable action.

Warnings require review but do not override a failure. Never promote using only
aggregate similarity, total TODOs, or total accepted patches.

## Failure triage

| Gate failure | Required action |
| --- | --- |
| Missing/incomplete/reordered stage or duration mismatch | Stop. Recover the original complete artifact if available; otherwise start a new rollout ID from smoke. Do not manufacture a snapshot. |
| Orphaned, running-as-exited, or nonzero managed process | Preserve logs, stop the exact PID, reconcile its state, and restart from a new rollout ID. |
| Semantic or per-family IR regression | Inspect the named family, contract, mutation, and frozen samples; repair or retrain, then restart at smoke. |
| Provenance or anti-copy regression | Quarantine the candidate and audit source spans, citations, feature-bus exclusions, and decompiler structure. Similarity gains cannot compensate. |
| Hammer proof or Lean reconstruction regression | Inspect obligation generation, backend translation, proof receipts, native reconstruction, and backend health. |
| Trusted-feedback count/digest failure | Inspect the guidance artifact, trusted feature bus, autoencoder training report, rejected/duplicate IDs, and configuration fingerprint. |
| Queue lag failure | Inspect claimed-item age, worker health, queue caps, batching, lock contention, and transient retries before changing parallelism. |
| Accepted patches/hour regression | Compare matched wall-clock rates, validation rejection, dedupe, main-apply rollback, and worker contention. Raw totals are not comparable. |
| Rollback evidence missing or digest mismatch | Do not promote. Preserve the directory read-only and investigate tampering, truncation, or storage failure. |

Unavailable proof backends may be warning-only for contracts that do not require
them. When backend availability is required, use the strict backend option and
treat unavailability as fatal. An external proof still requires the configured
trusted Lean reconstruction before it becomes training evidence.

## Rollback and incident preservation

If a prefix or production check fails:

1. stop the exact rollout process gracefully and verify no managed process
   remains;
2. make the manifest, gate JSON, stage summary copies, runner logs, TODO queue,
   model state, and promotion/export records read-only or copy them to durable
   incident storage;
3. verify every stage copy before using it:

   ```bash
   sha256sum workspace/test-logs/<rollout-id>-rollout-evidence/*.summary.json
   jq '.snapshots[] | {stage, rollback_evidence}' \
     workspace/test-logs/<rollout-id>-rollout-snapshots.json
   ```

4. record the failed stage, stop reason, host, PID set, current revision, and
   the exact first gate failure;
5. disable the exact promoted guidance activation key using its recorded
   `remove_promoted_guidance_records` action and restore `canary_only` mode;
6. restore compiler/model/queue state only through the deployment’s reviewed
   rollback procedure, using the recorded baseline revision and artifact—not a
   guessed “latest good” file; and
7. rerun validation and begin a fresh four-stage rollout from smoke.

Do not delete failed evidence, rewrite the manifest, reuse a rollout ID, skip to
canary, or mark an orphan as exited. If an activation registry is not wired,
promotion reports are review evidence only and must remain inactive.

## Parallelism controls

Use the production profile emitted by the autotuner as the starting point. The
primary controls are:

- `CODEX_PARALLEL_SCOPES` and `CODEX_SCOPE_WORKERS` for isolated Codex work;
- `AUTOENCODER_BRIDGE_WORKERS` for bridge/prover evaluation;
- `DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS` for Hammer backends; and
- `LEANSTRAL_AUDIT_BATCH_SIZE` and `LEANSTRAL_AUDIT_BATCH_USE_MESH` for audit
  batching.

Change resource knobs only between complete rollout attempts, record the
profile, and start again from smoke. Higher utilization is not a promotion
criterion. Queue lag, process lifecycle, accepted patches per hour, per-family
quality, provenance, and trust boundaries remain authoritative.
