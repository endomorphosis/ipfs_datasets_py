# Web Archiving Unified API Refactor Plan

## 1. Objectives

Build a single, production-ready API for web discovery and extraction that:
- Searches across multiple providers using a shared interface.
- Scrapes/extracts content using multiple methods with deterministic fallbacks.
- Prioritizes highest-throughput methods first while preserving quality and reliability.
- Reuses existing `web_archiving` code where viable, with low-risk incremental migration.

Primary outcomes:
- One entrypoint for "search + fetch content" workflows.
- Throughput-aware orchestration (not just static order).
- Unified observability, retry policy, and circuit breaker behavior.
- Clear deprecation path for legacy direct engine calls.

## 2. Current State (Grounded in Existing Code)

Relevant modules today:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_web_scraper.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/search_engines/base.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/search_engines/orchestrator.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/common_crawl_integration.py`
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/__init__.py`

Strengths:
- Existing search adapter abstractions and orchestrator (`MultiEngineOrchestrator`).
- Existing unified scraping module with multi-method fallback (`UnifiedWebScraper`).
- Common Crawl integration with local/remote/CLI options.
- Significant MCP tool coverage for individual providers.

Gaps to close:
- Search and scraping orchestration are split (no single "unified query + retrieve" API).
- Fallback ordering is mostly static and not throughput-adaptive.
- No common provider health score/circuit-breaker shared by search and scraping.
- Duplicate capability exposure across `processors/web_archiving` and MCP wrappers.
- Limited provider-neutral ranking/quality scoring and budget-aware execution.

## 3. Target Architecture

### 3.1 Top-level API (new facade)

Introduce `UnifiedWebArchivingAPI` as the canonical entrypoint.

Proposed module:
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_api.py`

Core operations:
1. `search(query, options) -> UnifiedSearchResponse`
2. `fetch(url, options) -> UnifiedFetchResponse`
3. `search_and_fetch(query, options) -> UnifiedPipelineResponse`
4. `archive(urls, options) -> UnifiedArchiveResponse`
5. `health() -> ProviderHealthSnapshot`

### 3.2 Provider model

Split providers by role but keep one contract style:
- Search providers: Brave, DuckDuckGo, Google CSE, GitHub, HuggingFace, OpenVerse, SerpStack, Common Crawl index queries.
- Fetch/scrape providers: Common Crawl WARC fetch, direct HTTP+BS4, Playwright, Wayback, Archive.is, Newspaper, Readability, IPWB.

Define two base interfaces:
- `SearchProvider`
- `FetchProvider`

Both implement:
- `capabilities()` (domains/content types/quotas/features)
- `execute(request)`
- `estimate_cost()`
- `health_state()`

### 3.3 Routing and execution layer

Introduce an execution planner that outputs a provider plan from policy + metrics.

New modules:
- `.../web_archiving/orchestration/policy.py`
- `.../web_archiving/orchestration/planner.py`
- `.../web_archiving/orchestration/executor.py`
- `.../web_archiving/orchestration/scoring.py`

Execution behavior:
- Select provider candidates by capability filter.
- Rank candidates by dynamic score (throughput-weighted).
- Execute top provider(s) with timeout and budget constraints.
- Apply fallback sequence with circuit breaker + jittered retries.
- Return normalized response envelope with trace info.

## 4. Throughput-First Strategy

### 4.1 Scoring formula

Use a composite score per provider and operation:
- `score = w_t * throughput_norm + w_s * success_norm + w_l * latency_norm + w_q * quality_norm + w_c * cost_norm`

Recommended default weights (throughput-priority):
- `w_t=0.40`, `w_s=0.20`, `w_l=0.15`, `w_q=0.15`, `w_c=0.10`

Notes:
- `throughput_norm`: pages/sec or results/sec from rolling window (e.g., last 5/15/60 min).
- `success_norm`: success rate with penalty for 429/5xx.
- `latency_norm`: p50/p95 latency (inverse normalized).
- `quality_norm`: extraction completeness/text quality score.
- `cost_norm`: token/API cost or infra cost.

### 4.2 Dynamic fallback policy

Fallback should be dynamic, not hardcoded:
- Primary path: highest current score for the requested operation.
- Soft fallback: next provider if timeout/error/quality below threshold.
- Hard fallback: archive sources (Common Crawl/Wayback/Archive.is) when origin fetch blocked.
- Circuit breaker open criteria: consecutive failures, high error ratio, or sustained throttling.

### 4.3 Execution modes

Support modes per request:
- `max_throughput`: aggressively parallel candidate execution, return first acceptable result.
- `balanced`: single best provider with fallback.
- `max_quality`: slower but higher-quality extraction strategy.
- `low_cost`: free/local providers first.

## 5. Unified Data Contracts

Create provider-neutral schemas (Pydantic/dataclass):
- `UnifiedSearchHit` (url/title/snippet/source/score/metadata)
- `UnifiedDocument` (url/content/text/html/title/metadata/extraction_provenance)
- `ExecutionTrace` (providers_attempted, timings, retries, fallback_reason)
- `UnifiedError` (code/provider/retryable/context)

Require all adapters to map into these contracts.

## 6. Refactoring Plan (Phased)

## Phase 0: Baseline and inventory (1-2 days)
- Inventory all existing search/fetch functions in `web_archiving` and MCP wrappers.
- Add benchmark harness for throughput/latency/success/quality per provider.
- Capture baseline metrics and publish as benchmark artifact.

Deliverables:
- Provider matrix (capabilities, auth, limits, expected throughput).
- Baseline dashboard JSON/CSV snapshots.

## Phase 1: Contract extraction (2-3 days)
- Create `contracts.py` with unified request/response/error models.
- Introduce adapter shims around existing engine modules.
- Keep old APIs operational via compatibility wrappers.

Deliverables:
- New contracts module + tests.
- Adapter compliance tests.

## Phase 2: Throughput-aware orchestrator (3-5 days)
- Implement planner/executor/scoring modules.
- Add rolling metrics collector and health registry.
- Add circuit breaker per provider and operation type.

Deliverables:
- Dynamic provider ranking and fallback engine.
- Configurable policy profile (`max_throughput`, `balanced`, etc.).

## Phase 3: Unified facade and MCP alignment (3-4 days)
- Implement `UnifiedWebArchivingAPI` with `search`, `fetch`, `search_and_fetch`, `archive`.
- Add MCP tools that call this facade instead of individual legacy functions.
- Keep legacy MCP tool names as passthrough aliases during migration.

Deliverables:
- New facade module.
- MCP bridge with feature flag routing.

## Phase 4: Migration and deprecation (2-3 days)
- Migrate internal call sites to unified facade.
- Mark legacy direct provider functions deprecated.
- Add migration guide + examples.

Deliverables:
- Updated internal imports.
- Deprecation warnings and docs.

## Phase 5: Hardening and performance tuning (ongoing 1-2 sprints)
- Tune scoring weights with real workload feedback.
- Add provider-specific optimizations (batching, cache priming, connection reuse).
- Add chaos/failure injection tests for fallback reliability.

Deliverables:
- SLO report (throughput, success, latency, quality).
- Finalized default policies per workload type.

## 7. Proposed File/Package Layout

- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_api.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/contracts.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/search/`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/fetch/`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/metrics/`
- `ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/compat/`

