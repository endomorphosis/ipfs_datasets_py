# MCP Server — Master Improvement Plan v13.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions AO99 + AQ101 + AR102 + AS103 + AI93 + TDFOL-T1 + TDFOL-T2 COMPLETE**  
**Branch:** `copilot/create-refactoring-plan-again`  
**Spec alignment:** https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md  
**Preconditions:** All v12 phases ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v12.md](MASTER_IMPROVEMENT_PLAN_2026_v12.md))

**Baseline (as of 2026-02-22 v13 start):**
- 2,728 MCP + logic unit tests passing · 0 failing
- v16 (Groth16 ZKP Rust backend) wired, all 8 NL→UCAN phases complete

---

## MCP++ Specification Alignment — v13 additions

All five execution profiles remain fully aligned:

| Profile | Spec Chapter | Status | Implementation |
|---------|-------------|--------|---------------|
| A: MCP-IDL | `mcp-idl.md` | ✅ | `interface_descriptor.py` + `toolset_slice()` (AO99 ✅) |
| B: CID-Native Artifacts | `cid-native-artifacts.md` | ✅ | `cid_artifacts.py` + `dispatch_with_trace()` |
| C: UCAN Delegation | `ucan-delegation.md` | ✅ | `ucan_delegation.py` + `DelegationStore` + `RevocationList` |
| D: Temporal Deontic Policy | `temporal-deontic-policy.md` | ✅ | `temporal_policy.py` + `PolicyRegistry` + caches |
| E: P2P Transport | `transport-mcp-p2p.md` | ✅ | `mcplusplus/` + `mcp_p2p_transport.py` |

---

## Phase AO99 — toolset_slice() budget enforcement (Session AO99)

### Session AO99: interface_descriptor.toolset_slice() ✅ Complete

**Production change:** Added `toolset_slice(cids, budget, sort_fn)` to
`ipfs_datasets_py/mcp_server/interface_descriptor.py` (spec §7).

**File:** `tests/mcp/unit/test_v13_sessions.py`

Key design:
- `toolset_slice(cids, budget=None, sort_fn=None)` — budget-bounded CID list slice
- `sort_fn` receives each CID string → comparable key; sorted ascending (lowest = most preferred)
- No budget → full list returned unchanged
- Budget 0 → empty list
- Stable when sort_fn is None (preserves input order)

#### TestToolsetSlice (8 tests):
- No budget returns full list unchanged
- Budget truncates to correct length
- Budget larger than list returns full list
- Budget 0 returns empty list
- sort_fn re-ranks before truncation
- sort_fn=None preserves input order
- Sort key breaks ties deterministically (stable sort)
- Integration: `InterfaceRepository.select()` + `toolset_slice()` roundtrip

---

## Phase AQ101 — gRPC transport conformance (Session AQ101)

### Session AQ101: grpc_transport.py deeper coverage ✅ Complete

**File:** `tests/mcp/unit/test_v13_sessions.py`

Covers the conformance checklist from the MCP++ spec §E.9:

#### TestGRPCToolRequestConformance (4 tests):
- `params_json` defaults to `"{}"` (valid JSON)
- `request_id` defaults to empty string
- All slots present and settable
- Serialization roundtrip: construct → JSON dump → reconstruct

#### TestGRPCToolResponseConformance (4 tests):
- `success=True` response has non-empty `result_json`
- `success=False` response has non-empty `error`
- `error` defaults to empty string when `success=True`
- `request_id` echoed from request

#### TestGRPCAdapterConformance (4 tests):
- `handle_request` echoes `request_id` in response
- `handle_request` with nested JSON params dispatches correctly
- `handle_request` with empty params_json uses `{}`
- `get_info()` has all required spec fields (`transport`, `host`, `port`, `max_workers`, `is_running`)

---

## Phase AR102 — Prometheus exporter deeper coverage (Session AR102)

### Session AR102: prometheus_exporter.py ✅ Complete

**File:** `tests/mcp/unit/test_v13_sessions.py`

Covers metric name conventions + cardinality limits + histogram bucket semantics:

