# GitHub Actions Self-Hosted Runner Setup Guide

This guide will help you set up self-hosted runners for building and testing Docker containers on different architectures.

## Why Use Self-Hosted Runners?

- **Native architecture builds**: Build directly on x86_64 or ARM64 without emulation
- **Faster builds**: No need for QEMU emulation overhead
- **Cost savings**: Use your own hardware instead of GitHub-hosted runners
- **Custom environment**: Install specific tools and dependencies

## Prerequisites

- A machine running Linux (Ubuntu 20.04+ recommended)
- Docker installed and running
- Sudo/root access for initial setup
- At least 2GB RAM and 10GB free disk space

## Quick Setup

### 1. Navigate to Repository Settings

Go to your GitHub repository:
```
https://github.com/YOUR_USERNAME/ipfs_datasets_py/settings/actions/runners
```

### 2. Add a New Runner

1. Click **"New self-hosted runner"**
2. Select your OS (Linux)
3. Select your architecture (X64 for x86_64, ARM64 for arm64)

### 3. Follow the Download Instructions

GitHub will provide commands like:

```bash
# Download
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.311.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz

# Extract
tar xzf ./actions-runner-linux-x64-2.311.0.tar.gz

# Configure
./config.sh --url https://github.com/YOUR_USERNAME/ipfs_datasets_py \
  --token YOUR_TOKEN

# Run
./run.sh
```

### 4. Add Appropriate Labels

During configuration, add these labels:
- For x86_64: `self-hosted`, `linux`, `x86_64`
- For ARM64: `self-hosted`, `linux`, `arm64`

## Installing as a Service (Recommended)

To run the runner as a background service:

```bash
cd actions-runner
sudo ./svc.sh install
sudo ./svc.sh start
```

Check status:
```bash
sudo ./svc.sh status
```

## Docker Setup

Ensure Docker is installed and the runner user has access:

```bash
# Install Docker (Ubuntu/Debian)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add runner user to docker group
sudo usermod -aG docker $USER

# Restart the runner service
sudo ./svc.sh restart
```

## Testing the Runner

After setup, you can test the runner by:

1. **Manual workflow dispatch**:
   - Go to Actions → Docker Build and Test → Run workflow
   - Select platform and click "Run workflow"

2. **Push a commit**:
   ```bash
   git commit --allow-empty -m "[test-runner] Testing self-hosted runner"
   git push
   ```

3. **Check the workflow**:
   - Go to the Actions tab
   - Look for your workflow run
   - Check if the self-hosted jobs ran successfully

## Multiple Runners Setup

### x86_64 Runner (Server/Desktop)

```bash
# On your x86_64 machine
cd ~
mkdir actions-runner-x86 && cd actions-runner-x86

# Download and configure for x86_64
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64-2.311.0.tar.gz
tar xzf actions-runner-linux-x64.tar.gz

# Configure with labels: self-hosted,linux,x86_64
./config.sh --url https://github.com/YOUR_USERNAME/ipfs_datasets_py \
  --token YOUR_TOKEN \
  --labels self-hosted,linux,x86_64

# Install as service
sudo ./svc.sh install
sudo ./svc.sh start
```

### ARM64 Runner (Raspberry Pi/ARM Server)

```bash
# On your ARM64 machine
cd ~
mkdir actions-runner-arm64 && cd actions-runner-arm64

# Download and configure for ARM64
curl -o actions-runner-linux-arm64.tar.gz -L \
  https://github.com/actions/runner/releases/latest/download/actions-runner-linux-arm64-2.311.0.tar.gz
tar xzf actions-runner-linux-arm64.tar.gz

# Configure with labels: self-hosted,linux,arm64
./config.sh --url https://github.com/YOUR_USERNAME/ipfs_datasets_py \
  --token YOUR_TOKEN \
  --labels self-hosted,linux,arm64

# Install as service
sudo ./svc.sh install
sudo ./svc.sh start
```

## Troubleshooting

