"""
Compute Backend abstraction for hardware-specific inference.

This module provides a unified interface for different compute backends
with automatic hardware detection and optimization.
"""

import logging
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class HardwareType(Enum):
    """Supported hardware types for ML inference."""
    CPU = "cpu"
    CUDA = "cuda"
    ROCM = "rocm"
    OPENVINO = "openvino"
    MPS = "mps"  # Apple Metal Performance Shaders
    WEBNN = "webnn"  # Browser WebNN
    WEBGPU = "webgpu"  # Browser WebGPU
    QUALCOMM = "qualcomm"  # Qualcomm DSP


class ComputeBackend:
    """
    Abstract interface for compute backends.
    
    This class provides a unified interface for different hardware
    acceleration backends, handling model loading, inference, and
    resource management.
    """
    
    def __init__(
        self,
        hardware_type: HardwareType,
        device_id: int = 0,
        options: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize compute backend.
        
        Args:
            hardware_type: Type of hardware to use
            device_id: Device ID for multi-device systems
            options: Backend-specific options
        """
        self.hardware_type = hardware_type
        self.device_id = device_id
        self.options = options or {}
        self._initialized = False
    
    def initialize(self) -> bool:
        """
        Initialize the compute backend.
        
        Returns:
            bool: True if initialization successful
        """
        try:
            # Backend-specific initialization would go here
            self._initialized = True
            logger.info(f"Initialized {self.hardware_type.value} backend")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize {self.hardware_type.value} backend: {e}")
            return False
    
    def is_available(self) -> bool:
        """
        Check if this backend is available on the current system.
        
        Returns:
            bool: True if backend is available
        """
        # This would check for actual hardware/driver availability
        return self._initialized
    
    def load_model(self, model_path: str, **kwargs) -> Any:
        """
        Load a model on this backend.
        
        Args:
            model_path: Path to model files
            **kwargs: Backend-specific loading options
            
        Returns:
            Loaded model object
        """
        if not self._initialized:
            raise RuntimeError(f"Backend {self.hardware_type.value} not initialized")
        
        # Backend-specific model loading
        logger.info(f"Loading model {model_path} on {self.hardware_type.value}")
        return None  # Mock
    
    def run_inference(self, model: Any, input_data: Any, **kwargs) -> Any:
        """
        Run inference on this backend.
        
        Args:
            model: Loaded model object
            input_data: Input data for inference
            **kwargs: Backend-specific inference options
            
        Returns:
            Inference results
        """
        if not self._initialized:
            raise RuntimeError(f"Backend {self.hardware_type.value} not initialized")
        
        # Backend-specific inference
        logger.info(f"Running inference on {self.hardware_type.value}")
        return None  # Mock
    
    def cleanup(self):
        """Clean up backend resources."""
        self._initialized = False
        logger.info(f"Cleaned up {self.hardware_type.value} backend")


def detect_available_hardware() -> List[HardwareType]:
    """
    Detect available hardware on the current system.
    
    Returns:
        list: List of available hardware types
    """
    available = [HardwareType.CPU]  # CPU always available
    
    # Check for CUDA
    try:
        import torch
        if torch.cuda.is_available():
            available.append(HardwareType.CUDA)
    except ImportError:
        pass
    
    # Check for MPS (Apple Silicon)
    try:
        import torch
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            available.append(HardwareType.MPS)
    except (ImportError, AttributeError):
        pass
    
    # Check for OpenVINO
    try:
        import openvino
        available.append(HardwareType.OPENVINO)
    except ImportError:
        pass
    
    return available


def get_compute_backend(
    hardware_type: Optional[HardwareType] = None,
    device_id: int = 0,
    **options
) -> ComputeBackend:
    """
    Get a compute backend instance.
    
    Args:
        hardware_type: Preferred hardware type (auto-detect if None)
        device_id: Device ID for multi-device systems
        **options: Backend-specific options
        
    Returns:
        ComputeBackend: Initialized backend instance
    """
    if hardware_type is None:
        # Auto-detect best available hardware
        available = detect_available_hardware()
        # Prefer GPU over CPU
        if HardwareType.CUDA in available:
            hardware_type = HardwareType.CUDA
        elif HardwareType.MPS in available:
            hardware_type = HardwareType.MPS
        else:
            hardware_type = HardwareType.CPU
    
    backend = ComputeBackend(hardware_type, device_id, options)
    backend.initialize()
    return backend
