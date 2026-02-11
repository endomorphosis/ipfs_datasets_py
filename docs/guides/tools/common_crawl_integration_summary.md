# Common Crawl Search Engine Integration - Complete Summary

## Overview

This document summarizes the complete integration of the `common_crawl_search_engine` submodule into `ipfs_datasets_py`, providing comprehensive access through multiple interfaces to support both local and remote deployment scenarios.

## Integration Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    ipfs_datasets_py Package                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Package Exports (ipfs_datasets_py.__init__)            │   │
│  │  - CommonCrawlSearchEngine                               │   │
│  │  - create_search_engine                                  │   │
│  │  - HAVE_COMMON_CRAWL flag                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Integration Layer (web_archiving/)                      │   │
│  │  - common_crawl_integration.py (Main wrapper)            │   │
│  │  - Three modes: local, remote, cli                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│       ↓                    ↓                    ↓               │
│  ┌─────────┐        ┌──────────┐        ┌──────────┐          │
│  │  Local  │        │  Remote  │        │   CLI    │          │
│  │  Mode   │        │   Mode   │        │   Mode   │          │
│  │         │        │          │        │          │          │
│  │ Direct  │        │ MCP JSON-│        │ Execute  │          │
│  │ imports │        │ RPC      │        │ ccindex  │          │
│  └─────────┘        └──────────┘        └──────────┘          │
│       ↓                    ↓                    ↓               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Submodule: common_crawl_search_engine                   │   │
│  │  Location: ipfs_datasets_py/web_archiving/               │   │
│  │            common_crawl_search_engine/                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│                    Access Methods                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. Python API          2. CLI Tools                             │
│     ├─ Local             ├─ ipfs-datasets common-crawl search   │
│     ├─ Remote            ├─ ipfs-datasets common-crawl list     │
│     └─ CLI               └─ ipfs-datasets cc info                │
│                                                                   │
│  3. MCP Tools           4. Dashboard                             │
│     ├─ search_*          ├─ Embedded mode                        │
│     ├─ fetch_*           ├─ Remote proxy                         │
│     └─ list_*            └─ Subdashboard integration             │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## File Structure

```
ipfs_datasets_py/
├── .gitmodules                              # Submodule configuration
├── ipfs_datasets_cli.py                     # Added 'common-crawl' command
├── ipfs_datasets_py/
│   ├── __init__.py                          # Export CommonCrawlSearchEngine
│   ├── web_archiving/
│   │   ├── __init__.py                      # Export integration classes
│   │   ├── common_crawl_integration.py      # Main integration wrapper
│   │   ├── common_crawl_search_engine/      # Git submodule
│   │   │   ├── README.md                    # Submodule documentation
│   │   │   ├── ccindex/                     # Search engine implementation
│   │   │   ├── ccsearch/                    # Dashboard and MCP server
│   │   │   ├── mcp_server.py                # MCP server implementation
│   │   │   ├── dashboard.py                 # Web dashboard
│   │   │   └── cli.py                       # CLI interface
│   │   └── common_crawl_search_engine_README.md  # Quick reference
│   ├── cli/
│   │   └── common_crawl_cli.py              # CLI command handlers
│   ├── mcp_server/tools/web_archive_tools/
│   │   ├── __init__.py                      # Export advanced tools
│   │   └── common_crawl_advanced.py         # MCP tools implementation
│   └── dashboards/
│       ├── __init__.py                      # Export dashboard
│       └── common_crawl_dashboard.py        # Dashboard integration
├── tests/integration/
│   └── test_common_crawl_submodule.py       # Integration tests
├── docs/
│   └── common_crawl_integration.md          # Complete documentation
└── scripts/demo/
    └── demonstrate_common_crawl_integration.py  # Demo script
```

## Access Method Details

### 1. Python Package API

**Module**: `ipfs_datasets_py.web_archiving`

**Classes**:
- `CommonCrawlSearchEngine` - Main wrapper class
- Supports three modes: `local`, `remote`, `cli`

**Functions**:
- `create_search_engine(**kwargs)` - Convenience factory

