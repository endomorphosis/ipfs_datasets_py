# GraphRAG Website Processing - Production Deployment Guide

This guide provides step-by-step instructions for deploying the GraphRAG website processing system in production environments.

## Prerequisites

### System Requirements
- **CPU**: Minimum 8 cores, recommended 16+ cores for high throughput
- **Memory**: Minimum 32GB RAM, recommended 64GB+ for large websites
- **Storage**: 500GB+ SSD storage for caching and temporary processing
- **Network**: High-bandwidth internet connection for web archiving

### Software Requirements
- Python 3.9+
- Docker 20.10+
- Kubernetes 1.25+ (for container deployment)
- Redis 7.0+ (for job queuing and caching)
- PostgreSQL 15+ (for metadata and analytics storage)
- IPFS node (for distributed storage)

## Deployment Options

### Option 1: Docker Compose (Recommended for Development/Small Scale)

1. **Clone the repository and setup environment:**
```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
cp .env.example .env
# Edit .env with your configuration
```

2. **Start the services:**
```bash
docker-compose up -d
```

3. **Initialize the database:**
```bash
docker-compose exec website-graphrag-processor python -m ipfs_datasets_py.scripts.init_database
```

4. **Verify deployment:**
```bash
curl http://localhost:8000/health
```

### Option 2: Kubernetes (Recommended for Production)

1. **Setup Kubernetes cluster:**
```bash
# Create namespace
kubectl create namespace graphrag-system

# Apply configurations
kubectl apply -f deployments/kubernetes/
```

2. **Configure secrets:**
```bash
kubectl create secret generic db-credentials \
  --from-literal=postgres-url="postgresql://user:pass@postgres:5432/graphrag" \
  -n graphrag-system

kubectl create secret generic api-keys \
  --from-literal=openai-api-key="your-key" \
  --from-literal=huggingface-token="your-token" \
  -n graphrag-system
```

3. **Deploy the application:**
```bash
kubectl apply -f deployments/kubernetes/website-graphrag-processor.yaml
```

4. **Setup ingress and load balancer:**
```bash
kubectl apply -f deployments/kubernetes/ingress.yaml
```

## Configuration Management

### Environment Variables
```bash
# Core Configuration
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO

# Database Configuration
POSTGRES_URL=postgresql://user:pass@postgres:5432/graphrag_db
REDIS_URL=redis://redis:6379/0

# IPFS Configuration
IPFS_API_URL=http://ipfs:5001
IPFS_GATEWAY_URL=http://ipfs:8080

# Processing Configuration
MAX_PARALLEL_JOBS=5
MAX_CONTENT_SIZE_MB=500
PROCESSING_TIMEOUT_MINUTES=60

# ML/AI Configuration
OPENAI_API_KEY=your_openai_key
HUGGINGFACE_TOKEN=your_hf_token
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# Monitoring Configuration
METRICS_ENABLED=true
GRAFANA_URL=http://grafana:3000
PROMETHEUS_URL=http://prometheus:9090
```

### Production Optimizations

#### 1. Performance Tuning
```python
# File: production_config.py
PRODUCTION_CONFIG = {
    'processing': {
        'max_parallel_websites': 10,
        'max_parallel_content_items': 50,
        'batch_size_html': 100,
        'batch_size_pdf': 20,
        'batch_size_media': 5,
        'cache_ttl_hours': 24,
        'memory_limit_gb': 8
    },
    'graphrag': {
        'vector_store_type': 'faiss',
        'embedding_batch_size': 32,
        'knowledge_graph_confidence_threshold': 0.8,
        'max_graph_entities': 10000
    },
    'monitoring': {
        'metrics_collection_interval': 30,
        'log_retention_days': 30,
        'alert_thresholds': {
            'processing_time_minutes': 30,
            'memory_usage_percent': 80,
            'error_rate_percent': 5
        }
    }
}
```

#### 2. Caching Strategy
```python
# File: caching_config.py
CACHE_CONFIG = {
    'redis': {
        'processed_content_ttl': 3600 * 24 * 7,  # 7 days
        'embeddings_ttl': 3600 * 24 * 30,  # 30 days
        'knowledge_graph_ttl': 3600 * 24 * 14,  # 14 days
        'query_results_ttl': 3600 * 2,  # 2 hours
    },
    'filesystem': {
        'warc_files_retention_days': 30,
        'media_files_retention_days': 7,
        'temp_processing_cleanup_hours': 6
    }
}
```

## Monitoring and Observability

### Metrics Collection
The system automatically collects comprehensive metrics:

- **Processing Metrics**: Success rates, processing times, throughput
- **Content Metrics**: Content types processed, quality scores
- **System Metrics**: CPU, memory, storage usage
- **Query Metrics**: Search performance, result relevance

