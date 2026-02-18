"""
Property-based tests for ZKP module using Hypothesis.

These tests validate key invariants hold across many generated inputs,
providing statistical confidence in correctness beyond fixed test cases.
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from ipfs_datasets_py.logic.zkp.canonicalization import (
    canonicalize_axioms,
    hash_axioms_commitment,
    hash_theorem,
    normalize_text,
)
from ipfs_datasets_py.logic.zkp.witness_manager import WitnessManager


# Strategies for generating test data
text_strategy = st.text(
    alphabet=st.characters(blacklist_categories=('Cc', 'Cs')),
    min_size=1,
    max_size=100
)

axiom_strategy = st.lists(
    st.text(
        alphabet=st.characters(blacklist_categories=('Cc', 'Cs')),
        min_size=1,
        max_size=50
    ),
    min_size=1,
    max_size=20,
    unique=True
)


class TestCanonicalityProperties:
    """Test canonicalization properties hold universally."""
    
    @given(text_strategy)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_normalization_is_idempotent(self, text):
        """Normalizing twice should equal normalizing once."""
        normalized_once = normalize_text(text)
        normalized_twice = normalize_text(normalized_once)
        
        assert normalized_once == normalized_twice
    
    @given(text_strategy)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_normalized_text_has_no_extra_whitespace(self, text):
        """Normalized text should not have consecutive spaces."""
        normalized = normalize_text(text)
        
        # Should not contain multiple consecutive spaces
        assert "  " not in normalized
        # Should not start or end with spaces
        assert not normalized.startswith(" ")
        assert not normalized.endswith(" ")
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_canonicalization_is_deterministic(self, axioms):
        """Canonicalizing same axioms twice produces identical result."""
        canonical_1 = canonicalize_axioms(axioms)
        canonical_2 = canonicalize_axioms(axioms)
        
        assert canonical_1 == canonical_2
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_canonicalization_sorted(self, axioms):
        """Canonical axioms should be sorted."""
        canonical = canonicalize_axioms(axioms)
        
        # Should equal itself when sorted
        assert canonical == sorted(canonical)
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_canonicalization_deduplicates(self, axioms):
        """Canonical axioms should have duplicates removed."""
        canonical = canonicalize_axioms(axioms)
        
        # Length should be <= original (can't add duplicates during canonicalization)
        assert len(canonical) <= len(axioms)
        # Should have no duplicates
        assert len(canonical) == len(set(canonical))
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_order_irrelevant_for_commitment(self, axioms):
        """Different orderings of same axioms produce same commitment."""
        # Generate commitment from original order
        commitment_original = hash_axioms_commitment(axioms)
        
        # Generate commitment from reversed order
        commitment_reversed = hash_axioms_commitment(list(reversed(axioms)))
        
        # Should be identical (order independent)
        assert commitment_original == commitment_reversed
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_axiom_deduplication_before_commit(self, axioms):
        """Adding duplicates shouldn't change commitment."""
        # Original commitment
        commitment_orig = hash_axioms_commitment(axioms)
        
        # Duplicate each axiom
        duplicated = []
        for axiom in axioms:
            duplicated.append(axiom)
            duplicated.append(axiom)  # Add duplicate
        
        # Commitment should be the same (duplicates removed before hashing)
        commitment_dup = hash_axioms_commitment(duplicated)
        
        assert commitment_orig == commitment_dup


class TestWitnessProperties:
    """Test witness generation properties."""
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_witness_generation_deterministic(self, axioms):
        """Generating witness twice produces same commitment."""
        manager = WitnessManager()
        
        witness_1 = manager.generate_witness(axioms=axioms, theorem="T")
        witness_2 = manager.generate_witness(axioms=axioms, theorem="T")
        
        assert witness_1.axioms_commitment_hex == witness_2.axioms_commitment_hex
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_witness_axioms_canonical(self, axioms):
        """Witness axioms are in canonical form (sorted, deduplicated)."""
        manager = WitnessManager()
        witness = manager.generate_witness(axioms=axioms, theorem="T")
        
        # Axioms should be sorted
        assert witness.axioms == sorted(witness.axioms)
        # Axioms should have no duplicates
        assert len(witness.axioms) == len(set(witness.axioms))
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_witness_count_consistent(self, axioms):
        """Witness count matches deduplicated axiom count."""
        manager = WitnessManager()
        witness = manager.generate_witness(axioms=axioms, theorem="T")
        
        unique_axioms = len(set(canonicalize_axioms(axioms)))
        assert len(witness.axioms) == unique_axioms
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_witness_commitment_stable(self, axioms):
        """Witness commitment stays stable across verifications."""
        manager = WitnessManager()
        witness = manager.generate_witness(axioms=axioms, theorem="T")
        
        commitment_1 = witness.axioms_commitment_hex
        
        # Validate it
        is_valid = manager.validate_witness(witness)
        
        commitment_2 = witness.axioms_commitment_hex
        
        # Commitment shouldn't change
        assert commitment_1 == commitment_2
        assert is_valid


