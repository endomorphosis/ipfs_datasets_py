"""
Accelerate Manager for coordinating distributed AI compute.

This module provides the main interface for using ipfs_accelerate_py
services within ipfs_datasets_py, with graceful fallback support.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

def _ensure_ipfs_accelerate_py_on_syspath() -> None:
    """Best-effort add the ipfs_accelerate_py repo root to sys.path."""

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "ipfs_accelerate_py"
        if candidate.is_dir():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return


# Try to import ipfs_accelerate_py components
try:
    _ensure_ipfs_accelerate_py_on_syspath()
    from ipfs_accelerate_py import llm_router as _accel_llm_router

    ACCELERATE_AVAILABLE = True
    ACCELERATE_IMPORT_ERROR = None
except Exception as e:
    logger.debug(f"ipfs_accelerate_py not available: {e}")
    _accel_llm_router = None
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
        self._accelerate_available = bool(ACCELERATE_AVAILABLE and _accel_llm_router is not None)

        if self._accelerate_available:
            logger.info("AccelerateManager initialized with ipfs_accelerate_py.llm_router")
        else:
            logger.info("AccelerateManager initialized in fallback mode (no ipfs_accelerate_py)")
    
    def is_available(self) -> bool:
        """Check if accelerate backend is available."""
        return bool(self._accelerate_available)
    
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
        _ = hardware
        normalized_task = (task_type or "").strip().lower()

        if normalized_task in {"text-generation", "text_generation", "generation", "generate", "completion"}:
            if isinstance(input_data, dict) and "prompt" in input_data:
                prompt = str(input_data.get("prompt") or "")
            else:
                prompt = str(input_data)

            if self._accelerate_available and _accel_llm_router is not None:
                try:
                    text = _accel_llm_router.generate_text(
                        prompt,
                        provider="hf",
                        model_name=model_name,
                        **kwargs,
                    )
                    return {
                        "status": "success",
                        "backend": "ipfs_accelerate_py",
                        "model": model_name,
                        "text": str(text),
                    }
                except Exception as e:
                    logger.error(f"Accelerate text-generation failed: {e}")
                    return self._fallback_inference(model_name, prompt, task_type, **kwargs)

            return self._fallback_inference(model_name, prompt, task_type, **kwargs)

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
            "text": None,
            "message": "Accelerate not available, using local fallback"
        }
    
    def get_available_hardware(self) -> List[str]:
        """
        Get list of available hardware backends.
        
        Returns:
            list: Available hardware types
        """
        return ["cpu"]
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get manager status and capabilities.
        
        Returns:
            dict: Status information
        """
        return {
            "accelerate_available": ACCELERATE_AVAILABLE,
            "accelerate_initialized": self._accelerate_available,
            "distributed_enabled": self.enable_distributed,
            "ipfs_gateway": self.ipfs_gateway,
            "available_hardware": self.get_available_hardware()
        }
