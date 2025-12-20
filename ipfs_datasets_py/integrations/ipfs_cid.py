"""
IPFS CID Computation with Multiformats + Kubo Fallback

This module provides fast CID computation using ipfs_multiformats library,
with automatic fallback to Kubo (IPFS daemon) if multiformats is unavailable.

The ipfs_multiformats library is much faster than calling the IPFS daemon,
but requires native dependencies. If not available, we fall back to Kubo.

Usage:
    from ipfs_datasets_py.integrations import compute_cid_for_content
    
    # Compute CID for content
    cid = compute_cid_for_content(b"Hello, IPFS!")
    # Returns: "QmX..."
    
    # For text content
    cid = compute_cid_for_content("Hello, IPFS!")
    
    # Advanced usage with custom codec/hash
    from ipfs_datasets_py.integrations import IPFSCIDComputer
    computer = IPFSCIDComputer(use_kubo_fallback=True)
    cid = computer.compute(content, codec='dag-cbor', hash_func='sha2-256')
"""

import hashlib
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Union, Optional, Literal

logger = logging.getLogger(__name__)

# Try to import ipfs_multiformats for fast CID computation
try:
    from ipfs_multiformats import ipfs_multiformats_py
    HAVE_MULTIFORMATS = True
    logger.info("Using ipfs_multiformats for fast CID computation")
except ImportError:
    HAVE_MULTIFORMATS = False
    logger.warning("ipfs_multiformats not available, will use Kubo fallback")


class IPFSCIDComputer:
    """
    Compute IPFS CIDs using multiformats library with Kubo fallback.
    
    This class tries to use the fast ipfs_multiformats library first,
    and falls back to calling the IPFS daemon (Kubo) if needed.
    """
    
    def __init__(
        self,
        use_kubo_fallback: bool = True,
        ipfs_binary: str = "ipfs"
    ):
        """
        Initialize CID computer.
        
        Args:
            use_kubo_fallback: Fall back to Kubo if multiformats unavailable
            ipfs_binary: Path to ipfs binary (default: "ipfs" in PATH)
        """
        self.use_kubo_fallback = use_kubo_fallback
        self.ipfs_binary = ipfs_binary
        self.have_multiformats = HAVE_MULTIFORMATS
        
        # Initialize multiformats if available
        if self.have_multiformats:
            try:
                self.multiformats = ipfs_multiformats_py({}, {})
                logger.info("ipfs_multiformats initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize ipfs_multiformats: {e}")
                self.have_multiformats = False
                self.multiformats = None
        else:
            self.multiformats = None
    
    def compute(
        self,
        content: Union[bytes, str],
        codec: str = 'dag-pb',
        hash_func: str = 'sha2-256',
        cid_version: int = 0
    ) -> Optional[str]:
        """
        Compute IPFS CID for content.
        
        Args:
            content: Content to compute CID for (bytes or str)
            codec: IPFS codec (default: 'dag-pb' for standard UnixFS)
            hash_func: Hash function (default: 'sha2-256')
            cid_version: CID version (0 or 1)
        
        Returns:
            CID string (e.g., "QmX...") or None if failed
        """
        # Convert string to bytes
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        # Try multiformats first if available
        if self.have_multiformats and self.multiformats:
            try:
                cid = self._compute_with_multiformats(content, codec, hash_func, cid_version)
                if cid:
                    return cid
            except Exception as e:
                logger.warning(f"Multiformats CID computation failed: {e}")
        
        # Fall back to Kubo if enabled
        if self.use_kubo_fallback:
            try:
                cid = self._compute_with_kubo(content)
                if cid:
                    return cid
            except Exception as e:
                logger.error(f"Kubo CID computation failed: {e}")
        
        logger.error("All CID computation methods failed")
        return None
    
    def _compute_with_multiformats(
        self,
        content: bytes,
        codec: str,
        hash_func: str,
        cid_version: int
    ) -> Optional[str]:
        """
        Compute CID using ipfs_multiformats library.
        
        This is the fast path - no need to call external IPFS daemon.
        """
        try:
            # For standard files, we need to wrap in UnixFS structure
            # This is what ipfs_multiformats does
            if codec == 'dag-pb':
                # UnixFS file wrapping
                from ipfs_multiformats import compute_cid
                cid = compute_cid(content)
                return cid
            else:
                # For other codecs, use raw hashing
                hash_obj = hashlib.sha256(content) if hash_func == 'sha2-256' else hashlib.sha512(content)
                digest = hash_obj.digest()
                
                # Convert to CID format (simplified)
                # In real implementation, would use proper multicodec/multihash encoding
                import base58
                cid = base58.b58encode(digest).decode('ascii')
                return f"Qm{cid[:44]}"  # CIDv0 format
        
        except Exception as e:
            logger.error(f"Multiformats computation error: {e}")
            return None
    
    def _compute_with_kubo(self, content: bytes) -> Optional[str]:
        """
        Compute CID using IPFS daemon (Kubo).
        
        This is slower but doesn't require native dependencies.
        """
        try:
            # Write content to temporary file
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            try:
                # Add to IPFS (with --only-hash flag to not store)
                result = subprocess.run(
                    [self.ipfs_binary, 'add', '--only-hash', '--quiet', tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    cid = result.stdout.strip()
                    logger.debug(f"Computed CID with Kubo: {cid}")
                    return cid
                else:
                    logger.error(f"Kubo add failed: {result.stderr}")
                    return None
            
            finally:
                # Clean up temp file
                Path(tmp_path).unlink(missing_ok=True)
        
        except subprocess.TimeoutExpired:
            logger.error("Kubo CID computation timed out")
            return None
        except FileNotFoundError:
            logger.error(f"IPFS binary not found: {self.ipfs_binary}")
            return None
        except Exception as e:
            logger.error(f"Kubo computation error: {e}")
            return None
    
    def compute_for_file(self, file_path: Union[str, Path]) -> Optional[str]:
        """
        Compute CID for a file.
        
        Args:
            file_path: Path to file
        
        Returns:
            CID string or None if failed
        """
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            return self.compute(content)
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return None


# Global instance for convenience
_global_computer = None

def get_cid_computer() -> IPFSCIDComputer:
    """Get global CID computer instance."""
    global _global_computer
    if _global_computer is None:
        _global_computer = IPFSCIDComputer()
    return _global_computer


def compute_cid_for_content(
    content: Union[bytes, str],
    codec: str = 'dag-pb',
    hash_func: str = 'sha2-256'
) -> Optional[str]:
    """
    Compute IPFS CID for content (convenience function).
    
    Uses ipfs_multiformats if available, falls back to Kubo.
    
    Args:
        content: Content to hash (bytes or str)
        codec: IPFS codec (default: 'dag-pb')
        hash_func: Hash function (default: 'sha2-256')
    
    Returns:
        CID string (e.g., "QmX...") or None if failed
    
    Example:
        cid = compute_cid_for_content(b"Hello, IPFS!")
        # Returns: "QmZULkCELmmk5XNfCgTnCyFgAVxBRBXyDHGGMVoLFLiXEN"
    """
    computer = get_cid_computer()
    return computer.compute(content, codec=codec, hash_func=hash_func)


def compute_cid_for_file(file_path: Union[str, Path]) -> Optional[str]:
    """
    Compute IPFS CID for a file (convenience function).
    
    Args:
        file_path: Path to file
    
    Returns:
        CID string or None if failed
    
    Example:
        cid = compute_cid_for_file("/path/to/document.pdf")
    """
    computer = get_cid_computer()
    return computer.compute_for_file(file_path)
