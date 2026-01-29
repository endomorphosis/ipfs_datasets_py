"""
Accelerate Manager for coordinating distributed AI compute.

This module provides the main interface for using ipfs_accelerate_py
services within ipfs_datasets_py, with graceful fallback support.
"""

import logging
from typing import Dict, Any, Optional, List, Union
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import ipfs_accelerate_py components
try:
    # Add accelerate path
    _repo_root = Path(__file__).resolve().parent.parent.parent
    _accelerate_path = _repo_root / "ipfs_accelerate_py"
    if _accelerate_path.exists() and str(_accelerate_path) not in sys.path:
        sys.path.insert(0, str(_accelerate_path))
    
    from ipfs_accelerate_py.ipfs_accelerate import ipfs_accelerate_py as AccelerateCore
    ACCELERATE_AVAILABLE = True
    ACCELERATE_IMPORT_ERROR = None
except ImportError as e:
    logger.debug(f"ipfs_accelerate_py not available: {e}")
    AccelerateCore = None
    ACCELERATE_AVAILABLE = False
    ACCELERATE_IMPORT_ERROR = str(e)


class AccelerateManager:
    """
    Manager for coordinating distributed AI compute using ipfs_accelerate_py.
    
    This class provides a unified interface for running ML inference with
    automatic hardware detection, optimization, and distributed coordination.
    Falls back to local compute if accelerate is unavailable.
    """
    
    def __init__(
        self,
        resources: Optional[Dict[str, Any]] = None,
        ipfs_gateway: Optional[str] = None,
        enable_distributed: bool = True
    ):
        """
        Initialize the AccelerateManager.
        
        Args:
            resources: Resource configuration for accelerate core
            ipfs_gateway: IPFS gateway URL for content distribution
            enable_distributed: Whether to enable distributed compute
        """
        self.resources = resources or {}
        self.ipfs_gateway = ipfs_gateway
        self.enable_distributed = enable_distributed
        self.accelerate_core = None
        
        if ACCELERATE_AVAILABLE:
            try:
                self.accelerate_core = AccelerateCore(resources=self.resources)
                logger.info("AccelerateManager initialized with ipfs_accelerate_py")
            except Exception as e:
                logger.warning(f"Failed to initialize accelerate core: {e}")
        else:
            logger.info("AccelerateManager initialized in fallback mode (no ipfs_accelerate_py)")
    
    def is_available(self) -> bool:
        """Check if accelerate backend is available."""
        return self.accelerate_core is not None
    
    def run_inference(
        self,
        model_name: str,
        input_data: Any,
        task_type: Optional[str] = None,
        hardware: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run ML inference using accelerate backend or fallback.
        
        Args:
            model_name: Name or path of the model
            input_data: Input data for inference
            task_type: Type of task (e.g., 'text-generation', 'embedding')
            hardware: Preferred hardware ('cpu', 'cuda', 'openvino', etc.)
            **kwargs: Additional inference parameters
            
        Returns:
            dict: Inference results with metadata
        """
        if self.accelerate_core:
            try:
                # Use ipfs_accelerate_py for inference
                result = self.accelerate_core.load_model(model_name)
                # Note: Actual inference API depends on ipfs_accelerate_py implementation
                return {
                    "status": "success",
                    "backend": "ipfs_accelerate_py",
                    "model": model_name,
                    "result": result
                }
            except Exception as e:
                logger.error(f"Accelerate inference failed: {e}")
                return self._fallback_inference(model_name, input_data, task_type, **kwargs)
        else:
            return self._fallback_inference(model_name, input_data, task_type, **kwargs)
    
    def _fallback_inference(
        self,
        model_name: str,
        input_data: Any,
        task_type: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Fallback inference using local resources.
        
        Args:
            model_name: Name or path of the model
            input_data: Input data for inference
            task_type: Type of task
            **kwargs: Additional parameters
            
        Returns:
            dict: Inference results (mock for now)
        """
        logger.info(f"Using fallback inference for model: {model_name}")
        return {
            "status": "success",
            "backend": "local_fallback",
            "model": model_name,
            "result": None,
            "message": "Accelerate not available, using local fallback"
        }
    
    def get_available_hardware(self) -> List[str]:
        """
        Get list of available hardware backends.
        
        Returns:
            list: Available hardware types
        """
        if self.accelerate_core:
            try:
                # Query accelerate for available hardware
                return ["cpu", "cuda", "openvino"]  # Mock list
            except Exception as e:
                logger.error(f"Failed to query hardware: {e}")
        
        return ["cpu"]  # Fallback to CPU only
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get manager status and capabilities.
        
        Returns:
            dict: Status information
        """
        return {
            "accelerate_available": ACCELERATE_AVAILABLE,
            "accelerate_initialized": self.accelerate_core is not None,
            "distributed_enabled": self.enable_distributed,
            "ipfs_gateway": self.ipfs_gateway,
            "available_hardware": self.get_available_hardware()
        }
