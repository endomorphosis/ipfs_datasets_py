# Configuration Guide

This guide covers how to configure IPFS Datasets Python for your specific needs.

## Quick Configuration

### Basic Configuration

The library uses environment variables and configuration files for customization:

```bash
# Copy example configuration
cp configs.yaml.example configs.yaml

# Edit configuration
nano configs.yaml
```

### Configuration Options

#### IPFS Settings
- `IPFS_HOST`: IPFS daemon host (default: `127.0.0.1`)
- `IPFS_PORT`: IPFS daemon port (default: `5001`)
- `IPFS_GATEWAY`: IPFS gateway URL

#### Storage Settings
- `STORAGE_PATH`: Local storage directory
- `CACHE_SIZE`: Cache size limit
- `TEMP_DIR`: Temporary files directory

#### Vector Store Settings
- `VECTOR_STORE_BACKEND`: Choose from `faiss`, `qdrant`, `elasticsearch`
- `EMBEDDING_MODEL`: Model for embeddings (default: `sentence-transformers/all-mpnet-base-v2`)
- `VECTOR_DIMENSION`: Embedding dimension

#### GraphRAG Settings
- `GRAPHRAG_MAX_DEPTH`: Maximum graph traversal depth
- `GRAPHRAG_SIMILARITY_THRESHOLD`: Minimum similarity for connections
- `CHUNK_SIZE`: Document chunk size
- `CHUNK_OVERLAP`: Overlap between chunks

## Advanced Configuration

### Performance Tuning

See [Performance Optimization Guide](guides/performance_optimization.md) for detailed tuning options.

### Security Configuration

See [Security & Governance Guide](guides/security/security_governance.md) for security settings.

### Deployment Configuration

For production deployment configuration, see:
- [Docker Deployment](guides/deployment/docker_deployment.md)
- [Production Deployment Guide](guides/deployment/graphrag_production_deployment_guide.md)

## Environment Variables

Create a `.env` file in your project root:

```bash
# Copy example
cp .env.example .env

# Edit with your settings
nano .env
```

Common environment variables:
- `OPENAI_API_KEY`: For OpenAI models
- `ANTHROPIC_API_KEY`: For Claude models
- `HUGGINGFACE_TOKEN`: For Hugging Face models

## Configuration Files

### configs.yaml

Main configuration file structure:

```yaml
ipfs:
  host: "127.0.0.1"
  port: 5001
  gateway: "https://ipfs.io"

storage:
  path: "./data"
  cache_size: "10GB"

vector_store:
  backend: "faiss"
  embedding_model: "sentence-transformers/all-mpnet-base-v2"

graphrag:
  max_depth: 3
  similarity_threshold: 0.7
  chunk_size: 1000
  chunk_overlap: 200
```

### sql_configs.yaml

For SQL database configuration (optional):

```yaml
database:
  type: "postgresql"
  host: "localhost"
  port: 5432
  name: "ipfs_datasets"
```

## Testing Configuration

Verify your configuration:

```bash
# Test IPFS connection
python -c "from ipfs_datasets_py import DatasetManager; dm = DatasetManager(); print('IPFS OK')"

# Test vector store
python -c "from ipfs_datasets_py.embeddings import FAISSVectorStore; vs = FAISSVectorStore(); print('Vector Store OK')"
```

## Troubleshooting

### IPFS Connection Issues

If you can't connect to IPFS:
1. Ensure IPFS daemon is running: `ipfs daemon`
2. Check IPFS API is accessible: `curl http://127.0.0.1:5001/api/v0/version`
3. Verify firewall settings

### Storage Issues

If you have storage problems:
1. Check disk space: `df -h`
2. Verify permissions on storage directory
3. Clear cache if needed: `rm -rf ./data/cache/*`

## Next Steps

- [Installation Guide](installation.md) - Install dependencies
- [User Guide](user_guide.md) - Learn how to use the library
- [Developer Guide](developer_guide.md) - Contributing and development
