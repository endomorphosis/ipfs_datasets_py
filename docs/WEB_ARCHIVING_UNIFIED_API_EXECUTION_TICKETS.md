# Web Archiving Unified API Execution Tickets

This document operationalizes the plan in `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` into implementation tickets that are ready to execute.

## 1. Delivery Model

Cadence:
- Sprint 1: Contracts + baseline + orchestrator core.
- Sprint 2: Unified facade + MCP alignment + migration.
- Sprint 3: Hardening + performance tuning + deprecation cleanup.

Estimate scale:
- `S`: 0.5-1 day
- `M`: 1-2 days
- `L`: 2-4 days

## 2. Ticket Backlog

## EPIC A: Baseline and Contracts

### WA-001 Provider Capability Inventory
- Size: `S`
- Goal: Create authoritative inventory of existing search/scrape providers.
- Files:
- `ipfs_datasets_py/docs/WEB_ARCHIVING_PROVIDER_MATRIX.md` (new)
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/__init__.py` (read-only mapping)
- Tasks:
- Enumerate provider name, type, auth, limits, likely throughput class, fallback suitability.
- Mark providers as `search`, `fetch`, or `hybrid`.
- Acceptance:
- Matrix includes all providers currently exposed via `web_archiving` and MCP wrappers.

### WA-002 Baseline Benchmark Harness
- Size: `M`
- Goal: Measure throughput/latency/success/quality before refactor.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/metrics/baseline_harness.py` (new)
- `ipfs_datasets_py/tests/integration_tests/web_archiving/test_baseline_harness.py` (new)
- Tasks:
- Create deterministic benchmark runner with pluggable provider list.
- Output JSON + CSV artifacts.
- Acceptance:
- Benchmark artifacts produced for at least 3 search + 3 fetch providers.

### WA-003 Unified Contracts Module
- Size: `M`
- Goal: Define provider-neutral request/response/error models.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/contracts.py` (new)
- `ipfs_datasets_py/tests/unit_tests/web_archive/test_unified_contracts.py` (new)
- Tasks:
- Add `UnifiedSearchRequest`, `UnifiedSearchResponse`, `UnifiedFetchRequest`, `UnifiedFetchResponse`, `ExecutionTrace`, `UnifiedError`.
- Add strict validation and serialization tests.
- Acceptance:
- All models pass unit tests and support JSON roundtrip.

### WA-004 Adapter Protocol Extraction
- Size: `M`
- Goal: Create typed provider protocol interfaces.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/base.py` (new)
- `ipfs_datasets_py/tests/unit_tests/web_archive/test_provider_protocols.py` (new)
- Tasks:
- Add `SearchProvider` and `FetchProvider` interface contracts.
- Include capability and health introspection methods.
- Acceptance:
- Existing adapters can conform with lightweight shims.

## EPIC B: Throughput-Aware Orchestration

### WA-005 Rolling Metrics Registry
- Size: `M`
- Goal: Track throughput, error rates, and latency by provider.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/metrics/registry.py` (new)
- `ipfs_datasets_py/tests/unit_tests/web_archive/test_metrics_registry.py` (new)
- Tasks:
- Implement rolling-window snapshots (`5m`, `15m`, `60m`).
- Record per-operation metrics (`search`, `fetch`, `archive`).
- Acceptance:
- Registry returns normalized metrics required for scoring.

### WA-006 Dynamic Scoring Engine
- Size: `M`
- Goal: Rank providers by throughput-weighted score.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/scoring.py` (new)
- `ipfs_datasets_py/tests/unit_tests/web_archive/test_scoring.py` (new)
- Tasks:
- Implement weighted score formula and normalization.
- Support profiles: `max_throughput`, `balanced`, `max_quality`, `low_cost`.
- Acceptance:
- Tests verify deterministic ranking under fixture metrics.

