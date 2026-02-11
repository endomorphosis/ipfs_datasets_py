# Common Crawl Search Engine Integration

This document describes the integration of the `common_crawl_search_engine` submodule into `ipfs_datasets_py`, providing advanced web archiving and internet search capabilities as a fallback/redundancy system for RAG data retrieval.

## Overview

The Common Crawl Search Engine integration provides fast, scalable access to Common Crawl archives without being bottlenecked by Cloudflare or other access restrictions. The system supports both local and remote deployment modes to accommodate the large Common Crawl URL indexes.

## Architecture

### Three Integration Modes

1. **Local/Embedded Mode** - Direct package imports when submodule is available locally
2. **Remote MCP JSON-RPC Mode** - Connect to standalone MCP server on another machine  
3. **CLI Mode** - Execute CLI commands (local or remote via SSH)

### Four Access Methods

The functionality is exposed through multiple interfaces:

1. **Package Exports** - Python API via `CommonCrawlSearchEngine` class
2. **CLI Tools** - Command-line interface via `ipfs-datasets common-crawl`
3. **MCP Server Tools** - AI assistant access via MCP protocol
4. **Dashboard Integration** - Web UI as a subdashboard

## Installation

### Initialize the Submodule

```bash
cd /path/to/ipfs_datasets_py
git submodule update --init
```

The submodule is located at:
```
ipfs_datasets_py/web_archiving/common_crawl_search_engine/
```

### Install Dependencies

The Common Crawl Search Engine has its own dependencies. Install them:

```bash
cd ipfs_datasets_py/web_archiving/common_crawl_search_engine
pip install -e .
```

## Usage

### 1. Python Package API

#### Local Mode (Default)

```python
from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine

# Initialize in local mode
engine = CommonCrawlSearchEngine(mode="local")

# Check if available
if engine.is_available():
    # Search for a domain
    results = engine.search_domain("example.com", max_matches=100)
    
    for result in results:
        print(f"URL: {result['url']}")
        print(f"Timestamp: {result['timestamp']}")
        print(f"WARC: {result['warc_filename']}")
        
    # List collections
    collections = engine.list_collections()
    
    # Get collection info
    info = engine.get_collection_info("CC-MAIN-2024-10")
    
    # Fetch WARC record
    content = engine.fetch_warc_record(
        warc_filename="crawl-data/...",
        warc_offset=12345,
        warc_length=1000
    )
```

#### Remote Mode (Connect to Standalone Server)

```python
from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine

# Initialize in remote mode
engine = CommonCrawlSearchEngine(
    mode="remote",
    mcp_endpoint="http://ccindex-server.example.com:8787"
)

# Same API as local mode
results = engine.search_domain("example.com", max_matches=50)
```

#### CLI Mode

```python
from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine

# Initialize in CLI mode (uses ccindex CLI tool)
engine = CommonCrawlSearchEngine(mode="cli")

# Or remote CLI via SSH
engine = CommonCrawlSearchEngine(
    mode="cli",
    ssh_host="ccindex-server.example.com"
)

# Same API
results = engine.search_domain("example.com")
```

### 2. CLI Tools

```bash
# Search for a domain (local mode)
ipfs-datasets common-crawl search example.com --max-matches 50

# Search with specific collection
ipfs-datasets common-crawl search example.com --collection CC-MAIN-2024-10

# Search using remote MCP server
ipfs-datasets common-crawl search example.com \
    --mode remote \
    --endpoint http://ccindex-server:8787

# List collections
ipfs-datasets common-crawl collections --json

# Get collection info
ipfs-datasets common-crawl info CC-MAIN-2024-10

# Fetch WARC record
ipfs-datasets common-crawl fetch \
    crawl-data/CC-MAIN-2024-10/segments/.../warc/file.warc.gz \
    12345 1000

# Show configuration
ipfs-datasets common-crawl config
```

### 3. MCP Server Tools

The Common Crawl integration is exposed via MCP tools for AI assistant access:

**Available Tools:**
- `search_common_crawl_advanced` - Search Common Crawl with advanced options
- `fetch_warc_record_advanced` - Fetch WARC records
- `list_common_crawl_collections_advanced` - List available collections
- `get_common_crawl_collection_info_advanced` - Get collection metadata

**Example Usage in MCP Client:**

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    search_common_crawl_advanced
)

result = await search_common_crawl_advanced(
    domain="example.com",
    max_matches=100,
    collection="CC-MAIN-2024-10"
)

print(result)  # Returns structured result dict
```

### 4. Dashboard Integration

The Common Crawl dashboard can be integrated as a subdashboard:

```python
from ipfs_datasets_py.dashboards import common_crawl_dashboard

# Create dashboard integration
integration = common_crawl_dashboard.create_dashboard_integration(
    mode="embedded",  # or "remote"
    port=8788
)

# Start embedded dashboard
integration.start_embedded_dashboard()

# Get dashboard URL
url = integration.get_dashboard_url()
print(f"Dashboard available at: {url}")

# Get iframe config for embedding
iframe_config = integration.get_iframe_config()

