"""Configuration loader for cache settings.

This module loads cache configuration from .github/cache-config.yml and 
.github/p2p-config.yml files, providing centralized configuration for
all cache implementations.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

logger = logging.getLogger(__name__)


class CacheConfig:
    """Cache configuration loaded from YAML files.
    
    Loads settings from:
    - .github/cache-config.yml - Cache and rate limiting settings
    - .github/p2p-config.yml - P2P network settings
    
    Attributes:
        enabled: Whether caching is enabled
        maxsize: Maximum cache entries
        default_ttl: Default TTL in seconds
        directory: Cache directory path
        persistence: Enable persistent cache
        operation_ttls: Per-operation TTL overrides
        rate_limiting: Rate limit settings
        p2p_enabled: Whether P2P is enabled
        p2p_config: P2P network configuration
    """
    
    def __init__(
        self,
        config_dir: Optional[Path] = None,
        cache_config_file: Optional[Path] = None,
        p2p_config_file: Optional[Path] = None
    ):
        """Initialize cache configuration.
        
        Args:
            config_dir: Directory containing config files (default: .github/)
            cache_config_file: Override cache config file path
            p2p_config_file: Override P2P config file path
        """
        # Determine config directory
        if config_dir is None:
            # Try to find .github directory
            cwd = Path.cwd()
            config_dir = cwd / ".github"
            if not config_dir.exists():
                # Try parent directories
                for parent in cwd.parents:
                    potential = parent / ".github"
                    if potential.exists():
                        config_dir = potential
                        break
        
        self.config_dir = Path(config_dir)
        
        # Load cache config
        if cache_config_file is None:
            cache_config_file = self.config_dir / "cache-config.yml"
        
        self._cache_config = self._load_yaml(cache_config_file)
        
        # Load P2P config
        if p2p_config_file is None:
            p2p_config_file = self.config_dir / "p2p-config.yml"
        
        self._p2p_config = self._load_yaml(p2p_config_file)
        
        logger.info(f"Loaded cache config from {config_dir}")
    
    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """Load YAML configuration file.
        
        Args:
            path: Path to YAML file
            
        Returns:
            Parsed configuration dict
        """
        try:
            if not path.exists():
                logger.warning(f"Config file not found: {path}, using defaults")
                return {}
            
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
                return config if config is not None else {}
                
        except Exception as e:
            logger.error(f"Error loading config from {path}: {e}")
            return {}
    
    @property
    def enabled(self) -> bool:
        """Check if caching is enabled."""
        return self._cache_config.get('cache', {}).get('enabled', True)
    
    @property
    def maxsize(self) -> int:
        """Get maximum cache size."""
        return self._cache_config.get('cache', {}).get('max_size', 5000)
    
    @property
    def default_ttl(self) -> int:
        """Get default TTL in seconds."""
        return self._cache_config.get('cache', {}).get('default_ttl', 300)
    
    @property
    def directory(self) -> Path:
        """Get cache directory path."""
        dir_str = self._cache_config.get('cache', {}).get('directory', '~/.cache/github-api-p2p')
        return Path(dir_str).expanduser()
    
    @property
    def persistence(self) -> bool:
        """Check if persistence is enabled."""
        return self._cache_config.get('cache', {}).get('persistence', True)
    
    @property
    def operation_ttls(self) -> Dict[str, int]:
        """Get per-operation TTL overrides."""
        return self._cache_config.get('operation_ttls', {})
    
    def get_operation_ttl(self, operation: str) -> int:
        """Get TTL for specific operation.
        
        Args:
            operation: Operation name
            
        Returns:
            TTL in seconds (default_ttl if not specified)
        """
        return self.operation_ttls.get(operation, self.default_ttl)
    
    @property
    def rate_limiting(self) -> Dict[str, Any]:
        """Get rate limiting configuration."""
        return self._cache_config.get('rate_limiting', {})
    
    @property
    def warning_threshold(self) -> int:
        """Get rate limit warning threshold."""
        return self.rate_limiting.get('warning_threshold', 100)
    
    @property
    def aggressive_threshold(self) -> int:
        """Get aggressive caching threshold."""
        return self.rate_limiting.get('aggressive_threshold', 50)
    
    @property
    def cache_first_mode(self) -> bool:
        """Check if cache-first mode is enabled."""
        return self.rate_limiting.get('cache_first_mode', True)
    
    @property
    def p2p_enabled(self) -> bool:
        """Check if P2P caching is enabled."""
        cache_p2p = self._cache_config.get('p2p', {}).get('enabled', False)
        network_enabled = self._p2p_config.get('network', {}).get('protocol_version') is not None
        return cache_p2p and network_enabled
    
    @property
    def p2p_config(self) -> Dict[str, Any]:
        """Get P2P network configuration."""
        return self._p2p_config
    
    @property
    def listen_port(self) -> int:
        """Get P2P listen port."""
        cache_port = self._cache_config.get('p2p', {}).get('listen_port', 9000)
        network_port = self._p2p_config.get('network', {}).get('listen', {}).get('port_range', {}).get('start', 9000)
        return cache_port if cache_port else network_port
    
    @property
    def peer_discovery(self) -> bool:
        """Check if peer discovery is enabled."""
        return self._p2p_config.get('discovery', {}).get('enabled', True)
    
    @property
    def encryption_enabled(self) -> bool:
        """Check if P2P encryption is enabled."""
        cache_encryption = self._cache_config.get('p2p', {}).get('encryption', {}).get('enabled', True)
        network_encryption = self._p2p_config.get('security', {}).get('encryption', {}).get('enabled', True)
        return cache_encryption and network_encryption
    
    @property
    def monitoring_enabled(self) -> bool:
        """Check if monitoring is enabled."""
        return self._cache_config.get('monitoring', {}).get('enabled', True)
    
    @property
    def export_metrics(self) -> bool:
        """Check if metrics export is enabled."""
        return self._cache_config.get('monitoring', {}).get('export_metrics', False)
    
    @property
    def metrics_format(self) -> str:
        """Get metrics export format."""
        return self._cache_config.get('monitoring', {}).get('metrics_format', 'json')


# Global config instance
_global_config: Optional[CacheConfig] = None


def get_global_config() -> CacheConfig:
    """Get or create global cache configuration.
    
    Returns:
        Global CacheConfig instance
    """
    global _global_config
    if _global_config is None:
        _global_config = CacheConfig()
    return _global_config


def set_global_config(config: CacheConfig) -> None:
    """Set global cache configuration.
    
    Args:
        config: CacheConfig instance to use globally
    """
    global _global_config
    _global_config = config
