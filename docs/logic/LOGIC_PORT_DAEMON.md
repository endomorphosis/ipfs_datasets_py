# Logic Port Daemon

`ipfs_datasets_py.optimizers.logic_port_daemon` is development tooling for iteratively improving the browser-native TypeScript/WASM port of the Python logic module.

It reads the TypeScript port roadmap as its controlling plan:

- `docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md`
- `docs/LOGIC_PORT_PARITY.md`

The nested deterministic parser plans are intentionally not the default task source for this daemon. Parser-specific work should be handled by the parser daemon.

Historical context:

- `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md`
- `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md`

It can still call `ipfs_datasets_py.llm_router.generate_text()` with `model_name="gpt-5.5"` for legacy JSON file/patch proposals. The supervised overnight path now defaults to `PROPOSAL_TRANSPORT=worktree`: Codex runs against a throwaway detached Git worktree, edits files directly there, writes `.logic_port_worktree_proposal.json` metadata, and exits. The daemon then harvests Git's canonical diff plus complete allowlisted file contents, removes the worktree, applies the harvested file replacements to the real project only after preflight checks, and runs validation. If validation fails, the daemon recreates the failed candidate inside another temporary worktree, asks Codex to repair the failing tests or TypeScript diagnostics in place, harvests the repaired files, and validates again before falling back to legacy JSON repair. This keeps unattended porting focused on actual TypeScript/WASM edits instead of fragile hand-authored patches.

The Python daemon accepts an optional provider for the legacy router path; when no provider is passed, `llm_router` owns provider selection and fallback policy. The supervised overnight script ignores inherited generic `PROVIDER` values by default and leaves the daemon provider unset, so router auto-selection remains available for explicit `PROPOSAL_TRANSPORT=llm_router` or `hybrid` debugging. `ensure_logic_port_daemon.sh` uses `LOGIC_PORT_PROVIDER` for deliberate overrides; set `LOGIC_PORT_PROVIDER=codex_cli` only when deliberately forcing Codex-only debugging. The supervised worktree Codex subprocess uses `WORKTREE_CODEX_SANDBOX=danger-full-access` by default because the local read-only/workspace sandbox has repeatedly terminated before returning a proposal in this environment. The daemon disables local Hugging Face fallback by default, because autonomous code changes should fail closed if the configured route cannot reach the requested model. The daemon only applies model output through allowlisted worktree-harvested file replacements or `git apply`; it does not execute arbitrary commands returned by the model.

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

For the current CLI and supervised default, `--proposal-transport worktree` asks Codex to edit an ephemeral worktree instead of returning a patch. The daemon records Git's harvested diff as an audit artifact, but applies complete file replacements harvested from that worktree whenever possible. `--worktree-repair-attempts 1` keeps a failed-validation candidate in the worktree workflow: after tests fail, the daemon creates a repair worktree with the failed files already applied and asks Codex to repair that concrete state before the next main-worktree validation. Use `--proposal-transport llm_router` only for legacy JSON proposal debugging, or `--proposal-transport hybrid` to try worktree first and fall back to the router JSON path if the direct-edit proposal produces no usable changes.

## Supervised Continuous Mode

For unattended overnight runs, prefer the repository supervisor script. It starts the logic-port daemon against the outer TypeScript project root, requests `gpt-5.5` through `llm_router` with provider selection left on auto by default, uses 300 second operation timeouts, restarts the child immediately if it exits, revisits blocked tasks, and replenishes the TypeScript port plan when the normal backlog is exhausted. The supervisor defaults `SLICE_MODE=balanced`, so repeated TypeScript failures still force compileable proposals but no longer shrink every recovery round into the smallest possible scaffold:

