# IPFS Datasets MCP Server - Kubernetes Deployment

This directory contains comprehensive Kubernetes deployment manifests for the IPFS Datasets MCP (Model Context Protocol) server and dashboard with horizontal scaling capabilities.

## 🚀 Features

- **Horizontally Scalable**: Automatic scaling based on CPU and memory usage
- **High Availability**: Pod disruption budgets and multiple replicas
- **Production Ready**: Security contexts, resource limits, health checks
- **Monitoring & Observability**: Prometheus and Grafana integration
- **Network Security**: Network policies for secure communication
- **Load Balancing**: Ingress with session affinity and load balancing

## 📁 Files Structure

```
kubernetes/
├── mcp-deployment.yaml      # Main deployment with HPA and PDB
├── mcp-ingress.yaml        # Ingress and load balancer configuration
├── monitoring.yaml         # Prometheus and Grafana monitoring stack
├── deploy.sh              # Automated deployment script
├── test.sh               # Comprehensive testing script
└── README.md             # This file
```

## 🔧 Prerequisites

### Required Tools
- `kubectl` - Kubernetes command-line tool
- `docker` - For building container images
- Kubernetes cluster (v1.20+)
- Metrics server (for HPA)

### Optional Components
- Ingress controller (nginx recommended)
- cert-manager (for TLS certificates)
- Persistent storage provider

### Quick Setup
```bash
# Install kubectl (if not already installed)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

# Install metrics-server (for HPA)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Install ingress-nginx (optional)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml
```

## 🚀 Quick Start

### Option 1: Automated Deployment (Recommended)

```bash
# Make scripts executable
chmod +x deploy.sh test.sh

# Full deployment (build + deploy + test)
./deploy.sh deploy

# Check status
./deploy.sh status

# Run tests
./test.sh
```

### Option 2: Manual Deployment

```bash
# 1. Build Docker image
docker build -f ../../ipfs_datasets_py/mcp_server/Dockerfile.standalone -t ipfs-datasets-mcp-standalone:latest ../../

# 2. Create namespace
kubectl create namespace ipfs-datasets-mcp

# 3. Deploy main components
kubectl apply -f mcp-deployment.yaml

# 4. Deploy ingress (optional)
kubectl apply -f mcp-ingress.yaml

# 5. Deploy monitoring (optional)
kubectl apply -f monitoring.yaml
```

## 📊 Architecture

### Components

1. **MCP Server**: Core API server handling MCP protocol requests
   - Default: 3 replicas (scales 2-10 based on load)
   - Resource limits: 1Gi memory, 500m CPU
   - Health checks on `/health` endpoint

2. **MCP Dashboard**: Web interface for monitoring and testing
   - Default: 2 replicas (scales 1-5 based on load)
   - Resource limits: 512Mi memory, 250m CPU
   - Communicates with MCP server via internal service

3. **Load Balancer**: External access via ingress or LoadBalancer service
   - Session affinity for consistent user experience
   - Rate limiting and security headers

4. **Monitoring Stack** (Optional):
   - Prometheus for metrics collection
   - Grafana for visualization
   - Custom alerts for MCP-specific metrics

### Scaling Behavior

- **MCP Server HPA**:
  - Min replicas: 2, Max replicas: 10
  - Scale up: When CPU > 70% or Memory > 80%
  - Scale down: Gradual (10% per minute)

- **MCP Dashboard HPA**:
  - Min replicas: 1, Max replicas: 5
  - Scale up: When CPU > 75% or Memory > 85%
  - Scale down: Conservative (50% per minute)

## 🔒 Security Features

### Pod Security
- Non-root user execution (UID 1000)
- Read-only root filesystem where possible
- Security contexts for all containers
- Resource limits to prevent resource exhaustion

### Network Security
- Network policies restricting inter-pod communication
- Ingress rules limiting external access
- Service mesh ready (Istio compatible)

### Secrets Management
- Kubernetes secrets for sensitive data
- ConfigMaps for configuration
- Environment variable injection

## 🌐 Access Methods

### Local Development
```bash
# Port forward MCP server
kubectl port-forward service/mcp-server-service 8000:8000 -n ipfs-datasets-mcp

# Port forward dashboard
kubectl port-forward service/mcp-dashboard-service 8080:8080 -n ipfs-datasets-mcp

# Access via browser
# - MCP Server: http://localhost:8000
# - Dashboard: http://localhost:8080
```

### Production Access

#### Via Ingress (Recommended)
```bash
# Update mcp-ingress.yaml with your domain
# Replace 'yourdomain.com' with your actual domain

# Access via:
# - https://mcp.yourdomain.com (Dashboard)
# - https://mcp-api.yourdomain.com (API)
```

#### Via LoadBalancer
```bash
# Get external IP
kubectl get service mcp-load-balancer -n ipfs-datasets-mcp

# Access via external IP
```

## 📈 Monitoring & Observability

### Metrics Available
- Request rate and response times
- Error rates and status codes
- Resource usage (CPU, memory)
- Pod health and availability
- Kubernetes-native metrics

