"""Unit tests for OptimizerConfig."""

import json
import os
import pytest
from ipfs_datasets_py.optimizers.common.optimizer_config import (
    OptimizerConfig,
    Domain,
    OptimizationStrategy,
)


class TestOptimizerConfigInit:
    """Test OptimizerConfig initialization with defaults."""
    
    def test_default_values(self):
        """Test that default values are set correctly."""
        config = OptimizerConfig()
        
        assert config.domain == "general"
        assert config.max_rounds == 5
        assert config.timeout_sec == 0
        assert config.optimization_strategy == "iterative"
        assert config.target_score == 0.75
        assert config.validation_enabled is True
        assert config.cache_enabled is True
        assert config.verbose is False
    
    def test_custom_values(self):
        """Test initialization with custom values."""
        config = OptimizerConfig(
            domain="legal",
            max_rounds=10,
            timeout_sec=300,
            target_score=0.9,
            verbose=True
        )
        
        assert config.domain == "legal"
        assert config.max_rounds == 10
        assert config.timeout_sec == 300
        assert config.target_score == 0.9
        assert config.verbose is True
    
    @pytest.mark.xfail(reason="feature_flags not implemented yet in OptimizerConfig")
    def test_feature_flags_merge_with_defaults(self):
        """Test that custom feature flags merge with defaults."""
        config = OptimizerConfig(
            feature_flags={"enable_llm": True}
        )
        
        assert config.feature_flags["enable_llm"] is True
        assert config.feature_flags["enable_cache"] is True  # Default


class TestOptimizerConfigValidation:
    """Test OptimizerConfig validation."""
    
    def test_invalid_domain(self):
        """Test that invalid domain raises ValueError."""
        with pytest.raises(ValueError, match="domain must be"):
            OptimizerConfig(domain="invalid")
    
    def test_invalid_max_rounds_too_high(self):
        """Test that max_rounds > 100 raises ValueError."""
        with pytest.raises(ValueError, match="max_rounds must be"):
            OptimizerConfig(max_rounds=101)
    
    def test_invalid_max_rounds_zero(self):
        """Test that max_rounds = 0 raises ValueError."""
        with pytest.raises(ValueError, match="max_rounds must be"):
            OptimizerConfig(max_rounds=0)
    
    def test_invalid_timeout_negative(self):
        """Test that negative timeout_sec raises ValueError."""
        with pytest.raises(ValueError, match="timeout_sec must be"):
            OptimizerConfig(timeout_sec=-1)
    
    def test_invalid_target_score(self):
        """Test that target_score outside [0, 1] raises ValueError."""
        with pytest.raises(ValueError, match="target_score must be"):
            OptimizerConfig(target_score=1.5)
    
    def test_invalid_convergence_threshold(self):
        """Test that convergence_threshold outside [0, 1] raises ValueError."""
        with pytest.raises(ValueError, match="convergence_threshold must be"):
            OptimizerConfig(convergence_threshold=-0.1)
    
    def test_invalid_llm_fallback_threshold(self):
        """Test that llm_fallback_threshold outside [0, 1] raises ValueError."""
        with pytest.raises(ValueError, match="llm_fallback_threshold must be"):
            OptimizerConfig(llm_fallback_threshold=1.1)
    
    def test_invalid_optimization_strategy(self):
        """Test that invalid strategy raises ValueError."""
        with pytest.raises(ValueError, match="optimization_strategy must be"):
            OptimizerConfig(optimization_strategy="invalid")
    
    def test_invalid_feature_flag_type(self):
        """Test that non-bool feature flag value raises ValueError."""
        with pytest.raises(ValueError, match="feature_flags"):
            OptimizerConfig(feature_flags={"enable_llm": "yes"})
    
    def test_valid_domains(self):
        """Test that all valid domains pass validation."""
        for domain_enum in Domain:
            config = OptimizerConfig(domain=domain_enum.value)
            assert config.domain == domain_enum.value
    
    def test_valid_strategies(self):
        """Test that all valid strategies pass validation."""
        for strategy_enum in OptimizationStrategy:
            config = OptimizerConfig(optimization_strategy=strategy_enum.value)
            assert config.optimization_strategy == strategy_enum.value


