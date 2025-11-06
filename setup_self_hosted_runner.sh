#!/bin/bash
# Setup script for GitHub Actions self-hosted runner
# This script sets up a self-hosted runner for the ipfs_datasets_py repository

set -e

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║         GitHub Actions Self-Hosted Runner Setup          ║"
echo "║                  ipfs_datasets_py                         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
RUNNER_DIR="/home/actions-runner"
REPO_OWNER="endomorphosis"
REPO_NAME="ipfs_datasets_py"
RUNNER_NAME="$(hostname)-$(date +%s)"
RUNNER_LABELS="self-hosted,x86_64,linux"

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo -e "${RED}❌ This script should not be run as root${NC}"
   echo "Please run as a regular user with sudo privileges"
   exit 1
fi

# System information
echo -e "${BLUE}📋 System Information:${NC}"
echo "- Architecture: $(uname -m)"
echo "- OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "- CPU Cores: $(nproc)"
echo "- Memory: $(free -h | grep Mem | awk '{print $2}')"
echo "- Disk Space: $(df -h / | tail -1 | awk '{print $4}') available"
echo ""

# Check dependencies
echo -e "${BLUE}📋 Checking dependencies...${NC}"

# Check if curl is available
if ! command -v curl &> /dev/null; then
    echo -e "${YELLOW}⚠️  Installing curl...${NC}"
    sudo apt-get update && sudo apt-get install -y curl
fi

# Check if jq is available
if ! command -v jq &> /dev/null; then
    echo -e "${YELLOW}⚠️  Installing jq...${NC}"
    sudo apt-get update && sudo apt-get install -y jq
fi

# Check Docker
if command -v docker &> /dev/null; then
    echo -e "${GREEN}✅ Docker is available${NC}"
    docker --version
else
    echo -e "${RED}❌ Docker is not installed${NC}"
    echo "Please install Docker first: https://docs.docker.com/install/"
    exit 1
fi

# Check GitHub CLI
if command -v gh &> /dev/null; then
    echo -e "${GREEN}✅ GitHub CLI is available${NC}"
    gh --version
    
    # Check if authenticated
    if gh auth status &> /dev/null; then
        echo -e "${GREEN}✅ GitHub CLI is authenticated${NC}"
    else
        echo -e "${YELLOW}⚠️  GitHub CLI is not authenticated${NC}"
        echo "Please run: gh auth login"
        exit 1
    fi
else
    echo -e "${RED}❌ GitHub CLI is not installed${NC}"
    echo "Installing GitHub CLI..."
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt-get update && sudo apt-get install -y gh
    echo "Please run: gh auth login"
    exit 1
fi

echo ""

# Get registration token
echo -e "${BLUE}🔐 Getting registration token from GitHub...${NC}"
REGISTRATION_TOKEN=$(gh api --method POST -H "Accept: application/vnd.github.v3+json" "/repos/${REPO_OWNER}/${REPO_NAME}/actions/runners/registration-token" --jq .token)

if [[ -z "$REGISTRATION_TOKEN" ]]; then
    echo -e "${RED}❌ Failed to get registration token${NC}"
    echo "Make sure you have admin access to the repository"
    exit 1
fi

echo -e "${GREEN}✅ Registration token obtained${NC}"

# Create runner directory
echo -e "${BLUE}📁 Creating runner directory...${NC}"
sudo mkdir -p "$RUNNER_DIR"
sudo chown $(whoami):$(whoami) "$RUNNER_DIR"
cd "$RUNNER_DIR"

# Download GitHub Actions runner
echo -e "${BLUE}📥 Downloading GitHub Actions runner...${NC}"
RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/v//')
RUNNER_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"

echo "Downloading runner version: ${RUNNER_VERSION}"
curl -o actions-runner-linux-x64.tar.gz -L "$RUNNER_URL"

# Extract runner
echo -e "${BLUE}📦 Extracting runner...${NC}"
tar xzf ./actions-runner-linux-x64.tar.gz
rm actions-runner-linux-x64.tar.gz

# Install dependencies
echo -e "${BLUE}📋 Installing runner dependencies...${NC}"
sudo ./bin/installdependencies.sh

# Configure runner
echo -e "${BLUE}⚙️  Configuring runner...${NC}"
./config.sh --url "https://github.com/${REPO_OWNER}/${REPO_NAME}" \
    --token "$REGISTRATION_TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "$RUNNER_LABELS" \
    --work "_work" \
    --unattended

# Create systemd service
echo -e "${BLUE}🔧 Creating systemd service...${NC}"
sudo ./svc.sh install
sudo ./svc.sh start

# Check service status
echo -e "${BLUE}📊 Checking service status...${NC}"
sudo systemctl status actions.runner.${REPO_OWNER}-${REPO_NAME}.${RUNNER_NAME}.service --no-pager

echo ""
echo -e "${GREEN}✅ GitHub Actions runner setup completed!${NC}"
echo ""
echo "Runner Details:"
echo "- Name: $RUNNER_NAME"
echo "- Labels: $RUNNER_LABELS"
echo "- Directory: $RUNNER_DIR"
echo "- Repository: ${REPO_OWNER}/${REPO_NAME}"
echo ""
echo "The runner is now running as a systemd service and will start automatically on boot."
echo ""
echo "To check runner status:"
echo "  sudo systemctl status actions.runner.${REPO_OWNER}-${REPO_NAME}.${RUNNER_NAME}.service"
echo ""
echo "To stop the runner:"
echo "  sudo systemctl stop actions.runner.${REPO_OWNER}-${REPO_NAME}.${RUNNER_NAME}.service"
echo ""
echo "To remove the runner:"
echo "  cd $RUNNER_DIR && ./config.sh remove --token [NEW_TOKEN]"
echo ""
echo "You can now use this runner in your GitHub Actions workflows with:"
echo "  runs-on: [self-hosted, x86_64, linux]"