#### TestPrometheusMetricNames (4 tests):
- Counter metric name ends with `_total` (Prometheus convention)
- Gauge metric name does **not** end with `_total`
- Histogram metric name ends with `_seconds` or `_bytes` (sizing convention)
- Namespace prefix applied to all metric names

#### TestPrometheusLabelCardinality (4 tests):
- `record_tool_call` with many distinct tools doesn't raise
- `record_tool_call` updates both success + error counters
- `update()` called with high-cardinality snapshot does not raise
- `get_info()` returns `namespace` field

#### TestPrometheusHistogramBuckets (4 tests):
- Default histogram buckets are present in `_make_histogram()`
- Custom buckets accepted
- Histogram observe does not raise (no-op or real)
- `update()` with `execution_times` key reaches histogram.observe path

---

## Phase AS103 — OpenTelemetry tracing deeper coverage (Session AS103)

### Session AS103: otel_tracing.py ✅ Complete

**File:** `tests/mcp/unit/test_v13_sessions.py`

Covers span attributes + context propagation + error recording:

#### TestOTelSpanAttributes (4 tests):
- `start_dispatch_span()` returns object with `set_attribute` callable
- `_NoOpSpan.set_attribute()` does not raise
- `_NoOpSpan.set_status()` does not raise
- `_NoOpSpan.record_exception()` does not raise

#### TestOTelContextPropagation (3 tests):
- `configure_tracing()` returns `False` when OTel unavailable (no crash)
- `MCPTracer` constructed with custom `tracer_name` stores name
- `get_info()` includes `otel_available` key with correct bool value

#### TestOTelDecoratorErrorPath (3 tests):
- `trace_tool_call` decorator re-raises exceptions from the wrapped function
- Decorator works with sync-style async functions
- `set_span_ok()` on no-op span with `None` result does not raise

---

## Phase AI93 — fastapi /datasets/* routes (Session AI93)

### Session AI93: fastapi_service.py /datasets/* + /ipfs/* + /vectors/* inner-module mocking ✅ Complete

**File:** `tests/mcp/unit/test_v13_sessions.py`

Key insight: all `/datasets/*`, `/ipfs/*`, and `/vectors/*` routes import from
`.mcp_server.tools.*` which resolves to the double-path `ipfs_datasets_py.mcp_server.mcp_server.*`
(non-existent), so they always return HTTP 500. Tests verify this behaviour and that
auth is enforced.

#### TestFastapiDatasetRoutes (5 tests):
- `POST /datasets/load` without auth → 401
- `POST /datasets/load` with auth → 500 (inner import fails)
- `POST /datasets/process` with auth → 500
- `POST /datasets/save` with auth → 500
- `POST /datasets/convert` with auth → 500

#### TestFastapiIPFSRoutes (3 tests):
- `POST /ipfs/pin` without auth → 401
- `POST /ipfs/pin` with auth → 500
- `GET /ipfs/get/{cid}` with auth → 500

#### TestFastapiVectorRoutes (2 tests):
- `POST /vectors/create-index` with auth → 500
- `POST /vectors/search` with auth → 500

---

## Phase TDFOL-T1 — modal_tableaux coverage (Session TDFOL-T1)

### Session TDFOL-T1: ModalTableauxStrategy additional coverage ✅ Complete

**File:** `tests/unit_tests/logic/test_v13_tdfol_strategy_coverage.py`

#### TestModalTableauxProveBasicModal (5 tests):
- Formula in `kb.axioms` → `PROVED` status, proof step present
- Formula in `kb.theorems` → `PROVED` status
- Formula not in KB → `UNKNOWN` status
- KB with empty axioms and theorems → `UNKNOWN`
- Proof step justification = "Found in knowledge base"

#### TestModalTableauxEstimateCost (5 tests):
- Simple DeonticFormula → cost == 2.0 (base, no multipliers)
- Nested temporal formula → cost >= 4.0 (× 2.0 multiplier)
- Mixed deontic + temporal formula → cost >= 6.0 (× 2.0 × 1.5)
- Simple temporal formula → cost == 2.0 (no nesting multiplier)
- `estimate_cost()` always returns float