```bash
nohup setsid -f bash ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh \
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

It is deliberately separate from `run_legal_parser_optimizer_daemon.sh`, which supervises the deterministic parser daemon and uses the parser implementation plans. Because the two daemons track different plans, the logic-port supervisor defaults `LOGIC_PORT_ALLOW_DURING_LEGAL_PARSER=1` and will keep working even when the parser daemon is active. The parser supervisor now defaults `SUPERVISOR_STOP_LOGIC_PORT_DAEMON=0`, so its competing-daemon cleanup does not stop logic-port work unless explicitly configured to do so. Set `LOGIC_PORT_ALLOW_DURING_LEGAL_PARSER=0` or `SUPERVISOR_STOP_LOGIC_PORT_DAEMON=1` only when you intentionally want parser work to have exclusive access to the repo.

The supervisor also has stale-heartbeat and stuck-phase watchdogs. `WATCHDOG_STALE_AFTER_SECONDS` defaults to `420`, which is intentionally longer than the default 300 second LLM and command timeouts. `WATCHDOG_STARTUP_GRACE_SECONDS` defaults to `120`, so a freshly started daemon has time to write its first heartbeat before the watchdog evaluates stale state from a previous run. `SUPERVISOR_PHASE_STUCK_GRACE_SECONDS` defaults to `90` and is recorded in the supervisor status as `phase_stuck_grace_seconds`. If the daemon heartbeat stops updating beyond the stale threshold, the supervisor terminates the daemon subprocess tree, records `last_recycle_reason: "stale_heartbeat"`, and immediately starts a fresh cycle. If the daemon heartbeat is still fresh but the active phase or descendant `codex exec` router call exceeds its timeout plus the stuck-phase grace, the supervisor records `last_recycle_reason: "agentic_stuck_repair"` and invokes bounded agentic maintenance with a `stuck_phase:*` or `stuck_llm_subprocess:*` reason before restarting. It also treats multiple concurrent descendant router `codex exec --ephemeral --json -` process groups as stuck evidence once the oldest duplicate group exceeds the phase-stuck grace, using a `duplicate_llm_subprocesses:*` reason, because that pattern usually means a prior LLM call leaked while the daemon began another attempt. Stuck-repair maintenance uses `SUPERVISOR_STUCK_MAINTENANCE_TIMEOUT_SECONDS`, default `360`, rather than the longer generic maintenance timeout; if that bounded repair times out, the supervisor records `last_agentic_maintenance_status: "timeout"`, restores the pre-maintenance daemon files, and immediately returns to the normal daemon cycle. Stop/restart cleanup sends `TERM` first and escalates to `KILL` after `STOP_GRACE_SECONDS`, which defaults to `10`. Startup, stop, and restart cleanup also sweep orphaned `logic_port_daemon` children that point at the same status file, abandoned repo-local `codex exec` router subprocesses for the configured model when they are no longer descendants of the active daemon, and orphaned repo-local agentic-maintenance Codex subprocesses left behind by a killed supervisor. The active child loop deliberately does not sweep router subprocesses, because some router providers detach helpers while the daemon is still waiting on them; it only treats over-timeout descendants or duplicate descendant router call process groups as stuck evidence for maintenance. Other daemon families are explicitly excluded from logic-port cleanup, including legal-parser descendants and `ppd/daemon/ppd_supervisor.py` or `ppd/daemon/ppd_daemon.py` descendants, even when they also run repo-local Codex subprocesses. When the supervisor has to clean up logic-port orphaned LLM calls, it records `last_orphaned_llm_cleanup_count` and triggers an infrastructure maintenance pass with an `orphaned_llm_calls:*` reason so the daemon/supervisor can automatically patch the root cause instead of requiring manual intervention. A nonblocking `flock` on `logic-port-daemon-supervisor.lock` prevents two supervisors from running at once even if a stale PID file is present.

For a belt-and-suspenders watchdog outside the supervisor itself, run `ensure_logic_port_daemon.sh` periodically from cron or systemd. The script is idempotent: when the daemon is healthy it only records `already_running`; when the health check fails it starts the supervisor with `nohup setsid -f` by default. Set `ENSURE_LAUNCH_MODE=tmux` to use a named detached `tmux` wrapper that restarts the supervisor process every five seconds if it exits. Because startup agentic maintenance can run before the daemon child writes its first heartbeat, `ensure` treats a live detached supervisor as a successful start and records `supervisor_started_waiting_for_daemon` until the child health check becomes green. The supervisor lock keeps repeated ensure calls from creating duplicate supervisors.

`check_logic_port_daemon.sh` treats an active supervisor maintenance window as healthy even when the daemon child is temporarily stopped, but only until the maintenance timeout plus a short grace expires. The supervisor records `active_agentic_maintenance_started_at` and `active_agentic_maintenance_timeout_seconds` while the maintenance process is running so the health check can distinguish a bounded self-repair from a stalled supervisor. Duplicate descendant router-process repair uses the same stuck-maintenance timeout fallback as stuck phases and stuck LLM subprocesses. This keeps `ensure_logic_port_daemon.sh` from spawning duplicate supervisors while the current supervisor is already repairing a stuck daemon, while still surfacing timed-out maintenance as unhealthy.

The supervisor can also run a bounded Codex maintenance pass when the daemon is alive but not making meaningful progress or when the supervisor itself detects infrastructure drift. `SUPERVISOR_AGENTIC_MAINTENANCE` defaults to `1`; set it to `0` to disable this behavior. Generic maintenance uses `SUPERVISOR_AGENTIC_TIMEOUT_SECONDS`, default `300`, and stuck-phase repair uses `SUPERVISOR_STUCK_MAINTENANCE_TIMEOUT_SECONDS`, default `360`, so a bad self-repair attempt times out and the supervisor immediately starts the next daemon cycle instead of sleeping or waiting indefinitely. `SUPERVISOR_AGENTIC_STARTUP_MAINTENANCE` defaults to `0`, so stale historical failure counters cannot prevent a restarted supervisor from launching a daemon child; set it to `1` only when you deliberately want maintenance before the first child starts. When startup maintenance is disabled, any persisted startup trigger is recorded as the cooldown baseline so the first live child gets a real chance to complete a new round before maintenance can interrupt it. Maintenance triggers when the current task reaches `SUPERVISOR_AGENTIC_TASK_FAILURES` failures since its last success, when `SUPERVISOR_AGENTIC_STAGNANT_ROUNDS` rounds elapse without a new accepted round, when `SUPERVISOR_AGENTIC_PROPOSAL_FAILURES` recent rounds produce no usable JSON/patch/file changes, when `SUPERVISOR_AGENTIC_TYPESCRIPT_QUALITY_FAILURES` recent rounds hit TypeScript parser/generic/type-quality failures with no accepted changed files, when `SUPERVISOR_AGENTIC_ROLLBACK_FAILURES` recent rounds fail as rollback-quality failures with no accepted changed files, or when repo-local orphaned router subprocesses prove that the daemon/supervisor cleanup path needs hardening. Rollback-quality failures include malformed patch apply-check failures, validation, validation-repair, file-repair-validation, and preflight loops. TypeScript quality failures include TS1005/TS1128-style parser failures plus TS2314/TS2322 generic and assignability failures, as well as common repair-loop diagnostics such as TS2339, TS2345, TS2365, and TS7006. Proposal-quality failures include parse, empty-proposal, invalid-no-change, and no-change loops. The supervisor stops the child daemon, invokes `codex exec` with `gpt-5.5` against only the daemon/supervisor/docs/tests allowlist, runs shell syntax checks plus the daemon unit tests, records the result under `logic-port-daemon-agentic-maintenance_*.log`, and restarts the daemon. Maintenance validation now requires the non-logic-daemon exclusion helper to remain present in both run and stop wrappers, so self-repair cannot accidentally drop the guard that protects the legal-parser and PPD daemon families. Maintenance prompts explicitly ask for infrastructure improvements that make future unattended rounds recover without user input while preserving `llm_router` as the default provider-routing authority, and they forbid running stop/start wrapper scripts or sending signals to daemon processes during maintenance. `SUPERVISOR_AGENTIC_SANDBOX` defaults to `danger-full-access` because the local Codex workspace sandbox can fail before commands run with bubblewrap loopback errors; normal porting work still routes through `llm_router` with the provider left unset unless `LOGIC_PORT_PROVIDER` explicitly pins one. The supervisor also treats sandbox-failure text in a maintenance transcript as a failed maintenance pass even when Codex exits with code 0.
If maintenance itself fails validation or times out, the supervisor records that failed self-repair as a synthetic daemon result with `supervisor_maintenance_failed` or `supervisor_maintenance_timeout`. It also marks the current checkbox in `docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md` as blocked when possible. That gives the daemon's normal task budget and blocked-task revisit rules concrete evidence to move past a poisoned task after a failed repair instead of repeatedly re-entering the same stuck loop.
When maintenance starts, the supervisor records the current progress counters as the new stagnant-round baseline before restarting the daemon. This prevents the same historical no-progress window from retriggering maintenance after the cooldown unless additional rounds complete without accepted work.
The cooldown is scoped by maintenance reason family and current task, so a previous stagnant-round maintenance pass does not suppress a later rollback-quality maintenance pass, and a TypeScript-quality maintenance pass for one checkbox does not suppress a later TypeScript-quality maintenance pass for a different checkbox.

```bash
PYTHONPATH=ipfs_datasets_py python3 -m ipfs_datasets_py.optimizers.logic_port_daemon \
  --repo-root . \
  --slice-mode balanced \
  --proposal-transport worktree \
  --worktree-edit-timeout-seconds 300 \
  --worktree-stale-after-seconds 7200 \
  --worktree-repair-attempts 1 \
  --apply \
  --watch \
  --retry-interval 0 \
  --llm-timeout 300 \
  --command-timeout 300 \
  --heartbeat-interval 30 \
  --max-task-failures 4 \
  --proposal-attempts 3 \
  --file-repair-attempts 1 \
  --preflight-repair-attempts 1 \
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

