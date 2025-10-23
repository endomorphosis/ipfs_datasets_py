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

# Install IPFS (support both ARM64 and AMD64)
RUN cd /tmp \
    && ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then IPFS_ARCH="arm64"; else IPFS_ARCH="amd64"; fi \
    && wget https://dist.ipfs.io/kubo/v0.23.0/kubo_v0.23.0_linux-${IPFS_ARCH}.tar.gz \
    && tar -xvzf kubo_v0.23.0_linux-${IPFS_ARCH}.tar.gz \
    && cd kubo \
    && bash install.sh \
    && cd .. \
    && rm -rf kubo kubo_v0.23.0_linux-${IPFS_ARCH}.tar.gz

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