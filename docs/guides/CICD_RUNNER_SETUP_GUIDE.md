# CI/CD Runner Setup Guide for ipfs_datasets_py

This guide will help you set up a self-hosted GitHub Actions runner on your x86_64 server to enable continuous integration and continuous deployment (CI/CD) for the ipfs_datasets_py repository.

## 🎯 Overview

### What This Does

Setting up a self-hosted runner allows you to:
- Run GitHub Actions workflows on your own hardware
- Execute tests and builds with your specific environment (CPU/GPU)
- Avoid GitHub-hosted runner limitations (time, resources)
- Test on the exact same architecture as your production environment
- Enable GPU-accelerated testing if available

### Architecture Support

This server is **x86_64** running Ubuntu 24.04.3 LTS. The runner will be configured with appropriate labels for this architecture.

## 🚀 Quick Start (Recommended)

### One-Command Setup

We've created an automated setup script that handles everything:

```bash
cd /home/barberb/ipfs_datasets_py
./setup_cicd_runner.sh
```

This script will:
1. ✅ Check prerequisites (Docker, disk space, GPU if available)
2. ✅ Download the GitHub Actions runner
3. ✅ Configure it for this repository
4. ✅ Install it as a system service
5. ✅ Start the runner automatically

### What You'll Need

Before running the script, you need a **GitHub registration token**:

1. Go to: https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners/new
2. Select:
   - **OS**: Linux
   - **Architecture**: X64
3. Copy the token from the configuration command (it looks like `XXXXXXXXXXXXXXXXXXXXXXXXXXXXX`)

The script will prompt you for this token.

## 📋 Manual Setup (Alternative)

If you prefer to set up manually or need to customize the installation:

### Step 1: Prepare the Environment

```bash
# Ensure Docker is installed
docker --version

# Ensure your user can run Docker without sudo
docker ps

# If the above fails, add yourself to docker group:
sudo usermod -aG docker $USER
# Then log out and back in
```

### Step 2: Download the Runner

```bash
# Create runner directory
mkdir -p ~/actions-runner-ipfs_datasets_py
cd ~/actions-runner-ipfs_datasets_py

# Download runner (latest version)
curl -o actions-runner-linux-x64-2.321.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-x64-2.321.0.tar.gz

# Extract
tar xzf actions-runner-linux-x64-2.321.0.tar.gz
```

### Step 3: Configure the Runner

```bash
# Get your token from GitHub (see Quick Start section)
GITHUB_TOKEN="YOUR_TOKEN_HERE"

# Configure with appropriate labels
./config.sh \
  --url https://github.com/endomorphosis/ipfs_datasets_py \
  --token "$GITHUB_TOKEN" \
  --name "runner-$(hostname)-x86_64" \
  --labels "self-hosted,linux,x86_64" \
  --work "_work" \
  --unattended \
  --replace
```

**Note**: If you have GPU available, add these labels: `--labels "self-hosted,linux,x86_64,gpu,cuda"`

### Step 4: Install as a Service

```bash
# Install the service
sudo ./svc.sh install

# Start the service
sudo ./svc.sh start

# Check status
sudo ./svc.sh status
```

## 🎮 GPU Support (Optional)

### Checking for GPU

```bash
# Check if NVIDIA GPU is available
nvidia-smi

# Check Docker GPU access
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

### Installing GPU Support

If you have an NVIDIA GPU but Docker can't access it:

```bash
# Install nvidia-container-toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# Test again
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

## ✅ Verification

### 1. Check Runner Status

```bash
cd ~/actions-runner-ipfs_datasets_py
sudo ./svc.sh status
```

Expected output:
```
● actions.runner.endomorphosis-ipfs_datasets_py.runner-<hostname>-x86_64.service - GitHub Actions Runner (...)
   Loaded: loaded
   Active: active (running)
```

### 2. Check on GitHub

Visit: https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners

You should see your runner listed as **Idle** with a green status indicator.

### 3. Test with a Workflow

```bash
cd /home/barberb/ipfs_datasets_py

# Create a test commit
git commit --allow-empty -m "[test-runner] Testing self-hosted runner"
git push

# Watch the Actions tab on GitHub
```

Visit: https://github.com/endomorphosis/ipfs_datasets_py/actions

You should see your workflow running on the self-hosted runner.

## 🔍 Understanding the Workflows

### Available Workflows

The repository has several CI/CD workflows configured:

1. **`docker-build-test.yml`** - Builds and tests Docker images
   - Runs on both GitHub-hosted and self-hosted runners
   - Tests multi-architecture builds (x86_64, ARM64)

2. **`runner-validation-clean.yml`** - Validates runner health
   - Tests system capabilities
   - Runs comprehensive validation
   - Scheduled daily

3. **`gpu-tests.yml`** - GPU-specific tests (if GPU available)
   - Tests GPU accessibility
   - Runs ML/AI workloads
   - Validates CUDA environment

4. **`self-hosted-runner.yml`** - Runner verification
   - Quick smoke test
   - Triggered by `[test-runner]` in commit message

### Workflow Triggers

Workflows can be triggered by:
- **Push** to main branch
- **Pull request** creation/update
- **Manual dispatch** (Actions tab → Run workflow)
- **Scheduled** (cron) - some workflows
- **Commit message tags** (e.g., `[test-runner]`)

