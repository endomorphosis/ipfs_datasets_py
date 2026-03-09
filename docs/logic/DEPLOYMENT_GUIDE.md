# Logic Module Deployment Guide

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Status:** Production Deployment Guide

---

## Table of Contents

- [Deployment Overview](#deployment-overview)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [IPFS Integration](#ipfs-integration)
- [Production Deployment](#production-deployment)
- [Monitoring and Observability](#monitoring-and-observability)
- [Troubleshooting](#troubleshooting)

---

## Deployment Overview

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Load Balancer / API Gateway          │
└────────────────────┬───────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
┌────────┴───────┐      ┌───────┴───────┐
│  Logic Module  │      │  Logic Module  │  (Replicas)
│   Instance 1   │      │   Instance 2   │
└────────┬───────┘      └───────┬───────┘
         │                       │
         └───────────┬───────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
┌────────┴────────┐    ┌─────────┴────────┐
│   IPFS Node     │    │   Redis/Cache    │
│  (Storage)      │    │  (Rate Limiting) │
└─────────────────┘    └──────────────────┘
```

### Deployment Options

1. **Local Development** - Standalone Python process
2. **Docker Container** - Containerized deployment
3. **Kubernetes** - Orchestrated multi-instance
4. **Serverless** - AWS Lambda / Google Cloud Functions
5. **Edge** - Cloudflare Workers / Similar

---

## System Requirements

### Minimum Requirements

- **Python:** 3.12+
- **Memory:** 512MB RAM
- **CPU:** 1 core
- **Disk:** 1GB free space
- **Network:** Internet access for package installation

### Recommended Production Requirements

- **Python:** 3.12+
- **Memory:** 2-4GB RAM
- **CPU:** 2-4 cores
- **Disk:** 10GB+ free space (for caching)
- **Network:** Low-latency network to IPFS nodes

### Optional Dependencies

- **IPFS:** For distributed proof caching
- **Redis:** For distributed rate limiting
- **spaCy:** For enhanced NLP (300MB+ models)
- **Z3/Lean/Coq:** For external proof verification

---

## Installation

### Standard Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install package
pip install ipfs-datasets-py

# Verify installation
python -c "from ipfs_datasets_py.logic import FOLConverter; print('OK')"
```

### Installation with Optional Dependencies

```bash
# Install with all optional dependencies
pip install ipfs-datasets-py[all]

# Or install specific extras
pip install ipfs-datasets-py[spacy]   # NLP enhancement
pip install ipfs-datasets-py[ipfs]    # IPFS integration
pip install ipfs-datasets-py[redis]   # Redis for rate limiting
pip install ipfs-datasets-py[test]    # Testing tools
```

### From Source

```bash
# Clone repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Install in development mode
pip install -e ".[all]"

# Run tests
pytest tests/
```

---

## Configuration

### Environment Variables

```bash
# Core configuration
export LOGIC_DEBUG=0                    # 0=off, 1=on
export LOGIC_MAX_INPUT_SIZE=10000       # 10KB max input
export LOGIC_MAX_PROOF_TIME=30          # 30s timeout
export LOGIC_CACHE_ENABLED=1            # Enable caching

# IPFS configuration
export IPFS_HOST=localhost
export IPFS_PORT=5001
export IPFS_PROTOCOL=http

# Redis configuration (for rate limiting)
export REDIS_URL=redis://localhost:6379/0

# Monitoring
export PROMETHEUS_PORT=9090
export LOG_LEVEL=INFO
```

### Configuration File

```python
# config.py
from ipfs_datasets_py.logic.config import LogicConfig

config = LogicConfig(
    # Input validation
    max_input_size=10000,
    max_formula_depth=100,
    max_quantifiers=20,
    
    # Performance
    max_proof_time=30,
    enable_cache=True,
    cache_max_size=1000,
    cache_ttl_seconds=3600,
    
    # Rate limiting
    rate_limit_enabled=True,
    rate_limit_calls=100,
    rate_limit_period=60,
    
    # Security
    suspicious_pattern_check=True,
    
    # IPFS
    ipfs_enabled=False,
    ipfs_host="localhost",
    ipfs_port=5001,
    
    # External provers
    z3_enabled=True,
    lean_enabled=False,
    coq_enabled=False,
)
```

### Application Configuration

```python
# app.py
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.config import load_config

# Load configuration
config = load_config("config.py")

# Initialize converter
converter = FOLConverter(config=config)

# Use converter
result = converter.convert("All cats are animals")
```

---

## IPFS Integration

### Install IPFS

```bash
# Download IPFS
wget https://dist.ipfs.io/kubo/v0.20.0/kubo_v0.20.0_linux-amd64.tar.gz
tar -xvzf kubo_v0.20.0_linux-amd64.tar.gz
cd kubo
sudo bash install.sh

# Initialize IPFS
ipfs init

# Start IPFS daemon
ipfs daemon &
```

### Configure IPFS Integration

```python
from ipfs_datasets_py.logic.integration.caching import IPFSProofCache

# Initialize IPFS cache
ipfs_cache = IPFSProofCache(
    ipfs_host="localhost",
    ipfs_port=5001,
    max_size=1000,
)

# Use IPFS-backed proof cache
from ipfs_datasets_py.logic.integration import prove_formula

result = prove_formula(
    "P → Q",
    assumptions=["P"],
    cache=ipfs_cache,  # Proof cached to IPFS
)
```

### IPFS Clustering

```bash
# Configure IPFS cluster for multi-node deployment
ipfs-cluster-service init
ipfs-cluster-service daemon &

# Cluster configuration
export CLUSTER_SECRET=$(od -vN 32 -An -tx1 /dev/urandom | tr -d ' \n')
export IPFS_CLUSTER_BOOTSTRAP=/ip4/bootstrap-node-ip/tcp/9096/ipfs/QmHash
```

### IPFS Best Practices

1. **Pin Important Data:** Pin proof caches to prevent garbage collection
   ```bash
   ipfs pin add QmProofCacheHash
   ```

2. **Use IPFS Gateway:** Serve proofs via HTTP
   ```
   https://ipfs.io/ipfs/QmProofCacheHash
   ```

3. **Monitor IPFS Health:**
   ```bash
   ipfs stats bw
   ipfs swarm peers
   ipfs repo gc
   ```

4. **Secure IPFS API:** Restrict API access
   ```json
   {
     "API": {
       "HTTPHeaders": {
         "Access-Control-Allow-Origin": ["http://your-domain.com"]
       }
     }
   }
   ```

---

## Production Deployment

### Docker Deployment

**Dockerfile:**
```dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 logic
USER logic
WORKDIR /home/logic

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY --chown=logic:logic . /home/logic/app
WORKDIR /home/logic/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "from ipfs_datasets_py.logic import FOLConverter; FOLConverter()" || exit 1

# Run application
CMD ["python", "-m", "ipfs_datasets_py.logic.api_server"]
```

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  logic-module:
    build: .
    ports:
      - "8000:8000"
    environment:
      - LOGIC_DEBUG=0
      - REDIS_URL=redis://redis:6379/0
      - IPFS_HOST=ipfs
    depends_on:
      - redis
      - ipfs
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 512M
    restart: unless-stopped
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    restart: unless-stopped
  
  ipfs:
    image: ipfs/kubo:latest
    ports:
      - "4001:4001"
      - "5001:5001"
      - "8080:8080"
    volumes:
      - ipfs-data:/data/ipfs
    restart: unless-stopped

volumes:
  redis-data:
  ipfs-data:
```

**Run:**
```bash
docker-compose up -d
docker-compose logs -f logic-module
```

### Kubernetes Deployment

**deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: logic-module
  labels:
    app: logic-module
spec:
  replicas: 3
  selector:
    matchLabels:
      app: logic-module
  template:
    metadata:
      labels:
        app: logic-module
    spec:
      containers:
      - name: logic
        image: logic-module:2.0.0
        ports:
        - containerPort: 8000
          name: http
        
        env:
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: logic-secrets
              key: redis-url
        - name: IPFS_HOST
          value: ipfs-service
        
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
        
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true

---
apiVersion: v1
kind: Service
metadata:
  name: logic-service
spec:
  selector:
    app: logic-module
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer

---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: logic-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: logic-module
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

**Deploy:**
```bash
kubectl apply -f deployment.yaml
kubectl get pods -l app=logic-module
kubectl logs -l app=logic-module -f
```

### Serverless Deployment

**AWS Lambda:**
```python
# lambda_handler.py
import json
from ipfs_datasets_py.logic.fol import FOLConverter

# Initialize once (reused across invocations)
converter = FOLConverter(use_fallback=True)

def lambda_handler(event, context):
    try:
        body = json.loads(event['body'])
        text = body['text']
        
        # Validate input
        if len(text) > 10000:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Input too large'})
            }
        
        # Convert
        result = converter.convert(text)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': result.success,
                'fol': result.fol,
                'confidence': result.confidence,
            })
        }
    
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
```

**serverless.yml:**
```yaml
service: logic-module

