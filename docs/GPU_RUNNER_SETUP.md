# GPU-Enabled Self-Hosted Runner Setup Guide

This guide provides comprehensive instructions for setting up GPU-enabled self-hosted GitHub Actions runners for CUDA/GPU-accelerated testing in the IPFS Datasets project.

## Overview

GPU-enabled runners enable:
- CUDA/GPU-accelerated model training and inference testing
- GPU-specific MCP tools validation
- Performance benchmarking with GPU hardware
- Multi-GPU testing scenarios
- GPU memory management testing

## Prerequisites

### Hardware Requirements
- **GPU**: NVIDIA GPU with CUDA Compute Capability 3.5+ (recommended: RTX 3070+, Tesla V100+, or A100)
- **CPU**: 8+ cores recommended
- **RAM**: 16GB+ system RAM (32GB+ recommended)
- **Storage**: 100GB+ available (models and datasets require significant space)
- **Power**: Adequate PSU for GPU load

### Software Requirements
- **OS**: Ubuntu 20.04+ or CentOS 8+ (x86_64)
- **NVIDIA Driver**: 470.57.02+ (see compatibility matrix)
- **CUDA Toolkit**: 11.8+ or 12.0+
- **Docker**: 20.10+ with NVIDIA Container Toolkit
- **Python**: 3.10, 3.11, or 3.12

## Installation Steps

### 1. System Preparation

#### Update System
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl wget git build-essential
```

#### Install NVIDIA Drivers
```bash
# Check current driver
nvidia-smi

# If driver not installed or outdated:
# Remove old drivers
sudo apt purge nvidia* libnvidia*

# Install latest driver
sudo apt install -y nvidia-driver-535
# OR for specific version:
# sudo apt install -y nvidia-driver-470

# Reboot system
sudo reboot

# Verify installation
nvidia-smi
```

#### Install CUDA Toolkit
```bash
# Download CUDA toolkit (replace with latest version)
wget https://developer.download.nvidia.com/compute/cuda/12.0.0/local_installers/cuda_12.0.0_525.60.13_linux.run

# Install CUDA
sudo sh cuda_12.0.0_525.60.13_linux.run

# Add CUDA to PATH
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

# Verify CUDA installation
nvcc --version
```

### 2. Install Docker with NVIDIA Support

#### Install Docker
```bash
# Remove old Docker versions
sudo apt remove docker docker-engine docker.io containerd runc

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

#### Install NVIDIA Container Toolkit
```bash
# Add NVIDIA package repositories
distribution=$(. /etc/os-release;echo $ID$VERSION_ID) \
    && curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
    && curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Install the toolkit
sudo apt update
sudo apt install -y nvidia-container-toolkit

# Configure Docker to use NVIDIA runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Test GPU access in Docker
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu20.04 nvidia-smi
```

### 3. Create GPU Runner User
```bash
# Create dedicated user
sudo useradd -m -s /bin/bash gpu-runner
sudo usermod -aG docker gpu-runner

# Switch to runner user
sudo su - gpu-runner
```

### 4. Install Python and Dependencies
```bash
# Install Python 3.12
sudo apt install -y python3.12 python3.12-venv python3.12-dev python3-pip

# Create virtual environment for testing
python3.12 -m venv gpu-test-env
source gpu-test-env/bin/activate

# Install GPU-specific packages
pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
pip install nvidia-ml-py3 gpustat

# Test GPU access in Python
python -c "
import torch
print(f'CUDA available: {torch.cuda.is_available()}')
print(f'CUDA devices: {torch.cuda.device_count()}')
for i in range(torch.cuda.device_count()):
    print(f'GPU {i}: {torch.cuda.get_device_name(i)}')
"
```

### 5. Set Up GitHub Actions Runner

#### Download and Configure Runner
```bash
# Create runner directory
mkdir actions-runner && cd actions-runner

# Download runner for x86_64
curl -o actions-runner-linux-x64-2.311.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz

# Extract
tar xzf ./actions-runner-linux-x64-2.311.0.tar.gz

# Configure runner
./config.sh --url https://github.com/endomorphosis/ipfs_datasets_py --token <YOUR_REGISTRATION_TOKEN>

# Configuration:
# - Name: gpu-runner-01
# - Labels: self-hosted,linux,x64,gpu
# - Group: Default
```