### WA-007 Circuit Breaker and Retry Policy
- Size: `M`
- Goal: Prevent repeated calls to degraded providers.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/resilience.py` (new)
- `ipfs_datasets_py/tests/unit_tests/web_archive/test_resilience.py` (new)
- Tasks:
- Implement per-provider state (`closed/open/half_open`).
- Add retry with exponential backoff + jitter.
- Acceptance:
- Breaker opens after threshold failures and recovers via probe requests.

### WA-008 Planner and Executor
- Size: `L`
- Goal: Generate provider plan and execute with dynamic fallback.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/planner.py` (new)
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/executor.py` (new)
- `ipfs_datasets_py/tests/unit_tests/web_archive/test_planner_executor.py` (new)
- Tasks:
- Filter by capability.
- Sort by dynamic score.
- Execute with timeout budget and fallback chain.
- Acceptance:
- Fallback order changes in response to metric degradation.

## EPIC C: Unified Facade and Integration

### WA-009 UnifiedWebArchivingAPI Facade
- Size: `L`
- Goal: Single top-level API for all workflows.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_api.py` (new)
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/__init__.py` (update exports)
- `ipfs_datasets_py/tests/unit_tests/web_archive/test_unified_api.py` (new)
- Tasks:
- Implement `search`, `fetch`, `search_and_fetch`, `archive`, `health`.
- Build from planner/executor + contracts.
- Acceptance:
- All methods return unified response models and trace metadata.

### WA-010 Integrate Existing Search Orchestrator
- Size: `M`
- Goal: Reuse/refactor `search_engines/orchestrator.py` as a provider backend.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/search_engines/orchestrator.py` (update)
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/search/multi_engine_provider.py` (new)
- Tasks:
- Wrap existing orchestrator behind new provider interfaces.
- Remove duplicated aggregation logic from new facade path.
- Acceptance:
- Legacy orchestrator remains functional while facade consumes provider wrapper.

### WA-011 Integrate UnifiedWebScraper as Fetch Backend
- Size: `M`
- Goal: Reuse existing `UnifiedWebScraper` under new provider contract.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_web_scraper.py` (minimal adaptation)
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/fetch/unified_scraper_provider.py` (new)
- Tasks:
- Adapt output to `UnifiedFetchResponse`.
- Convert static fallback list into planner-managed candidate list.
- Acceptance:
- Fetch provider can be scored and reranked dynamically.

### WA-012 MCP Unified Tool Bridge
- Size: `L`
- Goal: Add MCP tools that call unified facade while preserving old endpoints.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/unified_api_tools.py` (new)
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/__init__.py` (update exports)
- `ipfs_datasets_py/tests/unit_tests/web_archive/test_mcp_unified_api_tools.py` (new)
- Tasks:
- Add MCP tools: `unified_search`, `unified_fetch`, `unified_search_and_fetch`, `unified_archive`.
- Feature-flag routing for safe rollout.
- Acceptance:
- New MCP tools function end-to-end and old tools still work.

## EPIC D: Migration and Deprecation

### WA-013 Compatibility Layer for Legacy APIs
- Size: `M`
- Goal: Avoid breaking existing callers during migration.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/compat/legacy_wrappers.py` (new)
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/__init__.py` (update references)
- Tasks:
- Route legacy function calls through unified facade where possible.
- Emit deprecation warnings with migration hints.
- Acceptance:
- Existing imports run unchanged with warnings only.

### WA-014 Internal Call Site Migration
- Size: `L`
- Goal: Update internal code to use unified facade.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/**` (targeted call sites)
- `ipfs_datasets_py/tests/**` (updated fixtures/mocks)
- Tasks:
- Replace direct provider invocations in internal workflows.
- Update tests to assert unified contracts.
- Acceptance:
- No net behavior regressions in integration tests.

### WA-015 Deprecation Documentation
- Size: `S`
- Goal: Publish migration guide and timeline.
- Files:
- `ipfs_datasets_py/docs/WEB_ARCHIVING_MIGRATION_GUIDE.md` (new)
- `ipfs_datasets_py/README.md` (update docs links)
- Tasks:
- Map old API calls to new facade methods.
- Define deprecation windows and removal milestones.
- Acceptance:
- Guide covers all known legacy entrypoints.

## EPIC E: Reliability, Performance, and Operations

