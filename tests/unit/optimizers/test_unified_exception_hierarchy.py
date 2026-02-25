"""Contract tests for optimizer exception hierarchy across subpackages."""

from ipfs_datasets_py.optimizers.common.exceptions import OptimizerError
from ipfs_datasets_py.optimizers.agentic.exceptions import AgenticError
from ipfs_datasets_py.optimizers.graphrag.exceptions import (
    GraphRAGError,
    LogicProvingError,
    OntologyExtractionError,
    OntologyValidationError,
    PathResolutionError,
    QueryCacheError,
    SessionError,
)
from ipfs_datasets_py.optimizers.graphrag.error_handling import GraphRAGException
from ipfs_datasets_py.optimizers.logic.exceptions import LogicError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.exceptions import (
    LogicTheoremOptimizerError,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    LogicTheoremOptimizerError as ExportedLogicTheoremOptimizerError,
)


def test_package_base_exceptions_inherit_optimizer_error() -> None:
    """All package-level base exceptions should share OptimizerError ancestry."""
    assert issubclass(AgenticError, OptimizerError)
    assert issubclass(GraphRAGError, OptimizerError)
    assert issubclass(LogicError, OptimizerError)
    assert issubclass(LogicTheoremOptimizerError, OptimizerError)


def test_graphrag_legacy_exception_joins_unified_hierarchy() -> None:
    """Legacy GraphRAGException should also be catchable via OptimizerError."""
    assert issubclass(GraphRAGException, GraphRAGError)
    assert issubclass(GraphRAGException, OptimizerError)


def test_logic_theorem_optimizer_exports_shared_exception() -> None:
    """Package-level lazy export should resolve to the same exception class."""
    assert ExportedLogicTheoremOptimizerError is LogicTheoremOptimizerError


def test_graphrag_specific_exceptions_map_to_unified_bases() -> None:
    """GraphRAG-specific exceptions should sit on the common optimizer tree."""
    from ipfs_datasets_py.optimizers.common.exceptions import (
        ConfigurationError,
        ExtractionError,
        ProvingError,
        RefinementError,
        ValidationError,
    )

    assert issubclass(OntologyExtractionError, ExtractionError)
    assert issubclass(OntologyValidationError, ValidationError)
    assert issubclass(LogicProvingError, ProvingError)
    assert issubclass(PathResolutionError, ConfigurationError)
    assert issubclass(SessionError, RefinementError)
    assert issubclass(QueryCacheError, OptimizerError)