#### Install as Service
```bash
sudo ./svc.sh install gpu-runner
sudo ./svc.sh start gpu-runner
sudo ./svc.sh status gpu-runner
```

### 6. Configure GPU Runner Environment

#### Create Environment File
Create `/home/gpu-runner/.env`:
```bash
# CUDA Configuration
CUDA_VISIBLE_DEVICES=0,1
NVIDIA_VISIBLE_DEVICES=all
NVIDIA_DRIVER_CAPABILITIES=compute,utility

# PyTorch Configuration
PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
CUDA_LAUNCH_BLOCKING=1

# Python Configuration
PYTHON_VERSION=3.12
PYTHONPATH=/home/gpu-runner/actions-runner/_work

# Testing Configuration
GPU_MEMORY_FRACTION=0.8
CUDA_DEVICE_ORDER=PCI_BUS_ID
```

#### Create GPU Testing Script
Create `/home/gpu-runner/test_gpu_setup.py`:
```python
#!/usr/bin/env python3
"""GPU setup validation script for GitHub Actions runner."""

import sys
import subprocess
import time

def test_nvidia_smi():
    """Test nvidia-smi availability."""
    try:
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ nvidia-smi working")
            print(result.stdout.split('\n')[8])  # GPU info line
            return True
        else:
            print("❌ nvidia-smi failed")
            return False
    except FileNotFoundError:
        print("❌ nvidia-smi not found")
        return False

def test_cuda_toolkit():
    """Test CUDA toolkit."""
    try:
        result = subprocess.run(['nvcc', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            version_line = [line for line in result.stdout.split('\n') if 'release' in line][0]
            print(f"✅ CUDA toolkit: {version_line.strip()}")
            return True
        else:
            print("❌ CUDA toolkit failed")
            return False
    except FileNotFoundError:
        print("❌ nvcc not found")
        return False

def test_docker_gpu():
    """Test Docker GPU access."""
    try:
        result = subprocess.run([
            'docker', 'run', '--rm', '--gpus', 'all',
            'nvidia/cuda:12.0-base-ubuntu20.04', 'nvidia-smi', '--query-gpu=name', '--format=csv,noheader'
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            gpus = result.stdout.strip().split('\n')
            print(f"✅ Docker GPU access: {len(gpus)} GPU(s)")
            for i, gpu in enumerate(gpus):
                print(f"  GPU {i}: {gpu}")
            return True
        else:
            print("❌ Docker GPU access failed")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ Docker GPU test error: {e}")
        return False

def test_pytorch_gpu():
    """Test PyTorch GPU access."""
    try:
        import torch
        
        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            print(f"✅ PyTorch GPU access: {device_count} device(s)")
            
            for i in range(device_count):
                name = torch.cuda.get_device_name(i)
                memory = torch.cuda.get_device_properties(i).total_memory / 1024**3
                print(f"  GPU {i}: {name} ({memory:.1f}GB)")
            
            # Test tensor operations
            x = torch.randn(1000, 1000, device='cuda')
            y = torch.randn(1000, 1000, device='cuda')
            start_time = time.time()
            z = torch.matmul(x, y)
            end_time = time.time()
            print(f"  Matrix multiplication test: {end_time - start_time:.3f}s")
            
            return True
        else:
            print("❌ PyTorch: CUDA not available")
            return False
    except ImportError:
        print("❌ PyTorch not installed")
        return False
    except Exception as e:
        print(f"❌ PyTorch GPU test error: {e}")
        return False

def main():
    """Run all GPU tests."""
    print("🧪 GPU Runner Setup Validation")
    print("=" * 40)
    
    tests = [
        ("NVIDIA SMI", test_nvidia_smi),
        ("CUDA Toolkit", test_cuda_toolkit),
        ("Docker GPU", test_docker_gpu),
        ("PyTorch GPU", test_pytorch_gpu),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n🔍 Testing {name}...")
        result = test_func()
        results.append((name, result))
    
    print("\n📊 Summary:")
    print("=" * 40)
    passed = 0
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name}: {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All GPU tests passed! Runner is ready.")
        return 0
    else:
        print("⚠️ Some tests failed. Check configuration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:
```bash
chmod +x /home/gpu-runner/test_gpu_setup.py
```

### 7. Validation and Testing

#### Run GPU Validation
```bash
cd /home/gpu-runner
python test_gpu_setup.py
```

Expected output:
```
🧪 GPU Runner Setup Validation
========================================