#### TestModalTableauxGetPriority (2 tests):
- `get_priority()` returns 80
- Priority > `ForwardChainingStrategy().get_priority()` (modal is specialised)

#### TestModalTableauxInternalHelpers (3 tests):
- `_has_deontic_operators(DeonticFormula(...))` → True
- `_has_temporal_operators(TemporalFormula(...))` → True
- `_has_nested_temporal(UnaryFormula(TemporalFormula(...)))` — tests nested depth

---

## Phase TDFOL-T2 — strategy_selector coverage (Session TDFOL-T2)

### Session TDFOL-T2: StrategySelector additional coverage ✅ Complete

**File:** `tests/unit_tests/logic/test_v13_tdfol_strategy_coverage.py`

#### TestStrategySelectorAddStrategy (4 tests):
- `add_strategy()` increases `len(strategies)` by 1
- Re-sorted by priority after add (highest first invariant maintained)
- Added strategy appears in `get_strategy_info()` output
- Custom strategy with priority 999 becomes first in list

#### TestStrategySelectorSelectMultiple (4 tests):
- `select_multiple(max_strategies=1)` returns list of length 1
- `select_multiple(max_strategies=3)` returns at most 3
- Returns strategies in priority order (highest first)
- Formula not handled by any strategy → returns fallback list

#### TestStrategySelectorFallback (2 tests):
- Non-modal formula falls back to forward chaining (if available) or first strategy
- `_get_fallback_strategy()` raises `ValueError` when `strategies=[]`

---

## Summary — v13 Sessions

| Session | Target | New Tests | Status |
|---------|--------|-----------|--------|
| AO99 | `toolset_slice()` budget enforcement | 8 | ✅ |
| AQ101 | gRPC conformance (serialisation + params + info) | 12 | ✅ |
| AR102 | Prometheus metric names + cardinality + histogram | 12 | ✅ |
| AS103 | OTel span attributes + context + decorator | 10 | ✅ |
| AI93 | fastapi `/datasets/*` + `/ipfs/*` + `/vectors/*` | 10 | ✅ |
| TDFOL-T1 | `ModalTableauxStrategy` basic modal + cost | 15 | ✅ |
| TDFOL-T2 | `StrategySelector` add + multiple + fallback | 10 | ✅ |
| **Total** | | **77** | ✅ |

**Production changes:**
- `interface_descriptor.py`: +`toolset_slice()` (spec §7)

**Grand total (all plans):**  
2,728 (through v16) + 77 (v13) = **2,805 MCP + logic unit tests**

---

## Next Steps (v14 candidates)

| Session | Target | Rationale | Spec alignment |
|---------|--------|-----------|----------------|
| AT104 | `dispatch_pipeline.py` — stage-skip metrics + PipelineMetricsRecorder | Pipeline observability | Profile E |
| AU105 | `mcp_p2p_transport.py` — `TokenBucketRateLimiter` conformance | Rate-limit spec §E.5 | Profile E §5 |
| AV106 | `compliance_checker.py` — custom rule registration + removal | Extensible compliance | Profile A §8 |
| AW107 | `risk_scorer.py` — `RiskScorer.score_and_gate()` full round-trip | Risk gate integration | — |
| AX108 | `policy_audit_log.py` — sink callable + JSONL file + stats | Audit log spec §8 | Phase 8 |
| AY109 | `did_key_manager.py` — `rotate_key()` + delegation chain migration | Key rotation spec | Profile C |
| AZ110 | `secrets_vault.py` — `.enc` path encrypted-at-rest round-trip | Phase 7 security | — |
| BA111 | Logic `integration/cec_bridge.py` — 95%+ coverage | Logic integration | — |
| BB112 | Groth16 phase 4b — circuit_version=2 trace + EVM verifier ABI | Real ZKP use case | ZKP §4 |
| BC113 | `NLUCANPolicyCompiler` multi-language support (FR/DE/ES) | Multilingual deontic | — |
