# 🚀 Setting Up Self-Hosted GitHub Runner with GPU Support

## Your System

**Detected:**
- 2x NVIDIA GeForce RTX 3090 (24GB each)
- Driver Version: 575.57.08
- CUDA Version: 12.9
- Docker GPU access: ✅ Available

## Quick Setup Guide

### Step 1: Get Your Runner Registration Token

1. Go to your repository on GitHub:
   ```
   https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners/new
   ```

2. Select:
   - OS: **Linux**
   - Architecture: **X64**

3. **Copy the registration token** from the commands GitHub shows you.

### Step 2: Download and Configure Runner

Run these commands **on this machine**:

```bash
# Create runner directory
mkdir -p ~/actions-runner && cd ~/actions-runner

# Download the latest runner (check GitHub for the latest version URL)
curl -o actions-runner-linux-x64-2.311.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz

# Optional: Validate the hash
echo "29fc8cf2dab4c195bb147384e7e2c94cfd4d4022c793b346a6175435265aa278  actions-runner-linux-x64-2.311.0.tar.gz" | shasum -a 256 -c

# Extract
tar xzf ./actions-runner-linux-x64-2.311.0.tar.gz

# Configure with GPU labels
./config.sh --url https://github.com/endomorphosis/ipfs_datasets_py \
  --token YOUR_REGISTRATION_TOKEN_HERE \
  --name "gpu-workstation" \
  --labels "self-hosted,linux,x64,gpu,cuda,rtx3090" \
  --work _work

# Answer prompts:
# - Runner group: Default
# - Runner name: gpu-workstation (or your preference)
# - Work folder: _work (default)
```

### Step 3: Install as a Service

```bash
cd ~/actions-runner

# Install the service
sudo ./svc.sh install

# Start the service
sudo ./svc.sh start

# Check status
sudo ./svc.sh status
```

### Step 4: Verify GPU Access in Docker

The runner needs to be able to access GPUs through Docker:

```bash
# Test GPU access
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi

# If this fails, you may need to install nvidia-container-toolkit:
# distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
# curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
# curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
#   sudo tee /etc/apt/sources.list.d/nvidia-docker.list
# sudo apt-get update
# sudo apt-get install -y nvidia-container-toolkit
# sudo systemctl restart docker
```

### Step 5: Verify Runner is Online

1. Go to: `https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners`
2. You should see your runner listed as "Idle" with a green dot
3. Labels should show: `self-hosted`, `linux`, `x64`, `gpu`, `cuda`, `rtx3090`

## Testing the GPU Runner

### Option 1: Push a Test Commit

```bash
cd ~/ipfs_datasets_py
git commit --allow-empty -m "[test-gpu-runner] Testing GPU-enabled self-hosted runner"
git push
```

### Option 2: Manual Workflow Dispatch

1. Go to: `https://github.com/endomorphosis/ipfs_datasets_py/actions`
2. Select "GPU-Enabled Tests" workflow
3. Click "Run workflow"

## Workflow Configuration

The workflows have been configured to:
- ✅ Use your GPU runner for GPU-dependent tests
- ✅ Fall back to CPU-only tests on GitHub-hosted runners
- ✅ Run both in parallel when possible
- ✅ Expose GPU info in test reports

## Runner Management

### Start/Stop/Restart

```bash
cd ~/actions-runner

# Stop
sudo ./svc.sh stop

# Start
sudo ./svc.sh start

# Restart
sudo ./svc.sh restart

# Status
sudo ./svc.sh status
```

### View Logs

```bash
# System logs
sudo journalctl -u actions.runner.* -f

# Runner logs
cd ~/actions-runner
tail -f _diag/Runner_*.log
```

### Remove Runner

```bash
cd ~/actions-runner

# Stop the service
sudo ./svc.sh stop
sudo ./svc.sh uninstall

# Remove from GitHub (get token from Settings → Actions → Runners)
./config.sh remove --token YOUR_REMOVAL_TOKEN
```

## Security Considerations

✅ **Best Practices:**
1. This machine should only run your own trusted code
2. Keep the system and Docker updated
3. Monitor GPU usage and temperature
4. Set up log rotation
5. Consider firewall rules

⚠️ **Warning:**
- Self-hosted runners execute code from your repository
- Only use with repositories you control
- GitHub-hosted runners are more isolated

## Resource Management

### Monitor GPU Usage

```bash
# Real-time monitoring
watch -n 1 nvidia-smi

# Check GPU memory
nvidia-smi --query-gpu=memory.used,memory.total --format=csv

# Monitor temperature
nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader
```

### Disk Space Management

```bash
# Check runner work directory size
du -sh ~/actions-runner/_work/

# Clean old builds
cd ~/actions-runner/_work
rm -rf */  # Be careful with this!

# Docker cleanup
docker system prune -af
```

## Troubleshooting

### Runner Not Appearing in GitHub

```bash
# Check service status
sudo systemctl status actions.runner.*

# Check logs
sudo journalctl -u actions.runner.* --since "1 hour ago"

# Restart
cd ~/actions-runner
sudo ./svc.sh restart
```

### GPU Not Available in Workflow

1. Check Docker GPU access:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
   ```

2. Verify nvidia-container-toolkit is installed:
   ```bash
   dpkg -l | grep nvidia-container-toolkit
   ```

3. Check Docker daemon config:
   ```bash
   cat /etc/docker/daemon.json
   # Should contain: {"default-runtime": "nvidia"}
   ```

### Runner Offline After Reboot

```bash
# Enable service to start on boot
sudo systemctl enable actions.runner.*

# Or manually start
cd ~/actions-runner
sudo ./svc.sh start
```

## Advanced Configuration

### Custom Work Directory

```bash
# Configure with custom work directory
./config.sh --url https://github.com/endomorphosis/ipfs_datasets_py \
  --token YOUR_TOKEN \
  --work /mnt/fast-ssd/runner-work
```

### Multiple Runners on Same Machine

```bash
# Create separate directories
mkdir -p ~/actions-runner-1
mkdir -p ~/actions-runner-2

# Configure each with unique names and work folders
```

### Environment Variables

Add to `~/.bashrc` or runner service:
```bash
export CUDA_VISIBLE_DEVICES=0,1  # Use both GPUs
export NVIDIA_VISIBLE_DEVICES=all
```

## What's Next?

After setup, your workflows will:
1. ✅ Detect GPU availability automatically
2. ✅ Run GPU tests on your runner
3. ✅ Run CPU tests on GitHub-hosted runners
4. ✅ Show GPU info in test summaries
5. ✅ Upload GPU test artifacts

## Support

If you encounter issues:
1. Check the runner logs: `~/actions-runner/_diag/`
2. Check system logs: `sudo journalctl -u actions.runner.*`
3. Verify GPU access: `nvidia-smi`
4. Test Docker GPU: `docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi`

---

**Your GPU Setup:**
- 2x RTX 3090 (24GB each)
- CUDA 12.9
- Driver 575.57.08
- Perfect for ML/AI workloads! 🚀
