"""OptimizerConfig adapter for backward compatibility.

This module provides utilities to work with both the old simple OptimizerConfig
and the new unified OptimizerConfig. It enables gradual migration without
breaking existing code.
"""

from typing import Any
from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig as UnifiedConfig


def convert_to_unified_config(
    config: Any,
) -> UnifiedConfig:
    """Convert old or new config format to unified OptimizerConfig.
    
    Args:
        config: Either old OptimizerConfig (from base_optimizer) or UnifiedConfig
        
    Returns:
        UnifiedConfig instance
        
    Raises:
        TypeError: If config type is not recognized
    """
    # If already unified config, return as-is
    if isinstance(config, UnifiedConfig):
        return config
    
    # If it's old OptimizerConfig (has 'strategy' attribute)
    if hasattr(config, 'strategy') and not hasattr(config, 'domain'):
        return UnifiedConfig(
            domain="general",
            # Map old strategy to new one
            optimization_strategy=_map_old_strategy_to_new(config.strategy),
            max_rounds=getattr(config, 'max_iterations', 5),
            target_score=getattr(config, 'target_score', 0.75),
            convergence_threshold=getattr(config, 'convergence_threshold', 0.01),
            validation_enabled=getattr(config, 'validation_enabled', True),
            cache_enabled=getattr(config, 'metrics_enabled', True),  # Map metrics_enabled -> cache_enabled
        )
    
    raise TypeError(f"Unsupported config type: {type(config)}")


def _map_old_strategy_to_new(old_strategy: Any) -> str:
    """Map old optimization strategy enum to new one.
    
    Args:
        old_strategy: Old OptimizationStrategy enum value
        
    Returns:
        String name of new strategy
    """
    # Old strategies: SGD, EVOLUTIONARY, REINFORCEMENT, HYBRID
    # New strategies: ITERATIVE, SINGLE_PASS, EVOLUTIONARY, REINFORCEMENT, HYBRID
    strategy_name = str(old_strategy).lower()
    
    if 'sgd' in strategy_name:
        return 'iterative'  # SGD maps to iterative
    elif 'hybrid' in strategy_name:
        return 'hybrid'
    elif 'evolutionary' in strategy_name:
        return 'evolutionary'
    elif 'reinforcement' in strategy_name:
        return 'reinforcement'
    else:
        return 'iterative'  # Default fallback


def create_unified_config(**kwargs: Any) -> UnifiedConfig:
    """Create unified config from keyword arguments.
    
    Convenience method to create UnifiedConfig with less boilerplate.
    
    Args:
        **kwargs: Config field values
        
    Returns:
        UnifiedConfig instance
    """
    return UnifiedConfig(**kwargs)
