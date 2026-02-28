"""Logic optimizer public API exports."""

from .exceptions import (
    LogicError,
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
)

__all__ = [
    "LogicError",
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
    "FLogicSemanticOptimizer",
    "FLogicOptimizerConfig",
    "FLogicOptimizerResult",
    "OntologyViolation",
]

_FLOGIC_EXPORTS = {
    "FLogicSemanticOptimizer",
    "FLogicOptimizerConfig",
    "FLogicOptimizerResult",
    "OntologyViolation",
}


def __getattr__(name: str):
    if name in _FLOGIC_EXPORTS:
        from .flogic_optimizer import (  # noqa: PLC0415
            FLogicSemanticOptimizer,
            FLogicOptimizerConfig,
            FLogicOptimizerResult,
            OntologyViolation,
        )
        _locals = {
            "FLogicSemanticOptimizer": FLogicSemanticOptimizer,
            "FLogicOptimizerConfig": FLogicOptimizerConfig,
            "FLogicOptimizerResult": FLogicOptimizerResult,
            "OntologyViolation": OntologyViolation,
        }
        value = _locals[name]
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")