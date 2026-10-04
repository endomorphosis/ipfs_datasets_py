# TDFOL Helm Chart

This Helm chart deploys the TDFOL (Temporal Dynamic First-Order Logic) service on a Kubernetes cluster.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- PV provisioner support in the underlying infrastructure (if persistence is enabled)
- Optional: Ingress controller (NGINX, Traefik, etc.)
- Optional: cert-manager for TLS certificate management

## Installing the Chart

### Quick Start

```bash
# Add the repository (if published)
helm repo add ipfs-datasets https://charts.ipfs-datasets.example.com
helm repo update

# Install with default values
helm install tdfol ipfs-datasets/tdfol --namespace tdfol --create-namespace

# Or install from local directory
helm install tdfol ./tdfol --namespace tdfol --create-namespace
```

### Custom Installation

```bash
# Install with custom values file
helm install tdfol ./tdfol \
  --namespace tdfol \
  --create-namespace \
  --values values-production.yaml

# Install with inline overrides
helm install tdfol ./tdfol \
  --namespace tdfol \
  --create-namespace \
  --set replicaCount=5 \
  --set resources.limits.memory=8Gi
```

## Uninstalling the Chart

```bash
helm uninstall tdfol --namespace tdfol
```

## Configuration

The following table lists the configurable parameters of the TDFOL chart and their default values.

### Global Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.imageRegistry` | Global Docker image registry | `""` |
| `global.imagePullSecrets` | Global Docker registry secret names | `[]` |
| `global.storageClass` | Global storage class for PVCs | `""` |

### Image Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.registry` | Image registry | `docker.io` |
| `image.repository` | Image repository | `ipfs-datasets/tdfol` |
| `image.tag` | Image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |

### Deployment Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `3` |
| `podAnnotations` | Annotations for pods | `{}` |
| `podSecurityContext` | Security context for pods | See `values.yaml` |

### Service Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `service.type` | Kubernetes service type | `ClusterIP` |
| `service.port` | Service HTTP port | `8080` |
| `service.metricsPort` | Service metrics port | `9090` |

### Ingress Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `true` |
| `ingress.className` | Ingress class name | `nginx` |
| `ingress.hosts` | Ingress hosts | `[{host: "tdfol.example.com"}]` |
| `ingress.tls` | Ingress TLS configuration | `[]` |

### Resource Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `resources.limits.cpu` | CPU limit | `4000m` |
| `resources.limits.memory` | Memory limit | `4Gi` |
| `resources.requests.cpu` | CPU request | `1000m` |
| `resources.requests.memory` | Memory request | `2Gi` |

### Autoscaling Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `autoscaling.enabled` | Enable HPA | `true` |
| `autoscaling.minReplicas` | Minimum replicas | `3` |
| `autoscaling.maxReplicas` | Maximum replicas | `10` |
| `autoscaling.targetCPUUtilizationPercentage` | Target CPU utilization | `70` |
| `autoscaling.targetMemoryUtilizationPercentage` | Target memory utilization | `80` |

### Persistence Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `persistence.enabled` | Enable persistence | `true` |
| `persistence.storageClass` | Storage class | `""` |
| `persistence.data.size` | Data volume size | `10Gi` |
| `persistence.logs.size` | Logs volume size | `5Gi` |
| `persistence.cache.size` | Cache volume size | `5Gi` |

### Application Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `config.logLevel` | Log level | `INFO` |
| `config.workers` | Number of workers | `4` |
| `config.maxProofDepth` | Maximum proof depth | `100` |
| `config.cacheEnabled` | Enable caching | `true` |

### Redis Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `redis.enabled` | Enable Redis | `true` |
| `redis.image.tag` | Redis image tag | `7-alpine` |
| `redis.persistence.enabled` | Enable Redis persistence | `true` |
| `redis.persistence.size` | Redis storage size | `2Gi` |

## Environment-Specific Configurations

### Development

```bash
helm install tdfol ./tdfol \
  --namespace tdfol-dev \
  --create-namespace \
  --set replicaCount=1 \
  --set resources.limits.memory=2Gi \
  --set persistence.data.size=5Gi \
  --set autoscaling.enabled=false
```

### Staging

```bash
helm install tdfol ./tdfol \
  --namespace tdfol-staging \
  --create-namespace \
  --set replicaCount=2 \
  --set resources.limits.memory=3Gi
```

### Production

```bash
helm install tdfol ./tdfol \
  --namespace tdfol-prod \
  --create-namespace \
  --values values-production.yaml \
  --set secrets.secretKey="$(openssl rand -hex 32)" \
  --set secrets.jwtSecret="$(openssl rand -hex 32)"
```

## Upgrading

```bash
# Upgrade with new values
helm upgrade tdfol ./tdfol \
  --namespace tdfol \
  --values values-production.yaml

# Rollback if needed
helm rollback tdfol --namespace tdfol
```

## Monitoring

The chart includes Prometheus metrics support. To scrape metrics:

```bash
# Port-forward to access metrics
kubectl port-forward -n tdfol svc/tdfol 9090:9090

# View metrics
curl http://localhost:9090/metrics
```

## Troubleshooting

### Check pod status
```bash
kubectl get pods -n tdfol
kubectl describe pod <pod-name> -n tdfol
```

### View logs
```bash
kubectl logs -n tdfol -l app.kubernetes.io/name=tdfol -f
```

### Check HPA status
```bash
kubectl get hpa -n tdfol
kubectl describe hpa tdfol -n tdfol
```

### Validate configuration
```bash
helm lint ./tdfol
helm template ./tdfol --debug
```

## Contributing

For bug reports and feature requests, please visit:
https://github.com/endomorphosis/ipfs_datasets_py/issues

## License

Apache-2.0
