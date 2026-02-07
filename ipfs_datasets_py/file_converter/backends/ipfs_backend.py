"""
IPFS Backend for File Converter.

This backend integrates IPFS storage with file conversion, allowing:
- Store converted files on IPFS
- Content-addressable storage
- Distributed retrieval
- Pin management
- Graceful fallback to local when IPFS unavailable

Environment Variables:
- IPFS_GATEWAY: IPFS gateway URL (default: http://127.0.0.1:5001)
- IPFS_STORAGE_ENABLED: Enable IPFS storage (default: 1)
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
import anyio

logger = logging.getLogger(__name__)

def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _ipfs_storage_enabled() -> bool:
    """Whether the IPFS backend should be enabled in this process.

    Importantly, this must NOT trigger heavy imports at module import time.
    """

    enabled_env = os.environ.get("IPFS_STORAGE_ENABLED", "1").strip().lower()
    if enabled_env in {"0", "false", "no", "disabled"}:
        return False

    # If IPFS Kit integration is explicitly disabled, keep the IPFS backend off.
    if _truthy(os.environ.get("IPFS_KIT_DISABLE")):
        return False

    # Benchmarks/tests should remain hermetic and avoid daemon/binary startup.
    if _truthy(os.environ.get("IPFS_DATASETS_PY_BENCHMARK")):
        return False

    return True


def _import_ipfs_kit_py() -> tuple[object | None, str | None]:
    """Best-effort import of ipfs_kit_py, returning (callable, error_message)."""

    # Try installed package first.
    try:
        from ipfs_kit_py import ipfs_kit_py as ipfs_kit_callable  # type: ignore
        return ipfs_kit_callable, None
    except Exception as exc:
        installed_error = exc

    # Fall back to workspace checkout if present.
    try:
        repo_root = Path(__file__).resolve().parents[4]
        ipfs_kit_path = repo_root / "ipfs_kit_py"
        if ipfs_kit_path.exists() and str(ipfs_kit_path) not in sys.path:
            sys.path.insert(0, str(ipfs_kit_path))
        from ipfs_kit_py import ipfs_kit_py as ipfs_kit_callable  # type: ignore
        return ipfs_kit_callable, None
    except Exception as exc:
        # Preserve the most relevant error for debugging.
        return None, f"{installed_error!r}; {exc!r}"


# Legacy module-level status (computed lazily in IPFSBackend.__init__).
IPFS_AVAILABLE = False
IPFS_IMPORT_ERROR: str | None = None
ipfs_kit = None


class IPFSBackend:
    """
    IPFS storage backend for file converter.
    
    Provides IPFS storage integration with graceful fallback to local operations
    when IPFS is unavailable.
    """
    
    def __init__(
        self,
        gateway_url: Optional[str] = None,
        enable_pinning: bool = True,
        auto_pin_on_add: bool = False
    ):
        """
        Initialize IPFS backend.
        
        Args:
            gateway_url: IPFS gateway URL (default: from env or http://127.0.0.1:5001)
            enable_pinning: Whether to enable pin management
            auto_pin_on_add: Automatically pin files when adding to IPFS
        """
        self.gateway_url = gateway_url or os.environ.get('IPFS_GATEWAY', 'http://127.0.0.1:5001')
        self.enable_pinning = enable_pinning
        self.auto_pin_on_add = auto_pin_on_add
        self.ipfs_client = None

        global IPFS_AVAILABLE, IPFS_IMPORT_ERROR, ipfs_kit
        if _ipfs_storage_enabled():
            ipfs_kit_callable, err = _import_ipfs_kit_py()
            ipfs_kit = ipfs_kit_callable
            IPFS_IMPORT_ERROR = err
            IPFS_AVAILABLE = ipfs_kit_callable is not None

        if IPFS_AVAILABLE and ipfs_kit:
            try:
                self.ipfs_client = ipfs_kit(resources={"ipfs_gateway": self.gateway_url})
                logger.info(f"IPFS backend initialized with gateway: {self.gateway_url}")
            except Exception as e:
                logger.warning(f"Failed to initialize IPFS client: {e}")
                self.ipfs_client = None
        else:
            logger.info("IPFS backend initialized in local-only mode")
    
    def is_available(self) -> bool:
        """Check if IPFS backend is available and connected."""
        return self.ipfs_client is not None
    
    async def add_file(
        self,
        file_path: Path,
        pin: Optional[bool] = None
    ) -> Optional[str]:
        """
        Add a file to IPFS.
        
        Args:
            file_path: Path to file to add
            pin: Whether to pin the file (default: use auto_pin_on_add)
            
        Returns:
            str: IPFS CID if successful, None if failed or unavailable
        """
        if not self.ipfs_client:
            logger.debug(f"IPFS unavailable, skipping add for {file_path}")
            return None
        
        should_pin = pin if pin is not None else self.auto_pin_on_add
        
        try:
            # Add file to IPFS
            result = await anyio.to_thread.run_sync(
                self.ipfs_client.add,
                str(file_path)
            )
            
            cid = result.get('Hash') or result.get('cid')
            logger.info(f"Added {file_path.name} to IPFS: {cid}")
            
            # Pin if requested
            if should_pin and self.enable_pinning and cid:
                await self.pin_file(cid)
            
            return cid
        except Exception as e:
            logger.error(f"Failed to add file to IPFS: {e}")
            return None
    
    async def get_file(
        self,
        cid: str,
        output_path: Path
    ) -> bool:
        """
        Retrieve a file from IPFS.
        
        Args:
            cid: IPFS CID to retrieve
            output_path: Where to save the retrieved file
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.ipfs_client:
            logger.debug(f"IPFS unavailable, cannot retrieve {cid}")
            return False
        
        try:
            # Get file from IPFS
            content = await anyio.to_thread.run_sync(
                self.ipfs_client.cat,
                cid
            )
            
            # Write to output path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
            
            logger.info(f"Retrieved {cid} from IPFS to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to retrieve file from IPFS: {e}")
            return False
    
    async def pin_file(self, cid: str) -> bool:
        """
        Pin a file in IPFS.
        
        Args:
            cid: IPFS CID to pin
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.ipfs_client or not self.enable_pinning:
            return False
        
        try:
            await anyio.to_thread.run_sync(
                self.ipfs_client.pin_add,
                cid
            )
            logger.info(f"Pinned {cid}")
            return True
        except Exception as e:
            logger.error(f"Failed to pin {cid}: {e}")
            return False
    
    async def unpin_file(self, cid: str) -> bool:
        """
        Unpin a file in IPFS.
        
        Args:
            cid: IPFS CID to unpin
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.ipfs_client or not self.enable_pinning:
            return False
        
        try:
            await anyio.to_thread.run_sync(
                self.ipfs_client.pin_rm,
                cid
            )
            logger.info(f"Unpinned {cid}")
            return True
        except Exception as e:
            logger.error(f"Failed to unpin {cid}: {e}")
            return False
    
    async def list_pins(self) -> List[str]:
        """
        List all pinned CIDs.
        
        Returns:
            list: List of pinned CIDs
        """
        if not self.ipfs_client or not self.enable_pinning:
            return []
        
        try:
            result = await anyio.to_thread.run_sync(
                self.ipfs_client.pin_ls
            )
            return list(result.get('Keys', {}).keys()) if isinstance(result, dict) else []
        except Exception as e:
            logger.error(f"Failed to list pins: {e}")
            return []
    
    def get_gateway_url(self, cid: str) -> str:
        """
        Get HTTP gateway URL for a CID.
        
        Args:
            cid: IPFS CID
            
        Returns:
            str: HTTP gateway URL
        """
        # Use public gateway if local is not available
        if self.ipfs_client:
            base_url = self.gateway_url.replace(':5001', ':8080')
        else:
            base_url = 'https://ipfs.io'
        
        return f"{base_url}/ipfs/{cid}"
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get backend status.
        
        Returns:
            dict: Status information
        """
        return {
            "available": IPFS_AVAILABLE,
            "connected": self.ipfs_client is not None,
            "gateway_url": self.gateway_url,
            "pinning_enabled": self.enable_pinning,
            "auto_pin": self.auto_pin_on_add,
            "import_error": IPFS_IMPORT_ERROR
        }


# Convenience function
def get_ipfs_backend(
    gateway_url: Optional[str] = None,
    **kwargs
) -> IPFSBackend:
    """
    Get an IPFS backend instance.
    
    Args:
        gateway_url: IPFS gateway URL
        **kwargs: Additional IPFSBackend parameters
        
    Returns:
        IPFSBackend: IPFS backend instance
    """
    return IPFSBackend(gateway_url=gateway_url, **kwargs)
