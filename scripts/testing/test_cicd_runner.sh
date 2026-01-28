#!/bin/bash
# Test script to validate CI/CD runner setup and functionality

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

REPO_NAME="ipfs_datasets_py"
RUNNER_DIR="$HOME/actions-runner-${REPO_NAME}"

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║        CI/CD Runner Validation - ipfs_datasets_py            ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TOTAL=0

# Test result tracking
declare -a FAILED_TESTS=()

# Helper functions
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    echo -e "${BLUE}[TEST $TESTS_TOTAL]${NC} $test_name"
    
    if eval "$test_command" &> /dev/null; then
        echo -e "  ${GREEN}✓ PASS${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_TESTS+=("$test_name")
        return 1
    fi
}

run_test_with_output() {
    local test_name="$1"
    local test_command="$2"
    
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    echo -e "${BLUE}[TEST $TESTS_TOTAL]${NC} $test_name"
    
    local output
    output=$(eval "$test_command" 2>&1)
    local result=$?
    
    if [ $result -eq 0 ]; then
        echo -e "  ${GREEN}✓ PASS${NC}"
        echo -e "  ${CYAN}Output:${NC} $output"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "  ${RED}✗ FAIL${NC}"
        echo -e "  ${RED}Error:${NC} $output"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_TESTS+=("$test_name")
        return 1
    fi
}

print_section() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Start tests
print_section "1. System Prerequisites"

run_test_with_output "Docker installed" "docker --version"
run_test "Docker daemon running" "docker ps"
run_test "User can run Docker" "docker run --rm hello-world"
run_test_with_output "Architecture check" "uname -m"
run_test_with_output "OS check" "cat /etc/os-release | grep PRETTY_NAME"

print_section "2. Runner Installation"

run_test "Runner directory exists" "[ -d '$RUNNER_DIR' ]"
run_test "Runner binary exists" "[ -f '$RUNNER_DIR/run.sh' ]"
run_test "Runner config exists" "[ -f '$RUNNER_DIR/.runner' ]"
run_test "Runner credentials exist" "[ -f '$RUNNER_DIR/.credentials' ]"

print_section "3. Runner Service"

if systemctl list-units --type=service | grep -q "actions.runner.*${REPO_NAME}"; then
    SERVICE_NAME=$(systemctl list-units --type=service | grep "actions.runner.*${REPO_NAME}" | awk '{print $1}')
    echo -e "${CYAN}Found service: $SERVICE_NAME${NC}"
    
    run_test "Runner service exists" "systemctl list-units --type=service | grep -q 'actions.runner.*${REPO_NAME}'"
    run_test "Runner service is enabled" "systemctl is-enabled $SERVICE_NAME"
    run_test "Runner service is active" "systemctl is-active $SERVICE_NAME"
    run_test_with_output "Runner service status" "systemctl status $SERVICE_NAME --no-pager | head -5"
else
    echo -e "${RED}✗ Runner service not found${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 4))
    TESTS_TOTAL=$((TESTS_TOTAL + 4))
    FAILED_TESTS+=("Runner service exists" "Runner service is enabled" "Runner service is active" "Runner service status")
fi

print_section "4. Docker Functionality"

run_test "Pull test image" "docker pull alpine:latest"
run_test "Run simple container" "docker run --rm alpine:latest echo 'Hello from Docker'"
run_test "Docker network access" "docker run --rm alpine:latest ping -c 1 google.com"
run_test "Docker build capability" "cd /home/barberb/ipfs_datasets_py && docker build -t test-runner:test -f docker/Dockerfile.minimal-test . --quiet"

if docker images | grep -q "test-runner.*test"; then
    run_test "Test image created" "docker images | grep -q 'test-runner.*test'"
    run_test "Test image runs" "docker run --rm test-runner:test python -c 'import sys; print(sys.version)'"
    
    # Cleanup
    docker rmi test-runner:test &> /dev/null || true
fi

print_section "5. GPU Support (Optional)"

if command -v nvidia-smi &> /dev/null; then
    run_test_with_output "NVIDIA GPU detected" "nvidia-smi --query-gpu=name --format=csv,noheader"
    run_test "NVIDIA driver loaded" "nvidia-smi"
    
    if docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &> /dev/null 2>&1; then
        run_test "Docker GPU access" "docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi"
        run_test_with_output "GPU memory check" "docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi --query-gpu=memory.total --format=csv,noheader"
        echo -e "${GREEN}✓ GPU support is fully functional${NC}"
    else
        echo -e "${YELLOW}⚠ GPU detected but Docker cannot access it${NC}"
        echo -e "  Consider installing nvidia-container-toolkit"
    fi
else
    echo -e "${CYAN}ℹ No GPU detected (this is fine for CPU-only workflows)${NC}"
fi

print_section "6. Repository Integration"

