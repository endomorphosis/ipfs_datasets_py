# Quick Start: IPFS Accelerate Integration

Get up and running with distributed AI compute in 5 minutes!

## 🚀 Installation (Choose One)

### Option 1: Install from PyPI (Recommended)
```bash
pip install -e ".[accelerate]"
```

### Option 2: Use Submodule (Development)
```bash
git submodule update --init ipfs_accelerate_py
pip install -e .
```

## ✅ Verify Installation

```python
from ipfs_datasets_py.accelerate_integration import (
    is_accelerate_available,
    get_accelerate_status
)

print(f"Accelerate available: {is_accelerate_available()}")
print(f"Status: {get_accelerate_status()}")
```

## 🎯 Basic Usage

### 1. Run Inference with Auto-Fallback

```python
from ipfs_datasets_py.accelerate_integration import AccelerateManager

# Initialize manager (automatically detects if accelerate is available)
manager = AccelerateManager()

# Run inference (falls back to local if accelerate unavailable)
result = manager.run_inference(
    model_name="bert-base-uncased",
    input_data="Hello world, this is a test!",
    task_type="embedding"
)

print(f"Status: {result['status']}")
print(f"Backend: {result['backend']}")
```

### 2. Check Hardware Availability

```python
from ipfs_datasets_py.accelerate_integration import get_compute_backend
from ipfs_datasets_py.accelerate_integration.compute_backend import (
    detect_available_hardware
)

# See what hardware is available
available = detect_available_hardware()
print(f"Available: {[h.value for h in available]}")

# Get best available backend
backend = get_compute_backend()
print(f"Selected: {backend.hardware_type.value}")
```

### 3. Distributed Processing

```python
from ipfs_datasets_py.accelerate_integration import (
    DistributedComputeCoordinator
)

# Initialize coordinator
coordinator = DistributedComputeCoordinator()
coordinator.initialize()

# Submit task for distributed processing
task = coordinator.submit_task(
    task_id="my-task-001",
    model_name="bert-base-uncased",
    input_data="Process this text",
    task_type="embedding"
)

print(f"Task submitted: {task.task_id}")
print(f"Status: {task.status.value}")
```

## 🎮 Try the Demo

```bash
# Run comprehensive demo
python examples/accelerate_integration_demo.py

# Or with accelerate disabled (to test fallback)
IPFS_ACCELERATE_ENABLED=0 python examples/accelerate_integration_demo.py
```

## 🔧 Configuration

### Environment Variables

```bash
# Disable accelerate (useful for CI/CD)
export IPFS_ACCELERATE_ENABLED=0

# Skip heavy imports for faster startup
export IPFS_ACCEL_SKIP_CORE=1

# Eager import model manager components
export IPFS_ACCEL_IMPORT_EAGER=1
```

### Check Configuration

```python
from ipfs_datasets_py.accelerate_integration import get_accelerate_status

status = get_accelerate_status()
print(f"Available: {status['available']}")
print(f"Enabled: {status['enabled']}")
print(f"Import Error: {status['import_error']}")
```

## 🧪 Testing

```bash
# Run all accelerate tests
pytest tests/test_accelerate_integration.py -v

# Test with accelerate disabled
IPFS_ACCELERATE_ENABLED=0 pytest tests/test_accelerate_integration.py -v
```

## 📚 Common Use Cases

### Use Case 1: Generate Embeddings

```python
from ipfs_datasets_py.accelerate_integration import AccelerateManager

manager = AccelerateManager()

texts = [
    "Machine learning is fascinating",
    "Deep learning powers modern AI",
    "Neural networks are everywhere"
]

results = []
for text in texts:
    result = manager.run_inference(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        input_data=text,
        task_type="embedding"
    )
    results.append(result)

print(f"Generated {len(results)} embeddings")
```

### Use Case 2: Batch Processing

