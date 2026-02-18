# TDFOL Quick Start Guide

Get TDFOL up and running in 5 minutes!

## Prerequisites

- Docker and Docker Compose installed
- 4GB RAM available
- 10GB disk space

## Option 1: Docker Compose (Recommended for Development)

```bash
# 1. Clone the repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py/deployment/tdfol

# 2. Create environment file
cp .env.example .env

# 3. Start all services
docker-compose up -d

# 4. Check status
docker-compose ps

# 5. View logs
docker-compose logs -f tdfol

# 6. Test the service
curl http://localhost:8080/health
```

**That's it!** TDFOL is now running at `http://localhost:8080`

### Included Services

- **TDFOL**: Main service (port 8080)
- **Redis**: Caching layer (port 6379)
- **Prometheus**: Metrics collection (port 9091)
- **Grafana**: Dashboards (port 3000, admin/admin)

### Common Commands

```bash
# Stop services
docker-compose stop

# Start services
docker-compose start

# Restart services
docker-compose restart

# View logs
docker-compose logs -f

# Remove everything
docker-compose down -v
```

## Option 2: Single Docker Container

```bash
# 1. Build the image
docker build -t tdfol:latest \
  -f deployment/tdfol/Dockerfile .

# 2. Run the container
docker run -d \
  --name tdfol \
  -p 8080:8080 \
  -v tdfol-data:/app/data \
  -e TDFOL_LOG_LEVEL=INFO \
  tdfol:latest

# 3. Check logs
docker logs -f tdfol

# 4. Test
curl http://localhost:8080/health
```

## Option 3: Kubernetes with Helm (Production)

### Prerequisites

- Kubernetes cluster (minikube, kind, or cloud provider)
- kubectl configured
- Helm 3.x installed

```bash
# 1. Create namespace
kubectl create namespace tdfol

# 2. Install with Helm
helm install tdfol deployment/tdfol/helm/tdfol \
  --namespace tdfol \
  --set replicaCount=3

# 3. Check status
kubectl get pods -n tdfol
kubectl get svc -n tdfol

# 4. Port forward to access locally
kubectl port-forward -n tdfol svc/tdfol 8080:8080

# 5. Test
curl http://localhost:8080/health
```

## Testing TDFOL

### Health Check

```bash
curl http://localhost:8080/health
```

Expected response:
```json
{"status": "healthy", "version": "1.0.0"}
```

### Basic Proof Request

```bash
curl -X POST http://localhost:8080/api/v1/prove \
  -H "Content-Type: application/json" \
  -d '{
    "formula": "P -> (Q -> P)",
    "timeout": 60
  }'
```

### Check Metrics

```bash
curl http://localhost:8080/metrics
```

## Configuration

### Key Environment Variables

Edit `.env` file:

```bash
# Logging
TDFOL_LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR

# Workers
TDFOL_WORKERS=4                   # Number of worker processes

# Proof settings
TDFOL_MAX_PROOF_DEPTH=100         # Maximum proof search depth
TDFOL_CACHE_ENABLED=true          # Enable proof caching

# Database
DATABASE_URL=sqlite:///app/data/tdfol.db

# Redis
REDIS_URL=redis://redis:6379/0
```

## Troubleshooting

### Issue: Container won't start

```bash
# Check logs
docker logs tdfol

# Check Docker resources
docker info

# Ensure ports are available
netstat -an | grep 8080
```

### Issue: Out of memory

```bash
# Increase Docker memory limit
# Docker Desktop -> Settings -> Resources -> Memory

# Or reduce workers
docker run -e TDFOL_WORKERS=2 ...
```

### Issue: Cannot connect to service

```bash
# Check if container is running
docker ps | grep tdfol

# Check container health
docker inspect tdfol | grep Health

# Check network
docker port tdfol
```

## Next Steps

### Development

- **Edit code**: Mount local directory for live development
  ```bash
  docker-compose -f docker-compose.yml -f docker-compose.override.yml up
  ```