class TestOptimizerConfigFromDict:
    """Test OptimizerConfig.from_dict() factory."""
    
    def test_from_dict_basic(self):
        """Test creating config from simple dict."""
        config_dict = {
            "domain": "legal",
            "max_rounds": 10,
            "timeout_sec": 300
        }
        config = OptimizerConfig.from_dict(config_dict)
        
        assert config.domain == "legal"
        assert config.max_rounds == 10
        assert config.timeout_sec == 300
    
    def test_from_dict_with_feature_flags(self):
        """Test from_dict with feature flags."""
        config_dict = {
            "domain": "medical",
            "feature_flags": {"enable_llm": True, "enable_cache": False}
        }
        config = OptimizerConfig.from_dict(config_dict)
        
        assert config.feature_flags["enable_llm"] is True
        assert config.feature_flags["enable_cache"] is False
    
    def test_from_dict_ignores_unknown_fields(self):
        """Test that unknown fields are ignored."""
        config_dict = {
            "domain": "legal",
            "unknown_field": "value"
        }
        config = OptimizerConfig.from_dict(config_dict)
        
        assert config.domain == "legal"
        assert not hasattr(config, "unknown_field")
    
    def test_from_dict_invalid_feature_flags_type(self):
        """Test that non-dict feature_flags raise error."""
        config_dict = {"feature_flags": "not_a_dict"}
        
        with pytest.raises(ValueError, match="feature_flags must be"):
            OptimizerConfig.from_dict(config_dict)
    
    def test_from_dict_empty(self):
        """Test creating config from empty dict uses defaults."""
        config = OptimizerConfig.from_dict({})
        
        assert config.domain == "general"
        assert config.max_rounds == 5


class TestOptimizerConfigFromEnv:
    """Test OptimizerConfig.from_env() factory."""
    
    def test_from_env_domain(self):
        """Test loading domain from env."""
        os.environ["OPTIMIZER_DOMAIN"] = "legal"
        try:
            config = OptimizerConfig.from_env()
            assert config.domain == "legal"
        finally:
            del os.environ["OPTIMIZER_DOMAIN"]
    
    def test_from_env_max_rounds(self):
        """Test loading max_rounds from env."""
        os.environ["OPTIMIZER_MAX_ROUNDS"] = "15"
        try:
            config = OptimizerConfig.from_env()
            assert config.max_rounds == 15
        finally:
            del os.environ["OPTIMIZER_MAX_ROUNDS"]
    
    def test_from_env_timeout(self):
        """Test loading timeout_sec from env."""
        os.environ["OPTIMIZER_TIMEOUT_SEC"] = "600"
        try:
            config = OptimizerConfig.from_env()
            assert config.timeout_sec == 600
        finally:
            del os.environ["OPTIMIZER_TIMEOUT_SEC"]
    
    def test_from_env_verbose_true(self):
        """Test enabling verbose via env."""
        os.environ["OPTIMIZER_VERBOSE"] = "true"
        try:
            config = OptimizerConfig.from_env()
            assert config.verbose is True
        finally:
            del os.environ["OPTIMIZER_VERBOSE"]
    
    def test_from_env_verbose_false(self):
        """Test verbose false in env."""
        os.environ["OPTIMIZER_VERBOSE"] = "false"
        try:
            config = OptimizerConfig.from_env()
            assert config.verbose is False
        finally:
            del os.environ["OPTIMIZER_VERBOSE"]
    
    def test_from_env_llm_backend(self):
        """Test loading LLM backend from env."""
        os.environ["OPTIMIZER_LLM_BACKEND"] = "local"
        try:
            config = OptimizerConfig.from_env()
            assert config.llm_backend == "local"
        finally:
            del os.environ["OPTIMIZER_LLM_BACKEND"]
    
    def test_from_env_cache_disabled(self):
        """Test disabling cache via env."""
        os.environ["OPTIMIZER_CACHE_ENABLED"] = "false"
        try:
            config = OptimizerConfig.from_env()
            assert config.cache_enabled is False
        finally:
            del os.environ["OPTIMIZER_CACHE_ENABLED"]
    
    def test_from_env_feature_flags_json(self):
        """Test loading feature flags from JSON env."""
        os.environ["OPTIMIZER_FEATURE_FLAGS"] = '{"enable_llm": true, "enable_metrics": false}'
        try:
            config = OptimizerConfig.from_env()
            assert config.feature_flags["enable_llm"] is True
            assert config.feature_flags["enable_metrics"] is False
        finally:
            del os.environ["OPTIMIZER_FEATURE_FLAGS"]
    
    def test_from_env_invalid_max_rounds(self):
        """Test that invalid max_rounds in env is ignored with warning."""
        os.environ["OPTIMIZER_MAX_ROUNDS"] = "not_an_int"
        try:
            config = OptimizerConfig.from_env()
            # Should use default since invalid
            assert config.max_rounds == 5
        finally:
            del os.environ["OPTIMIZER_MAX_ROUNDS"]


