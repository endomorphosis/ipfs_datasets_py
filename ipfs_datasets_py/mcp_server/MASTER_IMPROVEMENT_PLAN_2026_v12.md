# MCP Server — Master Improvement Plan v12.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions W80 + AG91 + AH92 + AE89/AF90 + AJ94 COMPLETE**  
**Branch:** `copilot/create-refactoring-plan-again`  
**Spec alignment:** https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md  
**Preconditions:** All v11 phases ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v11.md](MASTER_IMPROVEMENT_PLAN_2026_v11.md))

**Baseline (as of 2026-02-22 v12 start):**
- 2,305 MCP unit tests passing · 0 failing (from v11 grand total)
- All v11 sessions X81–AD88 complete (108 new tests + 3 new production modules)

---

## MCP++ Specification Alignment — v12 additions

All new production code in this plan is aligned to the MCP++ spec published at
[github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md](https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md).

| Profile | Spec Chapter | Status | Implementation |
|---------|-------------|--------|---------------|
| A: MCP-IDL | `mcp-idl.md` | ✅ | `interface_descriptor.py` + HTM hook |
| B: CID-Native Artifacts | `cid-native-artifacts.md` | ✅ | `cid_artifacts.py` + `dispatch_with_trace()` |
| C: UCAN Delegation | `ucan-delegation.md` | ✅ **New module** | `ucan_delegation.py` |
| D: Temporal Deontic Policy | `temporal-deontic-policy.md` | ✅ | `temporal_policy.py` + `PolicyRegistry` |
| E: P2P Transport | `transport-mcp-p2p.md` | ✅ Existing | `mcplusplus/` wrappers |

---

## Phase W — HTM schema cache + lazy load (Session W80)

### Session W80: ToolCategory.get_tool_schema cache + HierarchicalToolManager deep paths ✅ Complete

**File:** `tests/mcp/unit/test_v12_htm_schema_session80.py` — **27 new tests**

#### TestToolCategorySchemaCache (5 tests):
- Cache miss → cache hit path; `_cache_misses`/`_cache_hits` counters correct
- `clear_schema_cache()` resets all counters and evicts entries
- `cache_info()` has `hits`/`misses`/`size` keys
- Unknown tool returns `None`
- Schema has `required=True`/`False` based on default presence

#### TestHTMGetToolSchema (3 tests):
- `get_tool_schema(cat, tool)` → `{"status": "success", "schema": {...}}`
- Unknown category → error dict
- Unknown tool → error dict

#### TestGetToolSchemaCid (3 tests, AE89):
- Returns `sha256:` prefixed CID string
- CID is deterministic for same function
- Raises `ValueError` when tool not found

#### TestLazyLoadCategory (3 tests):
- Loader callable invoked on first `get_category()` call; loader is popped from `_lazy_loaders`
- Lazy category appears in `list_categories()` output before loading
- Lazy category is marked `"lazy": True` before loading

#### TestGetResultCache (2 tests):
- Graceful `ImportError` → returns `None` (no crash)
- Pre-seeded sentinel returned on second call (cache of the cache)

#### TestDispatchShuttingDown (5 tests):
- `_shutting_down=True` → error dict with "shutting down"
- Tool not found → error dict
- Tool raises `TypeError` → error dict
- Successful sync tool → result dict with `request_id`
- Successful async tool → result dict

#### TestDispatchWithTrace (4 tests, AF90):
- `_trace` key present in result
- `intent_cid` is stable (deterministic)
- `ExecutionEnvelope.is_complete()` is `True`
- `interface_cid` forwarded to trace

#### TestModuleLevelWrappers (2 tests):
- `tools_get_schema(cat, tool)` delegates to manager
- `tools_dispatch(cat, tool, params)` delegates to manager

---

## Phase AG91 — PolicyRegistry (Session AG91)

### Session AG91: temporal_policy.PolicyRegistry + JSON persistence ✅ Complete

**Production change:** Added `PolicyRegistry` class + `get_policy_registry()` singleton to
`ipfs_datasets_py/mcp_server/temporal_policy.py`.

**File:** `tests/mcp/unit/test_v12_spec_extensions_session91_92.py` — **13 new tests**

Key design:
- `PolicyRegistry` wraps `PolicyEvaluator` with additional metadata tracking
- `register()` stores `policy_cid → policy_id` mapping
- `list_policies()` returns list of `{policy_id, policy_cid}` dicts
- `evaluate()` delegates to inner evaluator
- `save(path)` → JSON file of all registered policies
- `load(path) → int` → loads policies from JSON, returns count
- `get_policy_registry()` → module-level lazy singleton

#### TestPolicyRegistry (13 tests):
- `register()` returns `sha256:` CID
- `list_policies()` empty initially
- `list_policies()` after register returns 1 entry
- Register 3 policies → list has 3
- `evaluate()` → `ALLOW` for permitted tool
- `evaluate()` → `DENY` for unknown policy CID
- `evaluate()` → `DENY` for prohibited tool
- `evaluator` property returns `PolicyEvaluator`
- `save()` creates JSON file with correct structure
- `load()` restores policies into new registry
- `load()` allows evaluation after roundtrip
- Global `get_policy_registry()` returns singleton

---

## Phase AH92 — UCAN Delegation (Session AH92)

### Session AH92: ucan_delegation.py — Profile C ✅ Complete

**New module:** `ipfs_datasets_py/mcp_server/ucan_delegation.py`  
**File:** `tests/mcp/unit/test_v12_spec_extensions_session91_92.py` — **30 new tests**

