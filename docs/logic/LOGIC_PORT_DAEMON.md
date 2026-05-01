# Logic Port Daemon

`ipfs_datasets_py.optimizers.logic_port_daemon` is development tooling for iteratively improving the browser-native TypeScript/WASM port of the Python logic module.

It reads the TypeScript port roadmap as its controlling plan:

- `docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md`
- `docs/LOGIC_PORT_PARITY.md`

The nested deterministic parser plans are intentionally not the default task source for this daemon. Parser-specific work should be handled by the parser daemon.

Historical context:

- `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md`
- `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md`

It then calls `ipfs_datasets_py.llm_router.generate_text()` with `model_name="gpt-5.5"` and asks for a conservative TypeScript port improvement. GPT-family models are pinned to the router's `codex_cli` provider unless `--provider` is supplied, so the request flows through `codex exec` rather than local Hugging Face fallback. The daemon disables local Hugging Face fallback by default, because autonomous code changes should fail closed if the configured router cannot reach the requested model. The daemon only applies model output through allowlisted file replacements or `git apply`; it does not execute arbitrary commands returned by the model.

## Dry Run

```bash
PYTHONPATH=ipfs_datasets_py python -m ipfs_datasets_py.optimizers.logic_port_daemon \
  --repo-root . \
  --iterations 1
```

Dry run is the default. It calls the router, parses the proposed patch, and reports the session result without mutating files.

## Apply Patches

```bash
PYTHONPATH=ipfs_datasets_py python -m ipfs_datasets_py.optimizers.logic_port_daemon \
  --repo-root . \
  --iterations 3 \
  --apply
```

With `--apply`, each patch must pass `git apply --check` before it is applied. After application, the daemon runs:

- `npx tsc --noEmit`
- `npm run validate:logic-port`

Use `--validation-command` to override those checks, or `--skip-validation` for a fast local experiment.

## Supervised Continuous Mode

For unattended overnight runs, prefer the repository supervisor script. It starts the logic-port daemon against the outer TypeScript project root, pins `gpt-5.5` through `codex_cli`, uses 300 second operation timeouts, restarts the child immediately if it exits, revisits blocked tasks, and replenishes the TypeScript port plan when the normal backlog is exhausted:

```bash
setsid bash ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh \
  </dev/null > ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.out 2>&1 &
```

Check it with:

```bash
bash ipfs_datasets_py/scripts/ops/legal_data/check_logic_port_daemon.sh
```

Ensure it is running, starting the supervisor only if the health check fails:

```bash
bash ipfs_datasets_py/scripts/ops/legal_data/ensure_logic_port_daemon.sh
```

Stop only the logic-port supervisor and its child daemon with:

```bash
bash ipfs_datasets_py/scripts/ops/legal_data/stop_logic_port_daemon.sh
```

The supervisor writes:

- `ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.pid`
- `ipfs_datasets_py/.daemon/logic-port-daemon.pid`
- `ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.lock`
- `ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.status.json`
- `ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.latest.log`
- `ipfs_datasets_py/.daemon/logic-port-daemon-ensure.status.json`

It is deliberately separate from `run_legal_parser_optimizer_daemon.sh`, which supervises the deterministic parser daemon and uses the parser implementation plans.

The supervisor also has a stale-heartbeat watchdog. `WATCHDOG_STALE_AFTER_SECONDS` defaults to `420`, which is intentionally longer than the default 300 second LLM and command timeouts. `WATCHDOG_STARTUP_GRACE_SECONDS` defaults to `120`, so a freshly started daemon has time to write its first heartbeat before the watchdog evaluates stale state from a previous run. If the daemon heartbeat stops updating beyond the stale threshold, the supervisor terminates the daemon subprocess tree, records `last_recycle_reason: "stale_heartbeat"`, and immediately starts a fresh cycle. Stop/restart cleanup sends `TERM` first and escalates to `KILL` after `STOP_GRACE_SECONDS`, which defaults to `10`. Startup, stop, and restart also sweep orphaned `logic_port_daemon` children that point at the same status file, preventing two logic-port daemons from writing to the same task board and TypeScript files. A nonblocking `flock` on `logic-port-daemon-supervisor.lock` prevents two supervisors from running at once even if a stale PID file is present.

For a belt-and-suspenders watchdog outside the supervisor itself, run `ensure_logic_port_daemon.sh` periodically from cron or systemd. The script is idempotent: when the daemon is healthy it only records `already_running`; when the health check fails it starts the supervisor with `setsid` and then verifies the new process. The supervisor lock keeps repeated ensure calls from creating duplicate supervisors.

