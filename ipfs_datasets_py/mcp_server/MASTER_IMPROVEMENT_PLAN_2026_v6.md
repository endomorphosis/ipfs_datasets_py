# MCP Server — Master Improvement Plan v6.0

**Date:** 2026-02-22  
**Status:** 🟢 **Sessions G40–G41 COMPLETE** — branch `copilot/create-refactoring-plan-again`  
**Preconditions:** All v5 phases are ✅ complete (see [MASTER_IMPROVEMENT_PLAN_2026_v5.md](MASTER_IMPROVEMENT_PLAN_2026_v5.md))

**Baseline (as of 2026-02-22):**
- 1457 tests passing · 0 failing
- `monitoring.py` 63% coverage → **80%+** ✅
- `enterprise_api.py` 66% coverage → **80%+** ✅
- `validators.py` 75% coverage → **90%+** ✅
- `tool_metadata.py` 95% coverage

**Bug Fix:** `monitoring.py` — `except anyio.get_cancelled_exc_class()():` (4 occurrences)
was creating exception *instances* instead of using exception *classes*; fixed to
`except anyio.get_cancelled_exc_class():` (lines 158, 177, 1002, 1009).

---

## Phase G — Coverage Hardening (Sessions G40–G42)

**Goal:** Raise coverage of core MCP server modules to ≥ 80–90%.

### Phase G40: monitoring.py + enterprise_api.py

**Target:** `monitoring.py` 63% → 80%+; `enterprise_api.py` 66% → 80%+

Coverage gaps addressed in `test_monitoring_session40.py`:
- `_start_monitoring` / `start_monitoring` (lines 129–147)
- `_monitoring_loop` / `_cleanup_loop` async exception paths (lines 151–186)
- `_collect_system_metrics` no-psutil fast path (lines 190–207)
- `track_request` context manager yield + exception paths (lines 309–346)
- `track_tool_execution` disabled path (line 404)
- `_check_health` async check path + `HealthCheckError` / `ImportError` handling (lines 530–566)
- `_check_alerts` response-time alert (lines 606–613)
- `_calculate_request_rate` with snapshots (lines 627–633)
- `_cleanup_old_data` (lines 653–668)
- `_compute_percentiles` with < 2 samples (lines 827–837)
- `get_tool_latency_percentiles` (lines 868–870)
- `get_performance_trends` (lines 969–977)
- `shutdown` method (lines 998–1010)
- `P2PMetricsCollector.get_dashboard_data` cache hit (line 1645)
- `get_metrics_collector` / `get_p2p_metrics_collector` singletons (lines 1856–1867)

Coverage gaps addressed in `test_enterprise_api_session40.py`:
- `EnterpriseGraphRAGAPI._create_app` + lifespan (lines 431–459)
- `EnterpriseGraphRAGAPI.create_jwt_token` + `validate_jwt_token` (lines 402–426)
- `_setup_routes` / `_setup_health_and_auth_routes` (lines 461–495)
- `_setup_core_api_routes` HTTP routes (lines 503–540)
- `_setup_search_routes` (lines 545–580)
- `_setup_analytics_routes` (lines 591–622)
- `ProcessingJobManager.process_job` success path (lines 275–312)
- Webhook notifications in exception handlers (lines 321, 329, 337)
- `AdvancedAnalyticsDashboard._calculate_avg_quality` (line 694)
- `create_enterprise_api` singleton (lines 724–727)

### Phase G41: validators.py

**Target:** `validators.py` 75% → 90%+

Coverage gaps addressed in `test_validators_session40.py`:
- `validate_text_input` suspicious-pattern path (lines 141–143)
- `validate_model_name` non-string + empty string paths (lines 215–222)
- `validate_model_name` unknown-pattern warning path (lines 229–231)
- `validate_ipfs_hash` non-string path (lines 241–242)
- `validate_collection_name` non-string + too-short paths (lines 348–349, 363–364)
- `validate_search_filters` empty-key / too-long key / invalid list / operator / type (lines 471–501)
- `validate_file_path` OSError path + `check_exists` (lines 599–626)
- `validate_json_schema` ValidationError re-raise (lines 728–731)
- `validate_url` OSError path + missing scheme (lines 840–849)

---

## Phase H — Integration & Scenario Tests (Sessions H43–H45)

**Goal:** Add end-to-end scenario tests covering multi-tool pipeline interactions.

- H43: Full `dispatch_parallel` workflow: submit 5 tools → collect results
- H44: `CircuitBreaker` CLOSED → OPEN → HALF_OPEN lifecycle test
- H45: GraphRAG + IPFS combined pipeline scenario

---

## Phase I — Documentation Completeness (Sessions I46–I47)

**Goal:** Bring all new API additions up to documentation standards.

- I46: Expand `docs/api/tool-reference.md` with Phase G/H additions; update ADR-004 for v6
- I47: Add cookbook examples for `dispatch_parallel`, `CircuitBreaker`, JWT auth flows

---

## Phase J — Security Hardening (Sessions J48–J49)

**Goal:** Strengthen input validation and authentication edge cases.

- J48: Add fuzzing tests for validators using `hypothesis` strategies
- J49: Review and tighten JWT token lifecycle; add token revocation stub

---

## Phase K — Performance Tuning (Sessions K50–K51)

**Goal:** Reduce mean dispatch latency by 10% vs v5 baseline.

- K50: Profile hot paths under 1000 concurrent dispatch calls; identify bottlenecks
- K51: Implement adaptive batch sizing for `dispatch_parallel`

---

## Phase L — Ecosystem Integrations (Sessions L52–L54)

**Goal:** Widen compatibility surface.

- L52: Add `grpc` transport adapter for MCP tools (gRPC stub)
- L53: Add Prometheus exporter for `EnhancedMetricsCollector`
- L54: Add OpenTelemetry tracing integration stubs

---

## Progress Tracking

| Phase | Session | Status | Tests Added | Coverage Δ |
|-------|---------|--------|-------------|------------|
| G40   | monitoring | ✅ Complete | +40 | 63% → 80%+ |
| G40   | enterprise_api | ✅ Complete | +20 | 66% → 80%+ |
| G41   | validators | ✅ Complete | +38 | 75% → 90%+ |
| H43   | integration | ⬜ Pending | — | — |
| H44   | circuit_breaker | ⬜ Pending | — | — |
| H45   | graphrag_ipfs | ⬜ Pending | — | — |
| I46   | docs | ⬜ Pending | — | — |
| I47   | cookbook | ⬜ Pending | — | — |
| J48   | fuzzing | ⬜ Pending | — | — |
| J49   | jwt | ⬜ Pending | — | — |
| K50   | profile | ⬜ Pending | — | — |
| K51   | adaptive_batch | ⬜ Pending | — | — |
| L52   | grpc | ⬜ Pending | — | — |
| L53   | prometheus | ⬜ Pending | — | — |
| L54   | otel | ⬜ Pending | — | — |