```python
from ipfs_datasets_py.accelerate_integration import (
    DistributedComputeCoordinator
)

coordinator = DistributedComputeCoordinator()
coordinator.initialize()

# Process many items in parallel
items = ["text1", "text2", "text3", "..."]
tasks = []

for i, item in enumerate(items):
    task = coordinator.submit_task(
        task_id=f"batch-{i}",
        model_name="bert-base-uncased",
        input_data=item,
        task_type="inference"
    )
    tasks.append(task)

print(f"Submitted {len(tasks)} tasks")
```

### Use Case 3: Hardware-Specific Processing

```python
from ipfs_datasets_py.accelerate_integration import get_compute_backend
from ipfs_datasets_py.accelerate_integration.compute_backend import HardwareType

# Force GPU usage (if available)
try:
    backend = get_compute_backend(HardwareType.CUDA)
    print("Using GPU acceleration")
except:
    backend = get_compute_backend(HardwareType.CPU)
    print("Falling back to CPU")
```

## 🚫 Disable in CI/CD

### In GitHub Actions

```yaml
- name: Run tests without accelerate
  env:
    IPFS_ACCELERATE_ENABLED: 0
  run: |
    pytest tests/
```

### In Docker

```dockerfile
ENV IPFS_ACCELERATE_ENABLED=0
RUN pytest tests/
```

### In Python Script

```python
import os
os.environ['IPFS_ACCELERATE_ENABLED'] = '0'

# Now import - accelerate will be disabled
from ipfs_datasets_py.accelerate_integration import is_accelerate_available
assert not is_accelerate_available()
```

## ❓ Troubleshooting

### Problem: Accelerate not detected

**Check status:**
```python
from ipfs_datasets_py.accelerate_integration import get_accelerate_status
print(get_accelerate_status())
```

**Solutions:**
- Initialize submodule: `git submodule update --init ipfs_accelerate_py`
- Install package: `pip install ipfs-accelerate-py`
- Check import error in status

### Problem: Import errors

**Check dependencies:**
```bash
pip install -e ".[accelerate]"
```

### Problem: GPU not detected

**Check CUDA:**
```python
import torch
print(f"CUDA available: {torch.cuda.is_available()}")
```

## 📖 Learn More

- **Comprehensive Guide**: [ACCELERATE_INTEGRATION_PLAN.md](ACCELERATE_INTEGRATION_PLAN.md)
- **Module Documentation**: [ipfs_datasets_py/accelerate_integration/README.md](ipfs_datasets_py/accelerate_integration/README.md)
- **Implementation Details**: [ACCELERATE_INTEGRATION_SUMMARY.md](ACCELERATE_INTEGRATION_SUMMARY.md)
- **ipfs_accelerate_py**: [GitHub Repository](https://github.com/endomorphosis/ipfs_accelerate_py)

## 🎓 Next Steps

1. **Run the demo**: `python examples/accelerate_integration_demo.py`
2. **Read the integration plan**: See [ACCELERATE_INTEGRATION_PLAN.md](ACCELERATE_INTEGRATION_PLAN.md)
3. **Try with your data**: Adapt examples to your use case
4. **Enable GPU**: Install CUDA/ROCm for acceleration
5. **Go distributed**: Set up multiple nodes for P2P compute

## 💡 Tips

- Start with local fallback mode to understand behavior
- Use `IPFS_ACCELERATE_ENABLED=0` during development/testing
- Check status with `get_accelerate_status()` for debugging
- Hardware detection is automatic - no configuration needed
- Fallbacks happen automatically on errors

## ⚡ Performance Tips

- Use GPU backends for large models (5-20x faster)
- Enable distributed mode for batch processing
- Pre-load models when possible
- Use appropriate batch sizes for your hardware
- Monitor with `manager.get_status()` and `coordinator.get_stats()`

## 🤝 Contributing

Found an issue or want to improve the integration?
- Open an issue on GitHub
- Submit a PR with improvements
- Share your use case in discussions
