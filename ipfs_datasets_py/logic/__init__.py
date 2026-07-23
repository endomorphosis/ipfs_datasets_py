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
import importlib
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

_SUBMODULE_EXPORTS = {
    "api",
    "batch_processing",
    "benchmarks",
    "bridge",
    "CEC",
    "cli",
    "common",
    "config",
    "deontic",
    "e2e_validation",
    "external_provers",
    "flogic",
    "flogic_optimizer",
    "fol",
    "hammers",
    "integration",
    "integrations",
    "ml_confidence",
    "modal",
    "monitoring",
    "observability",
    "security",
    "security_models",
    "submodule_registry",
    "TDFOL",
    "tools",
    "types",
    "zkp",
}

_REGISTRY_EXPORTS = {
    "LogicSubmoduleSpec",
    "logic_integration_manifest",
    "logic_optimizer_scope_for_component",
    "logic_optimizer_target_file_hints",
    "logic_submodule_import_report",
    "logic_submodule_names",
    "logic_submodule_spec",
    "logic_submodule_specs",
}

_PROFILE_D_EXPORTS = {
    "ProfileDPolicyError",
    "evaluate_execution_policy",
}

_PROFILE_G_EXPORTS = {
    "Ed25519Signer",
    "GoalPlanValidator",
    "NeighborhoodAttestationEngine",
    "ProfileGError",
    "RiskEvidenceStore",
    "evaluate_risk_model",
    "profile_g_cid",
    "validate_profile_g_artifact",
}

__all__ = sorted(_SUBMODULE_EXPORTS | _REGISTRY_EXPORTS | _PROFILE_D_EXPORTS | _PROFILE_G_EXPORTS)


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
        # Redirect to integration module without recursive package getattr.
        module = importlib.import_module(".integration", __name__)
        globals()["tools"] = module
        return module

    if name in _REGISTRY_EXPORTS:
        registry = importlib.import_module(".submodule_registry", __name__)
        value = getattr(registry, name)
        globals()[name] = value
        return value

    if name in _PROFILE_D_EXPORTS:
        module = importlib.import_module(".profile_d_policy", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value

    if name in _PROFILE_G_EXPORTS:
        module = importlib.import_module(".profile_g", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value

    if name in _SUBMODULE_EXPORTS:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