### Runner Not Appearing in GitHub

```bash
# Check service status
sudo ./svc.sh status

# View logs
sudo journalctl -u actions.runner.* -f
```

### Docker Permission Denied

Docker permission issues are common with self-hosted runners. Use our automated fix:

```bash
# Quick fix - add user to docker group
sudo usermod -aG docker $(whoami)

# For runner services, identify the runner user first:
ps aux | grep Runner.Listener
# Then add that user to docker group:
sudo usermod -aG docker runner-user

# Restart runner service
sudo systemctl restart actions.runner.*

# Test access
docker ps
```

**Automated Solution:**
```bash
# Use our comprehensive fix script
sudo ./scripts/setup-runner-docker-permissions.sh

# Or run diagnostics first
sudo ./scripts/setup-runner-docker-permissions.sh --diagnostics
```

**Manual Service Fix:**
```bash
# Create systemd override for proper group inheritance
sudo mkdir -p /etc/systemd/system/actions.runner.*.service.d/
sudo tee /etc/systemd/system/actions.runner.*.service.d/docker.conf << EOF
[Service]
SupplementaryGroups=docker
EOF

sudo systemctl daemon-reload
sudo systemctl restart actions.runner.*
```

**Emergency Fix (less secure):**
```bash
# Temporary socket permission fix
sudo chmod 666 /var/run/docker.sock
```

For detailed solutions, see: `docs/DOCKER_PERMISSION_INFRASTRUCTURE_SOLUTIONS.md`

### Runner Offline

```bash
# Restart the service
cd ~/actions-runner
sudo ./svc.sh stop
sudo ./svc.sh start
```

### Clean Up Failed Builds

```bash
# Clean Docker system
docker system prune -af

# Clean old runner data
cd ~/actions-runner/_work
rm -rf *
```

## Security Considerations

1. **Isolate runners**: Run on dedicated machines or VMs
2. **Firewall rules**: Restrict network access
3. **Regular updates**: Keep runner software updated
4. **Monitor resources**: Watch CPU, memory, and disk usage
5. **Review logs**: Check for suspicious activity

## Resource Requirements

### Minimum (Testing)
- 2 CPU cores
- 2GB RAM
- 10GB disk space
- 10 Mbps network

### Recommended (Production)
- 4+ CPU cores
- 8GB+ RAM
- 50GB+ SSD storage
- 100+ Mbps network

## Monitoring

Monitor your runners:

```bash
# Check Docker disk usage
docker system df

# Check runner logs
sudo journalctl -u actions.runner.* --since "1 hour ago"

# Monitor system resources
htop  # or top
df -h
free -h
```

## Removing a Runner

```bash
cd ~/actions-runner

# Stop the service
sudo ./svc.sh stop
sudo ./svc.sh uninstall

# Remove the runner
./config.sh remove --token YOUR_TOKEN

# Clean up
cd ..
rm -rf actions-runner
```

## Additional Resources

- [GitHub Actions Self-Hosted Runners Documentation](https://docs.github.com/en/actions/hosting-your-own-runners)
- [Docker Installation Guide](https://docs.docker.com/engine/install/)
- [GitHub Actions Best Practices](https://docs.github.com/en/actions/learn-github-actions/best-practices-for-github-actions)

## Support

If you encounter issues:

1. Check the [GitHub Actions documentation](https://docs.github.com/en/actions)
2. Review runner logs: `sudo journalctl -u actions.runner.* -f`
3. Open an issue in this repository with:
   - Runner OS and architecture
   - Error messages from logs
   - Steps to reproduce

## Workflow Integration

The following workflows are configured to use self-hosted runners:

- `.github/workflows/docker-build-test.yml` - Docker build and test
- `.github/workflows/self-hosted-runner.yml` - Runner verification

These workflows will:
- ✅ Run on GitHub-hosted runners (always available)
- ✅ Run on self-hosted runners (if available)
- ⏭️ Skip gracefully if runners are offline

