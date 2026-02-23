"""Unified configuration for all optimizer types.

This module provides a single, comprehensive OptimizerConfig dataclass that can
be used across GraphRAG, LogicTheoremOptimizer, and AgenticOptimizer, eliminating
configuration drift and providing a consistent interface for all optimizers.

The config supports factory methods (from_dict, from_env, merge) for flexible
instantiation and environment-based configuration.

Example:
    >>> from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
    >>>
    >>> # Load from dictionary
    >>> config_dict = {
    ...     "domain": "legal",
    ...     "max_rounds": 5,
    ...     "timeout_sec": 300,
    ...     "feature_flags": {"enable_llm": True}
    ... }
    >>> config = OptimizerConfig.from_dict(config_dict)
    >>>
    >>> # Load from environment
    >>> env_config = OptimizerConfig.from_env()
    >>>
    >>> # Merge configurations
    >>> merged = config.merge(env_config)
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import logging
import os
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


class Domain(Enum):
    """Supported optimization domains."""
    LEGAL = "legal"
    MEDICAL = "medical"
    FINANCIAL = "financial"
    TECHNICAL = "technical"
    GENERAL = "general"


class OptimizationStrategy(Enum):
    """Optimization strategy selection."""
    ITERATIVE = "iterative"      # Multi-round optimization
    SINGLE_PASS = "single_pass"  # One-shot optimization
    EVOLUTIONARY = "evolutionary" # Population-based optimization
    REINFORCEMENT = "reinforcement" # RL-based optimization
    HYBRID = "hybrid"             # Mixed strategy


@dataclass
class OptimizerConfig:
    """Unified configuration for all optimizer types.
    
    This dataclass centralizes configuration across GraphRAG, LogicTheoremOptimizer,
    and AgenticOptimizer, enabling consistent configuration management and reducing
    parameter drift.
    
    Attributes:
        domain: The optimization domain (legal, medical, financial, technical, general)
        max_rounds: Maximum refinement rounds (1–100); default 5
        timeout_sec: Maximum execution time in seconds; 0 = unlimited
        logger: Python logger instance for structured logging; if None, uses module logger
        metrics_collector: Optional PerformanceMetricsCollector for tracking metrics
        feature_flags: Dict of feature toggles (enable_llm, enable_cache, etc.)
        optimization_strategy: Strategy for optimization (iterative, evolutionary, etc.)
        target_score: Target quality score [0.0, 1.0]; optimization stops when reached
        convergence_threshold: Score improvement threshold to consider convergence
        early_stopping_enabled: Stop if no improvement for N rounds
        early_stopping_rounds: Number of rounds without improvement before stopping
        validation_enabled: Run validation step after optimization
        llm_backend: Name of LLM backend ('openai', 'huggingface', 'local')
        llm_fallback_enabled: Use LLM as fallback when rule-based fails
        llm_fallback_threshold: Confidence threshold below which to use LLM fallback
        cache_enabled: Enable caching of intermediate results
        cache_ttl_sec: Cache time-to-live in seconds
        parallel_enabled: Enable parallel processing where possible
        max_workers: Maximum worker threads for parallelization
        seed: Random seed for reproducibility
        verbose: Enable verbose logging
    """
    
    # Core configuration
    domain: str = Domain.GENERAL.value
    max_rounds: int = 5
    timeout_sec: int = 0  # 0 = unlimited
    logger: Optional[Any] = None
    metrics_collector: Optional[Any] = None
    
    # Feature flags
    feature_flags: Dict[str, bool] = field(default_factory=lambda: {
        "enable_llm": False,
        "enable_cache": True,
        "enable_validation": True,
        "enable_metrics": True,
    })
    
    # Optimization strategy
    optimization_strategy: str = OptimizationStrategy.ITERATIVE.value
    target_score: float = 0.75
    convergence_threshold: float = 0.01
    
    # Early stopping
    early_stopping_enabled: bool = True
    early_stopping_rounds: int = 3
    
    # Validation
    validation_enabled: bool = True
    
    # LLM backend
    llm_backend: str = "openai"
    llm_fallback_enabled: bool = False
    llm_fallback_threshold: float = 0.5
    
    # Caching
    cache_enabled: bool = True
    cache_ttl_sec: int = 3600  # 1 hour
    
    # Parallelization
    parallel_enabled: bool = False
    max_workers: int = 4
    
    # Reproducibility
    seed: Optional[int] = None
    
    # Diagnostics
    verbose: bool = False
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        self.validate()
    
    def validate(self) -> None:
        """Validate all configuration constraints.
        
        Raises:
            ValueError: If any constraint is violated
        """
        errors = []
        
        # Domain validation
        valid_domains = {d.value for d in Domain}
        if self.domain not in valid_domains:
            errors.append(f"domain must be one of {valid_domains}, got '{self.domain}'")
        
        # max_rounds validation
        if not isinstance(self.max_rounds, int) or self.max_rounds < 1 or self.max_rounds > 100:
            errors.append(f"max_rounds must be int in [1, 100], got {self.max_rounds}")
        
        # timeout_sec validation
        if not isinstance(self.timeout_sec, int) or self.timeout_sec < 0:
            errors.append(f"timeout_sec must be int ≥ 0, got {self.timeout_sec}")
        
        # target_score validation
        if not (0.0 <= self.target_score <= 1.0):
            errors.append(f"target_score must be in [0.0, 1.0], got {self.target_score}")
        
        # convergence_threshold validation
        if not (0.0 <= self.convergence_threshold <= 1.0):
            errors.append(f"convergence_threshold must be in [0.0, 1.0], got {self.convergence_threshold}")
        
        # early_stopping_rounds validation
        if not isinstance(self.early_stopping_rounds, int) or self.early_stopping_rounds < 1:
            errors.append(f"early_stopping_rounds must be int ≥ 1, got {self.early_stopping_rounds}")
        
        # llm_fallback_threshold validation
        if not (0.0 <= self.llm_fallback_threshold <= 1.0):
            errors.append(f"llm_fallback_threshold must be in [0.0, 1.0], got {self.llm_fallback_threshold}")
        
        # cache_ttl_sec validation
        if not isinstance(self.cache_ttl_sec, int) or self.cache_ttl_sec < 0:
            errors.append(f"cache_ttl_sec must be int ≥ 0, got {self.cache_ttl_sec}")
        
        # max_workers validation
        if not isinstance(self.max_workers, int) or self.max_workers < 1:
            errors.append(f"max_workers must be int ≥ 1, got {self.max_workers}")
        
        # optimization_strategy validation
        valid_strategies = {s.value for s in OptimizationStrategy}
        if self.optimization_strategy not in valid_strategies:
            errors.append(f"optimization_strategy must be one of {valid_strategies}, got '{self.optimization_strategy}'")
        
        # Feature flags validation (all must be bool)
        for key, value in self.feature_flags.items():
            if not isinstance(value, bool):
                errors.append(f"feature_flags['{key}'] must be bool, got {type(value).__name__}")
        
        if errors:
            raise ValueError("OptimizerConfig validation failed:\n  " + "\n  ".join(errors))
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "OptimizerConfig":
        """Create OptimizerConfig from a dictionary.
        
        Args:
            config_dict: Dictionary with config fields
            
        Returns:
            OptimizerConfig instance
            
        Raises:
            ValueError: If validation fails
        """
        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in config_dict.items() if k in known_fields}
        
        # Handle feature_flags specially
        if 'feature_flags' in filtered and not isinstance(filtered['feature_flags'], dict):
            raise ValueError("feature_flags must be a dict")
        
        return cls(**filtered)
    
    @classmethod
    def from_env(cls) -> "OptimizerConfig":
        """Create OptimizerConfig from environment variables.
        
        Supported env vars (uppercase):
            OPTIMIZER_DOMAIN, OPTIMIZER_MAX_ROUNDS, OPTIMIZER_TIMEOUT_SEC,
            OPTIMIZER_LLM_BACKEND, OPTIMIZER_LLMFALLBACK_ENABLED,
            OPTIMIZER_CACHE_ENABLED, OPTIMIZER_VERBOSE, OPTIMIZER_SEED
            
        Returns:
            OptimizerConfig with values from environment
        """
        env_dict = {}
        
        # Domain
        if domain := os.environ.get("OPTIMIZER_DOMAIN"):
            env_dict["domain"] = domain
        
        # Numeric fields
        if max_rounds := os.environ.get("OPTIMIZER_MAX_ROUNDS"):
            try:
                env_dict["max_rounds"] = int(max_rounds)
            except ValueError:
                logger.warning(f"Invalid OPTIMIZER_MAX_ROUNDS: {max_rounds}")
        
        if timeout := os.environ.get("OPTIMIZER_TIMEOUT_SEC"):
            try:
                env_dict["timeout_sec"] = int(timeout)
            except ValueError:
                logger.warning(f"Invalid OPTIMIZER_TIMEOUT_SEC: {timeout}")
        
        if seed := os.environ.get("OPTIMIZER_SEED"):
            try:
                env_dict["seed"] = int(seed)
            except ValueError:
                logger.warning(f"Invalid OPTIMIZER_SEED: {seed}")
        
        # String fields
        if llm_backend := os.environ.get("OPTIMIZER_LLM_BACKEND"):
            env_dict["llm_backend"] = llm_backend
        
        # Boolean fields
        env_dict["llm_fallback_enabled"] = os.environ.get("OPTIMIZER_LLM_FALLBACK_ENABLED", "").lower() == "true"
        env_dict["cache_enabled"] = os.environ.get("OPTIMIZER_CACHE_ENABLED", "true").lower() == "true"
        env_dict["verbose"] = os.environ.get("OPTIMIZER_VERBOSE", "").lower() == "true"
        
        # Feature flags from env
        if feature_flags_json := os.environ.get("OPTIMIZER_FEATURE_FLAGS"):
            try:
                env_dict["feature_flags"] = json.loads(feature_flags_json)
            except json.JSONDecodeError:
                logger.warning(f"Invalid OPTIMIZER_FEATURE_FLAGS JSON: {feature_flags_json}")
        
        return cls.from_dict(env_dict)
    
    def merge(self, other: "OptimizerConfig") -> "OptimizerConfig":
        """Merge this config with another, with 'other' values taking precedence.
        
        Args:
            other: Another OptimizerConfig to merge in
            
        Returns:
            New merged OptimizerConfig
            
        Raises:
            ValueError: If validation fails on merged result
        """
        # Convert both to dicts
        self_dict = asdict(self)
        other_dict = asdict(other)
        
        # Handle feature_flags specially (merge dicts, not replace)
        self_flags = self_dict.pop("feature_flags", {})
        other_flags = other_dict.pop("feature_flags", {})
        merged_flags = {**self_flags, **other_flags}
        
        # Merge all other fields (other takes precedence)
        merged_dict = {**self_dict, **other_dict}
        merged_dict["feature_flags"] = merged_flags
        
        return OptimizerConfig.from_dict(merged_dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary.
        
        Returns:
            Dictionary representation of config
        """
        result = asdict(self)
        # Remove logger and metrics_collector (not serializable)
        result.pop("logger", None)
        result.pop("metrics_collector", None)
        return result
    
    def to_json(self) -> str:
        """Convert config to JSON string (logger/metrics_collector excluded).
        
        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    def copy(self, **overrides) -> "OptimizerConfig":
        """Create a copy with optional field overrides.
        
        Args:
            **overrides: Fields to override
            
        Returns:
            New OptimizerConfig with overrides applied
        """
        config_dict = asdict(self)
        config_dict.update(overrides)
        return OptimizerConfig.from_dict(config_dict)
    
    def __repr__(self) -> str:
        """Return string representation."""
        fields = [
            f"domain={self.domain!r}",
            f"max_rounds={self.max_rounds}",
            f"timeout_sec={self.timeout_sec}",
            f"strategy={self.optimization_strategy!r}",
            f"target_score={self.target_score}",
            f"llm_backend={self.llm_backend!r}",
        ]
        if self.verbose:
            fields.append("verbose=True")
        return f"OptimizerConfig({', '.join(fields)})"
