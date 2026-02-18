# TDFOL Deployment Infrastructure

> **Production-ready deployment for TDFOL (Temporal Dynamic First-Order Logic) Service**

This directory contains comprehensive deployment infrastructure for TDFOL across multiple platforms including Docker, Kubernetes, Helm, and major cloud providers.

## 📋 Contents

- [Quick Start](#quick-start)
- [Deployment Options](#deployment-options)
- [Directory Structure](#directory-structure)
- [Prerequisites](#prerequisites)
- [Documentation](#documentation)
- [Support](#support)

## 🚀 Quick Start

### Local Development with Docker Compose

```bash
# Clone the repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py/deployment/tdfol

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f tdfol

# Access the service
curl http://localhost:8080/health
```

### Production Deployment with Kubernetes

```bash
# Install with Helm
helm install tdfol ./helm/tdfol \
  --namespace tdfol \
  --create-namespace \
  --values ./helm/tdfol/values.yaml

# Check deployment status
kubectl get pods -n tdfol
kubectl get svc -n tdfol

# Access the service
kubectl port-forward -n tdfol svc/tdfol 8080:8080
curl http://localhost:8080/health
```

## 📦 Deployment Options

### 1. Docker (Local Development)

**Best for**: Local development, testing, and single-server deployments

```bash
# Build image
docker build -t tdfol:latest -f Dockerfile ../..

# Run container
docker run -d \
  -p 8080:8080 \
  -v tdfol-data:/app/data \
  --name tdfol \
  tdfol:latest
```

**Features**:
- Multi-stage build for optimization
- Production-ready image (<500MB)
- Non-root user for security
- Health checks
- Volume persistence

**Documentation**: [Docker Guide](./docker-compose.yml)

### 2. Docker Compose (Development)

**Best for**: Local development with multiple services

```bash
docker-compose up -d
```

**Includes**:
- TDFOL service
- Redis cache
- Prometheus monitoring
- Grafana dashboards

**Documentation**: [Docker Compose Guide](./docker-compose.yml)

### 3. Kubernetes (Production)

**Best for**: Production deployments with high availability

```bash
# Apply manifests
kubectl apply -f kubernetes/
```

**Features**:
- Multi-replica deployment
- Horizontal Pod Autoscaling
- Load balancing
- Persistent storage
- Health probes
- Resource limits

**Documentation**: [Kubernetes Guide](./kubernetes/README.md)

### 4. Helm Charts (Recommended)

**Best for**: Templated, reusable, production deployments

```bash
helm install tdfol ./helm/tdfol
```

**Features**:
- Configurable templates
- Environment-specific values
- Easy upgrades and rollbacks
- Dependency management

**Documentation**: [Helm Guide](./helm/tdfol/README.md)

### 5. Cloud Providers

Deploy to major cloud platforms with detailed guides:

- **[AWS](./docs/cloud-providers/AWS.md)**: ECS Fargate, EKS, ALB, RDS, ElastiCache
- **[GCP](./docs/cloud-providers/GCP.md)**: Cloud Run, GKE, Cloud SQL, Memorystore
- **[Azure](./docs/cloud-providers/AZURE.md)**: Container Instances, AKS, Azure SQL, Redis Cache

## 📁 Directory Structure

```
deployment/tdfol/
├── Dockerfile                    # Multi-stage production Dockerfile
├── .dockerignore                 # Docker build exclusions
├── docker-compose.yml            # Multi-service compose file
├── docker-compose.override.yml   # Development overrides
├── .env.example                  # Environment variables template
│
├── kubernetes/                   # Raw Kubernetes manifests
│   ├── namespace.yaml            # Namespace configuration
│   ├── configmap.yaml            # Configuration data
│   ├── secret.yaml               # Sensitive data (template)
│   ├── pvc.yaml                  # Persistent volume claims
│   ├── deployment.yaml           # Deployment specification
│   ├── service.yaml              # Service definitions (ClusterIP, NodePort, LoadBalancer)
│   ├── ingress.yaml              # Ingress configuration
│   ├── hpa.yaml                  # Horizontal Pod Autoscaler
│   ├── rbac.yaml                 # RBAC configuration
│   └── policies.yaml             # Network and disruption policies
│
├── helm/                         # Helm chart directory
│   ├── CHANGELOG.md              # Helm chart version history
│   └── tdfol/                    # TDFOL Helm chart
│       ├── Chart.yaml            # Chart metadata
│       ├── values.yaml           # Default values (configurable)
│       ├── README.md             # Chart documentation
│       └── templates/            # Kubernetes resource templates
│           ├── _helpers.tpl      # Template helpers
│           ├── deployment.yaml   # Deployment template
│           ├── service.yaml      # Service template
│           ├── ingress.yaml      # Ingress template
│           ├── configmap.yaml    # ConfigMap template
│           ├── secret.yaml       # Secret template
│           ├── pvc.yaml          # PVC templates
│           ├── hpa.yaml          # HPA template
│           ├── pdb.yaml          # Pod Disruption Budget
│           ├── serviceaccount.yaml  # ServiceAccount template
│           ├── redis.yaml        # Redis deployment
│           └── NOTES.txt         # Post-install notes
│
├── docs/                         # Documentation
│   └── cloud-providers/          # Cloud-specific guides
│       ├── AWS.md                # AWS deployment (ECS, EKS)
│       ├── GCP.md                # GCP deployment (Cloud Run, GKE)
│       └── AZURE.md              # Azure deployment (ACI, AKS)
│
├── monitoring/                   # Monitoring configuration
│   ├── prometheus.yml            # Prometheus config
│   ├── grafana-dashboards/       # Grafana dashboards
│   └── grafana-datasources/      # Grafana datasources
│
├── README.md                     # This file
└── QUICKSTART.md                 # Quick deployment guide
```

## 🔧 Prerequisites

### Common Requirements

- **Git**: Version control
- **Docker**: 20.10+ (for Docker deployments)
- **Docker Compose**: 2.0+ (for Compose deployments)
- **kubectl**: 1.28+ (for Kubernetes deployments)
- **Helm**: 3.2+ (for Helm deployments)

### Cloud-Specific Requirements

#### AWS
- AWS CLI 2.x
- eksctl (for EKS)
- Active AWS account

#### GCP
- Google Cloud SDK
- gcloud CLI
- Active GCP project

#### Azure
- Azure CLI
- Active Azure subscription

### System Requirements

**Minimum**:
- CPU: 2 cores
- RAM: 2GB
- Storage: 10GB

**Recommended (Production)**:
- CPU: 4 cores
- RAM: 4GB
- Storage: 20GB
- Load balancer
- Multiple instances (HA)

## 📚 Documentation

### Getting Started

1. **[Quick Start Guide](./QUICKSTART.md)** - Get running in 5 minutes
2. **[Docker Guide](./Dockerfile)** - Build and run with Docker
3. **[Kubernetes Guide](./kubernetes/README.md)** - Deploy to Kubernetes
4. **[Helm Guide](./helm/tdfol/README.md)** - Use Helm charts

### Cloud Providers

- **[AWS Deployment](./docs/cloud-providers/AWS.md)** - Complete AWS guide
- **[GCP Deployment](./docs/cloud-providers/GCP.md)** - Complete GCP guide
- **[Azure Deployment](./docs/cloud-providers/AZURE.md)** - Complete Azure guide

### Configuration

- **[Environment Variables](./.env.example)** - All configuration options
- **[Helm Values](./helm/tdfol/values.yaml)** - Chart configuration
- **[Kubernetes Configs](./kubernetes/configmap.yaml)** - K8s configuration

### Operations

- **Monitoring**: Prometheus + Grafana included
- **Logging**: CloudWatch, Stackdriver, Azure Monitor support
- **Scaling**: Horizontal Pod Autoscaler configured
- **High Availability**: Multi-replica with anti-affinity
- **Security**: Non-root, network policies, RBAC

## 🔐 Security Considerations

1. **Secrets Management**
   - Never commit secrets to version control
   - Use Kubernetes Secrets or cloud secret managers
   - Rotate secrets regularly

2. **Network Security**
   - Enable TLS/SSL for all external connections
   - Use network policies to restrict pod communication
   - Implement firewall rules

3. **Container Security**
   - Run as non-root user (UID 1000)
   - Scan images for vulnerabilities
   - Keep base images updated

4. **Access Control**
   - Use RBAC for Kubernetes access
   - Implement least-privilege IAM policies
   - Enable audit logging

## 💰 Cost Estimates

### Docker (Self-Hosted)

- **Small** (2 vCPU, 2GB RAM): $10-20/month
- **Medium** (4 vCPU, 4GB RAM): $40-80/month
- **Large** (8 vCPU, 8GB RAM): $80-160/month

### AWS

- **ECS Fargate**: $140-420/month
- **EKS**: $380-580/month
- See [AWS Guide](./docs/cloud-providers/AWS.md) for details

### GCP

- **Cloud Run**: $50-150/month
- **GKE**: $300-500/month
- See [GCP Guide](./docs/cloud-providers/GCP.md) for details

### Azure

- **Container Instances**: $60-180/month
- **AKS**: $350-550/month
- See [Azure Guide](./docs/cloud-providers/AZURE.md) for details

## 🐛 Troubleshooting

### Common Issues

#### Docker build fails

```bash
# Clear Docker cache
docker system prune -a

# Rebuild without cache
docker build --no-cache -t tdfol:latest .
```

#### Kubernetes pods not starting

```bash
# Check pod status
kubectl describe pod <pod-name> -n tdfol

# View logs
kubectl logs <pod-name> -n tdfol

# Check events
kubectl get events -n tdfol --sort-by='.lastTimestamp'
```

#### Helm install fails

```bash
# Validate chart
helm lint ./helm/tdfol

# Dry run
helm install tdfol ./helm/tdfol --dry-run --debug

# Check values
helm get values tdfol -n tdfol
```

### Getting Help

1. **Documentation**: Check the relevant guide in `docs/`
2. **GitHub Issues**: [Report bugs](https://github.com/endomorphosis/ipfs_datasets_py/issues)
3. **Logs**: Always include logs when reporting issues
4. **Community**: Join discussions on GitHub

## 🔄 CI/CD Integration

Automated deployment workflow: `.github/workflows/tdfol-ci.yml`

**Features**:
- Automated testing on push/PR
- Code coverage reporting
- Docker image building
- Security scanning
- Helm chart validation
- Automated deployment to dev/staging/prod

**Badges**:

[![CI/CD](https://github.com/endomorphosis/ipfs_datasets_py/workflows/TDFOL%20CI%2FCD/badge.svg)](https://github.com/endomorphosis/ipfs_datasets_py/actions)
[![Coverage](https://img.shields.io/codecov/c/github/endomorphosis/ipfs_datasets_py)](https://codecov.io/gh/endomorphosis/ipfs_datasets_py)
[![Docker](https://img.shields.io/docker/image-size/ipfs-datasets/tdfol)](https://hub.docker.com/r/ipfs-datasets/tdfol)

## 📈 Monitoring and Observability

### Metrics

- **Prometheus**: Scrapes metrics from `/metrics` endpoint
- **Grafana**: Pre-configured dashboards included
- **CloudWatch/Stackdriver/Azure Monitor**: Cloud-native monitoring

### Logging

- **Application Logs**: `/app/logs/` (persistent)
- **Container Logs**: `docker logs` or `kubectl logs`
- **Centralized Logging**: Supports ELK, Splunk, CloudWatch Logs

### Tracing

- **Distributed Tracing**: OpenTelemetry compatible
- **X-Ray/Cloud Trace**: Cloud provider integration

### Alerts

- **CPU/Memory**: Resource utilization alerts
- **Health Checks**: Liveness/readiness probe failures
- **Error Rate**: Application error monitoring
- **Latency**: Request duration tracking

## 🎯 Production Readiness Checklist

- [ ] Secrets configured in secure store
- [ ] Resource limits set appropriately
- [ ] Health checks configured
- [ ] Monitoring and alerting enabled
- [ ] Backup strategy in place
- [ ] Disaster recovery tested
- [ ] Security scan passed
- [ ] Load testing completed
- [ ] Documentation reviewed
- [ ] Runbooks created
- [ ] On-call rotation established

## 🤝 Contributing

Improvements to deployment infrastructure are welcome!

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

Apache-2.0 - See [LICENSE](../../LICENSE) for details.

## 🙏 Acknowledgments

- IPFS Datasets Python team
- Kubernetes community
- Helm community
- Cloud provider documentation teams

---

**Need Help?** Check the [Quick Start Guide](./QUICKSTART.md) or open an [issue](https://github.com/endomorphosis/ipfs_datasets_py/issues).
