"""
Test suite for unified Neurosymbolic API.

Tests the complete integrated system.
"""

import pytest
import logging

from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Formula,
    Predicate,
    BinaryFormula,
    LogicOperator,
)

# Try to import integration modules
try:
    from ipfs_datasets_py.logic.integration.neurosymbolic_api import (
        NeurosymbolicReasoner,
        ReasoningCapabilities,
        get_reasoner,
    )
    INTEGRATION_AVAILABLE = True
except ImportError:
    INTEGRATION_AVAILABLE = False
    pytest.skip("Neurosymbolic API not available", allow_module_level=True)


class TestReasoningCapabilities:
    """Test ReasoningCapabilities dataclass."""
    
    def test_capabilities_creation(self):
        """Test creating capabilities object."""
        caps = ReasoningCapabilities()
        assert caps.tdfol_rules == 40
        assert caps.cec_rules == 87
        assert caps.total_rules == 127
        assert len(caps.modal_provers) == 5
    
    def test_capabilities_custom(self):
        """Test creating custom capabilities."""
        caps = ReasoningCapabilities(
            tdfol_rules=50,
            cec_rules=100,
            total_rules=150,
        )
        assert caps.tdfol_rules == 50
        assert caps.cec_rules == 100
        assert caps.total_rules == 150


class TestNeurosymbolicReasoner:
    """Test the main NeurosymbolicReasoner class."""
    
    def setup_method(self):
        """Setup for each test."""
        self.reasoner = NeurosymbolicReasoner()
    
    def test_reasoner_initialization(self):
        """Test reasoner initializes correctly."""
        assert self.reasoner is not None
        assert isinstance(self.reasoner, NeurosymbolicReasoner)
    
    def test_reasoner_has_knowledge_base(self):
        """Test reasoner has knowledge base."""
        assert hasattr(self.reasoner, 'kb')
        assert self.reasoner.kb is not None
    
    def test_reasoner_has_prover(self):
        """Test reasoner has prover."""
        assert hasattr(self.reasoner, 'prover')
        assert self.reasoner.prover is not None
    
    def test_reasoner_has_nl_interface(self):
        """Test reasoner has NL interface."""
        assert hasattr(self.reasoner, 'nl_interface')
        # Might be None if NL not available
    
    def test_get_capabilities(self):
        """Test getting system capabilities."""
        caps = self.reasoner.get_capabilities()
        
        assert 'tdfol_rules' in caps
        assert 'cec_rules' in caps
        assert 'total_inference_rules' in caps
        assert 'modal_provers' in caps
        assert 'shadowprover_available' in caps
        assert 'grammar_available' in caps
        assert 'natural_language' in caps
        
        assert caps['tdfol_rules'] >= 0
        assert caps['total_inference_rules'] >= caps['tdfol_rules']
    
    def test_parse_tdfol_format(self):
        """Test parsing TDFOL format."""
        formula = self.reasoner.parse("forall x. P(x) -> Q(x)", format="tdfol")
        
        if formula:
            assert isinstance(formula, Formula)
            logging.info(f"Parsed TDFOL: {formula.to_string()}")
    
    def test_parse_dcec_format(self):
        """Test parsing DCEC format."""
        formula = self.reasoner.parse("(O P)", format="dcec")
        
        if formula:
            assert isinstance(formula, Formula)
            logging.info(f"Parsed DCEC: {formula.to_string()}")
    
    def test_parse_auto_format(self):
        """Test auto-format detection."""
        # Should detect DCEC
        formula1 = self.reasoner.parse("(and P Q)", format="auto")
        if formula1:
            assert isinstance(formula1, Formula)
        
        # Should detect TDFOL
        formula2 = self.reasoner.parse("P -> Q", format="auto")
        if formula2:
            assert isinstance(formula2, Formula)
    
    def test_add_knowledge_string(self):
        """Test adding knowledge from string."""
        success = self.reasoner.add_knowledge("P")
        assert isinstance(success, bool)
    
    def test_add_knowledge_formula(self):
        """Test adding knowledge from formula."""
        p = Predicate("P", ())
        success = self.reasoner.add_knowledge(p)
        assert success == True
    
    def test_add_axiom_vs_theorem(self):
        """Test adding as axiom vs theorem."""
        success1 = self.reasoner.add_knowledge("P", is_axiom=True)
        success2 = self.reasoner.add_knowledge("Q", is_axiom=False)
        
        assert isinstance(success1, bool)
        assert isinstance(success2, bool)
    
    def test_prove_simple_formula(self):
        """Test proving simple formula."""
        # Add axiom
        p = Predicate("P", ())
        self.reasoner.add_knowledge(p)
        
        # Prove same formula
        result = self.reasoner.prove(p)
        assert result is not None
        logging.info(f"Proof result: {result.status}")
    
    def test_prove_with_premises(self):
        """Test proving with additional premises."""
        p = Predicate("P", ())
        q = Predicate("Q", ())
        
        # Prove Q given P and P->Q
        result = self.reasoner.prove(
            q,
            given=[p, "P -> Q"],
            timeout_ms=2000
        )
        assert result is not None
        logging.info(f"Proof with premises: {result.status}")
    
    def test_explain_formula(self):
        """Test explaining a formula."""
        p = Predicate("P", ())
        explanation = self.reasoner.explain(p)
        
        assert explanation is not None
        assert isinstance(explanation, str)
        assert len(explanation) > 0
    
    def test_explain_string(self):
        """Test explaining from string."""
        explanation = self.reasoner.explain("P")
        assert isinstance(explanation, str)
    
    def test_query_natural_language(self):
        """Test natural language query."""
        # Add some knowledge
        self.reasoner.add_knowledge("P")
        
        # Query
        result = self.reasoner.query("Is P true?")
        
        assert 'question' in result
        assert 'answer' in result
        assert 'success' in result
        
        logging.info(f"Query result: {result}")