- **Run tests**: Execute test suite
  ```bash
  docker-compose run --rm tdfol pytest tests/
  ```

- **Access shell**: Debug inside container
  ```bash
  docker exec -it tdfol bash
  ```

### Production

- **Scale up**: Increase replicas
  ```bash
  helm upgrade tdfol deployment/tdfol/helm/tdfol --set replicaCount=10
  ```

- **Enable monitoring**: Access Grafana dashboards
  ```bash
  kubectl port-forward -n tdfol svc/grafana 3000:3000
  # Visit http://localhost:3000 (admin/admin)
  ```

- **Configure ingress**: Expose via domain
  ```bash
  helm upgrade tdfol deployment/tdfol/helm/tdfol \
    --set ingress.enabled=true \
    --set ingress.hosts[0].host=tdfol.example.com
  ```

### Cloud Deployment

Choose your cloud provider:

- **[AWS Guide](./docs/cloud-providers/AWS.md)**: Deploy to ECS or EKS
- **[GCP Guide](./docs/cloud-providers/GCP.md)**: Deploy to Cloud Run or GKE  
- **[Azure Guide](./docs/cloud-providers/AZURE.md)**: Deploy to ACI or AKS

## Monitoring

### Prometheus Metrics

```bash
# Port forward Prometheus (if using Docker Compose)
curl http://localhost:9091/targets

# Port forward Prometheus (if using Kubernetes)
kubectl port-forward -n tdfol svc/prometheus 9091:9090
curl http://localhost:9091/targets
```

### Grafana Dashboards

```bash
# Docker Compose
# Visit http://localhost:3000 (admin/admin)

# Kubernetes
kubectl port-forward -n tdfol svc/grafana 3000:3000
# Visit http://localhost:3000
```

### Application Logs

```bash
# Docker
docker logs -f tdfol

# Docker Compose
docker-compose logs -f tdfol

# Kubernetes
kubectl logs -f -n tdfol deployment/tdfol
```

## Cleanup

### Docker Compose

```bash
# Stop and remove containers, networks
docker-compose down

# Also remove volumes (data will be lost!)
docker-compose down -v
```

### Docker

```bash
# Stop and remove container
docker stop tdfol
docker rm tdfol

# Remove volume
docker volume rm tdfol-data

# Remove image
docker rmi tdfol:latest
```

### Kubernetes

```bash
# Uninstall Helm release
helm uninstall tdfol -n tdfol

# Delete namespace (and all resources)
kubectl delete namespace tdfol
```

## Getting Help

- **Documentation**: [Full README](./README.md)
- **Issues**: [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Logs**: Always include logs when reporting issues

## Cheat Sheet

```bash
# Quick commands reference

# Docker Compose
docker-compose up -d              # Start all services
docker-compose down               # Stop all services
docker-compose logs -f            # Follow logs
docker-compose ps                 # List services
docker-compose restart tdfol      # Restart TDFOL

# Docker
docker run -d -p 8080:8080 tdfol:latest    # Run container
docker logs -f tdfol                        # View logs
docker exec -it tdfol bash                  # Shell access
docker stop tdfol                           # Stop container
docker start tdfol                          # Start container

# Kubernetes
kubectl get pods -n tdfol                   # List pods
kubectl logs -f -n tdfol deployment/tdfol   # View logs
kubectl describe pod <pod> -n tdfol         # Pod details
kubectl port-forward -n tdfol svc/tdfol 8080:8080  # Port forward

# Helm
helm list -n tdfol                          # List releases
helm upgrade tdfol helm/tdfol               # Upgrade release
helm rollback tdfol -n tdfol                # Rollback release
helm uninstall tdfol -n tdfol               # Uninstall release

# Testing
curl http://localhost:8080/health           # Health check
curl http://localhost:8080/metrics          # Prometheus metrics
curl -X POST http://localhost:8080/api/v1/prove -d '{"formula":"P->P"}'  # Test proof
```

---

**Ready to deploy?** See the [Full Deployment Guide](./README.md) for production setup.