provider:
  name: aws
  runtime: python3.12
  memorySize: 1024
  timeout: 30
  
  environment:
    LOGIC_DEBUG: 0
    LOGIC_MAX_INPUT_SIZE: 10000

functions:
  convert:
    handler: lambda_handler.lambda_handler
    events:
      - http:
          path: convert
          method: post
          cors: true

plugins:
  - serverless-python-requirements
```

**Deploy:**
```bash
serverless deploy
```

---

## Monitoring and Observability

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# Define metrics
conversion_counter = Counter(
    'logic_conversions_total',
    'Total number of conversions'
)
conversion_duration = Histogram(
    'logic_conversion_duration_seconds',
    'Conversion duration'
)
cache_hit_rate = Gauge(
    'logic_cache_hit_rate',
    'Cache hit rate'
)

# Instrument code
from ipfs_datasets_py.logic.fol import FOLConverter
import time

class MonitoredConverter(FOLConverter):
    def convert(self, text):
        conversion_counter.inc()
        
        start = time.time()
        result = super().convert(text)
        duration = time.time() - start
        
        conversion_duration.observe(duration)
        
        return result

# Start metrics server
start_http_server(9090)
```

### Logging Configuration

```python
import logging
import json

# JSON logging for production
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
        }
        return json.dumps(log_data)

# Configure logging
logger = logging.getLogger('ipfs_datasets_py.logic')
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
```

