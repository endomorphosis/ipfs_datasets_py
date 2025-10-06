# MCP Server Docker Deployment Guide

This guide provides comprehensive instructions for deploying the IPFS Datasets MCP server and dashboard using Docker for simplified deployment and testing.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Docker Deployment Options](#docker-deployment-options)
3. [Environment Configuration](#environment-configuration)
4. [Browser Automation Testing](#browser-automation-testing)
5. [Production Deployment](#production-deployment)
6. [Troubleshooting](#troubleshooting)

## Quick Start

The fastest way to get the MCP server and dashboard running is using Docker Compose:

### Option 1: Full Stack with Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Start all services (MCP server, dashboard, and IPFS node)
docker-compose -f docker-compose.mcp.yml up -d

# Check service status
docker-compose -f docker-compose.mcp.yml ps

# View logs
docker-compose -f docker-compose.mcp.yml logs -f mcp-dashboard

# Access the dashboard
open http://localhost:8899/mcp
```

### Option 2: Individual Container Deployment

```bash
# Build and run MCP server only
docker build -f ipfs_datasets_py/mcp_server/Dockerfile -t ipfs-datasets-mcp .
docker run -d -p 8000:8000 --name mcp-server ipfs-datasets-mcp

# Build and run MCP dashboard
docker build -f ipfs_datasets_py/mcp_server/Dockerfile.dashboard -t ipfs-datasets-dashboard .
docker run -d -p 8899:8899 --name mcp-dashboard \
    -e MCP_SERVER_HOST=host.docker.internal \
    ipfs-datasets-dashboard
```

## Docker Deployment Options

### 1. MCP Server Only

For VS Code integration or headless operation:

```bash
# Build the MCP server image
docker build -f ipfs_datasets_py/mcp_server/Dockerfile -t ipfs-datasets-mcp .

# Run with basic configuration
docker run -p 8000:8000 ipfs-datasets-mcp

# Run with custom configuration
docker run -p 8000:8000 \
    -v $(pwd)/config:/app/config:ro \
    -e IPFS_DATASETS_CONFIG=/app/config/mcp_config.yaml \
    ipfs-datasets-mcp
```

**Health Check:**
```bash
curl -f http://localhost:8000/health
```

### 2. MCP Dashboard + Server

For web-based interface and monitoring:

```bash
# Use Docker Compose for both services
docker-compose -f docker-compose.mcp.yml up mcp-server mcp-dashboard

# Or build and run individually
docker build -f ipfs_datasets_py/mcp_server/Dockerfile.dashboard -t ipfs-datasets-dashboard .
docker run -p 8899:8899 \
    --link mcp-server:mcp-server \
    -e MCP_SERVER_HOST=mcp-server \
    ipfs-datasets-dashboard
```

**Access Points:**
- Dashboard: http://localhost:8899/mcp
- Server Status: http://localhost:8899/api/mcp/status
- API Documentation: http://localhost:8899/api/mcp/tools

### 3. Full Stack with IPFS

For complete functionality including IPFS operations:

```bash
# Start all services including IPFS node
docker-compose -f docker-compose.mcp.yml up -d

# Services included:
# - MCP Server (port 8000)
# - MCP Dashboard (port 8899) 
# - IPFS Node (API: 5001, Gateway: 8082, P2P: 4001)
```

## Environment Configuration

### MCP Server Configuration

```bash
# Core settings
MCP_SERVER_HOST=0.0.0.0          # Bind address
MCP_SERVER_PORT=8000             # Server port
IPFS_DATASETS_CONFIG=config.yaml # Config file path

# Python settings
PYTHONFAULTHANDLER=1             # Enable fault handler
PYTHONUNBUFFERED=1              # Unbuffered output
```

### MCP Dashboard Configuration

```bash
# Dashboard settings
MCP_DASHBOARD_HOST=0.0.0.0       # Dashboard bind address
MCP_DASHBOARD_PORT=8899          # Dashboard port
MCP_DASHBOARD_BLOCKING=1         # Blocking mode for container

# Server connection
MCP_SERVER_HOST=mcp-server       # MCP server hostname
MCP_SERVER_PORT=8000             # MCP server port

# Features
MCP_ENABLE_TOOL_EXECUTION=true   # Allow tool execution
MCP_TOOL_TIMEOUT=30.0           # Tool execution timeout
MCP_MAX_CONCURRENT_TOOLS=5       # Max concurrent executions
```

### IPFS Configuration

```bash
# IPFS settings (when using IPFS service)
IPFS_PROFILE=server              # Server profile for headless operation
IPFS_API_HOST=ipfs              # IPFS API hostname
IPFS_API_PORT=5001              # IPFS API port
IPFS_GATEWAY_PORT=8082          # IPFS gateway port
```

## Browser Automation Testing

### Comprehensive Test Suite

The project includes a comprehensive browser automation testing framework using Playwright that tests all dashboard features.

#### Running Tests Locally

```bash
# Install testing dependencies
pip install playwright pytest-playwright pytest-asyncio
playwright install chromium

# Run comprehensive tests
pytest tests/integration/dashboard/comprehensive_mcp_dashboard_test.py -v

# Run with HTML report
pytest tests/integration/dashboard/comprehensive_mcp_dashboard_test.py \
    --html=test_outputs/report.html --self-contained-html

# Run specific test categories
pytest tests/integration/dashboard/comprehensive_mcp_dashboard_test.py \
    -k "test_mcp_dashboard_api_endpoints" -v
```

#### Running Tests with Docker

```bash
# Build testing image
docker build -f Dockerfile.testing -t ipfs-datasets-testing .

# Run tests against local services
docker run --rm \
    --network host \
    -v $(pwd)/test_outputs:/app/test_outputs \
    ipfs-datasets-testing

# Run tests with Docker Compose (includes services)
docker-compose -f docker-compose.mcp.yml --profile testing up \
    --abort-on-container-exit browser-tests
```

### Test Coverage

The comprehensive test suite covers:

#### ✅ UI Testing
- [x] Dashboard navigation and menu items
- [x] Server status display and real-time updates
- [x] Tool discovery and categorization
- [x] Tool execution interface
- [x] Execution history display
- [x] Responsive design (desktop, tablet, mobile)

#### ✅ Functional Testing  
- [x] REST API endpoints (`/api/mcp/status`, `/api/mcp/tools`, etc.)
- [x] JavaScript SDK integration
- [x] Error handling and validation
- [x] Tool parameter input and validation

#### ✅ Performance Testing
- [x] Page load times and performance metrics
- [x] Resource usage monitoring
- [x] Network request optimization

#### ✅ Accessibility Testing
- [x] Alt text on images
- [x] Form label associations
- [x] Heading structure validation
- [x] Keyboard navigation support

#### ✅ Visual Regression Testing
- [x] Automated screenshot comparison
- [x] Cross-browser compatibility
- [x] Theme and styling consistency

### Test Output

Tests generate comprehensive reports including:

- **Screenshots**: Visual documentation of all test steps
- **Performance Metrics**: Load times, resource usage, API response times
- **Error Reports**: Detailed logging of any issues found
- **Accessibility Report**: WCAG compliance analysis
- **API Test Results**: Endpoint validation and response testing

```bash
# View test results
ls test_outputs/
# mcp_dashboard_screenshots/    # Visual documentation
# mcp_dashboard_test_results.json  # Detailed test results
# report.html                   # HTML test report
```

## Integration with VS Code

For VS Code Copilot integration alongside Docker deployment:

```bash
# Start MCP server in Docker
docker-compose -f docker-compose.mcp.yml up -d mcp-server

# Update VS Code settings to use Docker server
{
  "mcp.servers": {
    "ipfs-datasets": {
      "command": "curl",
      "args": ["-X", "POST", "http://localhost:8000/api/mcp/execute"],
      "cwd": "/workspace"
    }
  }
}
```

## API Reference

### MCP Server Endpoints

- `GET /health` - Server health check
- `POST /api/mcp/execute` - Execute MCP tool
- `GET /api/mcp/tools` - List available tools

### Dashboard Endpoints

- `GET /mcp` - Dashboard interface
- `GET /api/mcp/status` - Server status and metrics
- `GET /api/mcp/tools` - Tool discovery
- `POST /api/mcp/tools/{category}/{tool}/execute` - Execute tool
- `GET /api/mcp/history` - Execution history

For more detailed API documentation, see the [MCP Dashboard README](../guides/MCP_DASHBOARD_README.md).