The supervisor can also run a bounded Codex maintenance pass when the daemon is alive but not making meaningful progress. `SUPERVISOR_AGENTIC_MAINTENANCE` defaults to `1`; set it to `0` to disable this behavior. Maintenance triggers when the current task reaches `SUPERVISOR_AGENTIC_TASK_FAILURES` failures since its last success, when `SUPERVISOR_AGENTIC_STAGNANT_ROUNDS` rounds elapse without a new accepted round, when `SUPERVISOR_AGENTIC_PROPOSAL_FAILURES` recent rounds produce no usable JSON/patch/file changes, when `SUPERVISOR_AGENTIC_TYPESCRIPT_QUALITY_FAILURES` recent rounds hit TypeScript parser/generic/type-quality failures with no accepted changed files, or when `SUPERVISOR_AGENTIC_ROLLBACK_FAILURES` recent rounds fail as rollback-quality failures with no accepted changed files. Rollback-quality failures include malformed patch apply-check failures, validation, validation-repair, file-repair-validation, and preflight loops. TypeScript quality failures include TS1005/TS1128-style parser failures plus TS2314/TS2322 generic and assignability failures. Proposal-quality failures include parse, empty-proposal, invalid-no-change, and no-change loops. The supervisor stops the child daemon, invokes `codex exec` with `gpt-5.5` against only the daemon/supervisor/docs/tests allowlist, runs shell syntax checks plus the daemon unit tests, records the result under `logic-port-daemon-agentic-maintenance_*.log`, and restarts the daemon. `SUPERVISOR_AGENTIC_COOLDOWN_SECONDS` prevents repeated maintenance loops.
When maintenance starts, the supervisor records the current progress counters as the new stagnant-round baseline before restarting the daemon. This prevents the same historical no-progress window from retriggering maintenance after the cooldown unless additional rounds complete without accepted work.
The cooldown is scoped by maintenance reason family, so a previous stagnant-round maintenance pass does not suppress a later rollback-quality maintenance pass.

```bash
PYTHONPATH=ipfs_datasets_py python3 -m ipfs_datasets_py.optimizers.logic_port_daemon \
  --repo-root . \
  --apply \
  --watch \
  --retry-interval 0 \
  --llm-timeout 300 \
  --command-timeout 300 \
  --heartbeat-interval 30 \
  --max-task-failures 4 \
  --proposal-attempts 3 \
  --file-repair-attempts 1 \
  --validation-repair-attempts 1 \
  --validation-repair-failure-budget 2 \
  --revisit-blocked-tasks \
  --blocked-backlog-limit 10 \
  --blocked-task-strategy fewest-failures \
  --plan-replenishment-limit 12 \
  --status-file ipfs_datasets_py/.daemon/logic-port-daemon.status.json \
  --progress-file ipfs_datasets_py/.daemon/logic-port-daemon.progress.json \
  --log-file ipfs_datasets_py/.daemon/logic-port-daemon.jsonl
```

Continuous mode runs without user input. If the configured `gpt-5.5` route is unavailable, it records a structured failure and starts the next cycle immediately by default. Time is bounded by operation timeouts, not by a fixed retry sleep: use `--llm-timeout 300` and `--command-timeout 300` to cap individual LLM and validation/git calls. When the route becomes available, it resumes patch generation, applies only patches that pass `git apply --check`, and then runs validation.

If a proposed patch fails `git apply --check`, the daemon stores the failed patch under `ipfs_datasets_py/.daemon/failed-patches/` and performs one automatic `gpt-5.5` repair attempt with the exact Git error before giving up on that cycle.

If the repaired diff is still malformed, the daemon performs one more repair path: it asks `gpt-5.5` to convert the same intended change into complete allowlisted file replacements. This is important for unattended runs because malformed diff hunks were the most common cause of "busy but no files changed" cycles.

The daemon also retries unusable proposals inside a cycle. If the model returns no JSON, an empty change, or refuses because the Codex subprocess is read-only, the next proposal attempt explicitly reminds it that the daemon applies returned JSON `files` replacements after validation. Empty proposals receive `failure_kind: "empty_proposal"` and parse failures receive `failure_kind: "parse"`, so repeated unproductive rounds can block the current task and advance the task board instead of spinning forever.

File replacement proposals now also get a cheap TypeScript replacement preflight during the proposal-attempt loop. If a replacement contains syntax errors such as Python-style object syntax or truncated declarations, or targeted generic/type-quality errors such as missing `Record`/`ReadonlyArray` type arguments and `unknown` assignability mistakes, the daemon rejects that proposal before touching the worktree and feeds the exact diagnostics into the next proposal attempt. This avoids spending a full validation/rollback cycle on files that cannot pass basic TypeScript checks.

