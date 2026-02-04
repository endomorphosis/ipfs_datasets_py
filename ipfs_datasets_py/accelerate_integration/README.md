# IPFS Accelerate Integration

This module provides integration between `ipfs_datasets_py` and `ipfs_accelerate_py` for distributed AI compute services with graceful fallbacks.

## Overview

The accelerate integration enables:
- **Hardware-accelerated ML inference** across CPU, GPU, OpenVINO, WebNN, WebGPU, and more
- **Distributed compute coordination** across IPFS network peers
- **Graceful fallbacks** when accelerate is unavailable or disabled
- **CI/CD friendly** with automatic detection and environment-based control

## Installation

### Option 1: Install with accelerate support (recommended)

```bash
# Install with accelerate extras (installs from GitHub main)
pip install -e ".[accelerate]"

# Or install full ipfs_accelerate_py from GitHub main
pip install git+https://github.com/endomorphosis/ipfs_accelerate_py.git@main
```

### Option 2: Use the submodule (development)

The submodule is already configured in `.gitmodules`:

```bash
# Initialize and update submodules
git submodule update --init ipfs_accelerate_py

# The integration will automatically detect and use the submodule
```

## Usage

### Basic Usage

```python
from ipfs_datasets_py.accelerate_integration import (
    AccelerateManager,
    is_accelerate_available,
    get_accelerate_status
)

# Check if accelerate is available
if is_accelerate_available():
    print("Accelerate is available!")
    
    # Create manager
    manager = AccelerateManager()
    
    # Run inference
    result = manager.run_inference(
        model_name="bert-base-uncased",
        input_data="Hello world",
        task_type="embedding"
    )
    print(result)
else:
    print("Accelerate not available, using fallback")
    status = get_accelerate_status()
    print(f"Status: {status}")
```

### Distributed Compute

```python
from ipfs_datasets_py.accelerate_integration import (
    AccelerateManager,
    DistributedComputeCoordinator
)

# Initialize manager with distributed compute
manager = AccelerateManager(enable_distributed=True)

# Create coordinator
coordinator = DistributedComputeCoordinator()
coordinator.initialize()

# Submit distributed task
task = coordinator.submit_task(
    task_id="task-001",
    model_name="bert-base-uncased",
    input_data="Process this text",
    task_type="inference"
)

# Check task status
status = coordinator.get_task_status(task.task_id)
print(f"Task status: {status}")
```

### Hardware Backend Selection

```python
from ipfs_datasets_py.accelerate_integration import (
    get_compute_backend,
    HardwareType,
    detect_available_hardware
)

# Detect available hardware
available = detect_available_hardware()
print(f"Available hardware: {available}")

# Get backend for specific hardware
backend = get_compute_backend(HardwareType.CUDA, device_id=0)

# Or auto-detect best hardware
backend = get_compute_backend()  # Automatically selects best available
```

## Environment Variables

Control the accelerate integration behavior with environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `IPFS_ACCELERATE_ENABLED` | `1` | Set to `0`, `false`, or `no` to disable accelerate |
| `IPFS_ACCEL_SKIP_CORE` | `0` | Skip heavy imports for faster load times |
| `IPFS_ACCEL_IMPORT_EAGER` | `0` | Eagerly import model manager components |

### Examples

```bash
# Disable accelerate for CI/CD
export IPFS_ACCELERATE_ENABLED=0
python my_script.py

# Skip heavy imports for faster startup
export IPFS_ACCEL_SKIP_CORE=1
python my_script.py
```

## Integration with Embeddings

The accelerate integration is automatically available in the embeddings module:

```python
from ipfs_datasets_py.embeddings import create_embeddings
from ipfs_datasets_py.accelerate_integration import is_accelerate_available

# Create embeddings with accelerate if available
embeddings = create_embeddings(
    texts=["text1", "text2"],
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    use_accelerate=is_accelerate_available()
)
```

## Integration with Dataset Processing

Use accelerate for dataset processing tasks:

```python
from ipfs_datasets_py.dataset_manager import DatasetManager
from ipfs_datasets_py.accelerate_integration import AccelerateManager

dataset_manager = DatasetManager()
accelerate_manager = AccelerateManager()

if accelerate_manager.is_available():
    # Process dataset with accelerate
    dataset = dataset_manager.get_dataset("squad")
    # ... processing with accelerate
else:
    # Fallback to local processing
    dataset = dataset_manager.get_dataset("squad")
    # ... local processing
```

## Architecture

The integration consists of three main components:

1. **AccelerateManager**: Main interface for coordinating distributed compute
2. **ComputeBackend**: Hardware abstraction layer for different backends
3. **DistributedComputeCoordinator**: P2P compute coordination across IPFS network

```
┌─────────────────────────────────────────┐
│      ipfs_datasets_py Application       │
└─────────────────┬───────────────────────┘
                  │
                  v
┌─────────────────────────────────────────┐
│      AccelerateManager                  │
│  ┌────────────┐  ┌────────────────────┐│
│  │  Compute   │  │    Distributed     ││
│  │  Backend   │  │   Coordinator      ││
│  └────────────┘  └────────────────────┘│
└──────────┬──────────────────────────────┘
           │
           v
┌─────────────────────────────────────────┐
│      ipfs_accelerate_py (submodule)     │
│  - Hardware Acceleration               │
│  - Model Management                    │
│  - IPFS Distribution                   │
└─────────────────────────────────────────┘
```

## Fallback Behavior

The integration is designed to be CI/CD friendly with automatic fallbacks:

1. **No accelerate**: Falls back to local compute
2. **Accelerate disabled**: Respects `IPFS_ACCELERATE_ENABLED=0`
3. **Import errors**: Logs warnings and uses fallback
4. **Runtime errors**: Catches exceptions and falls back gracefully

## Testing

Test the integration with and without accelerate:

```bash
# Test with accelerate enabled
pytest tests/test_accelerate_integration.py

# Test with accelerate disabled (fallback mode)
IPFS_ACCELERATE_ENABLED=0 pytest tests/test_accelerate_integration.py

# Test distributed compute
pytest tests/test_distributed_compute.py
```

## Development

### Adding New Hardware Backends

To add support for new hardware:

1. Add the hardware type to `HardwareType` enum in `compute_backend.py`
2. Implement detection logic in `detect_available_hardware()`
3. Update `ComputeBackend` initialization as needed

### Extending Distributed Compute

To extend distributed compute capabilities:

1. Modify `DistributedComputeCoordinator` in `distributed_coordinator.py`
2. Implement peer discovery using IPFS pubsub or DHT
3. Add load balancing and task scheduling logic

## Troubleshooting

### Accelerate not detected

Check the status:

```python
from ipfs_datasets_py.accelerate_integration import get_accelerate_status
print(get_accelerate_status())
```

Common issues:
- Submodule not initialized: `git submodule update --init ipfs_accelerate_py`
- Import errors: Check `import_error` field in status
- Environment disabled: Check `IPFS_ACCELERATE_ENABLED` variable

### Performance Issues

Enable performance logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Monitor hardware usage and consider:
- Using GPU backend for large models
- Enabling distributed compute for large workloads
- Adjusting `max_concurrent_tasks` in coordinator

## References

- [ipfs_accelerate_py GitHub](https://github.com/endomorphosis/ipfs_accelerate_py)
- [ipfs_accelerate_py Documentation](https://github.com/endomorphosis/ipfs_accelerate_py/blob/main/README.md)
- [IPFS Documentation](https://docs.ipfs.io/)
