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

```bash
PYTHONPATH=ipfs_datasets_py python3 -m ipfs_datasets_py.optimizers.logic_port_daemon \
  --repo-root . \
  --apply \
  --watch \
  --retry-interval 0 \
  --llm-timeout 300 \
  --command-timeout 300 \
  --heartbeat-interval 30 \
  --max-task-failures 6 \
  --proposal-attempts 3 \
  --file-repair-attempts 1 \
  --validation-repair-attempts 1 \
  --status-file ipfs_datasets_py/.daemon/logic-port-daemon.status.json \
  --progress-file ipfs_datasets_py/.daemon/logic-port-daemon.progress.json \
  --log-file ipfs_datasets_py/.daemon/logic-port-daemon.jsonl
```

Continuous mode runs without user input. If the configured `gpt-5.5` route is unavailable, it records a structured failure and starts the next cycle immediately by default. Time is bounded by operation timeouts, not by a fixed retry sleep: use `--llm-timeout 300` and `--command-timeout 300` to cap individual LLM and validation/git calls. When the route becomes available, it resumes patch generation, applies only patches that pass `git apply --check`, and then runs validation.

If a proposed patch fails `git apply --check`, the daemon stores the failed patch under `ipfs_datasets_py/.daemon/failed-patches/` and performs one automatic `gpt-5.5` repair attempt with the exact Git error before giving up on that cycle.

If the repaired diff is still malformed, the daemon performs one more repair path: it asks `gpt-5.5` to convert the same intended change into complete allowlisted file replacements. This is important for unattended runs because malformed diff hunks were the most common cause of "busy but no files changed" cycles.

The daemon also retries unusable proposals inside a cycle. If the model returns no JSON, an empty change, or refuses because the Codex subprocess is read-only, the next proposal attempt explicitly reminds it that the daemon applies returned JSON `files` replacements after validation. Empty proposals receive `failure_kind: "empty_proposal"` and parse failures receive `failure_kind: "parse"`, so repeated unproductive rounds can block the current task and advance the task board instead of spinning forever.

When complete file replacements apply but fail validation, the daemon now performs one validation-repair attempt before waiting for the next cycle. The repair prompt includes the failed validation output and the attempted file contents, asks for corrected complete file replacements, and reruns the normal validation/rollback flow.

Each proposal prompt includes recent failure context for the selected task plus current contents for likely target files selected from the tracked TypeScript logic tree. This keeps complete-file replacements grounded in the actual code instead of asking the model to infer file shape from filenames alone.

The prompt intentionally asks for one narrow requirement per cycle, at most 180 changed diff lines, and usually one implementation file plus one focused test. It now prefers exact `files` replacements over unified diffs for TypeScript/doc edits. File replacements are path-allowlisted, formatted with Prettier for TypeScript files, and rolled back automatically if validation fails, which keeps overnight runs biased toward changes that can be applied and validated unattended.

The daemon writes a heartbeat/status file while running:

- `ipfs_datasets_py/.daemon/logic-port-daemon.status.json`

That file records the daemon PID, timestamp, current state, selected task, latest result, changed files, and failure kind. While a cycle is active, a background heartbeat rewrites the file with `state: "heartbeat"` and the `active_state` it is waiting on, so a fresh timestamp means the daemon is alive even if the current Codex call has not returned yet. Use it with the JSONL result log to distinguish a crashed daemon from an active daemon that is waiting on Codex or validation.

The daemon also writes a progress summary:

- `ipfs_datasets_py/.daemon/logic-port-daemon.progress.json`

That file records total rounds, valid rounds, acceptance rate, current task, current-task failure counts, active state, plan status counts, failure-kind counts, the latest round, recent failures, and recent accepted changed files. It is written at cycle start, on heartbeat, and after each completed round, so it appears immediately after daemon startup instead of only after the first LLM call returns. Provider/Cloudflare HTML failures are compacted and classified, keeping the progress file readable even when Codex emits long HTTP error pages.

The daemon blocks the current task after repeated failures in two ways: `--max-task-failures` counts total failures for the task since its last accepted round, while `max_task_failure_rounds` still guards repeated same-kind failures. This prevents a task from spinning forever by alternating between parse, patch, and validation failures.

The daemon also encodes local test-harness conventions. Logic tests run under Jest with global `describe`/`it`/`expect`, so proposals importing `vitest` or `@jest/globals` are rejected before any files are written. This avoids failed autonomous cycles that create valid-looking tests for the wrong runner.

## Markdown Task Tracking

The TypeScript port plan is the daemon's task ledger. By default this daemon maintains a generated `Daemon Task Board` inside `docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md`. The nested deterministic parser implementation plan is intentionally left for the parser-specific daemon.

On each daemon round it:

- parses Markdown task checkboxes from the porting plan;
- treats `[x]` as complete, `[ ]` as needed, `[~]` as in progress, and `[!]` as blocked;
- selects the first task that is not complete and injects that task into the next LLM prompt;
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
  --max-task-failures 6 \
  --proposal-attempts 3 \
  --file-repair-attempts 1 \
  --validation-repair-attempts 1 \
  --status-file ipfs_datasets_py/.daemon/logic-port-daemon.status.json \
  --progress-file ipfs_datasets_py/.daemon/logic-port-daemon.progress.json \
  --log-file ipfs_datasets_py/.daemon/logic-port-daemon.jsonl
```

## Runtime Boundary

This daemon is optimizer/development tooling. It must not be imported by the browser runtime and must not change the TypeScript logic port into a Python-service wrapper. The implementation target remains local TypeScript/WASM parity.
