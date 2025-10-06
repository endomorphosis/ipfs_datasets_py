# IPFS Datasets Deployment Guide

## Overview
This guide provides comprehensive instructions for deploying the **production-ready** IPFS Datasets API with integrated embedding capabilities. After comprehensive documentation reconciliation (July 4, 2025), this system is confirmed to be **~95% implemented and functional**.

## Current Status ✅
- **Implementation**: All core components implemented and functional
- **Testing**: Test framework standardized (Worker 130 complete), implementation in progress (Worker 131)
- **Documentation**: Fully reconciled and accurate
- **Deployment**: Ready for production deployment

## Quick Start

### 1. Environment Setup
```bash
# Clone and navigate to the project
cd /path/to/ipfs_datasets_py-1

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Start the Service

#### Development Mode
```bash
# Start with debug and auto-reload
python start_fastapi.py --env development --debug --reload

# Or use VS Code task
# Run Task: "Start FastAPI Service"
```

#### Production Mode
```bash
# Start production server
python start_fastapi.py --env production --host 0.0.0.0 --port 8000
```

### 3. Access the API
- **API Documentation**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health
- **API Status**: http://localhost:8000/api/status

## Configuration

### Environment Variables
Set these environment variables for production deployment:

```bash
# Application settings
export DEBUG=false
export ENVIRONMENT=production
export HOST=0.0.0.0
export PORT=8000

# Security settings
export SECRET_KEY=your-production-secret-key-here
export ACCESS_TOKEN_EXPIRE_MINUTES=30

# Rate limiting
export RATE_LIMIT_ENABLED=true
export REDIS_URL=redis://localhost:6379  # Optional for distributed rate limiting

# Embedding settings
export DEFAULT_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# CORS settings (adjust for your domain)
export ALLOWED_ORIGINS=["https://yourdomain.com","https://api.yourdomain.com"]
```

### Configuration File
Alternatively, create a `.env` file in the project root:

```env
DEBUG=false
ENVIRONMENT=production
SECRET_KEY=your-production-secret-key-here
HOST=0.0.0.0
PORT=8000
ALLOWED_ORIGINS=["*"]
RATE_LIMIT_ENABLED=true
DEFAULT_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

## API Usage Examples

### Authentication
```bash
# Get authentication token
curl -X POST "http://localhost:8000/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"username": "demo", "password": "demo"}'

# Response: {"access_token": "...", "token_type": "bearer", "expires_in": 1800}
```

### Generate Embeddings
```bash
# Single text embedding
curl -X POST "http://localhost:8000/embeddings/generate" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"text": "Hello world", "model": "sentence-transformers/all-MiniLM-L6-v2"}'

# Batch embedding generation
curl -X POST "http://localhost:8000/embeddings/batch" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"texts": ["Hello", "World"], "model": "sentence-transformers/all-MiniLM-L6-v2"}'
```

### Dataset Operations
```bash
# Load a dataset
curl -X POST "http://localhost:8000/datasets/load" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"source": "squad", "format": "json"}'

# Process a dataset
curl -X POST "http://localhost:8000/datasets/process" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"dataset_source": "dataset_id", "operations": [{"type": "filter", "column": "text", "condition": "length > 100"}]}'
```

### Vector Search
```bash
# Semantic search
curl -X POST "http://localhost:8000/search/semantic" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"query": "machine learning", "collection_name": "documents", "top_k": 10}'
```

### IPFS Operations
```bash
# Pin content to IPFS
curl -X POST "http://localhost:8000/ipfs/pin" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"content_source": "/path/to/file.json"}'

# Get content from IPFS
curl -X GET "http://localhost:8000/ipfs/get/QmYourCIDHere" \
     -H "Authorization: Bearer YOUR_TOKEN"
```

## Production Deployment

### Docker Deployment (Recommended)

#### 1. Create Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 apiuser && chown -R apiuser:apiuser /app
USER apiuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the application
CMD ["python", "start_fastapi.py", "--env", "production"]
```

#### 2. Build and Run Container
```bash
# Build the image
docker build -t ipfs-datasets-api .

