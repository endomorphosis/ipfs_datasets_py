# GCP Deployment Guide for TDFOL

Deploy TDFOL on Google Cloud Platform using Cloud Run or Google Kubernetes Engine (GKE).

## Prerequisites

```bash
# Install gcloud CLI
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# Initialize gcloud
gcloud init

# Set project
gcloud config set project YOUR_PROJECT_ID

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  container.googleapis.com \
  containerregistry.googleapis.com \
  cloudsql.googleapis.com \
  redis.googleapis.com \
  cloudmonitoring.googleapis.com
```

## Option 1: Cloud Run (Serverless)

### Deploy

```bash
# Build and push to Google Container Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT/tdfol:latest deployment/tdfol/

# Deploy to Cloud Run
gcloud run deploy tdfol \
  --image gcr.io/YOUR_PROJECT/tdfol:latest \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 4Gi \
  --cpu 2 \
  --min-instances 1 \
  --max-instances 10 \
  --set-env-vars TDFOL_LOG_LEVEL=INFO
```

### Cost: ~$50-150/month (depending on traffic)

## Option 2: GKE (Kubernetes)

### Create Cluster

```bash
gcloud container clusters create tdfol-cluster \
  --region us-central1 \
  --num-nodes 3 \
  --machine-type n1-standard-4 \
  --enable-autoscaling \
  --min-nodes 3 \
  --max-nodes 10 \
  --enable-stackdriver-kubernetes

# Get credentials
gcloud container clusters get-credentials tdfol-cluster --region us-central1
```

### Deploy with Helm

```bash
helm install tdfol deployment/tdfol/helm/tdfol \
  --namespace tdfol \
  --create-namespace \
  --set image.registry=gcr.io/YOUR_PROJECT \
  --set image.repository=tdfol \
  --set image.tag=latest
```

### Cost: ~$300-500/month

## Cloud SQL (PostgreSQL)

```bash
gcloud sql instances create tdfol-db \
  --database-version=POSTGRES_15 \
  --tier=db-custom-2-8192 \
  --region=us-central1 \
  --backup-start-time=03:00 \
  --enable-bin-log \
  --availability-type=regional

# Create database
gcloud sql databases create tdfol --instance=tdfol-db

# Get connection string
gcloud sql instances describe tdfol-db --format="value(connectionName)"
```

## Memorystore (Redis)

```bash
gcloud redis instances create tdfol-redis \
  --size=2 \
  --region=us-central1 \
  --redis-version=redis_7_0 \
  --tier=basic

# Get endpoint
gcloud redis instances describe tdfol-redis --region=us-central1 --format="value(host)"
```

## Monitoring with Cloud Monitoring

- Automatic metrics collection
- Pre-built dashboards
- Alert policies
- Log aggregation

## Troubleshooting

```bash
# View logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=tdfol"

# Check service status
gcloud run services describe tdfol --region us-central1
```

See full [GCP documentation](https://cloud.google.com/run/docs) for more details.
