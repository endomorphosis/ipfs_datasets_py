"""
Unit tests for WitnessManager.

Tests witness generation, validation, and consistency checking.
"""

import pytest
from ipfs_datasets_py.logic.zkp.witness_manager import WitnessManager
from ipfs_datasets_py.logic.zkp.statement import Statement, Witness
from ipfs_datasets_py.logic.zkp.canonicalization import hash_axioms_commitment


class TestWitnessGeneration:
    """Test witness generation from axioms."""
    
    def test_generate_witness_basic(self):
        """Generate witness from simple axioms."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "P -> Q"],
            theorem="Q"
        )
        
        assert witness is not None
        assert len(witness.axioms) == 2
        assert "P" in witness.axioms
        assert "P -> Q" in witness.axioms
        assert witness.axioms_commitment_hex is not None
    
    def test_generate_witness_deduplicates_axioms(self):
        """Witness generation deduplicates axioms."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "P", "Q"],
            theorem="P"
        )
        
        # Should have deduplicated ["P", "Q"]
        assert len(witness.axioms) == 2
        assert set(witness.axioms) == {"P", "Q"}
    
    def test_generate_witness_sorts_axioms(self):
        """Witness generation sorts axioms consistently."""
        manager = WitnessManager()
        
        # Generate same witness with different input order
        w1 = manager.generate_witness(
            axioms=["P", "Q", "R"],
            theorem="S"
        )
        
        w2 = manager.generate_witness(
            axioms=["R", "P", "Q"],
            theorem="S"
        )
        
        # Both should have same sorted axioms
        assert w1.axioms == w2.axioms
        assert w1.axioms_commitment_hex == w2.axioms_commitment_hex
    
    def test_generate_witness_rejects_empty_axioms(self):
        """Witness generation rejects empty axiom list."""
        manager = WitnessManager()
        
        with pytest.raises(ValueError, match="axioms cannot be empty"):
            manager.generate_witness(axioms=[], theorem="Q")
    
    def test_generate_witness_includes_metadata(self):
        """Generated witness includes circuit metadata."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P"],
            theorem="Q",
            circuit_version=2,
            ruleset_id="FOL_advanced"
        )
        
        assert witness.circuit_version == 2
        assert witness.ruleset_id == "FOL_advanced"
    
    def test_generate_witness_includes_intermediate_steps(self):
        """Witness can include optional intermediate steps."""
        manager = WitnessManager()
        steps = ["P", "P -> Q", "Q"]
        
        witness = manager.generate_witness(
            axioms=["P", "P -> Q"],
            theorem="Q",
            intermediate_steps=steps
        )
        
        assert witness.intermediate_steps == steps


class TestWitnessValidation:
    """Test witness validation."""
    
    def test_validate_witness_valid(self):
        """Valid witness passes validation."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        assert manager.validate_witness(witness)
    
    def test_validate_witness_checks_structure(self):
        """Validation rejects malformed witness."""
        manager = WitnessManager()
        
        # Witness with missing axioms_commitment_hex
        bad_witness = Witness(
            axioms=["P"],
            intermediate_steps=[],
            axioms_commitment_hex=None,
            circuit_version=1,
            ruleset_id="TDFOL_v1"
        )
        
        assert not manager.validate_witness(bad_witness)
    
    def test_validate_witness_checks_axiom_count(self):
        """Validation checks expected axiom count."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        # Correct count passes
        assert manager.validate_witness(witness, expected_axiom_count=2)
        
        # Wrong count fails
        assert not manager.validate_witness(witness, expected_axiom_count=3)
    
    def test_validate_witness_checks_axiom_values(self):
        """Validation checks expected axiom values."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        # Exact match passes
        assert manager.validate_witness(
            witness,
            expected_axioms=["P", "Q"]
        )
        
        # Different order but same set passes (canonicalized)
        assert manager.validate_witness(
            witness,
            expected_axioms=["Q", "P"]
        )
        
        # Different axioms fail
        assert not manager.validate_witness(
            witness,
            expected_axioms=["P", "R"]
        )
    
    def test_validate_witness_checks_commitment(self):
        """Validation verifies axiom commitment is consistent."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        # Verify commitment is correct
        expected_commitment = hash_axioms_commitment(witness.axioms)
        assert witness.axioms_commitment_hex == expected_commitment.hex()
        
        # Should validate successfully
        assert manager.validate_witness(witness)


class TestProofStatementCreation:
    """Test creating proof statements from witnesses."""
    
    def test_create_proof_statement(self):
        """Create proof statement from witness."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        proof_stmt = manager.create_proof_statement(witness, theorem="R")
        
        assert proof_stmt is not None
        assert proof_stmt.statement is not None
        assert proof_stmt.circuit_id == "knowledge_of_axioms"
        assert proof_stmt.witness_count == 2
    
    def test_proof_statement_includes_theorem_hash(self):
        """Proof statement includes hash of theorem."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P"],
            theorem="Q"
        )
        
        proof_stmt = manager.create_proof_statement(witness, theorem="Q")
        
        assert proof_stmt.statement.theorem_hash is not None
        # Hash should be hex-encoded
        assert isinstance(proof_stmt.statement.theorem_hash, str)
        assert len(proof_stmt.statement.theorem_hash) == 64  # SHA256 hex
    
    def test_proof_statement_includes_axioms_commitment(self):
        """Proof statement includes axioms commitment."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        proof_stmt = manager.create_proof_statement(witness, theorem="R")
        
        assert proof_stmt.statement.axioms_commitment == witness.axioms_commitment_hex
    
    def test_proof_statement_custom_circuit_id(self):
        """Proof statement can use custom circuit ID."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P"],
            theorem="Q"
        )
        
        proof_stmt = manager.create_proof_statement(
            witness,
            theorem="Q",
            circuit_id="custom_circuit"
        )
        
        assert proof_stmt.circuit_id == "custom_circuit"


class TestWitnessConsistency:
    """Test witness-statement consistency verification."""
    
    def test_verify_witness_consistency_valid(self):
        """Valid witness-statement pair passes consistency check."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        proof_stmt = manager.create_proof_statement(witness, "R")
        statement = proof_stmt.statement
        
        assert manager.verify_witness_consistency(witness, statement)
    
    def test_verify_witness_consistency_commitment_mismatch(self):
        """Consistency check fails on commitment mismatch."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P"],
            theorem="Q"
        )
        
        # Create statement with wrong commitment
        statement = Statement(
            theorem_hash="abc123",
            axioms_commitment="wrong_commitment",
            circuit_version=1,
            ruleset_id="TDFOL_v1"
        )
        
        assert not manager.verify_witness_consistency(witness, statement)
    
    def test_verify_witness_consistency_version_mismatch(self):
        """Consistency check fails on circuit version mismatch."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P"],
            theorem="Q",
            circuit_version=1
        )
        
        # Create statement with different version
        commitment = hash_axioms_commitment(witness.axioms)
        statement = Statement(
            theorem_hash="abc123",
            axioms_commitment=commitment.hex(),
            circuit_version=2,  # Different!
            ruleset_id="TDFOL_v1"
        )
        
        assert not manager.verify_witness_consistency(witness, statement)
    
    def test_verify_witness_consistency_ruleset_mismatch(self):
        """Consistency check fails on ruleset mismatch."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P"],
            theorem="Q",
            ruleset_id="TDFOL_v1"
        )
        
        # Create statement with different ruleset
        commitment = hash_axioms_commitment(witness.axioms)
        statement = Statement(
            theorem_hash="abc123",
            axioms_commitment=commitment.hex(),
            circuit_version=1,
            ruleset_id="FOL_advanced"  # Different!
        )
        
        assert not manager.verify_witness_consistency(witness, statement)


class TestWitnessCache:
    """Test witness caching."""
    
    def test_witness_cached_after_generation(self):
        """Generated witnesses are cached by commitment."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        # Should be retrievable from cache
        cached = manager.get_cached_witness(witness.axioms_commitment_hex)
        assert cached is not None
        assert cached.axioms == witness.axioms
    
    def test_cache_retrieval_miss(self):
        """Cache returns None for non-existent commitment."""
        manager = WitnessManager()
        
        result = manager.get_cached_witness("nonexistent")
        assert result is None
    
    def test_clear_cache(self):
        """Cache can be cleared."""
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P"],
            theorem="Q"
        )
        
        # Cache should have witness
        assert manager.get_cached_witness(witness.axioms_commitment_hex) is not None
        
        # Clear cache
        manager.clear_cache()
        
        # Cache should be empty
        assert manager.get_cached_witness(witness.axioms_commitment_hex) is None
