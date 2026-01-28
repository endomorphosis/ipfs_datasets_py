#!/usr/bin/env python3
"""
Demonstration of ipfs_accelerate_py Integration.

This script demonstrates the integration between ipfs_datasets_py and
ipfs_accelerate_py for distributed AI compute with graceful fallbacks.

Usage:
    python examples/accelerate_integration_demo.py
    
    # Or with accelerate disabled
    IPFS_ACCELERATE_ENABLED=0 python examples/accelerate_integration_demo.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

def demo_status_check():
    """Demo 1: Check accelerate status."""
    print("=" * 70)
    print("Demo 1: Checking Accelerate Status")
    print("=" * 70)
    
    from ipfs_datasets_py.accelerate_integration import (
        is_accelerate_available,
        get_accelerate_status
    )
    
    print(f"Is accelerate available? {is_accelerate_available()}")
    print("\nDetailed status:")
    status = get_accelerate_status()
    for key, value in status.items():
        print(f"  {key}: {value}")
    print()


def demo_manager_initialization():
    """Demo 2: Initialize AccelerateManager."""
    print("=" * 70)
    print("Demo 2: Initializing AccelerateManager")
    print("=" * 70)
    
    from ipfs_datasets_py.accelerate_integration import AccelerateManager
    
    if AccelerateManager is None:
        print("AccelerateManager not available (accelerate disabled or not installed)")
        print("This is expected in CI/CD or when IPFS_ACCELERATE_ENABLED=0")
        return
    
    manager = AccelerateManager()
    print("Manager initialized successfully!")
    
    status = manager.get_status()
    print("\nManager status:")
    for key, value in status.items():
        print(f"  {key}: {value}")
    print()


def demo_inference_with_fallback():
    """Demo 3: Run inference with automatic fallback."""
    print("=" * 70)
    print("Demo 3: Running Inference with Fallback")
    print("=" * 70)
    
    from ipfs_datasets_py.accelerate_integration import AccelerateManager
    
    if AccelerateManager is None:
        print("AccelerateManager not available - skipping inference demo")
        return
    
    manager = AccelerateManager()
    
    # Try to run inference (will fallback if accelerate unavailable)
    result = manager.run_inference(
        model_name="bert-base-uncased",
        input_data="Hello world, this is a test!",
        task_type="embedding"
    )
    
    print(f"Inference result:")
    print(f"  Status: {result.get('status')}")
    print(f"  Backend: {result.get('backend')}")
    print(f"  Model: {result.get('model')}")
    if result.get('message'):
        print(f"  Message: {result.get('message')}")
    print()


def demo_hardware_detection():
    """Demo 4: Detect available hardware."""
    print("=" * 70)
    print("Demo 4: Hardware Detection")
    print("=" * 70)
    
    from ipfs_datasets_py.accelerate_integration import get_compute_backend
    
    if get_compute_backend is None:
        print("Hardware detection not available (accelerate disabled or not installed)")
        return
    
    from ipfs_datasets_py.accelerate_integration.compute_backend import (
        detect_available_hardware,
        HardwareType
    )
    
    available = detect_available_hardware()
    print(f"Available hardware types: {[h.value for h in available]}")
    
    # Get a backend
    backend = get_compute_backend()
    print(f"\nAuto-selected backend: {backend.hardware_type.value}")
    print(f"Backend initialized: {backend.is_available()}")
    print()


def demo_distributed_coordinator():
    """Demo 5: Distributed compute coordination."""
    print("=" * 70)
    print("Demo 5: Distributed Compute Coordinator")
    print("=" * 70)
    
    from ipfs_datasets_py.accelerate_integration import DistributedComputeCoordinator
    
    if DistributedComputeCoordinator is None:
        print("DistributedComputeCoordinator not available")
        return
    
    coordinator = DistributedComputeCoordinator(max_concurrent_tasks=5)
    coordinator.initialize()
    
    print("Coordinator initialized!")
    
    # Submit a few tasks
    tasks = []
    for i in range(3):
        task = coordinator.submit_task(
            task_id=f"demo-task-{i+1}",
            model_name="bert-base-uncased",
            input_data=f"Sample text {i+1}",
            task_type="embedding"
        )
        tasks.append(task)
        print(f"Submitted task: {task.task_id} (status: {task.status.value})")
    
    # Get stats
    stats = coordinator.get_stats()
    print("\nCoordinator statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print()


def demo_environment_control():
    """Demo 6: Environment-based control."""
    print("=" * 70)
    print("Demo 6: Environment-Based Control")
    print("=" * 70)
    
    print("Current environment variables:")
    print(f"  IPFS_ACCELERATE_ENABLED: {os.environ.get('IPFS_ACCELERATE_ENABLED', 'not set (defaults to 1)')}")
    print(f"  IPFS_ACCEL_SKIP_CORE: {os.environ.get('IPFS_ACCEL_SKIP_CORE', 'not set (defaults to 0)')}")
    
    print("\nTo disable accelerate, run:")
    print("  export IPFS_ACCELERATE_ENABLED=0")
    print("  python examples/accelerate_integration_demo.py")
    
    print("\nTo skip heavy imports, run:")
    print("  export IPFS_ACCEL_SKIP_CORE=1")
    print("  python examples/accelerate_integration_demo.py")
    print()


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "IPFS Accelerate Integration Demo" + " " * 20 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    try:
        # Demo 1: Status check
        demo_status_check()
        
        # Demo 2: Manager initialization
        demo_manager_initialization()
        
        # Demo 3: Inference with fallback
        demo_inference_with_fallback()
        
        # Demo 4: Hardware detection
        demo_hardware_detection()
        
        # Demo 5: Distributed coordinator
        demo_distributed_coordinator()
        
        # Demo 6: Environment control
        demo_environment_control()
        
        print("=" * 70)
        print("All demos completed successfully!")
        print("=" * 70)
        print()
        
        print("Next steps:")
        print("  1. Install accelerate: pip install -e '.[accelerate]'")
        print("  2. Try with GPU: Use CUDA-enabled system")
        print("  3. Test distributed: Run on multiple nodes")
        print("  4. Read docs: See ACCELERATE_INTEGRATION_PLAN.md")
        print()
        
    except Exception as e:
        print(f"\n❌ Error running demos: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