# Get navigation item for main menu
nav_item = integration.get_nav_item()

# Health check
health = integration.health_check()
```

#### Register with Flask App

```python
from flask import Flask
from ipfs_datasets_py.dashboards.common_crawl_dashboard import register_dashboard_routes

app = Flask(__name__)

# Register Common Crawl dashboard routes
register_dashboard_routes(app, prefix="/subdashboard/common-crawl")

# Dashboard will be available at:
# - /subdashboard/common-crawl (main dashboard iframe)
# - /subdashboard/common-crawl/health (health check)
# - /subdashboard/common-crawl/config (configuration)
```

## Configuration

### Environment Variables

The Common Crawl Search Engine uses several environment variables:

```bash
# State directory
export CCINDEX_STATE_DIR="state"

# Event logging
export CCINDEX_EVENT_LOG_PATH="state/ccindex_events.jsonl"

# Brave resolve strategy
export BRAVE_RESOLVE_STRATEGY="domain_url_join_parallel"

# Rowgroup settings
export BRAVE_RESOLVE_ROWGROUP_SLICE_MODE="auto"
export BRAVE_RESOLVE_ROWGROUP_WORKERS="8"
export BRAVE_RESOLVE_SKIP_LEGACY_SCHEMA="1"

# Index directories (optional)
export BRAVE_RESOLVE_ROWGROUP_INDEX_DIR="/path/to/collection/indexes"
export BRAVE_RESOLVE_ROWGROUP_YEAR_DIR="/path/to/year/indexes"
```

### Python Configuration

```python
engine = CommonCrawlSearchEngine(
    mode="local",
    master_db_path="/path/to/master.duckdb",  # Optional
    state_dir="state",  # Default
    rowgroup_index_dir="/path/to/indexes",  # Optional
    year_index_dir="/path/to/year/indexes"  # Optional
)
```

## Deployment Scenarios

### Scenario 1: Small-Scale Local Development

For development and small-scale use, run everything locally:

```python
# Local mode with embedded indexes
engine = CommonCrawlSearchEngine(mode="local")
```

### Scenario 2: Large-Scale Remote Deployment

For production with large URL indexes, run the MCP server on a dedicated machine:

**On the index server:**
```bash
# Start MCP server
ccindex-mcp-server --mode tcp --host 0.0.0.0 --port 8787

# Or start dashboard (includes MCP endpoint)
ccindex-dashboard --host 0.0.0.0 --port 8787
```

**On client machines:**
```python
# Connect via remote mode
engine = CommonCrawlSearchEngine(
    mode="remote",
    mcp_endpoint="http://ccindex-server.example.com:8787"
)
```

### Scenario 3: Hybrid with Dashboard

Run the dashboard with iframe embedding:

```python
from ipfs_datasets_py.dashboards.common_crawl_dashboard import CommonCrawlDashboardIntegration

# Remote dashboard
integration = CommonCrawlDashboardIntegration(
    mode="remote",
    remote_endpoint="http://ccindex-server:8787"
)

# Get iframe config for main dashboard
config = integration.get_iframe_config()
```

## Testing

Run the integration tests:

```bash
pytest tests/integration/test_common_crawl_submodule.py -v
```

The tests verify:
- Submodule is properly initialized
- Integration modules can be imported
- MCP tools are registered
- Dashboard integration is available
- Graceful fallback when submodule is unavailable

## Troubleshooting

### Submodule Not Initialized

**Error:** `Common Crawl Search Engine not available`

**Solution:**
```bash
git submodule update --init
cd ipfs_datasets_py/web_archiving/common_crawl_search_engine
pip install -e .
```

### Remote Server Unreachable

**Error:** `request failed: ConnectionError`

**Solution:**
1. Verify server is running: `curl http://ccindex-server:8787/api/health`
2. Check firewall rules
3. Verify endpoint URL is correct

### CLI Command Not Found

**Error:** `ccindex: command not found`

**Solution:**
```bash
cd ipfs_datasets_py/web_archiving/common_crawl_search_engine
pip install -e .
```

## Performance Considerations

### Index Size

Common Crawl URL indexes can be very large (100s of GB). For production:

1. **Use dedicated machines** for index storage and queries
2. **Enable rowgroup slicing** for faster domain lookups
3. **Use per-year indexes** for time-based queries
4. **Configure appropriate worker counts** based on CPU cores

### Network Latency

For remote mode:

1. **Deploy MCP server close to indexes** to minimize I/O latency
2. **Use connection pooling** for multiple queries
3. **Consider batch operations** for multiple domains
4. **Enable compression** for large result sets

## Related Documentation

- Common Crawl Search Engine: `ipfs_datasets_py/web_archiving/common_crawl_search_engine/README.md`
- Web Archive Tools: `docs/tutorials/web_archive_tutorial.md`
- MCP Server: `docs/guides/mcp_server.md`
- Dashboard Integration: `docs/dashboards.md`

## Support

For issues related to:
- **Integration**: Open an issue in `endomorphosis/ipfs_datasets_py`
- **Search Engine**: Open an issue in `endomorphosis/common_crawl_search_engine`