class TestHashProperties:
    """Test hashing function properties."""
    
    @given(text_strategy)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_theorem_hash_deterministic(self, text):
        """Same theorem text always produces same hash."""
        hash_1 = hash_theorem(text)
        hash_2 = hash_theorem(text)
        
        assert hash_1 == hash_2
        assert isinstance(hash_1, bytes)
        assert len(hash_1) == 32  # SHA256
    
    @given(text_strategy, text_strategy)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_different_theorems_different_hashes(self, text1, text2):
        """Different theorems should (very likely) produce different hashes."""
        if text1 == text2:
            # Skip if randomly generated same text
            pytest.skip("Generated texts are identical")
        
        # Normalize since we're comparing canonicalized forms
        norm1 = normalize_text(text1)
        norm2 = normalize_text(text2)
        
        if norm1 == norm2:
            # If they normalize to same thing, hashes should be same
            hash_1 = hash_theorem(text1)
            hash_2 = hash_theorem(text2)
            assert hash_1 == hash_2
        else:
            # Different normalized forms -> different hashes (with high probability)
            hash_1 = hash_theorem(text1)
            hash_2 = hash_theorem(text2)
            # Almost certainly different (birthday paradox negligible for SHA256)
            assert hash_1 != hash_2
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_commitment_hash_deterministic(self, axioms):
        """Same axioms always produce same commitment hash."""
        commitment_1 = hash_axioms_commitment(axioms)
        commitment_2 = hash_axioms_commitment(axioms)
        
        assert commitment_1 == commitment_2
        assert isinstance(commitment_1, bytes)
        assert len(commitment_1) == 32  # SHA256


class TestInvarianceProperties:
    """Test key invariance properties hold universally."""
    
    @given(axiom_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_statement_consistency_through_witness_cycle(self, axioms):
        """Statement-witness consistency holds through full cycle."""
        manager = WitnessManager()
        theorem = "T"
        
        # Generate witness
        witness = manager.generate_witness(axioms=axioms, theorem=theorem)
        
        # Create proof statement
        proof_stmt = manager.create_proof_statement(witness, theorem)
        
        # Verify consistency
        is_consistent = manager.verify_witness_consistency(
            witness,
            proof_stmt.statement
        )
        
        assert is_consistent
    
    @given(
        st.lists(
            st.text(alphabet=st.characters(blacklist_categories=('Cc', 'Cs')), min_size=1, max_size=50),
            min_size=1,
            max_size=10
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_reordering_preserves_all_properties(self, axioms):
        """Reordering axioms preserves all witness properties."""
        manager = WitnessManager()
        theorem = "T"
        
        # Generate from original
        witness_orig = manager.generate_witness(axioms=axioms, theorem=theorem)
        
        # Generate from reversed
        witness_rev = manager.generate_witness(
            axioms=list(reversed(axioms)),
            theorem=theorem
        )
        
        # All properties should be identical
        assert witness_orig.axioms_commitment_hex == witness_rev.axioms_commitment_hex
        assert witness_orig.circuit_version == witness_rev.circuit_version
        assert witness_orig.ruleset_id == witness_rev.ruleset_id
        assert len(witness_orig.axioms) == len(witness_rev.axioms)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_single_axiom(self):
        """Single axiom should work."""
        manager = WitnessManager()
        witness = manager.generate_witness(axioms=["A"], theorem="B")
        
        assert len(witness.axioms) == 1
        assert witness.axioms[0] == "A"
    
    def test_single_character_axioms(self):
        """Single character axioms should work."""
        manager = WitnessManager()
        witness = manager.generate_witness(axioms=["P", "Q", "R"], theorem="S")
        
        assert len(witness.axioms) == 3
    
    def test_very_long_axiom(self):
        """Very long axiom text should work."""
        long_axiom = "A" * 1000
        manager = WitnessManager()
        
        witness = manager.generate_witness(axioms=[long_axiom], theorem="B")
        assert len(witness.axioms) == 1
    
    def test_many_axioms(self):
        """Many axioms should be handled."""
        many_axioms = [f"A{i}" for i in range(1000)]
        manager = WitnessManager()
        
        witness = manager.generate_witness(axioms=many_axioms, theorem="B")
        assert len(witness.axioms) == 1000
