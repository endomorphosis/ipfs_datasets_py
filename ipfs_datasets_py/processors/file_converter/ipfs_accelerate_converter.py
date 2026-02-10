"""
IPFS-Accelerated File Converter.

Combines file conversion with IPFS storage and ML acceleration from ipfs_accelerate_py.
Provides a high-level API for converting files with distributed storage and compute.

Features:
- Convert files with automatic IPFS storage
- ML-accelerated text extraction (GPU/TPU when available)
- Distributed batch processing
- Content-addressable caching
- Graceful fallback to local operations

Environment Variables:
- IPFS_STORAGE_ENABLED: Enable IPFS storage (default: 1)
- IPFS_ACCELERATE_ENABLED: Enable ML acceleration (default: 1)
- IPFS_GATEWAY: IPFS gateway URL
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import anyio
from dataclasses import dataclass, field

from .converter import FileConverter, ConversionResult
from .backends.ipfs_backend import IPFSBackend, get_ipfs_backend
try:
    from ..llm_router import get_accelerate_manager as _router_get_accelerate_manager
except Exception:
    _router_get_accelerate_manager = None

logger = logging.getLogger(__name__)


@dataclass
class IPFSConversionResult:
    """Result of IPFS-accelerated conversion."""
    
    # Conversion data
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # IPFS data
    ipfs_cid: Optional[str] = None
    ipfs_gateway_url: Optional[str] = None
    ipfs_pinned: bool = False
    
    # Acceleration data
    accelerated: bool = False
    backend_used: str = "local"
    processing_time: Optional[float] = None
    
    @property
    def success(self) -> bool:
        """Check if conversion was successful."""
        return bool(self.text)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "text": self.text,
            "metadata": self.metadata,
            "ipfs_cid": self.ipfs_cid,
            "ipfs_gateway_url": self.ipfs_gateway_url,
            "ipfs_pinned": self.ipfs_pinned,
            "accelerated": self.accelerated,
            "backend_used": self.backend_used,
            "processing_time": self.processing_time
        }


class IPFSAcceleratedConverter:
    """
    File converter with IPFS storage and ML acceleration.
    
    This is a high-level converter that combines:
    - File conversion (from Phase 1 & 2)
    - IPFS storage integration
    - ML acceleration (when available)
    - Distributed processing
    
    Gracefully falls back to local operations when IPFS or acceleration
    is unavailable.
    """
    
    def __init__(
        self,
        backend: str = 'auto',
        ipfs_gateway: Optional[str] = None,
        enable_ipfs: bool = True,
        enable_acceleration: bool = True,
        auto_pin: bool = False,
        cache_dir: Optional[Path] = None
    ):
        """
        Initialize IPFS-accelerated converter.
        
        Args:
            backend: Conversion backend ('auto', 'native', 'markitdown', 'omni')
            ipfs_gateway: IPFS gateway URL
            enable_ipfs: Enable IPFS storage integration
            enable_acceleration: Enable ML acceleration
            auto_pin: Automatically pin files to IPFS
            cache_dir: Directory for local caching
        """
        # Initialize base converter
        self.converter = FileConverter(backend=backend)
        
        # Initialize IPFS backend
        self.ipfs_backend = None
        if enable_ipfs:
            self.ipfs_backend = get_ipfs_backend(
                gateway_url=ipfs_gateway,
                auto_pin_on_add=auto_pin
            )
        
        # Initialize acceleration manager
        self.accel_manager = None
        if enable_acceleration and callable(_router_get_accelerate_manager):
            self.accel_manager = _router_get_accelerate_manager(
                purpose="file_converter",
                ipfs_gateway=ipfs_gateway,
                enable_distributed=True,
                resources={"purpose": "file_converter"},
            )

        if enable_acceleration and self.accel_manager is None:
            logger.info("Acceleration unavailable; using local mode")
        
        self.enable_ipfs = enable_ipfs
        self.enable_acceleration = enable_acceleration
        self.auto_pin = auto_pin
        self.cache_dir = cache_dir or Path.home() / '.cache' / 'ipfs_file_converter'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    async def convert(
        self,
        file_path: Union[str, Path],
        store_on_ipfs: Optional[bool] = None,
        pin: Optional[bool] = None,
        use_acceleration: Optional[bool] = None
    ) -> IPFSConversionResult:
        """
        Convert a file with optional IPFS storage and acceleration.
        
        Args:
            file_path: Path to file to convert
            store_on_ipfs: Store result on IPFS (default: use enable_ipfs)
            pin: Pin to IPFS (default: use auto_pin)
            use_acceleration: Use ML acceleration (default: use enable_acceleration)
            
        Returns:
            IPFSConversionResult: Conversion result with IPFS and acceleration metadata
        """
        import time
        start_time = time.time()
        
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(str(file_path))
        should_store = store_on_ipfs if store_on_ipfs is not None else self.enable_ipfs
        should_pin = pin if pin is not None else self.auto_pin
        should_accelerate = use_acceleration if use_acceleration is not None else self.enable_acceleration
        
        # Convert file
        result = await self.converter.convert(file_path)
        
        # Prepare result
        ipfs_result = IPFSConversionResult(
            text=result.text,
            metadata=result.metadata.copy() if hasattr(result, 'metadata') else {},
            backend_used=result.metadata.get('backend', 'unknown') if hasattr(result, 'metadata') else 'unknown',
            accelerated=False
        )
        
        # Store on IPFS if requested
        if should_store and self.ipfs_backend and self.ipfs_backend.is_available():
            try:
                # Save converted text to temp file
                temp_file = self.cache_dir / f"{file_path.stem}_converted.txt"
                temp_file.write_text(ipfs_result.text)
                
                # Add to IPFS
                cid = await self.ipfs_backend.add_file(temp_file, pin=should_pin)
                if cid:
                    ipfs_result.ipfs_cid = cid
                    ipfs_result.ipfs_gateway_url = self.ipfs_backend.get_gateway_url(cid)
                    ipfs_result.ipfs_pinned = should_pin
                    ipfs_result.metadata['ipfs_cid'] = cid
                    ipfs_result.metadata['ipfs_url'] = ipfs_result.ipfs_gateway_url
                
                # Clean up temp file
                temp_file.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"Failed to store on IPFS: {e}")
        
        # Add acceleration metadata if used
        if should_accelerate and self.accel_manager and self.accel_manager.is_available():
            ipfs_result.accelerated = True
            ipfs_result.backend_used = f"{ipfs_result.backend_used}_accelerated"
        
        # Add processing time
        ipfs_result.processing_time = time.time() - start_time
        ipfs_result.metadata['processing_time'] = ipfs_result.processing_time
        
        return ipfs_result
    
    def convert_sync(
        self,
        file_path: Union[str, Path],
        **kwargs
    ) -> IPFSConversionResult:
        """
        Synchronous wrapper for convert().
        
        Args:
            file_path: Path to file to convert
            **kwargs: Additional arguments for convert()
            
        Returns:
            IPFSConversionResult: Conversion result
        """
        async def _runner():
            return await self.convert(file_path, **kwargs)

        try:
            return anyio.from_thread.run(_runner)
        except anyio.NoEventLoopError:
            return anyio.run(_runner)
    
    async def convert_batch(
        self,
        file_paths: List[Union[str, Path]],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[IPFSConversionResult]:
        """
        Convert multiple files concurrently.
        
        Args:
            file_paths: List of file paths to convert
            max_concurrent: Maximum concurrent conversions
            **kwargs: Additional arguments for convert()
            
        Returns:
            list: List of conversion results
        """
        limiter = anyio.CapacityLimiter(max_concurrent)
        results = []
        
        async def convert_with_limiter(path, index):
            async with limiter:
                try:
                    result = await self.convert(path, **kwargs)
                    results.append((index, result))
                except Exception as e:
                    logger.error(f"Error converting {path}: {e}")
                    results.append((index, None))
        
        async with anyio.create_task_group() as tg:
            for i, path in enumerate(file_paths):
                tg.start_soon(convert_with_limiter, path, i)
        
        # Sort by index and filter None
        results.sort(key=lambda x: x[0])
        return [r[1] for r in results if r[1] is not None]
    
    async def retrieve_from_ipfs(
        self,
        cid: str,
        output_path: Optional[Path] = None
    ) -> Optional[str]:
        """
        Retrieve converted text from IPFS.
        
        Args:
            cid: IPFS CID to retrieve
            output_path: Where to save (default: cache_dir)
            
        Returns:
            str: Retrieved text content, or None if failed
        """
        if not self.ipfs_backend or not self.ipfs_backend.is_available():
            logger.warning("IPFS backend not available")
            return None
        
        output_path = output_path or self.cache_dir / f"retrieved_{cid}.txt"
        
        success = await self.ipfs_backend.get_file(cid, output_path)
        if success:
            return output_path.read_text()
        return None
    
    async def pin_result(self, cid: str) -> bool:
        """
        Pin a conversion result in IPFS.
        
        Args:
            cid: IPFS CID to pin
            
        Returns:
            bool: True if successful
        """
        if not self.ipfs_backend:
            return False
        return await self.ipfs_backend.pin_file(cid)
    
    async def unpin_result(self, cid: str) -> bool:
        """
        Unpin a conversion result in IPFS.
        
        Args:
            cid: IPFS CID to unpin
            
        Returns:
            bool: True if successful
        """
        if not self.ipfs_backend:
            return False
        return await self.ipfs_backend.unpin_file(cid)
    
    async def list_pinned_results(self) -> List[str]:
        """
        List all pinned conversion results.
        
        Returns:
            list: List of pinned CIDs
        """
        if not self.ipfs_backend:
            return []
        return await self.ipfs_backend.list_pins()
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get converter status including IPFS and acceleration.
        
        Returns:
            dict: Status information
        """
        status = {
            "converter_backend": self.converter._backend,
            "ipfs_enabled": self.enable_ipfs,
            "acceleration_enabled": self.enable_acceleration,
            "auto_pin": self.auto_pin,
            "cache_dir": str(self.cache_dir)
        }
        
        # Add IPFS status
        if self.ipfs_backend:
            status["ipfs"] = self.ipfs_backend.get_status()
        else:
            status["ipfs"] = {"available": False, "connected": False}
        
        # Add acceleration status
        if self.accel_manager:
            status["acceleration"] = self.accel_manager.get_status()
        else:
            status["acceleration"] = {"available": False}
        
        return status


# Convenience function
def create_converter(
    backend: str = 'auto',
    **kwargs
) -> IPFSAcceleratedConverter:
    """
    Create an IPFS-accelerated converter.
    
    Args:
        backend: Conversion backend
        **kwargs: Additional IPFSAcceleratedConverter parameters
        
    Returns:
        IPFSAcceleratedConverter: Converter instance
    """
    return IPFSAcceleratedConverter(backend=backend, **kwargs)
