#!/bin/bash
# Final verification script for Docker and GitHub Actions setup

set -e

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   Docker & GitHub Actions Setup - Final Verification     ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASSED=0
FAILED=0

check_item() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅${NC} $2"
        ((PASSED++))
    else
        echo -e "${RED}❌${NC} $2"
        ((FAILED++))
    fi
}

echo -e "${BLUE}📋 Checking System Prerequisites...${NC}"
echo ""

# Check Docker
docker --version > /dev/null 2>&1
check_item $? "Docker is installed"

docker images > /dev/null 2>&1
check_item $? "Docker is running"

docker compose version > /dev/null 2>&1
check_item $? "Docker Compose is available"

echo ""
echo -e "${BLUE}📦 Checking Docker Files...${NC}"
echo ""

# Check Dockerfiles
[ -f "Dockerfile" ]
check_item $? "Dockerfile exists"

[ -f "Dockerfile.minimal-test" ]
check_item $? "Dockerfile.minimal-test exists"

[ -f "Dockerfile.mcp-minimal" ]
check_item $? "Dockerfile.mcp-minimal exists"

[ -f "Dockerfile.dashboard-minimal" ]
check_item $? "Dockerfile.dashboard-minimal exists"

[ -f "docker-compose.yml" ]
check_item $? "docker-compose.yml exists"

[ -f "docker-compose.mcp.yml" ]
check_item $? "docker-compose.mcp.yml exists"

echo ""
echo -e "${BLUE}🔧 Checking Configuration Files...${NC}"
echo ""

[ -f ".env.example" ]
check_item $? ".env.example exists"

[ -f ".env" ]
check_item $? ".env exists"

[ -s ".env" ]
check_item $? ".env has content"

echo ""
echo -e "${BLUE}🚀 Checking GitHub Actions Workflows...${NC}"
echo ""

[ -f ".github/workflows/docker-build-test.yml" ]
check_item $? "docker-build-test.yml workflow exists"

[ -f ".github/workflows/docker-ci.yml" ]
check_item $? "docker-ci.yml workflow exists"

[ -f ".github/workflows/self-hosted-runner.yml" ]
check_item $? "self-hosted-runner.yml workflow exists"

echo ""
echo -e "${BLUE}📚 Checking Documentation...${NC}"
echo ""

[ -f "docs/RUNNER_SETUP.md" ]
check_item $? "docs/RUNNER_SETUP.md exists"

[ -f "DOCKER_GITHUB_ACTIONS_SETUP.md" ]
check_item $? "DOCKER_GITHUB_ACTIONS_SETUP.md exists"

[ -f "RUNNER_QUICKSTART.md" ]
check_item $? "RUNNER_QUICKSTART.md exists"

echo ""
echo -e "${BLUE}🧪 Checking Test Scripts...${NC}"
echo ""

[ -f "test_docker_x86.sh" ]
check_item $? "test_docker_x86.sh exists"

[ -x "test_docker_x86.sh" ]
check_item $? "test_docker_x86.sh is executable"

echo ""
echo -e "${BLUE}🐳 Checking Docker Images...${NC}"
echo ""

docker images ipfs-datasets-py:minimal-x86 > /dev/null 2>&1
check_item $? "ipfs-datasets-py:minimal-x86 image built"

# Test the image
if docker images ipfs-datasets-py:minimal-x86 | grep -q minimal-x86; then
    docker run --rm ipfs-datasets-py:minimal-x86 python -c "import sys; sys.exit(0)" > /dev/null 2>&1
    check_item $? "Docker image runs successfully"
else
    echo -e "${YELLOW}⏭️${NC}  Docker image not built yet (run test_docker_x86.sh)"
fi

echo ""
echo -e "${BLUE}🔍 Validating Docker Compose...${NC}"
echo ""

docker compose -f docker-compose.yml config > /dev/null 2>&1
check_item $? "docker-compose.yml is valid"

docker compose -f docker-compose.mcp.yml config > /dev/null 2>&1
check_item $? "docker-compose.mcp.yml is valid"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo -e "${GREEN}✅ Passed: $PASSED${NC}  ${RED}❌ Failed: $FAILED${NC}"
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 All checks passed! Setup is complete.${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Test Docker: bash test_docker_x86.sh"
    echo "  2. Commit changes: git add . && git commit -m 'Add Docker and GitHub Actions support'"
    echo "  3. Push to GitHub: git push"
    echo "  4. Set up runners: See RUNNER_QUICKSTART.md"
    echo ""
    exit 0
else
    echo -e "${RED}⚠️  Some checks failed. Please review the errors above.${NC}"
    echo ""
    exit 1
fi