🔍 Testing NVIDIA SMI...
✅ nvidia-smi working
| NVIDIA GeForce RTX 3090     Off  | 00000000:01:00.0 Off |                  N/A |

🔍 Testing CUDA Toolkit...
✅ CUDA toolkit: Cuda compilation tools, release 12.0, V12.0.76

🔍 Testing Docker GPU...
✅ Docker GPU access: 1 GPU(s)
  GPU 0: NVIDIA GeForce RTX 3090

🔍 Testing PyTorch GPU...
✅ PyTorch GPU access: 1 device(s)
  GPU 0: NVIDIA GeForce RTX 3090 (24.0GB)
  Matrix multiplication test: 0.023s

📊 Summary:
========================================
NVIDIA SMI: ✅ PASS
CUDA Toolkit: ✅ PASS
Docker GPU: ✅ PASS
PyTorch GPU: ✅ PASS

Overall: 4/4 tests passed
🎉 All GPU tests passed! Runner is ready.
```

#### Test with GitHub Actions
Trigger the "GPU-Enabled Tests" workflow to validate the runner.

### 8. System Service Configuration

Create `/etc/systemd/system/gpu-runner.service`:
```ini
[Unit]
Description=GitHub Actions GPU Runner
After=network.target nvidia-persistenced.service

[Service]
Type=simple
User=gpu-runner
Group=gpu-runner
WorkingDirectory=/home/gpu-runner/actions-runner
ExecStart=/home/gpu-runner/actions-runner/run.sh
Restart=always
RestartSec=10
Environment=NVIDIA_VISIBLE_DEVICES=all
Environment=CUDA_VISIBLE_DEVICES=0,1

[Install]
WantedBy=multi-user.target
```

Enable the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable gpu-runner
sudo systemctl start gpu-runner
sudo systemctl status gpu-runner
```

## Monitoring and Maintenance

### GPU Monitoring Tools

#### Install Monitoring
```bash
# Install GPU monitoring tools
pip install gpustat nvitop

# Install system monitoring
sudo apt install -y htop iotop nethogs
```

#### Monitoring Commands
```bash
# GPU utilization
gpustat -i 1

# Detailed GPU info
nvitop

# NVIDIA system management
nvidia-smi -l 1

# Check running processes on GPU
nvidia-smi pmon

# GPU memory usage
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

### Log Monitoring
```bash
# Runner logs
tail -f /home/gpu-runner/actions-runner/_diag/Runner_*.log

# System service logs
sudo journalctl -u gpu-runner -f

# NVIDIA logs
sudo journalctl -u nvidia-persistenced -f
```

### Performance Monitoring Script
Create `/home/gpu-runner/monitor_gpu.sh`:
```bash
#!/bin/bash
# GPU performance monitoring for GitHub Actions

LOG_FILE="/home/gpu-runner/gpu_performance.log"
INTERVAL=10

echo "$(date): Starting GPU monitoring" >> $LOG_FILE

while true; do
    echo "=== $(date) ===" >> $LOG_FILE
    
    # GPU utilization
    nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits >> $LOG_FILE
    
    # System load
    echo "CPU: $(cat /proc/loadavg)" >> $LOG_FILE
    echo "Memory: $(free -m | grep Mem | awk '{printf "%.1f%%\n", $3/$2 * 100.0}')" >> $LOG_FILE
    
    sleep $INTERVAL
done
```

### Automated Health Checks
Create `/home/gpu-runner/health_check.py`:
```python
#!/usr/bin/env python3
"""Health check script for GPU runner."""

import subprocess
import json
import time
import sys

