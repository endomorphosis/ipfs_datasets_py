"""Batch 265: Unified OptimizerConfig Support in AgenticOptimizer

Tests the integration of OptimizerConfig dataclass with AgenticOptimizer,
ensuring both new typed configs and legacy dict configs work correctly.
"""

import pytest
from unittest.mock import MagicMock

from ipfs_datasets_py.optimizers.agentic.base import (
    AgenticOptimizer,
    ChangeControlMethod,
    OptimizationMethod,
    OptimizationTask,
    OptimizationResult,
)
from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig


# Concrete test optimizer for testing abstract base
class TestOptimizer(AgenticOptimizer):
    """Minimal concrete optimizer for testing."""
    
    def _get_method(self) -> OptimizationMethod:
        return OptimizationMethod.TEST_DRIVEN
    
    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        return OptimizationResult(
            task_id=task.task_id,
            success=True,
            method=self.method,
            changes="Test changes",
        )


class TestUnifiedOptimizerConfig:
    """Test OptimizerConfig dataclass integration."""
    
    def test_optimizer_config_dataclass_instantiation(self):
        """Test creating optimizer with OptimizerConfig dataclass."""
        config = OptimizerConfig(
            domain="legal",
            max_rounds=10,
            verbose=True,
            target_score=0.85,
        )
        
        optimizer = TestOptimizer(
            agent_id="test-1",
            llm_router=MagicMock(),
            config=config,
        )
        
        assert optimizer.config == config
        assert isinstance(optimizer.config, OptimizerConfig)
        assert optimizer.domain == "legal"
        assert optimizer.max_rounds == 10
        assert optimizer.verbose is True
    
    def test_optimizer_config_dict_backward_compat(self):
        """Test creating optimizer with legacy dict config."""
        config_dict = {
            "domain": "medical",
            "max_rounds": 7,
            "verbose": False,
            "target_score": 0.75,
        }
        
        optimizer = TestOptimizer(
            agent_id="test-2",
            llm_router=MagicMock(),
            config=config_dict,
        )
        
        # Dict should be converted to OptimizerConfig
        assert isinstance(optimizer.config, OptimizerConfig)
        assert optimizer.domain == "medical"
        assert optimizer.max_rounds == 7
        assert optimizer.verbose is False
    
    def test_optimizer_config_none_uses_defaults(self):
        """Test creating optimizer with None config uses defaults."""
        optimizer = TestOptimizer(
            agent_id="test-3",
            llm_router=MagicMock(),
            config=None,
        )
        
        assert isinstance(optimizer.config, OptimizerConfig)
        assert optimizer.domain == "general"  # Default domain
        assert optimizer.max_rounds == 5  # Default max_rounds
        assert optimizer.verbose is False  # Default verbose
    
    def test_optimizer_config_invalid_type_raises(self):
        """Test passing invalid config type raises TypeError."""
        with pytest.raises(TypeError, match="config must be OptimizerConfig or dict"):
            TestOptimizer(
                agent_id="test-4",
                llm_router=MagicMock(),
                config="invalid",  # type: ignore
            )
    
    def test_get_config_value_with_dataclass(self):
        """Test get_config_value() with OptimizerConfig dataclass."""
        config = OptimizerConfig(
            domain="financial",
            max_rounds=15,
            timeout_sec=600,
        )
        
        optimizer = TestOptimizer(
            agent_id="test-5",
            llm_router=MagicMock(),
            config=config,
        )
        
        assert optimizer.get_config_value("domain") == "financial"
        assert optimizer.get_config_value("max_rounds") == 15
        assert optimizer.get_config_value("timeout_sec") == 600
        assert optimizer.get_config_value("nonexistent", "default") == "default"
    
    def test_get_config_value_with_dict(self):
        """Test get_config_value() with legacy dict config."""
        config_dict = {
            "domain": "technical",
            "max_rounds": 3,
            "custom_field": "custom_value",
        }
        
        optimizer = TestOptimizer(
            agent_id="test-6",
            llm_router=MagicMock(),
            config=config_dict,
        )
        
        assert optimizer.get_config_value("domain") == "technical"
        assert optimizer.get_config_value("max_rounds") == 3
        # Custom fields in dict are preserved during conversion (ignored by dataclass)
        assert optimizer.get_config_value("nonexistent", "fallback") == "fallback"
    
    def test_domain_property_with_dataclass(self):
        """Test domain property with OptimizerConfig."""
        config = OptimizerConfig(domain="legal")
        optimizer = TestOptimizer(
            agent_id="test-7",
            llm_router=MagicMock(),
            config=config,
        )
        
        assert optimizer.domain == "legal"
    
    def test_domain_property_with_dict(self):
        """Test domain property with legacy dict."""
        optimizer = TestOptimizer(
            agent_id="test-8",
            llm_router=MagicMock(),
            config={"domain": "medical"},
        )
        
        # Dict normalized to OptimizerConfig, so domain property works
        assert optimizer.domain == "medical"
    
    def test_max_rounds_property_with_dataclass(self):
        """Test max_rounds property with OptimizerConfig."""
        config = OptimizerConfig(max_rounds=20)
        optimizer = TestOptimizer(
            agent_id="test-9",
            llm_router=MagicMock(),
            config=config,
        )
        
        assert optimizer.max_rounds == 20
    
    def test_verbose_property_with_dataclass(self):
        """Test verbose property with OptimizerConfig."""
        config = OptimizerConfig(verbose=True)
        optimizer = TestOptimizer(
            agent_id="test-10",
            llm_router=MagicMock(),
            config=config,
        )
        
        assert optimizer.verbose is True


