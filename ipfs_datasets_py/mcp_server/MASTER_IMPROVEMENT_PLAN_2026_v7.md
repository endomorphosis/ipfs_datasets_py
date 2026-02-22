# MCP Server — Master Improvement Plan v7.0

**Date:** 2026-02-22 (session 45)
**Status:** 🟢 **Active** — Phases M, N, O in progress
**Preconditions:** All v4, v5 A-F, and v6 G-L phases ✅ complete
**Branch:** `copilot/create-improvement-refactoring-plan`
**Previous Plans:** [v6](MASTER_IMPROVEMENT_PLAN_2026_v6.md) · [v5](MASTER_IMPROVEMENT_PLAN_2026_v5.md) · [v4](MASTER_REFACTORING_PLAN_2026_v4.md)

---

## TL;DR

All prior refactoring (v4) and improvement (v5 A-F, v6 G-L) phases are complete as of
session 44.  This v7 plan is driven by two new architectural constraints identified
in session 45:

1. **Use anyio everywhere instead of asyncio** — No `import asyncio` or `asyncio.*`
   calls in production code; use anyio APIs throughout.
2. **No Flask servers** — All tool access must go through the MCP+P2P server, the
   `ipfs-datasets` CLI, or `ipfs_datasets_py` package imports.  Flask is not an
   approved HTTP layer for this project.

**Current baseline (2026-02-22, session 44):**
- **1816 tests passing** · 0 failing
- All root-level mcp_server modules covered at 80%+
- `simple_server.py` and `standalone_server.py` using Flask (deprecated as of session 45)
- `executor.py` had misleading "asyncio" comments (fixed in session 45)
- `README.md` and `DUAL_RUNTIME_ARCHITECTURE.md` had `asyncio.run()` examples (fixed)

---

## Table of Contents

