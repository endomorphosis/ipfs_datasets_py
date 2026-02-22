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

`tests/mcp/unit/test_deprecation_session45.py` — 13 tests:
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

## 3. Phase M: Flask Removal

**Goal:** Fully remove Flask from the MCP server codebase (not just deprecate).

### M1 — Replace `simple_server.py` with MCP-native equivalent

**Status:** 🔴 Pending

`simple_server.py` currently provides HTTP routes (`/`, `/tools`, `/tools/<name>`)
using Flask.  The replacement is the MCP stdio server (`server.py`) plus the CLI
tool.  Once all consumers are migrated, `simple_server.py` should be deleted or
reduced to an import-shim that immediately raises `DeprecationWarning`.

**Acceptance criteria:**
- [ ] No caller outside `simple_server.py` itself imports `SimpleIPFSDatasetsMCPServer`
- [ ] `Dockerfile.simple` updated to use `python -m ipfs_datasets_py.mcp_server`
- [ ] `start_simple_server.sh` updated or removed
- [ ] File marked for deletion with `# TODO: remove in v2.0` comment

### M2 — Replace `standalone_server.py` with MCP stdio + health file

**Status:** 🔴 Pending

`standalone_server.py` is used by `Dockerfile.standalone` for Docker deployments.
The replacement strategy:

1. Use `python -m ipfs_datasets_py.mcp_server` as the Docker CMD
2. For Docker health checks, create a simple `/health` file on disk that the
   `HEALTHCHECK` CMD checks with `test -f /tmp/healthy`
3. Or, use the lightweight FastAPI service layer instead of Flask

**Acceptance criteria:**
- [ ] `Dockerfile.standalone` no longer references `standalone_server.py`
- [ ] `standalone_server.py` reduced to a one-line shim or deleted

### M3 — Remove Flask from `requirements-docker.txt`

**Status:** 🔴 Pending

Once M1 and M2 are done, `flask` can be removed from `requirements-docker.txt`.

---

## 4. Phase N: anyio Migration Validation

**Goal:** Audit and validate that no production Python file in `mcp_server/` uses
`import asyncio` or calls `asyncio.*` directly.

### N1 — Automated check (already passing)

The grep-based check in session 45 confirmed **zero** `import asyncio` or
`asyncio.` calls in any `.py` file (excluding test files and markdown/backups).
The only occurrences were:

- Comments in `executor.py` (fixed in session 45)
- Markdown code examples (fixed in session 45)
- `.backup` file (not part of build)

**Status:** ✅ Complete

### N2 — Add CI check for asyncio regressions

**Status:** 🔴 Pending

Add a `pytest` fixture or CI step that verifies no production file imports asyncio:

```python
# tests/mcp/unit/test_no_asyncio_session45.py
import ast, pathlib

def test_no_asyncio_imports_in_production_code():
    """No production mcp_server .py file should import asyncio directly."""
    mcp_root = pathlib.Path("ipfs_datasets_py/mcp_server")
    violations = []
    for py_file in mcp_root.rglob("*.py"):
        if "test_" in py_file.name or "__pycache__" in str(py_file):
            continue
        src = py_file.read_text(errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in getattr(node, "names", [])]
                module = getattr(node, "module", "") or ""
                if "asyncio" in names or module.startswith("asyncio"):
                    violations.append(f"{py_file}:{node.lineno}")
    assert violations == [], f"asyncio imports found: {violations}"
```

### N3 — Documentation audit

**Status:** ✅ Partially complete (session 45)

- [x] `README.md` code examples updated
- [x] `DUAL_RUNTIME_ARCHITECTURE.md` code example updated
- [ ] `tools/legal_dataset_tools/` markdown guides (CRON_SETUP_GUIDE.md, PLAYWRIGHT_SETUP.md, COURTLISTENER_API_GUIDE.md) — still show `asyncio.run()` — update to `anyio.run()`
- [ ] `docs/adr/ADR-002-dual-runtime.md` — note says "developers must avoid `asyncio.sleep` only" — rephrase

---

## 5. Phase O: Docker Image Refresh

**Goal:** Update Docker images to use the MCP stdio server instead of Flask.

### O1 — Update `Dockerfile.standalone`

**Status:** 🔴 Pending

Current `Dockerfile.standalone` installs Flask and runs `standalone_server.py`.
Replace with:

```dockerfile
# Install minimal Python dependencies (no Flask needed)
RUN pip install mcp>=1.2.0 anyio>=4.0.0

# Run MCP stdio server
CMD ["python", "-m", "ipfs_datasets_py.mcp_server"]
```

For health checks, use a process-based check:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import ipfs_datasets_py; print('ok')" || exit 1
```

### O2 — Update `start_services.sh`

**Status:** 🔴 Pending

`start_services.sh` passes `--http` to the MCP server (now deprecated).
Update to use stdio mode (or remove `--http` flag).

### O3 — Update `Dockerfile.simple`

**Status:** 🔴 Pending

`Dockerfile.simple` uses `start_services.sh` which uses `--http`.  Update the
CMD to use stdio mode directly.

---

## 6. Success Metrics

| Metric | Session 44 Baseline | Session 45 | Phase M Target | Phase N Target |
|--------|--------------------|----|---|---|
| Tests passing | 1816 | 1829+ | 1829+ | 1829+ |
| Flask imports in `.py` files | 2 hard + 1 conditional | 1 conditional (guarded) + deprecation warnings | 0 | 0 |
| `asyncio.run()` in `.py` source | 0 | 0 ✅ | 0 | 0 |
| `asyncio.*` comments (misleading) | 3 | 0 ✅ | 0 | 0 |
| `asyncio.run()` in doc code blocks | 2 | 0 ✅ | 0 | 0 |
| DeprecationWarnings on Flask classes | 0 | 5 ✅ | 5+ | — |
| Flask fallback in `__main__.py` | present | removed ✅ | — | — |
| Docker images using Flask | 2 | 2 | 0 | — |

---

*This document supersedes [MASTER_IMPROVEMENT_PLAN_2026_v6.md](MASTER_IMPROVEMENT_PLAN_2026_v6.md)
for active work.  Prior phases G-L remain complete.*
