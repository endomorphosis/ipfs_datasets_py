# Docker Deployment Guide

This guide explains how to use Docker to containerize IPFS Datasets Python applications. Using Docker provides several benefits, including easy deployment, consistent environments, and isolation from the host system.

## Table of Contents

1. [Basic Docker Setup](#basic-docker-setup)
2. [Multi-Container Setup with Docker Compose](#multi-container-setup-with-docker-compose)
3. [IPFS Node Integration](#ipfs-node-integration)
4. [Production Deployment Considerations](#production-deployment-considerations)
5. [Example Configurations](#example-configurations)

## Basic Docker Setup

### Dockerfile

Create a `Dockerfile` in the root of your project:

```dockerfile
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Install the package
RUN pip install -e .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Run the application
CMD ["python", "your_script.py"]
```

### Building and Running

Build the Docker image:

```bash
docker build -t ipfs-datasets-py .
```

Run the container:

```bash
docker run -it ipfs-datasets-py
```

## Multi-Container Setup with Docker Compose

For more complex setups with multiple services, use Docker Compose.

### docker-compose.yml

```yaml
version: '3.8'

services:
  # IPFS node
  ipfs:
    image: ipfs/kubo:latest
    container_name: ipfs-node
    restart: unless-stopped
    ports:
      - "4001:4001"
      - "8080:8080"
      - "5001:5001"
    volumes:
      - ipfs_data:/data/ipfs
      - ipfs_export:/export
    
  # Elasticsearch for audit logging
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.9.0
    container_name: elasticsearch
    restart: unless-stopped
    environment:
      - discovery.type=single-node
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    ports:
      - "9200:9200"
    volumes:
      - elasticsearch_data:/usr/share/elasticsearch/data
  
  # Application container
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ipfs-datasets-app
    restart: unless-stopped
    depends_on:
      - ipfs
      - elasticsearch
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    environment:
      - IPFS_API_URL=http://ipfs:5001
      - ELASTICSEARCH_URL=http://elasticsearch:9200
    command: python app.py

volumes:
  ipfs_data:
  ipfs_export:
  elasticsearch_data:
```

### Running with Docker Compose

```bash
docker-compose up -d
```

Stop the containers:

```bash
docker-compose down
```

## IPFS Node Integration

### Connecting to an IPFS Node

Configure your application to connect to the IPFS node:

```python
from ipfs_datasets_py.config import Config

# Load configuration
config = Config.load_from_env()

# Connect to IPFS node
ipfs_api_url = config.get("IPFS_API_URL", "http://ipfs:5001")
```

### Custom IPFS Configuration

Create a custom IPFS configuration for your node:

1. Create a file `ipfs_config.json`:

```json
{
  "Addresses": {
    "API": "/ip4/0.0.0.0/tcp/5001",
    "Gateway": "/ip4/0.0.0.0/tcp/8080",
    "Swarm": [
      "/ip4/0.0.0.0/tcp/4001",
      "/ip6/::/tcp/4001",
      "/ip4/0.0.0.0/udp/4001/quic",
      "/ip6/::/udp/4001/quic"
    ]
  },
  "Bootstrap": [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt"
  ],
  "Experimental": {
    "FilestoreEnabled": true,
    "UrlstoreEnabled": true,
    "Libp2pStreamMounting": true,
    "ShardingEnabled": true
  }
}
```

2. Update your `docker-compose.yml`:

```yaml
services:
  ipfs:
    image: ipfs/kubo:latest
    volumes:
      - ./ipfs_config.json:/data/ipfs/config
      - ipfs_data:/data/ipfs
      - ipfs_export:/export
```

## Production Deployment Considerations

### Environment Variables

Use environment variables for configuration in production:

```yaml
services:
  app:
    environment:
      - IPFS_API_URL=http://ipfs:5001
      - ELASTICSEARCH_URL=http://elasticsearch:9200
      - LOG_LEVEL=INFO
      - STORAGE_PATH=/app/data
      - VECTOR_INDEX_DIMENSION=768
      - VECTOR_INDEX_METRIC=cosine
```

### Resource Limits

Set resource limits to prevent container resource exhaustion:

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

### Healthchecks

Add healthchecks to ensure containers are running properly:

```yaml
services:
  app:
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

### Data Persistence

Ensure data persistence with named volumes:

```yaml
services:
  app:
    volumes:
      - app_data:/app/data
      - app_logs:/app/logs

volumes:
  app_data:
  app_logs:
```

## Example Configurations

### Basic Vector Search Application

```yaml
version: '3.8'

services:
  ipfs:
    image: ipfs/kubo:latest
    ports:
      - "5001:5001"
    volumes:
      - ipfs_data:/data/ipfs
  
  vector-search:
    build: .
    depends_on:
      - ipfs
    environment:
      - IPFS_API_URL=http://ipfs:5001
      - VECTOR_INDEX_PATH=/app/data/vector_index
      - VECTOR_INDEX_DIMENSION=768
    volumes:
      - app_data:/app/data
    command: python -m vector_search_server

volumes:
  ipfs_data:
  app_data:
```

### Knowledge Graph Application

```yaml
version: '3.8'

services:
  ipfs:
    image: ipfs/kubo:latest
    ports:
      - "5001:5001"
    volumes:
      - ipfs_data:/data/ipfs
  
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.9.0
    environment:
      - discovery.type=single-node
      - "ES_JAVA_OPTS=-Xms1g -Xmx1g"
    ports:
      - "9200:9200"
    volumes:
      - es_data:/usr/share/elasticsearch/data
  
  knowledge-graph:
    build: .
    depends_on:
      - ipfs
      - elasticsearch
    environment:
      - IPFS_API_URL=http://ipfs:5001
      - ELASTICSEARCH_URL=http://elasticsearch:9200
      - GRAPH_STORAGE_PATH=/app/data/kg
    volumes:
      - app_data:/app/data
    command: python -m knowledge_graph_server
  
  api:
    build: 
      context: .
      dockerfile: Dockerfile.api
    depends_on:
      - knowledge-graph
    ports:
      - "8000:8000"
    environment:
      - KG_SERVICE_URL=http://knowledge-graph:8080
    command: uvicorn api:app --host 0.0.0.0 --port 8000

volumes:
  ipfs_data:
  es_data:
  app_data:
```

### Complete GraphRAG System

```yaml
version: '3.8'

services:
  ipfs:
    image: ipfs/kubo:latest
    ports:
      - "5001:5001"
    volumes:
      - ipfs_data:/data/ipfs
  
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.9.0
    environment:
      - discovery.type=single-node
      - "ES_JAVA_OPTS=-Xms1g -Xmx1g"
    volumes:
      - es_data:/usr/share/elasticsearch/data
  
  vector-service:
    build:
      context: .
      dockerfile: Dockerfile.vector
    depends_on:
      - ipfs
    environment:
      - IPFS_API_URL=http://ipfs:5001
      - VECTOR_INDEX_PATH=/app/data/vector_index
    volumes:
      - vector_data:/app/data
    command: python -m vector_service
  
  kg-service:
    build:
      context: .
      dockerfile: Dockerfile.kg
    depends_on:
      - ipfs
    environment:
      - IPFS_API_URL=http://ipfs:5001
      - KG_STORAGE_PATH=/app/data/kg
    volumes:
      - kg_data:/app/data
    command: python -m kg_service
  
  graphrag-service:
    build:
      context: .
      dockerfile: Dockerfile.graphrag
    depends_on:
      - vector-service
      - kg-service
    environment:
      - VECTOR_SERVICE_URL=http://vector-service:8080
      - KG_SERVICE_URL=http://kg-service:8081
    command: python -m graphrag_service
  
  audit-service:
    build:
      context: .
      dockerfile: Dockerfile.audit
    depends_on:
      - elasticsearch
    environment:
      - ELASTICSEARCH_URL=http://elasticsearch:9200
    volumes:
      - audit_data:/app/data
    command: python -m audit_service
  
  api-gateway:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    depends_on:
      - graphrag-service
      - audit-service
    environment:
      - GRAPHRAG_SERVICE_URL=http://graphrag-service:8082
      - AUDIT_SERVICE_URL=http://audit-service:8083
    command: uvicorn api_gateway:app --host 0.0.0.0 --port 8000

volumes:
  ipfs_data:
  es_data:
  vector_data:
  kg_data:
  audit_data:
```

### Scaling with Docker Swarm

For production environments, you can use Docker Swarm for orchestration:

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml ipfs-datasets
```

For Swarm deployment, update your `docker-compose.yml`:

```yaml
version: '3.8'

services:
  ipfs:
    image: ipfs/kubo:latest
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.role == manager
  
  vector-service:
    build:
      context: .
      dockerfile: Dockerfile.vector
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
  
  api-gateway:
    ports:
      - "8000:8000"
    deploy:
      replicas: 2
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
```

This Docker deployment guide provides flexible, scalable deployment options for IPFS Datasets Python applications, from simple single-container deployments to complex multi-service architectures.