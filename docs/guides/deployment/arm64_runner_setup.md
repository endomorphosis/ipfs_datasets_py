# ARM64 Self-Hosted Runner Setup Guide

This guide provides step-by-step instructions for setting up ARM64 self-hosted GitHub Actions runners for the IPFS Datasets project.

## Overview

ARM64 self-hosted runners enable:
- Multi-architecture testing and validation
- ARM64-specific performance testing
- Docker builds for ARM64 platforms
- Complete CI/CD coverage across architectures

## Prerequisites

### Hardware Requirements
- ARM64-based system (e.g., Raspberry Pi 4, ARM64 server, Apple Silicon Mac, AWS Graviton)
- **Minimum**: 4GB RAM, 2 CPU cores, 20GB storage
- **Recommended**: 8GB+ RAM, 4+ CPU cores, 50GB+ storage
- Network connectivity to GitHub

### Software Requirements
- **Operating System**: Ubuntu 20.04+ (ARM64), macOS (Apple Silicon), or other ARM64 Linux distribution
- **Docker**: Latest version with ARM64 support
- **Python**: 3.10, 3.11, or 3.12
- **Git**: Latest version
- **curl**: For health checks and testing

## Setup Instructions

### 1. System Preparation

#### Ubuntu/Debian ARM64
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y curl wget git python3 python3-pip python3-venv
sudo apt install -y build-essential libssl-dev libffi-dev

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

#### macOS (Apple Silicon)
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required packages
brew install python@3.12 git curl

# Install Docker Desktop for Mac (ARM64 version)
# Download from: https://docs.docker.com/desktop/mac/install/
```

### 2. Create Runner User (Linux only)
```bash
# Create dedicated user for GitHub Actions runner
sudo useradd -m -s /bin/bash github-runner
sudo usermod -aG docker github-runner
sudo su - github-runner
```

### 3. Register Self-Hosted Runner

1. **Navigate to Repository Settings**:
   - Go to `https://github.com/endomorphosis/ipfs_datasets_py`
   - Click **Settings** → **Actions** → **Runners**
   - Click **New self-hosted runner**

2. **Select ARM64 Configuration**:
   - **Operating System**: Linux (or macOS)
   - **Architecture**: ARM64

3. **Download and Configure Runner**:
```bash
# Create runner directory
mkdir actions-runner && cd actions-runner

# Download the runner (replace with actual download URL from GitHub)
curl -o actions-runner-linux-arm64-2.311.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-arm64-2.311.0.tar.gz

# Validate the hash (optional but recommended)
echo "476c5d770c7b2b4b9b6f36e6ba1df90c4e3b4d2e3b8b4e7b9b4e7b9b4e7b9b4e  actions-runner-linux-arm64-2.311.0.tar.gz" | shasum -a 256 -c

# Extract the installer
tar xzf ./actions-runner-linux-arm64-2.311.0.tar.gz
```

4. **Configure the Runner**:
```bash
# Configure the runner (use the token from GitHub)
./config.sh --url https://github.com/endomorphosis/ipfs_datasets_py --token <YOUR_REGISTRATION_TOKEN>

# When prompted, configure:
# - Runner name: arm64-runner-01 (or similar)
# - Runner group: Default
# - Labels: self-hosted,linux,arm64 (or self-hosted,macOS,arm64)
# - Work folder: _work (default)
```

### 4. Install Service (Linux)
```bash
# Install the service
sudo ./svc.sh install

# Start the service
sudo ./svc.sh start

# Check service status
sudo ./svc.sh status
```

### 5. Verify Installation
```bash
# Test Docker functionality
docker run --rm hello-world

# Test Python
python3 --version
python3 -c "import platform; print(f'Platform: {platform.platform()}, Machine: {platform.machine()}')"

# Test system resources
echo "CPU Cores: $(nproc)"
echo "Memory: $(free -h | grep Mem | awk '{print $2}')"
echo "Disk: $(df -h / | tail -1 | awk '{print $4}') available"
```

## Configuration Files

### Runner Environment Variables
Create `/home/github-runner/.env`:
```bash
# Python configuration
PYTHON_VERSION=3.12
PATH="/usr/bin:/usr/local/bin:$PATH"

# Docker configuration
DOCKER_BUILDKIT=1
COMPOSE_DOCKER_CLI_BUILD=1

# MCP Dashboard configuration
MCP_DASHBOARD_HOST=127.0.0.1
MCP_DASHBOARD_PORT=8899

# Test configuration
PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright
```

