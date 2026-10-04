"""Lazy public contracts for Crypto IR sanctions compliance.

Importing this package performs no list acquisition, networking, reporting, or
optional dependency loading.
"""

from __future__ import annotations

import importlib
from typing import Any, Final


_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "models": (
        "AssociationEvidence",
        "AssociationKind",
        "COMPLIANCE_SCHEMA_VERSION",
        "CRYPTO_IR_COMPLIANCE_DOMAIN",
        "ComplianceModelError",
        "DesignationRecord",
        "DigitalCurrencyIdentifier",
        "Jurisdiction",
        "LegalPolicyApproval",
        "LicenseDisposition",
        "LicenseRecord",
        "OwnershipEvidence",
        "OwnershipInterest",
        "OwnershipKind",
        "PolicyRule",
        "SANCTIONS_POLICY_SCHEMA_VERSION",
        "SANCTIONS_SNAPSHOT_SCHEMA_VERSION",
        "SanctionsAuthority",
        "SanctionsList",
        "SanctionsMatch",
        "SanctionsPolicy",
        "SanctionsPolicyOutcome",
        "SanctionsProgram",
        "SanctionsSnapshot",
    ),
    "policy": (
        "SANCTIONS_SCREENING_SCHEMA_VERSION",
        "SanctionsDecision",
        "SanctionsScreeningRequest",
        "evaluate_sanctions_policy",
        "screen_sanctions",
    ),
}

_EXPORT_MODULE: Final[dict[str, str]] = {
    name: module_name
    for module_name, names in _EXPORTS.items()
    for name in names
}

if len(_EXPORT_MODULE) != sum(len(names) for names in _EXPORTS.values()):
    raise RuntimeError("compliance package exports must have one owning module")

__all__ = sorted(_EXPORT_MODULE)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