### Health Checks
```python
# Health check endpoints
GET /health              # Basic health check
GET /health/detailed     # Detailed system status
GET /health/dependencies # External dependency status
GET /metrics            # Prometheus metrics endpoint
```

### Alerting Rules
```yaml
# File: monitoring/alerts.yaml
groups:
  - name: graphrag-alerts
    rules:
    - alert: HighProcessingTime
      expr: avg_processing_time_seconds > 1800  # 30 minutes
      for: 5m
      annotations:
        summary: "Website processing taking too long"
    
    - alert: HighMemoryUsage
      expr: memory_usage_percent > 85
      for: 2m
      annotations:
        summary: "High memory usage detected"
    
    - alert: ProcessingFailureRate
      expr: processing_failure_rate > 0.1  # 10% failure rate
      for: 5m
      annotations:
        summary: "High processing failure rate"
```

## Security Configuration

### Authentication and Authorization
```python
# File: security_config.py
SECURITY_CONFIG = {
    'auth': {
        'jwt_secret_key': 'your-secret-key',
        'jwt_algorithm': 'HS256',
        'token_expiry_hours': 24,
        'refresh_token_expiry_days': 30
    },
    'rate_limiting': {
        'requests_per_minute': 60,
        'processing_jobs_per_hour': 10,
        'query_requests_per_minute': 100
    },
    'data_protection': {
        'encrypt_stored_content': True,
        'anonymize_user_queries': True,
        'content_retention_days': 90
    }
}
```

### API Security
- JWT-based authentication
- Rate limiting per user/API key
- Request validation and sanitization
- CORS configuration for web clients
- HTTPS enforcement

## Backup and Recovery

### Automated Backups
```bash
# Database backup script (runs daily)
#!/bin/bash
pg_dump $POSTGRES_URL > /backups/graphrag_$(date +%Y%m%d).sql
aws s3 cp /backups/ s3://your-backup-bucket/ --recursive

# IPFS data backup
ipfs pin ls --type=recursive > /backups/ipfs_pins_$(date +%Y%m%d).txt
```

### Disaster Recovery
1. **Database Recovery**: Restore from latest SQL backup
2. **IPFS Data Recovery**: Re-pin content from backup pin list
3. **Configuration Recovery**: Deploy from version-controlled configs
4. **Processing State Recovery**: Resume from job queue checkpoints

## Scaling Considerations

### Horizontal Scaling
- Deploy multiple processor instances behind load balancer
- Use Redis for job distribution across instances
- Scale IPFS nodes in cluster configuration
- Implement database read replicas for queries

### Vertical Scaling
- Increase CPU cores for faster parallel processing
- Add memory for larger content processing
- Use faster storage (NVMe SSD) for temporary files
- Optimize network bandwidth for web archiving

### Auto-scaling Configuration
```yaml
# Kubernetes HPA configuration
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: website-graphrag-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: website-graphrag-processor
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

## Maintenance and Updates

### Regular Maintenance Tasks
1. **Daily**: Check system health, review error logs
2. **Weekly**: Clean temporary files, update processing statistics
3. **Monthly**: Review and optimize configurations, update dependencies
4. **Quarterly**: Perform full system backup test, capacity planning review

### Update Procedures
1. **Code Updates**: Use blue-green deployment with health checks
2. **Database Migrations**: Test in staging, run during low-traffic periods
3. **Configuration Updates**: Use rolling updates with validation
4. **Dependency Updates**: Update in staging first, monitor for issues

### Performance Monitoring
- Set up Grafana dashboards for real-time monitoring
- Configure automated alerts for system anomalies
- Regular performance baseline reviews
- Capacity planning based on usage trends

## Troubleshooting Guide

### Common Issues and Solutions

#### High Memory Usage
```bash
# Check memory usage by component
docker stats
kubectl top pods -n graphrag-system

# Solutions:
# 1. Reduce batch sizes in configuration
# 2. Increase memory limits
# 3. Optimize content caching strategy
```

#### Processing Timeouts
```bash
# Check processing queue
redis-cli -h redis LLEN processing_queue

# Solutions:
# 1. Increase timeout values
# 2. Add more worker instances
# 3. Optimize processing pipeline
```

#### IPFS Connection Issues
```bash
# Check IPFS node status
curl http://ipfs:5001/api/v0/version

# Solutions:
# 1. Restart IPFS node
# 2. Check network connectivity
# 3. Verify IPFS configuration
```

This deployment guide provides comprehensive instructions for getting the GraphRAG website processing system running in production with proper monitoring, security, and scalability considerations.