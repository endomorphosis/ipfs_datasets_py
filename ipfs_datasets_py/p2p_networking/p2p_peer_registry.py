"""
P2P Peer Registry for GitHub Actions Cache Sharing

Uses GitHub Actions cache API to maintain a registry of active P2P cache peers
across different self-hosted runners. This enables peer discovery without 
requiring a central rendezvous server.
"""

import json
import logging
import os
import socket
import subprocess
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class P2PPeerRegistry:
    """
    Manages peer discovery for P2P cache sharing across GitHub Actions runners.
    
    Uses GitHub CLI to store/retrieve peer information in GitHub Actions cache,
    allowing runners to discover each other without a central server.
    """
    
    def __init__(
        self,
        repo: str,
        runner_name: Optional[str] = None,
        cache_prefix: str = "p2p-peer-registry",
        peer_ttl_minutes: int = 30
    ):
        """
        Initialize peer registry.
        
        Args:
            repo: GitHub repository (e.g., 'owner/repo')
            runner_name: Name of this runner (auto-detected if None)
            cache_prefix: Prefix for cache keys
            peer_ttl_minutes: How long peer entries are valid
        """
        self.repo = repo
        self.runner_name = runner_name or self._detect_runner_name()
        self.cache_prefix = cache_prefix
        self.peer_ttl = timedelta(minutes=peer_ttl_minutes)
        
        # Detect public IP for this runner
        self.public_ip = self._detect_public_ip()
        
        logger.info(f"P2P Peer Registry initialized: runner={self.runner_name}, ip={self.public_ip}")
    
    def _detect_runner_name(self) -> str:
        """Detect the GitHub Actions runner name."""
        # Try environment variables
        runner_name = os.environ.get("RUNNER_NAME")
        if runner_name:
            return runner_name
        
        # Try hostname
        try:
            return socket.gethostname()
        except Exception:
            return "unknown-runner"
    
    def _detect_public_ip(self) -> Optional[str]:
        """
        Detect the public IP address of this runner.
        
        This is needed for NAT traversal and peer connectivity.
        """
        try:
            # Try multiple services for redundancy
            services = [
                "https://api.ipify.org",
                "https://ifconfig.me/ip",
                "https://icanhazip.com"
            ]
            
            import urllib.request
            for service in services:
                try:
                    with urllib.request.urlopen(service, timeout=5) as response:
                        return response.read().decode('utf-8').strip()
                except Exception:
                    continue
            
            return None
        except Exception as e:
            logger.warning(f"Failed to detect public IP: {e}")
            return None
    
    def register_peer(
        self,
        peer_id: str,
        listen_port: int,
        multiaddr: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Register this runner as an active peer.
        
        Args:
            peer_id: libp2p peer ID
            listen_port: Port the peer is listening on
            multiaddr: Full libp2p multiaddr
            metadata: Optional additional metadata
            
        Returns:
            True if registration succeeded
        """
        try:
            peer_info = {
                "peer_id": peer_id,
                "runner_name": self.runner_name,
                "public_ip": self.public_ip,
                "listen_port": listen_port,
                "multiaddr": multiaddr,
                "last_seen": datetime.utcnow().isoformat(),
                "metadata": metadata or {}
            }
            
            # Store peer info in GitHub Actions cache
            cache_key = f"{self.cache_prefix}-{self.runner_name}"
            
            # Create temp file with peer info
            temp_file = f"/tmp/{cache_key}.json"
            with open(temp_file, "w") as f:
                json.dump(peer_info, f)
            
            # Upload to GitHub Actions cache using gh CLI
            result = subprocess.run(
                [
                    "gh", "cache", "upload",
                    temp_file,
                    "--key", cache_key,
                    "--repo", self.repo
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Clean up temp file
            os.unlink(temp_file)
            
            if result.returncode == 0:
                logger.info(f"✓ Registered peer: {peer_id[:16]}... on {self.public_ip}:{listen_port}")
                return True
            else:
                logger.warning(f"Failed to register peer: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error registering peer: {e}")
            return False
    
    def discover_peers(self, max_peers: int = 10) -> List[Dict]:
        """
        Discover active peers from the registry.
        
        Args:
            max_peers: Maximum number of peers to return
            
        Returns:
            List of peer info dictionaries
        """
        try:
            # List all cache entries with our prefix
            result = subprocess.run(
                [
                    "gh", "cache", "list",
                    "--repo", self.repo,
                    "--json", "key,createdAt,sizeInBytes"
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.warning(f"Failed to list cache: {result.stderr}")
                return []
            
            # Parse cache list
            cache_entries = json.loads(result.stdout)
            
            # Filter for peer registry entries
            peer_keys = [
                entry["key"] 
                for entry in cache_entries 
                if entry["key"].startswith(self.cache_prefix)
            ]
            
            # Download and parse peer info
            peers = []
            for cache_key in peer_keys[:max_peers]:
                # Skip our own entry
                if cache_key == f"{self.cache_prefix}-{self.runner_name}":
                    continue
                
                try:
                    # Download peer info
                    temp_file = f"/tmp/{cache_key}.json"
                    download_result = subprocess.run(
                        [
                            "gh", "cache", "download",
                            cache_key,
                            "--dir", "/tmp",
                            "--repo", self.repo
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if download_result.returncode == 0 and os.path.exists(temp_file):
                        with open(temp_file, "r") as f:
                            peer_info = json.load(f)
                        
                        # Check if peer is still active (within TTL)
                        last_seen = datetime.fromisoformat(peer_info["last_seen"])
                        if datetime.utcnow() - last_seen < self.peer_ttl:
                            peers.append(peer_info)
                        else:
                            logger.debug(f"Peer {peer_info['peer_id'][:16]}... expired")
                        
                        # Clean up temp file
                        os.unlink(temp_file)
                        
                except Exception as e:
                    logger.debug(f"Failed to fetch peer {cache_key}: {e}")
                    continue
            
            logger.info(f"✓ Discovered {len(peers)} active peers")
            return peers
            
        except Exception as e:
            logger.error(f"Error discovering peers: {e}")
            return []
    
    def get_bootstrap_addrs(self, max_peers: int = 5) -> List[str]:
        """
        Get bootstrap multiaddrs for discovered peers.
        
        Args:
            max_peers: Maximum number of bootstrap peers
            
        Returns:
            List of libp2p multiaddrs
        """
        peers = self.discover_peers(max_peers)
        return [peer["multiaddr"] for peer in peers if peer.get("multiaddr")]
    
    def cleanup_stale_peers(self) -> int:
        """
        Remove stale peer entries from the registry.
        
        Returns:
            Number of peers cleaned up
        """
        try:
            # Get all peer entries
            result = subprocess.run(
                [
                    "gh", "cache", "list",
                    "--repo", self.repo,
                    "--json", "key,createdAt"
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return 0
            
            cache_entries = json.loads(result.stdout)
            
            # Find stale entries
            cleaned = 0
            for entry in cache_entries:
                key = entry["key"]
                if not key.startswith(self.cache_prefix):
                    continue
                
                created_at = datetime.fromisoformat(entry["createdAt"].replace("Z", "+00:00"))
                if datetime.utcnow().replace(tzinfo=created_at.tzinfo) - created_at > self.peer_ttl:
                    # Delete stale entry
                    subprocess.run(
                        ["gh", "cache", "delete", key, "--repo", self.repo],
                        capture_output=True,
                        timeout=30
                    )
                    cleaned += 1
                    logger.debug(f"Cleaned up stale peer: {key}")
            
            if cleaned > 0:
                logger.info(f"✓ Cleaned up {cleaned} stale peer(s)")
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Error cleaning up peers: {e}")
            return 0
    
    def heartbeat(self, peer_id: str, listen_port: int, multiaddr: str) -> None:
        """
        Send periodic heartbeat to keep peer entry fresh.
        
        Should be called every ~5-10 minutes.
        """
        self.register_peer(peer_id, listen_port, multiaddr)