## 🛠 Management Commands

### Service Management

```bash
cd ~/actions-runner-ipfs_datasets_py

# Check status
sudo ./svc.sh status

# Stop the runner
sudo ./svc.sh stop

# Start the runner
sudo ./svc.sh start

# Restart the runner
sudo ./svc.sh restart

# View logs
sudo journalctl -u actions.runner.* -f
```

### Updating the Runner

```bash
cd ~/actions-runner-ipfs_datasets_py

# Stop the service
sudo ./svc.sh stop

# The runner will auto-update when it starts
# Or manually update:
sudo ./svc.sh start
```

### Removing the Runner

```bash
cd ~/actions-runner-ipfs_datasets_py

# Stop and uninstall service
sudo ./svc.sh stop
sudo ./svc.sh uninstall

# Remove configuration
./config.sh remove --token YOUR_GITHUB_TOKEN

# Remove directory
cd ~
rm -rf ~/actions-runner-ipfs_datasets_py
```

## 🔒 Security Considerations

### Runner Security

- The runner runs as your user account
- It has access to Docker (and GPU if available)
- It can execute arbitrary code from workflows
- Only use on trusted repositories

### Best Practices

1. **Dedicated Machine**: If possible, use a dedicated machine for runners
2. **Regular Updates**: Keep the runner software updated
3. **Monitor Resources**: Watch CPU, memory, and disk usage
4. **Review Workflows**: Check workflow files before they run
5. **Network Security**: Ensure proper firewall rules

### Repository Settings

Restrict who can run workflows on self-hosted runners:

1. Go to: Settings → Actions → General
2. Under "Fork pull request workflows from outside collaborators"
3. Select "Require approval for all outside collaborators"

## 🐛 Troubleshooting

### Runner Not Appearing on GitHub

```bash
# Check if service is running
sudo ./svc.sh status

# Check logs for errors
sudo journalctl -u actions.runner.* -n 100

# Verify network connectivity
curl -I https://github.com

# Try reconfiguring
cd ~/actions-runner-ipfs_datasets_py
./config.sh remove --token YOUR_TOKEN
./config.sh --url https://github.com/endomorphosis/ipfs_datasets_py --token NEW_TOKEN ...
```

### Docker Permission Denied

```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Apply group changes (logout/login or use newgrp)
newgrp docker

# Test
docker ps
```

### Runner Goes Offline

```bash
# Restart the service
cd ~/actions-runner-ipfs_datasets_py
sudo ./svc.sh restart

# Check system resources
df -h /
free -h
top
```

### Workflow Failures

```bash
# Check runner logs during workflow execution
sudo journalctl -u actions.runner.* -f

# Clean up Docker resources
docker system prune -af

# Clean up work directory
cd ~/actions-runner-ipfs_datasets_py/_work
rm -rf *
```

### GPU Not Detected in Workflows

```bash
# Verify GPU access from runner
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi

# Check nvidia-container-toolkit
dpkg -l | grep nvidia-container-toolkit

# Restart Docker
sudo systemctl restart docker
```

## 📊 Monitoring

### Resource Usage

```bash
# Check runner resource usage
ps aux | grep Runner.Listener

# Monitor Docker containers
docker stats

# Check disk space
df -h ~/actions-runner-ipfs_datasets_py/_work/

# Monitor system load
htop  # or top
```

### Workflow History

View workflow runs and logs:
- https://github.com/endomorphosis/ipfs_datasets_py/actions

### Runner Activity

View runner activity:
- https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners

## 📚 Additional Resources

### Documentation Files

- `docs/RUNNER_SETUP.md` - Comprehensive runner setup guide
- `DOCKER_GITHUB_ACTIONS_SETUP.md` - Docker and GitHub Actions overview
- `CI_CD_ANALYSIS.md` - Analysis of the CI/CD setup
- `COMPLETE_SETUP_SUMMARY.md` - Full setup summary

### Scripts

- `setup_cicd_runner.sh` - Automated setup script ⭐
- `comprehensive_runner_validation.py` - Runner validation suite
- `test_docker_x86.sh` - Docker testing script

### GitHub Documentation

- [Self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [GitHub Actions](https://docs.github.com/en/actions)
- [Workflow syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)

## 🎉 Next Steps

After setting up the runner:

1. **Test the setup**: Push a test commit with `[test-runner]` tag
2. **Monitor workflows**: Watch the Actions tab for successful runs
3. **Review results**: Check the workflow summaries and logs
4. **Iterate**: Adjust workflow configurations as needed
5. **Scale**: Consider setting up additional runners if needed

## 💡 Tips

- Use `[skip ci]` in commit messages to skip CI/CD runs
- Use `[test-runner]` to specifically test self-hosted runner
- Check workflow YAML files in `.github/workflows/` to understand what runs when
- Use workflow dispatch for manual testing
- Keep an eye on disk space in `~/actions-runner-ipfs_datasets_py/_work/`

---

**Questions or Issues?**

- Check the GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Review workflow logs in the Actions tab
- Check runner logs with `journalctl`
- Consult the additional documentation files listed above
