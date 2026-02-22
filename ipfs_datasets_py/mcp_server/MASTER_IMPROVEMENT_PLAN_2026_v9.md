# MCP Server — Master Improvement Plan v9.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions P65 + Q67 + Q68 + R69 COMPLETE** — branch `copilot/create-refactoring-plan-again`  
**Preconditions:** All v8 phases are ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v8.md](MASTER_IMPROVEMENT_PLAN_2026_v8.md))

**Baseline (as of 2026-02-22 v9 start):**
- 2,024 MCP unit tests passing · 0 failing (from v8 grand total)
- All v8 sessions O62, O63, P64 complete (141 new tests)
- Coverage gaps: `server.py` register paths, `hierarchical_tool_manager.py` shutdown, `enterprise_api.py` RateLimiter/ProcessingJobManager, `monitoring.py` loop/track paths

---

## Phase P — server.py register/start paths (Session P65)

**Goal:** Cover `register_tools()`, `register_ipfs_kit_tools()`, `start_stdio()`, `start()`.

### Session P65: server.py register + start ✅ Complete

**File:** `tests/mcp/unit/test_server_register_session65.py` — **14 new tests**

Coverage gaps addressed:

#### TestRegisterTools (4 tests):
- `register_tools()` with `mcp=None` → raises `ImportError("MCP dependency")`
- `register_tools()` with mocked `mcp` → exactly 4 `add_tool` calls + 4 `tools` entries
- `_register_tools_from_subdir()` with `ERROR_REPORTING_AVAILABLE=False` → raw tool stored
- `_register_tools_from_subdir()` with `ERROR_REPORTING_AVAILABLE=True` → wrapped tool stored

#### TestRegisterIpfsKitTools (5 tests):
- `register_ipfs_kit_tools(url=...)` → `_register_ipfs_kit_mcp_client` awaited, direct not called
- `register_ipfs_kit_tools()` no URL → `_register_direct_ipfs_kit_imports` called, mcp_client not awaited
- `_register_ipfs_kit_mcp_client()` with `MCPClient` import failing → no raise
- `_register_direct_ipfs_kit_imports()` with `ipfs_kit_py=None` → no raise, no tools added
- `_register_direct_ipfs_kit_imports()` with real pkg → `ipfs_kit_add` in `tools`

#### TestStartStdio (5 tests):
- `start_stdio()` → `mcp.run_stdio_async()` awaited
- `start_stdio()` raises `ServerStartupError` → re-raised
- `start_stdio()` with `p2p` set → `p2p.start()` and `p2p.stop()` called
- `start()` → falls back to `mcp.run_stdio_async()`
- `start()` with `ipfs_kit_mcp_url` → `register_ipfs_kit_tools(url)` called

---

## Phase Q — hierarchical_tool_manager.py shutdown + dispatch edge cases (Session Q67)

**Goal:** Cover `graceful_shutdown()` + remaining `dispatch_parallel()` edge cases.

### Session Q67: Graceful shutdown + dispatch edge cases ✅ Complete

**File:** `tests/mcp/unit/test_hierarchical_shutdown_session67.py` — **9 new tests**

Coverage gaps addressed:

#### TestGracefulShutdown (6 tests):
- Zero categories → `{"status": "ok", "categories_cleared": 0}`
- 3 pre-loaded categories → `categories_cleared=3`, `categories == {}`
- Internal state cleared: `_discovered_categories=False`, `_shutting_down=False`
- Timeout path (manual `TimeoutError`) → `status='timeout'` recorded
- Tool/schema caches are cleared on each category
- Return dict has `"status"` and `"categories_cleared"` keys

#### TestDispatchParallelEdgeCases (3 tests):
- `return_exceptions=True` + exception → error dict with `status="error"` and `error` key
- `max_concurrent=2` with 4 calls → all 4 processed in 2 batches, `call_count == 4`
- `return_exceptions=False` + exception → `ExceptionGroup` / `ValueError` propagates

---

## Phase Q — enterprise_api.py deep coverage (Session Q68)

**Goal:** Cover `RateLimiter`, `ProcessingJobManager`, `EnterpriseGraphRAGAPI`, `AdvancedAnalyticsDashboard`.

### Session Q68: Enterprise API deep coverage ✅ Complete

**File:** `tests/mcp/unit/test_enterprise_api_deep_session68.py` — **25 new tests**

Coverage gaps addressed:

