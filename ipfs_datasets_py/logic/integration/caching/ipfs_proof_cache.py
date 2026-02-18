"""
IPFS-backed distributed proof cache.

This module implements a distributed caching layer using IPFS for persistent storage
and synchronization across multiple nodes.

Features:
- IPFS content-addressable storage for proofs
- Distributed cache synchronization
- Automatic fallback to local cache
- Pin management for important proofs
- Cache statistics tracking

Example:
    >>> from ipfs_datasets_py.logic.integration.ipfs_proof_cache import IPFSProofCache
    >>> 
    >>> # Initialize with IPFS connection
    >>> cache = IPFSProofCache(ipfs_host='127.0.0.1', ipfs_port=5001)
    >>> 
    >>> # Store proof (automatically uploads to IPFS)
    >>> cache.put("formula_hash", proof_result, ttl=7200, pin=True)
    >>> 
    >>> # Retrieve proof (from local or IPFS)
    >>> cached = cache.get("formula_hash")
    >>> 
    >>> # Sync with IPFS network
    >>> cache.sync_from_ipfs()
"""

import json
import time
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from pathlib import Path

try:
    import ipfshttpclient
    IPFS_AVAILABLE = True
except ImportError:
    IPFS_AVAILABLE = False

from ...common.proof_cache import ProofCache, CachedProofResult as CachedProof, get_global_cache

logger = logging.getLogger(__name__)


@dataclass
class IPFSCachedProof(CachedProof):
    """
    Extended cached proof with IPFS information.
    
    Attributes:
        formula: The formula that was proven
        result: The proof result
        timestamp: When the proof was cached
        ttl: Time-to-live in seconds
        ipfs_cid: IPFS Content ID (hash) of the cached proof
        pinned: Whether this proof is pinned in IPFS
    """
    ipfs_cid: Optional[str] = None
    pinned: bool = False


