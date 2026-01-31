# Deployment Guides

Comprehensive deployment documentation for various environments and configurations.

## Available Guides

- [Docker Deployment](docker_deployment.md) - Container-based deployment
- [GraphRAG Production Deployment](graphrag_production_deployment_guide.md) - Production GraphRAG setup
- [Runner Setup](runner_setup.md) - GitHub Actions self-hosted runners
- [ARM64 Runner Setup](arm64_runner_setup.md) - ARM-based runner configuration
- [GPU Runner Setup](gpu_runner_setup.md) - GPU-enabled runner deployment
- [Runner Authentication Setup](runner_authentication_setup.md) - Authentication configuration
- [Docker Permission Fix](docker_permission_fix.md) - Docker permission issues
- [Docker Permission Infrastructure Solutions](docker_permission_infrastructure_solutions.md) - Infrastructure-level solutions

## Deployment Options

### Container Deployment
- **Docker**: Single-container deployment
- **Docker Compose**: Multi-container orchestration
- **Kubernetes**: Cloud-native deployment

### Runner Deployment
- **Standard Runners**: x86_64 GitHub Actions runners
- **ARM64 Runners**: ARM-based runners
- **GPU Runners**: CUDA-enabled runners

### Production Deployment
- **GraphRAG**: Production GraphRAG with knowledge graphs
- **MCP Server**: Model Context Protocol server deployment
- **API Servers**: RESTful API deployment

## Quick Start

### Docker Deployment
```bash
# Build and run
docker-compose up -d

# Check status
docker-compose ps
```

### Runner Setup
```bash
# Download runner
./deployments/setup_runner.sh

# Configure and start
./run.sh
```

## Related Documentation

- [Main Deployment Guide](../deployment.md) - Overview of all deployment options
- [Configuration Guide](../configuration.md) - Configuration options
- [Performance Optimization](../guides/performance_optimization.md) - Performance tuning
- [Security Guide](../guides/security/security_governance.md) - Security best practices