#### TestRateLimiter (5 tests):
- Unknown endpoint → passes
- First request increments counter to 1
- Exceeds limit → `HTTPException(429)` raised
- Expired window → evicts old items, counter reset to 1
- Two users are independent (user_a limited doesn't affect user_b)

#### TestProcessingJobManager (9 tests):
- `submit_job()` returns non-empty job_id, job stored in `mgr.jobs`
- Submitted job has `status='queued'`, `progress=0.0`
- `get_job_status()` returns `JobStatusResponse` for known job
- `get_job_status()` returns `None` for unknown job
- `get_user_jobs()` returns only jobs for that user
- `get_user_jobs()` sorted descending by `created_at`
- `process_job()` with `ToolExecutionError` → `status='failed'`
- `process_job()` with `ValueError` → `status='failed'`, `"Invalid parameters"` in message
- `_send_webhook_notification()` with aiohttp absent → no raise
- `_send_webhook_notification()` generic exception → no raise

#### TestEnterpriseGraphRAGAPITokens (5 tests):
- `create_jwt_token({"username": "demo"})` → non-empty string
- `create_jwt_token({"user_id": "id"})` → no exception
- `validate_jwt_token()` for valid demo token → dict with `username == 'demo'`
- `validate_jwt_token()` garbled token → `None`
- `validate_jwt_token()` revoked token → `None`

#### TestAdvancedAnalyticsDashboard (5 tests):
- `generate_system_report()` empty → `total_jobs=0`, `success_rate=0`
- `_calculate_avg_quality()` no results → `0.0`
- `_get_recent_activity()` empty → `[]`
- `_get_recent_activity()` 1 job → entry with `job_id`/`status`/`website_url`/`created_at` keys
- `generate_system_report()` with completed/failed/queued → correct counts in `job_statistics`

**Key setup:** `ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag` must be stubbed in `sys.modules` BEFORE importing `enterprise_api` (it's a module-level import of `CompleteGraphRAGSystem`).

---

## Phase R — monitoring.py deep coverage (Session R69)

**Goal:** Cover `_monitoring_loop()`, `_cleanup_loop()`, `track_request()`, `track_tool_execution()`, `get_metrics_summary()`, `_collect_system_metrics()` without psutil.

### Session R69: Monitoring deep coverage ✅ Complete

**File:** `tests/mcp/unit/test_monitoring_deep_session69.py` — **27 new tests**

Coverage gaps addressed:

#### TestMonitoringLoopPaths (5 tests):
- `_monitoring_loop()` → exits on `CancelledError`
- `_monitoring_loop()` → `MetricsCollectionError` → sleeps 60s (patched `anyio.sleep` at module level)
- `_monitoring_loop()` → `OSError` → sleeps 60s
- `_cleanup_loop()` → exits on `CancelledError`
- `_cleanup_loop()` → `IOError` → sleeps 3600s

**Key:** Patch `anyio.sleep` at `ipfs_datasets_py.mcp_server.monitoring.anyio.sleep`, NOT at `anyio.sleep`; the `CancelledError` raised in `fake_sleep` propagates out, so catch `BaseException` in tests.

#### TestTrackRequest (5 tests):
- Success → `request_count` incremented
- Success → `request_times` has ≥ 1 entry
- Exception inside context → `error_count` incremented, re-raises
- `MonitoringError` inside context → `error_count` incremented, re-raises
- After context, `active_requests` is empty

#### TestTrackToolExecution (7 tests):
- Success → `call_counts[tool] == 1`
- Success → `error_counts[tool] == 0`
- Failure → `error_counts[tool] == 1`
- Records time in `execution_times[tool]`
- 1 pass + 1 fail → `success_rates[tool] == 0.5`
- Updates `last_called` to a `datetime`
- Two tools have independent counts

#### TestGetMetricsSummary (6 tests):
- Has all required top-level keys
- `uptime_seconds ≥ 0`
- `request_metrics` has all sub-keys
- Includes tool after `track_tool_execution` call
- `tool_metrics == {}` when nothing tracked
- `recent_alerts == []` initially

#### TestCollectSystemMetricsNoPsutil (2 tests):
- `HAVE_PSUTIL=False` → snapshot appended with `cpu_percent=0.0`
- `HAVE_PSUTIL=False` → `system_metrics['cpu_percent'] == 0.0`

#### TestStartMonitoring (2 tests):
- `enabled=False` → `_start_monitoring` never called
- Called outside async context → no exception

---

## Summary — v9 Sessions

| Session | File | New Tests | Status |
|---------|------|-----------|--------|
| P65 | `test_server_register_session65.py` | 14 | ✅ Complete |
| Q67 | `test_hierarchical_shutdown_session67.py` | 9 | ✅ Complete |
| Q68 | `test_enterprise_api_deep_session68.py` | 25 | ✅ Complete |
| R69 | `test_monitoring_deep_session69.py` | 27 | ✅ Complete |
| **Total** | | **75** | ✅ |

**Grand total (all plans):** 2,024 (through v8) + 75 (v9) = **2,099 MCP unit tests**

---

## Next Steps (v10 candidates)

| Session | Target | Rationale |
|---------|--------|-----------|
| S71 | `server.py` — `handle_tool()`, error handler registration, `_build_tool_response` | Still ~20 uncovered stmts |
| S72 | `fastapi_service.py` — `/datasets/*` authenticated body via `sys.modules` injection | 150+ stmts for dataset routes |
| T73 | `enterprise_api.py` — `_setup_routes()`, `_setup_core_api_routes()`, TestClient route tests | HTTP route integration |
| T74 | `p2p_service_manager.py` — `start()` success path, `_ensure_ipfs_accelerate_on_path()` | Start path never hit |
| U75 | `monitoring.py` — `_check_health()` async path, `P2PMetricsCollector` alerts | Alert thresholds |
| U76 | Integration: full MCP server → `start_stdio` → tool list → dispatch round-trip | End-to-end validation |
