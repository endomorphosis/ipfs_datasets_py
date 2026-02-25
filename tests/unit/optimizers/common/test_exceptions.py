"""Tests for the typed exception hierarchy in common/exceptions.py."""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.exceptions import (
    AuthenticationError,
    CircuitBreakerOpenError,
    ConfigurationError,
    ExternalServiceError,
    ExtractionError,
    OptimizerError,
    OptimizerTimeoutError,
    ProvingError,
    RateLimitError,
    RefinementError,
    RetryableBackendError,
    ValidationError,
    exception_to_dict,
    safe_error_handler,
    wrap_exceptions,
)


class TestOptimizerError:
    def test_message_stored(self):
        e = OptimizerError("boom")
        assert e.message == "boom"
        assert str(e) == "boom"

    def test_details_in_str(self):
        e = OptimizerError("boom", details={"key": "val"})
        assert "details=" in str(e)
        assert "key" in str(e)

    def test_details_none_no_pipe(self):
        assert "|" not in str(OptimizerError("boom"))

    def test_is_exception(self):
        with pytest.raises(OptimizerError):
            raise OptimizerError("test")


class TestExtractionError:
    def test_is_optimizer_error(self):
        with pytest.raises(OptimizerError):
            raise ExtractionError("extract failed")

    def test_message(self):
        e = ExtractionError("NER failed", details={"input": "raw"})
        assert "NER failed" in str(e)


class TestValidationError:
    def test_errors_list_stored(self):
        e = ValidationError("bad schema", errors=["field_missing", "type_mismatch"])
        assert e.errors == ["field_missing", "type_mismatch"]
        assert "field_missing" in str(e)

    def test_no_errors_defaults_to_empty_list(self):
        e = ValidationError("bad")
        assert e.errors == []

    def test_is_optimizer_error(self):
        with pytest.raises(OptimizerError):
            raise ValidationError("fail")


class TestProvingError:
    def test_prover_in_str(self):
        e = ProvingError("UNSAT", prover="z3", formula="∀x P(x)")
        s = str(e)
        assert "z3" in s
        assert "∀x P(x)" in s

    def test_is_validation_error(self):
        with pytest.raises(ValidationError):
            raise ProvingError("unsat")

    def test_is_optimizer_error(self):
        with pytest.raises(OptimizerError):
            raise ProvingError("unsat")

    def test_prover_none_no_pipe(self):
        e = ProvingError("fail")
        assert e.prover is None
        assert e.formula is None

    def test_with_errors_list(self):
        e = ProvingError("bad", errors=["clause 1"], prover="cvc5")
        assert "clause 1" in str(e)
        assert "cvc5" in str(e)


class TestRefinementError:
    def test_is_optimizer_error(self):
        with pytest.raises(OptimizerError):
            raise RefinementError("diverged")


class TestConfigurationError:
    def test_is_optimizer_error(self):
        with pytest.raises(OptimizerError):
            raise ConfigurationError("bad strategy")

    def test_details(self):
        e = ConfigurationError("bad", details={"field": "strategy"})
        assert "strategy" in str(e)


class TestExternalServiceErrors:
    def test_external_service_error_inherits_optimizer_error(self):
        assert issubclass(ExternalServiceError, OptimizerError)

    def test_timeout_error_inherits_external_service_error(self):
        assert issubclass(OptimizerTimeoutError, ExternalServiceError)

    def test_retryable_error_inherits_external_service_error(self):
        assert issubclass(RetryableBackendError, ExternalServiceError)

    def test_circuit_breaker_error_inherits_external_service_error(self):
        assert issubclass(CircuitBreakerOpenError, ExternalServiceError)

    def test_rate_limit_error_inherits_external_service_error(self):
        assert issubclass(RateLimitError, ExternalServiceError)

    def test_authentication_error_inherits_external_service_error(self):
        assert issubclass(AuthenticationError, ExternalServiceError)

    def test_exception_to_dict_includes_external_service_fields(self):
        err = RateLimitError(
            "Too many requests",
            service="provider-x",
            retry_after_seconds=15.0,
            details={"status": 429},
        )
        payload = exception_to_dict(err)
        assert payload["type"] == "RateLimitError"
        assert payload["service"] == "provider-x"
        assert payload["retry_after_seconds"] == 15.0
        assert payload["details"] == {"status": 429}


class TestHierarchyOrdering:
    """Verify the documented exception hierarchy is correct."""

    def test_proving_is_validation(self):
        assert issubclass(ProvingError, ValidationError)

    def test_validation_is_optimizer(self):
        assert issubclass(ValidationError, OptimizerError)

    def test_extraction_is_optimizer(self):
        assert issubclass(ExtractionError, OptimizerError)

    def test_refinement_is_optimizer(self):
        assert issubclass(RefinementError, OptimizerError)

    def test_configuration_is_optimizer(self):
        assert issubclass(ConfigurationError, OptimizerError)

    def test_optimizer_is_exception(self):
        assert issubclass(OptimizerError, Exception)


class TestWrapExceptions:
    def test_wraps_typed_exception_and_preserves_cause(self):
        with pytest.raises(ExtractionError) as exc_info:
            with wrap_exceptions(ExtractionError, "extract failed"):
                raise ValueError("bad input")
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_reraises_optimizer_error_unchanged(self):
        with pytest.raises(ValidationError) as exc_info:
            with wrap_exceptions(ExtractionError, "ignored"):
                raise ValidationError("schema invalid")
        assert isinstance(exc_info.value, ValidationError)
        assert not isinstance(exc_info.value, ExtractionError)

    def test_propagates_base_exception(self):
        with pytest.raises(KeyboardInterrupt):
            with wrap_exceptions(ExtractionError, "ignored"):
                raise KeyboardInterrupt("stop")


class TestSafeErrorHandler:
    def test_catches_declared_exceptions_and_returns_default(self):
        @safe_error_handler(ValueError, default=123)
        def _fn():
            raise ValueError("bad")

        assert _fn() == 123

    def test_propagates_base_exception(self):
        @safe_error_handler(ValueError, default=123)
        def _fn():
            raise KeyboardInterrupt("stop")

        with pytest.raises(KeyboardInterrupt):
            _fn()
