# 🎮 GPU-Enabled Self-Hosted Runner - Complete Setup

## Summary

Your machine has **2x NVIDIA RTX 3090 GPUs** (24GB each) - perfect for ML/AI workloads! I've set up everything you need to use them with GitHub Actions.

## ✅ What's Been Created

### 1. GPU-Specific Workflows
- **`.github/workflows/gpu-tests.yml`** - Runs GPU-dependent tests on your self-hosted runner
  - Automatically detects GPU availability
  - Runs GPU tests on self-hosted runner (with your RTX 3090s)
  - Runs CPU tests on GitHub-hosted runners in parallel
  - Shows GPU info in test summaries

### 2. GPU Docker Support
- **`Dockerfile.gpu`** - Docker image with CUDA 12.0 and PyTorch GPU support
- Includes PyTorch with CUDA
- Optimized for your GPU setup
- Tests GPU access automatically

### 3. Setup Scripts
- **`setup_gpu_runner.sh`** - Automated self-hosted runner setup
- **`test_gpu_setup.sh`** - Test GPU and Docker before runner setup
- **`GPU_RUNNER_SETUP.md`** - Complete documentation

### 4. Pytest Configuration
- **`pytest.ini`** - Updated with GPU test markers
- **Custom markers:**
  - `@pytest.mark.gpu` - For GPU-required tests
  - `@pytest.mark.multi_gpu` - For tests needing 2+ GPUs (you have 2!)
  - `@pytest.mark.slow` - For slow tests
  - Auto-skips GPU tests when GPU unavailable

## 🚀 Quick Setup (3 Steps)

### Step 1: Test GPU Setup (Optional but Recommended)

```bash
# Test that GPUs are accessible
bash test_gpu_setup.sh
```

### Step 2: Set Up Self-Hosted Runner

**Option A: Automated Setup**
```bash
bash setup_gpu_runner.sh
```
It will ask for your GitHub registration token.

**Option B: Manual Setup**
1. Go to: https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners/new
2. Copy the registration token
3. Follow the commands in `GPU_RUNNER_SETUP.md`

### Step 3: Commit and Push

```bash
git add .
git commit -m "Add GPU-enabled self-hosted runner support"
git push
```

## 🎯 How It Works

### Workflow Behavior

1. **GPU Tests** (`gpu-tests.yml`):
   - Runs on your machine (self-hosted, linux, x64, gpu)
   - Has access to both RTX 3090s
   - Runs tests marked with `@pytest.mark.gpu`
   - Shows GPU memory usage in summaries

2. **CPU Tests** (same workflow):
   - Runs on GitHub-hosted runners
   - Runs tests marked with `@pytest.mark.not gpu`
   - Free and fast

3. **Docker Tests**:
   - Builds GPU-enabled containers
   - Tests PyTorch GPU access
   - Runs containerized GPU tests

### Test Organization

```python
# Example GPU test
import pytest
import torch

@pytest.mark.gpu
def test_model_on_gpu():
    assert torch.cuda.is_available()
    model = MyModel().cuda()
    # ... test with GPU

@pytest.mark.multi_gpu
def test_distributed_training():
    assert torch.cuda.device_count() >= 2
    # ... test with multiple GPUs

# Regular CPU test (runs on GitHub)
def test_data_processing():
    # ... CPU-only test
```

## 📊 Your GPU Configuration

```
GPU 0: NVIDIA GeForce RTX 3090 (24GB)
GPU 1: NVIDIA GeForce RTX 3090 (24GB)
Driver: 575.57.08
CUDA: 12.9
Total VRAM: 48GB
```

**Perfect for:**
- ✅ Training large language models
- ✅ Computer vision tasks
- ✅ Distributed training (2 GPUs!)
- ✅ Batch processing
- ✅ Model inference testing

## 🔧 Runner Labels

Your runner will have these labels:
- `self-hosted` - It's your machine
- `linux` - OS type
- `x64` - Architecture
- `gpu` - Has GPUs
- `cuda` - CUDA support
- `rtx3090` - Specific GPU model

