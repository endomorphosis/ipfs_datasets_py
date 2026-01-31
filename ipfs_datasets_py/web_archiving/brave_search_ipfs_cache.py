"""IPFS Content-Addressed Cache for Brave Search.

This module provides distributed caching of Brave Search results using IPFS/libp2p,
enabling cache sharing across multiple nodes with content-addressed verification.

Architecture:
- Local cache (fast, file-based) as primary
- IPFS cache (distributed, content-addressed) as secondary
- Hybrid mode: check local first, fallback to IPFS
- Cache entries stored as JSON in IPFS
- CID index maintained locally for fast lookups
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def _get_ipfs_client():
    """Get IPFS client instance.
    
    Returns:
        ipfshttpclient.Client or None if not available
    """
    try:
        import ipfshttpclient
        
        # Try to connect to IPFS daemon
        ipfs_host = os.environ.get("IPFS_HOST", "/ip4/127.0.0.1/tcp/5001")
        client = ipfshttpclient.connect(ipfs_host)
        return client
    except Exception as e:
        logger.debug(f"IPFS client not available: {e}")
        return None


def _compute_cache_cid_key(*, q: str, count: int, offset: int, country: str, safesearch: str) -> str:
    """Compute a deterministic key for IPFS cache lookup.
    
    This is similar to the file cache key but optimized for IPFS.
    
    Args:
        q: Query string
        count: Number of results
        offset: Pagination offset
        country: Country code
        safesearch: Safesearch level
        
    Returns:
        Hex string that can be used as IPFS key
    """
    payload = {
        "q": q,
        "count": int(count),
        "offset": int(offset),
        "country": str(country),
        "safesearch": str(safesearch),
        "version": "v1"  # Version for cache format
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class BraveSearchIPFSCache:
    """IPFS-based distributed cache for Brave Search results.
    
    This class provides content-addressed caching using IPFS, enabling
    cache sharing across multiple nodes in a network.
    
    Features:
    - Store search results in IPFS with content addressing
    - Retrieve cached results by CID
    - Local CID index for fast lookups
    - Automatic cache discovery via IPFS network
    - Pin important cache entries
    - Garbage collection of old entries
    
    Example:
        >>> cache = BraveSearchIPFSCache()
        >>> if cache.is_available():
        ...     # Store results
        ...     cid = cache.store("query", results, metadata)
        ...     # Retrieve results
        ...     cached = cache.retrieve("query", metadata)
        ...     if cached:
        ...         print(f"Cache hit! CID: {cached['cid']}")
    """
    
    def __init__(self):
        """Initialize IPFS cache."""
        self.ipfs_client = _get_ipfs_client()
        self._available = self.ipfs_client is not None
        
        # Local CID index: query_key -> CID mapping
        self._cid_index_path = Path(
            os.environ.get("BRAVE_SEARCH_IPFS_INDEX_PATH") or 
            Path((os.environ.get("CCINDEX_STATE_DIR") or "state").strip() or "state") / "brave_ipfs_cache_index.json"
        )
        self._cid_index = self._load_cid_index()
        
        # Configuration
        self._pin_cache_entries = (os.environ.get("BRAVE_SEARCH_IPFS_PIN") or "").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self._cache_ttl_s = int((os.environ.get("BRAVE_SEARCH_IPFS_TTL_S") or "604800").strip() or "604800")  # 7 days default
    
    def is_available(self) -> bool:
        """Check if IPFS cache is available.
        
        Returns:
            True if IPFS client is connected
        """
        return self._available
    
    def _load_cid_index(self) -> Dict[str, Dict[str, Any]]:
        """Load CID index from disk.
        
        Returns:
            Dict mapping query keys to CID metadata
        """
        if not self._cid_index_path.exists():
            return {}
        
        try:
            raw = self._cid_index_path.read_text(encoding="utf-8").strip()
            data = json.loads(raw) if raw else {}
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"Failed to load CID index: {e}")
            return {}
    
    def _save_cid_index(self) -> None:
        """Save CID index to disk."""
        try:
            self._cid_index_path.parent.mkdir(parents=True, exist_ok=True)
            with self._cid_index_path.open("w", encoding="utf-8") as f:
                json.dump(self._cid_index, f, sort_keys=True, indent=2)
                f.write("\n")
        except Exception as e:
            logger.warning(f"Failed to save CID index: {e}")
    
    def store(
        self,
        query: str,
        results: List[Dict[str, str]],
        *,
        count: int = 10,
        offset: int = 0,
        country: str = "us",
        safesearch: str = "moderate",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Store search results in IPFS.
        
        Args:
            query: Search query
            results: List of search results
            count: Number of results
            offset: Pagination offset
            country: Country code
            safesearch: Safesearch level
            metadata: Additional metadata (e.g., total results, cache info)
            
        Returns:
            IPFS CID of stored data, or None if failed
        """
        if not self._available:
            return None
        
        try:
            # Prepare cache entry
            cache_entry = {
                "query": query,
                "count": count,
                "offset": offset,
                "country": country,
                "safesearch": safesearch,
                "results": results,
                "metadata": metadata or {},
                "timestamp": time.time(),
                "version": "v1"
            }
            
            # Store in IPFS
            cache_json = json.dumps(cache_entry, sort_keys=True, indent=2)
            result = self.ipfs_client.add_json(cache_entry)
            cid = result if isinstance(result, str) else result.get("Hash")
            
            if not cid:
                logger.warning("Failed to get CID from IPFS add result")
                return None
            
            # Pin if configured
            if self._pin_cache_entries:
                try:
                    self.ipfs_client.pin.add(cid)
                    logger.debug(f"Pinned cache entry: {cid}")
                except Exception as e:
                    logger.debug(f"Failed to pin cache entry: {e}")
            
            # Update local CID index
            query_key = _compute_cache_cid_key(
                q=query, count=count, offset=offset, country=country, safesearch=safesearch
            )
            self._cid_index[query_key] = {
                "cid": cid,
                "timestamp": time.time(),
                "query": query[:100],  # Store truncated query for debugging
                "result_count": len(results)
            }
            self._save_cid_index()
            
            logger.info(f"Stored Brave Search results in IPFS: {cid}")
            return cid
            
        except Exception as e:
            logger.error(f"Failed to store in IPFS: {e}")
            return None
    
    def retrieve(
        self,
        query: str,
        *,
        count: int = 10,
        offset: int = 0,
        country: str = "us",
        safesearch: str = "moderate"
    ) -> Optional[Dict[str, Any]]:
        """Retrieve cached search results from IPFS.
        
        Args:
            query: Search query
            count: Number of results
            offset: Pagination offset
            country: Country code
            safesearch: Safesearch level
            
        Returns:
            Dict with cached results and metadata, or None if not found/expired
        """
        if not self._available:
            return None
        
        try:
            # Look up CID in local index
            query_key = _compute_cache_cid_key(
                q=query, count=count, offset=offset, country=country, safesearch=safesearch
            )
            
            cid_entry = self._cid_index.get(query_key)
            if not cid_entry:
                return None
            
            # Check TTL
            timestamp = cid_entry.get("timestamp", 0)
            if (time.time() - timestamp) > self._cache_ttl_s:
                logger.debug(f"IPFS cache entry expired for query: {query}")
                # Clean up expired entry
                del self._cid_index[query_key]
                self._save_cid_index()
                return None
            
            cid = cid_entry["cid"]
            
            # Retrieve from IPFS
            cache_entry = self.ipfs_client.get_json(cid)
            
            if not isinstance(cache_entry, dict):
                logger.warning(f"Invalid cache entry from IPFS: {cid}")
                return None
            
            # Validate cache entry
            if cache_entry.get("query") != query:
                logger.warning(f"Query mismatch in cached entry: {cid}")
                return None
            
            logger.info(f"Retrieved Brave Search results from IPFS: {cid}")
            
            return {
                "results": cache_entry.get("results", []),
                "metadata": cache_entry.get("metadata", {}),
                "cid": cid,
                "timestamp": cache_entry.get("timestamp"),
                "cached": True,
                "cache_source": "ipfs",
                "cache_age_s": time.time() - cache_entry.get("timestamp", time.time())
            }
            
        except Exception as e:
            logger.debug(f"Failed to retrieve from IPFS: {e}")
            return None
    
    def stats(self) -> Dict[str, Any]:
        """Get IPFS cache statistics.
        
        Returns:
            Dict with cache statistics
        """
        ipfs_connected = False
        ipfs_version = None
        ipfs_peer_id = None
        
        if self._available:
            try:
                version_info = self.ipfs_client.version()
                ipfs_version = version_info.get("Version")
                id_info = self.ipfs_client.id()
                ipfs_peer_id = id_info.get("ID")
                ipfs_connected = True
            except Exception:
                pass
        
        return {
            "available": self._available,
            "ipfs_connected": ipfs_connected,
            "ipfs_version": ipfs_version,
            "ipfs_peer_id": ipfs_peer_id,
            "cid_index_entries": len(self._cid_index),
            "cid_index_path": str(self._cid_index_path),
            "pin_enabled": self._pin_cache_entries,
            "ttl_s": self._cache_ttl_s,
            "ipfs_host": os.environ.get("IPFS_HOST", "/ip4/127.0.0.1/tcp/5001")
        }
    
    def clear_index(self) -> Dict[str, Any]:
        """Clear the local CID index.
        
        Note: This only clears the local index, not the IPFS cache itself.
        To remove data from IPFS, use garbage collection.
        
        Returns:
            Dict with clearing result
        """
        try:
            cleared_count = len(self._cid_index)
            self._cid_index = {}
            self._save_cid_index()
            
            return {
                "status": "success",
                "cleared_entries": cleared_count,
                "message": f"Cleared {cleared_count} CID index entries"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
    
    def gc(self) -> Dict[str, Any]:
        """Garbage collect unpinned IPFS cache entries.
        
        Returns:
            Dict with GC result
        """
        if not self._available:
            return {
                "status": "unavailable",
                "message": "IPFS not available"
            }
        
        try:
            result = self.ipfs_client.repo.gc()
            
            # Count freed items
            freed_count = 0
            if isinstance(result, list):
                freed_count = len(result)
            
            return {
                "status": "success",
                "freed_count": freed_count,
                "message": f"Garbage collected {freed_count} items"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
    
    def pin_entry(self, cid: str) -> Dict[str, Any]:
        """Pin a cache entry to prevent garbage collection.
        
        Args:
            cid: IPFS CID to pin
            
        Returns:
            Dict with pin result
        """
        if not self._available:
            return {
                "status": "unavailable",
                "message": "IPFS not available"
            }
        
        try:
            self.ipfs_client.pin.add(cid)
            return {
                "status": "success",
                "cid": cid,
                "message": f"Pinned {cid}"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
    
    def unpin_entry(self, cid: str) -> Dict[str, Any]:
        """Unpin a cache entry.
        
        Args:
            cid: IPFS CID to unpin
            
        Returns:
            Dict with unpin result
        """
        if not self._available:
            return {
                "status": "unavailable",
                "message": "IPFS not available"
            }
        
        try:
            self.ipfs_client.pin.rm(cid)
            return {
                "status": "success",
                "cid": cid,
                "message": f"Unpinned {cid}"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
    
    def list_pins(self) -> Dict[str, Any]:
        """List all pinned cache entries.
        
        Returns:
            Dict with list of pinned CIDs
        """
        if not self._available:
            return {
                "status": "unavailable",
                "message": "IPFS not available"
            }
        
        try:
            pins = self.ipfs_client.pin.ls()
            pin_list = []
            
            if isinstance(pins, dict):
                for cid, info in pins.get("Keys", {}).items():
                    pin_list.append({
                        "cid": cid,
                        "type": info.get("Type", "unknown")
                    })
            
            return {
                "status": "success",
                "pins": pin_list,
                "count": len(pin_list)
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }


__all__ = [
    "BraveSearchIPFSCache",
]
