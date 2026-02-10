"""
GitHub API Response Cache

This module provides caching capabilities for GitHub API responses to reduce
the number of API calls and avoid rate limiting.

Uses content-addressed hashing (multiformats) to intelligently detect stale cache.
Supports P2P cache sharing via libp2p for distributed runners with encryption
using GitHub token as shared secret (only runners with same GitHub access can decrypt).
"""

import json
import logging
import os
import time
import hashlib
import anyio
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import threading
from threading import Lock

# Try to import cryptography for message encryption
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False
    Fernet = None
    PBKDF2HMAC = None
    hashes = None
    default_backend = None

# Try to import multiformats for content-addressed caching
try:
    from multiformats import CID, multihash
    HAVE_MULTIFORMATS = True
except ImportError:
    HAVE_MULTIFORMATS = False
    CID = None
    multihash = None

# Try to import libp2p for P2P cache sharing
try:
    from libp2p import new_host
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.network.stream.net_stream_interface import INetStream
    HAVE_LIBP2P = True
except ImportError:
    HAVE_LIBP2P = False
    new_host = None

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a cached API response with content-based validation."""
    data: Any
    timestamp: float
    ttl: int  # Time to live in seconds
    content_hash: Optional[str] = None  # Multihash of validation fields
    validation_fields: Optional[Dict[str, Any]] = None  # Fields used for hash
    
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return time.time() - self.timestamp > self.ttl
    
    def is_stale(self, current_validation_fields: Optional[Dict[str, Any]] = None) -> bool:
        """
        Check if cache is stale by comparing validation fields.
        
        Args:
            current_validation_fields: Current values of validation fields
            
        Returns:
            True if cache is stale (hash mismatch), False if still valid
        """
        # If no validation fields, fall back to TTL-based expiration
        if not self.content_hash or not current_validation_fields:
            return self.is_expired()
        
        # Compute hash of current validation fields
        current_hash = GitHubAPICache._compute_validation_hash(current_validation_fields)
        
        # Cache is stale if hash changed
        return current_hash != self.content_hash


class GitHubAPICache:
    """
    Cache for GitHub API responses with TTL and persistence.
    
    Features:
    - In-memory caching with TTL
    - Optional disk persistence
    - Thread-safe operations
    - Automatic expiration
    - Cache statistics
    """
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        default_ttl: int = 300,  # 5 minutes
        max_cache_size: int = 1000,
        enable_persistence: bool = True,
        enable_p2p: bool = True,
        p2p_listen_port: int = 9000,
        p2p_bootstrap_peers: Optional[List[str]] = None,
        github_repo: Optional[str] = None,
        enable_peer_discovery: bool = True,
        enable_universal_connectivity: bool = True
    ):
        """
        Initialize the GitHub API cache.
        
        Args:
            cache_dir: Directory for persistent cache (default: ~/.cache/github_cli)
            default_ttl: Default time-to-live for cache entries in seconds
            max_cache_size: Maximum number of entries to keep in memory
            enable_persistence: Whether to persist cache to disk
            enable_p2p: Whether to enable P2P cache sharing via libp2p
            p2p_listen_port: Port for libp2p to listen on (default: 9000)
            p2p_bootstrap_peers: List of bootstrap peer multiaddrs
            github_repo: GitHub repository for peer discovery (e.g., 'owner/repo')
            enable_peer_discovery: Whether to use GitHub cache API for peer discovery
        """
        self.default_ttl = default_ttl
        self.max_cache_size = max_cache_size
        self.enable_persistence = enable_persistence
        self.enable_p2p = enable_p2p and HAVE_LIBP2P
        self.enable_universal_connectivity = enable_universal_connectivity
        
        # Set up cache directory
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".cache" / "github_cli"
        
        if self.enable_persistence:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        
        # Statistics
        self._stats = {
            "hits": 0,
            "misses": 0,
            "peer_hits": 0,
            "expirations": 0,
            "evictions": 0,
            "api_calls_saved": 0
        }
        
        # P2P networking
        self._p2p_host = None
        self._p2p_protocol = "/github-cache/1.0.0"
        self._p2p_listen_port = p2p_listen_port
        self._p2p_bootstrap_peers = p2p_bootstrap_peers or []
        self._p2p_connected_peers: Dict[str, Any] = {}
        self._p2p_thread: Optional[threading.Thread] = None
        self._p2p_stop_event = threading.Event()
        self._universal_connectivity = None
        
        # Peer discovery
        self.github_repo = github_repo or os.environ.get("GITHUB_REPOSITORY")
        self.enable_peer_discovery = enable_peer_discovery and self.github_repo
        self._peer_registry = None
        
        if self.enable_peer_discovery and self.enable_p2p:
            try:
                from .p2p_peer_registry import P2PPeerRegistry
                self._peer_registry = P2PPeerRegistry(
                    repo=self.github_repo,
                    peer_ttl_minutes=15
                )
                logger.info(f"✓ P2P peer discovery enabled for {self.github_repo}")
            except Exception as e:
                logger.warning(f"⚠ Peer discovery unavailable: {e}")
                self.enable_peer_discovery = False
        
        # Encryption for P2P messages (using GitHub token as shared secret)
        self._encryption_key = None
        self._cipher = None
        if self.enable_p2p and HAVE_CRYPTO:
            try:
                self._init_encryption()
                logger.info("✓ P2P message encryption enabled")
            except Exception as e:
                logger.warning(f"⚠ P2P encryption unavailable: {e}")
        
        # Load persistent cache if enabled
        if self.enable_persistence:
            self._load_from_disk()
        
        # Initialize P2P if enabled
        if self.enable_p2p:
            try:
                self._init_p2p()
                logger.info(f"✓ P2P cache sharing enabled on port {p2p_listen_port}")
            except Exception as e:
                logger.warning(f"⚠ Failed to initialize P2P: {e}")
                self.enable_p2p = False
    
    def _make_cache_key(self, operation: str, *args, **kwargs) -> str:
        """
        Create a cache key from operation and parameters.
        
        Args:
            operation: Operation name (e.g., 'list_repos', 'workflow_runs')
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Cache key string
        """
        # Sort kwargs for consistent key generation
        sorted_kwargs = sorted(kwargs.items())
        key_parts = [operation] + list(map(str, args)) + [f"{k}={v}" for k, v in sorted_kwargs]
        return ":".join(key_parts)
    
    @staticmethod
    def _compute_validation_hash(validation_fields: Dict[str, Any]) -> str:
        """
        Compute content-addressed hash of validation fields using multiformats.
        
        Args:
            validation_fields: Fields to hash (e.g., {'updatedAt': '2025-11-06T10:00:00Z'})
            
        Returns:
            CID string if multiformats available, otherwise SHA256 hex
        """
        # Sort fields for deterministic hashing
        sorted_fields = json.dumps(validation_fields, sort_keys=True)
        
        if HAVE_MULTIFORMATS:
            # Use multiformats for content-addressed hashing
            content_bytes = sorted_fields.encode('utf-8')
            hasher = hashlib.sha256()
            hasher.update(content_bytes)
            digest = hasher.digest()
            
            # Wrap in multihash
            mh = multihash.wrap(digest, 'sha2-256')
            # Create CID
            cid = CID('base32', 1, 'raw', mh)
            return str(cid)
        else:
            # Fallback to simple SHA256 hex
            hasher = hashlib.sha256()
            hasher.update(sorted_fields.encode('utf-8'))
            return hasher.hexdigest()
    
    @staticmethod
    def _extract_validation_fields(operation: str, data: Any) -> Optional[Dict[str, Any]]:
        """
        Extract validation fields from API response based on operation type.
        
        Args:
            operation: Operation name
            data: API response data
            
        Returns:
            Dictionary of fields to use for validation hashing
        """
        if not data:
            return None
        
        validation = {}
        
        # Repository operations - use updatedAt/pushedAt
        if operation.startswith('list_repos') or operation == 'get_repo_info':
            if isinstance(data, list):
                # For list operations, hash all repo update times
                for repo in data:
                    if isinstance(repo, dict):
                        repo_id = repo.get('name') or repo.get('url', '')
                        validation[repo_id] = {
                            'updatedAt': repo.get('updatedAt'),
                            'pushedAt': repo.get('pushedAt')
                        }
            elif isinstance(data, dict):
                # For single repo
                validation['updatedAt'] = data.get('updatedAt')
                validation['pushedAt'] = data.get('pushedAt')
        
        # Workflow operations - use updatedAt/status/conclusion
        elif 'workflow' in operation:
            if isinstance(data, list):
                for workflow in data:
                    if isinstance(workflow, dict):
                        wf_id = str(workflow.get('databaseId', workflow.get('id', '')))
                        validation[wf_id] = {
                            'status': workflow.get('status'),
                            'conclusion': workflow.get('conclusion'),
                            'updatedAt': workflow.get('updatedAt')
                        }
            elif isinstance(data, dict):
                validation['status'] = data.get('status')
                validation['conclusion'] = data.get('conclusion')
                validation['updatedAt'] = data.get('updatedAt')
        
        # Runner operations - use status/busy
        elif 'runner' in operation:
            if isinstance(data, list):
                for runner in data:
                    if isinstance(runner, dict):
                        runner_id = str(runner.get('id', runner.get('name', '')))
                        validation[runner_id] = {
                            'status': runner.get('status'),
                            'busy': runner.get('busy')
                        }
            elif isinstance(data, dict):
                validation['status'] = data.get('status')
                validation['busy'] = data.get('busy')
        
        # Copilot operations - hash the prompt for deterministic results
        elif operation.startswith('copilot_'):
            # Copilot responses should be stable for same prompts
            # No validation needed - rely on TTL
            return None
        
        return validation if validation else None
    
    def get(
        self,
        operation: str,
        *args,
        validation_fields: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Optional[Any]:
        """
        Get a cached response with optional validation field checking.
        
        Args:
            operation: Operation name
            *args: Positional arguments
            validation_fields: Current validation fields to check staleness
            **kwargs: Keyword arguments
            
        Returns:
            Cached data or None if not found/expired/stale
        """
        cache_key = self._make_cache_key(operation, *args, **kwargs)
        
        with self._lock:
            entry = self._cache.get(cache_key)
            
            if entry is None:
                self._stats["misses"] += 1
                return None
            
            # Check TTL-based expiration
            if entry.is_expired():
                logger.debug(f"Cache entry expired for {cache_key}")
                del self._cache[cache_key]
                self._stats["expirations"] += 1
                self._stats["misses"] += 1
                return None
            
            # Check content-based staleness
            if validation_fields and entry.is_stale(validation_fields):
                logger.debug(f"Cache entry stale (hash mismatch) for {cache_key}")
                del self._cache[cache_key]
                self._stats["expirations"] += 1
                self._stats["misses"] += 1
                return None
            
            self._stats["hits"] += 1
            logger.debug(f"Cache hit for {cache_key}")
            return entry.data
    
    def put(
        self,
        operation: str,
        data: Any,
        ttl: Optional[int] = None,
        *args,
        **kwargs
    ) -> None:
        """
        Store a response in the cache with content-based validation.
        
        Args:
            operation: Operation name
            data: Data to cache
            ttl: Time-to-live in seconds (uses default if None)
            *args: Positional arguments
            **kwargs: Keyword arguments
        """
        cache_key = self._make_cache_key(operation, *args, **kwargs)
        ttl = ttl if ttl is not None else self.default_ttl
        
        # Extract validation fields and compute hash
        validation_fields = self._extract_validation_fields(operation, data)
        content_hash = None
        if validation_fields:
            content_hash = self._compute_validation_hash(validation_fields)
            logger.debug(f"Computed validation hash for {cache_key}: {content_hash[:16]}...")
        
        with self._lock:
            # Evict oldest entries if cache is full
            if len(self._cache) >= self.max_cache_size:
                self._evict_oldest()
            
            entry = CacheEntry(
                data=data,
                timestamp=time.time(),
                ttl=ttl,
                content_hash=content_hash,
                validation_fields=validation_fields
            )
            
            self._cache[cache_key] = entry
            logger.debug(f"Cached {cache_key} with TTL {ttl}s")
            
            # Persist to disk if enabled
            if self.enable_persistence:
                self._save_to_disk(cache_key, entry)
            
            # Broadcast to P2P peers if enabled
            if self.enable_p2p:
                self._broadcast_in_background(cache_key, entry)
    
    def _evict_oldest(self) -> None:
        """Evict the oldest cache entry."""
        if not self._cache:
            return
        
        # Find oldest entry
        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
        del self._cache[oldest_key]
        self._stats["evictions"] += 1
        logger.debug(f"Evicted cache entry: {oldest_key}")
    
    def invalidate(self, operation: str, *args, **kwargs) -> None:
        """
        Invalidate a specific cache entry.
        
        Args:
            operation: Operation name
            *args: Positional arguments
            **kwargs: Keyword arguments
        """
        cache_key = self._make_cache_key(operation, *args, **kwargs)
        
        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                logger.debug(f"Invalidated cache entry: {cache_key}")
                
                # Remove from disk if persistence enabled
                if self.enable_persistence:
                    cache_file = self.cache_dir / f"{self._sanitize_filename(cache_key)}.json"
                    if cache_file.exists():
                        cache_file.unlink()
    
    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all cache entries matching a pattern.
        
        Args:
            pattern: Pattern to match (e.g., 'list_repos' will invalidate all list_repos calls)
            
        Returns:
            Number of entries invalidated
        """
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(pattern)]
            
            for key in keys_to_delete:
                del self._cache[key]
                
                # Remove from disk if persistence enabled
                if self.enable_persistence:
                    cache_file = self.cache_dir / f"{self._sanitize_filename(key)}.json"
                    if cache_file.exists():
                        cache_file.unlink()
            
            logger.info(f"Invalidated {len(keys_to_delete)} cache entries matching '{pattern}'")
            return len(keys_to_delete)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._stats = {
                "hits": 0,
                "misses": 0,
                "expirations": 0,
                "evictions": 0
            }
            
            # Clear disk cache if persistence enabled
            if self.enable_persistence and self.cache_dir.exists():
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
            
            logger.info("Cleared all cache entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary of cache statistics
        """
        with self._lock:
            local_hits = self._stats["hits"]
            peer_hits = self._stats["peer_hits"]
            total_hits = local_hits + peer_hits
            total_requests = total_hits + self._stats["misses"]
            hit_rate = total_hits / total_requests if total_requests > 0 else 0
            
            # API calls saved = hits (local + peer) that would have been API calls
            api_calls_saved = total_hits
            
            stats = {
                **self._stats,
                "local_hits": local_hits,
                "total_hits": total_hits,
                "total_requests": total_requests,
                "hit_rate": hit_rate,
                "cache_size": len(self._cache),
                "max_cache_size": self.max_cache_size,
                "api_calls_saved": api_calls_saved,
                "p2p_enabled": self.enable_p2p
            }
            
            # Add P2P-specific stats if enabled
            if self.enable_p2p:
                stats["connected_peers"] = len(self._p2p_connected_peers)
                if self._p2p_host:
                    stats["peer_id"] = self._p2p_host.get_id().pretty()
                
                # Add universal connectivity stats if available
                if self._universal_connectivity:
                    stats["connectivity"] = self._universal_connectivity.get_connectivity_status()
            
            return stats
    
    def _sanitize_filename(self, key: str) -> str:
        """Sanitize a cache key for use as a filename."""
        # Replace invalid filename characters with underscores
        return key.replace("/", "_").replace(":", "_").replace("*", "_")
    
    def _save_to_disk(self, cache_key: str, entry: CacheEntry) -> None:
        """Save a cache entry to disk."""
        try:
            cache_file = self.cache_dir / f"{self._sanitize_filename(cache_key)}.json"
            cache_data = {
                "data": entry.data,
                "timestamp": entry.timestamp,
                "ttl": entry.ttl,
                "content_hash": entry.content_hash,
                "validation_fields": entry.validation_fields
            }
            
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f)
            
            logger.debug(f"Saved cache entry to {cache_file}")
        except Exception as e:
            logger.warning(f"Failed to save cache entry to disk: {e}")
    
    def _load_from_disk(self) -> None:
        """Load cache entries from disk."""
        if not self.cache_dir.exists():
            return
        
        loaded_count = 0
        expired_count = 0
        
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    with open(cache_file, 'r') as f:
                        cache_data = json.load(f)
                    
                    entry = CacheEntry(
                        data=cache_data["data"],
                        timestamp=cache_data["timestamp"],
                        ttl=cache_data["ttl"],
                        content_hash=cache_data.get("content_hash"),
                        validation_fields=cache_data.get("validation_fields")
                    )
                    
                    # Only load non-expired entries
                    if not entry.is_expired():
                        # Reconstruct cache key from filename
                        cache_key = cache_file.stem
                        self._cache[cache_key] = entry
                        loaded_count += 1
                    else:
                        # Remove expired cache file
                        cache_file.unlink()
                        expired_count += 1
                
                except Exception as e:
                    logger.warning(f"Failed to load cache file {cache_file}: {e}")
            
            if loaded_count > 0:
                logger.info(f"Loaded {loaded_count} cache entries from disk ({expired_count} expired)")
        
        except Exception as e:
            logger.warning(f"Failed to load cache from disk: {e}")
    
    def _init_encryption(self) -> None:
        """
        Initialize encryption for P2P messages using GitHub token as shared secret.
        
        All runners with the same GitHub authentication will share the same encryption key,
        allowing only authorized runners to decrypt cache messages.
        """
        if not HAVE_CRYPTO:
            raise RuntimeError("cryptography not available, install with: pip install cryptography")
        
        # Get GitHub token (shared secret)
        github_token = os.environ.get("GITHUB_TOKEN")
        if not github_token:
            # Try to get token from gh CLI
            try:
                import subprocess
                result = subprocess.run(
                    ["gh", "auth", "token"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    github_token = result.stdout.strip()
            except Exception as e:
                logger.debug(f"Failed to get GitHub token from gh CLI: {e}")
        
        if not github_token:
            raise RuntimeError("GitHub token not available (set GITHUB_TOKEN or run 'gh auth login')")
        
        # Derive encryption key from GitHub token using PBKDF2
        # This ensures all runners with same token get same encryption key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"github-cache-p2p",  # Fixed salt for deterministic key derivation
            iterations=100000,
            backend=default_backend()
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(github_token.encode('utf-8')))
        self._encryption_key = key
        self._cipher = Fernet(key)
        
        logger.debug("Encryption key derived from GitHub token")
    
    def _encrypt_message(self, data: Dict[str, Any]) -> bytes:
        """
        Encrypt a message for P2P transmission.
        
        Args:
            data: Dictionary to encrypt
            
        Returns:
            Encrypted bytes
        """
        if not self._cipher:
            # No encryption available, send plaintext (with warning)
            logger.warning("P2P message sent unencrypted (cryptography not available)")
            return json.dumps(data).encode('utf-8')
        
        try:
            plaintext = json.dumps(data).encode('utf-8')
            encrypted = self._cipher.encrypt(plaintext)
            return encrypted
        except Exception as e:
            logger.error(f"Failed to encrypt message: {e}")
            raise
    
    def _decrypt_message(self, encrypted_data: bytes) -> Optional[Dict[str, Any]]:
        """
        Decrypt a P2P message.
        
        Args:
            encrypted_data: Encrypted bytes
            
        Returns:
            Decrypted dictionary or None if decryption fails
        """
        if not self._cipher:
            # No encryption available, try parsing as plaintext
            try:
                return json.loads(encrypted_data.decode('utf-8'))
            except Exception as e:
                logger.warning(f"Failed to parse unencrypted message: {e}")
                return None
        
        try:
            decrypted = self._cipher.decrypt(encrypted_data)
            return json.loads(decrypted.decode('utf-8'))
        except Exception as e:
            logger.warning(f"Failed to decrypt message (wrong key or corrupted): {e}")
            return None
    
    def _init_p2p(self) -> None:
        """Initialize P2P networking for cache sharing."""
        if not HAVE_LIBP2P:
            raise RuntimeError("libp2p not available, install with: pip install libp2p")

        if self._p2p_thread is not None and self._p2p_thread.is_alive():
            return

        self._p2p_stop_event.clear()

        def _thread_main() -> None:
            async def _serve() -> None:
                await self._start_p2p_host()
                # Keep the background async runtime alive until stop requested.
                await anyio.to_thread.run_sync(self._p2p_stop_event.wait)

                try:
                    if self._p2p_host:
                        await self._p2p_host.close()
                except Exception:
                    pass

            try:
                anyio.run(_serve)
            except Exception as e:
                logger.warning(f"P2P background runner exited: {e}")

        self._p2p_thread = threading.Thread(
            target=_thread_main,
            name="GitHubAPICacheP2P",
            daemon=True,
        )
        self._p2p_thread.start()
    
    async def _start_p2p_host(self) -> None:
        """Start libp2p host for P2P cache sharing."""
        try:
            # Create libp2p host
            self._p2p_host = await new_host()
            
            # Initialize universal connectivity if enabled
            if self.enable_universal_connectivity:
                try:
                    from .p2p_connectivity import get_universal_connectivity, ConnectivityConfig
                    
                    config = ConnectivityConfig(
                        enable_mdns=True,
                        enable_dht=True,
                        enable_relay=True,
                        enable_autonat=True,
                        enable_hole_punching=True
                    )
                    self._universal_connectivity = get_universal_connectivity(config)
                    
                    # Configure transports and discovery
                    await self._universal_connectivity.configure_transports(self._p2p_host)
                    await self._universal_connectivity.start_mdns_discovery(self._p2p_host)
                    await self._universal_connectivity.configure_dht(self._p2p_host)
                    await self._universal_connectivity.enable_autonat(self._p2p_host)
                    await self._universal_connectivity.enable_hole_punching(self._p2p_host)
                    
                    logger.info("✓ Universal connectivity enabled")
                except Exception as e:
                    logger.warning(f"Universal connectivity not available: {e}")
            
            # Set stream handler for cache protocol
            self._p2p_host.set_stream_handler(self._p2p_protocol, self._handle_cache_stream)
            
            # Start listening
            listen_addr = f"/ip4/0.0.0.0/tcp/{self._p2p_listen_port}"
            await self._p2p_host.get_network().listen(listen_addr)
            
            peer_id = self._p2p_host.get_id().pretty()
            logger.info(f"P2P host started, listening on {listen_addr}")
            logger.info(f"Peer ID: {peer_id}")
            
            # Register this peer in the discovery registry
            if self._peer_registry:
                try:
                    # Get public IP for multiaddr
                    public_ip = self._peer_registry.public_ip or "127.0.0.1"
                    multiaddr = f"/ip4/{public_ip}/tcp/{self._p2p_listen_port}/p2p/{peer_id}"
                    
                    self._peer_registry.register_peer(
                        peer_id=peer_id,
                        listen_port=self._p2p_listen_port,
                        multiaddr=multiaddr
                    )
                    
                    # Use universal connectivity for multi-method peer discovery
                    if self._universal_connectivity:
                        discovered_addrs = await self._universal_connectivity.discover_peers_multimethod(
                            github_registry=self._peer_registry,
                            bootstrap_peers=self._p2p_bootstrap_peers
                        )
                    else:
                        # Fallback to simple discovery
                        discovered_addrs = self._peer_registry.get_bootstrap_addrs(max_peers=5)
                    
                    if discovered_addrs:
                        logger.info(f"✓ Discovered {len(discovered_addrs)} peer(s) via registry")
                        self._p2p_bootstrap_peers.extend(discovered_addrs)
                except Exception as e:
                    logger.warning(f"Peer discovery failed: {e}")
            
            # Connect to bootstrap peers with enhanced connectivity
            for peer_addr in self._p2p_bootstrap_peers:
                try:
                    if self._universal_connectivity:
                        # Use universal connectivity with fallback strategies
                        success = await self._universal_connectivity.attempt_connection(
                            self._p2p_host,
                            peer_addr,
                            use_relay=True
                        )
                        if not success:
                            logger.warning(f"Failed to connect to peer {peer_addr}")
                    else:
                        # Fallback to direct connection
                        await self._connect_to_peer(peer_addr)
                except Exception as e:
                    logger.warning(f"Failed to connect to bootstrap peer {peer_addr}: {e}")
        
        except Exception as e:
            logger.error(f"Failed to start P2P host: {e}")
            raise
    
    async def _connect_to_peer(self, peer_addr: str) -> None:
        """Connect to a peer by multiaddr."""
        if not self._p2p_host:
            return
        
        peer_info = info_from_p2p_addr(peer_addr)
        await self._p2p_host.connect(peer_info)
        
        peer_id = peer_info.peer_id.pretty()
        self._p2p_connected_peers[peer_id] = peer_info
        logger.info(f"Connected to peer: {peer_id}")
    
    async def _handle_cache_stream(self, stream: 'INetStream') -> None:
        """Handle incoming encrypted cache entry from peer."""
        try:
            # Read encrypted cache entry data
            encrypted_data = await stream.read()
            
            # Decrypt message
            message = self._decrypt_message(encrypted_data)
            if message is None:
                logger.warning("Failed to decrypt message from peer (unauthorized or corrupted)")
                await stream.write(b"ERROR: Decryption failed")
                return
            
            # Extract cache entry
            cache_key = message.get("key")
            entry_data = message.get("entry")
            
            if not cache_key or not entry_data:
                logger.warning("Received invalid cache entry from peer")
                await stream.write(b"ERROR: Invalid format")
                return
            
            # Reconstruct cache entry
            entry = CacheEntry(
                data=entry_data["data"],
                timestamp=entry_data["timestamp"],
                ttl=entry_data["ttl"],
                content_hash=entry_data.get("content_hash"),
                validation_fields=entry_data.get("validation_fields")
            )
            
            # Verify content hash if available
            if entry.content_hash and entry.validation_fields:
                expected_hash = self._compute_validation_hash(entry.validation_fields)
                if expected_hash != entry.content_hash:
                    logger.warning(f"Content hash mismatch for {cache_key}, rejecting")
                    return
            
            # Store in cache if not expired
            if not entry.is_expired():
                with self._lock:
                    # Only store if we don't have it or our version is older
                    existing = self._cache.get(cache_key)
                    if not existing or existing.timestamp < entry.timestamp:
                        self._cache[cache_key] = entry
                        self._stats["peer_hits"] += 1
                        logger.debug(f"Received cache entry from peer: {cache_key}")
                        
                        # Persist if enabled
                        if self.enable_persistence:
                            self._save_to_disk(cache_key, entry)
            
            # Send acknowledgment
            await stream.write(b"OK")
        
        except Exception as e:
            logger.error(f"Error handling cache stream: {e}")
        finally:
            await stream.close()
    
    async def _broadcast_cache_entry(self, cache_key: str, entry: CacheEntry) -> None:
        """Broadcast encrypted cache entry to all connected peers."""
        if not self._p2p_host or not self._p2p_connected_peers:
            return
        
        try:
            # Prepare message
            message = {
                "key": cache_key,
                "entry": {
                    "data": entry.data,
                    "timestamp": entry.timestamp,
                    "ttl": entry.ttl,
                    "content_hash": entry.content_hash,
                    "validation_fields": entry.validation_fields
                }
            }
            
            # Encrypt message (only peers with same GitHub token can decrypt)
            encrypted_bytes = self._encrypt_message(message)
            
            # Send to all connected peers
            for peer_id, peer_info in list(self._p2p_connected_peers.items()):
                try:
                    stream = await self._p2p_host.new_stream(peer_info.peer_id, [self._p2p_protocol])
                    await stream.write(encrypted_bytes)
                    
                    # Wait for ack
                    ack = await stream.read()
                    if ack == b"OK":
                        logger.debug(f"Broadcast cache entry to {peer_id}: {cache_key}")
                    
                    await stream.close()
                
                except Exception as e:
                    logger.warning(f"Failed to broadcast to peer {peer_id}: {e}")
        
        except Exception as e:
            logger.error(f"Error broadcasting cache entry: {e}")
    
    def _broadcast_in_background(self, cache_key: str, entry: CacheEntry) -> None:
        """Broadcast cache entry in background (non-blocking)."""
        if not self.enable_p2p or not self._p2p_host:
            return

        try:
            from ipfs_datasets_py.utils.anyio_compat import in_async_context

            if in_async_context():
                anyio.lowlevel.spawn_system_task(self._broadcast_cache_entry, cache_key, entry)
                return
        except Exception:
            pass

        def _runner() -> None:
            try:
                anyio.run(self._broadcast_cache_entry, cache_key, entry)
            except Exception:
                pass

        threading.Thread(target=_runner, name="GitHubAPICacheBroadcast", daemon=True).start()


# Global cache instance (can be configured at module level)
_global_cache: Optional[GitHubAPICache] = None


def get_global_cache(**kwargs) -> GitHubAPICache:
    """
    Get or create the global GitHub API cache instance.
    
    Automatically reads P2P configuration from environment variables:
    - CACHE_ENABLE_P2P: Enable P2P cache sharing (default: true)
    - CACHE_LISTEN_PORT: P2P listen port (default: 9000)
    - CACHE_BOOTSTRAP_PEERS: Comma-separated list of peer multiaddrs
    - CACHE_DEFAULT_TTL: Default cache TTL in seconds (default: 300)
    - CACHE_DIR: Cache directory (default: ~/.cache/github_cli)
    
    Args:
        **kwargs: Arguments to pass to GitHubAPICache constructor (overrides env vars)
        
    Returns:
        Global GitHubAPICache instance
    """
    global _global_cache
    
    if _global_cache is None:
        # Read from environment if not provided
        if 'enable_p2p' not in kwargs:
            kwargs['enable_p2p'] = os.environ.get('CACHE_ENABLE_P2P', 'true').lower() == 'true'
        
        if 'p2p_listen_port' not in kwargs:
            kwargs['p2p_listen_port'] = int(os.environ.get('CACHE_LISTEN_PORT', '9000'))
        
        if 'p2p_bootstrap_peers' not in kwargs:
            peers_str = os.environ.get('CACHE_BOOTSTRAP_PEERS', '')
            if peers_str:
                kwargs['p2p_bootstrap_peers'] = [p.strip() for p in peers_str.split(',') if p.strip()]
        
        if 'default_ttl' not in kwargs:
            kwargs['default_ttl'] = int(os.environ.get('CACHE_DEFAULT_TTL', '300'))
        
        if 'cache_dir' not in kwargs and 'CACHE_DIR' in os.environ:
            kwargs['cache_dir'] = os.environ['CACHE_DIR']
        
        _global_cache = GitHubAPICache(**kwargs)
    
    return _global_cache


def configure_cache(**kwargs) -> GitHubAPICache:
    """
    Configure the global cache with custom settings.
    
    Args:
        **kwargs: Arguments to pass to GitHubAPICache constructor
        
    Returns:
        Configured GitHubAPICache instance
    """
    global _global_cache
    _global_cache = GitHubAPICache(**kwargs)
    return _global_cache
