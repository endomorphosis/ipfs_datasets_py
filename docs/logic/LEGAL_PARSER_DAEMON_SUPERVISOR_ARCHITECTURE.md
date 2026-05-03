# Legal Parser Daemon Supervisor Architecture

This daemon stack exists to autonomously improve the deterministic legal parser,
encoder, decoder, and prover-syntax integration without adding parser-runtime
LLM dependencies.

## Control Layers

1. `ensure_legal_parser_optimizer_daemon.sh`
   - Owns unattended liveness.
   - Starts a wrapper loop around the supervisor.
   - Removes stale supervisor pid/lock artifacts when the process is dead.
   - Re-wraps an already-running supervisor so a later supervisor exit is still
     restarted.
   - Writes `.daemon/legal_parser_daemon_ensure.status.json`.

2. `run_legal_parser_optimizer_daemon.sh`
   - Owns supervision and recovery.
   - Starts the Python optimizer daemon.
   - Detects stale heartbeats, dirty parser target loops, repeated rejection
     families, repeated validation failure families, accepted-patch stalls, and
     repeated recovery failures.
   - Runs focused recovery or Codex maintenance when the daemon is stuck.

3. `ipfs_datasets_py.optimizers.logic.deontic.parser_daemon`
   - Owns parser improvement cycles.
   - Evaluates deterministic parser quality.
   - Requests a bounded implementation slice through `llm_router`.
   - Validates candidate patches before retaining them.
   - Emits progress and current-status artifacts for the supervisor.

## Mission Lanes

The daemon prompt now includes a durable `mission_state` with an `active_lane`.
The active lane keeps autonomous work pointed at the right kind of progress:

- `repair_stability`: fix focused validation failures and dirty target loops.
- `parser_capability_expansion`: add deterministic parser/IR/formula/export
  families with tests.
- `encoder_decoder_prover_integration`: build text -> encoder -> IR -> decoder
  -> text quality checks and theorem-prover syntax validation across frame
  logic, deontic CEC, FOL, deontic FOL, and deontic temporal FOL.
- `metric_moving_parser_slice`: target a concrete metric-stall sample.
- `patch_stable_parser_family`: keep a family-sized improvement within a
  narrow file pair when patch application is unstable.

## Recovery Contract

The supervisor should never silently stall in a dead or idle state. Expected
behavior:

- If the daemon dies or heartbeat goes stale, recycle it.
- During the child startup grace window, do not act on stale progress artifacts
  from the previous run; give the new daemon a chance to write a fresh status
  first.
- Stop known competing automation, including PPD daemon/supervisor processes
  and orphaned PP&D LLM helper children that can launch their own Codex,
  Copilot, and pytest loops against the same worktree.
- If legal-parser targets are dirty and stable, validate and commit them or
  restore only those targets.
- If recovery itself repeats the same failure, escalate to maintenance.
- If an internal escalation reason exists, keep it sticky across child stop so
  maintenance cannot be skipped just because the stopped child no longer emits
  the same live trigger.
- If cycles keep advancing without accepted parser/encoder/decoder/prover work,
  escalate to maintenance instead of waiting overnight for visible files to
  change.
- If maintenance produces no output for the idle-timeout window, terminate it.
- If maintenance validates changed allowed files, stage and commit those changes
  with a supervisor-maintenance commit so repaired daemon programming becomes
  durable and visible to later runs.
- If the supervisor is terminated during maintenance, clear the active
  maintenance window and mark the running maintenance status as interrupted so
  health checks cannot report stale work as live progress.
- If the roadmap checklist has no actionable pending tasks, maintenance should
  audit the current parser/formal-logic code against the original goal and add
  concrete unchecked tasks to the implementation plan before restarting normal
  capability work.
- If a no-op recovery clears a stale trigger, restart quickly.
- If the supervisor exits, the ensure wrapper restarts it.
- Health is green only when the supervisor is alive and either the daemon has a
  fresh heartbeat or a bounded supervisor recovery/maintenance window is active.

## Patch Transport

The daemon still stores proposals as auditable unified diffs, but patch
validation is not a single brittle `git apply --check` anymore. It first tries a
strict apply check, then retries with whitespace repair, then with Git three-way
apply. The actual apply step reuses the strategy that passed validation. Longer
term, the preferred direction is patchless proposal generation in an isolated
worktree: let the model edit files there, then have Git generate the canonical
diff that the daemon validates and applies.

## Formal Logic Target Scope

Autonomous parser work is allowed to move across the whole deterministic formal
logic stack, not just the first parser/export files. The daemon prompt and
recovery allowlists include parser, IR, formula, converter, exports, decoder,
prover syntax, graph/support/knowledge-base helpers, and the matching deontic
tests. That keeps overnight work aligned with the goal: deterministic legal text
to `LegalNormIR` to formal logic/prover syntax without parser-runtime LLM calls.

For unattended unbounded runs, even the default `standard_material_slice` is
quality-gated. A retained slice should be a coherent parser/formal-logic family,
not a one-phrase patch that makes the daemon look busy without moving the
implementation plan.

## Recommended Overnight Entry Point

Use the ensure wrapper, not the raw supervisor:

```bash
bash scripts/ops/legal_data/ensure_legal_parser_optimizer_daemon.sh
```

For an external terminal session wrapper:

```bash
ENSURE_LAUNCH_MODE=tmux bash scripts/ops/legal_data/ensure_legal_parser_optimizer_daemon.sh
```
