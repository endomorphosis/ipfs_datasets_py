"""
Witness Management for ZKP Circuit Integration.

Manages generation, validation, and verification of witnesses in zero-knowledge
proofs. Witnesses are the private inputs to ZKP circuits that prove knowledge
of axioms without revealing them.
"""

from typing import List, Optional, Dict, Any
from .statement import Statement, Witness, ProofStatement
from .canonicalization import (
    canonicalize_axioms,
    hash_theorem,
    hash_axioms_commitment,
)
from .circuits import MVPCircuit
from .legal_theorem_semantics import derive_tdfol_v1_trace


class WitnessManager:
    """
    Manage ZKP witness generation and validation.
    
    A witness is the private knowledge that proves a theorem without revealing
    the axioms. This class handles:
    - Witness generation from axioms
    - Witness serialization/deserialization
    - Witness validation against statements
    - Commitment verification
    
    Example:
        >>> manager = WitnessManager()
        >>> witness = manager.generate_witness(
        ...     axioms=["P", "P -> Q"],
        ...     theorem="Q"
        ... )
        >>> assert manager.validate_witness(witness, expected_axiom_count=2)
    """
    
    def __init__(self):
        """Initialize witness manager."""
        self._witness_cache: Dict[str, Witness] = {}
    
    def generate_witness(
        self,
        axioms: List[str],
        theorem: str,
        intermediate_steps: Optional[List[str]] = None,
        circuit_version: int = 1,
        ruleset_id: str = "TDFOL_v1",
    ) -> Witness:
        """
        Generate a witness that proves knowledge of axioms for a theorem.
        
        The witness is the private input to the ZKP circuit. It consists of:
        - Canonicalized axioms (private)
        - Optional intermediate logical steps
        - Commitment metadata
        
        Args:
            axioms: Private axioms that prove the theorem
            theorem: The theorem to prove (public)
            intermediate_steps: Optional intermediate reasoning steps
            circuit_version: Circuit specification version
            ruleset_id: Ruleset identifier (e.g., "TDFOL_v1")
        
        Returns:
            Witness: The generated witness structure
        
        Raises:
            ValueError: If axioms are empty or invalid
        
        Example:
            >>> witness = manager.generate_witness(
            ...     axioms=["All humans are mortal", "Socrates is human"],
            ...     theorem="Socrates is mortal"
            ... )
            >>> print(f"Axiom count: {len(witness.axioms)}")
            Axiom count: 2
        """
        if not axioms:
            raise ValueError("Cannot generate witness: axioms cannot be empty")
        
        # Canonicalize axioms for consistency
        canonical_axioms = canonicalize_axioms(axioms)
        
        # Generate commitment
        axioms_commitment = hash_axioms_commitment(canonical_axioms)
        
        # Optionally derive a constraint-friendly trace for semantics circuits.
        #
        # For `circuit_version >= 2` we interpret `TDFOL_v1` as the MVP Horn
        # fragment (facts + implications) defined in `legal_theorem_semantics`.
        if circuit_version >= 2 and ruleset_id == "TDFOL_v1" and intermediate_steps is None:
            trace = derive_tdfol_v1_trace(canonical_axioms, theorem)
            intermediate_steps = trace or []

        # Create witness
        witness = Witness(
            axioms=canonical_axioms,
            theorem=theorem,
            intermediate_steps=intermediate_steps or [],
            axioms_commitment_hex=axioms_commitment.hex(),
            circuit_version=circuit_version,
            ruleset_id=ruleset_id,
        )
        
        # Cache for quick lookup
        commitment_key = axioms_commitment.hex()
        self._witness_cache[commitment_key] = witness
        
        return witness
    
    def validate_witness(
        self,
        witness: Witness,
        expected_axiom_count: Optional[int] = None,
        expected_axioms: Optional[List[str]] = None,
    ) -> bool:
        """
        Validate witness structure and properties.
        
        Args:
            witness: The witness to validate
            expected_axiom_count: Expected number of axioms (if known)
            expected_axioms: Expected axiom values (if known). Axioms are
                             compared after canonicalization.
        
        Returns:
            bool: True if witness is valid
        
        Example:
            >>> assert manager.validate_witness(
            ...     witness,
            ...     expected_axiom_count=2
            ... )
        """
        try:
            # Check basic structure
            if not hasattr(witness, 'axioms') or not witness.axioms:
                return False
            
            if not hasattr(witness, 'axioms_commitment_hex'):
                return False
            
            # Verify axiom count if provided
            if expected_axiom_count is not None:
                if len(witness.axioms) != expected_axiom_count:
                    return False
            
            # Verify axioms match expected set if provided
            if expected_axioms is not None:
                canonical_expected = canonicalize_axioms(expected_axioms)
                canonical_actual = canonicalize_axioms(witness.axioms)
                if canonical_expected != canonical_actual:
                    return False
            
            # Verify commitment is consistent
            commitment = hash_axioms_commitment(witness.axioms)
            if commitment.hex() != witness.axioms_commitment_hex:
                return False
            
            return True
            
        except (AttributeError, TypeError, ValueError):
            return False
    
    def create_proof_statement(
        self,
        witness: Witness,
        theorem: str,
        circuit_id: str = "knowledge_of_axioms",
    ) -> ProofStatement:
        """
        Create a proof statement from a witness and theorem.
        
        The proof statement combines the public statement (theorem, axioms
        commitment) with circuit metadata. This is what gets sent to the
        circuit for verification.
        
        Args:
            witness: The private witness generated from axioms
            theorem: The public theorem to prove
            circuit_id: Identifies which circuit to use
        
        Returns:
            ProofStatement: Combined public statement + circuit metadata
        
        Example:
            >>> proof_stmt = manager.create_proof_statement(witness, "Q")
            >>> assert proof_stmt.statement.theorem_hash is not None
        """
        # Generate theorem hash
        theorem_hash = hash_theorem(theorem)
        
        # Create public statement
        statement = Statement(
            theorem_hash=theorem_hash.hex(),
            axioms_commitment=witness.axioms_commitment_hex,
            circuit_version=witness.circuit_version,
            ruleset_id=witness.ruleset_id,
        )
        
        # Create proof statement with metadata
        proof_statement = ProofStatement(
            statement=statement,
            circuit_id=circuit_id,
            witness_count=len(witness.axioms),
        )
        
        return proof_statement
    
    def verify_witness_consistency(
        self,
        witness: Witness,
        statement: Statement,
    ) -> bool:
        """
        Verify that a witness is consistent with a public statement.
        
        This checks that:
        - The witness axioms hash to the statement's axioms_commitment
        - The circuit versions match
        - The ruleset IDs match
        
        Args:
            witness: The private witness
            statement: The public statement from the proof
        
        Returns:
            bool: True if witness is consistent with statement
        
        Example:
            >>> assert manager.verify_witness_consistency(witness, statement)
        """
        try:
            circuit = MVPCircuit(circuit_version=statement.circuit_version)
            return circuit.verify_constraints(witness, statement)

        except (AttributeError, TypeError, ValueError):
            return False
    
    def clear_cache(self):
        """Clear witness cache."""
        self._witness_cache.clear()
    
    def get_cached_witness(self, commitment_hex: str) -> Optional[Witness]:
        """
        Retrieve a cached witness by its axioms commitment.
        
        Args:
            commitment_hex: Hex-encoded axioms commitment
        
        Returns:
            Witness if found in cache, None otherwise
        """
        return self._witness_cache.get(commitment_hex)
