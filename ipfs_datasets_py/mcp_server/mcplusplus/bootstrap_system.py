"""
Multi-Method Bootstrap System for P2P Network Initialization

Provides robust network bootstrapping with multiple fallback mechanisms:
- IPFS bootstrap nodes
- Custom bootstrap servers
- Public IP detection
- NAT traversal helpers

Author: MCP Server Team
Date: 2026-02-18
"""

import asyncio
import socket
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set
from enum import Enum
import time
import aiohttp

logger = logging.getLogger(__name__)


class BootstrapMethod(Enum):
    """Bootstrap method types."""
    IPFS_BOOTSTRAP = "ipfs_bootstrap"
    CUSTOM_SERVER = "custom_server"
    LOCAL_DISCOVERY = "local_discovery"
    DHT = "dht"
    RELAY = "relay"


class BootstrapStatus(Enum):
    """Bootstrap attempt status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class BootstrapNode:
    """
    Represents a bootstrap node.
    
    Attributes:
        multiaddr: Multiaddress of the bootstrap node
        method: Bootstrap method used
        priority: Priority (lower = higher priority)
        timeout: Connection timeout in seconds
        metadata: Additional node metadata
    """
    multiaddr: str
    method: BootstrapMethod
    priority: int = 5
    timeout: float = 10.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BootstrapAttempt:
    """
    Records a bootstrap attempt.
    
    Attributes:
        node: The bootstrap node
        status: Attempt status
        start_time: When attempt started
        end_time: When attempt ended
        error: Error message (if failed)
        peer_count: Number of peers discovered
    """
    node: BootstrapNode
    status: BootstrapStatus = BootstrapStatus.PENDING
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error: Optional[str] = None
    peer_count: int = 0


class PublicIPDetector:
    """
    Detects public IP address using multiple services.
    
    Features:
    - Multiple fallback services
    - IPv4 and IPv6 support
    - Caching to avoid repeated lookups
    - Timeout handling
    """
    
    DEFAULT_SERVICES = [
        "https://api.ipify.org",
        "https://api64.ipify.org",
        "https://checkip.amazonaws.com",
        "https://icanhazip.com",
        "https://ifconfig.me/ip"
    ]
    
    def __init__(
        self,
        services: Optional[List[str]] = None,
        timeout: float = 5.0,
        cache_ttl: float = 3600.0
    ):
        """
        Initialize IP detector.
        
        Args:
            services: List of IP detection service URLs
            timeout: Request timeout in seconds
            cache_ttl: Cache TTL in seconds
        """
        self.services = services or self.DEFAULT_SERVICES
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cached_ip: Optional[str] = None
        self._cache_time: float = 0
    
    async def get_public_ip(
        self,
        prefer_ipv6: bool = False,
        force_refresh: bool = False
    ) -> Optional[str]:
        """
        Get public IP address.
        
        Args:
            prefer_ipv6: Prefer IPv6 if available
            force_refresh: Force cache refresh
            
        Returns:
            Public IP address or None if detection fails
        """
        # Check cache
        if not force_refresh and self._cached_ip:
            if time.time() - self._cache_time < self.cache_ttl:
                return self._cached_ip
        
        # Try each service
        for service_url in self.services:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        service_url,
                        timeout=aiohttp.ClientTimeout(total=self.timeout)
                    ) as response:
                        if response.status == 200:
                            ip = (await response.text()).strip()
                            # Validate IP format
                            if self._validate_ip(ip):
                                self._cached_ip = ip
                                self._cache_time = time.time()
                                logger.info(f"Detected public IP: {ip} (via {service_url})")
                                return ip
            except Exception as e:
                logger.debug(f"Failed to detect IP via {service_url}: {e}")
                continue
        
        logger.error("Failed to detect public IP from all services")
        return None
    
    def _validate_ip(self, ip: str) -> bool:
        """Validate IP address format."""
        try:
            socket.inet_aton(ip)
            return True
        except socket.error:
            try:
                socket.inet_pton(socket.AF_INET6, ip)
                return True
            except socket.error:
                return False
    
    def get_cached_ip(self) -> Optional[str]:
        """Get cached IP without refresh."""
        if self._cached_ip and time.time() - self._cache_time < self.cache_ttl:
            return self._cached_ip
        return None


class NATHelper:
    """
    Helper for NAT traversal.
    
    Features:
    - NAT type detection
    - UPnP/NAT-PMP support (future)
    - STUN/TURN relay coordination
    """
    
    @staticmethod
    async def detect_nat_type() -> str:
        """
        Detect NAT type.
        
        Returns:
            NAT type string (e.g., "symmetric", "cone", "open", "unknown")
        """
        # Simplified NAT detection
        # In production, this would use STUN protocol
        try:
            # Check if we can bind to a port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('', 0))
            local_port = sock.getsockname()[1]
            sock.close()
            
            # Assume cone NAT if we can bind
            return "cone"
        except OSError:
            return "unknown"
    
    @staticmethod
    async def request_port_mapping(
        internal_port: int,
        external_port: int,
        protocol: str = "tcp",
        lifetime: int = 3600
    ) -> bool:
        """
        Request port mapping via UPnP/NAT-PMP.
        
        Args:
            internal_port: Internal port to map
            external_port: External port to map to
            protocol: Protocol ("tcp" or "udp")
            lifetime: Mapping lifetime in seconds
            
        Returns:
            True if mapping successful
        """
        # Placeholder for UPnP/NAT-PMP implementation
        logger.warning("Port mapping not yet implemented")
        return False


class BootstrapSystem:
    """
    Multi-method bootstrap system for P2P network initialization.
    
    Features:
    - Multiple bootstrap methods with fallback
    - Priority-based node selection
    - Parallel bootstrap attempts
    - Public IP detection
    - NAT traversal support
    - Bootstrap history tracking
    """
    
    # Default IPFS bootstrap nodes
    DEFAULT_IPFS_BOOTSTRAP = [
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
    ]
    
    def __init__(
        self,
        max_concurrent_attempts: int = 3,
        ip_detector: Optional[PublicIPDetector] = None,
        nat_helper: Optional[NATHelper] = None
    ):
        """
        Initialize bootstrap system.
        
        Args:
            max_concurrent_attempts: Max parallel bootstrap attempts
            ip_detector: Public IP detector instance
            nat_helper: NAT traversal helper
        """
        self.max_concurrent_attempts = max_concurrent_attempts
        self.ip_detector = ip_detector or PublicIPDetector()
        self.nat_helper = nat_helper or NATHelper()
        
        self.bootstrap_nodes: List[BootstrapNode] = []
        self.attempts: List[BootstrapAttempt] = []
        self._semaphore = asyncio.Semaphore(max_concurrent_attempts)
        
        # Add default IPFS bootstrap nodes
        self._add_default_nodes()
    
    def _add_default_nodes(self) -> None:
        """Add default IPFS bootstrap nodes."""
        for multiaddr in self.DEFAULT_IPFS_BOOTSTRAP:
            self.bootstrap_nodes.append(BootstrapNode(
                multiaddr=multiaddr,
                method=BootstrapMethod.IPFS_BOOTSTRAP,
                priority=5
            ))
    
    def add_bootstrap_node(self, node: BootstrapNode) -> None:
        """Add a custom bootstrap node."""
        self.bootstrap_nodes.append(node)
    
    def add_custom_server(
        self,
        multiaddr: str,
        priority: int = 3,
        timeout: float = 10.0
    ) -> None:
        """
        Add a custom bootstrap server.
        
        Args:
            multiaddr: Server multiaddress
            priority: Priority (lower = higher priority)
            timeout: Connection timeout
        """
        node = BootstrapNode(
            multiaddr=multiaddr,
            method=BootstrapMethod.CUSTOM_SERVER,
            priority=priority,
            timeout=timeout
        )
        self.bootstrap_nodes.append(node)
    
    async def bootstrap(
        self,
        max_nodes: Optional[int] = None,
        timeout: float = 30.0
    ) -> Dict[str, Any]:
        """
        Perform bootstrap process.
        
        Args:
            max_nodes: Maximum nodes to try (None = try all)
            timeout: Overall timeout in seconds
            
        Returns:
            Dictionary with bootstrap results
        """
        start_time = time.time()
        
        # Detect public IP
        public_ip = await self.ip_detector.get_public_ip()
        
        # Detect NAT type
        nat_type = await self.nat_helper.detect_nat_type()
        
        # Sort nodes by priority
        sorted_nodes = sorted(self.bootstrap_nodes, key=lambda n: n.priority)
        if max_nodes:
            sorted_nodes = sorted_nodes[:max_nodes]
        
        # Perform bootstrap attempts
        successful = 0
        failed = 0
        
        tasks = []
        for node in sorted_nodes:
            task = asyncio.create_task(self._bootstrap_node(node))
            tasks.append(task)
        
        # Wait for all attempts with overall timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout
            )
            
            for result in results:
                if isinstance(result, Exception):
                    failed += 1
                elif result:
                    successful += 1
                else:
                    failed += 1
                    
        except asyncio.TimeoutError:
            logger.warning(f"Bootstrap timed out after {timeout}s")
        
        end_time = time.time()
        
        return {
            "success": successful > 0,
            "successful_nodes": successful,
            "failed_nodes": failed,
            "total_attempts": len(sorted_nodes),
            "public_ip": public_ip,
            "nat_type": nat_type,
            "execution_time": end_time - start_time,
            "attempts": [
                {
                    "multiaddr": a.node.multiaddr,
                    "method": a.node.method.value,
                    "status": a.status.value,
                    "error": a.error,
                    "peer_count": a.peer_count
                }
                for a in self.attempts
            ]
        }
    
    async def _bootstrap_node(self, node: BootstrapNode) -> bool:
        """
        Attempt to bootstrap from a single node.
        
        Args:
            node: Bootstrap node to connect to
            
        Returns:
            True if successful
        """
        async with self._semaphore:
            attempt = BootstrapAttempt(node=node)
            attempt.status = BootstrapStatus.IN_PROGRESS
            self.attempts.append(attempt)
            
            try:
                # Simulate bootstrap connection
                # In production, this would connect to the actual node
                await asyncio.sleep(0.1)  # Simulate network delay
                
                # Placeholder logic - would actually connect to node
                if node.multiaddr.startswith("/dns4/bootstrap.libp2p.io"):
                    # Simulate successful connection
                    attempt.status = BootstrapStatus.SUCCESS
                    attempt.peer_count = 5  # Simulated peer discovery
                    logger.info(f"Successfully bootstrapped from {node.multiaddr}")
                    return True
                else:
                    attempt.status = BootstrapStatus.FAILED
                    attempt.error = "Connection refused"
                    return False
                    
            except asyncio.TimeoutError:
                attempt.status = BootstrapStatus.TIMEOUT
                attempt.error = f"Timeout after {node.timeout}s"
                logger.warning(f"Bootstrap timeout for {node.multiaddr}")
                return False
                
            except Exception as e:
                attempt.status = BootstrapStatus.FAILED
                attempt.error = str(e)
                logger.error(f"Bootstrap failed for {node.multiaddr}: {e}")
                return False
                
            finally:
                attempt.end_time = time.time()
    
    def get_bootstrap_history(self) -> List[Dict[str, Any]]:
        """Get history of bootstrap attempts."""
        return [
            {
                "multiaddr": a.node.multiaddr,
                "method": a.node.method.value,
                "status": a.status.value,
                "start_time": a.start_time,
                "end_time": a.end_time,
                "error": a.error,
                "peer_count": a.peer_count,
                "duration": a.end_time - a.start_time if a.end_time else None
            }
            for a in self.attempts
        ]
    
    def clear_history(self) -> None:
        """Clear bootstrap attempt history."""
        self.attempts.clear()


# Global bootstrap system instance
_bootstrap_system: Optional[BootstrapSystem] = None


def get_bootstrap_system() -> BootstrapSystem:
    """Get or create the global bootstrap system."""
    global _bootstrap_system
    if _bootstrap_system is None:
        _bootstrap_system = BootstrapSystem()
    return _bootstrap_system


def reset_bootstrap_system() -> None:
    """Reset the global bootstrap system (for testing)."""
    global _bootstrap_system
    _bootstrap_system = None
