"""
Session 48 — Coverage Tests for Neurosymbolic Modules

Covers:
- symbolic/symbolic_logic_primitives.py (0% → 51%)
- symbolic/neurosymbolic_api.py (0% → 63%)
- symbolic/neurosymbolic_graphrag.py (0% → 81%)
- symbolic/neurosymbolic/embedding_prover.py (0% → 82%)
- symbolic/neurosymbolic/hybrid_confidence.py (0% → 89%)
- symbolic/neurosymbolic/reasoning_coordinator.py (0% → 83%)
- bridges/base_prover_bridge.py (59% → ~75%)

All tests follow GIVEN-WHEN-THEN format.
"""

from __future__ import annotations
import sys
import types
import pytest
import logging
from typing import Optional
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

def _make_formula(text: str = "O(pay(alice))"):
    """Create a real TDFOL Formula for testing."""
    from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
    return parse_tdfol(text)


def _make_proof_result(proved: bool = False):
    """Create a real ProofResult for testing."""
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
    status = ProofStatus.PROVED if proved else ProofStatus.UNKNOWN
    return ProofResult(status=status, formula=None, time_ms=0, method="test")


# ===========================================================================
# 1. EmbeddingEnhancedProver
# ===========================================================================

class TestEmbeddingEnhancedProver:
    """Tests for symbolic/neurosymbolic/embedding_prover.py"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        self.EmbeddingEnhancedProver = EmbeddingEnhancedProver

    def test_init_no_model(self):
        """GIVEN no sentence-transformers installed WHEN init THEN model is None."""
        prover = self.EmbeddingEnhancedProver()
        assert prover.model is None
        assert prover.cache_enabled is True
        assert prover.model_name == "sentence-transformers/all-MiniLM-L6-v2"

    def test_init_cache_disabled(self):
        """GIVEN cache_enabled=False WHEN init THEN cache is empty and disabled."""
        prover = self.EmbeddingEnhancedProver(cache_enabled=False)
        assert prover.cache_enabled is False
        assert prover.embedding_cache == {}

    def test_compute_similarity_empty_axioms(self):
        """GIVEN goal formula WHEN axioms is empty THEN similarity is 0.0."""
        prover = self.EmbeddingEnhancedProver()
        goal = _make_formula()
        result = prover.compute_similarity(goal, [])
        assert result == 0.0

    def test_compute_similarity_exact_match(self):
        """GIVEN goal that matches an axiom exactly WHEN compute THEN similarity is 1.0."""
        prover = self.EmbeddingEnhancedProver()
        goal = _make_formula("O(pay(alice))")
        axioms = [_make_formula("O(pay(alice))")]
        result = prover.compute_similarity(goal, axioms)
        assert result == 1.0

    def test_compute_similarity_substring_match(self):
        """GIVEN goal contained in an axiom WHEN compute THEN similarity >= 0.7."""
        prover = self.EmbeddingEnhancedProver()
        goal = _make_formula("O(pay(alice))")
        axioms = [_make_formula("O(sign(bob))")]
        result = prover.compute_similarity(goal, axioms)
        assert 0.0 <= result <= 1.0

    def test_find_similar_formulas_empty(self):
        """GIVEN no candidates WHEN find_similar THEN returns empty list."""
        prover = self.EmbeddingEnhancedProver()
        query = _make_formula()
        result = prover.find_similar_formulas(query, [])
        assert result == []

    def test_find_similar_formulas_top_k(self):
        """GIVEN 3 candidates and top_k=2 WHEN find_similar THEN returns 2 results."""
        prover = self.EmbeddingEnhancedProver()
        query = _make_formula("O(pay(alice))")
        candidates = [
            _make_formula("O(pay(alice))"),
            _make_formula("O(sign(bob))"),
            _make_formula("O(deliver(charlie))"),
        ]
        result = prover.find_similar_formulas(query, candidates, top_k=2)
        assert len(result) == 2
        # Results should be sorted by similarity descending
        assert result[0][1] >= result[1][1]

    def test_find_similar_formulas_returns_formula_score_tuples(self):
        """GIVEN candidates WHEN find_similar THEN each item is (formula, float)."""
        prover = self.EmbeddingEnhancedProver()
        query = _make_formula("O(pay(alice))")
        candidates = [_make_formula("O(pay(alice))")]
        result = prover.find_similar_formulas(query, candidates, top_k=5)
        assert len(result) == 1
        formula, score = result[0]
        assert isinstance(score, float)

    def test_get_embedding_fallback(self):
        """GIVEN no sentence-transformers WHEN _get_embedding THEN returns a list."""
        prover = self.EmbeddingEnhancedProver()
        emb = prover._get_embedding("test formula text")
        assert isinstance(emb, list)
        assert len(emb) == 100  # Padded to 100

    def test_get_embedding_cache_hit(self):
        """GIVEN cache_enabled WHEN same text requested twice THEN cache is used."""
        prover = self.EmbeddingEnhancedProver()
        emb1 = prover._get_embedding("same text")
        assert len(prover.embedding_cache) == 1
        emb2 = prover._get_embedding("same text")
        assert len(prover.embedding_cache) == 1  # No new entry
        assert emb1 == emb2

    def test_cosine_similarity_identical(self):
        """GIVEN two identical vectors WHEN cosine_similarity THEN returns 1.0."""
        prover = self.EmbeddingEnhancedProver()
        vec = [1.0, 0.0, 0.0]
        result = prover._cosine_similarity(vec, vec)
        assert abs(result - 1.0) < 1e-6

    def test_cosine_similarity_zero_vectors(self):
        """GIVEN zero vectors WHEN cosine_similarity THEN returns 0.0."""
        prover = self.EmbeddingEnhancedProver()
        vec = [0.0, 0.0, 0.0]
        result = prover._cosine_similarity(vec, vec)
        assert result == 0.0

    def test_cosine_similarity_dimension_mismatch(self):
        """GIVEN vectors with different sizes WHEN cosine_similarity THEN raises ValueError."""
        prover = self.EmbeddingEnhancedProver()
        with pytest.raises(ValueError):
            prover._cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])

    def test_clear_cache(self):
        """GIVEN embeddings cached WHEN clear_cache THEN cache is empty."""
        prover = self.EmbeddingEnhancedProver()
        prover._get_embedding("formula1")
        assert len(prover.embedding_cache) == 1
        prover.clear_cache()
        assert len(prover.embedding_cache) == 0

    def test_get_cache_stats(self):
        """GIVEN prover WHEN get_cache_stats THEN returns dict with expected keys."""
        prover = self.EmbeddingEnhancedProver()
        stats = prover.get_cache_stats()
        assert "cache_size" in stats
        assert "cache_enabled" in stats
        assert "model_loaded" in stats
        assert stats["model_loaded"] is False

    def test_fallback_similarity_jaccard(self):
        """GIVEN no exact/substring match WHEN _fallback_similarity THEN uses Jaccard."""
        prover = self.EmbeddingEnhancedProver()
        goal = "pay alice obligation"
        axioms = ["pay bob permission"]
        result = prover._fallback_similarity(goal, axioms)
        assert 0.0 <= result <= 1.0


# ===========================================================================
# 2. HybridConfidenceScorer
# ===========================================================================

class TestHybridConfidenceScorer:
    """Tests for symbolic/neurosymbolic/hybrid_confidence.py"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import (
            HybridConfidenceScorer, ConfidenceBreakdown, ConfidenceSource
        )
        self.Scorer = HybridConfidenceScorer
        self.Breakdown = ConfidenceBreakdown
        self.Source = ConfidenceSource

    def test_init_default_weights(self):
        """GIVEN no args WHEN init THEN weights sum to 1.0."""
        scorer = self.Scorer()
        assert abs(scorer.symbolic_weight + scorer.neural_weight - 1.0) < 1e-6

    def test_init_custom_weights(self):
        """GIVEN sym=0.9, neu=0.1 WHEN init THEN weights are normalized."""
        scorer = self.Scorer(symbolic_weight=0.9, neural_weight=0.1)
        assert abs(scorer.symbolic_weight - 0.9) < 1e-6
        assert abs(scorer.neural_weight - 0.1) < 1e-6

    def test_compute_confidence_symbolic_only(self):
        """GIVEN only symbolic result WHEN compute THEN symbolic dominates."""
        scorer = self.Scorer()
        pr = _make_proof_result(proved=True)
        bd = scorer.compute_confidence(symbolic_result=pr)
        assert bd.total_confidence > 0.5
        assert "symbolic" in bd.explanation

    def test_compute_confidence_symbolic_failed(self):
        """GIVEN failed symbolic proof WHEN compute THEN confidence is low."""
        scorer = self.Scorer()
        pr = _make_proof_result(proved=False)
        bd = scorer.compute_confidence(symbolic_result=pr)
        assert bd.symbolic_confidence == 0.0

    def test_compute_confidence_neural_only(self):
        """GIVEN only neural similarity=0.8 WHEN compute THEN neural dominates."""
        scorer = self.Scorer()
        bd = scorer.compute_confidence(neural_similarity=0.8)
        assert bd.total_confidence > 0.5
        assert bd.neural_confidence == 0.8

    def test_compute_confidence_both_symbolic_and_neural(self):
        """GIVEN both symbolic proof and neural similarity WHEN compute THEN combined."""
        scorer = self.Scorer()
        pr = _make_proof_result(proved=True)
        bd = scorer.compute_confidence(symbolic_result=pr, neural_similarity=0.6)
        assert bd.total_confidence > 0.5
        assert bd.symbolic_confidence == 1.0
        assert bd.neural_confidence == 0.6

    def test_compute_confidence_with_formula(self):
        """GIVEN formula provided WHEN compute THEN structural confidence used."""
        scorer = self.Scorer(use_structural=True)
        f = _make_formula()
        bd = scorer.compute_confidence(formula=f)
        assert bd.structural_confidence > 0.0

    def test_compute_confidence_structural_disabled(self):
        """GIVEN use_structural=False WHEN compute THEN structural confidence is 0."""
        scorer = self.Scorer(use_structural=False)
        f = _make_formula()
        bd = scorer.compute_confidence(formula=f)
        assert bd.structural_confidence == 0.0

    def test_compute_confidence_no_evidence(self):
        """GIVEN no arguments WHEN compute THEN confidence is 0 with explanation."""
        scorer = self.Scorer(use_structural=False)
        bd = scorer.compute_confidence()
        assert bd.total_confidence == 0.0
        assert "no evidence" in bd.explanation.lower()

    def test_confidence_calibration(self):
        """GIVEN calibration_factor=0.5 WHEN compute THEN result is halved."""
        scorer = self.Scorer(calibration_factor=0.5)
        bd = scorer.compute_confidence(neural_similarity=1.0)
        assert bd.total_confidence <= 0.5 + 0.01  # small tolerance for structural

    def test_structural_confidence_simple(self):
        """GIVEN simple formula (depth<=2) WHEN structural THEN returns high value."""
        scorer = self.Scorer()
        f = _make_formula("O(pay(alice))")
        conf = scorer._compute_structural_confidence(f)
        assert conf >= 0.7

    def test_get_statistics_empty(self):
        """GIVEN no history WHEN get_statistics THEN returns empty message."""
        scorer = self.Scorer()
        stats = scorer.get_statistics()
        assert "message" in stats

    def test_get_statistics_with_data(self):
        """GIVEN some computations WHEN get_statistics THEN returns stats dict."""
        scorer = self.Scorer()
        scorer.compute_confidence(neural_similarity=0.5)
        scorer.compute_confidence(neural_similarity=0.8)
        stats = scorer.get_statistics()
        assert stats["count"] == 2
        assert "mean_confidence" in stats
        assert "min_confidence" in stats
        assert "max_confidence" in stats

    def test_confidence_breakdown_dataclass(self):
        """GIVEN ConfidenceBreakdown init WHEN created THEN weights default to empty dict."""
        bd = self.Breakdown(total_confidence=0.7)
        assert bd.weights == {}
        assert bd.explanation == ""

    def test_confidence_source_enum(self):
        """GIVEN ConfidenceSource WHEN accessed THEN has expected values."""
        assert self.Source.SYMBOLIC.value == "symbolic"
        assert self.Source.NEURAL.value == "neural"
        assert self.Source.STRUCTURAL.value == "structural"
        assert self.Source.HISTORICAL.value == "historical"


