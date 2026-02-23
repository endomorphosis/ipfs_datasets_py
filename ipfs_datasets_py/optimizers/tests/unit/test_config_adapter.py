"""Tests for OptimizerConfig adapter."""

import pytest
from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig as UnifiedConfig
from ipfs_datasets_py.optimizers.common.base_optimizer import (
    OptimizerConfig as OldConfig,
    OptimizationStrategy as OldStrategy,
)
from ipfs_datasets_py.optimizers.common.config_adapter import (
    convert_to_unified_config,
    create_unified_config,
)


class TestConfigAdapter:
    """Test OptimizerConfig adapter for backward compatibility."""
    
    def test_convert_unified_config_passthrough(self):
        """Test that unified config is passed through unchanged."""
        original = UnifiedConfig(domain="legal", max_rounds=7)
        converted = convert_to_unified_config(original)
        
        assert converted is original  # Same object
        assert converted.domain == "legal"
        assert converted.max_rounds == 7
    
    def test_convert_old_config_sgd_strategy(self):
        """Test converting old config with SGD strategy."""
        old = OldConfig(
            strategy=OldStrategy.SGD,
            max_iterations=10,
            target_score=0.9,
        )
        
        unified = convert_to_unified_config(old)
        
        assert isinstance(unified, UnifiedConfig)
        assert unified.max_rounds == 10
        assert unified.target_score == 0.9
        assert unified.optimization_strategy == "iterative"  # SGD -> iterative
    
    def test_convert_old_config_evolutionary_strategy(self):
        """Test converting old config with evolutionary strategy."""
        old = OldConfig(strategy=OldStrategy.EVOLUTIONARY)
        
        unified = convert_to_unified_config(old)
        
        assert unified.optimization_strategy == "evolutionary"
    
    def test_convert_old_config_hybrid_strategy(self):
        """Test converting old config with hybrid strategy."""
        old = OldConfig(strategy=OldStrategy.HYBRID)
        
        unified = convert_to_unified_config(old)
        
        assert unified.optimization_strategy == "hybrid"
    
    def test_convert_old_config_with_validation(self):
        """Test that validation_enabled is preserved."""
        old = OldConfig(validation_enabled=False)
        
        unified = convert_to_unified_config(old)
        
        assert unified.validation_enabled is False
    
    def test_convert_old_config_default_domain(self):
        """Test that old config maps to general domain."""
        old = OldConfig()
        
        unified = convert_to_unified_config(old)
        
        assert unified.domain == "general"
    
    def test_convert_invalid_type(self):
        """Test that invalid config type raises TypeError."""
        with pytest.raises(TypeError, match="Unsupported config type"):
            convert_to_unified_config("not a config")
    
    def test_create_unified_config_simple(self):
        """Test creating unified config with kwargs."""
        config = create_unified_config(
            domain="medical",
            max_rounds=5,
            verbose=True
        )
        
        assert config.domain == "medical"
        assert config.max_rounds == 5
        assert config.verbose is True
    
    def test_create_unified_config_with_defaults(self):
        """Test that create uses defaults when not specified."""
        config = create_unified_config()
        
        assert config.domain == "general"
        assert config.max_rounds == 5
        assert config.optimization_strategy == "iterative"
