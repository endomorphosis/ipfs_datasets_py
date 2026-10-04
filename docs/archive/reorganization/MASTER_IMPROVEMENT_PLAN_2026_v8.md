# MCP Server Master Improvement Plan 2026 — v8

*Supersedes [MASTER_IMPROVEMENT_PLAN_2026_v7.md](MASTER_IMPROVEMENT_PLAN_2026_v7.md)*

---

## Summary of All Completed Sessions

| Session | Tests Added | Focus |
|---------|------------|-------|
| 41 | 29 | Tool metadata, validators |
| 42 | 45 | Core modules: logger, mcp_interfaces, exceptions, configs, trio_bridge |
| 43 | 101 | Client, fastapi_config, trio_adapter, register_p2p_tools |
| 44 | 98 | __main__, investigation_mcp_client, simple_server, standalone_server, temporal_deontic |
| 45 | 16 | Flask deprecation: simple_server, standalone_server, __main__, executor, README/docs |
| 46 | 4 | asyncio-free CI check, Dockerfile.standalone, start_services.sh, external callers |
| 47 | 13 | Flask removed from requirements-docker.txt, Dockerfile.simple CMD/EXPOSE, start_simple_server.sh |
| 48 | 86 | server.py, runtime_router.py, server_context.py new tests |

---

## Session 48 Completed Work ✅

### Phase P — server.py, runtime_router.py, server_context.py Coverage

#### 8.1 Test File Created ✅

`tests/mcp/unit/test_server_session48.py` — 86 tests covering:

**server.py (37% coverage, up from 19%)**
- `return_text_content` / `return_tool_call_results` helpers
- `import_tools_from_directory` — nonexistent dirs, empty dirs, skips `__dunder__` / hidden files, handles `ImportError`
- `IPFSDatasetsMCPServer.__init__` — default/custom config, FastMCP-None path, P2P error paths
- `_initialize_error_reporting`, `_initialize_mcp_server`
- `_sanitize_error_context` — sensitive key patterns, scalar types, list/dict/custom types
- `_wrap_tool_with_error_reporting` — sync/async wrappers, exception re-raise
- `validate_p2p_message` — shared_token mode, missing/non-string token, valid token path, ImportError path, ConfigurationError path
- `start_stdio_server` / `start_server` — KeyboardInterrupt handling, ServerStartupError handling, ipfs_kit_url setting
- `Args` pydantic model — basic construction, host/port, ipfs_kit_url

**runtime_router.py (47% coverage, up from 0%)**
- `RuntimeMetrics` — record_request (success + error), avg/p95/p99 latency, min/max tracking, bounded list (1000 entries), to_dict keys, edge cases (empty latencies, inf min)
- `RuntimeRouter` — init (default/custom), metrics disabled, register_tool_runtime, get_tool_runtime, list_tools_by_runtime, detect_runtime (sync/async), get_metrics, reset_metrics, repr

**server_context.py (75% coverage, up from 0%)**
- `ServerConfig` — defaults and custom values
- `ServerContext` — enter/exit lifecycle, double-enter guard, properties (outside raises, inside works), register_cleanup_handler (normal + exception in handler), vector store register/get/clear-on-exit, workflow_scheduler setter
- `list_tools` — tool manager queried, empty when no manager
- `get_tool` — qualified dot-notation, simple name returns None
- `execute_tool` — success, ToolNotFoundError on missing, ToolExecutionError on exception
- Module helpers: `create_server_context`, `set_current_context`, `get_current_context`

#### 8.2 Stub Compatibility Fix ✅

- `test_server_session48.py` MCP stubs now use `MagicMock()` as base (not `types.ModuleType`) so all attribute access returns a MagicMock instead of raising `AttributeError`
- Added `mcp.server.Server` class stub (needed by `temporal_deontic_mcp_server.py`)
- Added `mcp.server.stdio.stdio_server` stub
- `FakeTool = MagicMock()` (not `Any`) to prevent `TypeError: Any cannot be instantiated`
- All 184 tests pass when `test_server_session48.py` and `test_additional_servers_session44.py` run together

---

## 7. Session 47 Completed Work ✅

### 7.1 Phase M2 — `simple_server.py` Marked for Deletion ✅

- Added `# TODO: remove in v2.0` comment at top of `simple_server.py`
- `start_simple_server.sh`: Flask invocation replaced with `python -m ipfs_datasets_py.mcp_server`; deprecation notice added

### 7.2 Phase M3/O4 — Flask Removed from Docker Requirements ✅

- `requirements-docker.txt`: `Flask>=3.1.1` → `anyio>=4.0.0`
- `Dockerfile.simple`: `EXPOSE 8000` / `EXPOSE 8080` removed; CMD updated to `["python", "-m", "ipfs_datasets_py.mcp_server"]`

### 7.3 Tests Added ✅

`tests/mcp/unit/test_flask_removal_session47.py` — 13 tests

---

## 6. Success Metrics

| Metric | Session 47 | Session 48 | Target |
|--------|-----------|-----------|--------|
| Tests passing (mcp/unit sessions 41-48) | 456 | 542 | 542+ |
| `server.py` coverage | 19% | 37% | 70%+ |
| `runtime_router.py` coverage | 0% | 47% | 70%+ |
| `server_context.py` coverage | 0% | 75% | 70% ✅ |
| `enterprise_api.py` coverage | 64% | 64% | 64% ✅ |
| `monitoring.py` coverage | 63% | 63% | 63% ✅ |

---

*Prior phases G-N remain complete as documented in v7.*
