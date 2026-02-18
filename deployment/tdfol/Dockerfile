# Multi-stage Dockerfile for TDFOL (Temporal Dynamic First-Order Logic) Service
# Production-optimized with security best practices and size optimization

# Stage 1: Base builder with all build dependencies
FROM python:3.12-slim-bookworm AS builder

LABEL maintainer="IPFS Datasets Team"
LABEL description="TDFOL - Temporal Dynamic First-Order Logic Service"
LABEL version="1.0.0"

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment for dependency isolation
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy only requirements first for better layer caching
WORKDIR /build
COPY requirements.txt .
COPY setup.py .
COPY README.md .
COPY ipfs_datasets_py/ ipfs_datasets_py/
COPY ipfs_kit_py/ ipfs_kit_py/

# Install dependencies with optimization flags
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -e ".[logic,knowledge_graphs]"

# Download NLTK data
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('averaged_perceptron_tagger'); nltk.download('maxent_ne_chunker'); nltk.download('words')"

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Stage 2: Runtime image
FROM python:3.12-slim-bookworm AS runtime

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy NLTK and spaCy data
COPY --from=builder /root/nltk_data /root/nltk_data
COPY --from=builder /opt/venv/lib/python3.12/site-packages/en_core_web_sm /opt/venv/lib/python3.12/site-packages/en_core_web_sm

# Create non-root user for security
RUN groupadd -r tdfol && useradd -r -g tdfol -u 1000 tdfol

# Create application directories
RUN mkdir -p /app/data /app/logs /app/cache && \
    chown -R tdfol:tdfol /app

# Copy application code
WORKDIR /app
COPY --chown=tdfol:tdfol ipfs_datasets_py/ ipfs_datasets_py/
COPY --chown=tdfol:tdfol scripts/ scripts/
COPY --chown=tdfol:tdfol setup.py README.md ./

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TDFOL_DATA_DIR=/app/data \
    TDFOL_LOG_DIR=/app/logs \
    TDFOL_CACHE_DIR=/app/cache

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "from ipfs_datasets_py.logic.TDFOL.tdfol_core import TDFOLFormula; print('OK')" || exit 1

# Switch to non-root user
USER tdfol

# Expose default port
EXPOSE 8080

# Default command - can be overridden
CMD ["python", "-m", "ipfs_datasets_py.mcp_server"]
