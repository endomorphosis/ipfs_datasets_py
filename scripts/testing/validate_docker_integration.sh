#!/bin/bash
# Quick Docker Integration Validation
# Tests that dependency checker is properly integrated into Docker setup

echo "🐳 Validating Docker Integration for Dependency Installer"
echo "========================================================"

# Check if Dockerfiles include dependency checker
echo "📄 Checking Dockerfile integration..."

check_dockerfile() {
    local file=$1
    echo -n "  $file: "
    
    if grep -q "dependency_checker.py" "$file" 2>/dev/null; then
        echo "✅ Integrated"
    else
        echo "❌ Missing"
        return 1
    fi
}

# Check main Dockerfiles
check_dockerfile "Dockerfile"
check_dockerfile "Dockerfile.mcp-minimal" 
check_dockerfile "Dockerfile.dashboard-minimal"
check_dockerfile "ipfs_datasets_py/mcp_server/Dockerfile"

# Check docker-compose files
echo ""
echo "📋 Checking Docker Compose integration..."

if [ -f "docker-compose.enhanced.yml" ]; then
    echo "  ✅ Enhanced compose file exists"
else
    echo "  ❌ Enhanced compose file missing"
fi

# Check entrypoint script
echo ""
echo "🚪 Checking entrypoint script..."

if grep -q "dependency_checker.py" "docker-entrypoint.sh" 2>/dev/null; then
    echo "  ✅ Entrypoint includes dependency checking"
else
    echo "  ❌ Entrypoint missing dependency checking"
fi

# Check if documentation exists
echo ""
echo "📚 Checking documentation..."

if [ -f "DOCKER_DEPENDENCY_INTEGRATION.md" ]; then
    echo "  ✅ Docker integration documentation exists"
else
    echo "  ❌ Docker integration documentation missing"
fi

echo ""
echo "🏁 Integration validation complete!"
echo ""
echo "To test a Docker build:"
echo "  docker build -f docker/Dockerfile.mcp-minimal -t test-deps ."
echo "  docker run --rm test-deps dependency-check --check-only"
echo ""
echo "To run enhanced services:"
echo "  docker-compose -f docker-compose.mcp.yml -f docker-compose.enhanced.yml up"