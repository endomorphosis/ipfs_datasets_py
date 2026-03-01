"""Hybrid law reasoner package.

Provides a proof-producing architecture that combines:
- DCEC/dynamic deontic compliance checks,
- temporal FOL deadline/interval reasoning,
- provenance-preserving proof logging.
"""

from .engine import HybridLawReasoner
from .models import (
    IRReference,
    PROOF_SCHEMA_VERSION,
    ProofObject,
    ProofStep,
    SourceProvenance,
)
from .serialization import (
    SUPPORTED_CNL_VERSION,
    SUPPORTED_IR_VERSION,
    append_proof_to_store,
    load_legal_ir_from_json,
    load_legacy_logic_hybrid_fixture,
    load_proof_store,
    proof_from_dict,
    proof_to_dict,
    validate_contract_versions,
    write_proof_store,
)

__all__ = [
    "HybridLawReasoner",
    "IRReference",
    "ProofObject",
    "ProofStep",
    "SourceProvenance",
    "PROOF_SCHEMA_VERSION",
    "SUPPORTED_IR_VERSION",
    "SUPPORTED_CNL_VERSION",
    "validate_contract_versions",
    "load_legal_ir_from_json",
    "load_legacy_logic_hybrid_fixture",
    "load_proof_store",
    "write_proof_store",
    "append_proof_to_store",
    "proof_from_dict",
    "proof_to_dict",
]
