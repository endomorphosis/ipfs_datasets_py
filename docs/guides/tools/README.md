# Tool Guides

Documentation for specific tools and integrations in IPFS Datasets Python.

## MCP Server Tools (200+ Tools)

The MCP (Model Context Protocol) server provides 200+ tools across 49+ categories:
- [MCP Server Integration](mcp_server_integration.md) - Main MCP server guide
- [MCP Dashboard](../../guides/MCP_DASHBOARD_README.md) - MCP dashboard

## Web Scraping & Data Collection

### Legal Data Tools
- [Municipal Codes Tool Guide](municipal_codes_tool_guide.md) - Municipal code scraping
- [Municipal Codes Dashboard](municipal_codes_dashboard_guide.md) - Dashboard interface
- [Patent Scraper Guide](patent_scraper_guide.md) - Patent database scraping

### Web Search & APIs
- [Web Search API Guide](web_search_api_guide.md) - Web search integration
- [Brave Search Client](brave_search_client.md) - Brave Search API
- [Brave Search IPFS Cache](brave_search_ipfs_cache.md) - Cached search results
- [Common Crawl Integration](common_crawl_integration.md) - Common Crawl access
- [Common Crawl Integration Summary](common_crawl_integration_summary.md) - Integration overview

## Media Processing

- [FFmpeg Tools Integration](ffmpeg_tools_integration.md) - FFmpeg video/audio processing
- Media download from 1000+ platforms (YouTube, Vimeo, TikTok, etc.)

## Development Tools

### Error Handling & Auto-Healing
- [CLI Error Auto-Healing](cli_error_auto_healing.md) - CLI error auto-fix
- [JS Error Auto-Healing Guide](js_error_auto_healing_guide.md) - JavaScript error auto-fix

### Alerting & Notifications
- [Discord Alerts Guide](discord_alerts_guide.md) - Discord integration

### Performance & Caching
- [CLI Caching Guide](cli_caching_guide.md) - CLI caching strategies

## Using Tools

Most tools can be accessed via:

### 1. Python API
```python
from ipfs_datasets_py.mcp_tools import ToolManager

tool_manager = ToolManager()
result = tool_manager.execute("tool_name", params)
```

### 2. MCP Server
```bash
# Start MCP server
python -m ipfs_datasets_py.mcp_server

# Access via MCP protocol
```

### 3. CLI
```bash
# Enhanced CLI with all tools
python scripts/cli/enhanced_cli.py --list-categories
python scripts/cli/enhanced_cli.py [category] [tool] [args]
```

## Tool Categories

- **dataset_tools** - Dataset loading and processing
- **embedding_tools** - Vector embeddings
- **search_tools** - Search functionality
- **pdf_tools** - PDF processing
- **media_tools** - Multimedia processing
- **legal_dataset_tools** - Legal data scraping
- **web_archive_tools** - Web archiving
- **vector_tools** - Vector store operations
- **ipfs_tools** - IPFS operations
- ...and 40+ more categories

## Related Documentation

- [MCP Tools Comprehensive Reference](../MCP_TOOLS_COMPREHENSIVE_REFERENCE.md) - Complete tool catalog
- [MCP Tools Technical Reference](../../architecture/mcp_tools_technical_reference.md) - Technical details
- [User Guide](../../user_guide.md) - General usage