Key design (aligned to spec Profile C):
- `Capability(resource, ability)` — `matches()` supports `"*"` wildcards on both sides
- `DelegationToken` — `cid` (lazy sha256), `is_valid()` (temporal window), `to_dict()`/`from_dict()`
- `DelegationChain` — ordered token list, `is_valid_chain()`, `covers(resource, ability)`
- `DelegationEvaluator` — `add_token()`, `get_token()`, `build_chain(leaf_cid)`, `can_invoke()`
- `get_delegation_evaluator()` — process-global singleton

#### TestCapability (5 tests):
- Exact match, wrong ability no match, wildcard ability, wildcard resource, both wildcards

#### TestDelegationToken (10 tests):
- CID starts `sha256:`, deterministic, different audience → different CID
- `is_valid()`: no expiry, future expiry, past expiry, `not_before` future
- `to_dict()` has required keys, `from_dict()` roundtrip preserves structure

#### TestDelegationChain (8 tests):
- `root_issuer`/`leaf_audience`, valid chain, broken chain invalid
- Expired token invalid, `covers()` match, `covers()` no match, empty chain

#### TestDelegationEvaluator (8 tests + global singleton):
- `add_token()` returns CID, `get_token()` retrieves, unknown CID returns None
- `can_invoke()`: success, wrong principal, unknown CID, unmatched capability
- `build_chain()` single token, global singleton

---

## Phase AE89/AF90 Integration Smoke Tests

**File:** `tests/mcp/unit/test_v12_spec_extensions_session91_92.py` — **4 tests**

- All four spec modules (`interface_descriptor`, `cid_artifacts`, `ucan_delegation`, `temporal_policy`) import cleanly
- `compute_cid` + `artifact_cid` give identical results for same data (cross-module CID stability)
- End-to-end: `IntentObject → PolicyEvaluator → DecisionObject`
- End-to-end: UCAN chain grants capability + policy registry allows → both succeed

---

## Phase AJ94 — monitoring loop branches (Session AJ94)

### Session AJ94: _monitoring_loop + _cleanup_loop complete branch coverage ✅ Complete

**File:** `tests/mcp/unit/test_v12_monitoring_loop_session94.py` — **10 new tests**

Strategy: patch `_collect_system_metrics` / `_cleanup_old_data` to raise desired exceptions;
patch `monitoring.anyio.sleep` to count calls and raise `Cancelled` on exit iteration.

#### TestMonitoringLoopCancelled (1 test):
- `_collect_system_metrics` raises `Cancelled` → loop breaks, no re-raise

#### TestMonitoringLoopMetricsCollectionError (1 test):
- `MetricsCollectionError` → `sleep(60)` is called

#### TestMonitoringLoopOSError (1 test):
- `OSError` → `sleep(60)` is called

#### TestMonitoringLoopGenericException (1 test):
- Generic `RuntimeError` → `sleep(60)` is called

#### TestMonitoringLoopHappyPath (1 test):
- No exception → `sleep(30)` called

#### TestCleanupLoopCancelled (1 test):
- `_cleanup_old_data` raises `Cancelled` → loop breaks cleanly

#### TestCleanupLoopMonitoringError (1 test):
- `MonitoringError` → re-raised immediately (not swallowed)

#### TestCleanupLoopIOError (1 test):
- `IOError` → `sleep(3600)` called

#### TestCleanupLoopGenericException (1 test):
- Generic `ValueError` → `sleep(3600)` called

#### TestCleanupLoopHappyPath (1 test):
- No exception → `sleep(3600)` called

---

## Summary — v12 Sessions

| Session | Target | New Tests | Status |
|---------|--------|-----------|--------|
| W80 | HTM schema cache + lazy load + dispatch_with_trace | 27 | ✅ |
| AG91 | `PolicyRegistry` + JSON persistence | 13 | ✅ |
| AH92 | **Profile C: UCAN Delegation** `ucan_delegation.py` | 30 | ✅ |
| AE89/AF90 | Spec module integration smoke tests | 4 | ✅ |
| AJ94 | `monitoring._monitoring_loop` + `_cleanup_loop` all branches | 10 | ✅ |
| **Total** | | **84** | ✅ |

**Production changes:**
- `hierarchical_tool_manager.py`: +`get_tool_schema_cid()` + `dispatch_with_trace()`
- `temporal_policy.py`: +`PolicyRegistry` + `get_policy_registry()`
- New: `ucan_delegation.py` (Profile C — UCAN delegation chain)

**Grand total (all plans):**  
2,305 (through v11) + 84 (v12) = **2,389 MCP unit tests**

---

## Next Steps (v13 candidates)

| Session | Target | Rationale | Spec alignment |
|---------|--------|-----------|----------------|
| AI93 | `fastapi_service.py` `/datasets/*` routes (inner-module mocked) | V77 deferred — 100+ uncovered stmts | — |
| AK95 | Enterprise analytics full round-trip: submit job → process → query | Y83 deferred | — |
| AL96 | Coverage gap sweep: push all mcp_server modules to ≥90% | Final consolidation | — |
| AM97 | P2P conformance tests aligned to `mcp+p2p` spec §9 interop checklist | Wire-level conformance | Profile E §9 |
| AN98 | `ucan_delegation.py` extended: `DelegationStore` + revocation list | UCAN revocation (spec §7) | Profile C |
| AO99 | `interface_descriptor.py` — `toolset_slice()` budget enforcement tests | `select()` budget deep paths | Profile A §7 |
| AP100 | `PolicyEvaluator` temporal window edge cases (at boundary, expired obligations) | Profile D §4 | Profile D |
| AQ101 | gRPC transport: `GRPCToolRequest`/`Response` serialisation conformance | `grpc_transport.py` deeper coverage | Profile E |
| AR102 | Prometheus exporter: metric names + label cardinality tests | `prometheus_exporter.py` deeper coverage | Observability |
| AS103 | OpenTelemetry tracing: span attributes + context propagation | `otel_tracing.py` deeper coverage | Observability |
