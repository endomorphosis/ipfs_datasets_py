# GraphRAG System - Infrastructure as Code

This directory contains all deployment configurations and infrastructure automation for the GraphRAG website processing system.

## Directory Structure

```
deployments/
├── kubernetes/           # Kubernetes deployment manifests
│   ├── infrastructure.yaml    # Database, Redis, IPFS, Elasticsearch
│   ├── graphrag-deployment.yaml  # Main application deployments
│   └── ingress.yaml           # Load balancing and ingress
├── monitoring/          # Monitoring and observability
│   ├── prometheus.yml         # Prometheus configuration
│   └── grafana/              # Grafana dashboards and datasources
├── nginx/              # Reverse proxy configuration
│   └── nginx.conf            # Load balancing and SSL termination
└── sql/               # Database initialization
    └── init.sql              # Schema and initial data
```

## Quick Start

### Docker Compose (Development/Small Scale)

1. **Setup environment:**
```bash
cp .env.example .env
# Edit .env with your configuration
```

2. **Start all services:**
```bash
docker-compose up -d
```

3. **Initialize database:**
```bash
docker-compose exec website-graphrag-processor python -m ipfs_datasets_py.scripts.init_database --init
```

4. **Access services:**
- GraphRAG API: http://localhost:8000
- Grafana Dashboard: http://localhost:3000 (admin/admin)
- Prometheus: http://localhost:9090

### Kubernetes (Production)

1. **Create namespace and secrets:**
```bash
kubectl create namespace graphrag-system

# Database credentials
kubectl create secret generic db-credentials \
  --from-literal=postgres-password="your_secure_password" \
  --from-literal=postgres-url="postgresql://graphrag_user:your_secure_password@postgres-service:5432/graphrag_db" \
  -n graphrag-system

# API credentials
kubectl create secret generic api-credentials \
  --from-literal=jwt-secret-key="your_ultra_secure_jwt_secret_minimum_32_characters" \
  -n graphrag-system

# External API keys
kubectl create secret generic api-keys \
  --from-literal=openai-api-key="your_openai_api_key" \
  --from-literal=huggingface-token="your_huggingface_token" \
  -n graphrag-system
```

2. **Deploy infrastructure:**
```bash
kubectl apply -f deployments/kubernetes/infrastructure.yaml
```

3. **Deploy application:**
```bash
kubectl apply -f deployments/kubernetes/graphrag-deployment.yaml
```

4. **Setup ingress:**
```bash
kubectl apply -f deployments/kubernetes/ingress.yaml
```

## Monitoring and Observability

### Prometheus Metrics
The system exposes comprehensive metrics:
- Processing job metrics (duration, success rate, queue length)
- System resource metrics (CPU, memory, disk usage)
- Knowledge graph metrics (entities, relationships extracted)
- API metrics (request rate, response time, error rate)

### Grafana Dashboards
Pre-configured dashboards for:
- System overview and health
- Processing performance and throughput
- Knowledge graph analytics
- User activity and API usage
- Resource utilization and scaling metrics

### Alerting
Configure alerts for:
- High error rates (>5%)
- High response times (>10s)
- Resource exhaustion (>90% CPU/memory)
- Processing queue backup (>100 jobs)
- Database connection issues

## Scaling Configuration

### Horizontal Pod Autoscaling
- **API servers**: 2-10 replicas based on CPU (70%) and memory (80%)
- **Job workers**: 3-20 replicas based on CPU (75%) and memory (85%)
- **Scaling policies**: Aggressive scale-up, conservative scale-down

### Vertical Scaling
- **API servers**: 4-8GB memory, 2-4 CPU cores
- **Job workers**: 2-4GB memory, 1-2 CPU cores
- **Database**: 2-4GB memory, 1-2 CPU cores
- **Cache**: 512MB-1GB memory, 250-500m CPU

## Security

### Network Security
- Network policies restricting inter-pod communication
- TLS termination at ingress
- Rate limiting on API endpoints

### Authentication & Authorization
- JWT-based authentication with configurable expiration
- Role-based access control (user, admin, analyst roles)
- API key management for external services

### Data Security
- Encrypted database connections
- Secret management via Kubernetes secrets
- Regular security scanning via CI/CD

## Backup and Recovery

### Database Backup
```bash
# Automated daily backups
kubectl create cronjob postgres-backup \
  --image=postgres:15-alpine \
  --schedule="0 2 * * *" \
  --restart=OnFailure \
  -- /bin/sh -c "pg_dump \$POSTGRES_URL > /backup/$(date +%Y%m%d_%H%M%S).sql"
```

### Disaster Recovery
- Database point-in-time recovery with WAL archiving
- IPFS content replication across multiple nodes
- Configuration backup in version control
- Automated recovery testing procedures

## Performance Optimization

### Resource Allocation
- Memory-optimized instances for embedding generation
- CPU-optimized instances for knowledge graph processing
- Storage-optimized instances for large content archives

### Caching Strategy
- Redis for session and temporary data
- Elasticsearch for search index caching
- IPFS for distributed content caching
- Application-level caching for embeddings

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
```bash
kubectl logs deployment/postgres -n graphrag-system
kubectl exec -it deployment/postgres -n graphrag-system -- psql -U graphrag_user -d graphrag_db
```

2. **IPFS Node Issues**
```bash
kubectl logs deployment/ipfs -n graphrag-system
kubectl exec -it deployment/ipfs -n graphrag-system -- ipfs id
```

3. **Processing Job Failures**
```bash
kubectl logs deployment/job-worker -n graphrag-system
# Check job status via API
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/jobs/
```

### Log Analysis
```bash
# Application logs
kubectl logs -f deployment/website-graphrag-processor -n graphrag-system

# Worker logs
kubectl logs -f deployment/job-worker -n graphrag-system

# System metrics
kubectl top pods -n graphrag-system
```

## Maintenance

### Updates and Upgrades
```bash
# Rolling update
kubectl set image deployment/website-graphrag-processor \
  graphrag-processor=ipfs-datasets-py:new-version \
  -n graphrag-system

# Monitor rollout
kubectl rollout status deployment/website-graphrag-processor -n graphrag-system
```

### Health Monitoring
```bash
# Check all services
kubectl get pods -n graphrag-system
kubectl get services -n graphrag-system
kubectl get ingress -n graphrag-system

# Resource usage
kubectl top pods -n graphrag-system
kubectl describe hpa -n graphrag-system
```