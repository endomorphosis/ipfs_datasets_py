"""Batch 266: Unified Exception Hierarchy Tests

Tests the unified exception hierarchy across graphrag, logic, and agentic
packages to ensure proper inheritance, imports, and exception handling.

Test Categories:
- Exception inheritance verification
- Cross-package exception catching
- Exception attribute preservation
- Exception message formatting
- Exception wrapping and context managers
"""

import pytest
from typing import Any, Optional

# GraphRAG exceptions
from ipfs_datasets_py.optimizers.graphrag.exceptions import (
    GraphRAGError,
    OntologyExtractionError,
    OntologyValidationError,
    LogicProvingError,
    PathResolutionError,
    QueryCacheError,
)

# Logic exceptions
from ipfs_datasets_py.optimizers.logic.exceptions import (
    LogicError,
)

# Agentic exceptions
from ipfs_datasets_py.optimizers.agentic.exceptions import (
    AgenticError,
)

# Common base exceptions
from ipfs_datasets_py.optimizers.common.exceptions import (
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
    wrap_exceptions,
)


# ============================================================================
# Test Classes
# ============================================================================

class TestExceptionInheritance:
    """Test exception inheritance hierarchy."""

    def test_graphrag_error_inherits_optimizer_error(self):
        """GraphRAGError inherits from OptimizerError."""
        assert issubclass(GraphRAGError, OptimizerError)

    def test_ontology_extraction_error_inherits_extraction_error(self):
        """OntologyExtractionError inherits from ExtractionError."""
        assert issubclass(OntologyExtractionError, ExtractionError)
        assert issubclass(OntologyExtractionError, OptimizerError)

    def test_ontology_validation_error_inherits_validation_error(self):
        """OntologyValidationError inherits from ValidationError."""
        assert issubclass(OntologyValidationError, ValidationError)
        assert issubclass(OntologyValidationError, OptimizerError)

    def test_logic_proving_error_inherits_proving_error(self):
        """LogicProvingError inherits from ProvingError."""
        assert issubclass(LogicProvingError, ProvingError)
        assert issubclass(LogicProvingError, OptimizerError)

    def test_path_resolution_error_inherits_configuration_error(self):
        """PathResolutionError inherits from ConfigurationError."""
        assert issubclass(PathResolutionError, ConfigurationError)
        assert issubclass(PathResolutionError, OptimizerError)

    def test_query_cache_error_inherits_optimizer_error(self):
        """QueryCacheError inherits from OptimizerError."""
        assert issubclass(QueryCacheError, OptimizerError)

    def test_logic_error_inherits_optimizer_error(self):
        """LogicError inherits from OptimizerError."""
        assert issubclass(LogicError, OptimizerError)

    def test_agentic_error_inherits_optimizer_error(self):
        """AgenticError inherits from OptimizerError."""
        assert issubclass(AgenticError, OptimizerError)


class TestCrossPackageExceptionCatching:
    """Test catching exceptions via base classes across packages."""

    def test_catch_graphrag_via_optimizer_error(self):
        """Can catch GraphRAGError via OptimizerError."""
        with pytest.raises(OptimizerError):
            raise GraphRAGError("test")

    def test_catch_ontology_extraction_via_extraction_error(self):
        """Can catch OntologyExtractionError via ExtractionError."""
        with pytest.raises(ExtractionError):
            raise OntologyExtractionError("test")

    def test_catch_ontology_validation_via_validation_error(self):
        """Can catch OntologyValidationError via ValidationError."""
        with pytest.raises(ValidationError):
            raise OntologyValidationError("test")

    def test_catch_logic_proving_via_proving_error(self):
        """Can catch LogicProvingError via ProvingError."""
        with pytest.raises(ProvingError):
            raise LogicProvingError("test")

    def test_catch_path_resolution_via_configuration_error(self):
        """Can catch PathResolutionError via ConfigurationError."""
        with pytest.raises(ConfigurationError):
            raise PathResolutionError("test")

    def test_catch_all_package_errors_via_optimizer_error(self):
        """Can catch all package errors via OptimizerError."""
        errors = [
            GraphRAGError("graph"),
            LogicError("logic"),
            AgenticError("agentic"),
            OntologyExtractionError("extract"),
            OntologyValidationError("validate"),
        ]
        
        for error in errors:
            with pytest.raises(OptimizerError):
                raise error


class TestExceptionAttributes:
    """Test exception attributes and properties."""

    def test_optimizer_error_has_message(self):
        """OptimizerError stores message attribute."""
        err = OptimizerError("test message")
        assert err.message == "test message"
        assert str(err) == "test message"

    def test_optimizer_error_has_details(self):
        """OptimizerError stores details attribute."""
        details = {"key": "value", "num": 42}
        err = OptimizerError("test", details=details)
        assert err.details == details
        assert "key" in str(err)

    def test_validation_error_has_errors_list(self):
        """ValidationError stores errors list."""
        errors = ["error1", "error2"]
        err = ValidationError("validation failed", errors=errors)
        assert err.errors == errors

    def test_validation_error_defaults_empty_errors(self):
        """ValidationError defaults to empty errors list."""
        err = ValidationError("validation failed")
        assert err.errors == []


