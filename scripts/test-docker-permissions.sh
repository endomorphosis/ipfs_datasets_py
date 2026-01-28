#!/bin/bash
# test-docker-permissions.sh
# Test script to verify Docker permission fixes for GitHub Actions runners

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Function to test basic Docker functionality
test_docker_basic() {
    print_header "Basic Docker Tests"
    
    # Test 1: Docker version
    if docker --version >/dev/null 2>&1; then
        print_success "Docker version command works"
        docker --version
    else
        print_error "Docker version command failed"
        return 1
    fi
    
    # Test 2: Docker info
    if docker info >/dev/null 2>&1; then
        print_success "Docker info command works"
    else
        print_error "Docker info command failed"
        return 1
    fi
    
    # Test 3: Docker ps
    if docker ps >/dev/null 2>&1; then
        print_success "Docker ps command works"
    else
        print_error "Docker ps command failed"
        return 1
    fi
    
    return 0
}

# Function to test Docker build capability
test_docker_build() {
    print_header "Docker Build Tests"
    
    # Create a minimal test Dockerfile
    cat > /tmp/Dockerfile.test << 'EOF'
FROM alpine:latest
RUN echo "Docker build test successful" > /test-result.txt
CMD ["cat", "/test-result.txt"]
EOF
    
    # Test Docker build
    if docker build -t test-docker-permissions -f /tmp/Dockerfile.test /tmp >/dev/null 2>&1; then
        print_success "Docker build works"
        
        # Test Docker run
        if RESULT=$(docker run --rm test-docker-permissions 2>/dev/null); then
            if [[ "$RESULT" == "Docker build test successful" ]]; then
                print_success "Docker run works - got expected output"
            else
                print_warning "Docker run works but unexpected output: $RESULT"
            fi
        else
            print_error "Docker run failed"
        fi
        
        # Cleanup
        docker rmi test-docker-permissions >/dev/null 2>&1 || true
    else
        print_error "Docker build failed"
        return 1
    fi
    
    # Cleanup test file
    rm -f /tmp/Dockerfile.test
    return 0
}

# Function to test permissions specifically
test_docker_permissions() {
    print_header "Docker Permission Analysis"
    
    print_info "Current user: $(whoami)"
    print_info "User ID: $(id -u)"
    print_info "Groups: $(groups)"
    
    # Check if user is in docker group
    if groups $(whoami) | grep -q docker; then
        print_success "User $(whoami) is in docker group"
    else
        print_error "User $(whoami) is NOT in docker group"
    fi
    
    # Check Docker socket permissions
    if [[ -S /var/run/docker.sock ]]; then
        SOCKET_PERMS=$(ls -la /var/run/docker.sock)
        print_info "Docker socket permissions: $SOCKET_PERMS"
        
        if [[ -r /var/run/docker.sock && -w /var/run/docker.sock ]]; then
            print_success "Docker socket is readable and writable"
        else
            print_error "Docker socket access is limited"
        fi
    else
        print_error "Docker socket not found at /var/run/docker.sock"
    fi
}

# Function to test runner-specific scenarios
test_runner_scenarios() {
    print_header "Runner-Specific Tests"
    
    # Check if running in a GitHub Actions environment
    if [[ -n "$GITHUB_ACTIONS" ]]; then
        print_info "Running in GitHub Actions environment"
        print_info "Runner OS: ${RUNNER_OS:-unknown}"
        print_info "Runner Arch: ${RUNNER_ARCH:-unknown}"
    else
        print_info "Not running in GitHub Actions environment"
    fi
    
    # Test Docker with common CI patterns
    print_info "Testing common CI Docker patterns..."
    
    # Test: Pull and run a simple image
    if docker pull alpine:latest >/dev/null 2>&1; then
        print_success "Docker pull works"
        
        if docker run --rm alpine:latest echo "CI test successful" >/dev/null 2>&1; then
            print_success "Docker run with pulled image works"
        else
            print_error "Docker run with pulled image failed"
        fi
    else
        print_error "Docker pull failed"
    fi
}

# Function to test project-specific Docker scenarios
test_project_docker() {
    print_header "Project Docker Tests"
    
    # Look for project Dockerfiles
    if [[ -f "Dockerfile.test" ]]; then
        print_info "Found Dockerfile.test - testing project build"
        
        if docker build -t ipfs-datasets-test -f docker/Dockerfile.test . >/dev/null 2>&1; then
            print_success "Project Docker build (Dockerfile.test) works"
            
            # Test basic import
            if docker run --rm ipfs-datasets-test python -c "import ipfs_datasets_py; print('Import successful')" >/dev/null 2>&1; then
                print_success "Project package import test works"
            else
                print_warning "Project package import test failed"
            fi
            
            # Cleanup
            docker rmi ipfs-datasets-test >/dev/null 2>&1 || true
        else
            print_error "Project Docker build failed"
        fi
    else
        print_info "No Dockerfile.test found - skipping project build test"
    fi
    
    # Test Docker Compose if available
    if [[ -f "docker/docker-compose.yml" ]]; then
        print_info "Found docker-compose.yml - testing validation"
        
        if docker compose config >/dev/null 2>&1; then
            print_success "Docker Compose configuration is valid"
        else
            print_error "Docker Compose configuration validation failed"
        fi
    fi
}

# Function to provide recommendations
provide_recommendations() {
    print_header "Recommendations"
    
    # Check if all tests passed
    if [[ $DOCKER_BASIC_OK == "true" && $DOCKER_BUILD_OK == "true" ]]; then
        print_success "All Docker tests passed! Your configuration is working correctly."
    else
        print_error "Some Docker tests failed. Consider the following:"
        echo ""
        echo "1. Add your user to the docker group:"
        echo "   sudo usermod -aG docker \$(whoami)"
        echo ""
        echo "2. If you're using a runner service, restart it:"
        echo "   sudo systemctl restart actions.runner.*"
        echo ""
        echo "3. For immediate testing (less secure):"
        echo "   sudo chmod 666 /var/run/docker.sock"
        echo ""
        echo "4. Use our automated fix script:"
        echo "   sudo ./scripts/setup-runner-docker-permissions.sh"
    fi
}

# Main execution
main() {
    echo -e "${BLUE}"
    echo "🐳 Docker Permission Test Suite"
    echo "=============================="
    echo -e "${NC}"
    
    DOCKER_BASIC_OK="false"
    DOCKER_BUILD_OK="false"
    
    # Run tests
    test_docker_permissions
    
    if test_docker_basic; then
        DOCKER_BASIC_OK="true"
    fi
    
    if test_docker_build; then
        DOCKER_BUILD_OK="true"
    fi
    
    test_runner_scenarios
    test_project_docker
    provide_recommendations
    
    print_header "Test Summary"
    echo "Basic Docker: $([ "$DOCKER_BASIC_OK" = "true" ] && echo -e "${GREEN}PASS${NC}" || echo -e "${RED}FAIL${NC}")"
    echo "Docker Build: $([ "$DOCKER_BUILD_OK" = "true" ] && echo -e "${GREEN}PASS${NC}" || echo -e "${RED}FAIL${NC}")"
    
    if [[ $DOCKER_BASIC_OK == "true" && $DOCKER_BUILD_OK == "true" ]]; then
        echo -e "\n${GREEN}🎉 All tests passed! Docker permissions are working correctly.${NC}"
        exit 0
    else
        echo -e "\n${RED}⚠️  Some tests failed. Docker permissions need attention.${NC}"
        exit 1
    fi
}

# Run main function
main "$@"