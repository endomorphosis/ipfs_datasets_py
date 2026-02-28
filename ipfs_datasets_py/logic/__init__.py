"""Consolidated logic namespace.

This package consolidates the former top-level modules:
- ipfs_datasets_py.logic.integrations
- ipfs_datasets_py.logic.tools (DEPRECATED - use integration/ or module-specific imports)
- ipfs_datasets_py.logic.integration

New canonical import paths live under:
- ipfs_datasets_py.logic.integrations
- ipfs_datasets_py.logic.integration (preferred over tools/)
- ipfs_datasets_py.logic.fol (for FOL-specific functionality)
- ipfs_datasets_py.logic.deontic (for deontic logic functionality)

The tools/ directory is deprecated and will be removed in v2.0.
Use integration/ or module-specific imports instead.
"""

from __future__ import annotations
import warnings


# Beartype emits PEP585 deprecation warnings at import-time for some legacy
# typing hints (e.g., ``typing.List[str]``). These warnings are not actionable
# for typical users and break the “import must be quiet” contract enforced by
# the superproject tests. We silence only this specific beartype category.
try:  # pragma: no cover
    from beartype.roar import BeartypeDecorHintPep585DeprecationWarning  # type: ignore
except Exception:  # pragma: no cover
    BeartypeDecorHintPep585DeprecationWarning = None  # type: ignore

if BeartypeDecorHintPep585DeprecationWarning is not None:
    warnings.filterwarnings(
        "ignore",
        category=BeartypeDecorHintPep585DeprecationWarning,  # type: ignore[arg-type]
    )

__all__ = ["api", "integrations", "tools", "integration", "cli", "flogic"]


def __getattr__(name):
    """
    Provide backward compatibility for tools/ imports with deprecation warnings.
    
    This allows old code like:
        from ipfs_datasets_py.logic import tools
        tools.deontic_logic_core.DeonticOperator
    
    To still work but with a deprecation warning.
    """
    if name == "tools":
        warnings.warn(
            "Importing from logic.tools is deprecated and will be removed in v2.0. "
            "Use logic.integration or module-specific imports (logic.fol, logic.deontic) instead. "
            "See MIGRATION_GUIDE.md for details.",
            DeprecationWarning,
            stacklevel=2
        )
        # Redirect to integration module
        from . import integration
        return integration

    if name == "api":
        from . import api
        return api

    if name == "cli":
        from . import cli
        return cli
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