**Example**:
```python
from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine

# Local mode
engine = CommonCrawlSearchEngine(mode="local")

# Remote mode
engine = CommonCrawlSearchEngine(
    mode="remote",
    mcp_endpoint="http://server:8787"
)

# CLI mode
engine = CommonCrawlSearchEngine(mode="cli")

# Use the engine
results = engine.search_domain("example.com", max_matches=100)
collections = engine.list_collections()
info = engine.get_collection_info("CC-MAIN-2024-10")
```

### 2. CLI Tools

**Command**: `ipfs-datasets common-crawl` (or `ipfs-datasets cc`)

**Subcommands**:
- `search <domain>` - Search for a domain
- `collections` - List available collections
- `fetch <file> <offset> <length>` - Fetch WARC record
- `info <collection>` - Get collection information
- `config` - Show configuration

**Options**:
- `--mode` - Integration mode (local/remote/cli)
- `--endpoint` - MCP server endpoint (for remote mode)
- `--max-matches` - Maximum number of results
- `--collection` - Specific collection name
- `--json` - JSON output format

**Example**:
```bash
# Local search
ipfs-datasets common-crawl search example.com --max-matches 50

# Remote search
ipfs-datasets common-crawl search example.com \
    --mode remote \
    --endpoint http://server:8787

# List collections
ipfs-datasets cc collections --json

# Get collection info
ipfs-datasets cc info CC-MAIN-2024-10 --json
```

### 3. MCP Server Tools

**Module**: `ipfs_datasets_py.mcp_server.tools.web_archive_tools`

**Tools**:
- `search_common_crawl_advanced(domain, max_matches, collection, master_db_path)`
- `fetch_warc_record_advanced(warc_filename, warc_offset, warc_length, decode_content)`
- `list_common_crawl_collections_advanced()`
- `get_common_crawl_collection_info_advanced(collection)`

**Features**:
- Async/await support
- Automatic fallback to basic Common Crawl tools
- Structured JSON responses
- Error handling with fallback information

**Example**:
```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    search_common_crawl_advanced
)

result = await search_common_crawl_advanced(
    domain="example.com",
    max_matches=100,
    collection="CC-MAIN-2024-10"
)

# Result structure:
# {
#     "status": "success",
#     "results": [...],
#     "count": 100,
#     "engine": "common_crawl_search_engine"
# }
```

### 4. Dashboard Integration

**Module**: `ipfs_datasets_py.dashboards.common_crawl_dashboard`

**Classes**:
- `CommonCrawlDashboardIntegration` - Dashboard wrapper

**Functions**:
- `create_dashboard_integration(**kwargs)` - Factory function
- `register_dashboard_routes(app, prefix)` - Flask/FastAPI registration

**Features**:
- Embedded mode (dashboard runs in same process)
- Remote mode (proxy to standalone MCP server)
- Iframe configuration for subdashboard embedding
- Navigation item configuration
- Health check endpoint
- MCP JSON-RPC proxy

**Example**:
```python
from ipfs_datasets_py.dashboards.common_crawl_dashboard import (
    CommonCrawlDashboardIntegration,
    register_dashboard_routes
)

# Create integration
integration = CommonCrawlDashboardIntegration(
    mode="remote",
    remote_endpoint="http://ccindex-server:8787"
)

# Get iframe config for main dashboard
iframe_config = integration.get_iframe_config()
# {
#     "name": "common_crawl",
#     "title": "Common Crawl Search",
#     "url": "http://ccindex-server:8787",
#     "icon": "🌐",
#     "category": "web_archive"
# }

# Get navigation item
nav_item = integration.get_nav_item()
# {
#     "id": "common-crawl",
#     "label": "Common Crawl",
#     "icon": "🌐",
#     "url": "/subdashboard/common-crawl",
#     "category": "Web Archive"
# }

# Register with Flask app
from flask import Flask
app = Flask(__name__)
register_dashboard_routes(app, prefix="/subdashboard/common-crawl")
```

## Deployment Scenarios

### Scenario 1: Development (Local Mode)

**Use Case**: Small-scale testing and development

**Setup**:
```bash
git submodule update --init
cd ipfs_datasets_py/web_archiving/common_crawl_search_engine
pip install -e .
```

**Usage**:
```python
engine = CommonCrawlSearchEngine(mode="local")
```

### Scenario 2: Production (Remote Mode)

**Use Case**: Large-scale with dedicated index server

**Server Setup**:
```bash
# On index server
ccindex-dashboard --host 0.0.0.0 --port 8787
```

