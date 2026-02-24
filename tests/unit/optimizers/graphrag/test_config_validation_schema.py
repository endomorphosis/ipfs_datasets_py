"""Unit tests for GraphRAG config validation schema exceptions."""

from ipfs_datasets_py.optimizers.common.exceptions import ConfigurationError
from ipfs_datasets_py.optimizers.graphrag.config_validation_schema import (
    ConfigValidationError,
    ConfigValidator,
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
