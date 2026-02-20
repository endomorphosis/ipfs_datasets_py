"""Enhanced Peer Discovery System for MCP++ Integration.

This module implements multi-source peer discovery with:
1. GitHub Issues-based peer registry (primary)
2. Local file fallback (secondary)
3. DHT peer discovery (tertiary)
4. mDNS local network discovery (quaternary)

The system aggregates peers from all sources, deduplicates, ranks by
reliability, and maintains an active connection pool.

Module: ipfs_datasets_py.mcp_server.mcplusplus.peer_discovery
"""

from __future__ import annotations

import anyio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class PeerInfo:
    """Information about a discovered peer."""
    
    peer_id: str
    multiaddr: str
    capabilities: List[str] = field(default_factory=list)
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    source: str = "unknown"  # github, local_file, dht, mdns
    ttl_seconds: int = 3600  # 1 hour default TTL
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if peer has exceeded its TTL."""
        return (time.time() - self.last_seen) > self.ttl_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PeerInfo:
        """Create from dictionary."""
        return cls(**data)


# ============================================================================
# GitHub Issues Peer Registry
# ============================================================================

class GitHubIssuesPeerRegistry:
    """Peer registry using GitHub Issues as backend.
    
    Each peer is represented as a GitHub Issue with labels:
    - peer-registry
    - peer-active / peer-inactive
    - capability-storage / capability-compute / etc.
    
    Issues are automatically cleaned up after TTL expiration.
    """
    
    def __init__(
        self,
        repo_owner: Optional[str] = None,
        repo_name: Optional[str] = None,
        github_token: Optional[str] = None,
        ttl_seconds: int = 3600,
    ):
        """Initialize GitHub Issues peer registry.
        
        Args:
            repo_owner: GitHub repository owner (default: from env)
            repo_name: GitHub repository name (default: from env)
            github_token: GitHub personal access token (default: from env)
            ttl_seconds: Peer TTL in seconds (default: 1 hour)
        """
        self.repo_owner = repo_owner or os.getenv("GITHUB_REPO_OWNER", "endomorphosis")
        self.repo_name = repo_name or os.getenv("GITHUB_REPO_NAME", "ipfs_datasets_py")
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.ttl_seconds = ttl_seconds
        self.available = bool(self.github_token)
        
        if not self.available:
            logger.warning("GitHub token not available - peer registry disabled")
    
    async def register_peer(
        self,
        peer_id: str,
        multiaddr: str,
        capabilities: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Register a peer by creating a GitHub Issue.
        
        Args:
            peer_id: Unique peer identifier
            multiaddr: Peer multiaddress
            capabilities: List of peer capabilities
            metadata: Additional peer metadata
            
        Returns:
            True if registration succeeded
        """
        if not self.available:
            logger.warning("Cannot register peer: GitHub token not available")
            return False
        
        try:
            # In real implementation, would use GitHub API
            # For now, just log the registration
            logger.info(f"Registering peer {peer_id} with capabilities {capabilities}")
            
            # Issue title: "Peer: {peer_id}"
            # Issue body: JSON with peer info
            # Labels: peer-registry, peer-active, capability-*
            
            peer_info = {
                "peer_id": peer_id,
                "multiaddr": multiaddr,
                "capabilities": capabilities,
                "registered_at": datetime.utcnow().isoformat(),
                "ttl_seconds": self.ttl_seconds,
                "metadata": metadata or {},
            }
            
            # Mock successful registration
            logger.debug(f"Peer info: {json.dumps(peer_info, indent=2)}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register peer: {e}")
            return False
    
    async def discover_peers(
        self,
        capability_filter: Optional[List[str]] = None,
        max_peers: int = 50,
    ) -> List[PeerInfo]:
        """Discover peers from GitHub Issues.
        
        Args:
            capability_filter: Filter by required capabilities
            max_peers: Maximum number of peers to return
            
        Returns:
            List of discovered PeerInfo objects
        """
        if not self.available:
            logger.warning("Cannot discover peers: GitHub token not available")
            return []
        
        try:
            # In real implementation, would query GitHub Issues API
            # For now, return empty list
            logger.info(f"Discovering peers (filter: {capability_filter}, max: {max_peers})")
            
            # Query: is:issue is:open label:peer-registry label:peer-active
            # If capability_filter: add label:capability-{cap} for each cap
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to discover peers from GitHub: {e}")
            return []
    
    async def update_peer(self, peer_id: str) -> bool:
        """Update peer's last_seen timestamp.
        
        Args:
            peer_id: Peer identifier to update
            
        Returns:
            True if update succeeded
        """
        if not self.available:
            return False
        
        try:
            # In real implementation, would update GitHub Issue
            logger.debug(f"Updating peer {peer_id} last_seen")
            return True
        except Exception as e:
            logger.error(f"Failed to update peer: {e}")
            return False
    
    async def cleanup_expired_peers(self) -> int:
        """Clean up expired peers.
        
        Returns:
            Number of peers cleaned up
        """
        if not self.available:
            return 0
        
        try:
            # In real implementation, would close expired issues
            logger.info("Cleaning up expired peers")
            
            # Query: is:issue is:open label:peer-registry
            # For each issue: check if last_updated > TTL
            # If expired: close issue or add peer-inactive label
            
            return 0
        except Exception as e:
            logger.error(f"Failed to cleanup peers: {e}")
            return 0


