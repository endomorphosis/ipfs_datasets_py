# 🚀 Quick GitHub Self-Hosted Runner Setup

## Prerequisites
- Linux machine (Ubuntu 20.04+ recommended)
- Docker installed
- Sudo access

## Step 1: Get Runner Token

Go to your repository on GitHub:
```
https://github.com/YOUR_USERNAME/ipfs_datasets_py/settings/actions/runners/new
```

You'll see commands like this - **copy them and run on your machine**:

## Step 2: Download and Configure (x86_64)

```bash
# Create directory
mkdir -p ~/actions-runner && cd ~/actions-runner

# Download (GitHub will show the exact URL)
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz

# Extract
tar xzf actions-runner-linux-x64.tar.gz

# Configure with your token (GitHub will provide this)
./config.sh --url https://github.com/YOUR_USERNAME/ipfs_datasets_py \
  --token YOUR_REGISTRATION_TOKEN \
  --labels self-hosted,linux,x86_64 \
  --name my-x86-runner

# Install as service
sudo ./svc.sh install

# Start the service
sudo ./svc.sh start

# Check status
sudo ./svc.sh status
```

## Step 3: For ARM64 (Raspberry Pi, etc.)

```bash
# Same as above but download ARM64 version
curl -o actions-runner-linux-arm64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-arm64-2.311.0.tar.gz

# Use labels: self-hosted,linux,arm64
./config.sh --url https://github.com/YOUR_USERNAME/ipfs_datasets_py \
  --token YOUR_REGISTRATION_TOKEN \
  --labels self-hosted,linux,arm64 \
  --name my-arm-runner
```

## Step 4: Ensure Docker Access

```bash
# Add runner user to docker group
sudo usermod -aG docker $(whoami)

# Restart the runner
cd ~/actions-runner
sudo ./svc.sh restart
```

## Step 5: Verify

1. Check GitHub Settings → Actions → Runners
2. Your runner should show as "Idle" (green dot)
3. Push a commit to trigger a workflow:

```bash
cd ~/ipfs_datasets_py
git add .
git commit -m "[test-runner] Testing self-hosted runner setup"
git push
```

## Troubleshooting

### Runner shows offline
```bash
sudo systemctl status actions.runner.*
sudo journalctl -u actions.runner.* -f
```

### Docker permission denied
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### View runner logs
```bash
cd ~/actions-runner
sudo ./svc.sh status
cat _diag/Runner_*.log
```

## Quick Commands

```bash
# Start runner
cd ~/actions-runner && sudo ./svc.sh start

# Stop runner
cd ~/actions-runner && sudo ./svc.sh stop

# Restart runner
cd ~/actions-runner && sudo ./svc.sh restart

# Check status
cd ~/actions-runner && sudo ./svc.sh status

# Remove runner
cd ~/actions-runner
sudo ./svc.sh stop
sudo ./svc.sh uninstall
./config.sh remove --token YOUR_TOKEN
```

## Security Tips

1. Use a dedicated machine or VM for runners
2. Keep the system updated: `sudo apt update && sudo apt upgrade`
3. Don't share runners between untrusted repositories
4. Monitor disk space: `df -h`
5. Check runner logs regularly

## What Happens Next?

Once your runner is set up:
- ✅ GitHub Actions will automatically use it for jobs with matching labels
- ✅ Docker builds will run natively (faster than QEMU)
- ✅ Tests will run on your actual hardware
- ✅ You'll see runner activity in the Actions tab

## Complete Documentation

For more details, see:
- [docs/RUNNER_SETUP.md](guides/deployment/runner_setup.md) - Full guide
- [DOCKER_GITHUB_ACTIONS_SETUP.md](./DOCKER_GITHUB_ACTIONS_SETUP.md) - Docker + Actions overview

---

**Need help?** Open an issue or check the runner logs!