class TestOptimizerConfigFeatures:
    """Test OptimizerConfig advanced features."""
    
    def test_config_from_dict_factory(self):
        """Test OptimizerConfig.from_dict() factory method."""
        config_dict = {
            "domain": "legal",
            "max_rounds": 8,
            "verbose": True,
            "llm_backend": "huggingface",
            "cache_enabled": False,
        }
        
        config = OptimizerConfig.from_dict(config_dict)
        
        assert config.domain == "legal"
        assert config.max_rounds == 8
        assert config.verbose is True
        assert config.llm_backend == "huggingface"
        assert config.cache_enabled is False
    
    def test_config_merge(self):
        """Test merging two OptimizerConfigs."""
        base_config = OptimizerConfig(
            domain="legal",
            max_rounds=5,
            verbose=False,
        )
        
        override_config = OptimizerConfig(
            domain="medical",  # Explicitly set domain to test override
            max_rounds=10,
            verbose=True,
        )
        
        merged = base_config.merge(override_config)
        
        assert merged.domain == "medical"  # Overridden
        assert merged.max_rounds == 10  # Overridden
        assert merged.verbose is True  # Overridden
    
    def test_config_to_dict(self):
        """Test OptimizerConfig.to_dict() serialization."""
        config = OptimizerConfig(
            domain="medical",
            max_rounds=7,
            timeout_sec=300,
        )
        
        config_dict = config.to_dict()
        
        assert isinstance(config_dict, dict)
        assert config_dict["domain"] == "medical"
        assert config_dict["max_rounds"] == 7
        assert config_dict["timeout_sec"] == 300
    
    def test_config_copy_with_overrides(self):
        """Test OptimizerConfig.copy() with field overrides."""
        original = OptimizerConfig(
            domain="legal",
            max_rounds=5,
            verbose=False,
        )
        
        modified = original.copy(max_rounds=15, verbose=True)
        
        assert modified.domain == "legal"  # Preserved
        assert modified.max_rounds == 15  # Overridden
        assert modified.verbose is True  # Overridden
        assert original.max_rounds == 5  # Original unchanged
    
    def test_config_validation_max_rounds(self):
        """Test OptimizerConfig validation for max_rounds."""
        with pytest.raises(ValueError, match="max_rounds must be int in \\[1, 100\\]"):
            OptimizerConfig(max_rounds=0)
        
        with pytest.raises(ValueError, match="max_rounds must be int in \\[1, 100\\]"):
            OptimizerConfig(max_rounds=101)
    
    def test_config_validation_target_score(self):
        """Test OptimizerConfig validation for target_score."""
        with pytest.raises(ValueError, match="target_score must be in \\[0.0, 1.0\\]"):
            OptimizerConfig(target_score=1.5)
        
        with pytest.raises(ValueError, match="target_score must be in \\[0.0, 1.0\\]"):
            OptimizerConfig(target_score=-0.1)
    
    def test_config_validation_domain(self):
        """Test OptimizerConfig validation for domain."""
        # Valid domains should work
        for domain in ["legal", "medical", "financial", "technical", "general"]:
            config = OptimizerConfig(domain=domain)
            assert config.domain == domain
        
        # Invalid domain should raise
        with pytest.raises(ValueError, match="domain must be one of"):
            OptimizerConfig(domain="invalid_domain")