Continuous mode runs without user input. In worktree transport, each proposal gets a bounded Codex direct-edit window controlled by `--worktree-edit-timeout-seconds 300`; failed or empty worktree edits are recorded as structured failures and the next cycle starts immediately by default. Time is bounded by operation timeouts, not by a fixed retry sleep: use `--llm-timeout 300`, `--command-timeout 300`, and `--worktree-edit-timeout-seconds 300` to cap individual router, validation/git, and direct-edit calls. When a proposal becomes usable, the daemon applies only allowlisted TypeScript/docs changes, validates them, repairs failed validation once in a fresh temporary worktree by default, and updates the port-plan task board only after accepted work.

If a proposed patch fails `git apply --check`, the daemon stores the failed patch under `ipfs_datasets_py/.daemon/failed-patches/` and performs one automatic `gpt-5.5` repair attempt with the exact Git error before giving up on that cycle.

If the repaired diff is still malformed, the daemon performs one more repair path: it asks `gpt-5.5` to convert the same intended change into complete allowlisted file replacements. This is important for unattended runs because malformed diff hunks were the most common cause of "busy but no files changed" cycles.

The daemon also retries unusable proposals inside a cycle. If the model returns no JSON, an empty change, or refuses because the Codex subprocess is read-only, the next proposal attempt explicitly reminds it that the daemon applies returned JSON `files` replacements after validation. Empty proposals receive `failure_kind: "empty_proposal"` and parse failures receive `failure_kind: "parse"`, so repeated unproductive rounds can block the current task and advance the task board instead of spinning forever.

