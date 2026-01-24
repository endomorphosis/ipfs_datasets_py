"""
Distributed GitHub API Cache using libp2p

This module implements a peer-to-peer cache for GitHub API responses
to reduce API rate limit usage across multiple GitHub Actions runners.

Key features:
- Content-addressable storage using IPFS multiformats
- P2P gossip for cache updates via pylibp2p
- Cache staleness detection via content hashing
- Automatic peer discovery and synchronization
"""

import anyio
import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
import hashlib

try:
    from libp2p import new_host
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.network.stream.net_stream_interface import INetStream
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.typing import TProtocol
    from multiaddr import Multiaddr
    LIBP2P_AVAILABLE = True
except ImportError:
    LIBP2P_AVAILABLE = False
    logging.warning("pylibp2p not available, distributed cache will be disabled")

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
        MULTIFORMATS_AVAILABLE = False
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
    Distributed cache for GitHub API responses using libp2p
    
    This cache reduces API rate limit usage by sharing responses
    between GitHub Actions runners via a P2P gossip network.
    """
    
    PROTOCOL_ID = TProtocol("/github-cache/1.0.0")
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        listen_port: int = 9000,
        bootstrap_peers: Optional[List[str]] = None,
        default_ttl: int = 300  # 5 minutes
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
        self.libp2p_enabled = LIBP2P_AVAILABLE
        
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
        logger.info(f"  libp2p: {'enabled' if self.libp2p_enabled else 'disabled'}")
        logger.info(f"  multiformats: {'enabled' if MULTIFORMATS_AVAILABLE else 'disabled'}")
    
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
        """Start the P2P network and begin listening"""
        if not self.libp2p_enabled:
            logger.warning("libp2p not available, running in local-only mode")
            return
        
        try:
            # Generate or load key pair
            key_pair = create_new_key_pair()
            
            # Create libp2p host
            self.host = await new_host(key_pair=key_pair)
            self.peer_id = str(self.host.get_id())
            
            # Set up stream handler for cache protocol
            self.host.set_stream_handler(self.PROTOCOL_ID, self._handle_cache_stream)
            
            # Start listening
            listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{self.listen_port}")
            await self.host.get_network().listen(listen_addr)
            
            logger.info(f"P2P cache node started")
            logger.info(f"  Peer ID: {self.peer_id}")
            logger.info(f"  Listening on: {listen_addr}")
            
            # Connect to bootstrap peers
            for peer_addr in self.bootstrap_peers:
                await self._connect_to_peer(peer_addr)
            
        except Exception as e:
            logger.error(f"Failed to start P2P network: {e}")
            self.libp2p_enabled = False
    
    async def stop(self):
        """Stop the P2P network"""
        if self.host:
            await self.host.close()
        self._save_cache()
    
    async def _connect_to_peer(self, peer_addr: str):
        """Connect to a peer"""
        try:
            peer_info = info_from_p2p_addr(Multiaddr(peer_addr))
            await self.host.connect(peer_info)
            peer_id = str(peer_info.peer_id)
            self.connected_peers.add(peer_id)
            logger.info(f"Connected to peer: {peer_id}")
        except Exception as e:
            logger.warning(f"Failed to connect to {peer_addr}: {e}")
    
    async def _handle_cache_stream(self, stream: INetStream):
        """Handle incoming cache synchronization stream"""
        try:
            peer_id = str(stream.muxed_conn.peer_id)
            logger.debug(f"Handling cache stream from {peer_id}")
            
            # Read message
            data = await stream.read()
            message = json.loads(data.decode('utf-8'))
            
            msg_type = message.get('type')
            
            if msg_type == 'cache_entry':
                # Peer is sharing a cache entry
                entry_dict = message.get('entry')
                entry = CacheEntry.from_dict(entry_dict)
                
                # Verify content hash
                if ContentHasher.verify_hash(entry.data, entry.content_hash):
                    self._update_local_cache(entry)
                    logger.debug(f"Received valid cache entry: {entry.key}")
                else:
                    logger.warning(f"Invalid cache entry hash from {peer_id}")
            
            elif msg_type == 'cache_request':
                # Peer is requesting a cache entry
                key = message.get('key')
                if key in self.local_cache and not self.local_cache[key].is_stale():
                    await self._send_cache_entry(stream, self.local_cache[key])
            
            await stream.close()
            
        except Exception as e:
            logger.error(f"Error handling cache stream: {e}")
    
    async def _send_cache_entry(self, stream: INetStream, entry: CacheEntry):
        """Send a cache entry to a peer"""
        try:
            message = {
                'type': 'cache_entry',
                'entry': entry.to_dict()
            }
            data = json.dumps(message).encode('utf-8')
            await stream.write(data)
        except Exception as e:
            logger.error(f"Error sending cache entry: {e}")
    
    async def _broadcast_cache_entry(self, entry: CacheEntry):
        """Broadcast a cache entry to all connected peers"""
        if not self.libp2p_enabled or not self.host:
            return
        
        for peer_id in self.connected_peers:
            try:
                # Open stream to peer
                stream = await self.host.new_stream(peer_id, [self.PROTOCOL_ID])
                await self._send_cache_entry(stream, entry)
                await stream.close()
            except Exception as e:
                logger.debug(f"Failed to broadcast to {peer_id}: {e}")
    
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
        if asyncio.iscoroutinefunction(fetch_fn):
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
            'peer_id': self.peer_id
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
    bootstrap_peers: Optional[List[str]] = None
) -> DistributedGitHubCache:
    """Initialize and start the distributed cache"""
    cache = DistributedGitHubCache(
        listen_port=listen_port,
        bootstrap_peers=bootstrap_peers
    )
    await cache.start()
    
    global _cache_instance
    _cache_instance = cache
    
    return cache
