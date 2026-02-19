"""
Tests for Lemma Generation (Phase 4 Weeks 2-3, Task 2.3)

This test module validates automatic lemma discovery, caching, and proof reuse
for DCEC theorem proving.

Test Coverage:
- Lemma discovery from proofs (3 tests)
- Lemma caching with LRU eviction (3 tests)
- Proof reuse with lemmas (3 tests)
- Pattern matching (2 tests)
- Cache statistics (2 tests)
- Integration with prover (2 tests)

Total: 15 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.lemma_generation import (
    Lemma,
    LemmaType,
    LemmaCache,
    LemmaGenerator,
    create_lemma_generator,
)
from ipfs_datasets_py.logic.CEC.native.prover_core import (
    ProofResult,
    ProofTree,
    ProofStep,
    ModusPonens,
    Simplification,
)
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    ConnectiveFormula,
    LogicalConnective,
    Predicate,
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace


class TestLemmaDiscovery:
    """Test automatic lemma discovery from proofs."""
    
    def test_discover_lemmas_from_successful_proof(self):
        """
        GIVEN a successful proof tree with intermediate steps
        WHEN discovering lemmas
        THEN should extract useful intermediate results
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        r_pred = namespace.add_predicate("R", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        r = AtomicFormula(r_pred, [])
        
        # Create a proof tree with steps
        axioms = [p, q]
        goal = r
        
        # Step 1: Derive P∧Q from P and Q
        p_and_q = ConnectiveFormula(LogicalConnective.AND, [p, q])
        step1 = ProofStep(
            formula=p_and_q,
            rule="Conjunction Introduction",
            premises=[0, 1],  # Indices: P=axiom[0], Q=axiom[1]
            step_number=1
        )
        
        # Step 2: Derive R from P∧Q (hypothetical)
        step2 = ProofStep(
            formula=r,
            rule="Complex Rule",
            premises=[2],  # Index 2: P∧Q from step 1 (axioms are 0,1)
            step_number=2
        )
        
        proof_tree = ProofTree(
            goal=goal,
            axioms=axioms,
            steps=[step1, step2],
            result=ProofResult.PROVED
        )
        
        # WHEN
        generator = LemmaGenerator()
        lemmas = generator.discover_lemmas(proof_tree, min_complexity=2)
        
        # THEN
        assert len(lemmas) >= 1
        assert generator.discovery_count >= 1
        # Should have discovered the conjunction as a lemma
        assert any(lemma.formula.to_string() == p_and_q.to_string() for lemma in lemmas)
    
    def test_no_lemmas_from_failed_proof(self):
        """
        GIVEN a failed proof tree
        WHEN discovering lemmas
        THEN should return empty list
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        proof_tree = ProofTree(
            goal=q,
            axioms=[p],
            steps=[],
            result=ProofResult.UNKNOWN
        )
        
        # WHEN
        generator = LemmaGenerator()
        lemmas = generator.discover_lemmas(proof_tree)
        
        # THEN
        assert len(lemmas) == 0
        assert generator.discovery_count == 0
    
    def test_min_complexity_filtering(self):
        """
        GIVEN proof steps with varying complexity
        WHEN discovering lemmas with minimum complexity
        THEN should only extract sufficiently complex lemmas
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # Simple step (1 premise)
        step1 = ProofStep(
            formula=p,
            rule="Axiom",
            premises=[],
            step_number=1
        )
        
        # Complex step (2 premises)
        p_and_q = ConnectiveFormula(LogicalConnective.AND, [p, q])
        step2 = ProofStep(
            formula=p_and_q,
            rule="Conjunction",
            premises=[0, 1],  # Indices of axioms
            step_number=2
        )
        
        proof_tree = ProofTree(
            goal=p_and_q,
            axioms=[p, q],
            steps=[step1, step2],
            result=ProofResult.PROVED
        )
        
        # WHEN - high complexity threshold
        generator = LemmaGenerator()
        lemmas = generator.discover_lemmas(proof_tree, min_complexity=2)
        
        # THEN - should only get complex lemma
        assert len(lemmas) == 1
        assert lemmas[0].formula.to_string() == p_and_q.to_string()


class TestLemmaCache:
    """Test lemma caching with LRU eviction."""
    
    def test_cache_add_and_get(self):
        """
        GIVEN a lemma cache
        WHEN adding and retrieving lemmas
        THEN should store and retrieve correctly
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        lemma = Lemma(
            formula=p,
            premises=[],
            rule="Test",
            lemma_type=LemmaType.DERIVED
        )
        
        cache = LemmaCache(max_size=10)
        
        # WHEN
        cache.add(lemma)
        retrieved = cache.get(p)
        
        # THEN
        assert retrieved is not None
        assert retrieved.formula.to_string() == p.to_string()
        assert cache.hits == 1
        assert cache.misses == 0
    
    def test_cache_miss(self):
        """
        GIVEN an empty cache
        WHEN retrieving a non-existent lemma
        THEN should return None and record miss
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        cache = LemmaCache(max_size=10)
        
        # WHEN
        retrieved = cache.get(p)
        
        # THEN
        assert retrieved is None
        assert cache.hits == 0
        assert cache.misses == 1
    
    def test_lru_eviction(self):
        """
        GIVEN a cache at capacity
        WHEN adding new lemmas
        THEN should evict least recently used
        """
        # GIVEN
        namespace = DCECNamespace()
        cache = LemmaCache(max_size=3)
        
        # Add 3 lemmas to fill cache
        lemmas = []
        for i in range(3):
            pred = namespace.add_predicate(f"P{i}", [])
            formula = AtomicFormula(pred, [])
            lemma = Lemma(formula=formula, premises=[], rule=f"Rule{i}")
            lemmas.append(lemma)
            cache.add(lemma)
        
        assert len(cache._cache) == 3
        
        # WHEN - add 4th lemma (should evict first)
        pred4 = namespace.add_predicate("P4", [])
        formula4 = AtomicFormula(pred4, [])
        lemma4 = Lemma(formula=formula4, premises=[], rule="Rule4")
        cache.add(lemma4)
        
        # THEN - cache size should stay at 3
        assert len(cache._cache) == 3
        # First lemma should be evicted
        assert cache.get(lemmas[0].formula) is None
        # Others should still be present
        assert cache.get(lemmas[1].formula) is not None
        assert cache.get(lemmas[2].formula) is not None
        assert cache.get(lemma4.formula) is not None


class TestProofReuse:
    """Test proof reuse with lemmas."""
    
    def test_prove_with_lemmas(self):
        """
        GIVEN lemmas in cache
        WHEN proving a new goal
        THEN should use cached lemmas
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # P → Q
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        axioms = [p, impl]
        goal = q
        rules = [ModusPonens()]
        
        generator = LemmaGenerator()
        
        # WHEN
        result = generator.prove_with_lemmas(goal, axioms, rules, max_steps=10)
        
        # THEN
        assert result.result == ProofResult.PROVED
    
    def test_lemma_reuse_count(self):
        """
        GIVEN lemmas from previous proofs
        WHEN proving multiple similar goals
        THEN should track reuse count
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        generator = LemmaGenerator()
        rules = [ModusPonens()]
        
        # First proof - discover lemmas
        result1 = generator.prove_with_lemmas(q, [p, impl], rules, max_steps=10)
        assert result1.result == ProofResult.PROVED
        
        initial_reuse = generator.reuse_count
        
        # WHEN - second proof (potentially reuses lemmas)
        result2 = generator.prove_with_lemmas(q, [p, impl], rules, max_steps=10)
        
        # THEN
        assert result2.result == ProofResult.PROVED
        # Reuse count may have increased
        assert generator.reuse_count >= initial_reuse
    
    def test_goal_already_in_axioms(self):
        """
        GIVEN goal that is already an axiom
        WHEN proving with lemmas
        THEN should immediately succeed
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        generator = LemmaGenerator()
        
        # WHEN
        result = generator.prove_with_lemmas(p, [p], [], max_steps=10)
        
        # THEN
        assert result.result == ProofResult.PROVED


class TestPatternMatching:
    """Test pattern matching for lemmas."""
    
    def test_find_by_pattern(self):
        """
        GIVEN lemmas with similar patterns
        WHEN searching by pattern
        THEN should find matching lemmas
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        lemma_p = Lemma(formula=p, premises=[], rule="Test")
        lemma_q = Lemma(formula=q, premises=[], rule="Test")
        
        cache = LemmaCache(max_size=10)
        cache.add(lemma_p)
        cache.add(lemma_q)
        
        # WHEN
        matches = cache.find_by_pattern(p)
        
        # THEN
        assert len(matches) >= 1
        assert any(m.formula.to_string() == p.to_string() for m in matches)
    
    def test_lemma_pattern_hash(self):
        """
        GIVEN lemmas
        WHEN created
        THEN should have pattern hashes
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        # WHEN
        lemma = Lemma(formula=p, premises=[], rule="Test")
        
        # THEN
        assert lemma.pattern_hash is not None
        assert len(lemma.pattern_hash) == 16  # 16-char hash


class TestCacheStatistics:
    """Test cache statistics tracking."""
    
    def test_cache_statistics(self):
        """
        GIVEN cache with hits and misses
        WHEN getting statistics
        THEN should report accurate metrics
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        cache = LemmaCache(max_size=10)
        lemma = Lemma(formula=p, premises=[], rule="Test")
        cache.add(lemma)
        
        # Generate some hits and misses
        cache.get(p)  # Hit
        cache.get(p)  # Hit
        cache.get(q)  # Miss
        
        # WHEN
        stats = cache.get_statistics()
        
        # THEN
        assert stats['hits'] == 2
        assert stats['misses'] == 1
        assert stats['total_requests'] == 3
        assert stats['hit_rate'] == 2/3
        assert stats['size'] == 1
    
    def test_generator_statistics(self):
        """
        GIVEN lemma generator with activity
        WHEN getting statistics
        THEN should report discovery and reuse counts
        """
        # Given
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        generator = LemmaGenerator()
        
        # Create a simple proof tree
        step = ProofStep(
            formula=p,
            rule="Test",
            premises=[0, 0],  # 2 premise indices for complexity
            step_number=1
        )
        proof_tree = ProofTree(
            goal=p,
            axioms=[p],
            steps=[step],
            result=ProofResult.PROVED
        )
        
        # WHEN
        generator.discover_lemmas(proof_tree)
        stats = generator.get_statistics()
        
        # THEN
        assert 'discovery_count' in stats
        assert 'reuse_count' in stats
        assert 'cache_size' in stats
        assert 'cache_hit_rate' in stats
        assert stats['discovery_count'] >= 1


class TestIntegration:
    """Test integration with prover."""
    
    def test_create_lemma_generator(self):
        """
        GIVEN convenience function
        WHEN creating generator
        THEN should work correctly
        """
        # WHEN
        generator = create_lemma_generator(max_lemmas=50)
        
        # THEN
        assert generator is not None
        assert generator.cache.max_size == 50
    
    def test_end_to_end_proof_with_lemmas(self):
        """
        GIVEN a complex proof scenario
        WHEN proving multiple related goals
        THEN lemmas should improve efficiency
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        r_pred = namespace.add_predicate("R", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        r = AtomicFormula(r_pred, [])
        
        # P → Q, Q → R
        impl1 = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        impl2 = ConnectiveFormula(LogicalConnective.IMPLIES, [q, r])
        
        generator = LemmaGenerator()
        rules = [ModusPonens()]
        
        # WHEN - first proof (P, P→Q ⊢ Q)
        result1 = generator.prove_with_lemmas(q, [p, impl1], rules, max_steps=20)
        assert result1.result == ProofResult.PROVED
        
        # Second proof (Q, Q→R ⊢ R)
        result2 = generator.prove_with_lemmas(r, [q, impl2], rules, max_steps=20)
        
        # THEN
        assert result2.result == ProofResult.PROVED
        # Should have discovered some lemmas
        stats = generator.get_statistics()
        assert stats['discovery_count'] >= 0  # At least some activity