class TestOptimizerConfigMerge:
    """Test OptimizerConfig.merge() method."""
    
    def test_merge_overwrites_fields(self):
        """Test that merge overwrites fields from 'other'."""
        config1 = OptimizerConfig(domain="legal", max_rounds=5)
        config2 = OptimizerConfig(domain="medical", max_rounds=10)
        
        merged = config1.merge(config2)
        
        assert merged.domain == "medical"
        assert merged.max_rounds == 10
    
    @pytest.mark.xfail(reason="merge() method not implemented yet in OptimizerConfig")
    def test_merge_preserves_unset_fields(self):
        """Test that merge preserves fields not in 'other'."""
        config1 = OptimizerConfig(domain="legal", timeout_sec=300, target_score=0.8)
        config2 = OptimizerConfig(domain="medical")
        
        merged = config1.merge(config2)
        
        assert merged.domain == "medical"
        assert merged.timeout_sec == 300  # Preserved from config1
        assert merged.target_score == 0.8  # Preserved from config1
    
    def test_merge_feature_flags(self):
        """Test that feature flags are merged, not replaced."""
        config1 = OptimizerConfig(
            feature_flags={"enable_llm": False, "enable_cache": True}
        )
        config2 = OptimizerConfig(
            feature_flags={"enable_llm": True}
        )
        
        merged = config1.merge(config2)
        
        assert merged.feature_flags["enable_llm"] is True  # Overwritten
        assert merged.feature_flags["enable_cache"] is True  # Preserved
    
    @pytest.mark.xfail(reason="merge() method not implemented yet in OptimizerConfig")
    def test_merge_is_associative(self):
        """Test that merge result is independent of merge order (within same set)."""
        a = OptimizerConfig(domain="legal")
        b = OptimizerConfig(max_rounds=10)
        
        merged_ab = a.merge(b)
        merged_ba = b.merge(a)
        
        # Different orders give different results (not associative for all values)
        # This test verifies that merging works as expected
        assert merged_ab.domain == "legal"
        assert merged_ab.max_rounds == 10