The daemon can also recover JSON proposals from Codex JSONL event streams. If the router returns raw `thread.started` / `turn.started` / `item.completed` events instead of only the final assistant text, the parser searches assistant message events for the JSON proposal before classifying the response as a parse failure. If Codex exits after startup events without any assistant proposal, the round is marked `codex_empty_event_stream` so the supervisor can treat it as proposal-quality stagnation instead of a mysterious parse failure. The prompt asks Codex not to run exploratory shell commands and uses a focused excerpt around the daemon-selected checkbox from `docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md`; this keeps the selected task visible even after the task board and test surface grow.

`--max-prompt-chars` controls the prompt budget for each LLM call and defaults to `32000`. The supervisor exposes the same setting through `MAX_PROMPT_CHARS`, also defaulting to `32000`. The task board is still the authoritative ledger, but only a compact excerpt centered on the selected task is embedded in each round.

File replacement proposals now also get a cheap TypeScript replacement preflight during the proposal-attempt loop. If a replacement contains syntax errors such as Python-style object syntax or truncated declarations, or targeted generic/type-quality errors such as missing `Record`/`Promise`/`Omit` type arguments, missing comparison operators in loops, and `unknown` assignability mistakes, the daemon first performs one targeted preflight-repair call with the exact diagnostics and original file replacements. If the repair still fails, the daemon rejects that proposal before touching the worktree and feeds the diagnostics into the next proposal attempt. This avoids spending a full validation/rollback cycle on files that cannot pass basic TypeScript checks, while giving obvious one-pass TypeScript damage a chance to recover inside the same cycle.
The same preflight path also applies a small deterministic cleanup pass for recurring transport/model text damage, including stripped generic arguments and stripped loop/comparison operators such as `index  input.length`. These repairs are intentionally narrow; proposals that still fail TypeScript preflight are classified by their diagnostics rather than by the raw repair stage that discovered them.

