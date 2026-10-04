#!/bin/bash
# Quick setup script for GPU-enabled self-hosted runner

set -e

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   Setting Up GPU-Enabled Self-Hosted GitHub Runner       ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check if running on GPU machine
echo -e "${BLUE}📋 Checking GPU availability...${NC}"
if ! nvidia-smi > /dev/null 2>&1; then
    echo -e "${RED}❌ NVIDIA GPUs not detected!${NC}"
    echo "This script should be run on a machine with NVIDIA GPUs."
    exit 1
fi

echo -e "${GREEN}✅ GPU(s) detected:${NC}"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo ""

# Check Docker GPU access
echo -e "${BLUE}📋 Checking Docker GPU access...${NC}"
if docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Docker can access GPUs${NC}"
else
    echo -e "${YELLOW}⚠️  Docker cannot access GPUs${NC}"
    echo "You may need to install nvidia-container-toolkit:"
    echo "  See: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

# Get GitHub token
echo -e "${BLUE}📋 GitHub Runner Setup${NC}"
echo ""
echo "You need a registration token from GitHub."
echo "Get it from: https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners/new"
echo ""
read -p "Enter your GitHub registration token: " GITHUB_TOKEN

if [ -z "$GITHUB_TOKEN" ]; then
    echo -e "${RED}❌ Token is required!${NC}"
    exit 1
fi

# Create runner directory
RUNNER_DIR="$HOME/actions-runner-gpu"
echo ""
echo -e "${BLUE}📦 Creating runner directory: $RUNNER_DIR${NC}"
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

# Download runner
RUNNER_VERSION="2.311.0"
echo -e "${BLUE}📥 Downloading GitHub Actions runner v${RUNNER_VERSION}...${NC}"
curl -o actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz -L \
    https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz

# Extract
echo -e "${BLUE}📦 Extracting...${NC}"
tar xzf actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz
rm actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz

# Configure
echo ""
echo -e "${BLUE}⚙️  Configuring runner...${NC}"
./config.sh \
    --url https://github.com/endomorphosis/ipfs_datasets_py \
    --token "$GITHUB_TOKEN" \
    --name "gpu-workstation-$(hostname)" \
    --labels "self-hosted,linux,x64,gpu,cuda,rtx3090" \
    --work "_work" \
    --unattended

# Install as service
echo ""
echo -e "${BLUE}🔧 Installing as system service...${NC}"
sudo ./svc.sh install

# Start service
echo -e "${BLUE}🚀 Starting runner service...${NC}"
sudo ./svc.sh start

# Check status
sleep 2
echo ""
echo -e "${BLUE}📊 Runner status:${NC}"
sudo ./svc.sh status

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                    ✅ Setup Complete!                      ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}Your GPU runner is now online!${NC}"
echo ""
echo "📍 Runner location: $RUNNER_DIR"
echo "📋 Check status: cd $RUNNER_DIR && sudo ./svc.sh status"
echo "📝 View logs: sudo journalctl -u actions.runner.* -f"
echo ""
echo "🎮 GPUs Available:"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
echo ""
echo "🔗 Verify on GitHub:"
echo "   https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners"
echo ""
echo "🧪 Test the runner:"
echo "   git commit --allow-empty -m '[test-gpu-runner] Testing GPU runner'"
echo "   git push"
echo ""
