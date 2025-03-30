# IPFS Datasets Python - Installation Guide

This guide provides detailed instructions for installing and configuring IPFS Datasets Python in various environments.

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Basic Installation](#basic-installation)
3. [Development Installation](#development-installation)
4. [Installing with Optional Dependencies](#installing-with-optional-dependencies)
5. [Docker Installation](#docker-installation)
6. [IPFS Setup](#ipfs-setup)
7. [Configuration](#configuration)
8. [Troubleshooting](#troubleshooting)

## System Requirements

### Minimum Requirements

- Python 3.7 or higher
- pip (Python package manager)
- 4GB RAM
- 2GB free disk space

### Recommended Requirements

- Python 3.9 or higher
- 8GB RAM
- 20GB free disk space
- IPFS daemon (version 0.12.0 or higher)
- CUDA-compatible GPU for faster vector operations (optional)

### Operating System Support

- Linux (Ubuntu 18.04+, Debian 10+, CentOS 7+)
- macOS (10.15 Catalina or newer)
- Windows 10 (with Windows Subsystem for Linux recommended)

## Basic Installation

The simplest way to install IPFS Datasets Python is via pip:

```bash
pip install ipfs-datasets-py
```

To verify the installation:

```bash
python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__version__)"
```

## Development Installation

For development or to use the latest features:

```bash
# Clone the repository
git clone https://github.com/your-organization/ipfs_datasets_py.git
cd ipfs_datasets_py

# Install in development mode
pip install -e .

# Install development dependencies
pip install -r requirements-dev.txt
```

## Installing with Optional Dependencies

IPFS Datasets Python offers several optional dependency groups for specific functionality:

### Vector Search Dependencies

```bash
pip install ipfs-datasets-py[vector]
```

This includes:
- faiss-cpu (or faiss-gpu for CUDA support)
- sentence-transformers
- numpy
- scipy

### Knowledge Graph and RAG Dependencies

```bash
pip install ipfs-datasets-py[graphrag]
```

This includes:
- spacy
- networkx
- huggingface-hub
- transformers
- torch

### Web Archive Integration Dependencies

```bash
pip install ipfs-datasets-py[webarchive]
```

This includes:
- archivenow
- warcio
- requests
- beautifulsoup4

### Full Installation (All Dependencies)

```bash
pip install ipfs-datasets-py[all]
```

### GPU Support

For GPU-accelerated vector operations:

```bash
# For CUDA 11.x
pip install torch==1.10.0+cu113 -f https://download.pytorch.org/whl/cu113/torch_stable.html
pip install faiss-gpu

# For CUDA 10.x
pip install torch==1.10.0+cu102 -f https://download.pytorch.org/whl/cu102/torch_stable.html
pip install faiss-gpu
```

## Docker Installation

For a containerized setup, you can use the provided Docker image:

```bash
# Pull the Docker image
docker pull yourorga/ipfs-datasets-py:latest

# Run a container
docker run -it --name ipfs-datasets-py \
  -v $(pwd)/data:/data \
  -p 8080:8080 \
  yourorga/ipfs-datasets-py:latest
```

### Building from Dockerfile

To build your own Docker image:

```bash
git clone https://github.com/your-organization/ipfs_datasets_py.git
cd ipfs_datasets_py

docker build -t ipfs-datasets-py:custom .
docker run -it --name ipfs-datasets-py-custom \
  -v $(pwd)/data:/data \
  -p 8080:8080 \
  ipfs-datasets-py:custom
```

## IPFS Setup

While IPFS Datasets Python can work without a local IPFS daemon, having one enables full functionality.

### Installing IPFS

#### Linux and macOS

```bash
# Download the latest release
wget https://dist.ipfs.io/go-ipfs/v0.12.0/go-ipfs_v0.12.0_linux-amd64.tar.gz
tar -xvzf go-ipfs_v0.12.0_linux-amd64.tar.gz

# Install
cd go-ipfs
sudo bash install.sh

# Initialize IPFS repository
ipfs init
```

#### Windows

1. Download the Windows binary from [IPFS Downloads](https://dist.ipfs.io/go-ipfs/v0.12.0/go-ipfs_v0.12.0_windows-amd64.zip)
2. Extract the archive
3. Add the extracted directory to your PATH
4. Open Command Prompt or PowerShell and run:
   ```
   ipfs init
   ```

### Running IPFS Daemon

To start the IPFS daemon:

```bash
ipfs daemon
```

For background running (Linux/macOS):

```bash
nohup ipfs daemon > ipfs.log 2>&1 &
```

### Configuring IPFS for IPFS Datasets Python

To enable API access:

```bash
ipfs config Addresses.API /ip4/127.0.0.1/tcp/5001
ipfs config --json API.HTTPHeaders.Access-Control-Allow-Origin '["*"]'
ipfs config --json API.HTTPHeaders.Access-Control-Allow-Methods '["PUT", "GET", "POST"]'
```

## Configuration

IPFS Datasets Python uses a configuration file for customization.

### Default Configuration Location

- Linux/macOS: `~/.ipfs_datasets/config.toml`
- Windows: `%USERPROFILE%\.ipfs_datasets\config.toml`

### Creating a Configuration File

Create a configuration file with your preferred settings:

```bash
mkdir -p ~/.ipfs_datasets
cat > ~/.ipfs_datasets/config.toml << EOF
[ipfs]
api_endpoint = "/ip4/127.0.0.1/tcp/5001"
gateway_url = "http://localhost:8080/ipfs/"
pin = true

[storage]
cache_dir = "~/.ipfs_datasets/cache"
temp_dir = "/tmp/ipfs_datasets"
max_cache_size_gb = 10

[vector_index]
default_dimension = 768
default_metric = "cosine"
index_location = "~/.ipfs_datasets/indexes"
use_memory_mapping = true

[embedding_models]
default = "sentence-transformers/all-MiniLM-L6-v2"

[security]
encryption_enabled = true
require_authentication = false
EOF
```

### Configuration in Python

You can also configure settings programmatically:

```python
from ipfs_datasets_py.config import set_config_value, save_config

# Set individual values
set_config_value("vector_index.default_dimension", 1024)
set_config_value("embedding_models.default", "sentence-transformers/all-mpnet-base-v2")

# Save configuration
save_config()
```

## Troubleshooting

### Common Installation Issues

#### Missing Dependencies

**Issue**: `ImportError: No module named 'xxx'`

**Solution**:
```bash
pip install ipfs-datasets-py[all]
# Or for specific dependency
pip install xxx
```

#### IPFS Connection Issues

**Issue**: `ConnectionRefusedError: [Errno 111] Connection refused`

**Solutions**:
1. Ensure IPFS daemon is running: `ipfs daemon`
2. Check API endpoint configuration
3. Verify firewall settings

#### GPU Issues

**Issue**: `ImportError: libcudart.so.xx.x: cannot open shared object file`

**Solution**:
```bash
# Install CUDA toolkit
# Then reinstall with correct CUDA version
pip uninstall torch faiss-gpu
pip install torch==1.10.0+cu113 -f https://download.pytorch.org/whl/cu113/torch_stable.html
pip install faiss-gpu
```

### Getting Help

If you encounter issues not covered here:

1. Check the [GitHub Issues](https://github.com/your-organization/ipfs_datasets_py/issues) for similar problems
2. Read the [FAQ](faq.md) for common questions
3. Join the [Community Discussion](https://github.com/your-organization/ipfs_datasets_py/discussions)
4. File a new issue with detailed information about your problem