### WA-016 Failure-Injection Test Suite
- Size: `M`
- Goal: Verify fallback behavior under outages/throttling.
- Files:
- `ipfs_datasets_py/tests/integration_tests/web_archiving/test_failure_injection.py` (new)
- Tasks:
- Simulate timeouts, 429s, provider unavailability.
- Validate fallback sequence, breaker behavior, and response traces.
- Acceptance:
- Retryable failure recovery >= 95% in controlled test runs.

### WA-017 Throughput Optimization Pass
- Size: `L`
- Goal: Improve docs/min and results/sec with concurrency tuning.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/executor.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_web_scraper.py`
- Tasks:
- Tune parallelism/batching per provider.
- Add pool/session reuse where safe.
- Acceptance:
- +30% throughput versus baseline in benchmark harness.

### WA-018 Structured Telemetry and Health Endpoint
- Size: `M`
- Goal: Add production observability for provider-level performance.
- Files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/metrics/telemetry.py` (new)
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_api.py`
- Tasks:
- Emit structured events (`request_id`, provider attempts, fallback count, latency).
- Implement `health()` summary from metrics registry + breaker states.
- Acceptance:
- Telemetry includes per-provider outcomes for every unified request.

## 3. Dependency Graph

Critical path:
1. `WA-001` -> `WA-003` -> `WA-004`
2. `WA-005` -> `WA-006` -> `WA-007` -> `WA-008`
3. `WA-003` + `WA-008` -> `WA-009`
4. `WA-009` -> `WA-012` + `WA-013`
5. `WA-013` -> `WA-014` -> `WA-015`
6. `WA-009` + `WA-012` -> `WA-016` -> `WA-017` -> `WA-018`

Parallelizable workstreams:
- Contracts/protocols (`WA-003`, `WA-004`) can run while benchmark setup (`WA-002`) is built.
- MCP bridge (`WA-012`) can begin once facade signatures stabilize.
- Documentation (`WA-015`) can draft early and finalize post-migration.

## 4. Sprint Cut Plan

## Sprint 1 (Must ship)
- `WA-001`, `WA-002`, `WA-003`, `WA-004`, `WA-005`, `WA-006`
- Exit criteria:
- Contracts defined.
- Baselines captured.
- Scoring produces deterministic throughput-prioritized ranking.

## Sprint 2 (Must ship)
- `WA-007`, `WA-008`, `WA-009`, `WA-010`, `WA-011`, `WA-012`
- Exit criteria:
- Unified facade available.
- Dynamic fallback and circuit breaker active.
- MCP unified tools available behind feature flag.

## Sprint 3 (Should ship)
- `WA-013`, `WA-014`, `WA-015`, `WA-016`, `WA-017`, `WA-018`
- Exit criteria:
- Internal callers migrated.
- Reliability/performance targets validated.
- Deprecation guidance published.

## 5. Release Gates

Gate 1: Contract Stability
- No breaking changes to unified contract schemas for one sprint.

Gate 2: Reliability
- Fallback success >= 95% in failure-injection suite.

Gate 3: Performance
- Throughput >= +30% versus baseline on representative workload.

Gate 4: Compatibility
- Legacy MCP and direct provider APIs continue to function during migration window.

## 6. Suggested Owners (Role-Based)

- Platform/Architecture owner:
- `WA-003`, `WA-004`, `WA-009`, `WA-013`

- Search integration owner:
- `WA-001`, `WA-010`, search-side portions of `WA-008`

- Scraping/archiving owner:
- `WA-011`, fetch-side portions of `WA-008`, `WA-017`

- MCP/API owner:
- `WA-012`, `WA-015`

- QA/Perf owner:
- `WA-002`, `WA-016`, `WA-018`

## 7. First Implementation Slice (Recommended)

Start with this 3-ticket thin slice to derisk architecture quickly:
1. `WA-003` Unified contracts.
2. `WA-005` Rolling metrics registry (minimal viable counters).
3. `WA-009` Unified facade with `search()` only, backed by existing `MultiEngineOrchestrator`.

Why this slice:
- Produces immediate, testable value.
- Keeps migration risk low.
- Enables progressive addition of throughput-aware planning and fetch unification.
