#!/bin/bash
# Docker Build and Test Script for IPFS Datasets Python
# Tests dependency installer integration in Docker containers

set -e

echo "🐳 Docker Integration Test for Dependency Installer"
echo "================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test functions
test_build() {
    local dockerfile=$1
    local tag=$2
    echo -e "${YELLOW}Building $dockerfile as $tag...${NC}"
    
    if docker build -f "$dockerfile" -t "$tag" . --quiet; then
        echo -e "${GREEN}✅ Build successful: $tag${NC}"
        return 0
    else
        echo -e "${RED}❌ Build failed: $tag${NC}"
        return 1
    fi
}

test_dependency_check() {
    local tag=$1
    echo -e "${YELLOW}Testing dependency checker in $tag...${NC}"
    
    if docker run --rm "$tag" dependency-check --check-only; then
        echo -e "${GREEN}✅ Dependency check passed: $tag${NC}"
        return 0
    else
        echo -e "${RED}❌ Dependency check failed: $tag${NC}"
        return 1
    fi
}

test_service_start() {
    local tag=$1
    local service=$2
    echo -e "${YELLOW}Testing service startup: $service in $tag...${NC}"
    
    # Start container in background
    container_id=$(docker run -d --rm -p 8000:8000 -p 8899:8899 "$tag" "$service")
    
    # Wait a moment for startup
    sleep 10
    
    # Test health endpoint
    if [ "$service" = "mcp-server" ]; then
        if curl -s http://localhost:8000/health > /dev/null; then
            echo -e "${GREEN}✅ Service healthy: $service${NC}"
            docker stop "$container_id" > /dev/null
            return 0
        fi
    elif [ "$service" = "mcp-dashboard" ]; then
        if curl -s http://localhost:8899/api/mcp/status > /dev/null; then
            echo -e "${GREEN}✅ Service healthy: $service${NC}"
            docker stop "$container_id" > /dev/null
            return 0
        fi
    fi
    
    echo -e "${RED}❌ Service health check failed: $service${NC}"
    docker logs "$container_id" | tail -20
    docker stop "$container_id" > /dev/null
    return 1
}

# Main test execution
main() {
    local failed=0
    
    echo "🏗️  Testing Docker builds..."
    
    # Test main Dockerfile
    if test_build "Dockerfile" "ipfs-datasets-main"; then
        test_dependency_check "ipfs-datasets-main" || ((failed++))
    else
        ((failed++))
    fi
    
    # Test MCP minimal Dockerfile
    if test_build "Dockerfile.mcp-minimal" "ipfs-datasets-mcp-minimal"; then
        test_dependency_check "ipfs-datasets-mcp-minimal" || ((failed++))
        test_service_start "ipfs-datasets-mcp-minimal" "mcp-server" || ((failed++))
    else
        ((failed++))
    fi
    
    # Test dashboard minimal Dockerfile
    if test_build "Dockerfile.dashboard-minimal" "ipfs-datasets-dashboard-minimal"; then
        test_dependency_check "ipfs-datasets-dashboard-minimal" || ((failed++))
        test_service_start "ipfs-datasets-dashboard-minimal" "mcp-dashboard" || ((failed++))
    else
        ((failed++))
    fi
    
    # Test MCP server Dockerfile
    if test_build "ipfs_datasets_py/mcp_server/Dockerfile" "ipfs-datasets-mcp-server"; then
        test_dependency_check "ipfs-datasets-mcp-server" || ((failed++))
    else
        ((failed++))
    fi
    
    echo ""
    echo "📊 Test Results:"
    echo "================"
    
    if [ $failed -eq 0 ]; then
        echo -e "${GREEN}🎉 All tests passed! Docker integration successful.${NC}"
        echo "✅ Dependency installer is working in all Docker containers"
        echo "✅ All services can start with proper dependency management"
        return 0
    else
        echo -e "${RED}❌ $failed test(s) failed.${NC}"
        echo "Please check the build logs and fix any issues."
        return 1
    fi
}

# Cleanup function
cleanup() {
    echo "🧹 Cleaning up test containers and images..."
    docker system prune -f > /dev/null 2>&1 || true
}

# Set up cleanup on exit
trap cleanup EXIT

# Run main test
main "$@"