### Health Checks

```python
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/health')
def health():
    """Liveness probe - is service running?"""
    return jsonify({"status": "healthy"}), 200

@app.route('/ready')
def ready():
    """Readiness probe - can service handle requests?"""
    try:
        # Check dependencies
        converter = FOLConverter()
        converter.convert("test")
        
        # Check cache
        from ipfs_datasets_py.logic.integration.caching import get_global_cache
        cache = get_global_cache()
        cache.stats()
        
        return jsonify({"status": "ready"}), 200
    
    except Exception as e:
        return jsonify({"status": "not ready", "error": str(e)}), 503

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
```

### Grafana Dashboard

```json
{
  "dashboard": {
    "title": "Logic Module Monitoring",
    "panels": [
      {
        "title": "Conversion Rate",
        "targets": [
          {
            "expr": "rate(logic_conversions_total[5m])"
          }
        ]
      },
      {
        "title": "Conversion Duration (P95)",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, logic_conversion_duration_seconds_bucket)"
          }
        ]
      },
      {
        "title": "Cache Hit Rate",
        "targets": [
          {
            "expr": "logic_cache_hit_rate"
          }
        ]
      },
      {
        "title": "Error Rate",
        "targets": [
          {
            "expr": "rate(logic_errors_total[5m])"
          }
        ]
      }
    ]
  }
}
```

