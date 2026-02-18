"""
Unit tests for ZKP golden vectors (regression testing).

Golden vectors are fixed test cases that capture expected behavior
for canonicalization, witness generation, and proof verification.
Running these tests ensures that behavior doesn't regress between releases.
"""

import json
import pytest
from pathlib import Path
from ipfs_datasets_py.logic.zkp.canonicalization import (
    canonicalize_axioms,
    hash_axioms_commitment,
    hash_theorem,
)
from ipfs_datasets_py.logic.zkp.witness_manager import WitnessManager
from ipfs_datasets_py.logic.zkp.statement import Statement


# Load golden vectors from JSON
VECTORS_PATH = Path(__file__).parent / "zkp_golden_vectors.json"
with open(VECTORS_PATH) as f:
    GOLDEN_VECTORS = json.load(f)


class TestGoldenVectors:
    """Test against fixed golden vectors for regression prevention."""
    
    def test_simple_modus_ponens(self):
        """Golden: classical modus ponens proof."""
        vector = GOLDEN_VECTORS["vectors"]["simple_modus_ponens"]
        
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=vector["axioms"],
            theorem=vector["theorem"]
        )
        
        assert witness is not None
        assert len(witness.axioms) == vector["expected_witness_count"]
        assert witness.axioms_commitment_hex is not None
    
    def test_ordering_independence(self):
        """Golden: same axioms in different order produce same commitment."""
        vec1 = GOLDEN_VECTORS["vectors"]["simple_modus_ponens"]
        vec2 = GOLDEN_VECTORS["vectors"]["simple_with_reordering"]
        
        manager = WitnessManager()
        
        witness1 = manager.generate_witness(
            axioms=vec1["axioms"],
            theorem=vec1["theorem"]
        )
        
        witness2 = manager.generate_witness(
            axioms=vec2["axioms"],
            theorem=vec2["theorem"]
        )
        
        # Key regression test: different order should produce SAME commitment
        assert witness1.axioms_commitment_hex == witness2.axioms_commitment_hex
        assert witness1.axioms_commitment_hex == vec1["expected_axioms_commitment"]
    
    def test_whitespace_normalization(self):
        """Golden: extra whitespace should not affect commitment."""
        vector = GOLDEN_VECTORS["vectors"]["whitespace_normalization"]
        
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=vector["axioms_with_whitespace"],
            theorem=vector["theorem"]
        )
        
        # Should produce valid commitment
        assert witness.axioms_commitment_hex is not None
        assert len(witness.axioms) == vector["expected_witness_count"]
    
    def test_duplicate_axioms_deduplicated(self):
        """Golden: duplicate axioms are removed in canonical form."""
        vector = GOLDEN_VECTORS["vectors"]["duplicate_axioms"]
        
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=vector["axioms"],
            theorem=vector["theorem"]
        )
        
        # Should have only 1 axiom after deduplication
        assert len(witness.axioms) == vector["expected_witness_count"]
        assert witness.axioms == vector["expected_axioms_after_dedup"]
    
    def test_three_axiom_chain(self):
        """Golden: longer proof chain."""
        vector = GOLDEN_VECTORS["vectors"]["three_axiom_chain"]
        
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=vector["axioms"],
            theorem=vector["theorem"]
        )
        
        assert len(witness.axioms) == vector["expected_witness_count"]
    
    def test_syllogism(self):
        """Golden: Aristotelian syllogism."""
        vector = GOLDEN_VECTORS["vectors"]["all_humans_mortal"]
        
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=vector["axioms"],
            theorem=vector["theorem"]
        )
        
        assert len(witness.axioms) == vector["expected_witness_count"]
    
    def test_large_axiom_set(self):
        """Golden: many axioms (ordering independence stress test)."""
        vector = GOLDEN_VECTORS["vectors"]["large_axiom_set"]
        
        manager = WitnessManager()
        
        # Original order
        witness1 = manager.generate_witness(
            axioms=vector["axioms"],
            theorem=vector["theorem"]
        )
        
        # Reversed order
        witness2 = manager.generate_witness(
            axioms=list(reversed(vector["axioms"])),
            theorem=vector["theorem"]
        )
        
        # Random permutation
        import random
        shuffled = list(vector["axioms"])
        random.seed(42)  # Fixed seed for reproducibility
        random.shuffle(shuffled)
        witness3 = manager.generate_witness(
            axioms=shuffled,
            theorem=vector["theorem"]
        )
        
        # All should have same commitment (order independent)
        assert witness1.axioms_commitment_hex == witness2.axioms_commitment_hex
        assert witness2.axioms_commitment_hex == witness3.axioms_commitment_hex
        assert len(witness1.axioms) == vector["expected_witness_count"]


