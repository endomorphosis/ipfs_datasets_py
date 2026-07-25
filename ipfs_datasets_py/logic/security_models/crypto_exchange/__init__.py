"""Crypto exchange security verification framework.

This is the frozen Security IR v1 compatibility namespace.  New declarations
and adapters live in :mod:`ipfs_datasets_py.logic.security_ir`; the legacy
exports below retain their original objects and behavior.
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any, Final

from .assumption_registry import evaluate_assumption_registry
from .claims import default_claims
from .extractors import SecurityIRFeatureLoopProjector
from .evidence_promotion import evaluate_evidence_promotion_workflow
from .ir.canonicalize import canonicalize_ir, canonicalize_ir_json
from .ir.cid import calculate_model_cid
from .ir.examples import example_minimal_exchange_model
from .ir.schema import DEFAULT_THREAT_MODEL_ASSUMPTIONS, SecurityModelIR, validate_ir
from .monitors.runtime_mtl import RuntimeMTLMonitor, check_runtime_properties
from .release_policy import ReleasePolicyEntry, evaluate_release_policy, release_policy_entries
from .reports.proof_receipt import ProofReceipt
from .reports.proof_report import ProofReport
from .runners.z3_runner import Z3Runner

__all__ = [
    'DEFAULT_THREAT_MODEL_ASSUMPTIONS',
    'ProofReceipt',
    'ProofReport',
    'ReleasePolicyEntry',
    'RuntimeMTLMonitor',
    'SecurityIRFeatureLoopProjector',
    'SecurityModelIR',
    'Z3Runner',
    'calculate_model_cid',
    'canonicalize_ir',
    'canonicalize_ir_json',
    'check_runtime_properties',
    'default_claims',
    'evaluate_assumption_registry',
    'evaluate_evidence_promotion_workflow',
    'evaluate_release_policy',
    'example_minimal_exchange_model',
    'release_policy_entries',
    'validate_ir',
]


# Explicit migration metadata is intentionally outside the frozen ``__all__``.
# Importing this module is kept quiet because the canonical legacy adapter must
# inspect the old schema without producing a warning itself.
__deprecated__ = True
__deprecated_since__ = "IRFamilyExports@1"
__replacement__ = "ipfs_datasets_py.logic.security_ir"

_DEPRECATION_MESSAGE: Final = (
    "ipfs_datasets_py.logic.security_models.crypto_exchange is a legacy "
    "compatibility path; use ipfs_datasets_py.logic.security_ir for new "
    "declarations and adapters."
)

_DEPRECATED_V1_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "LegacyAdapterResult": ("ipfs_datasets_py.logic.security_ir", "LegacyAdapterResult"),
    "LegacyVerificationData": (
        "ipfs_datasets_py.logic.security_ir",
        "LegacyVerificationData",
    ),
    "SecurityIR": ("ipfs_datasets_py.logic.security_ir", "SecurityIR"),
    "SecurityIRLegacyAdapter": (
        "ipfs_datasets_py.logic.security_ir",
        "SecurityIRLegacyAdapter",
    ),
    "adapt_legacy_security_ir": (
        "ipfs_datasets_py.logic.security_ir",
        "adapt_legacy_security_ir",
    ),
    "to_legacy_security_ir": (
        "ipfs_datasets_py.logic.security_ir",
        "to_legacy_security_ir",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve transitional v1 APIs without expanding the frozen root API."""

    target = _DEPRECATED_V1_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
    module_name, attribute_name = target
    return getattr(importlib.import_module(module_name), attribute_name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_DEPRECATED_V1_EXPORTS))
