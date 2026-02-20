# Investigation Tools

MCP tools for multi-source investigation workflows: data ingestion, entity analysis,
geospatial analysis, relationship mapping, and deontic legal reasoning.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `data_ingestion_engine.py` | `DataIngestionEngine` class | Business logic for news/feed/web document ingestion (not MCP-facing) |
| `data_ingestion_tools.py` | `ingest_news_feed()`, `ingest_website()`, `ingest_document_collection()` | MCP wrappers: ingest from RSS/Atom feeds, websites, document sets |
| `entity_analysis_tools.py` | `analyze_entities()`, `cross_reference_entities()`, `build_entity_profile()` | Entity extraction, cross-referencing, profile construction |
| `geospatial_analysis_engine.py` | `GeospatialAnalysisEngine` class | Business logic for spatiotemporal event mapping (not MCP-facing) |
| `geospatial_analysis_tools.py` | `extract_locations()`, `map_events()`, `query_geographic_context()` | Extract locations from text, map events, geographic context queries |
| `relationship_timeline_tools.py` | `build_relationship_graph()`, `generate_timeline()`, `find_connections()` | Relationship mapping, event timelines, connection discovery |
| `deontological_reasoning_tools.py` | `analyze_legal_obligations()`, `check_compliance()`, `reason_about_norms()` | Deontic logic analysis: obligations, permissions, prohibitions |

## Usage

### Ingest and analyse a news feed

```python
from ipfs_datasets_py.mcp_server.tools.investigation_tools import (
    ingest_news_feed, analyze_entities, build_relationship_graph
)

# 1. Ingest articles from an RSS feed
articles = await ingest_news_feed(
    url="https://feeds.reuters.com/reuters/topNews",
    max_articles=100,
    date_after="2024-01-01"
)

# 2. Extract entities from ingested content
entities = await analyze_entities(
    content=articles["content"],
    entity_types=["Person", "Organization", "Location", "Event"]
)

# 3. Build a relationship graph
graph = await build_relationship_graph(
    entities=entities["entities"],
    source_text=articles["content"]
)
```

### Geospatial analysis

```python
from ipfs_datasets_py.mcp_server.tools.investigation_tools import (
    extract_locations, map_events
)

locations = await extract_locations(text=document_text)
events = await map_events(
    locations=locations["locations"],
    include_timeline=True
)
```

### Deontic legal analysis

```python
from ipfs_datasets_py.mcp_server.tools.investigation_tools import analyze_legal_obligations

result = await analyze_legal_obligations(
    document="/data/contract.pdf",
    jurisdiction="US-CA",
    analysis_type="obligations"   # "obligations" | "permissions" | "prohibitions"
)
```

## Core Modules

- `data_ingestion_engine.DataIngestionEngine` — ingestion business logic
- `geospatial_analysis_engine.GeospatialAnalysisEngine` — spatial business logic
- `ipfs_datasets_py.logic.TDFOL` — deontic reasoning engine

## Status

| Tool | Status |
|------|--------|
| `data_ingestion_tools` | ✅ Production ready |
| `entity_analysis_tools` | ✅ Production ready |
| `geospatial_analysis_tools` | ✅ Production ready |
| `relationship_timeline_tools` | ✅ Production ready |
| `deontological_reasoning_tools` | ✅ Production ready |
