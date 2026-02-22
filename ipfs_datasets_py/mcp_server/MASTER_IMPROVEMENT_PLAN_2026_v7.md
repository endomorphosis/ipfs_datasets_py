# MCP Server — Master Improvement Plan v7.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions M55 + N59 COMPLETE** — branch `copilot/create-refactoring-plan-again`  
**Preconditions:** All v6 phases are ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v6.md](MASTER_IMPROVEMENT_PLAN_2026_v6.md))

**Baseline (as of 2026-02-22 v7 start):**
- 1,749 MCP unit tests passing · 0 failing
- All v6 sessions G40–L54 complete (565 new tests, 15 sessions)
- `fastapi_service.py` 635 stmts — existing coverage: ~40% (19 smoke tests)
- `p2p_mcp_registry_adapter.py` 180 stmts — existing coverage: ~70% (26 tests)

---

## Phase M — fastapi_service.py Deep Coverage (Sessions M55–M56)

**Goal:** Raise `fastapi_service.py` coverage from ~40% to ≥ 75%.

### Session M55: Core route coverage + helpers ✅ Complete

**File:** `tests/mcp/unit/test_fastapi_service_session55.py` — **91 new tests**

Coverage gaps addressed:

#### TestReadinessCheck (7 tests):
- `/health/ready` returns 200 status
- `checks.metrics_collector` and `checks.tool_manager` keys present
- `uptime_seconds` key present
- `categories` key within tool_manager check

#### TestMetricsEndpoint (6 tests):
- `/metrics` returns 200 with `text/plain` content-type
- Response contains `# HELP` comment lines
- Response contains `mcp_uptime_seconds`, `mcp_requests_total`, `process_cpu_percent` metrics

#### TestFallbackPasswordContext (6 tests):
- `hash()` returns deterministic 64-char hex string matching `hashlib.sha256`
- `verify()` returns True for correct password, False for wrong password

#### TestCreateAccessToken (4 tests):
- Returns `str` containing correct `sub` claim and `exp` claim
- Custom `expires_delta` results in future expiry ≥ 1 hour

#### TestCheckRateLimitLogic (6 tests):
- Endpoint not in `RATE_LIMITS` → no exception
- First request increments counter to 1
- At `requests` threshold → `HTTPException(429)` raised
- `admin/*` wildcard pattern matched
- Expired window resets counter to 1

#### TestToolsEndpoints (8 tests):
- Unauthenticated `/tools/list` → 401
- Authenticated `/tools/list` → 200 with `tools`, `count`, `categories` keys
- Unauthenticated `/tools/execute/tool` → 401
- Unknown tool → 4xx/5xx
- Mocked tool → 200 with `status=success`, `result`, `tool` keys

#### TestHTTPExceptionHandlerFormat (4 tests):
- Login with empty username triggers 400 with `error`, `status_code`, `timestamp` keys

#### TestMCPServerErrorHandler (4 tests) — **direct function call**:
- `MCPServerError` → 500
- `ToolNotFoundError` → 404
- `ConfigurationError` → 400
- Response body has `error_type` key

#### TestGeneralExceptionHandler (3 tests) — **direct function call**:
- `ValueError` → 500 JSON with `error` and `timestamp` keys

#### TestWorkflowEndpoints (5 tests):
- Unauthenticated → 401
- Authenticated + mocked inner module → 200 with `task_id`, `workflow_name`, `steps_count`

#### TestDatasetEndpointsAuth (6 tests):
- Unauthenticated `/datasets/load,process,save,convert` → 401
- Authenticated → endpoint responds (200/404/500)

#### TestIPFSEndpointsAuth (4 tests) + TestVectorEndpointsAuth (4 tests):
- Unauthenticated → 401; authenticated → responds

#### TestAuditAndCacheEndpointsAuth (6 tests):
- Unauthenticated → 401; authenticated → responds

#### TestLogApiRequest (3 tests):
- `log_api_request` with success/error/input_size → no exception (audit module import failure gracefully swallowed)

#### TestCustomOpenAPI (3 tests):
- `custom_openapi()` returns dict with `openapi` key; result is cached on second call

#### TestRunServers (4 tests):
- `run_development_server()` and `run_production_server()` call `uvicorn.run`
- `run_production_server` passes `workers` ≥ 1

#### TestAdditionalRouteGuards (8 tests):
- `/analysis/clustering`, `/analysis/quality`, `/admin/stats`, `/admin/health`,
  `/embeddings/batch` — unauthenticated → 401; authenticated → endpoint responds

---

