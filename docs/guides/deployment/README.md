# Deployment Guides

Comprehensive deployment documentation for various environments and configurations.

## Available Guides

### Container Deployment
- [Docker Deployment](docker_deployment.md) - Container-based deployment with Docker and Docker Compose
- [GraphRAG Production Deployment](graphrag_production_deployment_guide.md) - Production GraphRAG setup with Kubernetes

### GitHub Actions Runners
- [Runner Setup](runner_setup.md) - Standard x86_64 self-hosted runners
- [ARM64 Runner Setup](arm64_runner_setup.md) - ARM-based runner configuration
- [GPU Runner Setup](gpu_runner_setup.md) - GPU-enabled runner deployment with CUDA
- [Runner Authentication Setup](runner_authentication_setup.md) - Authentication and access configuration

### Docker Infrastructure
- [Docker Permission Fix](docker_permission_fix.md) - Resolving Docker permission issues
- [Docker Permission Infrastructure Solutions](docker_permission_infrastructure_solutions.md) - System-level solutions

## Deployment Options

### Container Deployment
- **Docker**: Single-container deployment for development
- **Docker Compose**: Multi-container orchestration
- **Kubernetes**: Cloud-native production deployment

### Runner Deployment
- **Standard Runners**: x86_64 GitHub Actions runners
- **ARM64 Runners**: ARM-based runners for multi-architecture support
- **GPU Runners**: CUDA-enabled runners for ML workloads

### Production Deployment
- **GraphRAG**: Production GraphRAG with knowledge graphs and vector stores
- **MCP Server**: Model Context Protocol server (200+ tools)
- **API Servers**: RESTful API deployment

## Quick Start

### Docker Deployment
```bash
# Build and run with Docker Compose
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

### Kubernetes Deployment
```bash
# Deploy to Kubernetes
kubectl apply -f deployments/kubernetes/

# Check deployment status
kubectl get pods
kubectl get services
```

### Runner Setup
```bash
# Download and configure runner
./config.sh --url https://github.com/your-org/your-repo --token YOUR_TOKEN

# Start runner
./run.sh
```

## Architecture

### High Availability Setup
For production HA deployments:
- Multiple application replicas behind load balancer
- Redundant IPFS nodes with DHT optimization
- Replicated vector stores (Qdrant cluster)
- Database replication (PostgreSQL streaming replication)

### Scaling Strategy
- **Horizontal Scaling**: Multiple container replicas with auto-scaling
- **Vertical Scaling**: Resource allocation per container
- **Database Scaling**: Read replicas and connection pooling
- **IPFS Scaling**: Gateway caching and DHT optimization

## Monitoring & Observability

Essential monitoring setup:
- **Application Metrics**: Response times, error rates, throughput
- **IPFS Metrics**: Peer count, bandwidth, pin status
- **Resource Metrics**: CPU, memory, disk, network
- **Business Metrics**: Documents processed, queries executed

See [Unified Dashboard](../../unified_dashboard.md) for monitoring dashboard setup.

## Security

Production security essentials:
- **Network**: Firewalls, VPNs, private networks
- **Access Control**: API keys, JWT tokens, RBAC
- **Encryption**: TLS for transit, encryption at rest
- **Audit Logging**: Track all operations

See [Security & Governance Guide](../security/security_governance.md).

## Disaster Recovery

### Backup Strategy
- Configuration files (daily)
- Vector store indices (incremental)
- Database dumps (daily with point-in-time recovery)
- IPFS pinned content lists (daily)

### Recovery Procedures
1. **Application Recovery**: Redeploy from container registry
2. **Data Recovery**: Restore from encrypted backups
3. **IPFS Recovery**: Re-pin content from backup lists
4. **Database Recovery**: Restore from SQL dumps or PITR

## Performance Tuning

Production performance optimization:
- Enable Redis caching for frequently accessed data
- Use GPU acceleration for embeddings (2-10x speedup)
- Optimize IPFS with custom gateway and pin sets
- Tune vector store parameters (HNSW ef_construction, M)
- Configure database connection pooling

See [Performance Optimization Guide](../performance_optimization.md).

## Troubleshooting

### Common Issues

**Deployment fails:**
- Check logs: `docker-compose logs` or `kubectl logs`
- Verify configuration files and secrets
- Check resource availability (CPU, memory, disk)
- Validate network connectivity

**Poor performance:**
- Review resource allocation and limits
- Check database query performance
- Monitor IPFS peer connections
- Profile application with py-spy or cProfile

**Connection errors:**
- Verify network connectivity between services
- Check firewall rules and security groups
- Validate DNS resolution
- Test service endpoints manually

## Related Documentation

- [Main Deployment Guide](../../deployment.md) - Overview of all deployment options
- [Configuration Guide](../../configuration.md) - Configuration reference
- [Performance Optimization](../performance_optimization.md) - Performance tuning
- [Security Guide](../security/security_governance.md) - Security best practices
- [Docker Deployment (Legacy)](../../deployment/DOCKER_DEPLOYMENT_GUIDE.md) - Legacy Docker guide
