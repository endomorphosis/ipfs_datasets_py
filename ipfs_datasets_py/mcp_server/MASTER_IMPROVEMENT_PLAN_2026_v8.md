# MCP Server — Master Improvement Plan v8.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions O62 + O63 + P64 COMPLETE** — branch `copilot/create-refactoring-plan-again`  
**Preconditions:** All v7 phases are ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v7.md](MASTER_IMPROVEMENT_PLAN_2026_v7.md))

**Baseline (as of 2026-02-22 v8 start):**
- 1,883 MCP unit tests passing · 0 failing (134 new from v7)
- All v7 sessions M55, N59 complete
- `server.py` — uncovered: `_sanitize_error_context`, `_wrap_tool_with_error_reporting`, `validate_p2p_message`, `import_tools_from_directory`, entry-point helpers
- `p2p_service_manager.py` — uncovered: connection pool, env helpers, `get_capabilities`, `state()` fallbacks
- `fastapi_service.py` — uncovered: `/health` liveness, `/auth/login`, `/auth/refresh`, `/embeddings/generate`, `/search/*`, `/analysis/*`, `/admin/*`, `run_workflow_background`

---

## Phase O — server.py + p2p_service_manager.py Deep Coverage (Sessions O62–O63)

**Goal:** Raise `server.py` and `p2p_service_manager.py` coverage to ≥ 75%.

### Session O62: server.py — lifecycle + helpers ✅ Complete

**File:** `tests/mcp/unit/test_server_session62.py` — **48 new tests**

Coverage gaps addressed:

#### TestReturnHelpers (3 tests):
- `return_text_content` with mocked `TextContent` → callable and called with correct args
- `return_tool_call_results` with `error=False` → `isError=False`
- `return_tool_call_results` with `error=True` → `isError=True`

#### TestImportToolsFromDirectory (5 tests):
- Non-existent directory → `{}`
- Empty directory → `{}`
- Private `_private.py` file → skipped
- Import error handled gracefully → `{}`
- Valid tool module → `importlib.import_module` called

#### TestIPFSDatasetsMCPServerInit (9 tests):
- Basic init with `FastMCP=None` → `mcp` is `None`, `tools == {}`
- Custom `server_configs` → stored
- `_initialize_mcp_server` with mocked `FastMCP` → `mcp` is instance
- `_initialize_mcp_server` without `FastMCP` → `mcp=None`, `_fastmcp_available=False`
- `_initialize_error_reporting` with `ERROR_REPORTING_AVAILABLE=True` → `install_global_handler` called
- `_initialize_error_reporting` exception swallowed
- `_initialize_p2p_services` import error → `p2p=None`
- `_initialize_p2p_services` generic exception → `p2p=None`

#### TestValidateP2PMessage (7 tests):
- `p2p_auth_mode=shared_token` → False
- No token field → False
- Empty token → False
- Non-string token → False
- Valid token + mock auth service → True
- Import error → False
- Configs raises on `p2p_auth_mode` → False (no raise)

#### TestSanitizeErrorContext (9 tests):
- Sensitive keys (`api_key`, `password`, `auth_token`) → `"<REDACTED>"`
- Simple types preserved
- List value → length summary
- Dict value → key count summary
- Object → type name
- `argument_count` correct
- `argument_names` correct
- Empty kwargs → `argument_count=0`

#### TestWrapToolWithErrorReporting (5 tests):
- Async tool wrapped → coroutine; returns correct result
- Sync tool wrapped → non-coroutine; returns correct result
- Async error reported and re-raised
- Sync error re-raised
- `__name__` preserved via `functools.wraps`

#### TestRegisterToolsFromSubdir (2 tests):
- Tools added to `self.tools` dict when `import_tools_from_directory` returns them
- Empty dir → `self.tools == {}`

#### TestRegisterIpfsKitTools (3 tests):
- `ipfs_kit_py` not installed → no raise
- `ipfs_kit_py` with `add` func → `ipfs_kit_add` in tools
- `MCPClient` import fails → no raise

#### TestStartFunctions (3 tests):
- `start_stdio_server` with `KeyboardInterrupt` → no raise
- `start_server` with `KeyboardInterrupt` → no raise
- `start_stdio_server(ipfs_kit_mcp_url=...)` updates `configs`

#### TestArgsModel (3 tests):
- Basic construction from namespace
- Custom host/port
- Optional fields `None` by default

---

### Session O63: p2p_service_manager.py — full lifecycle + pool ✅ Complete

**File:** `tests/mcp/unit/test_p2p_service_manager_session63.py` — **59 new tests**

Coverage gaps addressed:

#### TestP2PServiceState (3 tests):
- Basic construction with required fields
- Default optional fields (last_error, counters)
- All fields set

#### TestP2PServiceManagerInit (12 tests):
- `enabled=False` by default
- `enabled=True` stored
- `queue_path` default and custom
- `listen_port` None then set
- `auth_mode` default `mcp_token`
- Pool initialized empty with `_pool_hits==0`, `_pool_misses==0`
- `_pool_max_size=10` default
- `_mcplusplus_available=False` initially
- `bootstrap_nodes` empty and custom

#### TestEnvHelpers (5 tests):
- `_setdefault_env` sets when not in env; skips when already set
- `_apply_env` sets `IPFS_ACCELERATE_PY_TASK_QUEUE_PATH`
- `_restore_env` removes set vars
- `_restore_env` restores prior value