## Phase N — P2PMCPRegistryAdapter Deep Coverage (Session N59)

**Goal:** Raise `p2p_mcp_registry_adapter.py` from ~70% to ≥ 88%.

### Session N59: Error paths + edge cases ✅ Complete

**File:** `tests/mcp/unit/test_p2p_mcp_registry_adapter_session59.py` — **43 new tests**

Coverage gaps addressed:

#### TestGetToolManagerSafely (4 tests):
- Returns manager on success
- `sys.modules` injection of `None` → graceful None return
- `ConfigurationError` re-raised
- Generic `RuntimeError` → returns `None`

#### TestDiscoverCategories (5 tests):
- `in_async_context=True` early return → `[]`
- Dict result with `categories` key → names extracted
- Non-dict result → `[]`
- Category with `category` key (not `name`) → included
- Non-dict category entries (str, int) → skipped via `isinstance` check

#### TestProcessCategoryTools (10 tests):
- Tool with `name=None` → skipped
- Two valid tools added to `out` dict
- No `tools` key in result → early return
- Non-dict result → early return
- `ToolExecutionError` from `_build_tool_wrapper` → swallowed by outer `except Exception`
- `ValueError` per-tool → swallowed with warning
- `TypeError` per-tool → swallowed with warning
- `ImportError` from `anyio_compat.run` → swallowed by outer `except (ImportError, ModuleNotFoundError)`
- `ConfigurationError` from `anyio_compat.run` → re-raised by outer `except ConfigurationError: raise`
- Tool descriptor has `hierarchical=True` and correct `category` in `runtime_metadata`

#### TestGetHierarchicalTools (6 tests):
- `manager=None` early return → `{}`
- `P2PServiceError` re-raised
- `ConfigurationError` in `_discover_categories` re-raised
- Generic `RuntimeError` → swallowed → `{}`
- `ModuleNotFoundError` in `_discover_categories` → `{}`
- Two categories processed → both tools returned

#### TestIsAsyncFunctionEdgeCases (6 tests):
- async def → True, sync def → False
- Non-callable integer → False
- `inspect.iscoroutinefunction` raises `TypeError` → False
- `inspect.iscoroutinefunction` raises `AttributeError` → False
- `inspect.iscoroutinefunction` raises `RuntimeError` → False

#### TestBuildToolWrapper (4 tests):
- Wrapper is callable; has correct `__name__` and `__doc__`; is coroutine function

#### TestDetectRuntimeEdgeCases (5 tests):
- `fn.__module__` raises `AttributeError` → defaults to RUNTIME_FASTAPI
- Module contains `trio` → RUNTIME_TRIO; contains `mcplusplus` → RUNTIME_TRIO
- Explicit `_mcp_runtime='fastapi'` marker → RUNTIME_FASTAPI
- Explicit `_mcp_runtime='trio'` marker → RUNTIME_TRIO

#### TestToolsPropertyEdgeCases (3 tests):
- `host.tools = None` → `{}`
- Host has no `tools` attribute → `{}`
- `host.tools` is a list → `{}`

---

## Progress Tracking

| Phase | Session | Status | Tests Added | Target |
|-------|---------|--------|-------------|--------|
| M55   | fastapi_service extended | ✅ Complete | +91 | `fastapi_service.py` 40%→75%+ |
| N59   | p2p_mcp_registry_adapter deep | ✅ Complete | +43 | `p2p_mcp_registry_adapter.py` 70%→88%+ |

**Total new tests in v7:** 134 (91 + 43)  
**Cumulative MCP tests:** 1,749 + 134 = **1,883** (target: 2,000+)

---

## Remaining Opportunities (v8)

| File | Stmts | Est. Current % | Est. Gap |
|------|-------|----------------|----------|
| `server.py` | 353 | ~60% | Routes, error handling, lifecycle |
| `fastapi_service.py` | 635 | ~75% (after M55) | Remaining route bodies via sys.modules mocks |
| `p2p_service_manager.py` | 227 | ~65% | `start()` success path, MCP++ features |
| `monitoring.py` | 406 | ~80% | async loop, advanced metrics |

**Suggested v8 sessions:**
- **O62**: `server.py` coverage (+40 tests — IPFSDatasetsMCPServer lifecycle, handle_tool, error paths)
- **O63**: `p2p_service_manager.py` deeper coverage (+20 tests — MCP++ integration, acquire/release pool)
- **P64**: `fastapi_service.py` remaining routes via `sys.modules` injection (+25 tests)
- **P65**: Create `MASTER_IMPROVEMENT_PLAN_2026_v8.md`