When complete file replacements apply but fail validation, the daemon now performs one validation-repair attempt before waiting for the next cycle. The repair prompt includes the failed validation output and the attempted file contents, asks for corrected complete file replacements, and reruns the normal validation/rollback flow.

Validation repair is adaptive. After a task accumulates `--validation-repair-failure-budget` validation-repair failures since its last accepted round, the daemon skips additional validation-repair LLM calls for that task and lets the normal task-failure threshold block or advance it faster. This keeps unattended runs moving when a task repeatedly produces malformed TypeScript repairs.

Each proposal prompt includes recent failure context for the selected task plus current contents for likely target files selected from the tracked TypeScript logic tree. This keeps complete-file replacements grounded in the actual code instead of asking the model to infer file shape from filenames alone.

The prompt intentionally asks for one narrow requirement per cycle, at most 180 changed diff lines, and usually one implementation file plus one focused test. It now prefers exact `files` replacements over unified diffs for TypeScript/doc edits. File replacements are path-allowlisted, formatted with Prettier for TypeScript files, and rolled back automatically if validation fails, which keeps overnight runs biased toward changes that can be applied and validated unattended.

The daemon writes a heartbeat/status file while running:

- `ipfs_datasets_py/.daemon/logic-port-daemon.status.json`

That file records the daemon PID, timestamp, current state, selected task, latest result, changed files, and failure kind. While a cycle is active, a background heartbeat rewrites the file with `state: "heartbeat"` and the `active_state` it is waiting on, so a fresh timestamp means the daemon is alive even if the current Codex call has not returned yet. Use it with the JSONL result log to distinguish a crashed daemon from an active daemon that is waiting on Codex or validation.

The daemon also writes a progress summary:

- `ipfs_datasets_py/.daemon/logic-port-daemon.progress.json`

That file records total rounds, valid rounds, acceptance rate, current task, current-task failure counts, active state, plan status counts, failure-kind counts, the latest round, recent failures, and recent accepted changed files. It is written at cycle start, on heartbeat, and after each completed round, so it appears immediately after daemon startup instead of only after the first LLM call returns. Provider/Cloudflare HTML failures are compacted and classified, keeping the progress file readable even when Codex emits long HTTP error pages.
It also records `stagnant_rounds_since_valid`, which is the daemon-side count of completed work rounds since the latest accepted round. The supervisor uses a persisted baseline for its own maintenance trigger, but this field makes the current no-progress streak visible in health checks and logs.

The daemon blocks the current task after repeated failures in two ways: `--max-task-failures` counts total failures for the task since its last accepted round, while `max_task_failure_rounds` still guards repeated same-kind failures. This prevents a task from spinning forever by alternating between parse, patch, and validation failures.

At the beginning of each supervised cycle, the daemon also checks historical JSONL results before calling the LLM. If the selected task already exceeds the total-failure threshold, it marks that task blocked and advances immediately, avoiding one more wasted Codex call on work that is already known to be stuck.

If every parsed port-plan task is already `[x]` complete or `[!]` blocked, the daemon does not call `llm_router` with an empty target. Without replenishment it writes a terminal `no_eligible_tasks` result to the JSONL log, status file, progress summary, and generated task board. That keeps overnight runs bounded by the plan instead of spending Codex calls on an empty target.

By default, continuous mode now tries to replenish the TypeScript port plan before taking that terminal stop. If no eligible tasks remain, it first scans the current Python logic inventory and TypeScript logic implementation state. When obvious module or capability-marker gaps are exhausted, it then reviews the original browser-native TypeScript/WASM parity goal against accepted-work evidence, progress logs, Python ML/spaCy expectations, public API coverage, and no-server-runtime validation needs. It appends a `Daemon-Discovered Implementation Gaps` section to `docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md`, refreshes the generated task board, and immediately continues with the newly added task. Use `--plan-replenishment-limit` to bound how many tasks are added in one pass, or `--no-plan-replenishment` to keep the old fail-closed behavior.

Use `--revisit-blocked-tasks` when the normal backlog is exhausted and you intentionally want the daemon to work through blocked tasks again. In that mode, selection still prefers `[ ]` and `[~]` tasks first; only when none remain does it select `[!]` tasks. The stale-failure pre-cycle blocker is disabled for this mode so historical failures do not immediately re-block the task before the new attempt. A successful round marks the blocked source checkbox `[x]`; a failed round leaves it blocked and records the latest failure evidence.

