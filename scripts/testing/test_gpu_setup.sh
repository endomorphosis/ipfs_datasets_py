#!/bin/bash
# Test GPU runner setup locally

set -e

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║          Testing GPU Runner Configuration                ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Check GPU availability
echo "🎮 GPU Information:"
nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv
echo ""

# Check Docker GPU access
echo "🐳 Testing Docker GPU access..."
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
echo ""

# Build GPU Docker image
echo "🔨 Building GPU Docker image..."
docker build -t ipfs-datasets-py:gpu-test -f docker/Dockerfile.gpu .
echo ""

# Test GPU in container
echo "🧪 Testing GPU in Docker container..."
docker run --rm --gpus all ipfs-datasets-py:gpu-test
echo ""

# Test PyTorch GPU
echo "🔥 Testing PyTorch GPU access..."
docker run --rm --gpus all ipfs-datasets-py:gpu-test python -c "
import torch
print(f'✅ PyTorch: {torch.__version__}')
print(f'✅ CUDA available: {torch.cuda.is_available()}')
print(f'✅ CUDA version: {torch.version.cuda}')
print(f'✅ GPU count: {torch.cuda.device_count()}')
for i in range(torch.cuda.device_count()):
    props = torch.cuda.get_device_properties(i)
    print(f'   GPU {i}: {torch.cuda.get_device_name(i)}')
    print(f'      Memory: {props.total_memory / 1024**3:.2f} GB')
    print(f'      Compute: {props.major}.{props.minor}')
"
echo ""

echo "✅ All GPU tests passed!"
echo ""
echo "Next steps:"
echo "  1. Run: bash setup_gpu_runner.sh"
echo "  2. Get token from: https://github.com/endomorphosis/ipfs_datasets_py/settings/actions/runners/new"
echo "  3. Push changes to trigger GPU workflows"
echo ""
