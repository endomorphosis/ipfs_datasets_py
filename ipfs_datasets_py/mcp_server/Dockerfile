# Use a Python 3.10+ base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_NO_INTERACTION=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install first (for better Docker layer caching)
COPY ipfs_datasets_py/mcp_server/requirements-docker.txt requirements.txt
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Copy the entire project
COPY . .

# Copy dependency checker
COPY scripts/utilities/dependency_checker.py scripts/utilities/dependency_checker.py

# Install the package in development mode
RUN pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e .

# Run dependency checker to install comprehensive dependencies
RUN python scripts/utilities/dependency_checker.py --install-optional || echo "Some optional dependencies may be missing"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Start the MCP server
CMD ["python", "-m", "ipfs_datasets_py.mcp_server", "--host", "0.0.0.0", "--port", "8000"]

# Usage (build from repository root):
# 1. Build the image: docker build -f ipfs_datasets_py/mcp_server/Dockerfile -t ipfs-datasets-mcp .
# 2. Run the container: docker run -p 8000:8000 ipfs-datasets-mcp
# 3. To use custom configuration: docker run -p 8000:8000 -v /path/to/config.yaml:/app/config.yaml ipfs-datasets-mcp python -m ipfs_datasets_py.mcp_server --config /app/config.yaml