Blocked task selection is controlled by `--blocked-task-strategy`:
When failure counts tie under `fewest-failures` or `most-failures`, the daemon now prefers the blocked task least recently attempted. That keeps revisit mode rotating across equally stuck tasks instead of repeatedly selecting the first checkbox by markdown order.

- `plan-order` keeps the markdown order and is the conservative default.
- `fewest-failures` chooses the blocked task with the fewest failures since its last accepted round, which is useful for overnight unblocking runs that should make easier progress first.
- `most-failures` chooses the task with the most failures first when you want to concentrate on the worst blocker.

Blocked-task revisit mode also writes a `Blocked Backlog` section to the generated task board and includes the same backlog context in the LLM prompt. Each entry records the task label, failure count since the last accepted round, failure-kind counts, and the latest compact error. Use `--blocked-backlog-limit` to control how many blocked tasks are summarized.

The daemon also encodes local test-harness conventions. Logic tests run under Jest with global `describe`/`it`/`expect`, so proposals importing `vitest` or `@jest/globals` are rejected before any files are written. This avoids failed autonomous cycles that create valid-looking tests for the wrong runner.

## Markdown Task Tracking

The TypeScript port plan is the daemon's task ledger. By default this daemon maintains a generated `Daemon Task Board` inside `docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md`. The nested deterministic parser implementation plan is intentionally left for the parser-specific daemon.

On each daemon round it:

- parses Markdown task checkboxes from the porting plan;
- treats `[x]` as complete, `[ ]` as needed, `[~]` as in progress, and `[!]` as blocked;
- selects the first needed or in-progress task and injects that task into the next LLM prompt;
- optionally revisits blocked tasks with `--revisit-blocked-tasks` after the needed/in-progress backlog is exhausted;
- updates the task board after the round with the current target, checklist state, latest result, and follow-up instructions.

The task board is generated between marker comments, so manual plan prose can stay stable while the daemon rewrites only its own tracking section.

For accepted rounds, the daemon records the concrete changed files in the JSONL artifact and in the task board's latest-round section. Successful checkbox tasks are also marked complete in the source checklist so the next cycle advances to the next unfinished porting task instead of repeating invisible fixture work.

The daemon now distinguishes fixture/capture tasks from implementation tasks. If the selected port-plan checkbox does not explicitly ask for fixtures, captures, docs, evaluation, or planning, a proposal must change runtime TypeScript under `src/lib/logic/`; docs-only and parity-fixture-only changes are rejected before they touch the worktree. Fixture and capture tasks must still add tests that load and assert the fixture content so the generated work is exercised by `npm run validate:logic-port`.

Validated accepted work is also appended to `docs/IPFS_DATASETS_LOGIC_PORT_DAEMON_ACCEPTED.md`. That ledger records the target task, impact statement, changed files, validation commands, and evidence artifact paths so daemon output is visible even when the changed files are small.

For every accepted round, the daemon also writes review artifacts under `ipfs_datasets_py/.daemon/accepted-work/`:

- a JSON manifest with task, impact, changed files, validation status, and diff-stat summary;
- a `.patch` snapshot from `git diff -- <changed files>`;
- a `.stat.txt` summary from `git diff --stat -- <changed files>`.

These files make accepted daemon output auditable without hunting through process logs.

If the system Codex CLI is too old for `gpt-5.5`, install a local CLI and point the router at it:

```bash
npm install --prefix ipfs_datasets_py/.daemon/codex-cli @openai/codex@0.125.0

IPFS_DATASETS_PY_CODEX_CLI_BIN=ipfs_datasets_py/.daemon/codex-cli/node_modules/.bin/codex \
IPFS_DATASETS_PY_CODEX_SANDBOX=read-only \
PYTHONPATH=ipfs_datasets_py \
python3 -m ipfs_datasets_py.optimizers.logic_port_daemon \
  --repo-root . \
  --apply \
  --watch \
  --retry-interval 0 \
  --llm-timeout 300 \
  --command-timeout 300 \
  --heartbeat-interval 30 \
  --max-task-failures 4 \
  --proposal-attempts 3 \
  --file-repair-attempts 1 \
  --validation-repair-attempts 1 \
  --status-file ipfs_datasets_py/.daemon/logic-port-daemon.status.json \
  --progress-file ipfs_datasets_py/.daemon/logic-port-daemon.progress.json \
  --log-file ipfs_datasets_py/.daemon/logic-port-daemon.jsonl
```

## Runtime Boundary

This daemon is optimizer/development tooling. It must not be imported by the browser runtime and must not change the TypeScript logic port into a Python-service wrapper. The implementation target remains local TypeScript/WASM parity.
