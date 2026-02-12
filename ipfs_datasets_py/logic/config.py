"""Configuration management for logic module.

This module provides centralized configuration management for the entire
logic module, supporting both file-based and environment-based configuration.

Usage:
    from ipfs_datasets_py.logic.config import get_config
    
    config = get_config()
    if config.provers['z3'].enabled:
        # Use Z3 prover
        pass
"""

import os
import yaml
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProverConfig:
    """Configuration for a single prover."""
    enabled: bool = True
    timeout: float = 5.0
    max_memory_mb: int = 2048
    options: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class CacheConfig:
    """Configuration for caching."""
    backend: str = "memory"  # "memory" or "redis"
    maxsize: int = 10000
    ttl: int = 3600  # Time-to-live in seconds
    redis_url: Optional[str] = None
    redis_db: int = 0
    enable_persistence: bool = False
    persistence_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class SecurityConfig:
    """Configuration for security."""
    rate_limit_calls: int = 100
    rate_limit_period: int = 60  # seconds
    max_text_length: int = 10000
    max_formula_depth: int = 100
    max_formula_complexity: int = 1000
    enable_audit_log: bool = True
    audit_log_path: Optional[str] = None
    enable_input_validation: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class MonitoringConfig:
    """Configuration for monitoring."""
    enabled: bool = True
    port: int = 9090
    log_level: str = "INFO"
    metrics_backend: str = "prometheus"  # "prometheus" or "statsd"
    enable_tracing: bool = False
    tracing_backend: str = "opentelemetry"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class LogicConfig:
    """Master configuration for logic module."""
    
    provers: Dict[str, ProverConfig] = field(default_factory=lambda: {
        'native': ProverConfig(enabled=True, timeout=5.0),
        'z3': ProverConfig(enabled=True, timeout=5.0),
        'cvc5': ProverConfig(enabled=False, timeout=10.0),
        'lean': ProverConfig(enabled=False, timeout=30.0),
        'coq': ProverConfig(enabled=False, timeout=30.0),
        'symbolicai': ProverConfig(enabled=False, timeout=10.0)
    })
    cache: CacheConfig = field(default_factory=CacheConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    
    @classmethod
    def from_file(cls, path: Path) -> 'LogicConfig':
        """Load configuration from YAML file.
        
        Args:
            path: Path to YAML configuration file
            
        Returns:
            LogicConfig instance
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config file is invalid
        """
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise ValueError(f"Failed to parse config file: {e}")
        
        # Parse provers
        provers = {}
        for name, prover_data in data.get('provers', {}).items():
            provers[name] = ProverConfig(**prover_data)
        
        # Parse cache
        cache_data = data.get('cache', {})
        cache = CacheConfig(**cache_data)
        
        # Parse security
        security_data = data.get('security', {})
        security = SecurityConfig(**security_data)
        
        # Parse monitoring
        monitoring_data = data.get('monitoring', {})
        monitoring = MonitoringConfig(**monitoring_data)
        
        return cls(
            provers=provers,
            cache=cache,
            security=security,
            monitoring=monitoring
        )
    
    @classmethod
    def from_env(cls) -> 'LogicConfig':
        """Load configuration from environment variables.
        
        Environment variables:
            Z3_ENABLED: Enable Z3 prover (default: true)
            Z3_TIMEOUT: Z3 timeout in seconds (default: 5.0)
            SYMBOLICAI_API_KEY: SymbolicAI API key (if set, enables SymbolicAI)
            SYMBOLICAI_TIMEOUT: SymbolicAI timeout (default: 10.0)
            CACHE_BACKEND: Cache backend (memory or redis)
            REDIS_URL: Redis URL for distributed cache
            RATE_LIMIT_CALLS: Rate limit calls per period (default: 100)
            RATE_LIMIT_PERIOD: Rate limit period in seconds (default: 60)
            LOG_LEVEL: Logging level (default: INFO)
            
        Returns:
            LogicConfig instance
        """
        # Parse provers
        provers = {
            'native': ProverConfig(
                enabled=True,
                timeout=float(os.getenv('NATIVE_TIMEOUT', '5.0'))
            ),
            'z3': ProverConfig(
                enabled=os.getenv('Z3_ENABLED', 'true').lower() == 'true',
                timeout=float(os.getenv('Z3_TIMEOUT', '5.0')),
                max_memory_mb=int(os.getenv('Z3_MAX_MEMORY_MB', '2048'))
            ),
            'cvc5': ProverConfig(
                enabled=os.getenv('CVC5_ENABLED', 'false').lower() == 'true',
                timeout=float(os.getenv('CVC5_TIMEOUT', '10.0'))
            ),
            'symbolicai': ProverConfig(
                enabled=bool(os.getenv('SYMBOLICAI_API_KEY')),
                timeout=float(os.getenv('SYMBOLICAI_TIMEOUT', '10.0')),
                options={
                    'model': os.getenv('SYMBOLICAI_MODEL', 'gpt-4'),
                    'temperature': float(os.getenv('SYMBOLICAI_TEMPERATURE', '0.0'))
                }
            )
        }
        
        # Parse cache
        cache = CacheConfig(
            backend=os.getenv('CACHE_BACKEND', 'memory'),
            maxsize=int(os.getenv('CACHE_MAXSIZE', '10000')),
            ttl=int(os.getenv('CACHE_TTL', '3600')),
            redis_url=os.getenv('REDIS_URL'),
            redis_db=int(os.getenv('REDIS_DB', '0'))
        )
        
        # Parse security
        security = SecurityConfig(
            rate_limit_calls=int(os.getenv('RATE_LIMIT_CALLS', '100')),
            rate_limit_period=int(os.getenv('RATE_LIMIT_PERIOD', '60')),
            max_text_length=int(os.getenv('MAX_TEXT_LENGTH', '10000')),
            max_formula_depth=int(os.getenv('MAX_FORMULA_DEPTH', '100')),
            max_formula_complexity=int(os.getenv('MAX_FORMULA_COMPLEXITY', '1000')),
            enable_audit_log=os.getenv('ENABLE_AUDIT_LOG', 'true').lower() == 'true',
            audit_log_path=os.getenv('AUDIT_LOG_PATH')
        )
        
        # Parse monitoring
        monitoring = MonitoringConfig(
            enabled=os.getenv('ENABLE_MONITORING', 'true').lower() == 'true',
            port=int(os.getenv('METRICS_PORT', '9090')),
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            enable_tracing=os.getenv('ENABLE_TRACING', 'false').lower() == 'true'
        )
        
        return cls(
            provers=provers,
            cache=cache,
            security=security,
            monitoring=monitoring
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary.
        
        Returns:
            Dictionary representation
        """
        return {
            'provers': {
                name: prover.to_dict()
                for name, prover in self.provers.items()
            },
            'cache': self.cache.to_dict(),
            'security': self.security.to_dict(),
            'monitoring': self.monitoring.to_dict()
        }
    
    def save(self, path: Path) -> None:
        """Save configuration to YAML file.
        
        Args:
            path: Output file path
        """
        with open(path, 'w') as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)
        
        logger.info(f"Configuration saved to {path}")


# Global configuration instance
_config: Optional[LogicConfig] = None


def get_config() -> LogicConfig:
    """Get global configuration instance.
    
    This function returns the global configuration singleton. On first call,
    it attempts to load configuration from:
    1. config.yaml in current directory
    2. Environment variables
    3. Default values
    
    Returns:
        LogicConfig instance
    """
    global _config
    if _config is None:
        # Try to load from file
        config_path = Path('config.yaml')
        if config_path.exists():
            logger.info(f"Loading configuration from {config_path}")
            _config = LogicConfig.from_file(config_path)
        else:
            # Fall back to environment variables
            logger.info("Loading configuration from environment variables")
            _config = LogicConfig.from_env()
    
    return _config


def set_config(config: LogicConfig) -> None:
    """Set global configuration instance.
    
    Args:
        config: LogicConfig instance to set as global
    """
    global _config
    _config = config
    logger.info("Global configuration updated")


def reload_config() -> LogicConfig:
    """Reload configuration from file or environment.
    
    This forces a reload of the configuration, useful for
    picking up changes without restarting the application.
    
    Returns:
        Reloaded LogicConfig instance
    """
    global _config
    _config = None
    return get_config()