### Grafana Dashboards
- MCP Server performance overview
- Resource utilization trends
- Error rate monitoring
- Scaling events tracking

### Prometheus Alerts
- Server down alerts
- High resource usage warnings
- Error rate thresholds
- Pod restart notifications

### Access Monitoring
```bash
# Port forward Grafana
kubectl port-forward service/grafana-service 3000:3000 -n ipfs-datasets-mcp

# Login: admin / (password from secret)
# Default dashboards available at startup
```

## 🔧 Configuration

### Environment Variables
Configure via ConfigMap or directly in deployment:

```yaml
env:
- name: MCP_HOST
  value: "0.0.0.0"
- name: MCP_PORT
  value: "8000"
- name: LOG_LEVEL
  value: "INFO"
- name: JWT_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: mcp-secrets
      key: jwt-secret
```

### Resource Limits
Adjust based on your workload:

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"
```

### Scaling Parameters
Modify HPA settings:

```yaml
spec:
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

## 🧪 Testing

### Automated Testing
```bash
# Run comprehensive test suite
./test.sh

# Tests include:
# - Pod health and availability
# - Service connectivity
# - API functionality
# - Scaling behavior
# - Security configurations
# - Performance benchmarks
```

### Manual Testing
```bash
# Health check
curl http://localhost:8000/health

# List available tools
curl http://localhost:8000/tools

# Execute a tool
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name": "echo", "parameters": {"text": "Hello Kubernetes!"}}'
```

### Load Testing
```bash
# Simple load test with curl
for i in {1..100}; do
  curl -s http://localhost:8000/health > /dev/null &
done
wait

# Monitor scaling behavior
watch kubectl get hpa -n ipfs-datasets-mcp
```

## 🔄 Scaling Operations

### Manual Scaling
```bash
# Scale MCP server
./deploy.sh scale server 5

# Scale dashboard
./deploy.sh scale dashboard 3

# Check scaling status
kubectl get deployments -n ipfs-datasets-mcp
```

### Auto-scaling Monitoring
```bash
# Watch HPA status
kubectl get hpa -n ipfs-datasets-mcp -w

# View scaling events
kubectl describe hpa mcp-server-hpa -n ipfs-datasets-mcp
```

## 🚨 Troubleshooting

### Common Issues

#### Pods not starting
```bash
# Check pod status
kubectl get pods -n ipfs-datasets-mcp

# View pod logs
kubectl logs -f deployment/mcp-server -n ipfs-datasets-mcp

# Describe pod issues
kubectl describe pod <pod-name> -n ipfs-datasets-mcp
```

#### Scaling not working
```bash
# Check metrics server
kubectl get apiservice v1beta1.metrics.k8s.io

# View HPA status
kubectl describe hpa mcp-server-hpa -n ipfs-datasets-mcp

# Check resource metrics
kubectl top pods -n ipfs-datasets-mcp
```

#### Ingress issues
```bash
# Check ingress controller
kubectl get pods -n ingress-nginx

# View ingress status
kubectl get ingress -n ipfs-datasets-mcp

# Check ingress logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

### Debug Commands
```bash
# Get all resources
kubectl get all -n ipfs-datasets-mcp

# Check events
kubectl get events -n ipfs-datasets-mcp --sort-by='.lastTimestamp'

# Shell into pod
kubectl exec -it deployment/mcp-server -n ipfs-datasets-mcp -- /bin/bash

# Port forward for debugging
kubectl port-forward pod/<pod-name> 8000:8000 -n ipfs-datasets-mcp
```

## 🔄 Updates and Maintenance

### Rolling Updates
```bash
# Update image
kubectl set image deployment/mcp-server mcp-server=ipfs-datasets-mcp-standalone:v2.0.0 -n ipfs-datasets-mcp

# Monitor rollout
kubectl rollout status deployment/mcp-server -n ipfs-datasets-mcp

# Rollback if needed
kubectl rollout undo deployment/mcp-server -n ipfs-datasets-mcp
```

### Backup and Recovery
```bash
# Backup configuration
kubectl get all,configmap,secret -n ipfs-datasets-mcp -o yaml > mcp-backup.yaml

# Restore from backup
kubectl apply -f mcp-backup.yaml
```

## 🧹 Cleanup

### Partial Cleanup
```bash
# Remove ingress only
kubectl delete -f mcp-ingress.yaml

# Remove monitoring only
kubectl delete -f monitoring.yaml
```

### Complete Cleanup
```bash
# Use automated cleanup
./deploy.sh cleanup

# Or manual cleanup
kubectl delete namespace ipfs-datasets-mcp
```

## 📚 Additional Resources

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Horizontal Pod Autoscaler](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Ingress Documentation](https://kubernetes.io/docs/concepts/services-networking/ingress/)
- [Prometheus Operator](https://prometheus-operator.dev/)
- [Grafana Documentation](https://grafana.com/docs/)

## 🤝 Contributing

1. Test your changes with the test suite
2. Update documentation if needed
3. Follow Kubernetes best practices
4. Ensure security configurations are maintained

## 📄 License

This deployment configuration follows the same license as the main IPFS Datasets Python project.