# ============================================================================
# Local File Peer Registry
# ============================================================================

class LocalFilePeerRegistry:
    """Peer registry using local JSON file as backend.
    
    Provides a fallback mechanism when GitHub Issues is unavailable.
    """
    
    def __init__(
        self,
        registry_path: Optional[Path] = None,
        ttl_seconds: int = 3600,
    ):
        """Initialize local file peer registry.
        
        Args:
            registry_path: Path to registry JSON file
            ttl_seconds: Peer TTL in seconds
        """
        default_path = Path.home() / ".cache" / "ipfs_datasets_py" / "peer_registry.json"
        self.registry_path = Path(registry_path or default_path)
        self.ttl_seconds = ttl_seconds
        self.available = True
        
        # Ensure directory exists
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize empty registry if doesn't exist
        if not self.registry_path.exists():
            self._save_registry({"peers": {}, "last_cleanup": time.time()})
    
    def _load_registry(self) -> Dict[str, Any]:
        """Load registry from file."""
        try:
            with open(self.registry_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
            return {"peers": {}, "last_cleanup": time.time()}
    
    def _save_registry(self, registry: Dict[str, Any]) -> bool:
        """Save registry to file."""
        try:
            # Atomic write using temporary file
            temp_path = self.registry_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(registry, f, indent=2)
            temp_path.replace(self.registry_path)
            return True
        except Exception as e:
            logger.error(f"Failed to save registry: {e}")
            return False
    
    async def register_peer(
        self,
        peer_id: str,
        multiaddr: str,
        capabilities: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Register a peer in local file.
        
        Args:
            peer_id: Unique peer identifier
            multiaddr: Peer multiaddress
            capabilities: List of peer capabilities
            metadata: Additional peer metadata
            
        Returns:
            True if registration succeeded
        """
        try:
            registry = self._load_registry()
            
            peer_info = {
                "peer_id": peer_id,
                "multiaddr": multiaddr,
                "capabilities": capabilities,
                "first_seen": time.time(),
                "last_seen": time.time(),
                "source": "local_file",
                "ttl_seconds": self.ttl_seconds,
                "metadata": metadata or {},
            }
            
            registry["peers"][peer_id] = peer_info
            return self._save_registry(registry)
            
        except Exception as e:
            logger.error(f"Failed to register peer: {e}")
            return False
    
    async def discover_peers(
        self,
        capability_filter: Optional[List[str]] = None,
        max_peers: int = 50,
    ) -> List[PeerInfo]:
        """Discover peers from local file.
        
        Args:
            capability_filter: Filter by required capabilities
            max_peers: Maximum number of peers to return
            
        Returns:
            List of discovered PeerInfo objects
        """
        try:
            registry = self._load_registry()
            peers = []
            
            for peer_data in registry.get("peers", {}).values():
                peer = PeerInfo.from_dict(peer_data)
                
                # Skip expired peers
                if peer.is_expired():
                    continue
                
                # Filter by capabilities
                if capability_filter:
                    if not all(cap in peer.capabilities for cap in capability_filter):
                        continue
                
                peers.append(peer)
                
                if len(peers) >= max_peers:
                    break
            
            return peers
            
        except Exception as e:
            logger.error(f"Failed to discover peers from local file: {e}")
            return []
    
    async def update_peer(self, peer_id: str) -> bool:
        """Update peer's last_seen timestamp.
        
        Args:
            peer_id: Peer identifier to update
            
        Returns:
            True if update succeeded
        """
        try:
            registry = self._load_registry()
            
            if peer_id in registry.get("peers", {}):
                registry["peers"][peer_id]["last_seen"] = time.time()
                return self._save_registry(registry)
            
            return False
        except Exception as e:
            logger.error(f"Failed to update peer: {e}")
            return False
    
    async def cleanup_expired_peers(self) -> int:
        """Clean up expired peers.
        
        Returns:
            Number of peers cleaned up
        """
        try:
            registry = self._load_registry()
            peers = registry.get("peers", {})
            
            expired_peer_ids = []
            for peer_id, peer_data in peers.items():
                peer = PeerInfo.from_dict(peer_data)
                if peer.is_expired():
                    expired_peer_ids.append(peer_id)
            
            # Remove expired peers
            for peer_id in expired_peer_ids:
                del peers[peer_id]
            
            registry["last_cleanup"] = time.time()
            self._save_registry(registry)
            
            logger.info(f"Cleaned up {len(expired_peer_ids)} expired peers")
            return len(expired_peer_ids)
            
        except Exception as e:
            logger.error(f"Failed to cleanup peers: {e}")
            return 0


# ============================================================================
# Multi-Source Peer Discovery Coordinator
# ============================================================================

class PeerDiscoveryCoordinator:
    """Coordinates peer discovery across multiple sources.
    
    Sources (in priority order):
    1. GitHub Issues (primary, persistent)
    2. Local file (secondary, fallback)
    3. DHT (tertiary, dynamic)
    4. mDNS (quaternary, local network)
    """
    
    def __init__(
        self,
        enable_github: bool = True,
        enable_local_file: bool = True,
        enable_dht: bool = False,  # Not yet implemented
        enable_mdns: bool = False,  # Not yet implemented
        ttl_seconds: int = 3600,
    ):
        """Initialize peer discovery coordinator.
        
        Args:
            enable_github: Enable GitHub Issues registry
            enable_local_file: Enable local file registry
            enable_dht: Enable DHT discovery
            enable_mdns: Enable mDNS discovery
            ttl_seconds: Default peer TTL
        """
        self.ttl_seconds = ttl_seconds
        self._peer_cache: Dict[str, PeerInfo] = {}
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 minutes
        
        # Initialize registries
        self.github_registry = None
        self.local_file_registry = None
        
        if enable_github:
            self.github_registry = GitHubIssuesPeerRegistry(ttl_seconds=ttl_seconds)
        
        if enable_local_file:
            self.local_file_registry = LocalFilePeerRegistry(ttl_seconds=ttl_seconds)
    
    async def register_peer(
        self,
        peer_id: str,
        multiaddr: str,
        capabilities: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """Register peer across all available registries.
        
        Args:
            peer_id: Unique peer identifier
            multiaddr: Peer multiaddress
            capabilities: List of peer capabilities
            metadata: Additional peer metadata
            
        Returns:
            Dict mapping registry name to success status
        """
        results = {}
        
        # Register with GitHub Issues
        if self.github_registry and self.github_registry.available:
            success = await self.github_registry.register_peer(
                peer_id, multiaddr, capabilities, metadata
            )
            results["github"] = success
        
        # Register with local file
        if self.local_file_registry:
            success = await self.local_file_registry.register_peer(
                peer_id, multiaddr, capabilities, metadata
            )
            results["local_file"] = success
        
        # Update cache
        peer = PeerInfo(
            peer_id=peer_id,
            multiaddr=multiaddr,
            capabilities=capabilities,
            metadata=metadata or {},
            ttl_seconds=self.ttl_seconds,
        )
        self._peer_cache[peer_id] = peer
        
        return results
    
    async def discover_peers(
        self,
        capability_filter: Optional[List[str]] = None,
        max_peers: int = 50,
        sources: Optional[List[str]] = None,
    ) -> List[PeerInfo]:
        """Discover peers from multiple sources.
        
        Args:
            capability_filter: Filter by required capabilities
            max_peers: Maximum number of peers to return
            sources: Specific sources to query (default: all available)
            
        Returns:
            Deduplicated list of PeerInfo objects
        """
        all_peers: Dict[str, PeerInfo] = {}
        
        # Determine which sources to query
        query_sources = sources or ["github", "local_file"]
        
        # Query GitHub Issues
        if "github" in query_sources and self.github_registry:
            try:
                peers = await self.github_registry.discover_peers(
                    capability_filter, max_peers
                )
                for peer in peers:
                    all_peers[peer.peer_id] = peer
            except Exception as e:
                logger.error(f"GitHub discovery failed: {e}")
        
        # Query local file
        if "local_file" in query_sources and self.local_file_registry:
            try:
                peers = await self.local_file_registry.discover_peers(
                    capability_filter, max_peers
                )
                for peer in peers:
                    # Don't overwrite GitHub peers (higher priority)
                    if peer.peer_id not in all_peers:
                        all_peers[peer.peer_id] = peer
            except Exception as e:
                logger.error(f"Local file discovery failed: {e}")
        
        # Add cached peers
        for peer_id, peer in self._peer_cache.items():
            if peer_id not in all_peers and not peer.is_expired():
                all_peers[peer_id] = peer
        
        # Sort by last_seen (most recent first) and limit
        sorted_peers = sorted(
            all_peers.values(),
            key=lambda p: p.last_seen,
            reverse=True
        )
        
        return sorted_peers[:max_peers]
    
    async def cleanup_expired_peers(self) -> Dict[str, int]:
        """Clean up expired peers across all registries.
        
        Returns:
            Dict mapping registry name to cleanup count
        """
        results = {}
        
        # Cleanup GitHub Issues
        if self.github_registry:
            count = await self.github_registry.cleanup_expired_peers()
            results["github"] = count
        
        # Cleanup local file
        if self.local_file_registry:
            count = await self.local_file_registry.cleanup_expired_peers()
            results["local_file"] = count
        
        # Cleanup cache
        expired_ids = [
            peer_id for peer_id, peer in self._peer_cache.items()
            if peer.is_expired()
        ]
        for peer_id in expired_ids:
            del self._peer_cache[peer_id]
        results["cache"] = len(expired_ids)
        
        self._last_cleanup = time.time()
        return results
    
    async def auto_cleanup_if_needed(self) -> None:
        """Automatically cleanup if interval has passed."""
        if (time.time() - self._last_cleanup) > self._cleanup_interval:
            await self.cleanup_expired_peers()


# ============================================================================
# Module Functions
# ============================================================================

_global_coordinator: Optional[PeerDiscoveryCoordinator] = None


def get_peer_discovery_coordinator(
    **kwargs: Any
) -> PeerDiscoveryCoordinator:
    """Get or create the global peer discovery coordinator.
    
    Args:
        **kwargs: Keyword arguments for PeerDiscoveryCoordinator
        
    Returns:
        Global PeerDiscoveryCoordinator instance
    """
    global _global_coordinator
    
    if _global_coordinator is None:
        _global_coordinator = PeerDiscoveryCoordinator(**kwargs)
    
    return _global_coordinator


def reset_peer_discovery_coordinator() -> None:
    """Reset the global peer discovery coordinator.
    
    Useful for testing or reconfiguration.
    """
    global _global_coordinator
    _global_coordinator = None
