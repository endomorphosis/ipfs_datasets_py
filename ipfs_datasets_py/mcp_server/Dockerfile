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

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Install the package
RUN pip install -e .

# Expose port
EXPOSE 8000

# Start the MCP server
CMD ["python", "-m", "ipfs_datasets_py.mcp_server", "--host", "0.0.0.0", "--port", "8000"]

# Usage:
# 1. Build the image: docker build -t ipfs-datasets-mcp .
# 2. Run the container: docker run -p 8000:8000 ipfs-datasets-mcp
# 3. To use custom configuration: docker run -p 8000:8000 -v /path/to/config.yaml:/app/config.yaml ipfs-datasets-mcp python -m ipfs_datasets_py.mcp_server --config /app/config.yaml
