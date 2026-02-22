# MCP Server — Master Improvement Plan v10.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions S71 + T73 + T74 + U75 + U76 COMPLETE** — branch `copilot/create-refactoring-plan-again`  
**Preconditions:** All v9 phases are ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v9.md](MASTER_IMPROVEMENT_PLAN_2026_v9.md))

**Baseline (as of 2026-02-22 v10 start):**
- 2,099 MCP unit tests passing · 0 failing (from v9 grand total)
- All v9 sessions P65, Q67, Q68, R69 complete (75 new tests)
- Additional bug fix: `test_validators_fuzzing_session48.py` now collects/skips correctly when `hypothesis` absent

---

## Bug Fix — test_validators_fuzzing_session48.py

**Problem:** `hypothesis` stubs were incomplete — `assume`/`_StStub` needed comments; `assume` stub lacked docstring.  
**Fix:** Added clarifying comment to `assume` stub; confirmed all 40 tests skip gracefully.

---

## Phase S — server.py handle_tool + error reporting (Session S71)

**Goal:** Cover `_wrap_tool_with_error_reporting`, `_initialize_error_reporting`, `start_stdio_server`/`start_server` function-level error paths.

### Session S71: server.py wrap + error + start functions ✅ Complete

**File:** `tests/mcp/unit/test_server_handle_tool_session71.py` — **15 new tests**

#### TestWrapToolWithErrorReporting (5 tests):
- `async_wrapper` success → returns value (async test, pytest-asyncio AUTO mode)
- `async_wrapper` exception → re-raises ValueError
- `sync_wrapper` success → returns value
- `sync_wrapper` exception → re-raises RuntimeError
- `functools.wraps` preserves `__name__`

#### TestInitializeErrorReporting (3 tests):
- `ERROR_REPORTING_AVAILABLE` is a bool (attribute exists)
- `_initialize_error_reporting()` no-raise when reporter absent
- `_initialize_error_reporting()` no-raise with mock reporter

#### TestStartStdioServerFunction (4 tests):
- `KeyboardInterrupt` handled silently
- `ServerStartupError` caught, not re-raised
- Generic `RuntimeError` caught gracefully
- `ipfs_kit_mcp_url` sets `configs.ipfs_kit_mcp_url` and `configs.ipfs_kit_integration`

#### TestStartServerFunction (3 tests):
- `KeyboardInterrupt` handled silently
- `ServerStartupError` caught, not re-raised
- `OSError` caught gracefully

---

## Phase T — enterprise_api.py TestClient integration (Session T73)

**Goal:** Exercise all route groups via `httpx.AsyncClient` + `ASGITransport`.

### Session T73: Enterprise API route integration ✅ Complete

**File:** `tests/mcp/unit/test_enterprise_api_routes_session73.py` — **21 new tests**

#### TestHealthEndpoint (3 tests):
- `/health` → 200
- `/health` → `{"status": "healthy", ...}`
- `/health` → has `timestamp` key

#### TestAuthLogin (4 tests):
- Valid credentials (demo) → 200 + `access_token`
- Valid credentials (admin) → 200
- Invalid credentials → 401
- `access_token` is non-empty string

#### TestJobsEndpoints (5 tests):
- `GET /api/v1/jobs` unauthenticated → 403
- `GET /api/v1/jobs` authenticated → 200 list
- `GET /api/v1/jobs/<nonexistent>` → 404
- `POST /api/v1/process-website` missing `url` → 422
- `POST /api/v1/process-website` valid → 200 with `job_id` + `status=queued`

#### TestAnalyticsRoutes (4 tests):
- `GET /api/v1/admin/analytics` unauthenticated → 403
- `GET /api/v1/admin/analytics` demo user → 403 (no admin role)
- `GET /api/v1/admin/analytics` admin user → 200 with keys
- `GET /api/v1/analytics/<nonexistent>` → 404

#### TestSearchRoute (2 tests):
- `POST /api/v1/search/...` unauthenticated → 403
- `POST /api/v1/search/<not-completed-job>` → 404

#### TestSetupRoutesDirect (3 tests):
- Routes registered on `app.routes` (health, login, jobs, analytics)
- `_setup_health_and_auth_routes` registers /health and /auth/login
- `_create_app` returns `FastAPI` instance

---

## Phase T — p2p_service_manager.py start + init (Session T74)

**Goal:** Cover `start()` success path, `_ensure_ipfs_accelerate_on_path`, `_initialize_mcplusplus_features`.

### Session T74: p2p_service_manager deep start paths ✅ Complete

**File:** `tests/mcp/unit/test_p2p_service_start_session74.py` — **22 new tests**

#### TestEnsureIpfsAccelerateOnPath (3 tests):
- `candidate.exists()` → path prepended, `sys.path` length ≥ before
- Called twice → idempotent (no raise)
- `OSError` → swallowed silently

#### TestP2PServiceManagerStart (5 tests):
- `enabled=False` → returns `False` immediately
- `ImportError` on import → returns `False`
- Success path (mocked `TaskQueueP2PServiceRuntime`) → returns `True`, sets `_runtime`/`_handle`
- Non-`ImportError` exception (via `_BadModule.__getattr__`) → returns `False`
- `_apply_env` is always called before import attempt

#### TestP2PServiceManagerState (5 tests):
- Returns `P2PServiceState` instance
- `running=False` when `_runtime=None`
- `last_error` extracted from runtime attribute
- `P2PServiceError` in `last_error` access → captured as error string
- Generic exception → fallback infers from `runtime.running`

#### TestAdvancedFeatureAccessors (6 tests):
- `has_advanced_features()` False by default, True when flag set
- `get_workflow_scheduler()` None by default, returns set value
- `get_peer_registry()` None by default, returns set value

