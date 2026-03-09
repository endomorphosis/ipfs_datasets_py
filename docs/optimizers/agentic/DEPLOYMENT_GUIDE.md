# Deployment Guide - Agentic Optimizer

**Document Version:** 1.0  
**Last Updated:** 2026-02-14  
**Target Audience:** DevOps Engineers, System Administrators, Deployment Teams

## Overview

This guide provides comprehensive deployment best practices for the agentic optimizer framework, from development through production deployment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Security Hardening](#security-hardening)
5. [Deployment Strategies](#deployment-strategies)
6. [Monitoring](#monitoring)
7. [Backup and Recovery](#backup-and-recovery)
8. [Scaling](#scaling)
9. [Troubleshooting](#troubleshooting)
10. [Maintenance](#maintenance)

---

## Prerequisites

### System Requirements

**Minimum:**
- Python 3.12+
- 2 CPU cores
- 4GB RAM
- 10GB disk space
- Network connectivity for LLM APIs

**Recommended:**
- Python 3.12+
- 4+ CPU cores
- 8GB+ RAM
- 50GB+ disk space (for caching)
- SSD storage
- 10+ Mbps network

### Software Dependencies

**Required:**
```bash
python3.12 (or higher)
pip (latest)
git (for repository operations)
```

**Optional but Recommended:**
```bash
mypy (type checking)
pytest (testing)
docker (containerization)
```

### LLM Provider Access

**At least one of:**
- OpenAI API key (GPT-4, Codex)
- Anthropic API key (Claude)
- Google API key (Gemini)
- Local model setup (HuggingFace)

---

## Installation

### 1. Development Installation

```bash
# Clone repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install with all features
pip install -e ".[all]"

# Verify installation
python -c "from ipfs_datasets_py.optimizers.agentic import OptimizerLLMRouter; print('✅ Installation successful')"
```

### 2. Production Installation

```bash
# Create dedicated user
sudo useradd -r -m -s /bin/bash optimizer
sudo -u optimizer -i

# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv git

# Install application
cd /opt
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install production dependencies
pip install --no-cache-dir -e ".[all]"

# Verify installation
python -m ipfs_datasets_py.optimizers.agentic.cli --help
```

### 3. Docker Installation

```dockerfile
# Dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -r -m -s /bin/bash optimizer

# Set working directory
WORKDIR /app

# Copy application
COPY . /app/

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[all]"

# Set user
USER optimizer

# Health check
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "from ipfs_datasets_py.optimizers.agentic import OptimizerLLMRouter" || exit 1

# Default command
CMD ["python", "-m", "ipfs_datasets_py.optimizers.agentic.cli", "--help"]
```

```bash
# Build and run
docker build -t agentic-optimizer:latest .
docker run -it --rm \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v $(pwd)/data:/app/data \
  agentic-optimizer:latest
```

---

## Configuration

### 1. Environment Variables

Create `.env` file:
```bash
# LLM Provider Configuration
IPFS_DATASETS_PY_LLM_PROVIDER=claude  # or gpt4, codex, etc.
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
GEMINI_API_KEY=your-key-here

# Optimizer Configuration
OPTIMIZER_MAX_AGENTS=5
OPTIMIZER_VALIDATION_LEVEL=standard
OPTIMIZER_CHANGE_CONTROL=patch  # or github

# IPFS Configuration
IPFS_GATEWAY=http://127.0.0.1:5001

# GitHub Configuration (if using github change control)
GITHUB_TOKEN=ghp_your-token-here
GITHUB_REPO=owner/repo

# Security Configuration
OPTIMIZER_ENABLE_SANDBOX=true
OPTIMIZER_MAX_MEMORY_MB=512
OPTIMIZER_MAX_CPU_PERCENT=80

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/optimizer/optimizer.log
```

### 2. Configuration File

Create `.optimizer-config.json`:
```json
{
  "change_control": "patch",
  "validation_level": "standard",
  "max_agents": 5,
  "ipfs_gateway": "http://127.0.0.1:5001",
  "github_repo": null,
  "github_token": null
}
```

### 3. Security Configuration

```python
# security_config.py
from ipfs_datasets_py.optimizers.agentic.production_hardening import SecurityConfig

config = SecurityConfig(
    # Sandboxing
    enable_sandbox=True,
    sandbox_timeout=60,
    max_memory_mb=512,
    max_cpu_percent=80,
    
    # Input validation
    allowed_file_extensions=['.py', '.js', '.ts', '.java', '.go', '.rs'],
    max_file_size_mb=10,
    
    # Token security
    mask_tokens_in_logs=True,
)
```

---

## Security Hardening

### 1. File Permissions

```bash
# Set proper ownership
sudo chown -R optimizer:optimizer /opt/ipfs_datasets_py

# Secure configuration files
chmod 600 .env
chmod 600 .optimizer-config.json

# Secure log directory
sudo mkdir -p /var/log/optimizer
sudo chown optimizer:optimizer /var/log/optimizer
chmod 750 /var/log/optimizer

# Secure cache directory
mkdir -p .cache/github-api
chmod 700 .cache
```

### 2. API Key Security

**Never commit API keys:**
```bash
# Add to .gitignore
echo ".env" >> .gitignore
echo ".optimizer-config.json" >> .gitignore
echo "*.pem" >> .gitignore
echo "*.key" >> .gitignore
```

**Rotate keys regularly:**
```bash
# OpenAI
# 1. Generate new key in OpenAI dashboard
# 2. Update .env file
# 3. Restart optimizer
# 4. Revoke old key

# Document rotation in security log
echo "$(date): Rotated OpenAI API key" >> /var/log/optimizer/security.log
```

### 3. Network Security

```bash
# Firewall rules (iptables)
sudo iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT  # HTTPS
sudo iptables -A OUTPUT -p tcp --dport 5001 -j ACCEPT  # IPFS
sudo iptables -A OUTPUT -j DROP  # Drop all other outbound

# Or use ufw
sudo ufw allow out 443/tcp
sudo ufw allow out 5001/tcp
sudo ufw default deny outgoing
```

### 4. Process Isolation

```bash
# Run as non-root user
sudo -u optimizer python -m ipfs_datasets_py.optimizers.agentic.cli

# Use systemd for process management (see section below)
```

---

## Deployment Strategies

### 1. Development Deployment

```bash
# Simple script execution
python -m ipfs_datasets_py.optimizers.agentic.cli optimize \
  --method test_driven \
  --target src/mycode.py \
  --description "Development optimization"
```

### 2. CI/CD Integration (GitHub Actions)

```yaml
# .github/workflows/agentic-optimization.yml
name: Agentic Code Optimization

on:
  schedule:
    - cron: '0 0 * * 1'  # Weekly on Monday
  workflow_dispatch:
    inputs:
      target_files:
        description: 'Files to optimize'
        required: true
        default: 'ipfs_datasets_py/'
      method:
        description: 'Optimization method'
        required: true
        default: 'test_driven'
        type: choice
        options:
          - test_driven
          - adversarial
          - actor_critic
          - chaos

jobs:
  optimize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install optimizer
        run: |
          pip install -e ".[all]"
      
      - name: Run optimization
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python -m ipfs_datasets_py.optimizers.agentic.cli optimize \
            --method ${{ github.event.inputs.method || 'test_driven' }} \
            --target ${{ github.event.inputs.target_files || 'ipfs_datasets_py/' }} \
            --description "Automated optimization"
      
      - name: Create PR
        if: success()
        uses: peter-evans/create-pull-request@v5
        with:
          title: "🤖 Automated code optimization"
          body: "Automated optimization via agentic optimizer"
          branch: "optimize/${{ github.run_id }}"
```

### 3. Production Deployment (systemd)

```ini
# /etc/systemd/system/optimizer.service
[Unit]
Description=Agentic Optimizer Service
After=network.target

[Service]
Type=simple
User=optimizer
Group=optimizer
WorkingDirectory=/opt/ipfs_datasets_py
Environment="PATH=/opt/ipfs_datasets_py/venv/bin"
EnvironmentFile=/opt/ipfs_datasets_py/.env
ExecStart=/opt/ipfs_datasets_py/venv/bin/python -m ipfs_datasets_py.optimizers.agentic.cli optimize --method test_driven --target /opt/target --description "Production optimization"
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/optimizer/optimizer.log
StandardError=append:/var/log/optimizer/error.log

# Security hardening
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/ipfs_datasets_py /var/log/optimizer

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable optimizer.service
sudo systemctl start optimizer.service

# Check status
sudo systemctl status optimizer.service
```

### 4. Kubernetes Deployment

```yaml
# optimizer-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agentic-optimizer
  labels:
    app: optimizer
spec:
  replicas: 1
  selector:
    matchLabels:
      app: optimizer
  template:
    metadata:
      labels:
        app: optimizer
    spec:
      containers:
      - name: optimizer
        image: agentic-optimizer:latest
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: optimizer-secrets
              key: openai-api-key
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: optimizer-secrets
              key: anthropic-api-key
        resources:
          requests:
            memory: "1Gi"
            cpu: "1000m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        volumeMounts:
        - name: config
          mountPath: /app/.optimizer-config.json
          subPath: config.json
      volumes:
      - name: config
        configMap:
          name: optimizer-config
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: optimizer-config
data:
  config.json: |
    {
      "change_control": "patch",
      "validation_level": "standard",
      "max_agents": 5
    }
---
apiVersion: v1
kind: Secret
metadata:
  name: optimizer-secrets
type: Opaque
stringData:
  openai-api-key: "sk-your-key-here"
  anthropic-api-key: "sk-ant-your-key-here"
```

```bash
# Deploy to Kubernetes
kubectl apply -f optimizer-deployment.yaml

# Check status
kubectl get pods -l app=optimizer
kubectl logs -f deployment/agentic-optimizer
```

---

## Monitoring

### 1. Application Monitoring

```python
# monitoring.py
from ipfs_datasets_py.optimizers.agentic import ResourceMonitor
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

monitor = ResourceMonitor()

# Monitor all operations
with monitor.monitor():
    # Your optimization
    result = optimizer.optimize(task)

stats = monitor.get_stats()
logger.info(f"Optimization completed in {stats['elapsed_time']:.2f}s")
logger.info(f"Peak memory usage: {stats['peak_memory_mb']:.1f}MB")

# Alert on high resource usage
if stats['peak_memory_mb'] > 1000:
    logger.warning("High memory usage detected!")
```

### 2. Log Monitoring

```bash
# Set up log rotation
sudo tee /etc/logrotate.d/optimizer <<EOF
/var/log/optimizer/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 optimizer optimizer
    sharedscripts
    postrotate
        systemctl reload optimizer.service > /dev/null 2>&1 || true
    endscript
}
EOF

# Test log rotation
sudo logrotate -d /etc/logrotate.d/optimizer
sudo logrotate -f /etc/logrotate.d/optimizer
```

### 3. Health Checks

```python
# health_check.py
from ipfs_datasets_py.optimizers.agentic import OptimizerLLMRouter
import sys

try:
    # Test LLM connection
    router = OptimizerLLMRouter()
    
    # Test basic functionality
    response = router.generate(
        prompt="Test",
        method=OptimizationMethod.TEST_DRIVEN,
        max_tokens=10,
    )
    
    print("✅ Health check passed")
    sys.exit(0)
except Exception as e:
    print(f"❌ Health check failed: {e}")
    sys.exit(1)
```

```bash
# Add to cron for periodic checks
*/5 * * * * /opt/ipfs_datasets_py/venv/bin/python /opt/ipfs_datasets_py/health_check.py
```

### 4. Metrics Collection

```python
# metrics.py
from ipfs_datasets_py.optimizers.agentic import OptimizerLLMRouter
from prometheus_client import Counter, Histogram, Gauge
import prometheus_client

# Define metrics
optimization_count = Counter('optimizer_optimizations_total', 'Total optimizations')
optimization_duration = Histogram('optimizer_duration_seconds', 'Optimization duration')
memory_usage = Gauge('optimizer_memory_mb', 'Memory usage in MB')

# Collect metrics
router = OptimizerLLMRouter()
stats = router.get_statistics()

optimization_count.inc(stats['total_calls'])
memory_usage.set(stats['peak_memory_mb'])

# Export metrics
prometheus_client.write_to_textfile('/var/lib/prometheus/optimizer.prom', prometheus_client.REGISTRY)
```

---

## Backup and Recovery

### 1. Configuration Backup

```bash
# Backup script
#!/bin/bash
BACKUP_DIR=/backup/optimizer/$(date +%Y%m%d)
mkdir -p $BACKUP_DIR

# Backup configuration
cp .env $BACKUP_DIR/
cp .optimizer-config.json $BACKUP_DIR/

# Backup learned policies
cp learned_policies.json $BACKUP_DIR/ 2>/dev/null || true

# Backup logs (last 7 days)
find /var/log/optimizer -name "*.log" -mtime -7 -exec cp {} $BACKUP_DIR/ \;

# Compress
tar -czf $BACKUP_DIR.tar.gz $BACKUP_DIR/
rm -rf $BACKUP_DIR

echo "Backup completed: $BACKUP_DIR.tar.gz"
```

### 2. State Recovery

```bash
# Recovery script
#!/bin/bash
BACKUP_FILE=$1

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup-file.tar.gz>"
    exit 1
fi

# Extract backup
tar -xzf $BACKUP_FILE -C /tmp/

# Restore configuration
cp /tmp/optimizer/*/env .env
cp /tmp/optimizer/*/.optimizer-config.json .optimizer-config.json

# Restore policies
cp /tmp/optimizer/*/learned_policies.json . 2>/dev/null || true

echo "Recovery completed"
```

---

## Scaling

### 1. Horizontal Scaling

```bash
# Run multiple optimizer instances
for i in {1..5}; do
    python -m ipfs_datasets_py.optimizers.agentic.cli optimize \
        --method test_driven \
        --target "batch_${i}/*.py" \
        --description "Batch ${i}" &
done

wait
echo "All batches completed"
```

### 2. Load Balancing

```nginx
# nginx.conf
upstream optimizer {
    least_conn;
    server optimizer1:8000;
    server optimizer2:8000;
    server optimizer3:8000;
}

server {
    listen 80;
    
    location / {
        proxy_pass http://optimizer;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Troubleshooting

### Common Issues

**1. Import Errors:**
```bash
# Check Python version
python --version  # Should be 3.12+

# Reinstall
pip install --force-reinstall -e ".[all]"
```

**2. API Key Issues:**
```bash
# Verify API key
echo $OPENAI_API_KEY | wc -c  # Should be ~50 characters

# Test API access
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

**3. Memory Issues:**
```bash
# Check available memory
free -h

# Reduce memory limit
export OPTIMIZER_MAX_MEMORY_MB=256
```

**4. Timeout Issues:**
```bash
# Increase timeout
export OPTIMIZER_SANDBOX_TIMEOUT=120
```

---

## Maintenance

### Regular Tasks

**Daily:**
- Check logs for errors
- Monitor resource usage
- Verify API connectivity

**Weekly:**
- Review optimization results
- Update learned policies
- Clean old cache files

**Monthly:**
- Rotate API keys
- Update dependencies
- Security audit
- Performance review

**Quarterly:**
- Full backup
- Disaster recovery drill
- Update documentation
- Review access controls

---

## Deployment Checklist

### Pre-Deployment
- [ ] Python 3.12+ installed
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] Configuration files created
- [ ] API keys configured
- [ ] File permissions set

### Deployment
- [ ] Application deployed
- [ ] Service started
- [ ] Health checks passing
- [ ] Logs accessible
- [ ] Monitoring configured

### Post-Deployment
- [ ] Run test optimization
- [ ] Verify results
- [ ] Check resource usage
- [ ] Review logs
- [ ] Document deployment

### Security
- [ ] API keys secured
- [ ] File permissions validated
- [ ] Network rules configured
- [ ] Sandbox enabled
- [ ] Token masking active

---

## Support

**Documentation:**
- README.md - Project overview
- SECURITY_AUDIT.md - Security features
- PERFORMANCE_TUNING.md - Performance optimization
- This document - Deployment guide

**Community:**
- GitHub Issues - Bug reports and feature requests
- GitHub Discussions - Questions and community support

**Professional Support:**
- Contact: support@example.com
- Enterprise support available

---

## Conclusion

Following this deployment guide ensures a secure, reliable, and performant deployment of the agentic optimizer framework. Regular maintenance and monitoring will help maintain optimal performance and security.

**Deployment Status Checklist:**
- ✅ Prerequisites met
- ✅ Application installed
- ✅ Configuration complete
- ✅ Security hardened
- ✅ Monitoring configured
- ✅ Backup strategy in place

**Your deployment is production-ready!**