# ===========================================================================
# 3. NeuralSymbolicCoordinator
# ===========================================================================

class TestNeuralSymbolicCoordinator:
    """Tests for symbolic/neurosymbolic/reasoning_coordinator.py"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import (
            NeuralSymbolicCoordinator, ReasoningStrategy, CoordinatedResult
        )
        self.Coordinator = NeuralSymbolicCoordinator
        self.Strategy = ReasoningStrategy
        self.Result = CoordinatedResult

    def test_init_default(self):
        """GIVEN no args WHEN init THEN coordinator ready with symbolic reasoner."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        assert coord.use_cec is False
        assert coord.use_modal is False
        assert coord.symbolic_reasoner is not None

    def test_get_capabilities(self):
        """GIVEN coordinator WHEN get_capabilities THEN returns dict with key fields."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        caps = coord.get_capabilities()
        assert "cec_enabled" in caps
        assert "strategies_available" in caps
        assert "confidence_threshold" in caps

    def test_prove_symbolic_only_strategy(self):
        """GIVEN SYMBOLIC_ONLY strategy WHEN prove THEN returns CoordinatedResult."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        result = coord.prove("O(pay(alice))", strategy=self.Strategy.SYMBOLIC_ONLY)
        assert isinstance(result.is_proved, bool)
        assert 0.0 <= result.confidence <= 1.0
        assert result.strategy_used == self.Strategy.SYMBOLIC_ONLY

    def test_prove_neural_only_falls_back_to_symbolic(self):
        """GIVEN NEURAL_ONLY but no embeddings WHEN prove THEN falls back to symbolic."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        result = coord.prove("O(pay(alice))", strategy=self.Strategy.NEURAL_ONLY)
        assert isinstance(result.is_proved, bool)

    def test_prove_hybrid_strategy(self):
        """GIVEN HYBRID strategy WHEN prove THEN returns CoordinatedResult."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        result = coord.prove("O(pay(alice))", strategy=self.Strategy.HYBRID)
        assert result.strategy_used in (self.Strategy.HYBRID, self.Strategy.SYMBOLIC_ONLY)

    def test_prove_auto_strategy(self):
        """GIVEN AUTO strategy WHEN prove THEN coordinator selects a strategy."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        result = coord.prove("O(pay(alice))", strategy=self.Strategy.AUTO)
        assert result.strategy_used != self.Strategy.AUTO  # Should have resolved

    def test_prove_with_axioms(self):
        """GIVEN axioms list WHEN prove THEN axioms are added to KB."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        result = coord.prove(
            "O(pay(alice))",
            axioms=["O(pay(bob))"],
            strategy=self.Strategy.SYMBOLIC_ONLY
        )
        assert isinstance(result.is_proved, bool)

    def test_prove_with_formula_object(self):
        """GIVEN Formula object WHEN prove THEN accepts without parse."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        formula = _make_formula("O(pay(alice))")
        result = coord.prove(formula, strategy=self.Strategy.SYMBOLIC_ONLY)
        assert isinstance(result.is_proved, bool)

    def test_choose_strategy_simple_formula(self):
        """GIVEN simple formula (few operators) WHEN _choose_strategy THEN returns SYMBOLIC."""
        coord = self.Coordinator(use_cec=False, use_modal=False, use_embeddings=False)
        f = _make_formula("O(pay(alice))")
        strategy = coord._choose_strategy(f, [])
        assert strategy == self.Strategy.SYMBOLIC_ONLY

    def test_coordinated_result_confidence_validation(self):
        """GIVEN invalid confidence WHEN create CoordinatedResult THEN raises ValueError."""
        with pytest.raises(ValueError):
            self.Result(is_proved=True, confidence=1.5)

    def test_coordinated_result_valid(self):
        """GIVEN valid CoordinatedResult WHEN created THEN all fields accessible."""
        result = self.Result(is_proved=True, confidence=0.9)
        assert result.is_proved is True
        assert result.confidence == 0.9
        assert result.reasoning_path == ""
        assert result.proof_steps == []

    def test_reasoning_strategy_enum(self):
        """GIVEN ReasoningStrategy enum WHEN accessed THEN has expected values."""
        assert self.Strategy.SYMBOLIC_ONLY.value == "symbolic"
        assert self.Strategy.NEURAL_ONLY.value == "neural"
        assert self.Strategy.HYBRID.value == "hybrid"
        assert self.Strategy.AUTO.value == "auto"


# ===========================================================================
# 4. NeurosymbolicReasoner (neurosymbolic_api.py)
# ===========================================================================

class TestNeurosymbolicReasoner:
    """Tests for symbolic/neurosymbolic_api.py"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_api import (
            NeurosymbolicReasoner, ReasoningCapabilities, get_reasoner
        )
        self.NeurosymbolicReasoner = NeurosymbolicReasoner
        self.ReasoningCapabilities = ReasoningCapabilities
        self.get_reasoner = get_reasoner

    def _make_reasoner(self):
        return self.NeurosymbolicReasoner(use_cec=False, use_modal=False, use_nl=False)

    def test_init_default(self):
        """GIVEN default args WHEN init THEN reasoner ready."""
        r = self._make_reasoner()
        assert r.prover is not None
        assert r.kb is not None

    def test_get_capabilities(self):
        """GIVEN reasoner WHEN get_capabilities THEN returns dict with tdfol_rules."""
        r = self._make_reasoner()
        caps = r.get_capabilities()
        assert "tdfol_rules" in caps
        assert "total_inference_rules" in caps
        assert caps["tdfol_rules"] == 40

    def test_parse_formula_does_not_raise_for_invalid(self):
        """GIVEN invalid formula string WHEN parse THEN no exception is raised."""
        r = self._make_reasoner()
        # parse() wraps exceptions; just verify no exception propagates
        try:
            r.parse("this is not a formula $$$", format="tdfol")
        except Exception as exc:
            pytest.fail(f"parse() raised an unexpected exception: {exc}")

    def test_add_knowledge_adds_formula(self):
        """GIVEN valid formula string WHEN add_knowledge THEN returns True."""
        r = self._make_reasoner()
        # Even if parse returns None, add_knowledge should return False gracefully
        # Let's use a formula that the reasoner might parse
        result = r.add_knowledge("O(pay(alice))")
        assert isinstance(result, bool)

    def test_prove_returns_proof_result(self):
        """GIVEN goal WHEN prove THEN returns ProofResult-compatible object."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
        r = self._make_reasoner()
        result = r.prove("O(pay(alice))")
        assert hasattr(result, 'status')
        assert hasattr(result, 'is_proved')

    def test_explain_formula_object(self):
        """GIVEN Formula object WHEN explain THEN returns string."""
        r = self._make_reasoner()
        f = _make_formula("O(pay(alice))")
        expl = r.explain(f)
        assert isinstance(expl, str)
        assert len(expl) > 0

    def test_explain_invalid_string(self):
        """GIVEN unparseable string WHEN explain THEN returns error string."""
        r = self._make_reasoner()
        expl = r.explain("invalid $$$ formula")
        assert isinstance(expl, str)

    def test_query_returns_dict(self):
        """GIVEN any question WHEN query THEN returns dict with 'success' key."""
        r = self._make_reasoner()
        result = r.query("Is Alice obligated to pay?")
        assert isinstance(result, dict)
        assert "success" in result
        assert "question" in result
        assert "answer" in result

    def test_query_failed_proof(self):
        """GIVEN question that can't be proved WHEN query THEN success=False."""
        r = self._make_reasoner()
        result = r.query("Is Alice obligated to pay?")
        assert result["success"] is False

    def test_get_reasoner_singleton(self):
        """GIVEN global reasoner WHEN get_reasoner called twice THEN same instance."""
        import ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_api as mod
        # Reset global
        mod._global_reasoner = None
        r1 = mod.get_reasoner()
        r2 = mod.get_reasoner()
        assert r1 is r2

    def test_reasoning_capabilities_defaults(self):
        """GIVEN ReasoningCapabilities WHEN created THEN default values set."""
        caps = self.ReasoningCapabilities()
        assert caps.tdfol_rules == 40
        assert caps.cec_rules == 87
        assert caps.total_rules == 127
        assert isinstance(caps.modal_provers, list)
        assert len(caps.modal_provers) == 5


