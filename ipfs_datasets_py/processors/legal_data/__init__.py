"""Legal data processing modules consolidated under ipfs_datasets_py.processors."""

from .reasoner import (
    HybridLawReasoner,
    IRReference,
    ProofObject,
    ProofStep,
    SourceProvenance,
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