class TestExceptionMessageFormatting:
    """Test exception message formatting."""

    def test_simple_message_no_details(self):
        """Simple message without details formats correctly."""
        err = OptimizerError("simple message")
        assert str(err) == "simple message"

    def test_message_with_details(self):
        """Message with details includes details in string."""
        err = OptimizerError("error occurred", details={"code": 500})
        assert "error occurred" in str(err)
        assert "code" in str(err)

    def test_nested_details_formatting(self):
        """Nested details format correctly."""
        err = OptimizerError("nested", details={"outer": {"inner": "value"}})
        str_repr = str(err)
        assert "nested" in str_repr
        assert "outer" in str_repr or "inner" in str_repr


class TestExceptionWrapping:
    """Test exception wrapping utilities."""

    def test_wrap_exceptions_catches_and_raises(self):
        """wrap_exceptions catches and re-raises as specified type."""
        with pytest.raises(ExtractionError):
            with wrap_exceptions(ExtractionError, "wrapped"):
                raise ValueError("original")

    def test_wrap_exceptions_preserves_message(self):
        """wrap_exceptions preserves original message."""
        original_msg = "specific error details"
        try:
            with wrap_exceptions(ExtractionError, "wrapped"):
                raise ValueError(original_msg)
        except ExtractionError as e:
            assert original_msg in str(e) or "wrapped" in str(e)

    def test_wrap_exceptions_no_error_passes_through(self):
        """wrap_exceptions passes through when no error occurs."""
        with wrap_exceptions(ExtractionError, "wrapped"):
            x = 1 + 1  # No error
        assert x == 2


class TestExceptionExports:
    """Test exception module exports."""

    def test_logic_exceptions_all_exported(self):
        """Logic exceptions module defines __all__."""
        from ipfs_datasets_py.optimizers.logic import exceptions as logic_exc
        assert hasattr(logic_exc, "__all__")
        assert "LogicError" in logic_exc.__all__
        assert "OptimizerError" in logic_exc.__all__

    def test_agentic_exceptions_all_exported(self):
        """Agentic exceptions module defines __all__."""
        from ipfs_datasets_py.optimizers.agentic import exceptions as agentic_exc
        assert hasattr(agentic_exc, "__all__")
        assert "AgenticError" in agentic_exc.__all__
        assert "OptimizerError" in agentic_exc.__all__

    def test_graphrag_exceptions_importable(self):
        """All GraphRAG exceptions are importable."""
        # Already imported at module level, just verify they exist
        assert GraphRAGError is not None
        assert OntologyExtractionError is not None
        assert OntologyValidationError is not None
        assert LogicProvingError is not None
        assert PathResolutionError is not None
        assert QueryCacheError is not None


class TestExceptionInstantiation:
    """Test exception instantiation with various arguments."""

    def test_instantiate_with_message_only(self):
        """Can instantiate with just message."""
        err = GraphRAGError("message")
        assert str(err) == "message"

    def test_instantiate_with_details(self):
        """Can instantiate with message and details."""
        err = OntologyExtractionError("failed", details={"entity": "test"})
        assert err.message == "failed"
        assert err.details == {"entity": "test"}

    def test_instantiate_validation_with_errors(self):
        """Can instantiate ValidationError with errors list."""
        err = OntologyValidationError(
            "validation failed",
            errors=["missing id", "invalid type"]
        )
        assert len(err.errors) == 2
        assert "missing id" in err.errors

    def test_instantiate_all_exception_types(self):
        """All exception types can be instantiated."""
        exceptions_to_test = [
            (OptimizerError, "base"),
            (ExtractionError, "extract"),
            (ValidationError, "validate"),
            (ProvingError, "prove"),
            (RefinementError, "refine"),
            (ConfigurationError, "config"),
            (GraphRAGError, "graphrag"),
            (OntologyExtractionError, "ontology extract"),
            (OntologyValidationError, "ontology validate"),
            (LogicProvingError, "logic prove"),
            (PathResolutionError, "path resolve"),
            (QueryCacheError, "query cache"),
            (LogicError, "logic"),
            (AgenticError, "agentic"),
        ]
        
        for exc_class, message in exceptions_to_test:
            err = exc_class(message)
            assert err.message == message
            assert isinstance(err, OptimizerError)


class TestExceptionPicklability:
    """Test that exceptions can be pickled (for multiprocessing)."""

    def test_optimizer_error_picklable(self):
        """OptimizerError can be pickled and restored."""
        import pickle
        
        err = OptimizerError("test message", details={"key": "value"})
        pickled = pickle.dumps(err)
        restored = pickle.loads(pickled)
        
        assert restored.message == err.message
        assert restored.details == err.details

    def test_validation_error_picklable(self):
        """ValidationError can be pickled and restored."""
        import pickle
        
        err = ValidationError(
            "validation failed",
            errors=["error1", "error2"],
            details={"field": "value"}
        )
        pickled = pickle.dumps(err)
        restored = pickle.loads(pickled)
        
        assert restored.message == err.message
        assert restored.errors == err.errors
        assert restored.details == err.details

    def test_all_package_errors_picklable(self):
        """All package-specific errors can be pickled."""
        import pickle
        
        errors = [
            GraphRAGError("graph"),
            OntologyExtractionError("extract"),
            OntologyValidationError("validate"),
            LogicProvingError("prove"),
            PathResolutionError("path"),
            QueryCacheError("cache"),
            LogicError("logic"),
            AgenticError("agentic"),
        ]
        
        for err in errors:
            pickled = pickle.dumps(err)
            restored = pickle.loads(pickled)
            assert restored.message == err.message
            assert type(restored) == type(err)
