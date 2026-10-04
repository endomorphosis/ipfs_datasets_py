# Docker Integration with Dependency Management

This document describes how the dependency installer is integrated into the Docker containers for IPFS Datasets Python.

## Overview

All Docker containers now include comprehensive dependency management through the integrated `dependency_checker.py` tool. This ensures that containers have all required packages installed and functioning properly.

## Enhanced Dockerfiles

### 1. Main Dockerfile (`Dockerfile`)
- **Full installation** with all features
- **Dependency checker** runs during build
- **Optional packages** installed automatically
- **IPFS integration** with proper configuration

### 2. MCP Server (`Dockerfile.mcp-minimal`)
- **MCP server** with comprehensive dependencies
- **Real MCP functionality** instead of placeholder
- **200+ tools** available with proper dependencies
- **FAISS, vector databases, ML libraries** included

### 3. MCP Dashboard (`Dockerfile.dashboard-minimal`)
- **Full dashboard** with all features
- **GraphRAG integration** supported
- **Analytics and monitoring** capabilities
- **Interactive web interface** with all dependencies

### 4. MCP Server (Full) (`ipfs_datasets_py/mcp_server/Dockerfile`)
- **Development version** with all features
- **Optional packages** installed
- **Comprehensive testing** capabilities

## Docker Compose Integration

### Basic Usage
```bash
# Start MCP services with enhanced dependency management
docker-compose -f docker-compose.mcp.yml up

# With enhanced configuration
docker-compose -f docker-compose.mcp.yml -f docker-compose.enhanced.yml up
```

### Services Available

1. **mcp-server** (Port 8000)
   - Full MCP server with 200+ tools
   - FAISS vector operations
   - Vector databases (Qdrant, ChromaDB, Elasticsearch)
   - ML libraries (XGBoost, LightGBM, CatBoost)

2. **mcp-dashboard** (Port 8899)
   - Interactive web dashboard
   - Real-time monitoring
   - GraphRAG processing interface
   - Analytics and visualization

3. **ipfs** (Ports 4001, 5001, 8082)
   - IPFS node for decentralized storage
   - API and gateway access
   - Automatic peer discovery

4. **dependency-validator** (Optional)
   - Validation service for dependency management
   - Generates comprehensive dependency reports
   - Use with `--profile validation`

## Dependency Management Features

### Build-Time Dependency Installation
- **Comprehensive checking** during Docker build
- **Automatic installation** of missing packages
- **Optional packages** included (Jupyter, advanced ML)
- **GPU packages** handled gracefully

### Runtime Dependency Validation
- **Startup checks** ensure dependencies are available
- **Graceful degradation** when optional packages missing
- **Informative warnings** for missing functionality
- **Mock implementations** for non-critical features

### Available Package Categories

**Core Packages (48)**: Always installed
- Web frameworks: Flask, Dash, FastAPI
- Data processing: Pandas, NumPy, PyArrow
- ML/AI: Transformers, PyTorch, NLTK
- Vector operations: FAISS, sentence-transformers
- Databases: DuckDB, vector stores
- File processing: PDF, image, document handling

**Optional Packages (8)**: Installed with `--install-optional`
- Jupyter ecosystem: jupyter, notebook, ipykernel, ipywidgets, jupyterlab
- Advanced ML: xgboost, lightgbm, catboost

**GPU Packages (2)**: Attempted but may fail gracefully
- GPU acceleration: cupy, faiss-gpu

## Usage Examples

### 1. Basic MCP Server
```bash
# Build and run MCP server
docker build -f Dockerfile.mcp-minimal -t ipfs-datasets-mcp .
docker run -p 8000:8000 ipfs-datasets-mcp

# Check dependencies
docker run --rm ipfs-datasets-mcp dependency-check --check-only
```

### 2. Full Stack with Dashboard
```bash
# Start complete stack
docker-compose -f docker-compose.mcp.yml up -d

# Check dashboard
curl http://localhost:8899/api/mcp/status

# Check MCP server
curl http://localhost:8000/health
```

### 3. Dependency Validation
```bash
# Run dependency validation
docker-compose -f docker-compose.mcp.yml --profile validation up dependency-validator

# View dependency report
cat dependency_reports/dependency_report.txt
```

### 4. Custom Builds with Features
```bash
# Build with specific features
docker build --build-arg FEATURES=all -t ipfs-datasets-full .
docker build --build-arg FEATURES=vector -t ipfs-datasets-vector .
docker build --build-arg FEATURES=minimal -t ipfs-datasets-minimal .
```

## Environment Variables

### MCP Server
- `MCP_SERVER_HOST`: Server host (default: 0.0.0.0)
- `MCP_SERVER_PORT`: Server port (default: 8000)
- `IPFS_DATASETS_CONFIG`: Config file path

### MCP Dashboard
- `MCP_DASHBOARD_HOST`: Dashboard host (default: 0.0.0.0)
- `MCP_DASHBOARD_PORT`: Dashboard port (default: 8899)
- `MCP_DASHBOARD_BLOCKING`: Blocking mode (default: 1)
- `MCP_SERVER_HOST`: MCP server hostname
- `MCP_SERVER_PORT`: MCP server port

### Dependency Management
- `RUN_DEPENDENCY_CHECK`: Force dependency check on startup
- `START_IPFS`: Start IPFS daemon automatically

## Health Checks

All containers include health checks:

**MCP Server**: `curl -f http://localhost:8000/health`
**MCP Dashboard**: `curl -f http://localhost:8899/api/mcp/status`
**IPFS**: Built-in IPFS health monitoring

## Troubleshooting

### Missing Dependencies
```bash
# Check what's missing
docker run --rm <image> dependency-check --check-only

# Force reinstall
docker run --rm <image> dependency-check --install-optional
```

### Service Issues
```bash
# Check logs
docker-compose logs mcp-server
docker-compose logs mcp-dashboard

# Interactive debugging
docker run -it --rm <image> bash
```

### Build Issues
```bash
# Clean build
docker build --no-cache -f <dockerfile> -t <tag> .

# Build with verbose output
docker build --progress=plain -f <dockerfile> -t <tag> .
```

## Production Considerations

1. **Resource Allocation**: Containers with full dependencies require more memory
2. **Build Caching**: Use multi-stage builds for faster rebuilds
3. **Security**: Regular updates of base images and dependencies
4. **Monitoring**: Use health checks and dependency validation
5. **Storage**: Consider volume mounts for persistent data

## Testing

Use the included test script to validate Docker integration:

```bash
# Run comprehensive Docker tests
./test_docker_integration.sh

# Test specific container
docker run --rm <image> dependency-check --verbose
```

This ensures all Docker containers have comprehensive dependency management and can run the full IPFS Datasets Python functionality with proper error handling and graceful degradation.