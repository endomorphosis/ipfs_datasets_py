# Legal Corpora Reindex Supervisor Operations

This directory operates the sealed four-lane `LCR-` board. Run it only from the clean `feature/legal-corpora-reindex` worktree bound by the scheduler config. The runtime namespace is `workspace/agent-supervisor/legal-corpora-reindex/`; it is Git-ignored and must not be shared with another board.

Set `IPFS_ACCELERATE_ROOT` to the clean `ipfs_accelerate_py` checkout containing the current configured-board scheduler. In the paired worktree layout it defaults to `../ipfs_accelerate_py`.

The board binds authoritative validation to `/usr/bin/python3.12 -S` and the single sealed package root `/opt/ipfs-accelerate-legal-validation-7ffe92439767/site-packages`. Its root-owned `DEPLOYMENT.json` has SHA-256 `654d64e130c9b8e748ea76c3947eb47cc52bea64adb40f2592f7204dfe503ad0` and binds `PAYLOAD_MANIFEST.jsonl` SHA-256 `7ffe92439767e99c849a4f7aad0ee5d64e19ab9f754b5f0915f00571ac51f85a`. Browser validation is separately bound through `PLAYWRIGHT_BROWSERS_PATH=/opt/ipfs-accelerate-legal-playwright-3c176393527b`; that deployment's receipt is SHA-256 `8b497a041d80cf64b4b792c0b9dee34970cdf0202b7801db7577540de4daea3f` and its manifest is SHA-256 `3c176393527b23c59dbf859e86626b32abcca006535679cbc27e69c3b09e7a78`.

The controller's DuckDB deployment remains a distinct control-plane dependency. `/opt/ipfs-accelerate-controller-duckdb-3781192a-1.5.2/site-packages` contains the DuckDB-only 1.5.2 Python/native payload extracted from pinned local image `sha256:3781192ac3d81754e0b97d655a314f653f0e2c19f8707e07cc8a36bc59374405` and cross-checked against cached wheel SHA-256 `ce0b8141a10d37ecef729c45bc41d334854013f4389f1488bd6035c5579aaac1`; its root-owned receipt is SHA-256 `8e3fb57e753b6c77c7608e7f54155436521d082e735c54e0cd66924cef4b31b8`. The paired wrappers admit that root only for the controller after attesting both repository roots. It is not appended to the authoritative validation `PYTHONPATH`.

Preflight verifies both validation deployment receipt hashes, schemas, passed verification fields, manifest hashes, manifest inventories, canonical paths, root ownership, read-only modes, and the absence of symlinks, hard links, and other nonregular objects. It then uses the daemon's sealed launcher and launch-projected environment to import the exact 42-module contract: `aiohttp`, `anyio`, `bs4`, `cachetools`, `cryptography`, `datasets`, `duckdb`, `faiss`, `fsspec`, `httpx`, `huggingface_hub`, `hypothesis`, `jsonschema`, `multiformats`, `networkx`, `numpy`, `pandas`, `playwright`, `pyarrow`, `pydantic`, `pydantic_settings`, `pypdf`, `PyPDF2`, `pytest`, `pytest_asyncio`, `pytest_benchmark`, `pytest_cov`, `pytest_mock`, `pytest_parallel`, `pytest_timeout`, `xdist`, `yaml`, `rdflib`, `requests`, `sklearn`, `scipy`, `sentence_transformers`, `torch`, `tqdm`, `transformers`, `trio`, and `urllib3`. User sites, system `dist-packages`, implicit pytest plugin autoload, bytecode writes, and dependency auto-install are excluded from authoritative validation.

## Validate and render

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
ACCELERATOR_ROOT="${IPFS_ACCELERATE_ROOT:-$(cd "$REPO_ROOT/../ipfs_accelerate_py" && pwd)}"
export PYTHONPATH="$ACCELERATOR_ROOT${PYTHONPATH:+:$PYTHONPATH}"

/usr/bin/python3.12 -I -S -B scripts/ops/legal_corpora_reindex/preflight.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_legal_corpora_reindex_scheduler.json \
  --json

/usr/bin/python3.12 -I -S -B scripts/ops/agent_supervisor/configured_board_scheduler.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_legal_corpora_reindex_scheduler.json \
  launch --implement --dry-run
```

The preflight rejects dirty or wrong-branch control planes, missing tracked files, invalid boards, non-ignored runtime paths, Git operations in progress, provider contract drift, and any existing process or stale artifact using the exact namespace. It never deletes or kills anything.

## Launch

```bash
/usr/bin/python3.12 -I -S -B scripts/ops/agent_supervisor/configured_board_scheduler.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_legal_corpora_reindex_scheduler.json \
  launch --implement
```

The default launch detaches. It uses four strict full-task-ID SHA-256 lanes, a serialized merge queue, bounded retries and refills, Grok `grok-4.5` as primary, and Codex `gpt-5.6-terra` only when the supervisor verifies primary quota exhaustion. Secrets come only from the inherited environment.

## Verify health

```bash
scripts/ops/legal_corpora_reindex/status.sh
scripts/ops/legal_corpora_reindex/status.sh --json --observe-seconds 20
```

Exit status is zero only for `starting`, `healthy`, or cryptographically/current-board-proven `completed`. Health requires exact process identity and ownership, fresh supervisor heartbeats, no duplicate/orphan process, no protected-path incident, no blocked work, bounded active worker/log age even when a worker PID remains live, and no ready-without-worker stall. Host-native workers are bound by process ancestry; isolated Grok/Codex workers behind a container shim are bound to the exact active task worktree recorded by the lane. The observed form takes two samples and rejects healthy lanes whose heartbeat and durable progress both remain unchanged.

Do not infer health from a PID alone. Do not manually start another copy when preflight reports an existing namespace. Reconcile incidents from the state/log receipts before any cleanup, and never delete a runtime tree while a matching process is live.

## Publication boundary

The operator's 2026-08-10 request authorizes additive publication to exactly `justicedao/ipfs_state_laws` and `justicedao/ipfs_federal_register`. Each production task must first create a manifest-bound authorization receipt, pass a live immutable staging redownload/canary, preserve the prior public pin, and use cached/environment credentials without exposing them. The authorization does not permit deletion, force-push, history rewrite, visibility change, credential changes, or publication to any other repository.