---

## Troubleshooting

### Common Issues

**Issue: "Module not found"**
```bash
# Solution: Ensure virtual environment is activated
source venv/bin/activate
pip install ipfs-datasets-py
```

**Issue: "IPFS connection refused"**
```bash
# Solution: Start IPFS daemon
ipfs daemon &

# Check IPFS is running
curl http://localhost:5001/api/v0/version
```

**Issue: "Memory exhausted"**
```bash
# Solution: Increase memory limits
export LOGIC_MAX_INPUT_SIZE=5000  # Reduce max input
export LOGIC_CACHE_MAX_SIZE=500   # Reduce cache

# Or increase Docker memory
docker run -m 4g logic-module
```

**Issue: "Slow conversions"**
```bash
# Solution: Enable caching
export LOGIC_CACHE_ENABLED=1

# Or use parallel processing
python -c "
from ipfs_datasets_py.logic.fol import FOLConverter
converter = FOLConverter()
results = converter.convert_batch(texts, parallel=True)
"
```

### Debug Mode

```bash
# Enable debug logging
export LOGIC_DEBUG=1

# Run with verbose output
python -m ipfs_datasets_py.logic --verbose

# Check logs
tail -f /var/log/logic-module.log
```

### Performance Issues

```bash
# Profile application
python -m cProfile -o profile.stats app.py
python -m pstats profile.stats

# Memory profiling
python -m memory_profiler app.py

# Monitor resource usage
docker stats logic-module
kubectl top pod -l app=logic-module
```

---

## Scaling Strategies

### Horizontal Scaling

```yaml
# Kubernetes HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: logic-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: logic-module
  minReplicas: 2
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

### Vertical Scaling

```yaml
# Increase resources per pod
resources:
  requests:
    memory: "2Gi"
    cpu: "2000m"
  limits:
    memory: "8Gi"
    cpu: "4000m"
```

### Caching Strategy

```python
# Multi-tier caching
from ipfs_datasets_py.logic.integration.caching import (
    ProofCache,
    IPFSProofCache,
)

# L1: In-memory cache (fast)
l1_cache = ProofCache(max_size=1000, ttl_seconds=300)

# L2: Redis cache (shared)
l2_cache = RedisProofCache(redis_url="redis://localhost:6379/0")

# L3: IPFS cache (persistent)
l3_cache = IPFSProofCache(ipfs_host="localhost", ipfs_port=5001)

# Use cascading cache
def get_proof(formula):
    # Check L1
    if formula in l1_cache:
        return l1_cache.get(formula)
    
    # Check L2
    if formula in l2_cache:
        result = l2_cache.get(formula)
        l1_cache.set(formula, result)
        return result
    
    # Check L3
    if formula in l3_cache:
        result = l3_cache.get(formula)
        l2_cache.set(formula, result)
        l1_cache.set(formula, result)
        return result
    
    # Compute and cache
    result = prove_formula(formula)
    l3_cache.set(formula, result)
    l2_cache.set(formula, result)
    l1_cache.set(formula, result)
    return result
```

---

## Summary

**Key Points:**
- ✅ System requirements: Python 3.12+, 512MB+ RAM
- ✅ Multiple deployment options: Docker, K8s, Serverless
- ✅ IPFS integration for distributed caching
- ✅ Configuration via environment variables or config file
- ✅ Monitoring with Prometheus and Grafana
- ✅ Health checks for readiness/liveness
- ✅ Horizontal and vertical scaling strategies

**For more details:**
- [SECURITY_GUIDE.md](./SECURITY_GUIDE.md) - Security hardening
- [PERFORMANCE_TUNING.md](./PERFORMANCE_TUNING.md) - Performance optimization
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Common issues

---

**Document Status:** Production Deployment Guide  
**Maintained By:** Logic Module DevOps Team  
**Review Frequency:** Every MINOR release
