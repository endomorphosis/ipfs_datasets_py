# Production Deployment Guide

This guide covers deploying IPFS Datasets Python in production environments.

## Quick Links

For detailed deployment guides, see:
- **[Docker Deployment](guides/deployment/docker_deployment.md)** - Containerized deployment
- **[GraphRAG Production Guide](guides/deployment/graphrag_production_deployment_guide.md)** - Production GraphRAG setup
- **[Runner Setup](guides/deployment/runner_setup.md)** - GitHub Actions self-hosted runners
- **[GPU Runner Setup](guides/deployment/gpu_runner_setup.md)** - GPU-enabled deployment

## Deployment Options

### 1. Docker Deployment (Recommended)

The easiest way to deploy in production:

```bash
# Build and run with Docker
docker-compose up -d
```

See [Docker Deployment Guide](guides/deployment/docker_deployment.md) for full details.

### 2. Kubernetes Deployment

For scalable cloud deployment:

```bash
# Deploy to Kubernetes
kubectl apply -f deployments/kubernetes/
```

See [GraphRAG Production Guide](guides/deployment/graphrag_production_deployment_guide.md) for Kubernetes setup.

### 3. Bare Metal Deployment

For direct server installation:

```bash
# Install dependencies
pip install ipfs-datasets-py[all]

# Configure systemd service
sudo cp ipfs-datasets-mcp.service /etc/systemd/system/
sudo systemctl enable ipfs-datasets-mcp
sudo systemctl start ipfs-datasets-mcp
```

## Production Checklist

### Before Deployment

- [ ] **Review Configuration** - See [Configuration Guide](configuration.md)
- [ ] **Security Setup** - See [Security & Governance](guides/security/security_governance.md)
- [ ] **Performance Tuning** - See [Performance Optimization](guides/performance_optimization.md)
- [ ] **Backup Strategy** - Plan data backup and recovery
- [ ] **Monitoring Setup** - Configure logging and metrics

### Deployment Steps

1. **Environment Setup**
   ```bash
   # Set production environment
   export ENVIRONMENT=production
   
   # Configure secrets
   cp .env.example .env
   # Edit .env with production credentials
   ```

2. **Database Setup** (if using SQL)
   ```bash
   # Initialize database
   python scripts/setup/init_database.py
   ```

3. **IPFS Node Setup**
   ```bash
   # Start IPFS daemon
   ipfs daemon &
   
   # Or use managed IPFS service
   ```

4. **Deploy Application**
   ```bash
   # Using Docker
   docker-compose -f docker-compose.prod.yml up -d
   
   # Or using systemd
   sudo systemctl start ipfs-datasets-mcp
   ```

5. **Verify Deployment**
   ```bash
   # Check service status
   docker-compose ps
   # or
   sudo systemctl status ipfs-datasets-mcp
   
   # Test endpoints
   curl http://localhost:8899/health
   ```

### After Deployment

- [ ] **Monitor Logs** - Check for errors
- [ ] **Load Testing** - Verify performance
- [ ] **Security Scan** - Run security checks
- [ ] **Backup Verification** - Test backup/restore
- [ ] **Documentation** - Update runbooks

## Architecture Considerations

### High Availability

For HA deployments:
- Multiple application instances behind load balancer
- Redundant IPFS nodes
- Replicated vector stores (Qdrant cluster)
- Database replication

### Scalability

Scaling strategies:
- **Horizontal**: Multiple container replicas
- **Vertical**: Increase resource allocation
- **Database**: Read replicas, sharding
- **IPFS**: DHT optimization, gateway caching

### Monitoring

Essential monitoring:
- **Application Metrics**: Response times, error rates
- **IPFS Metrics**: Peer count, data transfer
- **Resource Metrics**: CPU, memory, disk, network
- **Business Metrics**: Queries processed, documents indexed

See [Unified Dashboard](unified_dashboard.md) for monitoring setup.

## Security

Production security essentials:
- **Network Security**: Firewalls, VPNs, private networks
- **Access Control**: Authentication, authorization, API keys
- **Data Security**: Encryption at rest and in transit
- **Audit Logging**: Track all operations

See [Security & Governance Guide](guides/security/security_governance.md) for details.

## Disaster Recovery

### Backup Strategy

What to backup:
- Configuration files (configs.yaml, .env)
- Vector store indices
- Database dumps
- IPFS pinned content list

### Recovery Procedures

1. **Application Recovery**: Redeploy from container images
2. **Data Recovery**: Restore from backups
3. **IPFS Recovery**: Re-pin content from backup list
4. **Database Recovery**: Restore from SQL dumps

## Performance Optimization

Production performance tips:
- Enable caching (Redis recommended)
- Use GPU for embeddings if available
- Optimize IPFS settings for your workload
- Tune vector store parameters

See [Performance Optimization Guide](guides/performance_optimization.md).

## Troubleshooting

### Common Issues

**Service won't start:**
- Check logs: `docker-compose logs` or `journalctl -u ipfs-datasets-mcp`
- Verify configuration files
- Check port conflicts

**Poor performance:**
- Review resource allocation
- Check database query performance
- Monitor IPFS peer connections
- Profile application code

**Connection errors:**
- Verify network connectivity
- Check firewall rules
- Validate DNS resolution
- Test IPFS API access

## Support

For production support:
- **Documentation**: See [User Guide](user_guide.md)
- **Issues**: Report at GitHub Issues
- **Community**: Join discussions

## Related Guides

- [Configuration Guide](configuration.md) - Configure the application
- [Docker Deployment](guides/deployment/docker_deployment.md) - Container deployment
- [Security Guide](guides/security/security_governance.md) - Security best practices
- [Performance Guide](guides/performance_optimization.md) - Optimization tips
