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
- If legal-parser targets are dirty and stable, validate and commit them or
  restore only those targets.
- If recovery itself repeats the same failure, escalate to maintenance.
- If cycles keep advancing without accepted parser/encoder/decoder/prover work,
  escalate to maintenance instead of waiting overnight for visible files to
  change.
- If maintenance produces no output for the idle-timeout window, terminate it.
- If a no-op recovery clears a stale trigger, restart quickly.
- If the supervisor exits, the ensure wrapper restarts it.

## Recommended Overnight Entry Point

Use the ensure wrapper, not the raw supervisor:

```bash
bash scripts/ops/legal_data/ensure_legal_parser_optimizer_daemon.sh
```

For an external terminal session wrapper:

```bash
ENSURE_LAUNCH_MODE=tmux bash scripts/ops/legal_data/ensure_legal_parser_optimizer_daemon.sh
```
