"""Batch 271: Cross-package exception hierarchy unification tests."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.exceptions import (
    ExtractionError as CommonExtractionError,
    OptimizerError as CommonOptimizerError,
    ProvingError as CommonProvingError,
    ValidationError as CommonValidationError,
)
from ipfs_datasets_py.optimizers.agentic import exceptions as agentic_exceptions
from ipfs_datasets_py.optimizers.graphrag import exceptions as graphrag_exceptions
from ipfs_datasets_py.optimizers.graphrag.schema_validator import OntologySchemaError
from ipfs_datasets_py.optimizers.logic import exceptions as logic_exceptions
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import exceptions as logic_theorem_exceptions


def test_agentic_reexports_common_exception_types() -> None:
    assert agentic_exceptions.OptimizerError is CommonOptimizerError
    assert agentic_exceptions.ExtractionError is CommonExtractionError
    assert agentic_exceptions.ValidationError is CommonValidationError
    assert agentic_exceptions.ProvingError is CommonProvingError


def test_logic_reexports_common_exception_types() -> None:
    assert logic_exceptions.OptimizerError is CommonOptimizerError
    assert logic_exceptions.ExtractionError is CommonExtractionError
    assert logic_exceptions.ValidationError is CommonValidationError
    assert logic_exceptions.ProvingError is CommonProvingError


def test_logic_theorem_reexports_common_exception_types() -> None:
    assert logic_theorem_exceptions.OptimizerError is CommonOptimizerError
    assert logic_theorem_exceptions.ExtractionError is CommonExtractionError
    assert logic_theorem_exceptions.ValidationError is CommonValidationError
    assert logic_theorem_exceptions.ProvingError is CommonProvingError


def test_graphrag_reexports_common_exception_types() -> None:
    assert graphrag_exceptions.OptimizerError is CommonOptimizerError
    assert graphrag_exceptions.ExtractionError is CommonExtractionError
    assert graphrag_exceptions.ValidationError is CommonValidationError
    assert graphrag_exceptions.ProvingError is CommonProvingError


def test_package_specific_bases_inherit_common_optimizer_error() -> None:
    assert issubclass(agentic_exceptions.AgenticError, CommonOptimizerError)
    assert issubclass(logic_exceptions.LogicError, CommonOptimizerError)
    assert issubclass(logic_theorem_exceptions.LogicTheoremOptimizerError, CommonOptimizerError)
    assert issubclass(graphrag_exceptions.GraphRAGError, CommonOptimizerError)


def test_schema_validator_ontology_schema_error_is_validation_error() -> None:
    assert issubclass(OntologySchemaError, CommonValidationError)


def test_common_optimizer_error_catches_package_exception_instances() -> None:
    with pytest.raises(CommonOptimizerError):
        raise agentic_exceptions.ExtractionError("agentic extraction failed")

    with pytest.raises(CommonOptimizerError):
        raise graphrag_exceptions.OntologyValidationError("ontology invalid")