class TestNeurosymbolicReasonerWithCEC:
    """Test reasoner specifically with CEC enabled."""
    
    def test_reasoner_with_cec_enabled(self):
        """Test creating reasoner with CEC."""
        reasoner = NeurosymbolicReasoner(use_cec=True, use_modal=False, use_nl=False)
        assert reasoner is not None
        
        caps = reasoner.get_capabilities()
        assert caps['tdfol_rules'] >= 40
    
    def test_reasoner_with_modal_enabled(self):
        """Test creating reasoner with modal logic."""
        reasoner = NeurosymbolicReasoner(use_cec=False, use_modal=True, use_nl=False)
        assert reasoner is not None
        
        caps = reasoner.get_capabilities()
        assert 'shadowprover_available' in caps
    
    def test_reasoner_with_all_features(self):
        """Test creating reasoner with all features."""
        reasoner = NeurosymbolicReasoner(use_cec=True, use_modal=True, use_nl=True)
        assert reasoner is not None
        
        caps = reasoner.get_capabilities()
        assert caps['total_inference_rules'] >= 40


class TestGlobalReasoner:
    """Test global reasoner singleton."""
    
    def test_get_global_reasoner(self):
        """Test getting global reasoner instance."""
        reasoner = get_reasoner()
        assert reasoner is not None
        assert isinstance(reasoner, NeurosymbolicReasoner)
    
    def test_global_reasoner_singleton(self):
        """Test global reasoner is singleton."""
        reasoner1 = get_reasoner()
        reasoner2 = get_reasoner()
        
        # Should be same instance
        assert reasoner1 is reasoner2


class TestIntegrationScenarios:
    """Test complete integration scenarios."""
    
    def setup_method(self):
        """Setup for each test."""
        self.reasoner = NeurosymbolicReasoner(
            use_cec=True,
            use_modal=True,
            use_nl=True
        )
    
    def test_modus_ponens_reasoning(self):
        """Test classic Modus Ponens."""
        # Add: P, P → Q
        self.reasoner.add_knowledge("P")
        self.reasoner.add_knowledge("P -> Q")
        
        # Prove: Q
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        q = parse_tdfol("Q")
        
        result = self.reasoner.prove(q, timeout_ms=2000)
        assert result is not None
        logging.info(f"Modus Ponens: {result.status}, method={result.method}")
    
    def test_temporal_reasoning_scenario(self):
        """Test temporal reasoning."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
            TemporalFormula,
            TemporalOperator,
            Predicate,
        )
        
        # Always available
        available = Predicate("Available", ())
        always_available = TemporalFormula(TemporalOperator.ALWAYS, available)
        
        self.reasoner.add_knowledge(always_available)
        
        # Should derive available now
        result = self.reasoner.prove(available, timeout_ms=2000)
        assert result is not None
        logging.info(f"Temporal reasoning: {result.status}")
    
    def test_deontic_reasoning_scenario(self):
        """Test deontic reasoning."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
            DeonticFormula,
            DeonticOperator,
            Predicate,
        )
        
        # Obligatory to report
        report = Predicate("Report", ())
        obligatory = DeonticFormula(DeonticOperator.OBLIGATORY, report)
        
        self.reasoner.add_knowledge(obligatory)
        
        # Should derive permission (O(p) → P(p))
        permitted = DeonticFormula(DeonticOperator.PERMISSIBLE, report)
        result = self.reasoner.prove(permitted, timeout_ms=2000)
        assert result is not None
        logging.info(f"Deontic reasoning: {result.status}")
    
    def test_multi_format_parsing(self):
        """Test parsing multiple formats in one session."""
        # TDFOL
        f1 = self.reasoner.parse("P -> Q", format="tdfol")
        
        # DCEC
        f2 = self.reasoner.parse("(O P)", format="dcec")
        
        # Auto
        f3 = self.reasoner.parse("(and P Q)", format="auto")
        
        # At least some should parse
        parsed_count = sum(1 for f in [f1, f2, f3] if f is not None)
        assert parsed_count > 0
        
        logging.info(f"Parsed {parsed_count}/3 formulas")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