When complete file replacements apply but fail validation, the daemon now performs one validation-repair attempt before waiting for the next cycle. The repair prompt includes the failed validation output and the attempted file contents, asks for corrected complete file replacements, and reruns the normal validation/rollback flow.

Validation repair is adaptive. After a task accumulates `--validation-repair-failure-budget` validation-repair failures since its last accepted round, the daemon skips additional validation-repair LLM calls for that task and lets the normal task-failure threshold block or advance it faster. This keeps unattended runs moving when a task repeatedly produces malformed TypeScript repairs.

Each proposal prompt includes recent failure context for the selected task plus current contents for likely target files selected from the tracked TypeScript logic tree. This keeps complete-file replacements grounded in the actual code instead of asking the model to infer file shape from filenames alone.

The prompt intentionally asks for one narrow requirement per cycle, at most 180 changed diff lines, and usually one implementation file plus one focused test. It now prefers exact `files` replacements over unified diffs for TypeScript/doc edits. File replacements are path-allowlisted, formatted with Prettier for TypeScript files, and rolled back automatically if validation fails, which keeps overnight runs biased toward changes that can be applied and validated unattended.

Runtime TypeScript changes under `src/lib/logic/` are now enforced as complete JSON `files` replacements when file-edit mode is enabled. If a model returns only a unified diff for runtime logic, the daemon rejects it during proposal preflight and retries with feedback before reaching `git apply`. This prevents malformed diff cycles from consuming an entire round when the same change can be represented as auditable file contents.

The daemon writes a heartbeat/status file while running:

- `ipfs_datasets_py/.daemon/logic-port-daemon.status.json`

That file records the daemon PID, timestamp, current state, selected task, latest result, changed files, and failure kind. Non-heartbeat states also include `state_started_at`. While a cycle is active, a background heartbeat rewrites the file with `state: "heartbeat"`, the `active_state` it is waiting on, and `active_state_started_at`, so a fresh timestamp means the daemon is alive even if the current Codex call has not returned yet. The supervisor uses the phase start timestamp to distinguish a healthy long-running call from a stuck over-timeout call that should trigger maintenance.

The daemon also writes a progress summary:

- `ipfs_datasets_py/.daemon/logic-port-daemon.progress.json`

That file records total rounds, valid rounds, acceptance rate, current task, current-task failure counts, active state, plan status counts, failure-kind counts, the latest round, recent failures, and recent accepted changed files. It is written at cycle start, on heartbeat, and after each completed round, so it appears immediately after daemon startup instead of only after the first LLM call returns. Provider/Cloudflare HTML failures are compacted and classified, keeping the progress file readable even when Codex emits long HTTP error pages.
It also records `stagnant_rounds_since_valid`, which is the daemon-side count of completed work rounds since the latest accepted round, and `typescript_quality_failures`, which counts recent no-change TypeScript parser/generic/assignability failures for supervisor diagnostics. The supervisor uses a persisted baseline for its own maintenance trigger, but this field makes the current no-progress streak visible in health checks and logs.
`typescript_quality_failures` also includes stable diagnostic signatures, so repeated loops like bare `Record`/`Promise`/`Omit` generics or malformed comparison operators can trigger supervisor maintenance as a specific repeated-diagnostic problem instead of being buried inside generic validation failures.
The progress file also records `rollback_quality_failures`, with total, consecutive, by-task, and by-kind counters for apply-check, preflight, validation, validation-repair, file-repair-validation, and TypeScript-quality rollback loops. Task blocking and task-board summaries use the normalized diagnostic classification, so a task that alternates between raw `preflight` and `validation_repair` stages for the same malformed TypeScript pattern can still hit the same-kind failure threshold and advance the unattended run.
The supervisor treats rollback-quality streaks that span multiple tasks differently from same-task rollback loops. If a consecutive rollback streak is produced by the daemon blocking one task and starting another, the supervisor lets the current task reach its own blocking budget instead of immediately launching maintenance from a cross-task aggregate. Same-task rollback streaks still trigger maintenance at the configured rollback threshold.
Before running full TypeScript preflight, the daemon now performs a deterministic scan for obvious proposal damage such as stripped comparison operators (`index  items.length`, `arity  'Entity'`) and bare generic aliases. These are rejected with targeted retry feedback before any worktree edit, which keeps malformed complete-file replacements from consuming validation/rollback cycles.
Task failure accounting normalizes markdown-only task label differences, such as backticks around Python module paths, before comparing daemon JSONL results to the plan. This keeps malformed proposals from resetting the per-task failure budget just because the model echoed the task title without markdown punctuation. Blocked-task revisit also treats repeated same-kind failures and rollback-quality failures as budget exhaustion, not only total failures. That prevents unattended runs from repeatedly revisiting blocked tasks that have already produced the same TypeScript preflight or rollback loop while fresher blocked tasks remain available.
When several rollback-quality rounds happen consecutively, the next prompt enters unattended rollback recovery mode. That mode asks for a smaller compileable scaffold, preserves existing module exports, and explicitly self-checks for stripped TypeScript operators or bare generics before the model returns JSON. The daemon also applies low-risk text repairs for recurring stripped comparison operators and string-array generic damage before TypeScript replacement preflight.