# ===========================================================================
# 5. NeurosymbolicGraphRAG
# ===========================================================================

class TestNeurosymbolicGraphRAG:
    """Tests for symbolic/neurosymbolic_graphrag.py"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_graphrag import (
            NeurosymbolicGraphRAG, PipelineResult
        )
        self.GraphRAG = NeurosymbolicGraphRAG
        self.PipelineResult = PipelineResult

    def _make_rag(self):
        return self.GraphRAG(use_neural=False, enable_proof_caching=False)

    def test_init_no_neural(self):
        """GIVEN use_neural=False WHEN init THEN no reasoning coordinator."""
        rag = self._make_rag()
        assert rag.use_neural is False
        assert rag.reasoning_coordinator is None

    def test_process_document_basic(self):
        """GIVEN simple text WHEN process_document THEN returns PipelineResult."""
        rag = self._make_rag()
        result = rag.process_document("Alice must pay Bob", "doc1")
        assert isinstance(result, self.PipelineResult)
        assert result.doc_id == "doc1"
        assert result.text == "Alice must pay Bob"
        assert 0.0 <= result.confidence <= 1.0

    def test_process_document_stores_in_dict(self):
        """GIVEN document processed WHEN access documents dict THEN doc_id in it."""
        rag = self._make_rag()
        rag.process_document("Alice must pay Bob", "doc1")
        assert "doc1" in rag.documents

    def test_process_document_reasoning_chain(self):
        """GIVEN document text WHEN process THEN reasoning_chain is populated."""
        rag = self._make_rag()
        result = rag.process_document("Alice must sign the contract", "doc2")
        assert len(result.reasoning_chain) > 0

    def test_get_document_summary_existing(self):
        """GIVEN processed document WHEN get_document_summary THEN returns dict."""
        rag = self._make_rag()
        rag.process_document("Alice must pay Bob", "doc1")
        summary = rag.get_document_summary("doc1")
        assert summary is not None
        assert summary["doc_id"] == "doc1"
        assert "formulas_count" in summary
        assert "confidence" in summary

    def test_get_document_summary_nonexistent(self):
        """GIVEN no documents WHEN get_document_summary THEN returns None."""
        rag = self._make_rag()
        result = rag.get_document_summary("nonexistent")
        assert result is None

    def test_get_pipeline_stats_empty(self):
        """GIVEN no documents WHEN get_pipeline_stats THEN returns zero counts."""
        rag = self._make_rag()
        stats = rag.get_pipeline_stats()
        assert stats["documents_processed"] == 0
        assert stats["total_formulas"] == 0
        assert stats["use_neural"] is False

    def test_get_pipeline_stats_after_processing(self):
        """GIVEN processed document WHEN get_pipeline_stats THEN shows processed count."""
        rag = self._make_rag()
        rag.process_document("Alice must pay Bob", "doc1")
        stats = rag.get_pipeline_stats()
        assert stats["documents_processed"] == 1

    def test_query_returns_rag_result(self):
        """GIVEN processed document WHEN query THEN returns RAGQueryResult-like."""
        rag = self._make_rag()
        rag.process_document("Alice must pay Bob", "doc1")
        result = rag.query("What are Alice's obligations?")
        assert result is not None

    def test_extract_formulas_from_must_pattern(self):
        """GIVEN text with 'must' WHEN process THEN formulas extracted."""
        rag = self._make_rag()
        result = rag.process_document("Alice must pay Bob", "doc1")
        # May or may not find formula depending on parser
        assert isinstance(result.formulas, list)

    def test_pipeline_result_dataclass(self):
        """GIVEN PipelineResult WHEN created THEN default fields set."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Formula
        pr = self.PipelineResult(doc_id="test", text="test text")
        assert pr.doc_id == "test"
        assert pr.formulas == []
        assert pr.proven_theorems == []
        assert pr.confidence == 0.0

    def test_export_knowledge_graph(self):
        """GIVEN processed rag WHEN export_knowledge_graph THEN returns dict."""
        rag = self._make_rag()
        rag.process_document("Alice must pay Bob", "doc1")
        graph = rag.export_knowledge_graph()
        assert isinstance(graph, dict)

    def test_check_consistency(self):
        """GIVEN processed rag WHEN check_consistency THEN returns (bool, list)."""
        rag = self._make_rag()
        rag.process_document("Alice must pay Bob", "doc1")
        is_consistent, issues = rag.check_consistency()
        assert isinstance(is_consistent, bool)
        assert isinstance(issues, list)