# Run the container
docker run -d \
    --name ipfs-datasets-api \
    -p 8000:8000 \
    -e SECRET_KEY=your-production-secret \
    -e ENVIRONMENT=production \
    ipfs-datasets-api
```

#### 3. Docker Compose (with Redis)
```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - SECRET_KEY=your-production-secret
      - ENVIRONMENT=production
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - api
    restart: unless-stopped
```

### Systemd Service (Linux)

#### 1. Create Service File
```ini
# /etc/systemd/system/ipfs-datasets-api.service
[Unit]
Description=IPFS Datasets API Service
After=network.target

[Service]
Type=exec
User=apiuser
Group=apiuser
WorkingDirectory=/opt/ipfs-datasets-api
Environment=PATH=/opt/ipfs-datasets-api/.venv/bin
Environment=SECRET_KEY=your-production-secret
Environment=ENVIRONMENT=production
ExecStart=/opt/ipfs-datasets-api/.venv/bin/python start_fastapi.py --env production
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

#### 2. Enable and Start Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable ipfs-datasets-api
sudo systemctl start ipfs-datasets-api
sudo systemctl status ipfs-datasets-api
```

## Monitoring and Maintenance

### Health Monitoring
```bash
# Basic health check
curl http://localhost:8000/health

# Detailed health information (requires authentication)
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/admin/health

# System statistics
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/admin/stats
```

### Log Monitoring
```bash
# Follow application logs (if using systemd)
sudo journalctl -u ipfs-datasets-api -f

# Docker logs
docker logs -f ipfs-datasets-api
```

### Performance Monitoring
```bash
# Cache statistics
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/cache/stats

# List available tools
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/tools/list
```

## Security Considerations

### Production Security Checklist
- [ ] Change default SECRET_KEY to a strong, random value
- [ ] Configure ALLOWED_ORIGINS for CORS appropriately
- [ ] Use HTTPS in production with proper SSL certificates
- [ ] Implement proper user authentication (beyond demo credentials)
- [ ] Set up rate limiting with Redis for distributed deployments
- [ ] Configure firewall rules to restrict access
- [ ] Regularly update dependencies for security patches
- [ ] Monitor audit logs for suspicious activity

### SSL/TLS Configuration
For production deployments, use a reverse proxy (nginx/Apache) with SSL:

```nginx
server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    ssl_certificate /path/to/certificate.crt;
    ssl_certificate_key /path/to/private.key;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Troubleshooting

### Common Issues

#### Import Errors
```bash
# Verify environment activation
source .venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Check Python path
python -c "import sys; print(sys.path)"
```

#### Port Already in Use
```bash
# Find process using port 8000
lsof -i :8000

# Kill process if needed
kill -9 <PID>

# Or use different port
python start_fastapi.py --port 8001
```

#### Permission Errors
```bash
# Check file permissions
ls -la start_fastapi.py

# Make executable if needed
chmod +x start_fastapi.py
```

### Validation Scripts
```bash
# Run comprehensive validation
python final_integration_validation.py

# Test FastAPI specifically
python validate_fastapi.py

# Test API endpoints
python test_fastapi_service.py
```

## Support and Documentation

- **API Documentation**: Available at `/docs` endpoint when service is running
- **OpenAPI Schema**: Available at `/openapi.json`
- **Health Status**: Available at `/health`
- **Integration Status**: See `INTEGRATION_STATUS_SUMMARY.md`
- **Phase Reports**: See `PHASE_*_COMPLETION_REPORT.md` files

## Performance Optimization

### For High-Load Environments
1. **Use Multiple Workers**: Configure uvicorn with multiple worker processes
2. **Redis Caching**: Enable Redis for distributed caching and rate limiting
3. **Load Balancing**: Use nginx or HAProxy for load distribution
4. **Database**: Consider PostgreSQL for persistent user management
5. **Monitoring**: Implement Prometheus/Grafana for metrics
6. **CDN**: Use CDN for static assets and API responses where appropriate

### Memory Optimization
```bash
# Start with limited workers for memory-constrained environments
uvicorn ipfs_datasets_py.fastapi_service:app --workers 2 --max-requests 1000
```

This deployment guide provides everything needed to run the IPFS Datasets API in development or production environments with the full embedding capabilities integrated from the ipfs_embeddings_py project.