#### TestStart (4 tests):
- `enabled=False` → False
- `ImportError` → False
- Generic `Exception` (not `ImportError`) during attribute access → False
- Mocked runtime → True

#### TestStop (4 tests):
- No runtime → True
- `P2PServiceError` → False
- Generic `Exception` → False
- Success → True

#### TestState (3 tests):
- No runtime, service unavailable → `P2PServiceState` with `running=False`
- Import error → uses `runtime.running` fallback
- `_workflow_scheduler` set → `workflow_scheduler_available=True`

#### TestMCPPlusPlusFeatures (5 tests):
- Import error → `_mcplusplus_available=False`
- `HAVE_MCPLUSPLUS=False` → not available
- No scheduler → no raise
- Scheduler + patched `reset_scheduler` → cleared
- Cleanup exception swallowed

#### TestGetters (6 tests):
- `get_workflow_scheduler` None initially; returns value when set
- `get_peer_registry` None initially; returns value when set
- `has_advanced_features` False initially; True when `_mcplusplus_available=True`

#### TestConnectionPool (11 tests):
- Miss → `None` returned, `_pool_misses++`
- Hit → conn returned, removed from pool, `_pool_hits++`
- Release → conn stored
- Release `None` → False
- Release full pool → False
- `clear_connection_pool` → empty pool, counters reset, count returned
- `get_pool_stats` empty → `hit_rate=None`
- `get_pool_stats` 2 hits + 2 misses → `hit_rate=0.5`
- `get_pool_stats` reflects pool size
- Thread safety (10 concurrent workers)

#### TestGetCapabilities (6 tests):
- All expected keys present
- `p2p_enabled=False` / True
- `connection_pool_max_size=10`
- `workflow_scheduler=False`
- `_ensure_ipfs_accelerate_on_path` doesn't raise

---

## Phase P — fastapi_service.py Additional Routes (Session P64)

**Goal:** Cover remaining routes and helpers in `fastapi_service.py` not addressed in M55.

### Session P64: Additional FastAPI routes ✅ Complete

**File:** `tests/mcp/unit/test_fastapi_additional_session64.py` — **34 new tests**

Coverage gaps addressed:

#### TestHealthLiveness (5 tests):
- `GET /health` → 200
- Body has `status=healthy`, `timestamp`, `version`, `uptime_seconds`

#### TestAuthLogin (5 tests):
- Valid credentials → `access_token` in response
- `expires_in > 0`
- Empty username → 400
- Empty password → 400
- Token JWT decoded has `sub==username`

#### TestAuthRefresh (3 tests):
- Authenticated → new token returned
- Unauthenticated → 401
- Invalid token → 401

#### TestGetCurrentUser (1 test):
- Token with no `sub` claim → 401

#### TestEmbeddingsGenerate (3 tests):
- Unauthenticated → 401
- Authenticated + inner import fails → 500
- Mocked tool → responds

#### TestEmbeddingsBatch (1 test):
- Unauthenticated → 401

#### TestSearchEndpoints (2 tests):
- `/search/semantic` unauthenticated → 401
- `/search/hybrid` unauthenticated → 401

#### TestAnalysisEndpoints (2 tests):
- `/analysis/clustering` unauthenticated → 401
- `/analysis/quality` unauthenticated → 401

#### TestAdminEndpoints (2 tests):
- `/admin/stats` unauthenticated → 401
- `/admin/health` unauthenticated → 401

#### TestWorkflowStatus (3 tests):
- Unauthenticated → 401
- Authenticated + import fail → 500
- Mocked tool → responds

#### TestRunWorkflowBackground (4 tests):
- `ToolNotFoundError` → logged, no raise
- `ToolExecutionError` → logged, no raise
- Generic `Exception` → logged, no raise
- Success → `log_api_request` called with `status="completed"`

#### TestPasswordFunctions (3 tests):
- `get_password_hash` returns non-empty string
- `verify_password` correct → True
- `verify_password` incorrect → False

---

## Summary — v8 Sessions

| Session | File | New Tests | Status |
|---------|------|-----------|--------|
| O62 | `test_server_session62.py` | 48 | ✅ Complete |
| O63 | `test_p2p_service_manager_session63.py` | 59 | ✅ Complete |
| P64 | `test_fastapi_additional_session64.py` | 34 | ✅ Complete |
| **Total** | | **141** | ✅ |

**Grand total (all plans):** 1,749 + 134 (v7) + 141 (v8) = **2,024 MCP unit tests**

---

## Next Steps (v9 candidates)

- `P65`: `server.py` — `register_tools()`, `register_ipfs_kit_tools()`, `start_stdio()`, `start()` — mock `FastMCP.run_stdio_async`
- `P66`: `fastapi_service.py` — authenticated body coverage for `/datasets/*`, `/ipfs/*`, `/vectors/*` via sys.modules injection
- `Q67`: `hierarchical_tool_manager.py` — `ToolScheduler`, `batch_dispatch`, `graceful_shutdown` edge cases
- `Q68`: `enterprise_api.py` — `PermissionManager`, `AuditLogger`, session management
- `R69`: `monitoring.py` — `MetricsCollector`, `_background_collect`, timer context
- `R70`: Integration tests for full MCP server startup → tool list → dispatch flow
