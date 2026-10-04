#!/bin/bash
# CI/CD Setup Helper - Shows what to do next

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

clear

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                                                               ║${NC}"
echo -e "${CYAN}║         CI/CD Setup for ipfs_datasets_py                      ║${NC}"
echo -e "${CYAN}║                                                               ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${GREEN}✅ CI/CD Setup Tools Ready!${NC}"
echo ""
echo "The CI/CD setup tools have been configured for this x86_64 server."
echo "These tools will set up a self-hosted GitHub Actions runner for"
echo "the ipfs_datasets_py repository."
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Quick Setup (3 Steps)${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${YELLOW}Step 1: Get GitHub Token${NC}"
echo ""
echo "  Visit this URL in your browser:"
echo -e "  ${BLUE}https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners/new${NC}"
echo ""
echo "  Select:"
echo "    • OS: Linux"
echo "    • Architecture: X64"
echo ""
echo "  Copy the registration token from the commands shown."
echo ""

echo -e "${YELLOW}Step 2: Run Setup Script${NC}"
echo ""
echo "  Execute:"
echo -e "  ${GREEN}./setup_cicd_runner.sh${NC}"
echo ""
echo "  The script will:"
echo "    ✓ Check prerequisites (Docker, disk space)"
echo "    ✓ Download GitHub Actions runner"
echo "    ✓ Configure for this repository"
echo "    ✓ Install as system service"
echo "    ✓ Start the runner"
echo ""

echo -e "${YELLOW}Step 3: Validate Setup${NC}"
echo ""
echo "  After setup completes, run:"
echo -e "  ${GREEN}./test_cicd_runner.sh${NC}"
echo ""
echo "  This validates:"
echo "    ✓ Runner installation"
echo "    ✓ Service status"
echo "    ✓ Docker functionality"
echo "    ✓ Repository integration"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Available Documentation${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  📖 Complete Guide:      CICD_RUNNER_SETUP_GUIDE.md"
echo "  📋 Quick Reference:     CICD_QUICK_REFERENCE.md"
echo "  📊 Setup Summary:       CICD_SETUP_SUMMARY.md"
echo "  🔧 CI/CD Analysis:      CI_CD_ANALYSIS.md"
echo "  📚 Runner Docs:         docs/RUNNER_SETUP.md"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  System Information${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Server:       $(hostname)"
echo "  Architecture: $(uname -m)"
echo "  OS:           $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "  Docker:       $(docker --version 2>/dev/null | cut -d' ' -f3 | tr -d ',' || echo 'Not found')"
echo "  Repository:   /home/barberb/ipfs_datasets_py"
echo ""

# Check if runner already exists
RUNNER_DIR="$HOME/actions-runner-ipfs_datasets_py"
if [ -d "$RUNNER_DIR" ]; then
    echo -e "${GREEN}  Status:       Runner directory exists${NC}"
    if systemctl list-units --type=service | grep -q "actions.runner.*ipfs_datasets_py"; then
        SERVICE_STATUS=$(systemctl is-active "$(systemctl list-units --type=service | grep 'actions.runner.*ipfs_datasets_py' | awk '{print $1}')" 2>/dev/null || echo "unknown")
        if [ "$SERVICE_STATUS" = "active" ]; then
            echo -e "${GREEN}  Runner:       Active and running ✓${NC}"
        else
            echo -e "${YELLOW}  Runner:       Installed but not running${NC}"
        fi
    else
        echo -e "${YELLOW}  Runner:       Directory exists but service not configured${NC}"
    fi
else
    echo -e "${BLUE}  Status:       Ready to install${NC}"
fi

echo ""

# Check GPU
if command -v nvidia-smi &> /dev/null 2>&1; then
    GPU_STATUS=$(nvidia-smi 2>&1)
    if echo "$GPU_STATUS" | grep -q "Driver/library version mismatch"; then
        echo -e "${YELLOW}  GPU:          Detected (driver mismatch - will run CPU-only)${NC}"
    elif echo "$GPU_STATUS" | grep -q "NVIDIA-SMI"; then
        GPU_COUNT=$(nvidia-smi --query-gpu=count --format=csv,noheader 2>/dev/null | head -1)
        echo -e "${GREEN}  GPU:          $GPU_COUNT GPU(s) available ✓${NC}"
    else
        echo -e "${YELLOW}  GPU:          Detected but not accessible${NC}"
    fi
else
    echo "  GPU:          Not detected (CPU-only mode)"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  What Happens After Setup${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  1. Runner appears on GitHub:"
echo -e "     ${BLUE}https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners${NC}"
echo ""
echo "  2. Workflows automatically use your runner:"
echo "     • docker-build-test.yml"
echo "     • self-hosted-runner.yml"
echo "     • runner-validation-clean.yml"
echo "     • And more..."
echo ""
echo "  3. You can trigger workflows by:"
echo "     • Pushing commits"
echo "     • Creating pull requests"
echo "     • Manual workflow dispatch"
echo "     • Using commit message tags like [test-runner]"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Ready to Begin?${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Check if already installed
if [ -d "$RUNNER_DIR" ] && systemctl list-units --type=service | grep -q "actions.runner.*ipfs_datasets_py"; then
    echo -e "${GREEN}Runner is already installed!${NC}"
    echo ""
    echo "To verify it's working:"
    echo -e "  ${GREEN}./test_cicd_runner.sh${NC}"
    echo ""
    echo "To reinstall:"
    echo -e "  ${GREEN}./setup_cicd_runner.sh${NC}"
    echo ""
else
    echo "To start setup, run:"
    echo ""
    echo -e "  ${GREEN}./setup_cicd_runner.sh${NC}"
    echo ""
fi

echo -e "${CYAN}For help, read:${NC} ${YELLOW}CICD_RUNNER_SETUP_GUIDE.md${NC}"
echo ""
