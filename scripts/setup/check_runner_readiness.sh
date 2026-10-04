#!/bin/bash
# Quick check script to verify system readiness for GitHub Actions runner

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║        GitHub Actions Runner Readiness Check             ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SUCCESS=0
WARNINGS=0
ERRORS=0

check_command() {
    if command -v "$1" &> /dev/null; then
        echo -e "${GREEN}✅ $1 is installed${NC}"
        if [[ "$1" == "docker" ]]; then
            echo "   $(docker --version)"
        elif [[ "$1" == "gh" ]]; then
            echo "   $(gh --version)"
        fi
        ((SUCCESS++))
    else
        echo -e "${RED}❌ $1 is not installed${NC}"
        ((ERRORS++))
    fi
}

check_service() {
    if systemctl is-active --quiet "$1"; then
        echo -e "${GREEN}✅ $1 service is running${NC}"
        ((SUCCESS++))
    else
        echo -e "${YELLOW}⚠️  $1 service is not running${NC}"
        ((WARNINGS++))
    fi
}

echo -e "${BLUE}📋 System Information:${NC}"
echo "- Hostname: $(hostname)"
echo "- Architecture: $(uname -m)"
echo "- OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "- CPU Cores: $(nproc)"
echo "- Memory: $(free -h | grep Mem | awk '{print $2}')"
echo "- Disk Space: $(df -h / | tail -1 | awk '{print $4}') available"
echo ""

echo -e "${BLUE}🔧 Required Tools:${NC}"
check_command "curl"
check_command "jq"
check_command "docker"
check_command "gh"
echo ""

echo -e "${BLUE}🔐 GitHub Authentication:${NC}"
if gh auth status &> /dev/null; then
    echo -e "${GREEN}✅ GitHub CLI is authenticated${NC}"
    echo "   Authenticated as: $(gh api user --jq .login)"
    ((SUCCESS++))
else
    echo -e "${RED}❌ GitHub CLI is not authenticated${NC}"
    echo "   Run: gh auth login"
    ((ERRORS++))
fi
echo ""

echo -e "${BLUE}🐳 Docker Status:${NC}"
check_service "docker"
if docker info &> /dev/null; then
    echo -e "${GREEN}✅ Docker is accessible${NC}"
    ((SUCCESS++))
else
    echo -e "${RED}❌ Docker is not accessible${NC}"
    echo "   You may need to add your user to the docker group:"
    echo "   sudo usermod -aG docker \$USER"
    echo "   Then log out and back in"
    ((ERRORS++))
fi
echo ""

echo -e "${BLUE}📁 Existing Runners:${NC}"
if [[ -d "/home/actions-runner" ]]; then
    echo -e "${YELLOW}⚠️  Runner directory exists: /home/actions-runner${NC}"
    if systemctl list-units --type=service --state=running | grep -q "actions.runner"; then
        echo -e "${GREEN}✅ GitHub Actions runner service is running${NC}"
        systemctl list-units --type=service --state=running | grep "actions.runner" | while read line; do
            echo "   $line"
        done
        ((SUCCESS++))
    else
        echo -e "${YELLOW}⚠️  Runner directory exists but service not running${NC}"
        ((WARNINGS++))
    fi
else
    echo -e "${BLUE}ℹ️  No existing runner directory found${NC}"
fi
echo ""

echo -e "${BLUE}🌐 Network Connectivity:${NC}"
if curl -s --max-time 5 https://github.com > /dev/null; then
    echo -e "${GREEN}✅ Can reach GitHub.com${NC}"
    ((SUCCESS++))
else
    echo -e "${RED}❌ Cannot reach GitHub.com${NC}"
    ((ERRORS++))
fi

if curl -s --max-time 5 https://api.github.com/repos/endomorphosis/ipfs_datasets_py > /dev/null; then
    echo -e "${GREEN}✅ Can reach repository API${NC}"
    ((SUCCESS++))
else
    echo -e "${RED}❌ Cannot reach repository API${NC}"
    ((ERRORS++))
fi
echo ""

echo "═══════════════════════════════════════════════════════════"
echo -e "📊 ${BLUE}Summary:${NC}"
echo -e "   ${GREEN}✅ Passed: $SUCCESS${NC}"
echo -e "   ${YELLOW}⚠️  Warnings: $WARNINGS${NC}"
echo -e "   ${RED}❌ Errors: $ERRORS${NC}"
echo ""

if [[ $ERRORS -eq 0 ]]; then
    echo -e "${GREEN}🎉 System is ready for GitHub Actions runner setup!${NC}"
    echo "Run: ./setup_self_hosted_runner.sh"
else
    echo -e "${RED}🚫 Please fix the errors above before proceeding.${NC}"
    if [[ $ERRORS -eq 1 ]] && ! gh auth status &> /dev/null; then
        echo ""
        echo -e "${YELLOW}💡 Quick fix: Run 'gh auth login' to authenticate${NC}"
    fi
fi
echo ""