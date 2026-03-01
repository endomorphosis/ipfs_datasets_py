"""Hybrid law reasoner package.

Provides a proof-producing architecture that combines:
- DCEC/dynamic deontic compliance checks,
- temporal FOL deadline/interval reasoning,
- provenance-preserving proof logging.
"""

from .engine import HybridLawReasoner
from .models import (
    IRReference,
    ProofObject,
    ProofStep,
    SourceProvenance,
)
from .serialization import (
    append_proof_to_store,
    load_legal_ir_from_json,
    load_proof_store,
    proof_from_dict,
    proof_to_dict,
    write_proof_store,
)

__all__ = [
    "HybridLawReasoner",
    "IRReference",
    "ProofObject",
    "ProofStep",
    "SourceProvenance",
    "load_legal_ir_from_json",
    "load_proof_store",
    "write_proof_store",
    "append_proof_to_store",
    "proof_from_dict",
    "proof_to_dict",
]