**Workflows can target it like:**
```yaml
runs-on: [self-hosted, linux, x64, gpu]
```

## 📝 Managing Your Runner

### Check Status
```bash
cd ~/actions-runner-gpu
sudo ./svc.sh status
```

### View Logs
```bash
sudo journalctl -u actions.runner.* -f
```

### Restart
```bash
cd ~/actions-runner-gpu
sudo ./svc.sh restart
```

### Monitor GPU Usage During Tests
```bash
watch -n 1 nvidia-smi
```

### Stop Runner
```bash
cd ~/actions-runner-gpu
sudo ./svc.sh stop
```

## 🎨 Example Workflow Run

When you push code:

```
1. GitHub Actions triggers workflows
2. GPU tests dispatch to your machine
3. Your runner picks up the job
4. Tests run with full GPU access
5. Results uploaded to GitHub
6. Summary shows GPU usage
7. Artifacts saved (test results, coverage, etc.)
```

You'll see output like:
```
🎮 GPU Runner Information
Hardware:
  NVIDIA GeForce RTX 3090, 575.57.08, 24576 MiB
  NVIDIA GeForce RTX 3090, 575.57.08, 24576 MiB

CUDA:
  - CUDA Version: 12.9
  - GPU Count: 2

📊 GPU Memory Usage
  0, NVIDIA GeForce RTX 3090, 1234 MiB, 24576 MiB
  1, NVIDIA GeForce RTX 3090, 0 MiB, 24576 MiB
```

## 🔐 Security Notes

✅ **Safe:**
- Your runner only runs code from your repository
- You control what tests run
- GPU access is isolated to your containers

⚠️ **Important:**
- Don't share runner with untrusted repos
- Monitor resource usage
- Keep drivers updated
- Check logs regularly

## 💡 Pro Tips

1. **Use both GPUs for tests:**
   ```python
   @pytest.mark.multi_gpu
   def test_data_parallel():
       model = nn.DataParallel(model, device_ids=[0, 1])
   ```

2. **Control GPU memory:**
   ```bash
   PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
   ```

3. **Monitor temperature:**
   ```bash
   nvidia-smi --query-gpu=temperature.gpu --format=csv -l 5
   ```

4. **Clean up between runs:**
   ```python
   torch.cuda.empty_cache()
   ```

## 📚 Files Created

- `.github/workflows/gpu-tests.yml` - GPU test workflow
- `Dockerfile.gpu` - GPU-enabled Docker image
- `GPU_RUNNER_SETUP.md` - Detailed setup guide
- `setup_gpu_runner.sh` - Automated setup script
- `test_gpu_setup.sh` - GPU testing script
- `pytest.ini` - Updated with GPU markers
- `tests/conftest.py` - Pytest GPU configuration

## 🆘 Troubleshooting

### Runner Not Showing Up
```bash
cd ~/actions-runner-gpu
sudo ./svc.sh status
sudo journalctl -u actions.runner.* --since "10 minutes ago"
```

### Docker Can't Access GPU
```bash
# Install nvidia-container-toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
    sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### GPU Tests Not Running
1. Check runner is online: Settings → Actions → Runners
2. Verify labels include "gpu"
3. Check workflow file uses correct labels
4. Look at workflow logs

## 🎉 Next Steps

1. ✅ Run `bash test_gpu_setup.sh` to verify everything works
2. ✅ Run `bash setup_gpu_runner.sh` to set up the runner
3. ✅ Commit and push changes
4. ✅ Watch your GPU tests run on GitHub Actions!

---

**Your Setup:**
- **Location:** This machine (`$(hostname)`)
- **GPUs:** 2x RTX 3090 (48GB total VRAM)
- **CUDA:** 12.9
- **Ready for:** ML training, inference, distributed tests

**Need help?** Check `GPU_RUNNER_SETUP.md` for detailed documentation!
