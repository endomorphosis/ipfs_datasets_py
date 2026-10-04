# Azure Deployment Guide for TDFOL

Deploy TDFOL on Microsoft Azure using Container Instances or Azure Kubernetes Service (AKS).

## Prerequisites

```bash
# Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Login
az login

# Set subscription
az account set --subscription YOUR_SUBSCRIPTION_ID

# Create resource group
az group create --name tdfol-rg --location eastus
```

## Option 1: Azure Container Instances (Simple)

### Deploy

```bash
# Create Azure Container Registry
az acr create --resource-group tdfol-rg \
  --name tdfol registry \
  --sku Basic

# Login to ACR
az acr login --name tdfolregistry

# Build and push
az acr build --registry tdfolregistry \
  --image tdfol:latest \
  --file deployment/tdfol/Dockerfile .

# Deploy to ACI
az container create \
  --resource-group tdfol-rg \
  --name tdfol \
  --image tdfolregistry.azurecr.io/tdfol:latest \
  --cpu 2 \
  --memory 4 \
  --ports 8080 \
  --dns-name-label tdfol \
  --environment-variables TDFOL_LOG_LEVEL=INFO
```

### Cost: ~$60-180/month

## Option 2: Azure Kubernetes Service (AKS)

### Create Cluster

```bash
# Create AKS cluster
az aks create \
  --resource-group tdfol-rg \
  --name tdfol-cluster \
  --node-count 3 \
  --node-vm-size Standard_D4s_v3 \
  --enable-addons monitoring \
  --enable-cluster-autoscaler \
  --min-count 3 \
  --max-count 10 \
  --generate-ssh-keys

# Get credentials
az aks get-credentials --resource-group tdfol-rg --name tdfol-cluster
```

### Deploy with Helm

```bash
# Attach ACR to AKS
az aks update --name tdfol-cluster \
  --resource-group tdfol-rg \
  --attach-acr tdfolregistry

# Deploy
helm install tdfol deployment/tdfol/helm/tdfol \
  --namespace tdfol \
  --create-namespace \
  --set image.registry=tdfolregistry.azurecr.io \
  --set image.repository=tdfol \
  --set image.tag=latest
```

### Cost: ~$350-550/month

## Azure Database for PostgreSQL

```bash
az postgres flexible-server create \
  --resource-group tdfol-rg \
  --name tdfol-db \
  --location eastus \
  --admin-user tdfol admin \
  --admin-password <password> \
  --sku-name Standard_D2s_v3 \
  --tier GeneralPurpose \
  --storage-size 128 \
  --version 15 \
  --high-availability Enabled
```

## Azure Cache for Redis

```bash
az redis create \
  --resource-group tdfol-rg \
  --name tdfol-redis \
  --location eastus \
  --sku Basic \
  --vm-size c1 \
  --enable-non-ssl-port
```

## Monitoring with Azure Monitor

- Application Insights integration
- Log Analytics workspace
- Alert rules
- Metrics dashboard

## Troubleshooting

```bash
# View logs
az container logs --resource-group tdfol-rg --name tdfol

# AKS logs
kubectl logs -n tdfol deployment/tdfol
```

See full [Azure documentation](https://docs.microsoft.com/azure/container-instances/) for details.
