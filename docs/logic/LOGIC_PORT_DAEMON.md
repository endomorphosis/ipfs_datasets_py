# Logic Port Daemon

`ipfs_datasets_py.optimizers.logic_port_daemon` is development tooling for iteratively improving the browser-native TypeScript/WASM port of the Python logic module.

It reads:

- `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md`
- `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md`
- the outer TypeScript port status docs when run from the Portland site repository

It then calls `ipfs_datasets_py.llm_router.generate_text()` with `model_name="gpt-5.5"` and asks for a conservative unified diff patch. GPT-family models are pinned to the router's `codex_cli` provider unless `--provider` is supplied, so the request flows through `codex exec` rather than local Hugging Face fallback. The daemon disables local Hugging Face fallback by default, because autonomous code changes should fail closed if the configured router cannot reach the requested model. The daemon only applies model output through `git apply`; it does not execute arbitrary commands returned by the model.

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
  --retry-interval 300 \
  --log-file ipfs_datasets_py/.daemon/logic-port-daemon.jsonl
```

Continuous mode runs without user input. If the configured `gpt-5.5` route is unavailable, it records a structured failure, sleeps, and retries. When the route becomes available, it resumes patch generation, applies only patches that pass `git apply --check`, and then runs validation.

If a proposed patch fails `git apply --check`, the daemon stores the failed patch under `ipfs_datasets_py/.daemon/failed-patches/` and performs one automatic `gpt-5.5` repair attempt with the exact Git error before giving up on that cycle.

The prompt intentionally asks for one narrow requirement per cycle, at most 180 changed diff lines, and usually one implementation file plus one focused test. This keeps overnight runs biased toward patches that can be applied and validated unattended.

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
  --retry-interval 300 \
  --log-file ipfs_datasets_py/.daemon/logic-port-daemon.jsonl
```

## Runtime Boundary

This daemon is optimizer/development tooling. It must not be imported by the browser runtime and must not change the TypeScript logic port into a Python-service wrapper. The implementation target remains local TypeScript/WASM parity.
