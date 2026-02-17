# Common Crawl Search Engine Submodule

This directory contains the `common_crawl_search_engine` submodule, which provides advanced search and indexing capabilities for Common Crawl data.

## Quick Start

### 1. Initialize the Submodule

If you just cloned this repository, initialize the submodule:

```bash
git submodule update --init
```

### 2. Install Dependencies

The submodule has its own dependencies. Install them:

```bash
cd ipfs_datasets_py/web_archiving/common_crawl_search_engine
pip install -e .
```

### 3. Use the Integration

The Common Crawl Search Engine is integrated into `ipfs_datasets_py` through multiple interfaces:

**Python API:**
```python
from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine

engine = CommonCrawlSearchEngine(mode="local")
results = engine.search_domain("example.com", max_matches=100)
```

**CLI:**
```bash
ipfs-datasets common-crawl search example.com --max-matches 50
ipfs-datasets common-crawl collections
```

**MCP Tools:**
```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import search_common_crawl_advanced

result = await search_common_crawl_advanced(domain="example.com")
```

## Integration Modes

### Local Mode (Default)

Direct package imports when the submodule is available locally:

```python
engine = CommonCrawlSearchEngine(mode="local")
```

### Remote Mode

Connect to a standalone MCP server on another machine (useful for large indexes):

```python
engine = CommonCrawlSearchEngine(
    mode="remote",
    mcp_endpoint="http://ccindex-server.example.com:8787"
)
```

### CLI Mode

Execute CLI commands (local or remote via SSH):

```python
engine = CommonCrawlSearchEngine(mode="cli")
# Or remote via SSH:
engine = CommonCrawlSearchEngine(mode="cli", ssh_host="server.example.com")
```

## Why Remote Mode?

Common Crawl URL indexes can be extremely large (100s of GB). For production deployments:

1. **Run the MCP server on a dedicated machine** with fast storage for indexes
2. **Connect from client machines** using remote mode
3. **Avoid network bottlenecks** by keeping indexes close to the MCP server

## Starting a Standalone MCP Server

On the server with indexes:

```bash
# Option 1: MCP server only
ccindex-mcp-server --mode tcp --host 0.0.0.0 --port 8787

# Option 2: With dashboard UI
ccindex-dashboard --host 0.0.0.0 --port 8787
```

## Documentation

- **Integration Guide**: `../../docs/common_crawl_integration.md`
- **Submodule README**: `README.md` (in this directory)
- **MCP Server**: See submodule documentation for MCP server details

## Troubleshooting

### Submodule Not Initialized

```bash
git submodule update --init --recursive
```

### Missing Dependencies

```bash
cd ipfs_datasets_py/web_archiving/common_crawl_search_engine
pip install -e .
```

### CLI Command Not Found

Make sure the submodule dependencies are installed:

```bash
cd ipfs_datasets_py/web_archiving/common_crawl_search_engine
pip install -e .
which ccindex  # Should show the installed command
```

## Related Files

- **Integration wrapper**: `../common_crawl_integration.py`
- **MCP tools**: `../../mcp_server/tools/web_archive_tools/common_crawl_advanced.py`
- **CLI commands**: `../../cli/common_crawl_cli.py`
- **Dashboard integration**: `../../dashboards/common_crawl_dashboard.py`
- **Tests**: `../../../tests/integration/test_common_crawl_submodule.py`

## Upstream Repository

This is a git submodule tracking:
- **Repository**: https://github.com/endomorphosis/common_crawl_search_engine
- **Purpose**: Fast Common Crawl domain/URL search with rowgroup slicing
- **Features**: DuckDB indexes, per-collection/year indexes, MCP integration

For issues specific to the search engine, open issues in the upstream repository.