## 8. API Sketch

```python
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI

api = UnifiedWebArchivingAPI()

search_resp = api.search(
    query="indiana legislative laws title 35",
    options={
        "mode": "max_throughput",
        "max_results": 50,
        "provider_allowlist": ["common_crawl", "brave", "duckduckgo"],
    },
)

fetch_resp = api.fetch(
    url="https://iga.in.gov/legislative/laws/",
    options={
        "mode": "balanced",
        "min_quality": 0.70,
        "fallback_enabled": True,
    },
)

pipeline_resp = api.search_and_fetch(
    query="site:iga.in.gov title 35 offenses",
    options={
        "mode": "max_throughput",
        "max_documents": 20,
        "parallelism": 8,
    },
)
```

## 9. Testing and Validation Plan

Test layers:
- Unit tests: provider adapters, scoring, planner rules, circuit breaker transitions.
- Integration tests: real provider calls (guarded by env keys) + deterministic mocked suite.
- Regression tests: current `web_archive` and MCP behavior remains backward compatible.
- Performance tests: compare throughput and latency against baseline.

Key acceptance criteria:
- Throughput improvement target: +30% docs/min in representative workload.
- Failure recovery: fallback success >= 95% for retryable failures.
- Backward compatibility: no breaking changes for existing MCP tool signatures (during migration window).
- Observability: per-provider metrics available for every request.

## 10. Observability and Operations

Add structured telemetry fields:
- `request_id`, `operation`, `mode`, `providers_attempted`, `provider_selected`, `fallback_count`, `total_latency_ms`, `quality_score`, `error_class`.

Expose metrics (Prometheus-style or JSON counters):
- `provider_requests_total`
- `provider_success_total`
- `provider_errors_total{error_type}`
- `provider_latency_ms_bucket`
- `provider_throughput_items_per_sec`
- `circuit_breaker_state`

## 11. Risks and Mitigations

Risk: API key limits and provider throttling.
- Mitigation: quota-aware routing + circuit breaker + adaptive backoff.

Risk: Quality regression from throughput-first ordering.
- Mitigation: quality threshold gate before accepting result; configurable mode.

Risk: Duplicate or inconsistent content from mixed providers.
- Mitigation: URL/content-hash dedup and canonicalization.

Risk: Migration churn for existing callers.
- Mitigation: compatibility wrappers and staged deprecation.

## 12. Immediate Next 7-Day Execution Plan

Day 1:
- Finalize provider inventory and baseline benchmark harness.

Day 2:
- Implement `contracts.py` and adapter conformance tests.

Day 3-4:
- Build dynamic scoring + planner + fallback executor.

Day 5:
- Add `UnifiedWebArchivingAPI` facade and integrate search/fetch path.

Day 6:
- Add MCP bridge wrappers and compatibility aliases.

Day 7:
- Run performance/regression suite and tune weight defaults.

## 13. Definition of Done

The refactor is complete when:
- All new workflows use `UnifiedWebArchivingAPI`.
- Provider selection is dynamic and throughput-prioritized by default.
- Fallbacks are deterministic, observable, and validated by failure-injection tests.
- Legacy APIs remain operational with explicit deprecation timeline.
- Documentation and benchmarks are published and reproducible.
