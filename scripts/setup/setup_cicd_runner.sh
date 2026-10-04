#!/bin/bash
# Automated CI/CD Runner Setup for ipfs_datasets_py
# This script sets up a self-hosted GitHub Actions runner on this server

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
REPO_OWNER="endomorphosis"
REPO_NAME="ipfs_datasets_py"
RUNNER_VERSION="2.321.0"  # Latest stable version
RUNNER_DIR="$HOME/actions-runner-${REPO_NAME}"

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║   GitHub Actions Runner Setup - ipfs_datasets_py             ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Function to print section headers
print_section() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Function to print status messages
print_status() {
    echo -e "${BLUE}→${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check prerequisites
print_section "1. Checking Prerequisites"

# Check OS
print_status "Checking operating system..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    print_success "OS: $PRETTY_NAME"
else
    print_error "Cannot determine OS"
    exit 1
fi

# Check architecture
ARCH=$(uname -m)
print_status "Checking architecture..."
print_success "Architecture: $ARCH"

# Check Docker
print_status "Checking Docker..."
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version | cut -d' ' -f3 | tr -d ',')
    print_success "Docker: $DOCKER_VERSION"
    
    # Check if user can run docker without sudo
    if docker ps &> /dev/null; then
        print_success "Docker permissions: OK"
    else
        print_warning "Docker requires sudo. Adding user to docker group..."
        sudo usermod -aG docker $USER
        print_warning "You may need to log out and back in for group changes to take effect"
    fi
else
    print_error "Docker not found. Please install Docker first."
    echo "Run: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

# Check for GPU (optional)
print_status "Checking for GPU..."
if command -v nvidia-smi &> /dev/null; then
    GPU_COUNT=$(nvidia-smi --query-gpu=count --format=csv,noheader | head -1)
    GPU_NAMES=$(nvidia-smi --query-gpu=name --format=csv,noheader | paste -sd "," -)
    print_success "GPU(s) detected: $GPU_COUNT - $GPU_NAMES"
    HAS_GPU=true
    
    # Check Docker GPU access
    if docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &> /dev/null 2>&1; then
        print_success "Docker GPU access: OK"
    else
        print_warning "Docker cannot access GPU. nvidia-container-toolkit may need to be installed."
        HAS_GPU=false
    fi
else
    print_status "No GPU detected (this is fine for CPU-only tasks)"
    HAS_GPU=false
fi

# Check available disk space
print_status "Checking disk space..."
AVAILABLE_GB=$(df -BG . | tail -1 | awk '{print $4}' | tr -d 'G')
if [ "$AVAILABLE_GB" -gt 20 ]; then
    print_success "Disk space: ${AVAILABLE_GB}GB available"
else
    print_warning "Low disk space: ${AVAILABLE_GB}GB available (recommended: >20GB)"
fi

# Check if runner already exists
print_section "2. Checking Existing Runner"

if [ -d "$RUNNER_DIR" ]; then
    print_warning "Runner directory already exists: $RUNNER_DIR"
    echo ""
    read -p "Do you want to remove it and reinstall? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "Stopping existing runner service..."
        cd "$RUNNER_DIR"
        if [ -f "svc.sh" ]; then
            sudo ./svc.sh stop 2>/dev/null || true
            sudo ./svc.sh uninstall 2>/dev/null || true
        fi
        cd ~
        print_status "Removing old runner directory..."
        rm -rf "$RUNNER_DIR"
        print_success "Old runner removed"
    else
        print_error "Aborting installation"
        exit 1
    fi
fi

# Get GitHub token
print_section "3. GitHub Authentication"

echo ""
echo "You need a registration token from GitHub."
echo ""
echo -e "${CYAN}Steps to get your token:${NC}"
echo "  1. Go to: https://github.com/${REPO_OWNER}/${REPO_NAME}/settings/actions/runners/new"
echo "  2. Select OS: Linux"
echo "  3. Select Architecture: X64"
echo "  4. Copy the registration token from the configuration command"
echo ""
read -p "Enter your GitHub registration token: " GITHUB_TOKEN