#### TestInitializeMCPPlusPlus (3 tests):
- `ImportError` → `_mcplusplus_available=False`
- `HAVE_MCPLUSPLUS=False` → early return, `_workflow_scheduler=None`
- Generic exception → `_mcplusplus_available=False`, no raise

---

## Phase U — monitoring.py _check_health async + P2P alerts (Session U75)

**Goal:** Cover `_check_health` async path and `P2PMetricsCollector` alert threshold methods.

### Session U75: Monitoring health checks + P2P alerts ✅ Complete

**File:** `tests/mcp/unit/test_monitoring_alerts_session75.py` — **22 new tests**

#### TestCheckHealthAsync (7 tests):
- Async coroutine check function → awaited, result stored
- Sync function returning awaitable → awaited
- Non-`HealthCheckResult` return → `status='healthy'`
- `HealthCheckError` → `status='critical'`, message preserved
- `ImportError` → `status='critical'`, `'unavailable'` in message
- Generic `Exception` → `status='critical'`
- `response_time_ms` updated in place on `HealthCheckResult` return

#### TestPeerDiscoveryAlerts (4 tests):
- ≤10 total → no alert
- failure_rate == 30% → no alert (at threshold)
- failure_rate > 30% → warning alert with `component='peer_discovery'`
- `get_alert_conditions` includes peer_discovery alert

#### TestWorkflowAlerts (4 tests):
- ≤5 total → no alert
- failure_rate == 20% → no alert
- failure_rate > 20% → warning alert with `component='workflows'`
- `get_alert_conditions` includes workflow alert

#### TestBootstrapAlerts (7 tests):
- ≤3 total → no alert
- failure_rate == 50% → no alert
- failure_rate > 50% → **critical** alert with `component='bootstrap'`
- `get_alert_conditions` includes bootstrap alert
- `get_alert_conditions` empty when all healthy
- Alert has `timestamp` key
- All three alert types fire simultaneously → set of 3 components

---

## Phase U — Integration round-trip (Session U76)

**Goal:** Verify that the complete server → tool manager → dispatch → metrics chain works end-to-end.

### Session U76: Full integration round-trip ✅ Complete

**File:** `tests/mcp/unit/test_server_integration_session76.py` — **18 new tests**

#### TestServerRegisterToolsLifecycle (3 tests):
- `register_tools()` → exactly 4 meta-tools in `srv.tools`
- `mcp.add_tool` called exactly 4 times
- `srv.mcp=None` → raises `ImportError`

#### TestHierarchicalToolManagerListOps (4 tests):
- `list_categories()` → non-empty list of dicts (each with `name` key)
- `list_tools(name)` → list or dict result for valid category
- `list_tools("nonexistent")` → returns result without raising

#### TestHierarchicalToolManagerDispatch (4 tests):
- `dispatch("admin_tools", "list_tools", {})` → dict result
- `dispatch("no_such_cat", "tool", {})` → error dict with `status='error'`
- `dispatch_parallel([{category, tool, params}×3], return_exceptions=True)` → 3 dicts
- `dispatch_parallel([])` → `[]`

#### TestMetricsIntegration (4 tests):
- `track_tool_execution` → `call_counts[tool] == 1`, `error_counts[tool] == 0`
- 5 success + 1 failure → `call_counts=6`, `error_counts=1`, `0 < success_rate < 1`
- `get_metrics_summary` includes tracked tool
- `track_request` async context manager completes without error

#### TestFullRoundTrip (3 tests):
- After `register_tools()`, `srv.tools["tools_list_categories"]` is callable
- `HierarchicalToolManager.list_categories()` is non-empty independent of server
- Bad category dispatch → error dict → tracked as failure, `error_counts==1`

---

## Summary — v10 Sessions

| Session | File | New Tests | Status |
|---------|------|-----------|--------|
| S71 | `test_server_handle_tool_session71.py` | 15 | ✅ Complete |
| T73 | `test_enterprise_api_routes_session73.py` | 21 | ✅ Complete |
| T74 | `test_p2p_service_start_session74.py` | 22 | ✅ Complete |
| U75 | `test_monitoring_alerts_session75.py` | 22 | ✅ Complete |
| U76 | `test_server_integration_session76.py` | 18 | ✅ Complete |
| Fix | `test_validators_fuzzing_session48.py` | 0 (+comment) | ✅ Fixed |
| **Total** | | **98 new** | ✅ |

**Grand total (all plans):** 2,099 (through v9) + 98 (v10) = **2,197 MCP unit tests**  
*(plus 40 skipped hypothesis tests)*

---

## Next Steps (v11 candidates)

| Session | Target | Rationale |
|---------|--------|-----------|
| V77 | `fastapi_service.py` — `/datasets/*` routes with mocked inner imports | 100+ uncovered stmts in dataset POST handlers |
| V78 | `enterprise_api.py` — `create_enterprise_api`, `start_enterprise_server` | Factory + server bootstrap paths |
| W79 | `server.py` — `_initialize_mcp_server`, `_initialize_p2p_services` | Init paths on startup |
| W80 | `hierarchical_tool_manager.py` — `get_schema`, `lazy_load_category` deep paths | Schema cache miss / lazy load success |
| X81 | `monitoring.py` — `_check_alerts` CPU/memory/error_rate/response_time triggers | 4 alert type thresholds |
| X82 | `p2p_service_manager.py` — `stop()` error paths, `P2PServiceError` in stop | Stop lifecycle error handling |
| Y83 | End-to-end: `EnterpriseGraphRAGAPI` → submit job → process → query analytics | Full job lifecycle |
| Z84 | Coverage report pass: consolidate gaps < 5% across all mcp_server modules | Final push to 90%+ |
