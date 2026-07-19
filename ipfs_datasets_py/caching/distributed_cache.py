"""
Distributed GitHub API Cache

This module implements a local persistent cache for GitHub API responses. The
older raw libp2p cache stream protocol is intentionally disabled; distributed
cache sharing must be provided by a canonical MCP++ service.

Key features:
- Content-addressable storage using IPFS multiformats
- Local persistent cache updates
- Cache staleness detection via content hashing
"""

import base64
import inspect
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
import hashlib

from ipfs_datasets_py.caching.task_p2p_cache import TaskP2PCacheAdapter

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    CRYPTO_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Fernet = None  # type: ignore[assignment]
    PBKDF2HMAC = None  # type: ignore[assignment]
    default_backend = None  # type: ignore[assignment]
    hashes = None  # type: ignore[assignment]
    CRYPTO_AVAILABLE = False

try:
    from ipfs_datasets_py.deps_resolver import resolve_module as _resolve_module
    from ipfs_datasets_py.deps_resolver import deps_get as _deps_get
    from ipfs_datasets_py.deps_resolver import deps_set as _deps_set
except Exception:  # pragma: no cover
    _resolve_module = None  # type: ignore
    _deps_get = None  # type: ignore
    _deps_set = None  # type: ignore

try:
    from multiformats import CID, multihash, multicodec
    MULTIFORMATS_AVAILABLE = True
except ImportError:
    try:
        from ipfs_datasets_py.auto_installer import ensure_module

        ensure_module('multiformats', 'multiformats')
        from multiformats import CID, multihash, multicodec
        MULTIFORMATS_AVAILABLE = True
    except ImportError:
        try:
            import sys

            sys.path.insert(0, str(Path(__file__).parent.parent / "ipfs_multiformats_py"))
            from multiformats import CID, multihash, multicodec
            MULTIFORMATS_AVAILABLE = True
        except ImportError:
            MULTIFORMATS_AVAILABLE = False
            logging.warning("ipfs_multiformats not available, using SHA256 hashing")

LIBP2P_AVAILABLE = False


_default_deps: object | None = None


def set_default_deps(deps: object | None) -> None:
    global _default_deps
    _default_deps = deps


def configure_libp2p(*, deps: object | None = None, libp2p_module=None) -> bool:
    """Compatibility stub for the retired raw distributed-cache transport."""
    global LIBP2P_AVAILABLE

    _ = libp2p_module
    LIBP2P_AVAILABLE = False
    if deps is None:
        deps = _default_deps
    if deps is not None and callable(_deps_set):
        try:
            _deps_set(deps, "pip::libp2p", None)
            _deps_set(deps, "ipfs_datasets_py::libp2p_configured", False)
        except Exception:
            pass
    logging.warning("Legacy raw DistributedGitHubCache libp2p transport is disabled")
    return False

try:
    from multiformats import CID, multihash, multicodec
    MULTIFORMATS_AVAILABLE = True
except ImportError:
    try:
        # Fallback to ipfs_multiformats_py
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "ipfs_multiformats_py"))
        from multiformats import CID, multihash, multicodec
        MULTIFORMATS_AVAILABLE = True
    except ImportError:
        try:
            from ipfs_datasets_py.auto_installer import ensure_module, get_installer

            if get_installer().auto_install and ensure_module("multiformats", "multiformats>=0.3.0") is not None:
                from multiformats import CID, multihash, multicodec

                MULTIFORMATS_AVAILABLE = True
            else:
                MULTIFORMATS_AVAILABLE = False
        except Exception:
            MULTIFORMATS_AVAILABLE = False

        if not MULTIFORMATS_AVAILABLE:
            logging.warning("ipfs_multiformats not available, using SHA256 hashing")


logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a cached GitHub API response"""
    key: str  # API endpoint/identifier
    data: Any  # Response data
    timestamp: float  # When cached
    ttl: int  # Time to live in seconds
    content_hash: str  # Content-addressable hash
    source_peer: Optional[str] = None  # Peer ID that provided this
    
    def is_stale(self) -> bool:
        """Check if cache entry has expired"""
        return time.time() - self.timestamp > self.ttl
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            'key': self.key,
            'data': self.data,
            'timestamp': self.timestamp,
            'ttl': self.ttl,
            'content_hash': self.content_hash,
            'source_peer': self.source_peer
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> 'CacheEntry':
        """Create from dictionary"""
        return cls(**d)


class ContentHasher:
    """Content-addressable hashing using IPFS multiformats"""
    
    @staticmethod
    def hash_content(data: Any) -> str:
        """
        Hash content using IPFS multiformats if available,
        otherwise fallback to SHA256
        """
        # Serialize data
        if isinstance(data, (dict, list)):
            content = json.dumps(data, sort_keys=True).encode('utf-8')
        elif isinstance(data, str):
            content = data.encode('utf-8')
        else:
            content = str(data).encode('utf-8')
        
        if MULTIFORMATS_AVAILABLE:
            try:
                # Use IPFS multihash (sha2-256)
                mh = multihash.digest(content, 'sha2-256')
                # Create CID v1 with raw codec
                cid = CID('base58btc', 1, 'raw', mh)
                return str(cid)
            except Exception as e:
                logger.warning(f"Failed to create CID, falling back to SHA256: {e}")
        
        # Fallback to standard SHA256
        return hashlib.sha256(content).hexdigest()
    
    @staticmethod
    def verify_hash(data: Any, expected_hash: str) -> bool:
        """Verify that data matches expected hash"""
        actual_hash = ContentHasher.hash_content(data)
        return actual_hash == expected_hash


class DistributedGitHubCache:
    """
    Local cache for GitHub API responses.
    
    Raw cache gossip is retired; use a canonical MCP++ cache service for
    distributed sharing.
    """
    
    PROTOCOL_ID = "github-cache-retired"
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        listen_port: int = 9000,
        bootstrap_peers: Optional[List[str]] = None,
        default_ttl: int = 300,  # 5 minutes
        *,
        enable_p2p: bool = False,
        enable_task_p2p_cache: bool | None = None,
        task_p2p_timeout_s: float = 10.0,
        p2p_shared_secret: Optional[str] = None,
        deps: object | None = None,
        libp2p_module=None,
    ):
        self.cache_dir = cache_dir or Path.home() / ".github-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.listen_port = listen_port
        self.bootstrap_peers = bootstrap_peers or []
        self.default_ttl = default_ttl
        
        # Local cache storage
        self.local_cache: Dict[str, CacheEntry] = {}
        self.cache_file = self.cache_dir / "cache.json"
        
        # P2P networking
        self.host = None
        self.peer_id = None
        self.connected_peers: Set[str] = set()
        self.raw_p2p_cache_requested = bool(enable_p2p)
        self._p2p_cipher = self._init_p2p_cipher(p2p_shared_secret) if enable_p2p else None
        if enable_p2p and self._p2p_cipher is None:
            logger.warning("Distributed cache p2p disabled: encrypted shared secret is required")
        elif enable_p2p:
            logger.warning("Legacy raw distributed cache P2P is disabled; running cache in local-only mode")
        _ = deps, libp2p_module
        self.libp2p_enabled = False
        self._task_p2p_cache = TaskP2PCacheAdapter(
            enabled=enable_task_p2p_cache,
            namespace="distributed-github-cache",
            shared_secret=p2p_shared_secret,
            timeout_s=float(task_p2p_timeout_s),
        )
        self.p2p_transport = self._task_p2p_cache.transport
        
        # Statistics
        self.stats = {
            'local_hits': 0,
            'peer_hits': 0,
            'misses': 0,
            'api_calls_saved': 0
        }
        
        # Load persisted cache
        self._load_cache()
        
        logger.info(f"Initialized distributed GitHub cache")
        logger.info("  raw libp2p: disabled")
        logger.info(f"  task p2p cache: {'enabled' if self._task_p2p_cache.enabled else 'disabled'}")
        logger.info(f"  multiformats: {'enabled' if MULTIFORMATS_AVAILABLE else 'disabled'}")

    def _init_p2p_cipher(self, explicit_secret: Optional[str]) -> Optional["Fernet"]:
        if not CRYPTO_AVAILABLE or Fernet is None or PBKDF2HMAC is None or hashes is None:
            return None
        secret = (
            explicit_secret
            or os.environ.get("IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET")
            or os.environ.get("IPFS_ACCELERATE_PY_CACHE_P2P_SHARED_SECRET")
            or os.environ.get("CACHE_P2P_SHARED_SECRET")
            or os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or ""
        ).strip()
        if not secret:
            return None
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"ipfs-datasets-distributed-cache-p2p-v1",
            iterations=200_000,
            backend=default_backend(),
        )
        return Fernet(base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8"))))

    def _encode_p2p_message(self, message: Dict[str, Any]) -> bytes:
        if self._p2p_cipher is None:
            raise RuntimeError("Distributed cache p2p encryption is not configured")
        payload = json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._p2p_cipher.encrypt(payload)

    def _decode_p2p_message(self, payload: bytes) -> Optional[Dict[str, Any]]:
        if self._p2p_cipher is None:
            logger.warning("Distributed cache rejected plaintext p2p payload")
            return None
        try:
            raw = self._p2p_cipher.decrypt(bytes(payload or b""))
            message = json.loads(raw.decode("utf-8"))
            return message if isinstance(message, dict) else None
        except Exception:
            return None
    
    def _load_cache(self):
        """Load cache from disk"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    for key, entry_dict in data.items():
                        entry = CacheEntry.from_dict(entry_dict)
                        if not entry.is_stale():
                            self.local_cache[key] = entry
                logger.info(f"Loaded {len(self.local_cache)} cache entries from disk")
            except Exception as e:
                logger.error(f"Failed to load cache: {e}")
    
    def _save_cache(self):
        """Persist cache to disk"""
        try:
            data = {k: v.to_dict() for k, v in self.local_cache.items() if not v.is_stale()}
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
    
    async def start(self):
        """Start the cache service.

        The retired raw P2P transport is never started from this compatibility
        class; distributed sharing belongs in MCP++.
        """
        self.libp2p_enabled = False
        self.host = None
        logger.warning("Legacy raw distributed cache P2P is disabled; running in local-only mode")
        return None
    
    async def stop(self):
        """Stop the cache service and persist local entries."""
        self.host = None
        self.libp2p_enabled = False
        self._save_cache()
    
    async def _connect_to_peer(self, peer_addr: str):
        """Legacy raw cache peer connection is retired."""
        _ = peer_addr
        return None
    
    async def _handle_cache_stream(self, stream: Any):
        """Legacy raw cache stream handler is disabled."""
        _ = stream
        raise RuntimeError("Legacy raw DistributedGitHubCache stream handler is disabled")
    
    async def _send_cache_entry(self, stream: Any, entry: CacheEntry):
        """Legacy raw cache send is disabled."""
        _ = stream, entry
        return None
    
    async def _broadcast_cache_entry(self, entry: CacheEntry):
        """Legacy raw cache broadcast is disabled."""
        _ = entry
        return None
    
    def _update_local_cache(self, entry: CacheEntry):
        """Update local cache with new entry"""
        # Check if we should update (newer or doesn't exist)
        if entry.key not in self.local_cache or \
           self.local_cache[entry.key].timestamp < entry.timestamp:
            self.local_cache[entry.key] = entry
            self._save_cache()
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache
        
        Returns cached value if available and not stale,
        otherwise returns None
        """
        # Check local cache first
        if key in self.local_cache:
            entry = self.local_cache[key]
            if not entry.is_stale():
                self.stats['local_hits'] += 1
                logger.debug(f"Cache hit (local): {key}")
                return entry.data
            else:
                # Remove stale entry
                del self.local_cache[key]

        remote_entry = self._task_p2p_cache.get(key)
        if isinstance(remote_entry, dict):
            try:
                entry_data = remote_entry.get("entry", remote_entry)
                entry = CacheEntry.from_dict(entry_data)
            except Exception:
                entry = None

            if entry is not None and not entry.is_stale() and ContentHasher.verify_hash(entry.data, entry.content_hash):
                self._update_local_cache(entry)
                self.stats['peer_hits'] += 1
                self.stats['api_calls_saved'] += 1
                logger.debug(f"Cache hit from MCP++ TaskQueue cache: {key}")
                return entry.data

        self.stats['misses'] += 1
        logger.debug(f"Cache miss: {key}")
        return None
    
    async def set(
        self,
        key: str,
        data: Any,
        ttl: Optional[int] = None,
        broadcast: bool = True
    ) -> str:
        """
        Set value in cache and optionally broadcast to peers
        
        Returns the content hash of the data
        """
        # Generate content hash
        content_hash = ContentHasher.hash_content(data)
        
        # Create cache entry
        entry = CacheEntry(
            key=key,
            data=data,
            timestamp=time.time(),
            ttl=ttl or self.default_ttl,
            content_hash=content_hash,
            source_peer=self.peer_id
        )
        
        # Update local cache
        self._update_local_cache(entry)

        await self._task_p2p_cache.set_async(
            key,
            {"entry": entry.to_dict()},
            ttl_s=float(entry.ttl),
        )

        # Broadcast to peers
        if broadcast and self.libp2p_enabled:
            await self._broadcast_cache_entry(entry)
            logger.debug(f"Broadcast cache entry: {key}")
        
        return content_hash
    
    async def get_or_fetch(
        self,
        key: str,
        fetch_fn,
        ttl: Optional[int] = None,
        *args,
        **kwargs
    ) -> Any:
        """
        Get from cache or fetch if not available
        
        Args:
            key: Cache key
            fetch_fn: Function to call if cache miss (can be async)
            ttl: Time to live for cached value
            *args, **kwargs: Arguments to pass to fetch_fn
        """
        # Try cache first
        cached = self.get(key)
        if cached is not None:
            self.stats['api_calls_saved'] += 1
            return cached
        
        # Cache miss - fetch from source
        if inspect.iscoroutinefunction(fetch_fn):
            data = await fetch_fn(*args, **kwargs)
        else:
            data = fetch_fn(*args, **kwargs)
        
        # Store in cache and broadcast
        await self.set(key, data, ttl=ttl)
        
        return data
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        total_requests = self.stats['local_hits'] + self.stats['peer_hits'] + self.stats['misses']
        hit_rate = (self.stats['local_hits'] + self.stats['peer_hits']) / total_requests if total_requests > 0 else 0
        
        return {
            **self.stats,
            'total_requests': total_requests,
            'hit_rate': hit_rate,
            'cache_size': len(self.local_cache),
            'connected_peers': len(self.connected_peers),
            'peer_id': self.peer_id,
            'p2p_enabled': bool(self._task_p2p_cache.enabled),
            'raw_p2p_cache_enabled': False,
            'raw_p2p_cache_requested': bool(getattr(self, "raw_p2p_cache_requested", False)),
            'p2p_transport': self._task_p2p_cache.transport,
            'task_p2p_cache_enabled': bool(self._task_p2p_cache.enabled),
            'task_p2p_cache_mode': self._task_p2p_cache.mode(),
        }
    
    def clear_stale(self):
        """Remove stale entries from cache"""
        stale_keys = [k for k, v in self.local_cache.items() if v.is_stale()]
        for key in stale_keys:
            del self.local_cache[key]
        if stale_keys:
            logger.info(f"Cleared {len(stale_keys)} stale cache entries")
            self._save_cache()


# Global cache instance
_cache_instance: Optional[DistributedGitHubCache] = None


def get_cache() -> DistributedGitHubCache:
    """Get or create global cache instance"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = DistributedGitHubCache()
    return _cache_instance


async def initialize_cache(
    listen_port: int = 9000,
    bootstrap_peers: Optional[List[str]] = None,
    *,
    enable_p2p: bool = False,
    p2p_shared_secret: Optional[str] = None,
) -> DistributedGitHubCache:
    """Initialize and start the distributed cache"""
    cache = DistributedGitHubCache(
        listen_port=listen_port,
        bootstrap_peers=bootstrap_peers,
        enable_p2p=enable_p2p,
        p2p_shared_secret=p2p_shared_secret,
    )
    await cache.start()
    
    global _cache_instance
    _cache_instance = cache
    
    return cache