if [ -z "$GITHUB_TOKEN" ]; then
    print_error "Token is required!"
    exit 1
fi

# Determine runner labels
print_section "4. Configuring Runner Labels"

LABELS="self-hosted,linux,$ARCH"

if [ "$HAS_GPU" = true ]; then
    LABELS="${LABELS},gpu,cuda"
    print_status "Adding GPU labels: gpu, cuda"
fi

print_success "Runner labels: $LABELS"

# Download and install runner
print_section "5. Installing GitHub Actions Runner"

print_status "Creating runner directory: $RUNNER_DIR"
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

print_status "Downloading runner v${RUNNER_VERSION}..."
RUNNER_ARCH="x64"
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    RUNNER_ARCH="arm64"
fi

RUNNER_FILE="actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_FILE}"

curl -o "$RUNNER_FILE" -L "$DOWNLOAD_URL"
print_success "Downloaded runner package"

print_status "Extracting runner..."
tar xzf "$RUNNER_FILE"
rm "$RUNNER_FILE"
print_success "Runner extracted"

# Configure runner
print_section "6. Configuring Runner"

RUNNER_NAME="runner-$(hostname)-${ARCH}"

print_status "Configuring runner with name: $RUNNER_NAME"
./config.sh \
    --url "https://github.com/${REPO_OWNER}/${REPO_NAME}" \
    --token "$GITHUB_TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "$LABELS" \
    --work "_work" \
    --unattended \
    --replace

print_success "Runner configured"

# Install as service
print_section "7. Installing Runner as System Service"

print_status "Installing runner service..."
sudo ./svc.sh install

print_status "Starting runner service..."
sudo ./svc.sh start

sleep 2

print_status "Checking runner status..."
sudo ./svc.sh status

# Summary
print_section "✅ Setup Complete!"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           GitHub Actions Runner Successfully Installed        ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Runner Details:${NC}"
echo "  • Name: $RUNNER_NAME"
echo "  • Labels: $LABELS"
echo "  • Location: $RUNNER_DIR"
echo "  • Repository: ${REPO_OWNER}/${REPO_NAME}"
echo ""
echo -e "${CYAN}Verify Installation:${NC}"
echo "  1. Check runner status:"
echo "     ${YELLOW}cd $RUNNER_DIR && sudo ./svc.sh status${NC}"
echo ""
echo "  2. View logs:"
echo "     ${YELLOW}sudo journalctl -u actions.runner.* -f${NC}"
echo ""
echo "  3. Verify on GitHub:"
echo "     ${YELLOW}https://github.com/${REPO_OWNER}/${REPO_NAME}/settings/actions/runners${NC}"
echo ""
echo -e "${CYAN}Test the Runner:${NC}"
echo "  ${YELLOW}cd /home/barberb/ipfs_datasets_py${NC}"
echo "  ${YELLOW}git commit --allow-empty -m '[test-runner] Testing self-hosted runner'${NC}"
echo "  ${YELLOW}git push${NC}"
echo ""
echo -e "${CYAN}Useful Commands:${NC}"
echo "  • Stop runner:     ${YELLOW}cd $RUNNER_DIR && sudo ./svc.sh stop${NC}"
echo "  • Start runner:    ${YELLOW}cd $RUNNER_DIR && sudo ./svc.sh start${NC}"
echo "  • Restart runner:  ${YELLOW}cd $RUNNER_DIR && sudo ./svc.sh restart${NC}"
echo "  • Uninstall:       ${YELLOW}cd $RUNNER_DIR && sudo ./svc.sh uninstall${NC}"
echo ""

if [ "$HAS_GPU" = true ]; then
    echo -e "${GREEN}🎮 GPU Support Enabled!${NC}"
    echo "  Your runner can execute GPU-accelerated workflows"
    echo ""
fi

print_success "Setup completed successfully!"
echo ""