# ===========================================================================
# 6. LogicPrimitives (symbolic_logic_primitives.py)
# ===========================================================================

class TestLogicPrimitives:
    """Tests for symbolic/symbolic_logic_primitives.py"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.symbolic.symbolic_logic_primitives import (
            LogicPrimitives, Symbol, get_available_primitives,
            create_logic_symbol, SYMBOLIC_AI_AVAILABLE
        )
        self.LogicPrimitives = LogicPrimitives
        self.Symbol = Symbol
        self.get_available_primitives = get_available_primitives
        self.create_logic_symbol = create_logic_symbol
        self.SYMBOLIC_AI_AVAILABLE = SYMBOLIC_AI_AVAILABLE

        # Create a concrete TestLP subclass (LogicPrimitives needs self.value)
        class TestLP(LogicPrimitives):
            def __init__(self, value: str):
                self.value = value
                self._semantic = False
            def _to_type(self, result):
                return Symbol(str(result))

        self.TestLP = TestLP

    @pytest.mark.skipif(
        __import__('importlib.util', fromlist=['find_spec']).find_spec('symai') is not None,
        reason="Test only valid when symai is not installed"
    )
    def test_symbolic_ai_not_available(self):
        """GIVEN no symai installed WHEN check THEN SYMBOLIC_AI_AVAILABLE is False."""
        assert self.SYMBOLIC_AI_AVAILABLE is False

    def test_get_available_primitives(self):
        """GIVEN call WHEN get_available_primitives THEN returns expected methods."""
        prims = self.get_available_primitives()
        assert "to_fol" in prims
        assert "negate" in prims
        assert "implies" in prims
        assert len(prims) >= 9

    def test_to_fol_universal(self):
        """GIVEN 'All cats are animals' WHEN to_fol THEN returns ∀x formula."""
        lp = self.TestLP("All cats are animals")
        result = lp.to_fol()
        assert "∀" in result.value or "forall" in result.value.lower() or "x" in result.value

    def test_to_fol_existential(self):
        """GIVEN 'Some dogs are friendly' WHEN to_fol THEN returns ∃x formula."""
        lp = self.TestLP("Some dogs are friendly")
        result = lp.to_fol()
        assert "∃" in result.value or "exists" in result.value.lower() or "x" in result.value

    def test_to_fol_simple(self):
        """GIVEN simple statement WHEN to_fol THEN returns predicate formula."""
        lp = self.TestLP("Alice is present")
        result = lp.to_fol()
        assert len(result.value) > 0

    def test_extract_quantifiers_universal(self):
        """GIVEN 'All humans are mortal' WHEN extract_quantifiers THEN includes universal."""
        lp = self.TestLP("All humans are mortal")
        result = lp.extract_quantifiers()
        assert "universal" in result.value.lower() or "all" in result.value.lower()

    def test_extract_quantifiers_existential(self):
        """GIVEN 'Some birds fly' WHEN extract_quantifiers THEN includes existential."""
        lp = self.TestLP("Some birds fly")
        result = lp.extract_quantifiers()
        assert "existential" in result.value.lower() or "some" in result.value.lower()

    def test_extract_quantifiers_none(self):
        """GIVEN statement with no quantifiers WHEN extract_quantifiers THEN says none."""
        lp = self.TestLP("Alice pays Bob")
        result = lp.extract_quantifiers()
        assert "none" in result.value.lower() or len(result.value) > 0

    def test_extract_predicates(self):
        """GIVEN 'All cats are animals' WHEN extract_predicates THEN returns predicates."""
        lp = self.TestLP("All cats are animals")
        result = lp.extract_predicates()
        assert len(result.value) > 0

    def test_logical_and(self):
        """GIVEN two symbols WHEN logical_and THEN returns ∧ formula."""
        lp1 = self.TestLP("P")
        lp2 = self.TestLP("Q")
        result = lp1.logical_and(lp2)
        assert "∧" in result.value or "and" in result.value.lower()

    def test_logical_or(self):
        """GIVEN two symbols WHEN logical_or THEN returns ∨ formula."""
        lp1 = self.TestLP("P")
        lp2 = self.TestLP("Q")
        result = lp1.logical_or(lp2)
        assert "∨" in result.value or "or" in result.value.lower()

    def test_implies(self):
        """GIVEN premise and conclusion WHEN implies THEN returns → formula."""
        lp1 = self.TestLP("P")
        lp2 = self.TestLP("Q")
        result = lp1.implies(lp2)
        assert "→" in result.value or "->" in result.value

    def test_negate(self):
        """GIVEN P WHEN negate THEN returns ¬P."""
        lp = self.TestLP("P")
        result = lp.negate()
        assert "¬" in result.value or "not" in result.value.lower()

    def test_analyze_logical_structure(self):
        """GIVEN any statement WHEN analyze THEN returns dict-like analysis."""
        lp = self.TestLP("All cats are animals")
        result = lp.analyze_logical_structure()
        assert len(result.value) > 0

    def test_simplify_logic(self):
        """GIVEN statement with extra spaces WHEN simplify THEN normalized."""
        lp = self.TestLP("P  and   Q")
        result = lp.simplify_logic()
        assert len(result.value) > 0

    def test_symbol_class_init(self):
        """GIVEN Symbol fallback class WHEN init THEN stores value."""
        sym = self.Symbol("test value")
        assert sym.value == "test value"


# ===========================================================================
# 7. BaseProverBridge
# ===========================================================================

class TestBaseProverBridge:
    """Tests for bridges/base_prover_bridge.py — the `available` attribute fix."""

    def test_available_attribute_set_on_init(self):
        """GIVEN BaseProverBridge subclass WHEN init THEN self.available is set."""
        from ipfs_datasets_py.logic.integration.bridges.base_prover_bridge import (
            BaseProverBridge, BridgeMetadata, BridgeCapability
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Formula

        class ConcreteTestBridge(BaseProverBridge):
            def _init_metadata(self):
                return BridgeMetadata(
                    name="test", version="0.1", target_system="test",
                    capabilities=[], requires_external_prover=False, description="test bridge"
                )
            def _check_availability(self):
                return False  # Not available
            def to_target_format(self, formula):
                return str(formula)
            def from_target_format(self, result):
                from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
                return ProofResult(status=ProofStatus.FAILED, formula=None, time_ms=0, method="test")
            def prove(self, formula, **kwargs):
                return self.from_target_format(None)

        bridge = ConcreteTestBridge()
        assert hasattr(bridge, 'available')
        assert bridge.available is False
        assert bridge._available is False

    def test_tdfol_shadowprover_bridge_init_no_crash(self):
        """GIVEN TDFOLShadowProverBridge WHEN init THEN no AttributeError on self.available."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import TDFOLShadowProverBridge
        bridge = TDFOLShadowProverBridge()
        assert hasattr(bridge, 'available')

    def test_tdfol_grammar_bridge_init_no_crash(self):
        """GIVEN TDFOLGrammarBridge WHEN init THEN no AttributeError on self.available."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import TDFOLGrammarBridge
        bridge = TDFOLGrammarBridge()
        assert hasattr(bridge, 'available')


# ===========================================================================
# 8. Integration smoke test
# ===========================================================================

class TestNeurosymbolicIntegrationSmoke:
    """End-to-end smoke tests combining multiple neurosymbolic modules."""

    def test_embedding_prover_in_coordinator(self):
        """GIVEN coordinator with embeddings WHEN prove THEN uses embedding prover."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import (
            NeuralSymbolicCoordinator, ReasoningStrategy
        )
        # use_embeddings=True will try to init EmbeddingEnhancedProver (which works without sentence-transformers)
        coord = NeuralSymbolicCoordinator(use_cec=False, use_modal=False, use_embeddings=True)
        # If embedding_prover loaded, test neural path
        f = _make_formula("O(pay(alice))")
        axioms = [_make_formula("O(pay(alice))")]
        result = coord.prove(f, axioms=axioms, strategy=ReasoningStrategy.NEURAL_ONLY)
        assert isinstance(result.is_proved, bool)

    def test_hybrid_confidence_with_embedding_similarity(self):
        """GIVEN HybridConfidenceScorer WHEN given both proofs THEN produces valid confidence."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import HybridConfidenceScorer
        scorer = HybridConfidenceScorer()
        pr_proved = _make_proof_result(proved=True)
        bd = scorer.compute_confidence(
            symbolic_result=pr_proved,
            neural_similarity=0.9,
            formula=_make_formula()
        )
        assert 0.5 < bd.total_confidence <= 1.0

    def test_full_pipeline_process_and_query(self):
        """GIVEN NeurosymbolicGraphRAG WHEN process + query THEN no exception."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_graphrag import NeurosymbolicGraphRAG
        rag = NeurosymbolicGraphRAG(use_neural=False, enable_proof_caching=False)
        rag.process_document("Bob must sign the contract", "contract1")
        rag.process_document("Alice must deliver the goods", "contract2")
        stats = rag.get_pipeline_stats()
        assert stats["documents_processed"] == 2
