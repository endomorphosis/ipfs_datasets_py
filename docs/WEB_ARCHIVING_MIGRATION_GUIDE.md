# Web Archiving Migration Guide

This guide explains how to migrate from legacy web archiving search/scrape entrypoints to the unified API introduced in `ipfs_datasets_py.processors.web_archiving.unified_api`.

## 1. Why Migrate

The unified API provides:
- Throughput-prioritized provider ordering.
- Circuit-breaker + retry fallback behavior.
- Provider-neutral request/response contracts.
- Unified observability and execution traces.
- A single MCP-facing surface for `search`, `fetch`, and `search_and_fetch`.

## 2. New Canonical Entry Points

Python API:
- `ipfs_datasets_py.processors.web_archiving.UnifiedWebArchivingAPI`

MCP tools:
- `unified_search`
- `unified_fetch`
- `unified_search_and_fetch`
- `unified_health`

Compatibility wrappers (deprecated but supported during migration):
- `legacy_search_web`
- `legacy_fetch_url`
- `legacy_search_and_fetch`

## 3. Legacy -> Unified Mapping

| Legacy pattern | Replace with | Notes |
|---|---|---|
| Direct multi-engine ad hoc search orchestration | `UnifiedWebArchivingAPI.search()` | Uses planner/scorer/executor pipeline. |
| Direct URL scraping utility calls | `UnifiedWebArchivingAPI.fetch()` | Uses unified scraper backend + standardized response. |
| Search then custom fetch loop | `UnifiedWebArchivingAPI.search_and_fetch()` | Returns combined envelope with documents. |
| Legacy wrappers in existing callers | Keep wrapper now, plan direct API migration | Wrappers emit `DeprecationWarning`. |

## 4. Python Migration Examples

### 4.1 Search

Old style (conceptual):
```python
# manual orchestrator/provider wiring
results = custom_search_fn(query="indiana code", max_results=20)
```

New style:
```python
from ipfs_datasets_py.processors.web_archiving import (
    OperationMode,
    UnifiedSearchRequest,
    UnifiedWebArchivingAPI,
)

api = UnifiedWebArchivingAPI()
response = api.search(
    UnifiedSearchRequest(
        query="indiana code",
        max_results=20,
        mode=OperationMode.MAX_THROUGHPUT,
        provider_allowlist=["brave", "duckduckgo", "google_cse"],
    )
)

if response.success:
    for hit in response.results:
        print(hit.url, hit.source)
```

### 4.2 Fetch

Old style (conceptual):
```python
doc = some_scraper.fetch("https://example.com")
```

New style:
```python
from ipfs_datasets_py.processors.web_archiving import UnifiedFetchRequest, UnifiedWebArchivingAPI

api = UnifiedWebArchivingAPI()
response = api.fetch(UnifiedFetchRequest(url="https://example.com"))

if response.success and response.document:
    print(response.document.title)
```

### 4.3 Search and Fetch Pipeline

```python
from ipfs_datasets_py.processors.web_archiving import UnifiedSearchRequest, UnifiedWebArchivingAPI

api = UnifiedWebArchivingAPI()
result = api.search_and_fetch(
    UnifiedSearchRequest(query="site:iga.in.gov title 35"),
    max_documents=5,
)

print(result["documents_count"])
```

## 5. MCP Migration Examples

### 5.1 Unified Search

```python
result = await unified_search(
    query="indiana statutes title 35",
    max_results=25,
    mode="max_throughput",
    provider_allowlist=["brave", "duckduckgo"],
)
```

### 5.2 Unified Fetch

```python
result = await unified_fetch(
    url="https://example.com/law",
    mode="balanced",
)
```

### 5.3 Unified Search and Fetch

```python
result = await unified_search_and_fetch(
    query="indiana code title 35",
    max_results=20,
    max_documents=5,
    mode="max_throughput",
)
```

## 6. Deprecation Policy

Current state:
- Legacy wrappers remain available through `web_archiving.compat.legacy_wrappers`.
- Wrappers produce `DeprecationWarning` to aid migration.

Recommended migration window:
- Phase 1: migrate new call sites immediately to unified API.
- Phase 2: migrate existing internal call sites to unified API.
- Phase 3: remove wrapper usage from application code.

## 7. Validation Checklist

After migration, verify:
- Search responses include execution trace and provider attempts.
- Fetch responses include normalized document envelope.
- Throughput mode uses ranked provider order in metadata.
- Existing flows still function where wrappers are temporarily retained.

## 8. Troubleshooting

Issue: `status=error` from unified search.
- Check `errors` and `trace.providers_attempted` in response payload.
- Use `unified_health` to inspect provider metrics and breaker state.

Issue: Legacy imports still in use.
- Search for `legacy_search_web|legacy_fetch_url|legacy_search_and_fetch` and replace with direct facade calls.

Issue: tests fail because of package-level import side effects in MCP tools.
- Prefer module-level imports in tests for focused wrapper validation when optional dependencies are absent.