**Client Usage**:
```python
engine = CommonCrawlSearchEngine(
    mode="remote",
    mcp_endpoint="http://ccindex-server.example.com:8787"
)
```

### Scenario 3: Hybrid (CLI Mode)

**Use Case**: Mixed local/remote execution

**Usage**:
```python
# Local CLI
engine = CommonCrawlSearchEngine(mode="cli")

# Remote CLI via SSH
engine = CommonCrawlSearchEngine(
    mode="cli",
    ssh_host="ccindex-server.example.com"
)
```

### Scenario 4: Dashboard Integration

**Use Case**: Web UI with multiple subdashboards

**Flask Integration**:
```python
from flask import Flask
from ipfs_datasets_py.dashboards.common_crawl_dashboard import register_dashboard_routes

app = Flask(__name__)
register_dashboard_routes(app, prefix="/subdashboard/common-crawl")

# Accessible at:
# - /subdashboard/common-crawl (iframe dashboard)
# - /subdashboard/common-crawl/health (health check)
# - /subdashboard/common-crawl/config (configuration)
```

## Testing

### Integration Tests

**File**: `tests/integration/test_common_crawl_submodule.py`

**Tests**:
- `test_submodule_exists` - Verify submodule directory exists
- `test_integration_module_import` - Test integration module imports
- `test_search_engine_class_import` - Test CommonCrawlSearchEngine import
- `test_create_search_engine_function` - Test factory function
- `test_search_engine_initialization` - Test initialization
- `test_mcp_tools_import` - Test MCP tools import
- `test_mcp_tools_in_web_archive_tools_all` - Test __all__ exports
- `test_search_tool_handles_unavailable_submodule` - Test graceful fallback
- `test_list_collections_tool_structure` - Test response structure
- `test_gitmodules_entry` - Verify .gitmodules configuration

**Run Tests**:
```bash
pytest tests/integration/test_common_crawl_submodule.py -v
```

### Demo Script

**File**: `scripts/demo/demonstrate_common_crawl_integration.py`

**Demos**:
1. Local mode integration
2. Remote mode integration
3. CLI mode integration
4. MCP tools integration
5. Dashboard integration
6. Package exports

**Run Demo**:
```bash
python scripts/demo/demonstrate_common_crawl_integration.py
```

## Documentation

### Primary Documents

1. **Integration Guide**: `docs/common_crawl_integration.md`
   - Complete usage guide
   - Configuration options
   - Deployment scenarios
   - Troubleshooting

2. **Quick Reference**: `ipfs_datasets_py/web_archiving/common_crawl_search_engine_README.md`
   - Quick start guide
   - Common commands
   - Troubleshooting

3. **Submodule README**: `ipfs_datasets_py/web_archiving/common_crawl_search_engine/README.md`
   - Upstream repository documentation
   - MCP server details
   - CLI tools

### Code Documentation

All modules include comprehensive docstrings:
- Class docstrings with usage examples
- Method docstrings with parameter descriptions
- Return value documentation
- Exception documentation

## Benefits Summary

1. **Redundancy**: Fallback for internet data retrieval when Cloudflare blocks
2. **Scalability**: Remote mode supports large indexes on dedicated machines
3. **Flexibility**: Three integration modes for different scenarios
4. **Unified Access**: Four access methods (package/CLI/MCP/dashboard)
5. **AI Integration**: MCP tools for AI assistant access
6. **Dashboard Integration**: Seamless subdashboard support
7. **Production Ready**: Comprehensive testing and documentation

## Next Steps

1. **Initialize Submodule**: `git submodule update --init`
2. **Install Dependencies**: `cd ipfs_datasets_py/web_archiving/common_crawl_search_engine && pip install -e .`
3. **Run Demo**: `python scripts/demo/demonstrate_common_crawl_integration.py`
4. **Read Documentation**: `docs/common_crawl_integration.md`
5. **Run Tests**: `pytest tests/integration/test_common_crawl_submodule.py -v`

## Support

- **Integration Issues**: Open issue in `endomorphosis/ipfs_datasets_py`
- **Search Engine Issues**: Open issue in `endomorphosis/common_crawl_search_engine`
- **Documentation**: See `docs/common_crawl_integration.md`