### System Service Configuration
Create `/etc/systemd/system/github-runner.service`:
```ini
[Unit]
Description=GitHub Actions Runner (ARM64)
After=network.target

[Service]
Type=simple
User=github-runner
WorkingDirectory=/home/github-runner/actions-runner
ExecStart=/home/github-runner/actions-runner/run.sh
Restart=always
RestartSec=5
Environment=RUNNER_ALLOW_RUNASROOT=false

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable github-runner
sudo systemctl start github-runner
sudo systemctl status github-runner
```

## Testing the Runner

### 1. Trigger ARM64 Workflow
Push a commit with `[test-arm64]` in the commit message, or manually trigger the "ARM64 Self-Hosted Runner" workflow.

### 2. Monitor Runner Activity
```bash
# Check runner logs
sudo journalctl -u github-runner -f

# Check runner directory
cd /home/github-runner/actions-runner
tail -f _diag/Runner_*.log
```

### 3. Validate ARM64 Functionality
The ARM64 runner workflow will test:
- System information and performance
- MCP Dashboard functionality
- Docker builds for ARM64
- Integration tests

## Troubleshooting

### Common Issues

#### Runner Not Appearing Online
```bash
# Check service status
sudo systemctl status github-runner

# Restart service
sudo systemctl restart github-runner

# Check runner configuration
cd /home/github-runner/actions-runner
./config.sh --check
```

#### Docker Permission Issues
```bash
# Add user to docker group
sudo usermod -aG docker github-runner

# Restart Docker service
sudo systemctl restart docker

# Test Docker access
docker run --rm hello-world
```

#### Python/Package Installation Issues
```bash
# Update pip
python3 -m pip install --upgrade pip

# Install in user directory
python3 -m pip install --user package_name

# Use virtual environment
python3 -m venv venv
source venv/bin/activate
pip install package_name
```

#### Performance Issues
```bash
# Check system resources
htop
free -h
df -h

# Monitor runner resource usage
ps aux | grep Runner
```

### Log Locations
- **Runner logs**: `/home/github-runner/actions-runner/_diag/`
- **System logs**: `sudo journalctl -u github-runner`
- **Docker logs**: `sudo journalctl -u docker`

## Maintenance

### Regular Updates
```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Update runner (when new versions available)
cd /home/github-runner/actions-runner
sudo ./svc.sh stop
./config.sh remove --token <REMOVAL_TOKEN>
# Download and configure new version
sudo ./svc.sh install
sudo ./svc.sh start
```

### Monitoring
Set up monitoring for:
- Runner availability
- System resources (CPU, memory, disk)
- Docker daemon status
- Network connectivity

### Backup
Important files to backup:
- `/home/github-runner/actions-runner/.runner`
- `/home/github-runner/actions-runner/.credentials`
- Custom configuration files

## Security Considerations

1. **Network Security**:
   - Ensure runner has secure network access
   - Consider firewall rules if needed
   - Monitor network traffic

2. **Access Control**:
   - Use dedicated `github-runner` user
   - Limit sudo access
   - Regular security updates

3. **Secrets Management**:
   - Never store secrets in runner configuration
   - Use GitHub encrypted secrets
   - Rotate registration tokens regularly

## Multi-Runner Setup

For high availability, consider setting up multiple ARM64 runners:

1. **Load Balancing**: GitHub automatically distributes jobs
2. **Redundancy**: Multiple runners prevent single points of failure
3. **Performance**: Parallel job execution

Example runner names:
- `arm64-runner-01`
- `arm64-runner-02` 
- `arm64-runner-03`

## Validation Checklist

- [ ] Runner appears online in GitHub repository settings
- [ ] ARM64 architecture correctly detected (`uname -m` shows `aarch64`)
- [ ] Docker functionality working (`docker run hello-world`)
- [ ] Python 3.10+ installed and accessible
- [ ] MCP Dashboard can start and respond
- [ ] Integration tests pass
- [ ] Service auto-starts on boot
- [ ] Logs are accessible and informative

## Support

For issues specific to this setup:
1. Check runner logs in `_diag/` directory
2. Review GitHub Actions workflow runs
3. Test components individually (Docker, Python, MCP Dashboard)
4. Check GitHub documentation for runner troubleshooting

For ARM64-specific issues:
1. Verify architecture compatibility of all dependencies
2. Check for ARM64-specific Docker images
3. Monitor memory usage (ARM64 systems often have less RAM)
4. Test performance compared to x86_64 runners