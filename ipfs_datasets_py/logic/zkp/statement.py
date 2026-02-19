"""Statement and witness format for ZKP circuits.

Defines what is proven (statement) and what must remain private (witness).

For the MVP circuit: "I know a set of axioms whose commitment matches X,
and the theorem being proven is Y."
"""

from dataclasses import dataclass
from typing import List, Dict, Any
import hashlib
import json


_U64_MAX = (1 << 64) - 1


def parse_circuit_ref(circuit_ref: str) -> tuple[str, int]:
    """Parse a circuit reference string.

    Version policy: `circuit_id@v<uint64>`.

    Returns:
        (circuit_id, version)
    """
    if not isinstance(circuit_ref, str):
        raise TypeError("circuit_ref must be a str")

    if circuit_ref == "":
        raise ValueError("circuit_ref cannot be empty")

    circuit_id, sep, version_part = circuit_ref.partition("@v")
    if sep != "@v":
        raise ValueError("circuit_ref must be of the form circuit_id@v<uint64>")

    if circuit_id == "":
        raise ValueError("circuit_id cannot be empty")
    if "@" in circuit_id:
        raise ValueError("circuit_id must not contain '@'")

    if version_part == "":
        raise ValueError("circuit_ref version is missing")
    if not version_part.isdecimal():
        raise ValueError("circuit_ref version must be an unsigned base-10 integer")

    version = int(version_part)
    if version < 0 or version > _U64_MAX:
        raise ValueError("circuit_ref version must be in uint64 range")

    return circuit_id, version


def parse_circuit_ref_lenient(circuit_ref: str, legacy_default_version: int = 1) -> tuple[str, int]:
    """Parse a circuit reference, accepting legacy unversioned identifiers.

    - Preferred format: `circuit_id@v<uint64>` (parsed via `parse_circuit_ref`)
    - Legacy format: `circuit_id` (interpreted as `circuit_id@v<legacy_default_version>`)
    """
    if not isinstance(circuit_ref, str):
        raise TypeError("circuit_ref must be a str")

    if circuit_ref == "":
        raise ValueError("circuit_ref cannot be empty")

    if "@v" in circuit_ref:
        return parse_circuit_ref(circuit_ref)

    if "@" in circuit_ref:
        raise ValueError("legacy circuit_id must not contain @")

    if not isinstance(legacy_default_version, int) or isinstance(legacy_default_version, bool):
        raise TypeError("legacy_default_version must be an int")
    if legacy_default_version < 0 or legacy_default_version > _U64_MAX:
        raise ValueError("legacy_default_version must be in uint64 range")

    return circuit_ref, legacy_default_version


def format_circuit_ref(circuit_id: str, version: int) -> str:
    """Format a circuit reference string using the version policy."""
    if not isinstance(circuit_id, str):
        raise TypeError("circuit_id must be a str")
    if circuit_id == "":
        raise ValueError("circuit_id cannot be empty")
    if "@" in circuit_id:
        raise ValueError("circuit_id must not contain '@'")

    if not isinstance(version, int) or isinstance(version, bool):
        raise TypeError("version must be an int")
    if version < 0 or version > _U64_MAX:
        raise ValueError("version must be in uint64 range")

    return f"{circuit_id}@v{version}"


@dataclass
class Statement:
    """
    Public statement being proven.
    
    These values are visible to verifier; they constrain what witness is valid.
    """
    
    theorem_hash: str  # SHA256 hash of `canonicalize_theorem(theorem)`
    axioms_commitment: str  # Merkle/Pedersen commitment to axiom set
    circuit_version: int  # Identifies constraint system (e.g., 1 for MVP)
    ruleset_id: str  # Identifies inference engine (e.g., "TDFOL_v1")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'theorem_hash': self.theorem_hash,
            'axioms_commitment': self.axioms_commitment,
            'circuit_version': self.circuit_version,
            'ruleset_id': self.ruleset_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Statement':
        """Create from dictionary."""
        return cls(
            theorem_hash=data['theorem_hash'],
            axioms_commitment=data['axioms_commitment'],
            circuit_version=data['circuit_version'],
            ruleset_id=data['ruleset_id'],
        )
    
    def to_field_elements(self) -> List[int]:
        """
        Convert statement to field elements for circuit.
        
        Maps each component to a field element (scalar mod p for BN254).
        
        For MVP, uses simple hashing:
        - theorem_hash (first 32 bytes → field element)
        - axioms_commitment (first 32 bytes → field element)
        - circuit_version (as int)
        - ruleset_id (hash first 32 bytes)
        
        Returns:
            List of field elements (as integers)
        """
        # Placeholder: in production, would use proper field encoding + padding
        P_BN254 = 21888242871839275222246405745257275088548364400416034343698204186575808495617
        
        fields = []
        
        # theorem_hash → field element
        theorem_int = int(self.theorem_hash, 16)  % P_BN254
        fields.append(theorem_int)
        
        # axioms_commitment → field element
        axioms_int = int(self.axioms_commitment, 16) % P_BN254
        fields.append(axioms_int)
        
        # circuit_version
        fields.append(self.circuit_version)
        
        # ruleset_id hash
        ruleset_hash = hashlib.sha256(self.ruleset_id.encode()).hexdigest()
        ruleset_int = int(ruleset_hash, 16) % P_BN254
        fields.append(ruleset_int)
        
        return fields


@dataclass
class Witness:
    """
    Private witness for circuit.
    
    These values remain secret; they satisfy the circuit constraints
    for a given Statement.
    """
    
    axioms: List[str]  # Private axiom set
    theorem: str | None = None  # Optional: theorem being proven (P7/P7.2)
    intermediate_steps: List[str] = None  # Optional: proof steps
    axioms_commitment_hex: str = None  # Commitment to axiom set
    circuit_version: int = 1  # Circuit spec version
    ruleset_id: str = "TDFOL_v1"  # Inference engine ID
    
    def __post_init__(self):
        if self.intermediate_steps is None:
            self.intermediate_steps = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (WARNING: reveals private data!)."""
        return {
            'axioms': self.axioms,
            'theorem': self.theorem,
            'intermediate_steps': self.intermediate_steps,
            'axioms_commitment_hex': self.axioms_commitment_hex,
            'circuit_version': self.circuit_version,
            'ruleset_id': self.ruleset_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Witness':
        """Create from dictionary."""
        return cls(
            axioms=data['axioms'],
            theorem=data.get('theorem'),
            intermediate_steps=data.get('intermediate_steps', []),
            axioms_commitment_hex=data.get('axioms_commitment_hex'),
            circuit_version=data.get('circuit_version', 1),
            ruleset_id=data.get('ruleset_id', 'TDFOL_v1'),
        )


@dataclass
class ProofStatement:
    """
    Complete proof statement: public inputs + circuit version.
    
    Used to bundle statement and circuit info for verification.
    """
    
    statement: Statement
    circuit_id: str  # Identifies the circuit (e.g., "knowledge_of_axioms")
    proof_type: str = "simulated"  # Proof system (e.g., "simulated", "groth16")
    witness_count: int = 0  # Number of axioms in witness
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'statement': self.statement.to_dict(),
            'circuit_id': self.circuit_id,
            'circuit_ref': format_circuit_ref(self.circuit_id, int(self.statement.circuit_version)),
            'proof_type': self.proof_type,
            'witness_count': self.witness_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProofStatement':
        """Create from dictionary."""
        return cls(
            statement=Statement.from_dict(data['statement']),
            circuit_id=data['circuit_id'],
            proof_type=data.get('proof_type', 'simulated'),
            witness_count=data.get('witness_count', 0),
        )