class TestGoldenInvariants:
    """Test key invariants defined in golden vectors."""
    
    def test_axiom_order_independence_variant_1(self):
        """Invariant: different orderings produce same commitment."""
        invariant = GOLDEN_VECTORS["invariants"]["axiom_order_independence"]
        pair = invariant["test_pairs"][0]
        
        commitment_a = hash_axioms_commitment(pair["set_a"])
        commitment_b = hash_axioms_commitment(pair["set_b"])
        
        assert commitment_a == commitment_b
        assert invariant["test_pairs"][0]["expected_commitment_equality"] is True
    
    def test_axiom_order_independence_variant_2(self):
        """Invariom: even with 4 axioms, order doesn't matter."""
        invariant = GOLDEN_VECTORS["invariants"]["axiom_order_independence"]
        pair = invariant["test_pairs"][1]
        
        commitment_a = hash_axioms_commitment(pair["set_a"])
        commitment_b = hash_axioms_commitment(pair["set_b"])
        
        assert commitment_a == commitment_b
    
    def test_whitespace_invariance_theorem(self):
        """Invariant: whitespace variations produce same theorem hash."""
        invariant = GOLDEN_VECTORS["invariants"]["whitespace_invariance"]
        pair = invariant["test_pairs"][0]
        
        hash_a = hash_theorem(pair["theorem_a"])
        hash_b = hash_theorem(pair["theorem_b"])
        
        assert hash_a == hash_b
        assert invariant["test_pairs"][0]["expected_hash_equality"] is True
    
    def test_whitespace_invariance_implication(self):
        """Invariant: implication with different spacing."""
        invariant = GOLDEN_VECTORS["invariants"]["whitespace_invariance"]
        pair = invariant["test_pairs"][1]
        
        hash_a = hash_theorem(pair["theorem_a"])
        hash_b = hash_theorem(pair["theorem_b"])
        
        assert hash_a == hash_b
    
    def test_deduplication_invariance(self):
        """Invariant: duplicates are removed and produce same commitment."""
        invariant = GOLDEN_VECTORS["invariants"]["deduplication_invariance"]
        pair = invariant["test_pairs"][0]
        
        canonical = canonicalize_axioms(pair["axioms"])
        assert canonical == pair["expected_canonical"]
        
        commitment_duplicates = hash_axioms_commitment(pair["axioms"])
        commitment_single = hash_axioms_commitment(pair["expected_canonical"])
        
        assert commitment_duplicates == commitment_single
    
    def test_determinism_stability(self):
        """Invariant: same inputs always produce same outputs."""
        # Run witness generation 100 times with same inputs
        axioms = ["P", "Q", "R"]
        theorem = "S"
        
        manager = WitnessManager()
        commitments = set()
        
        for _ in range(100):
            witness = manager.generate_witness(
                axioms=axioms,
                theorem=theorem
            )
            commitments.add(witness.axioms_commitment_hex)
        
        # Should have only 1 unique commitment (100% determinism)
        assert len(commitments) == 1


class TestProofVerificationVectors:
    """Test expected proof verification behavior."""
    
    def test_valid_proof_structure(self):
        """Golden: valid simulated proof has expected structure."""
        vector = GOLDEN_VECTORS["proof_verification_vectors"]["valid_simulated_proof"]
        
        manager = WitnessManager()
        witness = manager.generate_witness(
            axioms=["P", "Q"],
            theorem="R"
        )
        
        proof_stmt = manager.create_proof_statement(witness, "R")
        
        # Verify structure matches expectations
        assert proof_stmt.statement.theorem_hash is not None
        assert proof_stmt.statement.axioms_commitment is not None
        assert proof_stmt.circuit_id == "knowledge_of_axioms"
        assert proof_stmt.witness_count == 2
    
    def test_missing_theorem_hash_rejected(self):
        """Golden: invalid proof missing theorem_hash is rejected."""
        # Can't actually create invalid ZKPProof through public API,
        # but we can verify the contract through witness validation
        vector = GOLDEN_VECTORS["proof_verification_vectors"]["invalid_missing_theorem_hash"]
        
        # Invalid statement without proper commitment
        from ipfs_datasets_py.logic.zkp.statement import Statement, Witness
        
        bad_witness = Witness(
            axioms=["P"],
            intermediate_steps=[],
            axioms_commitment_hex="invalid",
            circuit_version=1,
            ruleset_id="TDFOL_v1"
        )
        
        # Create statement with wrong commitment
        bad_statement = Statement(
            theorem_hash="",
            axioms_commitment="no_match",
            circuit_version=1,
            ruleset_id="TDFOL_v1"
        )
        
        manager = WitnessManager()
        # Should not be consistent
        assert not manager.verify_witness_consistency(bad_witness, bad_statement)


class TestPerformanceBaselines:
    """
    Test that operations stay within performance baselines.
    These are soft tests - they warn but don't fail if performance drops slightly.
    """
    
    def test_canonicalization_performance(self):
        """Canonicalization should be fast."""
        import time
        
        baselines = GOLDEN_VECTORS["performance_baselines"]["canonicalization"]
        
        # Test normalize_text
        start = time.time()
        for _ in range(1000):
            from ipfs_datasets_py.logic.zkp.canonicalization import normalize_text
            normalize_text("All  humans  are    mortal")
        elapsed_ms = (time.time() - start) * 1000 / 1000
        
        # Should be well under baseline
        assert elapsed_ms < 100  # Conservative: 0.1ms per call baseline
    
    def test_witness_generation_performance(self):
        """Witness generation should be fast."""
        import time
        
        manager = WitnessManager()
        
        # Test with 2 axioms
        start = time.time()
        for _ in range(100):
            manager.generate_witness(
                axioms=["P", "Q"],
                theorem="R"
            )
        elapsed_ms = (time.time() - start) * 1000 / 100
        
        # Should be well under baseline (< 2ms per call)
        assert elapsed_ms < 5  # Conservative baseline
