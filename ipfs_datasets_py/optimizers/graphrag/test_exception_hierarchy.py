"""Test unified exception hierarchy for GraphRAG optimizer.

This validates that:
1. All GraphRAG-specific exceptions inherit from the correct base classes
2. Typed exceptions are used instead of stdlib exceptions where appropriate
3. Exception instances carry structured details for debugging
"""

import pytest
from pathlib import Path
from typing import Any

from .exceptions import (
    # Base hierarchy
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
    # GraphRAG-specific
    GraphRAGError,
    OntologyExtractionError,
    OntologyValidationError,
    LogicProvingError,
    PathResolutionError,
    QueryCacheError,
    SessionError,
)


class TestExceptionHierarchy:
    """Test exception inheritance and structure."""

    def test_base_hierarchy_inheritance(self):
        """All optimizer exceptions inherit from OptimizerError."""
        assert issubclass(ExtractionError, OptimizerError)
        assert issubclass(ValidationError, OptimizerError)
        assert issubclass(ProvingError, ValidationError)  # ProvingError is validation failure
        assert issubclass(RefinementError, OptimizerError)
        assert issubclass(ConfigurationError, OptimizerError)
        assert issubclass(GraphRAGError, OptimizerError)

    def test_graphrag_specific_inheritance(self):
        """GraphRAG-specific exceptions inherit from appropriate base classes."""
        assert issubclass(OntologyExtractionError, ExtractionError)
        assert issubclass(OntologyValidationError, ValidationError)
        assert issubclass(LogicProvingError, ProvingError)
        assert issubclass(PathResolutionError, ConfigurationError)
        assert issubclass(QueryCacheError, OptimizerError)
        assert issubclass(SessionError, RefinementError)

    def test_exception_with_message(self):
        """Exceptions can be raised with a message."""
        exc = OptimizerError("Test error message")
        assert str(exc) == "Test error message"
        assert exc.message == "Test error message"

    def test_exception_with_details(self):
        """Exceptions can carry structured details."""
        details = {"key": "value", "count": 42}
        exc = OptimizerError("Test error", details=details)
        assert exc.details == details
        assert "details=" in str(exc)

    def test_validation_error_with_errors_list(self):
        """ValidationError can carry a list of validation errors."""
        errors = ["Missing field 'id'", "Invalid type for 'score'"]
        exc = ValidationError("Validation failed", errors=errors)
        assert exc.errors == errors
        assert "errors=" in str(exc)

    def test_proving_error_with_prover_info(self):
        """ProvingError can carry prover-specific information."""
        exc = ProvingError(
            "Proof failed",
            prover="z3",
            formula="Entity(x) => Type(x)",
            errors=["UNSAT"]
        )
        assert exc.prover == "z3"
        assert exc.formula == "Entity(x) => Type(x)"
        assert "prover=" in str(exc)
        assert "formula=" in str(exc)

    def test_catch_base_class(self):
        """Catching OptimizerError catches all optimizer exceptions."""
        try:
            raise OntologyValidationError("Test", errors=["error1"])
        except OptimizerError as e:
            assert isinstance(e, OntologyValidationError)
            assert e.message == "Test"

    def test_catch_specific_class(self):
        """Can catch specific exception types."""
        try:
            raise QueryCacheError("Cache miss", details={"key": "test_key"})
        except QueryCacheError as e:
            assert e.details["key"] == "test_key"


class TestExceptionUsage:
    """Test that exceptions are actually used in the codebase."""

    def test_cli_wrapper_path_resolution(self):
        """CLI wrapper raises PathResolutionError for invalid paths."""
        from .cli_wrapper import _safe_resolve
        
        with pytest.raises(PathResolutionError) as exc_info:
            _safe_resolve("/proc/self/mem")
        
        assert "restricted area" in str(exc_info.value)
        assert exc_info.value.details is not None

    def test_cli_wrapper_missing_file(self):
        """CLI wrapper raises PathResolutionError for missing files."""
        from .cli_wrapper import _safe_resolve
        
        with pytest.raises(PathResolutionError) as exc_info:
            _safe_resolve("/nonexistent/file/path.txt", must_exist=True)
        
        assert "not found" in str(exc_info.value)

    def test_ontology_validator_invalid_ontology(self):
        """OntologyValidator raises OntologyValidationError for invalid input."""
        from .ontology_validator import OntologyValidator
        
        validator = OntologyValidator()
        
        # Test with non-dict input
        with pytest.raises(OntologyValidationError) as exc_info:
            validator.suggest_entity_merges("not a dict", threshold=0.8)
        
        assert "must be a dictionary" in str(exc_info.value)

    def test_ontology_validator_invalid_threshold(self):
        """OntologyValidator raises OntologyValidationError for bad threshold."""
        from .ontology_validator import OntologyValidator
        
        validator = OntologyValidator()
        ontology = {"entities": [], "relationships": []}
        
        with pytest.raises(OntologyValidationError) as exc_info:
            validator.suggest_entity_merges(ontology, threshold=1.5)
        
        assert "between 0.0 and 1.0" in str(exc_info.value)

    def test_logic_validator_non_dict_ontology(self):
        """LogicValidator raises OntologyValidationError for non-dict ontology."""
        from .logic_validator import LogicValidator
        
        validator = LogicValidator()
        
        with pytest.raises(OntologyValidationError) as exc_info:
            validator.ontology_to_tdfol(["not", "a", "dict"])
        
        assert "must be a dict" in str(exc_info.value)

    def test_logic_validator_missing_entities(self):
        """LogicValidator raises OntologyValidationError for missing entities."""
        from .logic_validator import LogicValidator
        
        validator = LogicValidator()
        
        with pytest.raises(OntologyValidationError) as exc_info:
            validator.ontology_to_tdfol({"entities": "not a list", "relationships": []})
        
        assert "must be a list" in str(exc_info.value)

    def test_query_planner_cache_error(self):
        """GraphRAGQueryOptimizer raises QueryCacheError for cache misses."""
        from .query_planner import GraphRAGQueryOptimizer
        
        optimizer = GraphRAGQueryOptimizer()
        
        with pytest.raises(QueryCacheError) as exc_info:
            optimizer.get_from_cache("nonexistent_key")
        
        assert "not in cache" in str(exc_info.value)
        assert exc_info.value.details is not None
        assert "query_key" in exc_info.value.details


class TestExceptionDocumentation:
    """Test that exceptions are properly documented."""

    def test_all_exceptions_have_docstrings(self):
        """All exception classes have docstrings."""
        exceptions = [
            OptimizerError,
            ExtractionError,
            ValidationError,
            ProvingError,
            RefinementError,
            ConfigurationError,
            GraphRAGError,
            OntologyExtractionError,
            OntologyValidationError,
            LogicProvingError,
            PathResolutionError,
            QueryCacheError,
            SessionError,
        ]
        
        for exc_class in exceptions:
            assert exc_class.__doc__ is not None, f"{exc_class.__name__} missing docstring"
            assert len(exc_class.__doc__.strip()) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
