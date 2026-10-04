# Dashboard Previews

HTML dashboard previews and demonstrations for IPFS Datasets Python.

## Contents

This directory contains HTML previews and screenshots of various dashboards:
- MCP Dashboard previews
- Finance Dashboard previews  
- Unified Dashboard previews
- Analytics Dashboard previews

## Purpose

Dashboards provide:
1. **Real-time Monitoring** - System status and metrics
2. **Data Visualization** - Charts and graphs
3. **Interactive Exploration** - Browse and search data
4. **Administration** - Configuration and management

## Available Dashboards

### Unified Dashboard
Comprehensive system overview combining multiple data sources.
See [Unified Dashboard Guide](../unified_dashboard.md) for details.

### MCP Dashboard
Model Context Protocol server dashboard with 200+ tools.
See [MCP Dashboard Guide](../guides/MCP_DASHBOARD_README.md) for details.

### Finance Dashboard
Financial data processing and analysis dashboard.

### Municipal Codes Dashboard
Legal code scraping and analysis interface.
See [Municipal Codes Dashboard Guide](../guides/tools/municipal_codes_dashboard_guide.md) for details.

## Using Dashboards

Most dashboards can be accessed via:

### 1. Web Interface
```bash
# Start dashboard server
python -m ipfs_datasets_py.mcp_server --dashboard

# Access at http://localhost:8899/dashboard
```

### 2. Standalone Mode
```bash
# Run specific dashboard
python scripts/dashboard/run_unified_dashboard.py
```

## Related Documentation

- [Unified Dashboard](../unified_dashboard.md) - Main dashboard documentation
- [MCP Server Integration](../guides/tools/mcp_server_integration.md) - MCP server setup
- [User Guide](../user_guide.md) - General usage