class TestAgenticOptimizerIntegration:
    """Test integration with concrete agentic optimizers."""
    
    def test_optimizer_with_typed_config_runs_optimize(self):
        """Test optimizer with typed config can run optimize()."""
        config = OptimizerConfig(
            domain="legal",
            max_rounds=5,
        )
        
        optimizer = TestOptimizer(
            agent_id="integration-1",
            llm_router=MagicMock(),
            config=config,
        )
        
        task = OptimizationTask(
            task_id="task-1",
            description="Test task",
        )
        
        result = optimizer.optimize(task)
        
        assert result.success is True
        assert result.method == OptimizationMethod.TEST_DRIVEN
    
    def test_optimizer_with_dict_config_runs_optimize(self):
        """Test optimizer with dict config can run optimize()."""
        optimizer = TestOptimizer(
            agent_id="integration-2",
            llm_router=MagicMock(),
            config={"domain": "medical", "max_rounds": 3},
        )
        
        task = OptimizationTask(
            task_id="task-2",
            description="Test task",
        )
        
        result = optimizer.optimize(task)
        
        assert result.success is True
        assert optimizer.config.domain == "medical"
    
    def test_optimizer_logger_from_config(self):
        """Test optimizer uses logger from OptimizerConfig."""
        import logging
        
        custom_logger = logging.getLogger("custom_test_logger")
        config = OptimizerConfig(logger=custom_logger)
        
        optimizer = TestOptimizer(
            agent_id="logger-test",
            llm_router=MagicMock(),
            config=config,
        )
        
        assert optimizer._log == custom_logger
    
    def test_optimizer_logger_override_with_explicit_logger(self):
        """Test explicit logger parameter overrides config logger."""
        import logging
        
        config_logger = logging.getLogger("config_logger")
        explicit_logger = logging.getLogger("explicit_logger")
        
        config = OptimizerConfig(logger=config_logger)
        
        optimizer = TestOptimizer(
            agent_id="logger-override",
            llm_router=MagicMock(),
            config=config,
            logger=explicit_logger,
        )
        
        assert optimizer._log == explicit_logger


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""
    
    def test_existing_dict_config_pattern_still_works(self):
        """Test existing dict-based config pattern still works."""
        # This is how existing code creates optimizers
        optimizer = TestOptimizer(
            agent_id="compat-1",
            llm_router=MagicMock(),
            change_control=ChangeControlMethod.PATCH,
            config={
                "domain": "legal",
                "max_rounds": 5,
                "verbose": True,
            },
        )
        
        # Should work seamlessly
        assert optimizer.domain == "legal"
        assert optimizer.max_rounds == 5
        assert optimizer.verbose is True
    
    def test_empty_dict_config_uses_defaults(self):
        """Test empty dict config uses default values."""
        optimizer = TestOptimizer(
            agent_id="compat-2",
            llm_router=MagicMock(),
            config={},
        )
        
        # Should use OptimizerConfig defaults
        assert optimizer.domain == "general"
        assert optimizer.max_rounds == 5
        assert optimizer.verbose is False
    
    def test_partial_dict_config_merges_with_defaults(self):
        """Test partial dict config merges with defaults."""
        optimizer = TestOptimizer(
            agent_id="compat-3",
            llm_router=MagicMock(),
            config={"domain": "medical"},  # Only specify domain
        )
        
        # Domain overridden, others use defaults
        assert optimizer.domain == "medical"
        assert optimizer.max_rounds == 5  # Default
        assert optimizer.verbose is False  # Default

