# Docker Configuration Files

This directory contains all Docker-related configuration files for the IPFS Datasets Python project.

## Docker Images

### Production Images

- **`Dockerfile`** - Main production image
- **`Dockerfile.simple`** - Simplified production image

### Test Images

- **`Dockerfile.test`** - General testing image
- **`Dockerfile.testing`** - Alternative testing configuration
- **`Dockerfile.minimal-test`** - Minimal test environment
- **`Dockerfile.cpu-tests`** - CPU-only test environment

### GPU Images

- **`Dockerfile.gpu`** - GPU-enabled image with CUDA support

### Specialized Images

- **`Dockerfile.mcp-minimal`** - Minimal MCP server image
- **`Dockerfile.mcp-simple`** - Simple MCP server image
- **`Dockerfile.mcp-tests`** - MCP testing image
- **`Dockerfile.dashboard-minimal`** - Minimal dashboard image
- **`Dockerfile.graphrag-tests`** - GraphRAG testing image

## Docker Compose Files

- **`docker-compose.yml`** - Main Docker Compose configuration
- **`docker-compose.mcp.yml`** - MCP-specific services
- **`docker-compose.enhanced.yml`** - Enhanced configuration with additional services

## Building Images

### Build a specific image:
```bash
# From repository root
docker build -t ipfs-datasets-py -f docker/Dockerfile .

# Build test image
docker build -t ipfs-datasets-py:test -f docker/Dockerfile.test .

# Build MCP minimal image
docker build -t ipfs-datasets-py:mcp -f docker/Dockerfile.mcp-minimal .
```

### Using Docker Compose:
```bash
# From repository root
docker compose -f docker/docker-compose.yml up

# MCP services
docker compose -f docker/docker-compose.mcp.yml up

# Enhanced configuration
docker compose -f docker/docker-compose.enhanced.yml up
```

## Multi-Platform Builds

Build for multiple architectures (x86_64 and ARM64):

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/Dockerfile.minimal-test \
  -t ipfs-datasets-py:multiarch \
  .
```

## Testing

Run tests in Docker container:

```bash
# Run test suite
docker build -t ipfs-datasets-py:test -f docker/Dockerfile.test .
docker run --rm ipfs-datasets-py:test pytest

# Run GPU tests (requires GPU host)
docker build -t ipfs-datasets-py:gpu -f docker/Dockerfile.gpu .
docker run --rm --gpus all ipfs-datasets-py:gpu pytest -m gpu
```

## CI/CD Integration

These Docker images are used in GitHub Actions workflows:

- `.github/workflows/docker-build-test.yml` - Multi-platform build testing
- `.github/workflows/docker-ci.yml` - Docker CI validation
- `.github/workflows/gpu-tests.yml` - GPU-enabled tests
- `.github/workflows/mcp-integration-tests.yml` - MCP integration tests

## Image Sizing Guidelines

- **Minimal images** (~500MB-1GB) - For basic functionality
- **Test images** (~1-2GB) - Include test dependencies
- **Full images** (~2-3GB) - Include all features
- **GPU images** (~4-6GB) - Include CUDA toolkit

## Best Practices

1. **Use specific base images** - Pin versions for reproducibility
2. **Multi-stage builds** - Reduce final image size
3. **Layer caching** - Order commands from least to most frequently changing
4. **Security** - Use non-root users, scan for vulnerabilities
5. **Documentation** - Keep this README updated with new images

## Maintenance

When adding new Docker images:
1. Add the Dockerfile to this directory
2. Update this README with description
3. Update relevant CI/CD workflows
4. Test locally before committing
5. Consider multi-platform support

## Troubleshooting

### Build Issues
- Check Docker daemon is running
- Verify base image availability
- Review build logs for errors

### Permission Issues
- Ensure user has Docker group membership
- Check file permissions in context

### Network Issues
- Verify internet connectivity for package downloads
- Check proxy settings if behind firewall

## Related Documentation

- [Main README](../README.md)
- [Setup Guide](../docs/quickstart/PLATFORM_INSTALL.md)
- [CI/CD Documentation](../.github/workflows/README.md)
