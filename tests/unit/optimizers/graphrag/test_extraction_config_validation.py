"""Parametrized tests for ExtractionConfig field validation.

This module provides comprehensive test coverage for the ExtractionConfig dataclass,
ensuring all field constraints are properly enforced and error messages are clear.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig


class TestExtractionConfigValidation:
    """Tests for ExtractionConfig validation."""

    # confidence_threshold tests
    @pytest.mark.parametrize("threshold", [0.0, 0.5, 1.0])
    def test_confidence_threshold_valid_range(self, threshold):
        """Test that valid confidence_threshold values pass validation."""
        config = ExtractionConfig(confidence_threshold=threshold)
        config.validate()  # Should not raise

    @pytest.mark.parametrize("threshold", [-0.1, 1.1, -1.0, 2.0])
    def test_confidence_threshold_invalid_range(self, threshold):
        """Test that invalid confidence_threshold values raise ValueError."""
        config = ExtractionConfig(confidence_threshold=threshold)
        with pytest.raises(ValueError, match="confidence_threshold must be in"):
            config.validate()

    # max_confidence tests
    @pytest.mark.parametrize("max_conf", [0.1, 0.5, 1.0])
    def test_max_confidence_valid_range(self, max_conf):
        """Test that valid max_confidence values pass validation."""
        # Set confidence_threshold to be less than max_confidence to satisfy constraint
        threshold = min(0.05, max_conf - 0.01) if max_conf > 0.01 else 0.01
        config = ExtractionConfig(confidence_threshold=threshold, max_confidence=max_conf)
        config.validate()  # Should not raise

    @pytest.mark.parametrize("max_conf", [0.0, -0.1, 1.1])
    def test_max_confidence_invalid_range(self, max_conf):
        """Test that invalid max_confidence values raise ValueError."""
        config = ExtractionConfig(max_confidence=max_conf)
        with pytest.raises(ValueError, match="max_confidence must be in"):
            config.validate()

    # confidence_threshold vs max_confidence ordering
    def test_confidence_threshold_greater_than_max_confidence_fails(self):
        """Test that confidence_threshold > max_confidence fails."""
        config = ExtractionConfig(
            confidence_threshold=0.8,
            max_confidence=0.6
        )
        with pytest.raises(ValueError, match="confidence_threshold.*must be.*<= max_confidence"):
            config.validate()

    def test_confidence_threshold_equals_max_confidence_passes(self):
        """Test that confidence_threshold == max_confidence passes."""
        config = ExtractionConfig(
            confidence_threshold=0.8,
            max_confidence=0.8
        )
        config.validate()  # Should not raise

    # max_entities and max_relationships
    @pytest.mark.parametrize("max_ent", [0, 1, 100, 1000, 10000])
    def test_max_entities_valid_values(self, max_ent):
        """Test that non-negative max_entities pass validation."""
        config = ExtractionConfig(max_entities=max_ent)
        config.validate()  # Should not raise

    @pytest.mark.parametrize("max_ent", [-1, -100])
    def test_max_entities_invalid_negative_values(self, max_ent):
        """Test that negative max_entities fail validation."""
        config = ExtractionConfig(max_entities=max_ent)
        with pytest.raises(ValueError, match="max_entities must be >= 0"):
            config.validate()

    @pytest.mark.parametrize("max_rel", [0, 1, 100, 1000])
    def test_max_relationships_valid_values(self, max_rel):
        """Test that non-negative max_relationships pass validation."""
        config = ExtractionConfig(max_relationships=max_rel)
        config.validate()  # Should not raise

    @pytest.mark.parametrize("max_rel", [-1, -50])
    def test_max_relationships_invalid_negative_values(self, max_rel):
        """Test that negative max_relationships fail validation."""
        config = ExtractionConfig(max_relationships=max_rel)
        with pytest.raises(ValueError, match="max_relationships must be >= 0"):
            config.validate()

    # window_size tests
    @pytest.mark.parametrize("win_size", [1, 5, 10, 50, 100])
    def test_window_size_valid_values(self, win_size):
        """Test that positive window_size values pass validation."""
        config = ExtractionConfig(window_size=win_size)
        config.validate()  # Should not raise

    @pytest.mark.parametrize("win_size", [0, -1, -5])
    def test_window_size_invalid_non_positive_values(self, win_size):
        """Test that non-positive window_size values fail validation."""
        config = ExtractionConfig(window_size=win_size)
        with pytest.raises(ValueError, match="window_size must be >= 1"):
            config.validate()

    # min_entity_length tests
    @pytest.mark.parametrize("min_len", [1, 2, 5, 10])
    def test_min_entity_length_valid_values(self, min_len):
        """Test that positive min_entity_length values pass validation."""
        config = ExtractionConfig(min_entity_length=min_len)
        config.validate()  # Should not raise

    @pytest.mark.parametrize("min_len", [0, -1, -10])
    def test_min_entity_length_invalid_non_positive_values(self, min_len):
        """Test that non-positive min_entity_length values fail validation."""
        config = ExtractionConfig(min_entity_length=min_len)
        with pytest.raises(ValueError, match="min_entity_length must be >= 1"):
            config.validate()

    # llm_fallback_threshold tests
    @pytest.mark.parametrize("llm_thresh", [0.0, 0.5, 1.0])
    def test_llm_fallback_threshold_valid_range(self, llm_thresh):
        """Test that valid llm_fallback_threshold values pass validation."""
        config = ExtractionConfig(llm_fallback_threshold=llm_thresh)
        config.validate()  # Should not raise

    @pytest.mark.parametrize("llm_thresh", [-0.1, 1.1, -1.0])
    def test_llm_fallback_threshold_invalid_range(self, llm_thresh):
        """Test that invalid llm_fallback_threshold values fail validation."""
        config = ExtractionConfig(llm_fallback_threshold=llm_thresh)
        with pytest.raises(ValueError, match="llm_fallback_threshold must be in"):
            config.validate()


class TestExtractionConfigDefaults:
    """Tests for ExtractionConfig default values."""

    def test_default_values_are_valid(self):
        """Test that default ExtractionConfig values pass validation."""
        config = ExtractionConfig()
        config.validate()  # Should not raise

    def test_default_confidence_threshold_is_half(self):
        """Test that default confidence_threshold is 0.5."""
        config = ExtractionConfig()
        assert config.confidence_threshold == 0.5

    def test_default_max_entities_is_unlimited(self):
        """Test that default max_entities is 0 (unlimited)."""
        config = ExtractionConfig()
        assert config.max_entities == 0

    def test_default_window_size_is_five(self):
        """Test that default window_size is 5."""
        config = ExtractionConfig()
        assert config.window_size == 5

    def test_default_include_properties_is_true(self):
        """Test that default include_properties is True."""
        config = ExtractionConfig()
        assert config.include_properties is True

    def test_default_llm_fallback_threshold_is_zero(self):
        """Test that default llm_fallback_threshold is 0.0 (disabled)."""
        config = ExtractionConfig()
        assert config.llm_fallback_threshold == 0.0

    def test_default_min_entity_length_is_two(self):
        """Test that default min_entity_length is 2."""
        config = ExtractionConfig()
        assert config.min_entity_length == 2


class TestExtractionConfigSerialization:
    """Tests for ExtractionConfig serialization/deserialization."""

    def test_to_dict_includes_all_fields(self):
        """Test that to_dict includes all config fields."""
        config = ExtractionConfig(
            confidence_threshold=0.7,
            max_entities=100,
            window_size=10,
            llm_fallback_threshold=0.6
        )
        d = config.to_dict()

        assert d["confidence_threshold"] == 0.7
        assert d["max_entities"] == 100
        assert d["window_size"] == 10
        assert d["llm_fallback_threshold"] == 0.6

    def test_from_dict_reconstructs_config(self):
        """Test that from_dict reconstructs config from dict."""
        original = ExtractionConfig(
            confidence_threshold=0.7,
            max_entities=100,
            window_size=10
        )
        d = original.to_dict()
        reconstructed = ExtractionConfig.from_dict(d)

        assert reconstructed.confidence_threshold == original.confidence_threshold
        assert reconstructed.max_entities == original.max_entities
        assert reconstructed.window_size == original.window_size

    def test_from_dict_with_missing_fields_uses_defaults(self):
        """Test that from_dict uses defaults for missing fields."""
        d = {"confidence_threshold": 0.8}
        config = ExtractionConfig.from_dict(d)

        assert config.confidence_threshold == 0.8
        assert config.max_entities == 0  # Default
        assert config.window_size == 5  # Default

    def test_roundtrip_preserves_validation(self):
        """Test that roundtrip through to_dict/from_dict preserves validity."""
        original = ExtractionConfig(
            confidence_threshold=0.6,
            max_confidence=0.9,
            max_entities=50,
            window_size=8
        )
        original.validate()

        d = original.to_dict()
        reconstructed = ExtractionConfig.from_dict(d)
        reconstructed.validate()  # Should not raise


class TestExtractionConfigMerge:
    """Tests for ExtractionConfig merge functionality."""

    def test_merge_overrides_non_default_values(self):
        """Test that merge uses 'other' values when they differ from defaults."""
        base = ExtractionConfig(confidence_threshold=0.5)
        override = ExtractionConfig(confidence_threshold=0.8, max_entities=100)

        merged = base.merge(override)

        assert merged.confidence_threshold == 0.8  # From override
        assert merged.max_entities == 100  # From override

    def test_merge_keeps_base_default_values_when_override_is_default(self):
        """Test that merge preserves base values when override is default."""
        base = ExtractionConfig(confidence_threshold=0.7, max_entities=100)
        override = ExtractionConfig()  # All defaults

        merged = base.merge(override)

        assert merged.confidence_threshold == 0.7  # Kept from base
        assert merged.max_entities == 100  # Kept from base

    def test_merged_config_is_valid(self):
        """Test that merged config passes validation."""
        base = ExtractionConfig(confidence_threshold=0.6)
        override = ExtractionConfig(max_confidence=0.8)

        merged = base.merge(override)
        merged.validate()  # Should not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
