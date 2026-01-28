"""
IPFS Accelerate Integration Module.

This module provides integration between ipfs_datasets_py and ipfs_accelerate_py
for distributed AI compute services with graceful fallbacks when the accelerate
package is disabled or unavailable.

Key Features:
- Hardware-accelerated ML inference (CPU, GPU, OpenVINO, WebNN, WebGPU)
- Distributed compute coordination across IPFS network
- Graceful fallback to local compute when accelerate is unavailable
- Environment-based enable/disable control (IPFS_ACCELERATE_ENABLED)
- CI/CD friendly with automatic detection and fallback

Environment Variables:
- IPFS_ACCELERATE_ENABLED: Set to '0', 'false', or 'no' to disable (default: enabled if available)
- IPFS_ACCEL_SKIP_CORE: Skip heavy core imports for faster load times
- IPFS_ACCEL_IMPORT_EAGER: Eagerly import model manager components

Usage:
    from ipfs_datasets_py.accelerate_integration import (
        AccelerateManager,
        is_accelerate_available,
        get_compute_backend
    )
    
    # Check if accelerate is available and enabled
    if is_accelerate_available():
        manager = AccelerateManager()
        result = manager.run_inference(model_name, input_data)
    else:
        # Fallback to local compute
        result = run_local_inference(model_name, input_data)
"""

import os
import logging
from typing import Dict, Any, Optional, List, Union
from pathlib import Path

__version__ = "0.1.0"

logger = logging.getLogger(__name__)

# Check if accelerate should be enabled (default: yes if available)
_ACCELERATE_ENABLED_ENV = os.environ.get('IPFS_ACCELERATE_ENABLED', '1').lower()
_ACCELERATE_DISABLED = _ACCELERATE_ENABLED_ENV in ('0', 'false', 'no', 'disabled')

# Try to import ipfs_accelerate_py
_ACCELERATE_AVAILABLE = False
_ACCELERATE_IMPORT_ERROR = None

if not _ACCELERATE_DISABLED:
    try:
        # Set environment to skip heavy imports for faster detection
        os.environ.setdefault('IPFS_ACCEL_SKIP_CORE', '0')
        
        # Import from the submodule location
        import sys
        _repo_root = Path(__file__).resolve().parent.parent.parent
        _accelerate_path = _repo_root / "ipfs_accelerate_py"
        
        if _accelerate_path.exists():
            sys.path.insert(0, str(_accelerate_path))
            
        # Try importing the module
        try:
            from ipfs_accelerate_py import (
                original_ipfs_accelerate_py,
                webnn_webgpu_available
            )
            _ACCELERATE_AVAILABLE = True
            logger.info("ipfs_accelerate_py is available and enabled")
        except ImportError as e:
            _ACCELERATE_IMPORT_ERROR = str(e)
            logger.debug(f"ipfs_accelerate_py import failed: {e}")
            
    except Exception as e:
        _ACCELERATE_IMPORT_ERROR = str(e)
        logger.debug(f"Failed to setup ipfs_accelerate_py: {e}")
else:
    logger.info("ipfs_accelerate_py is disabled via IPFS_ACCELERATE_ENABLED environment variable")


def is_accelerate_available() -> bool:
    """
    Check if ipfs_accelerate_py is available and enabled.
    
    Returns:
        bool: True if accelerate is available and not disabled, False otherwise
    """
    return _ACCELERATE_AVAILABLE and not _ACCELERATE_DISABLED


def get_accelerate_status() -> Dict[str, Any]:
    """
    Get detailed status of ipfs_accelerate_py integration.
    
    Returns:
        dict: Status information including availability, enabled state, and any errors
    """
    return {
        "available": _ACCELERATE_AVAILABLE,
        "enabled": not _ACCELERATE_DISABLED,
        "import_error": _ACCELERATE_IMPORT_ERROR,
        "env_disabled": _ACCELERATE_DISABLED,
        "env_var": _ACCELERATE_ENABLED_ENV
    }


# Import core components based on availability
if is_accelerate_available():
    try:
        from .manager import AccelerateManager
        from .compute_backend import ComputeBackend, get_compute_backend
        from .distributed_coordinator import DistributedComputeCoordinator
        
        HAVE_ACCELERATE_MANAGER = True
    except ImportError as e:
        logger.warning(f"Failed to import accelerate integration components: {e}")
        HAVE_ACCELERATE_MANAGER = False
        AccelerateManager = None
        ComputeBackend = None
        get_compute_backend = None
        DistributedComputeCoordinator = None
else:
    HAVE_ACCELERATE_MANAGER = False
    AccelerateManager = None
    ComputeBackend = None
    get_compute_backend = None
    DistributedComputeCoordinator = None


__all__ = [
    # Status functions
    'is_accelerate_available',
    'get_accelerate_status',
    
    # Core components (may be None if not available)
    'AccelerateManager',
    'ComputeBackend',
    'get_compute_backend',
    'DistributedComputeCoordinator',
    
    # Status flags
    'HAVE_ACCELERATE_MANAGER',
]
