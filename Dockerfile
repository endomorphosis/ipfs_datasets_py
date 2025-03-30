# IPFS Datasets Python
# A unified interface for data processing and distribution across decentralized networks

FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Install IPFS
RUN cd /tmp \
    && wget https://dist.ipfs.io/go-ipfs/v0.12.0/go-ipfs_v0.12.0_linux-amd64.tar.gz \
    && tar -xvzf go-ipfs_v0.12.0_linux-amd64.tar.gz \
    && cd go-ipfs \
    && bash install.sh \
    && cd .. \
    && rm -rf go-ipfs go-ipfs_v0.12.0_linux-amd64.tar.gz

# Copy project files
COPY . /app/

# Install the package and its dependencies
RUN pip install --no-cache-dir -e .

# Install optional dependencies based on the specified features
ARG FEATURES=all
RUN if [ "$FEATURES" = "all" ]; then \
        pip install --no-cache-dir -e ".[all]"; \
    elif [ "$FEATURES" = "vector" ]; then \
        pip install --no-cache-dir -e ".[vector]"; \
    elif [ "$FEATURES" = "graphrag" ]; then \
        pip install --no-cache-dir -e ".[graphrag]"; \
    elif [ "$FEATURES" = "webarchive" ]; then \
        pip install --no-cache-dir -e ".[webarchive]"; \
    elif [ "$FEATURES" = "distributed" ]; then \
        pip install --no-cache-dir -e ".[distributed]"; \
    elif [ "$FEATURES" = "minimal" ]; then \
        pip install --no-cache-dir -e "."; \
    fi

# Initialize IPFS (but don't start the daemon)
RUN ipfs init

# Set up the configuration directory
RUN mkdir -p /root/.ipfs_datasets \
    && cp /app/config/config.toml /root/.ipfs_datasets/config.toml

# Create volumes for data persistence
VOLUME ["/root/.ipfs", "/root/.ipfs_datasets", "/data"]

# Expose ports
# IPFS API and Gateway
EXPOSE 5001 8080
# libp2p ports
EXPOSE 4001/tcp 4001/udp
# Web service port
EXPOSE 8000

# Set up entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Default command (can be overridden)
CMD ["ipfs-datasets-server"]