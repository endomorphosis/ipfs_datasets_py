"""Unit tests for GraphRAG config validation schema exceptions."""

from ipfs_datasets_py.optimizers.common.exceptions import ConfigurationError
from ipfs_datasets_py.optimizers.graphrag.config_validation_schema import (
    ConfigValidationError,
    ConfigValidator,
    ValidationRuleSet,
    _compile_pattern,
)


def test_config_validation_error_inherits_configuration_error() -> None:
    """ConfigValidationError should be part of shared optimizer exception tree."""
    err = ConfigValidationError("confidence", ["must be <= 1.0"])
    assert isinstance(err, ConfigurationError)
    assert err.field_name == "confidence"
    assert err.errors == ["must be <= 1.0"]


def test_config_validation_error_populates_details() -> None:
    """Details payload should include field and errors for structured handling."""
    err = ConfigValidationError("max_entities", ["must be >= 1"])
    assert err.details == {"field_name": "max_entities", "errors": ["must be >= 1"]}


def test_validate_strict_raises_unified_config_error() -> None:
    """Strict validation should raise ConfigValidationError for invalid config."""
    validator = ConfigValidator()
    invalid = {"confidence": 0.9, "max_confidence": 0.8}

    try:
        validator.validate_strict(invalid)
        raise AssertionError("Expected ConfigValidationError")
    except ConfigValidationError as err:
        assert err.field_name == "confidence"
        assert isinstance(err, ConfigurationError)


def test_compile_pattern_is_cached_for_identical_input() -> None:
    """Pattern compiler should return shared compiled object for same pattern."""
    _compile_pattern.cache_clear()
    first = _compile_pattern(r"^[a-z]+$")
    second = _compile_pattern(r"^[a-z]+$")
    assert first is second


def test_validation_rule_set_uses_compiled_pattern_cache() -> None:
    """Pattern rules should work with cached compilation and still validate."""
    _compile_pattern.cache_clear()
    rules = ValidationRuleSet("name", str).add_pattern(r"^[A-Z][a-z]+$")

    valid, errors = rules.validate("Alice")
    assert valid is True
    assert errors == []

    valid, errors = rules.validate("alice")
    assert valid is False
    assert errors
