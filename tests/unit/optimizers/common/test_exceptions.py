"""Tests for the typed exception hierarchy in common/exceptions.py."""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.exceptions import (
    ConfigurationError,
    ExtractionError,
    OptimizerError,
    ProvingError,
    RefinementError,
    ValidationError,
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