class IPFSProofCache(ProofCache):
    """
    IPFS-backed distributed proof cache with automatic synchronization.
    
    This cache extends the local ProofCache with IPFS storage capabilities,
    enabling distributed caching across multiple nodes while maintaining
    backward compatibility and graceful fallback.
    
    Features:
        - Automatic IPFS upload for new proofs
        - Distributed cache synchronization
        - Pin management for important proofs
        - Local fallback when IPFS unavailable
        - Statistics tracking for IPFS operations
    
    Args:
        max_size: Maximum number of proofs to cache locally (default: 1000)
        ttl: Default time-to-live in seconds (default: 3600)
        ipfs_host: IPFS API host (default: '127.0.0.1')
        ipfs_port: IPFS API port (default: 5001)
        enable_ipfs: Enable IPFS backend (default: True if available)
        cache_dir: Directory for local cache persistence
    
    Example:
        >>> cache = IPFSProofCache(
        ...     max_size=5000,
        ...     ttl=7200,
        ...     ipfs_host='ipfs.example.com',
        ...     enable_ipfs=True
        ... )
        >>> cache.put("formula", result, pin=True)  # Pins to IPFS
        >>> cache.sync_from_ipfs()  # Sync from network
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        ttl: int = 3600,
        ipfs_host: str = '127.0.0.1',
        ipfs_port: int = 5001,
        enable_ipfs: bool = True,
        cache_dir: Optional[Path] = None
    ):
        """Initialize IPFS-backed cache."""
        super().__init__(max_size=max_size, ttl=ttl, cache_dir=cache_dir)
        
        self.ipfs_host = ipfs_host
        self.ipfs_port = ipfs_port
        self.enable_ipfs = enable_ipfs and IPFS_AVAILABLE
        self.ipfs_client: Optional[Any] = None
        
        # IPFS-specific statistics
        self.ipfs_uploads = 0
        self.ipfs_downloads = 0
        self.ipfs_errors = 0
        self.pinned_count = 0
        
        # Initialize IPFS client
        if self.enable_ipfs:
            self._init_ipfs_client()
        else:
            if enable_ipfs and not IPFS_AVAILABLE:
                logger.warning(
                    "IPFS backend requested but ipfshttpclient not installed. "
                    "Install with: pip install ipfshttpclient"
                )
            logger.info("IPFS backend disabled, using local cache only")
    
    def _init_ipfs_client(self) -> None:
        """Initialize IPFS HTTP client connection."""
        try:
            self.ipfs_client = ipfshttpclient.connect(
                f'/ip4/{self.ipfs_host}/tcp/{self.ipfs_port}/http'
            )
            # Test connection
            self.ipfs_client.id()
            logger.info(f"Connected to IPFS node at {self.ipfs_host}:{self.ipfs_port}")
        except Exception as e:
            logger.error(f"Failed to connect to IPFS: {e}")
            logger.warning("Falling back to local cache only")
            self.enable_ipfs = False
            self.ipfs_client = None
    
    def put(
        self,
        formula: str,
        result: Dict[str, Any],
        ttl: Optional[int] = None,
        pin: bool = False
    ) -> None:
        """
        Store a proof result in cache and optionally upload to IPFS.
        
        Args:
            formula: The formula that was proven
            result: The proof result to cache
            ttl: Time-to-live in seconds (uses default if None)
            pin: Whether to pin this proof in IPFS (default: False)
        
        Example:
            >>> cache.put("∀x P(x)", {"success": True}, ttl=7200, pin=True)
        """
        # Store in local cache first
        super().put(formula, result, ttl)
        
        # Upload to IPFS if enabled
        if self.enable_ipfs and self.ipfs_client:
            try:
                self._upload_to_ipfs(formula, result, pin)
            except Exception as e:
                logger.error(f"Failed to upload to IPFS: {e}")
                self.ipfs_errors += 1
    
    def _upload_to_ipfs(
        self,
        formula: str,
        result: Dict[str, Any],
        pin: bool = False
    ) -> Optional[str]:
        """Upload proof to IPFS and return CID."""
        if not self.ipfs_client:
            return None
        
        try:
            # Prepare proof data
            proof_data = {
                'formula': formula,
                'result': result,
                'timestamp': time.time(),
                'version': '1.0'
            }
            
            # Upload to IPFS (convert to JSON for upload)
            proof_data_json = json.dumps(proof_data, indent=2)
            res = self.ipfs_client.add_json(json.loads(proof_data_json))
            cid = res
            
            self.ipfs_uploads += 1
            
            # Pin if requested
            if pin:
                self.ipfs_client.pin.add(cid)
                self.pinned_count += 1
                logger.info(f"Pinned proof to IPFS: {cid}")
            
            # Update local cache with IPFS info
            if formula in self._cache:
                cached = self._cache[formula]
                if isinstance(cached, IPFSCachedProof):
                    cached.ipfs_cid = cid
                    cached.pinned = pin
            
            logger.debug(f"Uploaded proof to IPFS: {cid}")
            return cid
            
        except Exception as e:
            logger.error(f"Error uploading to IPFS: {e}")
            self.ipfs_errors += 1
            return None
    
    def get_from_ipfs(self, cid: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve proof from IPFS by CID.
        
        Args:
            cid: IPFS Content ID
        
        Returns:
            Proof data if found, None otherwise
        
        Example:
            >>> proof = cache.get_from_ipfs("QmXxx...")
        """
        if not self.enable_ipfs or not self.ipfs_client:
            return None
        
        try:
            proof_data = self.ipfs_client.get_json(cid)
            self.ipfs_downloads += 1
            return proof_data
        except Exception as e:
            logger.error(f"Error retrieving from IPFS {cid}: {e}")
            self.ipfs_errors += 1
            return None
    
    def sync_from_ipfs(self, cid_list: Optional[List[str]] = None) -> int:
        """
        Sync proofs from IPFS network into local cache.
        
        Args:
            cid_list: List of CIDs to sync (default: sync all pinned)
        
        Returns:
            Number of proofs synced
        
        Example:
            >>> synced = cache.sync_from_ipfs()
            >>> print(f"Synced {synced} proofs from IPFS")
        """
        if not self.enable_ipfs or not self.ipfs_client:
            logger.warning("IPFS not available, cannot sync")
            return 0
        
        synced = 0
        
        try:
            # If no list provided, get pinned objects
            if cid_list is None:
                pins = self.ipfs_client.pin.ls(type='recursive')
                cid_list = list(pins.get('Keys', {}).keys())
            
            # Download and cache each proof
            for cid in cid_list:
                proof_data = self.get_from_ipfs(cid)
                if proof_data and 'formula' in proof_data and 'result' in proof_data:
                    # Add to local cache
                    super().put(
                        proof_data['formula'],
                        proof_data['result'],
                        ttl=self.default_ttl
                    )
                    synced += 1
            
            logger.info(f"Synced {synced} proofs from IPFS")
            
        except Exception as e:
            logger.error(f"Error syncing from IPFS: {e}")
            self.ipfs_errors += 1
        
        return synced
    
    def pin_proof(self, formula: str, prover: str = "default") -> bool:
        """
        Pin a cached proof to IPFS.
        
        Args:
            formula: Formula to pin
            prover: Prover name (default: "default")
        
        Returns:
            True if successfully pinned, False otherwise
        
        Example:
            >>> cache.pin_proof("∀x P(x)", "z3")
        """
        if not self.enable_ipfs or not self.ipfs_client:
            return False
        
        cached = self.get(formula, prover)
        if not cached:
            logger.warning(f"Cannot pin: formula not in cache: {formula}")
            return False
        
        try:
            # Get or create CID
            key = self._make_key(formula, prover)
            if key in self._cache:
                cached_item = self._cache[key]
                if isinstance(cached_item, IPFSCachedProof) and cached_item.ipfs_cid:
                    cid = cached_item.ipfs_cid
                else:
                    # Upload if not yet in IPFS
                    cid = self._upload_to_ipfs(formula, cached, pin=False)
            else:
                return False
            
            if cid:
                # Pin in IPFS
                self.ipfs_client.pin.add(cid)
                self.pinned_count += 1
                
                # Update cache metadata
                if isinstance(cached_item, IPFSCachedProof):
                    cached_item.pinned = True
                
                logger.info(f"Pinned proof: {cid}")
                return True
            
        except Exception as e:
            logger.error(f"Error pinning proof: {e}")
            self.ipfs_errors += 1
        
        return False
    
    def unpin_proof(self, formula: str, prover: str = "default") -> bool:
        """
        Unpin a proof from IPFS.
        
        Args:
            formula: Formula to unpin
            prover: Prover name (default: "default")
        
        Returns:
            True if successfully unpinned, False otherwise
        """
        if not self.enable_ipfs or not self.ipfs_client:
            return False
        
        try:
            key = self._make_key(formula, prover)
            if key in self._cache:
                cached_item = self._cache[key]
                if isinstance(cached_item, IPFSCachedProof) and cached_item.ipfs_cid:
                    self.ipfs_client.pin.rm(cached_item.ipfs_cid)
                    cached_item.pinned = False
                    self.pinned_count = max(0, self.pinned_count - 1)
                    logger.info(f"Unpinned proof: {cached_item.ipfs_cid}")
                    return True
        except Exception as e:
            logger.error(f"Error unpinning proof: {e}")
            self.ipfs_errors += 1
        
        return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics including IPFS metrics.
        
        Returns:
            Dictionary containing all statistics
        
        Example:
            >>> stats = cache.get_statistics()
            >>> print(f"IPFS uploads: {stats['ipfs_uploads']}")
            >>> print(f"Hit rate: {stats['hit_rate']:.1%}")
        """
        stats = super().get_statistics()
        
        # Add IPFS-specific statistics
        stats.update({
            'ipfs_enabled': self.enable_ipfs,
            'ipfs_uploads': self.ipfs_uploads,
            'ipfs_downloads': self.ipfs_downloads,
            'ipfs_errors': self.ipfs_errors,
            'ipfs_pinned': self.pinned_count,
            'ipfs_host': self.ipfs_host if self.enable_ipfs else None,
            'ipfs_port': self.ipfs_port if self.enable_ipfs else None
        })
        
        return stats
    
    def close(self) -> None:
        """Close IPFS client connection."""
        if self.ipfs_client:
            try:
                self.ipfs_client.close()
            except Exception as e:
                # IPFS client cleanup failed - ignore
                logger.debug(f"IPFS client cleanup failed: {e}")
            self.ipfs_client = None
        
        super().close()


# Global IPFS cache instance
_global_ipfs_cache: Optional[IPFSProofCache] = None


def get_global_ipfs_cache(
    max_size: int = 1000,
    ttl: int = 3600,
    ipfs_host: str = '127.0.0.1',
    ipfs_port: int = 5001,
    enable_ipfs: bool = True
) -> IPFSProofCache:
    """
    Get or create the global IPFS proof cache instance.
    
    Args:
        max_size: Maximum cache size
        ttl: Default TTL in seconds
        ipfs_host: IPFS API host
        ipfs_port: IPFS API port
        enable_ipfs: Enable IPFS backend
    
    Returns:
        Global IPFS cache instance
    
    Example:
        >>> cache = get_global_ipfs_cache()
        >>> cache.put("formula", result)
    """
    global _global_ipfs_cache
    
    if _global_ipfs_cache is None:
        _global_ipfs_cache = IPFSProofCache(
            max_size=max_size,
            ttl=ttl,
            ipfs_host=ipfs_host,
            ipfs_port=ipfs_port,
            enable_ipfs=enable_ipfs
        )
    
    return _global_ipfs_cache