The daemon blocks the current task after repeated failures in two ways: `--max-task-failures` counts total failures for the task since its last accepted round, while `max_task_failure_rounds` still guards repeated same-kind failures. This prevents a task from spinning forever by alternating between parse, patch, and validation failures.

At the beginning of each supervised cycle, the daemon also checks historical JSONL results before calling the LLM. If the selected task already exceeds the total-failure threshold, it marks that task blocked and advances immediately, avoiding one more wasted Codex call on work that is already known to be stuck.

If every parsed port-plan task is already `[x]` complete or `[!]` blocked, the daemon does not call `llm_router` with an empty target. Without replenishment it writes a terminal `no_eligible_tasks` result to the JSONL log, status file, progress summary, and generated task board. That keeps overnight runs bounded by the plan instead of spending Codex calls on an empty target.

By default, continuous mode now tries to replenish the TypeScript port plan before taking that terminal stop. If no eligible tasks remain, it first scans the current Python logic inventory and TypeScript logic implementation state. When obvious module or capability-marker gaps are exhausted, it then reviews the original browser-native TypeScript/WASM parity goal against accepted-work evidence, progress logs, Python ML/spaCy expectations, public API coverage, and no-server-runtime validation needs. It appends a `Daemon-Discovered Implementation Gaps` section to `docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md`, refreshes the generated task board, and immediately continues with the newly added task. Use `--plan-replenishment-limit` to bound how many tasks are added in one pass, or `--no-plan-replenishment` to keep the old fail-closed behavior.

Use `--revisit-blocked-tasks` when the normal backlog is exhausted and you intentionally want the daemon to work through blocked tasks again. In that mode, selection still prefers `[ ]` and `[~]` tasks first; only when none remain does it select `[!]` tasks. The stale-failure pre-cycle blocker is disabled for this mode so historical failures do not immediately re-block the task before the new attempt. A successful round marks the blocked source checkbox `[x]`; a failed round leaves it blocked and records the latest failure evidence.

Blocked-task revisit mode has a small dependency gate for cleanup tasks. It will not select a task that removes `nlpUnavailable` or `mlUnavailable` capability flags while browser-native ML/NLP prerequisite tasks are still unfinished or while those markers still exist in runtime TypeScript files under `src/lib/logic`. Test-only assertions are ignored by this gate so the eventual cleanup task can update its own tests. If every remaining blocked task is dependency-gated, the daemon treats the plan as having no eligible target and falls back to goal review and plan replenishment instead of spending a cycle on impossible cleanup.

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
- a `.diff` audit snapshot from `git diff -- <changed files>`;
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
  --slice-mode balanced \
  --apply \
  --watch \
  --retry-interval 0 \
  --llm-timeout 300 \
  --command-timeout 300 \
  --heartbeat-interval 30 \
  --max-task-failures 4 \
  --proposal-attempts 3 \
  --file-repair-attempts 1 \
  --preflight-repair-attempts 1 \
  --validation-repair-attempts 1 \
  --status-file ipfs_datasets_py/.daemon/logic-port-daemon.status.json \
  --progress-file ipfs_datasets_py/.daemon/logic-port-daemon.progress.json \
  --log-file ipfs_datasets_py/.daemon/logic-port-daemon.jsonl
```

## Runtime Boundary

This daemon is optimizer/development tooling. It must not be imported by the browser runtime and must not change the TypeScript logic port into a Python-service wrapper. The implementation target remains local TypeScript/WASM parity.
