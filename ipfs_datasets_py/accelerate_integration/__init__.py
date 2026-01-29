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
from typing import Dict, Any

__version__ = "0.1.0"

logger = logging.getLogger(__name__)

# Check if accelerate should be enabled (default: enabled)
_ACCELERATE_ENABLED_ENV = os.environ.get('IPFS_ACCELERATE_ENABLED', '1').lower()
_ACCELERATE_DISABLED = _ACCELERATE_ENABLED_ENV in ('0', 'false', 'no', 'disabled')


def is_accelerate_available() -> bool:
    """
    Check if ipfs_accelerate_py is available and enabled.
    
    Returns:
        bool: True if accelerate is available and not disabled, False otherwise
    """
    # The integration layer itself is available as long as it is not explicitly
    # disabled. When the optional `ipfs_accelerate_py` backend is missing, the
    # components operate in local fallback mode.
    return not _ACCELERATE_DISABLED


def get_accelerate_status() -> Dict[str, Any]:
    """
    Get detailed status of ipfs_accelerate_py integration.
    
    Returns:
        dict: Status information including availability, enabled state, and any errors
    """
    # Re-read the environment at call time so status reporting reflects
    # runtime configuration changes (e.g., tests using monkeypatch.setenv).
    env_value = os.environ.get('IPFS_ACCELERATE_ENABLED', '1').lower()
    env_disabled = env_value in ('0', 'false', 'no', 'disabled')

    backend_available = False
    backend_import_error = None
    try:
        from .manager import ACCELERATE_AVAILABLE as _BACKEND_AVAILABLE  # noqa: N812
        from .manager import ACCELERATE_IMPORT_ERROR as _BACKEND_IMPORT_ERROR  # noqa: N812

        backend_available = bool(_BACKEND_AVAILABLE)
        backend_import_error = _BACKEND_IMPORT_ERROR
    except Exception as e:  # pragma: no cover
        backend_available = False
        backend_import_error = str(e)

    return {
        "available": backend_available,
        "enabled": not env_disabled,
        "import_error": backend_import_error,
        "env_disabled": env_disabled,
        "env_var": env_value,
    }


# Import core components. These modules provide graceful fallback behavior
# when the optional `ipfs_accelerate_py` backend is not available.
if not _ACCELERATE_DISABLED:
    try:
        from .manager import AccelerateManager
        from .compute_backend import ComputeBackend, get_compute_backend
        from .distributed_coordinator import DistributedComputeCoordinator

        HAVE_ACCELERATE_MANAGER = True
    except Exception as e:
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