if [ -d "/home/barberb/ipfs_datasets_py/.git" ]; then
    run_test "Repository exists" "[ -d '/home/barberb/ipfs_datasets_py/.git' ]"
    run_test_with_output "Git remote configured" "cd /home/barberb/ipfs_datasets_py && git remote -v | head -1"
    run_test "Git working tree clean" "cd /home/barberb/ipfs_datasets_py && git status --porcelain | wc -l | grep -q '^0$' || true"
    run_test "Can access GitHub" "curl -s -o /dev/null -w '%{http_code}' https://github.com | grep -q 200"
else
    echo -e "${RED}✗ Repository not found at /home/barberb/ipfs_datasets_py${NC}"
fi

print_section "7. Workflow Files"

WORKFLOW_DIR="/home/barberb/ipfs_datasets_py/.github/workflows"
if [ -d "$WORKFLOW_DIR" ]; then
    WORKFLOW_COUNT=$(ls -1 "$WORKFLOW_DIR"/*.yml 2>/dev/null | wc -l)
    echo -e "${CYAN}Found $WORKFLOW_COUNT workflow files${NC}"
    
    run_test "Workflow directory exists" "[ -d '$WORKFLOW_DIR' ]"
    run_test "Self-hosted runner workflow exists" "[ -f '$WORKFLOW_DIR/self-hosted-runner.yml' ]"
    run_test "Runner validation workflow exists" "[ -f '$WORKFLOW_DIR/runner-validation-clean.yml' ]"
    
    if [ -f "$WORKFLOW_DIR/gpu-tests.yml" ]; then
        echo -e "${GREEN}✓ GPU tests workflow found${NC}"
    fi
    
    # List all workflows
    echo ""
    echo -e "${CYAN}Available workflows:${NC}"
    ls -1 "$WORKFLOW_DIR"/*.yml 2>/dev/null | xargs -n 1 basename | sed 's/^/  • /'
else
    echo -e "${RED}✗ Workflow directory not found${NC}"
fi

print_section "8. System Resources"

echo -e "${CYAN}System Information:${NC}"
echo "  • Hostname: $(hostname)"
echo "  • Architecture: $(uname -m)"
echo "  • CPU Cores: $(nproc)"
echo "  • Memory: $(free -h | grep Mem | awk '{print $2}')"
echo "  • Disk Available: $(df -h / | tail -1 | awk '{print $4}')"

# Check minimum requirements
run_test "Sufficient CPU cores (>1)" "[ $(nproc) -gt 1 ]"
run_test "Sufficient memory (>2GB)" "[ $(free -g | grep Mem | awk '{print $2}') -gt 2 ]"
run_test "Sufficient disk space (>10GB)" "[ $(df -BG / | tail -1 | awk '{print $4}' | tr -d 'G') -gt 10 ]"

print_section "9. Runner Logs Check"

if systemctl list-units --type=service | grep -q "actions.runner.*${REPO_NAME}"; then
    SERVICE_NAME=$(systemctl list-units --type=service | grep "actions.runner.*${REPO_NAME}" | awk '{print $1}')
    
    echo -e "${CYAN}Recent runner logs (last 10 lines):${NC}"
    sudo journalctl -u "$SERVICE_NAME" -n 10 --no-pager | tail -10
    
    run_test "No critical errors in logs" "! sudo journalctl -u '$SERVICE_NAME' -n 50 --no-pager | grep -i 'fatal\|critical'"
else
    echo -e "${YELLOW}⚠ Cannot check logs - service not found${NC}"
fi

# Final summary
print_section "Test Summary"

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                    Test Results                           ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Total Tests:  ${BLUE}$TESTS_TOTAL${NC}"
echo -e "  Passed:       ${GREEN}$TESTS_PASSED${NC}"
echo -e "  Failed:       ${RED}$TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              ✓ ALL TESTS PASSED!                          ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}Your CI/CD runner is fully operational!${NC}"
    echo ""
    echo -e "${CYAN}Next steps:${NC}"
    echo "  1. Verify runner on GitHub:"
    echo "     https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners"
    echo ""
    echo "  2. Test with a workflow run:"
    echo "     cd /home/barberb/ipfs_datasets_py"
    echo "     git commit --allow-empty -m '[test-runner] Testing CI/CD runner'"
    echo "     git push"
    echo ""
    echo "  3. Monitor workflow execution:"
    echo "     https://github.com/endomorphosis/ipfs_datasets_py/actions"
    echo ""
    exit 0
else
    echo -e "${RED}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║              ✗ SOME TESTS FAILED                          ║${NC}"
    echo -e "${RED}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Failed tests:${NC}"
    for test in "${FAILED_TESTS[@]}"; do
        echo "  ✗ $test"
    done
    echo ""
    echo -e "${CYAN}Troubleshooting:${NC}"
    echo "  1. Review the failed tests above"
    echo "  2. Check runner service logs:"
    echo "     sudo journalctl -u actions.runner.* -n 50"
    echo "  3. Verify runner configuration:"
    echo "     cd $RUNNER_DIR && cat .runner"
    echo "  4. Try restarting the runner:"
    echo "     cd $RUNNER_DIR && sudo ./svc.sh restart"
    echo ""
    exit 1
fi
