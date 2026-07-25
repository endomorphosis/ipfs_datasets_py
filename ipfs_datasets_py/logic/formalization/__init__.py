"""Stable domain-neutral formalization contracts.

Only deterministic data contracts and compiler protocols are exported here.
Learned advisors, checkpoints, and runtime backends intentionally remain out
of the package-root API until their interfaces are reviewed.
"""

from __future__ import annotations

import importlib
from typing import Any, Final


_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "compiler": (
        "FORMALIZATION_ARTIFACT_SCHEMA_VERSION",
        "FORMALIZATION_COMPILER_CONFIG_SCHEMA_VERSION",
        "UNSUPPORTED_SEMANTICS_SCHEMA_VERSION",
        "FormalizationArtifact",
        "FormalizationCompiler",
        "FormalizationCompilerConfig",
        "UnsupportedSemanticsDiagnostic",
        "UnsupportedSemanticsPolicy",
    ),
    "samples": (
        "FORMALIZATION_SAMPLE_SCHEMA_VERSION",
        "FormalizationSample",
        "FormalizationValidationError",
    ),
    "views": (
        "FORMALIZATION_VIEW_SCHEMA_VERSION",
        "FORMALIZATION_VIEW_REGISTRY_SCHEMA_VERSION",
        "FORMAL_SYMBOL_TABLE_SCHEMA_VERSION",
        "FORMAL_FORMULA_SCHEMA_VERSION",
        "FORMAL_CROSS_VIEW_LINK_SCHEMA_VERSION",
        "CrossViewLink",
        "CrossViewRelation",
        "FormalFormula",
        "FormalSymbol",
        "FormalizationView",
        "SymbolTable",
        "ViewRegistry",
        "canonical_view_registry_json",
        "validate_view_artifacts",
    ),
}

_EXPORT_MODULE: Final[dict[str, str]] = {
    name: module_name
    for module_name, names in _EXPORTS.items()
    for name in names
}

__all__ = sorted(_EXPORT_MODULE)


def __getattr__(name: str) -> Any:
    """Load a reviewed formalization contract from its owning leaf module."""

    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