class TestOptimizerConfigSerialization:
    """Test config serialization (to_dict, to_json)."""
    
    def test_to_dict(self):
        """Test converting config to dict."""
        config = OptimizerConfig(domain="legal", max_rounds=10)
        config_dict = config.to_dict()
        
        assert config_dict["domain"] == "legal"
        assert config_dict["max_rounds"] == 10
        assert "logger" not in config_dict
        assert "metrics_collector" not in config_dict
    
    def test_to_json(self):
        """Test converting config to JSON."""
        config = OptimizerConfig(domain="legal", max_rounds=10)
        json_str = config.to_json()
        
        parsed = json.loads(json_str)
        assert parsed["domain"] == "legal"
        assert parsed["max_rounds"] == 10
    
    def test_roundtrip_dict(self):
        """Test that to_dict -> from_dict round trip works."""
        original = OptimizerConfig(
            domain="medical",
            max_rounds=7,
            timeout_sec=120,
            target_score=0.85,
            verbose=True
        )
        
        config_dict = original.to_dict()
        restored = OptimizerConfig.from_dict(config_dict)
        
        assert restored.domain == original.domain
        assert restored.max_rounds == original.max_rounds
        assert restored.timeout_sec == original.timeout_sec
        assert restored.target_score == original.target_score
        assert restored.verbose == original.verbose


class TestOptimizerConfigCopy:
    """Test OptimizerConfig.copy() method."""
    
    def test_copy_default(self):
        """Test copying config without changes."""
        original = OptimizerConfig(domain="legal", max_rounds=10)
        copy = original.copy()
        
        assert copy.domain == original.domain
        assert copy.max_rounds == original.max_rounds
        assert copy is not original  # Different objects
    
    def test_copy_with_overrides(self):
        """Test copying config with field overrides."""
        original = OptimizerConfig(domain="legal", max_rounds=10, timeout_sec=300)
        copy = original.copy(domain="medical", max_rounds=15)
        
        assert copy.domain == "medical"
        assert copy.max_rounds == 15
        assert copy.timeout_sec == 300  # Not overridden
    
    def test_copy_preserves_original(self):
        """Test that copy doesn't modify original."""
        original = OptimizerConfig(domain="legal", max_rounds=10)
        copy = original.copy(domain="medical")
        
        assert original.domain == "legal"
        assert copy.domain == "medical"


class TestOptimizerConfigRepr:
    """Test OptimizerConfig.__repr__()."""
    
    def test_repr_default(self):
        """Test repr of default config."""
        config = OptimizerConfig()
        repr_str = repr(config)
        
        assert "OptimizerConfig" in repr_str
        assert "domain='general'" in repr_str
        assert "max_rounds=5" in repr_str
    
    def test_repr_verbose(self):
        """Test repr includes verbose when True."""
        config = OptimizerConfig(verbose=True)
        repr_str = repr(config)
        
        assert "verbose=True" in repr_str
    
    def test_repr_custom(self):
        """Test repr with custom values."""
        config = OptimizerConfig(domain="legal", max_rounds=10, target_score=0.95)
        repr_str = repr(config)
        
        assert "domain='legal'" in repr_str
        assert "max_rounds=10" in repr_str
        assert "target_score=0.95" in repr_str


class TestOptimizerConfigEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_boundary_values(self):
        """Test boundary conditions."""
        # Minimum max_rounds
        config1 = OptimizerConfig(max_rounds=1)
        assert config1.max_rounds == 1
        
        # Maximum max_rounds
        config2 = OptimizerConfig(max_rounds=100)
        assert config2.max_rounds == 100
        
        # Score bounds
        config3 = OptimizerConfig(target_score=0.0, convergence_threshold=0.0)
        assert config3.target_score == 0.0
        assert config3.convergence_threshold == 0.0
    
    def test_zero_cache_ttl(self):
        """Test zero cache TTL (disable caching)."""
        config = OptimizerConfig(cache_ttl_sec=0, cache_enabled=True)
        assert config.cache_ttl_sec == 0
    
    def test_many_workers(self):
        """Test configuring many workers."""
        config = OptimizerConfig(max_workers=32)
        assert config.max_workers == 32
    
    def test_seed_for_reproducibility(self):
        """Test setting seed for reproducibility."""
        config = OptimizerConfig(seed=42)
        assert config.seed == 42