1. [Architectural Constraints](#1-architectural-constraints)
2. [Session 45 Completed Work](#2-session-45-completed-work)
3. [Phase M: Flask Removal](#3-phase-m-flask-removal)
4. [Phase N: anyio Migration Validation](#4-phase-n-anyio-migration-validation)
5. [Phase O: Docker Image Refresh](#5-phase-o-docker-image-refresh)
6. [Success Metrics](#6-success-metrics)

---

## 1. Architectural Constraints

### 1.1 anyio Instead of asyncio

The project uses **anyio** as its async abstraction layer to support both the
asyncio and trio backends.  No production code should directly import `asyncio`
or call `asyncio.*` functions.  Instead:

| asyncio API | anyio equivalent |
|---|---|
| `asyncio.run(coro)` | `anyio.run(coro)` |
| `asyncio.sleep(n)` | `await anyio.sleep(n)` |
| `asyncio.gather(*coros)` | `anyio_compat.gather(coros)` |
| `asyncio.get_event_loop().run_in_executor(…)` | `await anyio.to_thread.run_sync(fn)` |
| `asyncio.Queue` | `anyio.create_memory_object_stream()` |
| `asyncio.Lock` | `anyio.Lock()` |
| `asyncio.Event` | `anyio.Event()` |
| `asyncio.Semaphore(n)` | `anyio.Semaphore(n)` |
| `asyncio.wait_for(coro, t)` | `with anyio.fail_after(t): await coro` |
| `asyncio.create_task(coro)` | Nursery: `nursery.start_soon(coro)` |

### 1.2 No Flask Servers

All tool and data access must go through:

1. **MCP stdio server** (recommended — for VS Code / AI assistants):
   ```bash
   python -m ipfs_datasets_py.mcp_server
   ```
2. **`ipfs-datasets` CLI** (for shell users):
   ```bash
   ipfs-datasets <command>
   ```
3. **Python package imports** (for programmatic use):
   ```python
   from ipfs_datasets_py import DatasetManager
   ```

If HTTP access is required (e.g. Docker health checks), use the **FastAPI service
layer** (`ipfs_datasets_py.mcp_server.fastapi_service`) which is built on
anyio/uvicorn — not Flask.

---

## 2. Session 45 Completed Work

### 2.1 Flask Deprecation Warnings Added ✅

| File | Change |
|------|--------|
| `simple_server.py` | Hard `from flask import …` moved to conditional try/except; `DeprecationWarning` added to `SimpleIPFSDatasetsMCPServer.__init__()` and `start_simple_server()`; module docstring updated with migration guide |
| `standalone_server.py` | `DeprecationWarning` added to `MinimalMCPServer.__init__()`, `MinimalMCPDashboard.__init__()`, and `main()` |
| `__main__.py` | `--http` mode now emits `DeprecationWarning` and prints migration guidance; **Flask fallback removed** (the fallback that imported `SimpleIPFSDatasetsMCPServer` is gone) |

### 2.2 asyncio References Fixed ✅

| File | Change |
|------|--------|
| `mcplusplus/executor.py` | 3 comments "Fallback to asyncio" → "anyio fallback (works with asyncio and trio backends)" |
| `README.md` | 2 code examples: `import asyncio` + `asyncio.run(main())` → `import anyio` + `anyio.run(main)` |
| `docs/architecture/DUAL_RUNTIME_ARCHITECTURE.md` | Code example: `import asyncio` / `asyncio.get_event_loop()` → `import anyio` / `anyio.to_thread.run_sync()` |

### 2.3 Tests Added ✅

`tests/mcp/unit/test_deprecation_session45.py` — 16 tests:
- `simple_server.SimpleIPFSDatasetsMCPServer` emits `DeprecationWarning`
- `simple_server.start_simple_server()` emits `DeprecationWarning`
- `standalone_server.MinimalMCPServer` emits `DeprecationWarning`
- `standalone_server.MinimalMCPDashboard` emits `DeprecationWarning`
- `standalone_server.main()` emits `DeprecationWarning`
- Flask-absent path: `SimpleIPFSDatasetsMCPServer` raises `ImportError` with helpful message
- `executor.py` comments contain "anyio" (no "asyncio" in non-comment code)
- `README.md` no longer contains `asyncio.run(` in code blocks
- `DUAL_RUNTIME_ARCHITECTURE.md` no longer contains `asyncio.get_event_loop()`

---

## 3. Session 46 Completed Work ✅

### 3.1 Phase N2 — CI Check for asyncio Regressions ✅

`tests/mcp/unit/test_no_asyncio_session46.py` — 4 tests (AST-based, no execution needed):
- `test_no_asyncio_imports_in_mcp_server_production_code` — scans every `.py` in mcp_server
- `test_mcp_root_exists` — sanity check for path configuration
- `test_at_least_one_py_file_scanned` — guards against misconfigured root path
- `test_anyio_present_in_mcp_server` — confirms anyio is actually used

### 3.2 Phase N3 — Documentation asyncio→anyio ✅

| File | Lines changed |
|------|---------------|
| `tools/legal_dataset_tools/PLAYWRIGHT_SETUP.md` | `import asyncio` × 2 → `import anyio`; `asyncio.run(verify())` → `anyio.run(verify)`; `asyncio.run(test_dc())` → `anyio.run(test_dc)` |
| `tools/legal_dataset_tools/CRON_SETUP_GUIDE.md` | `import asyncio` → `import anyio`; `asyncio.run(main())` → `anyio.run(main)` |
| `tools/legal_dataset_tools/COURTLISTENER_API_GUIDE.md` | `import asyncio` → `import anyio`; `asyncio.run(test_connection())` → `anyio.run(test_connection)` |
| `docs/adr/ADR-002-dual-runtime.md` | "asyncio event loop" → "anyio's asyncio backend"; "FastAPI routes continue to use asyncio" → "FastAPI routes run via anyio's asyncio backend"; Negative consequence improved: "must avoid asyncio.sleep only" → explicit list of banned primitives |

### 3.3 Phase M1 — External Callers Warned ✅

| File | Change |
|------|--------|
| `scripts/cli/integrated_cli.py` | Added `warnings.warn(DeprecationWarning)` before `SimpleIPFSDatasetsMCPServer` import |
| `scripts/cli/comprehensive_distributed_cli.py` | Added `warnings.warn(DeprecationWarning)` before `SimpleIPFSDatasetsMCPServer` import |

### 3.4 Phase M2 / O1 — `Dockerfile.standalone` Rewritten ✅

Removed: `flask>=3.0.0`, `standalone_server.py` copy, HTTP HEALTHCHECK, port 8000/8080 EXPOSEs  
Added: `anyio>=4.0.0`, full mcp_server package copy, process-based HEALTHCHECK  
New CMD: `python -m ipfs_datasets_py.mcp_server` (stdio mode)

### 3.5 Phase O2 — `start_services.sh` Fixed ✅

Removed `--host 0.0.0.0 --port 8000 --http` arguments from the MCP server startup line.  
Stdio mode is now the default.  Comment updated with explanation.

### 3.6 Phase O3 — `Dockerfile.simple` HEALTHCHECK Updated ✅

Removed HTTP-based health check (`curl -f http://localhost:8000/health`).  
New HEALTHCHECK: `python -c "import ipfs_datasets_py.mcp_server; print('ok')"` (process-based).

---

## 4. Phase M: Flask Removal

**Goal:** Fully remove Flask from the MCP server codebase (not just deprecate).

### M1 — Warn external callers of `SimpleIPFSDatasetsMCPServer` ✅ (Session 46)

**Status:** ✅ Complete

`scripts/cli/integrated_cli.py` and `scripts/cli/comprehensive_distributed_cli.py`
both emit `DeprecationWarning` before importing `SimpleIPFSDatasetsMCPServer`.

### M2 — Replace `simple_server.py` with MCP-native equivalent

**Status:** 🟡 In Progress — warnings added; deletion pending

`simple_server.py` currently provides HTTP routes (`/`, `/tools`, `/tools/<name>`)
using Flask.  The replacement is the MCP stdio server (`server.py`) plus the CLI
tool.  Once all consumers are migrated, `simple_server.py` should be deleted or
reduced to an import-shim that immediately raises `DeprecationWarning`.

**Acceptance criteria:**
- [x] No caller outside `simple_server.py` itself imports `SimpleIPFSDatasetsMCPServer` **without** a `DeprecationWarning`
- [ ] `Dockerfile.simple` updated to use `python -m ipfs_datasets_py.mcp_server` ← remaining
- [ ] `start_simple_server.sh` updated or removed ← remaining
- [ ] File marked for deletion with `# TODO: remove in v2.0` comment ← remaining

### M3 — Remove Flask from `requirements-docker.txt`

**Status:** 🔴 Pending

Once M2 is fully done, `flask` can be removed from `requirements-docker.txt`.

---

## 5. Phase N: anyio Migration Validation

**Goal:** Audit and validate that no production Python file in `mcp_server/` uses
`import asyncio` or calls `asyncio.*` directly.

### N1 — Automated check (already passing)

The grep-based check in session 45 confirmed **zero** `import asyncio` or
`asyncio.` calls in any `.py` file (excluding test files and markdown/backups).

**Status:** ✅ Complete

### N2 — CI check for asyncio regressions ✅ (Session 46)

**Status:** ✅ Complete

`tests/mcp/unit/test_no_asyncio_session46.py` — 4 AST-based tests confirm no production
file in `mcp_server/` imports `asyncio`.  Any future regression will cause this test
to fail immediately.

### N3 — Documentation audit ✅ (Session 46)

**Status:** ✅ Complete

- [x] `README.md` code examples updated (session 45)
- [x] `DUAL_RUNTIME_ARCHITECTURE.md` code example updated (session 45)
- [x] `tools/legal_dataset_tools/PLAYWRIGHT_SETUP.md` — `asyncio.run()` × 2 → `anyio.run()` (session 46)
- [x] `tools/legal_dataset_tools/CRON_SETUP_GUIDE.md` — `asyncio.run()` → `anyio.run()` (session 46)
- [x] `tools/legal_dataset_tools/COURTLISTENER_API_GUIDE.md` — `asyncio.run()` → `anyio.run()` (session 46)
- [x] `docs/adr/ADR-002-dual-runtime.md` — wording updated to use anyio-first language (session 46)

---

## 6. Phase O: Docker Image Refresh

**Goal:** Update Docker images to use the MCP stdio server instead of Flask.

### O1 — `Dockerfile.standalone` rewritten ✅ (Session 46)

**Status:** ✅ Complete

Removed `flask>=3.0.0`; removed `standalone_server.py`; process-based HEALTHCHECK;
CMD is now `python -m ipfs_datasets_py.mcp_server`.

### O2 — `start_services.sh` fixed ✅ (Session 46)

**Status:** ✅ Complete

Removed `--host 0.0.0.0 --port 8000 --http` flags.  MCP server runs in stdio mode.

### O3 — `Dockerfile.simple` HEALTHCHECK updated ✅ (Session 46)

**Status:** ✅ Complete

Removed HTTP-based health check (`curl -f http://localhost:8000/health`).  
New HEALTHCHECK: `python -c "import ipfs_datasets_py.mcp_server; print('ok')"` (process-based).

### O4 — Remove Flask from `requirements-docker.txt` 🔴 Pending

**Status:** 🔴 Pending

Once `simple_server.py` itself is deleted or fully migrated, remove `flask` from
`requirements-docker.txt`.

---

## 6. Success Metrics

| Metric | Session 44 Baseline | Session 45 | Session 46 | Phase M Target | Phase N Target |
|--------|--------------------|----|---|---|---|
| Tests passing | 1816 | 1829+ | 1833 ✅ | 1833+ | 1833+ |
| Flask imports in `.py` files | 2 hard + 1 conditional | 1 conditional (guarded) + deprecation warnings | 1 conditional + deprecation warnings + external caller warnings ✅ | 0 | 0 |
| `asyncio.run()` in `.py` source | 0 | 0 ✅ | 0 ✅ | 0 | 0 |
| `asyncio.*` comments (misleading) | 3 | 0 ✅ | 0 ✅ | 0 | 0 |
| `asyncio.run()` in doc code blocks | 2 | 0 ✅ | 0 ✅ | 0 | 0 |
| `asyncio.run()` in tool guide docs | 4 | 4 | 0 ✅ (N3 complete) | 0 | 0 |
| `asyncio` wording in ADR-002 | stale | stale | updated ✅ | — | ✅ |
| DeprecationWarnings on Flask classes | 0 | 5 ✅ | 5 ✅ | 5+ | — |
| Flask fallback in `__main__.py` | present | removed ✅ | removed ✅ | — | — |
| External callers warned | 0 | 0 | 2 ✅ (M1) | 2 | — |
| `Dockerfile.standalone` uses Flask | yes | yes | no ✅ (M2/O1) | no | — |
| `start_services.sh` --http flag | yes | yes | removed ✅ (O2) | no | — |
| `Dockerfile.simple` HTTP healthcheck | yes | yes | removed ✅ (O3) | no | — |
| CI asyncio regression check | none | none | ✅ `test_no_asyncio_session46.py` (N2) | ✅ | ✅ |

---

*This document supersedes [MASTER_IMPROVEMENT_PLAN_2026_v6.md](MASTER_IMPROVEMENT_PLAN_2026_v6.md)
for active work.  Prior phases G-L remain complete.*