def check_gpu_health():
    """Check GPU health and availability."""
    try:
        # Check GPU temperature
        result = subprocess.run([
            'nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            temps = [int(temp) for temp in result.stdout.strip().split('\n')]
            max_temp = max(temps)
            
            if max_temp > 85:  # Temperature threshold
                return False, f"GPU temperature too high: {max_temp}°C"
            
            return True, f"GPU temperature OK: {max_temp}°C"
        else:
            return False, "nvidia-smi failed"
    
    except Exception as e:
        return False, f"GPU health check error: {e}"

def check_docker_gpu():
    """Check Docker GPU access."""
    try:
        result = subprocess.run([
            'docker', 'run', '--rm', '--gpus', 'all',
            'nvidia/cuda:12.0-base-ubuntu20.04', 'nvidia-smi', '-L'
        ], capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0:
            gpu_count = len(result.stdout.strip().split('\n'))
            return True, f"Docker GPU access OK: {gpu_count} GPU(s)"
        else:
            return False, "Docker GPU access failed"
    
    except Exception as e:
        return False, f"Docker GPU check error: {e}"

def main():
    """Run health checks."""
    checks = [
        ("GPU Health", check_gpu_health),
        ("Docker GPU", check_docker_gpu),
    ]
    
    results = {}
    all_passed = True
    
    for name, check_func in checks:
        passed, message = check_func()
        results[name] = {"passed": passed, "message": message}
        if not passed:
            all_passed = False
        print(f"{name}: {'✅' if passed else '❌'} {message}")
    
    # Write results to file for monitoring
    with open('/home/gpu-runner/health_status.json', 'w') as f:
        json.dump({
            "timestamp": time.time(),
            "overall_health": all_passed,
            "checks": results
        }, f, indent=2)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
```

Set up cron job for health checks:
```bash
# Add to crontab
crontab -e

# Add line:
*/5 * * * * /usr/bin/python3 /home/gpu-runner/health_check.py
```

## Troubleshooting

### Common Issues

#### CUDA Out of Memory
```bash
# Check GPU memory usage
nvidia-smi

# Clear GPU memory
python -c "
import torch
if torch.cuda.is_available():
    torch.cuda.empty_cache()
    print('GPU cache cleared')
"

# Restart runner if needed
sudo systemctl restart gpu-runner
```

#### Driver Issues
```bash
# Check driver status
nvidia-smi

# Reinstall driver if needed
sudo apt install --reinstall nvidia-driver-535

# Check kernel modules
lsmod | grep nvidia
modinfo nvidia
```

#### Docker GPU Issues
```bash
# Check NVIDIA container runtime
docker info | grep nvidia

# Test GPU container
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu20.04 nvidia-smi

# Restart Docker daemon
sudo systemctl restart docker
```

### Performance Optimization

#### GPU Memory Management
```bash
# Set GPU memory fraction
export CUDA_MEM_FRACTION=0.8

# Enable memory growth
export TF_FORCE_GPU_ALLOW_GROWTH=true

# Limit CUDA malloc
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
```

#### Power Management
```bash
# Set GPU performance mode
sudo nvidia-smi -pm 1

# Set power limit (adjust as needed)
sudo nvidia-smi -pl 300  # 300W limit

# Set GPU clocks
sudo nvidia-smi -ac 877,1400  # Memory,Graphics clocks
```

## Security Considerations

1. **GPU Access Control**: Limit GPU access to runner user only
2. **Container Security**: Use specific CUDA container versions
3. **Resource Limits**: Set appropriate GPU memory and compute limits
4. **Monitoring**: Monitor for unusual GPU usage patterns
5. **Updates**: Keep NVIDIA drivers and CUDA toolkit updated

## Multi-GPU Configuration

For multiple GPUs:
```bash
# Configure environment for multiple GPUs
export CUDA_VISIBLE_DEVICES=0,1,2,3

# Test all GPUs
python -c "
import torch
for i in range(torch.cuda.device_count()):
    print(f'GPU {i}: {torch.cuda.get_device_name(i)}')
    x = torch.randn(1000, 1000, device=f'cuda:{i}')
    print(f'  Memory allocated: {torch.cuda.memory_allocated(i) / 1024**2:.1f}MB')
"
```

## Validation Checklist

- [ ] NVIDIA drivers installed and working (`nvidia-smi`)
- [ ] CUDA toolkit installed (`nvcc --version`)
- [ ] Docker with NVIDIA runtime working
- [ ] PyTorch/TensorFlow GPU access confirmed
- [ ] GitHub Actions runner registered with `gpu` label
- [ ] GPU health monitoring set up
- [ ] Performance monitoring active
- [ ] Service auto-starts on boot
- [ ] Temperature monitoring configured
- [ ] Memory usage limits set

This setup provides a robust GPU-enabled testing environment for the IPFS Datasets project's machine learning and GPU-accelerated functionality.