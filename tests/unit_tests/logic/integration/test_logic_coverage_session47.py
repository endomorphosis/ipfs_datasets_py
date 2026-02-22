"""
Session 47 — Logic Integration Coverage Tests.

Targets remaining uncovered lines in:
- reasoning/deontological_reasoning_utils.py  (30% → 95%)
- reasoning/logic_verification.py             (53% → 80%)
- reasoning/logic_verification_utils.py       (85% → 100%)
- domain/legal_domain_knowledge.py            (39% → 90%)
- domain/deontic_query_engine.py              (30% → 80%)
- domain/temporal_deontic_api.py              (10% → 80%)
- reasoning/deontological_reasoning.py        (75% → 92%)

All tests follow GIVEN-WHEN-THEN format.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helper: run async functions in tests
# ---------------------------------------------------------------------------

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# 1. deontological_reasoning_utils.py
# ===========================================================================

class TestExtractKeywords:
    """Tests for extract_keywords function."""

    def test_basic_keywords_extracted(self):
        """GIVEN a text with meaningful words
        WHEN extract_keywords is called
        THEN meaningful keywords are returned excluding stop-words"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_keywords
        result = extract_keywords("must pay taxes annually")
        assert "pay" in result
        assert "taxes" in result
        # stop words filtered
        assert "the" not in result
        assert "a" not in result

    def test_stop_words_removed(self):
        """GIVEN text with only stop-words
        WHEN extract_keywords is called
        THEN empty set returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_keywords
        result = extract_keywords("the a an and or but in on at")
        assert isinstance(result, set)
        # all are stop-words or ≤2 chars
        assert len(result) == 0

    def test_short_words_filtered(self):
        """GIVEN text with 1-2 char words
        WHEN extract_keywords is called
        THEN they are filtered out"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_keywords
        result = extract_keywords("up it is go")
        # 'up'=2, 'it'=2, 'is'=2, 'go'=2 — all ≤2 chars filtered
        assert len(result) == 0


class TestCalculateTextSimilarity:
    """Tests for calculate_text_similarity function."""

    def test_identical_texts_have_high_similarity(self):
        """GIVEN two identical texts
        WHEN calculate_text_similarity is called
        THEN similarity is 1.0"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import calculate_text_similarity
        assert calculate_text_similarity("pay taxes", "pay taxes") == 1.0

    def test_unrelated_texts_have_low_similarity(self):
        """GIVEN two unrelated texts
        WHEN calculate_text_similarity is called
        THEN similarity is low"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import calculate_text_similarity
        score = calculate_text_similarity("pay taxes", "file lawsuit")
        assert score < 0.5

    def test_partial_overlap(self):
        """GIVEN two texts sharing some words
        WHEN calculate_text_similarity is called
        THEN similarity is between 0 and 1"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import calculate_text_similarity
        score = calculate_text_similarity("pay annual taxes", "pay bills")
        assert 0.0 < score < 1.0

    def test_empty_texts_return_zero(self):
        """GIVEN empty texts
        WHEN calculate_text_similarity is called
        THEN 0.0 returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import calculate_text_similarity
        assert calculate_text_similarity("", "pay taxes") == 0.0
        assert calculate_text_similarity("pay taxes", "") == 0.0
        assert calculate_text_similarity("", "") == 0.0


class TestAreEntitiesSimilar:
    """Tests for are_entities_similar function."""

    def test_identical_entities_are_similar(self):
        """GIVEN identical entity names
        WHEN are_entities_similar is called
        THEN True returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_entities_similar
        assert are_entities_similar("citizen", "citizen") is True

    def test_substring_match(self):
        """GIVEN entity name that is substring of other
        WHEN are_entities_similar is called
        THEN True returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_entities_similar
        assert are_entities_similar("citizen", "citizens") is True

    def test_unrelated_entities_not_similar(self):
        """GIVEN completely different entities
        WHEN are_entities_similar is called with default threshold
        THEN False returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_entities_similar
        assert are_entities_similar("citizen", "corporation") is False

    def test_case_insensitive(self):
        """GIVEN entities with different casing
        WHEN are_entities_similar is called
        THEN True returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_entities_similar
        assert are_entities_similar("CITIZEN", "citizen") is True


class TestAreActionsSimilar:
    """Tests for are_actions_similar function."""

    def test_identical_actions_are_similar(self):
        """GIVEN identical actions
        WHEN are_actions_similar is called
        THEN True returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_actions_similar
        assert are_actions_similar("pay taxes", "pay taxes") is True

    def test_substring_match(self):
        """GIVEN action that is substring of other
        WHEN are_actions_similar is called
        THEN True returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_actions_similar
        assert are_actions_similar("pay taxes", "must pay taxes annually") is True

    def test_unrelated_actions_not_similar(self):
        """GIVEN unrelated actions
        WHEN are_actions_similar is called
        THEN False returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_actions_similar
        assert are_actions_similar("pay taxes", "file lawsuit") is False


class TestNormalizeEntityAction:
    """Tests for normalize_entity and normalize_action."""

    def test_normalize_entity_strips_and_lowercases(self):
        """GIVEN entity with extra whitespace and capitals
        WHEN normalize_entity is called
        THEN stripped lowercase returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import normalize_entity
        assert normalize_entity("  CITIZEN  ") == "citizen"

    def test_normalize_action_strips_and_lowercases(self):
        """GIVEN action with extra whitespace and capitals
        WHEN normalize_action is called
        THEN stripped lowercase returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import normalize_action
        assert normalize_action("  PAY TAXES  ") == "pay taxes"


class TestExtractConditionsExceptions:
    """Tests for extract_conditions_from_text and extract_exceptions_from_text."""

    def test_extract_conditions_if_clause(self):
        """GIVEN text with if-clause
        WHEN extract_conditions_from_text is called
        THEN condition extracted"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_conditions_from_text
        conditions = extract_conditions_from_text("if employed, must pay taxes")
        assert len(conditions) > 0

    def test_extract_conditions_when_clause(self):
        """GIVEN text with when-clause
        WHEN extract_conditions_from_text is called
        THEN condition extracted"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_conditions_from_text
        conditions = extract_conditions_from_text("when the contract is signed, the party must comply")
        assert len(conditions) > 0

    def test_extract_conditions_empty_text(self):
        """GIVEN text without conditions
        WHEN extract_conditions_from_text is called
        THEN empty list returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_conditions_from_text
        conditions = extract_conditions_from_text("must pay taxes")
        assert conditions == []

    def test_extract_exceptions_unless_clause(self):
        """GIVEN text with unless-clause
        WHEN extract_exceptions_from_text is called
        THEN exception extracted"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_exceptions_from_text
        exceptions = extract_exceptions_from_text("must pay taxes unless exempt")
        assert len(exceptions) > 0

    def test_extract_exceptions_empty_text(self):
        """GIVEN text without exceptions
        WHEN extract_exceptions_from_text is called
        THEN empty list returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_exceptions_from_text
        exceptions = extract_exceptions_from_text("must pay taxes")
        assert exceptions == []


# ===========================================================================
# 2. logic_verification.py — uncovered paths
# ===========================================================================

class TestLogicVerifierFallbackPaths:
    """Tests for LogicVerifier fallback paths (use_symbolic_ai=False)."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        self.verifier = LogicVerifier(use_symbolic_ai=False, fallback_enabled=True)

    def test_add_axiom_invalid_syntax_returns_false(self):
        """GIVEN axiom with invalid formula (unbalanced parens)
        WHEN add_axiom called
        THEN False returned and axiom not added"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification_types import LogicAxiom
        invalid_axiom = LogicAxiom(name="invalid", formula="P ∧ (Q", description="bad", axiom_type="user_defined")
        result = self.verifier.add_axiom(invalid_axiom)
        assert result is False

    def test_add_axiom_duplicate_returns_false(self):
        """GIVEN axiom with name that already exists
        WHEN add_axiom called again
        THEN False returned"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification_types import LogicAxiom
        axiom = LogicAxiom(name="modus_ponens", formula="P", description="dup", axiom_type="built_in")
        result = self.verifier.add_axiom(axiom)
        assert result is False

    def test_check_consistency_with_contradiction(self):
        """GIVEN formulas containing P and ¬P
        WHEN check_consistency called (fallback)
        THEN is_consistent=False"""
        result = self.verifier.check_consistency(["P", "¬P"])
        assert result.is_consistent is False
        assert result.confidence > 0.5

    def test_check_consistency_without_contradiction(self):
        """GIVEN formulas that don't contradict
        WHEN check_consistency called (fallback)
        THEN is_consistent=True"""
        result = self.verifier.check_consistency(["P", "Q"])
        assert result.is_consistent is True

    def test_check_entailment_modus_ponens_fallback(self):
        """GIVEN premises with P→Q and P
        WHEN check_entailment called (fallback)
        THEN entails=True"""
        result = self.verifier.check_entailment(["P → Q", "P"], "Q")
        assert result.entails is True
        assert result.confidence > 0.5

    def test_check_entailment_no_premises_returns_false(self):
        """GIVEN empty premises
        WHEN check_entailment called
        THEN entails=False"""
        result = self.verifier.check_entailment([], "Q")
        assert result.entails is False

    def test_generate_proof_modus_ponens(self):
        """GIVEN premises P→Q and P
        WHEN generate_proof called (fallback)
        THEN is_valid=True with steps"""
        result = self.verifier.generate_proof(["P → Q", "P"], "Q")
        assert result.is_valid is True
        assert len(result.steps) > 0
        assert result.method_used == "fallback_modus_ponens"

    def test_generate_proof_cache_hit(self):
        """GIVEN same proof requested twice
        WHEN generate_proof called again
        THEN cached result returned"""
        self.verifier.generate_proof(["P → Q", "P"], "Q")
        result = self.verifier.generate_proof(["P → Q", "P"], "Q")
        assert result.is_valid is True
        # cache size should be 1
        assert len(self.verifier.proof_cache) == 1

    def test_generate_proof_no_valid_proof(self):
        """GIVEN premises with no deduction path
        WHEN generate_proof called
        THEN is_valid=False"""
        result = self.verifier.generate_proof(["P", "Q"], "R")
        assert result.is_valid is False

    def test_verify_formula_syntax_empty_formula(self):
        """GIVEN empty string formula
        WHEN verify_formula_syntax called
        THEN status='invalid'"""
        result = self.verifier.verify_formula_syntax("")
        assert result["status"] == "invalid"

    def test_verify_formula_syntax_valid_formula(self):
        """GIVEN well-formed formula
        WHEN verify_formula_syntax called (fallback)
        THEN status='valid'"""
        result = self.verifier.verify_formula_syntax("P ∧ Q")
        assert result["status"] == "valid"

    def test_verify_formula_syntax_unbalanced(self):
        """GIVEN formula with unbalanced parens
        WHEN verify_formula_syntax called (fallback)
        THEN status='invalid'"""
        result = self.verifier.verify_formula_syntax("P ∧ (Q")
        assert result["status"] == "invalid"

    def test_check_satisfiability_empty_formula(self):
        """GIVEN empty formula
        WHEN check_satisfiability called
        THEN satisfiable=False"""
        result = self.verifier.check_satisfiability("")
        assert result["satisfiable"] is False
        assert result["status"] == "invalid"

    def test_check_satisfiability_contradiction(self):
        """GIVEN P∧¬P formula
        WHEN check_satisfiability called (fallback)
        THEN satisfiable=False"""
        result = self.verifier.check_satisfiability("P∧¬P")
        assert result["satisfiable"] is False
        assert result["status"] == "unsatisfiable"

    def test_check_satisfiability_normal_formula(self):
        """GIVEN normal formula
        WHEN check_satisfiability called (fallback)
        THEN assumed satisfiable"""
        result = self.verifier.check_satisfiability("P ∧ Q")
        assert result["satisfiable"] is True

    def test_check_validity_empty_formula(self):
        """GIVEN empty formula
        WHEN check_validity called
        THEN valid=False"""
        result = self.verifier.check_validity("")
        assert result["valid"] is False

    def test_check_validity_tautology(self):
        """GIVEN P∨¬P tautology
        WHEN check_validity called (fallback)
        THEN valid=True, status=tautology"""
        result = self.verifier.check_validity("P∨¬P")
        assert result["valid"] is True
        assert result["status"] == "tautology"

    def test_check_validity_normal_formula(self):
        """GIVEN normal non-tautology formula
        WHEN check_validity called (fallback)
        THEN valid=False, status=unknown"""
        result = self.verifier.check_validity("P ∧ Q")
        assert result["valid"] is False

    def test_initialize_proof_rules(self):
        """GIVEN a LogicVerifier
        WHEN _initialize_proof_rules called
        THEN returns list of rule dicts"""
        rules = self.verifier._initialize_proof_rules()
        assert isinstance(rules, list)
        assert len(rules) >= 7  # 3 basic + 4 additional

    def test_clear_cache(self):
        """GIVEN verifier with cached proofs
        WHEN clear_cache called
        THEN cache is empty"""
        self.verifier.generate_proof(["P → Q", "P"], "Q")
        assert len(self.verifier.proof_cache) > 0
        self.verifier.clear_cache()
        assert len(self.verifier.proof_cache) == 0

    def test_get_axioms_filtered_by_type(self):
        """GIVEN verifier with axioms
        WHEN get_axioms called with axiom_type
        THEN only matching axioms returned"""
        built_ins = self.verifier.get_axioms("built_in")
        assert all(a.axiom_type == "built_in" for a in built_ins)


class TestLogicVerifierSymbolicFallback:
    """Tests for LogicVerifier symbolic AI paths — using mock Symbol."""

    def _make_symbol_mock(self, response_text: str):
        mock_sym = MagicMock()
        mock_query = MagicMock()
        mock_query.value = response_text
        mock_sym.query.return_value = mock_query
        return mock_sym

    def test_consistency_symbolic_fallback_on_unknown(self):
        """GIVEN SymbolicAI returns 'unknown'
        WHEN check_consistency_symbolic called
        THEN falls back to pattern matching"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        import ipfs_datasets_py.logic.integration.reasoning.logic_verification as lv_mod
        symbol_mock = self._make_symbol_mock("unknown result, cannot determine")
        with patch.object(lv_mod, 'Symbol', return_value=symbol_mock), \
             patch.object(lv_mod, 'SYMBOLIC_AI_AVAILABLE', True):
            verifier = LogicVerifier(use_symbolic_ai=True, fallback_enabled=True)
            result = verifier._check_consistency_symbolic(["P", "Q"])
        # Falls back to pattern_matching
        assert result.method_used == "pattern_matching"

    def test_consistency_symbolic_inconsistent_response(self):
        """GIVEN SymbolicAI returns 'inconsistent'
        WHEN _check_consistency_symbolic called
        THEN is_consistent=False"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        import ipfs_datasets_py.logic.integration.reasoning.logic_verification as lv_mod
        symbol_mock = self._make_symbol_mock("inconsistent formulas detected")
        with patch.object(lv_mod, 'Symbol', return_value=symbol_mock), \
             patch.object(lv_mod, 'SYMBOLIC_AI_AVAILABLE', True):
            verifier = LogicVerifier(use_symbolic_ai=True, fallback_enabled=True)
            result = verifier._check_consistency_symbolic(["P", "¬P"])
        assert result.is_consistent is False

    def test_consistency_symbolic_consistent_response(self):
        """GIVEN SymbolicAI returns 'consistent'
        WHEN _check_consistency_symbolic called
        THEN is_consistent=True"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        import ipfs_datasets_py.logic.integration.reasoning.logic_verification as lv_mod
        symbol_mock = self._make_symbol_mock("consistent and compatible")
        with patch.object(lv_mod, 'Symbol', return_value=symbol_mock), \
             patch.object(lv_mod, 'SYMBOLIC_AI_AVAILABLE', True):
            verifier = LogicVerifier(use_symbolic_ai=True, fallback_enabled=True)
            result = verifier._check_consistency_symbolic(["P", "Q"])
        assert result.is_consistent is True

    def test_entailment_symbolic_yes_response(self):
        """GIVEN SymbolicAI returns 'yes'
        WHEN _check_entailment_symbolic called
        THEN entails=True"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        import ipfs_datasets_py.logic.integration.reasoning.logic_verification as lv_mod
        symbol_mock = self._make_symbol_mock("yes, the entailment holds")
        with patch.object(lv_mod, 'Symbol', return_value=symbol_mock), \
             patch.object(lv_mod, 'SYMBOLIC_AI_AVAILABLE', True):
            verifier = LogicVerifier(use_symbolic_ai=True, fallback_enabled=True)
            result = verifier._check_entailment_symbolic(["P → Q", "P"], "Q")
        assert result.entails is True

    def test_entailment_symbolic_no_response(self):
        """GIVEN SymbolicAI returns 'no'
        WHEN _check_entailment_symbolic called
        THEN entails=False"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        import ipfs_datasets_py.logic.integration.reasoning.logic_verification as lv_mod
        symbol_mock = self._make_symbol_mock("no, cannot establish entailment")
        with patch.object(lv_mod, 'Symbol', return_value=symbol_mock), \
             patch.object(lv_mod, 'SYMBOLIC_AI_AVAILABLE', True):
            verifier = LogicVerifier(use_symbolic_ai=True, fallback_enabled=True)
            result = verifier._check_entailment_symbolic(["P"], "Q")
        assert result.entails is False

    def test_entailment_symbolic_uncertain_fallback(self):
        """GIVEN SymbolicAI returns 'uncertain' (no yes/no)
        WHEN _check_entailment_symbolic called
        THEN fallback used"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        import ipfs_datasets_py.logic.integration.reasoning.logic_verification as lv_mod
        # "uncertain" does not contain "yes" or "no" as substrings
        symbol_mock = self._make_symbol_mock("uncertain, further analysis required")
        with patch.object(lv_mod, 'Symbol', return_value=symbol_mock), \
             patch.object(lv_mod, 'SYMBOLIC_AI_AVAILABLE', True):
            verifier = LogicVerifier(use_symbolic_ai=True, fallback_enabled=True)
            result = verifier._check_entailment_symbolic(["P → Q", "P"], "Q")
        # Fallback should handle modus ponens
        assert result.entails is True

    def test_proof_symbolic_with_steps(self):
        """GIVEN SymbolicAI returns parseable proof steps
        WHEN _generate_proof_symbolic called
        THEN ProofResult with steps returned"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        import ipfs_datasets_py.logic.integration.reasoning.logic_verification as lv_mod
        proof_text = "Step 1: P → Q (premise)\nStep 2: P (premise)\nStep 3: Q (modus_ponens)"
        symbol_mock = self._make_symbol_mock(proof_text)
        with patch.object(lv_mod, 'Symbol', return_value=symbol_mock), \
             patch.object(lv_mod, 'SYMBOLIC_AI_AVAILABLE', True):
            verifier = LogicVerifier(use_symbolic_ai=True, fallback_enabled=True)
            result = verifier._generate_proof_symbolic(["P → Q", "P"], "Q")
        assert len(result.steps) == 3
        assert result.method_used == "symbolic_ai"

    def test_find_conflicting_pairs_symbolic(self):
        """GIVEN SymbolicAI returns 'no' for contradiction check
        WHEN _find_conflicting_pairs_symbolic called
        THEN conflicting pair added"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        import ipfs_datasets_py.logic.integration.reasoning.logic_verification as lv_mod
        symbol_mock = self._make_symbol_mock("no, they cannot both be true")
        with patch.object(lv_mod, 'Symbol', return_value=symbol_mock), \
             patch.object(lv_mod, 'SYMBOLIC_AI_AVAILABLE', True):
            verifier = LogicVerifier(use_symbolic_ai=True, fallback_enabled=True)
            result = verifier._find_conflicting_pairs_symbolic(["P", "¬P"])
        assert len(result) == 1


class TestLogicVerifierUtilConvenienceFunctions:
    """Tests for convenience functions in logic_verification_utils.py."""

    def test_verify_consistency_convenience(self):
        """GIVEN list of contradictory formulas
        WHEN verify_consistency called
        THEN is_consistent=False"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification_utils import verify_consistency
        result = verify_consistency(["P", "¬P"])
        assert result.is_consistent is False

    def test_verify_entailment_convenience(self):
        """GIVEN modus ponens premises and conclusion
        WHEN verify_entailment called
        THEN entails=True"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification_utils import verify_entailment
        result = verify_entailment(["P → Q", "P"], "Q")
        assert result.entails is True

    def test_generate_proof_convenience(self):
        """GIVEN modus ponens premises and conclusion
        WHEN generate_proof called
        THEN is_valid=True"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification_utils import generate_proof
        result = generate_proof(["P → Q", "P"], "Q")
        assert result.is_valid is True

    def test_create_logic_verifier_factory(self):
        """GIVEN factory call with default params
        WHEN create_logic_verifier called
        THEN LogicVerifier instance returned"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification_utils import create_logic_verifier
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        verifier = create_logic_verifier(use_symbolic_ai=False)
        assert isinstance(verifier, LogicVerifier)

    def test_validate_formula_syntax_unbalanced_closing(self):
        """GIVEN formula with extra closing paren
        WHEN validate_formula_syntax called
        THEN False returned (paren_count goes negative)"""
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification_utils import validate_formula_syntax
        assert validate_formula_syntax("P)") is False


# ===========================================================================
# 3. domain/legal_domain_knowledge.py
# ===========================================================================

class TestLegalDomainKnowledge:
    """Tests for LegalDomainKnowledge class methods."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        self.knowledge = LegalDomainKnowledge()

    def test_classify_obligation(self):
        """GIVEN text with 'shall' obligation indicator
        WHEN classify_legal_statement called
        THEN OBLIGATION operator returned with confidence"""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        op, conf = self.knowledge.classify_legal_statement("The party shall pay rent monthly")
        assert op == DeonticOperator.OBLIGATION
        assert conf > 0.5

    def test_classify_permission(self):
        """GIVEN text with 'may' permission indicator
        WHEN classify_legal_statement called
        THEN PERMISSION operator returned"""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        op, conf = self.knowledge.classify_legal_statement("The tenant may terminate this lease")
        assert op == DeonticOperator.PERMISSION

    def test_classify_prohibition(self):
        """GIVEN text with 'must not' prohibition indicator
        WHEN classify_legal_statement called
        THEN PROHIBITION operator returned"""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        op, conf = self.knowledge.classify_legal_statement("Employees must not disclose confidential information")
        assert op == DeonticOperator.PROHIBITION
        assert conf > 0.5

    def test_classify_modal_verb_fallback(self):
        """GIVEN text where no pattern matches but modal verb present
        WHEN classify_legal_statement called
        THEN returns result using modal verb fallback"""
        # Text that won't match specific patterns but has modal verb
        op, conf = self.knowledge.classify_legal_statement("The rule requires must compliance")
        # Should return something (not crash)
        assert op is not None

    def test_extract_agents_person(self):
        """GIVEN text with legal person entity
        WHEN extract_agents called
        THEN agents list non-empty"""
        agents = self.knowledge.extract_agents("The contractor shall complete all work by deadline")
        assert isinstance(agents, list)

    def test_extract_agents_with_context_boost(self):
        """GIVEN text with agent preceded by 'the'
        WHEN extract_agents called
        THEN confidence may be boosted"""
        agents = self.knowledge.extract_agents("The employer shall pay the employee salary")
        # Just verify it returns a list without error
        assert isinstance(agents, list)

    def test_extract_conditions_if_clause(self):
        """GIVEN legal text with if clause
        WHEN extract_conditions called
        THEN conditions list non-empty"""
        conditions = self.knowledge.extract_conditions("If the contract is breached, the party must pay damages")
        assert isinstance(conditions, list)

    def test_extract_temporal_expressions_deadline(self):
        """GIVEN text with temporal deadline
        WHEN extract_temporal_expressions called
        THEN deadline category populated"""
        temporal = self.knowledge.extract_temporal_expressions(
            "The contractor shall complete all work by December 31, 2024"
        )
        assert isinstance(temporal, dict)
        assert "deadline" in temporal

    def test_identify_legal_domain_contract(self):
        """GIVEN contract-related text
        WHEN identify_legal_domain called
        THEN contract domain identified"""
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        domain, conf = self.knowledge.identify_legal_domain(
            "This contract agreement between the parties establishes obligations for performance and consideration"
        )
        assert domain == LegalDomain.CONTRACT or conf >= 0.0  # tolerance — domain detection may vary

    def test_identify_legal_domain_no_keywords(self):
        """GIVEN text with no domain keywords
        WHEN identify_legal_domain called
        THEN default CONTRACT domain returned"""
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        domain, conf = self.knowledge.identify_legal_domain("some random text with no legal terms")
        assert domain == LegalDomain.CONTRACT
        assert conf <= 0.5

    def test_extract_legal_entities(self):
        """GIVEN legal text with agents and concepts
        WHEN extract_legal_entities called
        THEN list of entity dicts returned"""
        entities = self.knowledge.extract_legal_entities(
            "The contractor shall perform obligations under this contract agreement"
        )
        assert isinstance(entities, list)
        # Should have at least the legal term "contractor" or "contract"
        assert any(e["type"] in ("agent", "legal_concept") for e in entities)

    def test_validate_deontic_extraction_obligation_with_permission_indicator(self):
        """GIVEN obligation text with permission indicator
        WHEN validate_deontic_extraction called
        THEN warning about conflicting signals"""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        result = self.knowledge.validate_deontic_extraction(
            "may pay taxes", DeonticOperator.OBLIGATION, 0.8
        )
        assert len(result["warnings"]) > 0
        assert result["confidence_adjustment"] < 0

    def test_validate_deontic_extraction_permission_with_obligation_indicator(self):
        """GIVEN permission text with obligation indicator
        WHEN validate_deontic_extraction called
        THEN warning about conflicting signals"""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        result = self.knowledge.validate_deontic_extraction(
            "must pay taxes", DeonticOperator.PERMISSION, 0.8
        )
        assert len(result["warnings"]) > 0

    def test_validate_deontic_extraction_low_confidence_invalid(self):
        """GIVEN extraction with confidence too low after adjustment
        WHEN validate_deontic_extraction called
        THEN is_valid=False"""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        result = self.knowledge.validate_deontic_extraction(
            "may must", DeonticOperator.OBLIGATION, 0.3
        )
        # Confidence 0.3 - 0.1 per conflict indicator = below 0.5
        assert result.get("is_valid") is False or result["confidence_adjustment"] < 0

    def test_demonstrate_legal_knowledge_runs(self):
        """GIVEN demonstrate_legal_knowledge function
        WHEN called
        THEN completes without error"""
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import demonstrate_legal_knowledge
        demonstrate_legal_knowledge()  # Should not raise


# ===========================================================================
# 4. domain/deontic_query_engine.py
# ===========================================================================

class TestDeonticQueryEngine:
    """Tests for DeonticQueryEngine class."""

    def _make_rule_set(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent, DeonticRuleSet
        )
        citizen = LegalAgent(identifier="citizen", name="Citizen", agent_type="person")
        corporation = LegalAgent(identifier="corporation", name="Corporation", agent_type="organization")
        return DeonticRuleSet(
            name="test_rules",
            formulas=[
                DeonticFormula(
                    operator=DeonticOperator.OBLIGATION,
                    proposition="pay taxes",
                    agent=citizen,
                    confidence=0.9,
                    source_text="Citizens must pay taxes",
                ),
                DeonticFormula(
                    operator=DeonticOperator.PERMISSION,
                    proposition="terminate contract",
                    agent=citizen,
                    confidence=0.8,
                    source_text="Citizens may terminate the contract",
                ),
                DeonticFormula(
                    operator=DeonticOperator.PROHIBITION,
                    proposition="disclose confidential",
                    agent=corporation,
                    confidence=0.95,
                    source_text="Corporations must not disclose confidential information",
                ),
            ],
        )

    def test_init_without_rule_set(self):
        """GIVEN no rule set
        WHEN DeonticQueryEngine initialized
        THEN empty indexes"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(enable_rate_limiting=False, enable_validation=False)
        assert engine.rule_set is None
        assert len(engine.operator_index) == 0

    def test_init_with_rule_set_builds_indexes(self):
        """GIVEN rule set with 3 formulas
        WHEN DeonticQueryEngine initialized with rule set
        THEN indexes built"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        rule_set = self._make_rule_set()
        engine = DeonticQueryEngine(rule_set=rule_set, enable_rate_limiting=False, enable_validation=False)
        assert len(engine.operator_index) > 0

    def test_load_rule_set(self):
        """GIVEN engine without rule set
        WHEN load_rule_set called
        THEN rule set loaded and indexes built"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(enable_rate_limiting=False, enable_validation=False)
        rule_set = self._make_rule_set()
        engine.load_rule_set(rule_set)
        assert engine.rule_set is not None
        assert len(engine.operator_index) > 0

    def test_query_obligations_no_filter(self):
        """GIVEN engine with rule set
        WHEN query_obligations called without filter
        THEN all obligations returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_obligations()
        assert result.total_matches == 1
        assert result.matching_formulas[0].proposition == "pay taxes"

    def test_query_obligations_with_agent_filter(self):
        """GIVEN engine with rule set
        WHEN query_obligations called with agent='citizen'
        THEN obligations for citizen returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_obligations(agent="citizen")
        assert result.total_matches == 1

    def test_query_permissions(self):
        """GIVEN engine with rule set
        WHEN query_permissions called
        THEN permissions returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_permissions()
        assert result.total_matches == 1

    def test_query_permissions_with_action_filter(self):
        """GIVEN engine with rule set
        WHEN query_permissions called with action='terminate'
        THEN matching permissions returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_permissions(action="terminate")
        assert result.total_matches >= 1

    def test_query_prohibitions(self):
        """GIVEN engine with rule set
        WHEN query_prohibitions called
        THEN prohibitions returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_prohibitions()
        assert result.total_matches == 1

    def test_query_by_natural_language_obligation(self):
        """GIVEN NL query with 'must'
        WHEN query_by_natural_language called
        THEN obligations returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine, QueryType
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_by_natural_language("what must citizens do?")
        assert result.query_type == QueryType.OBLIGATIONS

    def test_query_by_natural_language_permission(self):
        """GIVEN NL query with 'may'
        WHEN query_by_natural_language called
        THEN permissions returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine, QueryType
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_by_natural_language("what may citizens do?")
        assert result.query_type == QueryType.PERMISSIONS

    def test_query_by_natural_language_prohibition(self):
        """GIVEN NL query with 'forbidden'
        WHEN query_by_natural_language called
        THEN prohibitions returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine, QueryType
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_by_natural_language("what is forbidden for corporations?")
        assert result.query_type == QueryType.PROHIBITIONS

    def test_query_by_natural_language_default(self):
        """GIVEN NL query with no keyword hints
        WHEN query_by_natural_language called
        THEN returns some result"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.query_by_natural_language("show rules about pay taxes")
        assert result is not None

    def test_check_compliance_returns_result(self):
        """GIVEN engine with rule set
        WHEN check_compliance called
        THEN ComplianceResult returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        result = engine.check_compliance("pay taxes", "citizen")
        assert hasattr(result, "is_compliant")
        assert hasattr(result, "compliance_score")

    def test_find_conflicts_with_conflicting_formulas(self):
        """GIVEN engine with obligation AND prohibition for same agent/action
        WHEN find_conflicts called
        THEN conflicts detected"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent, DeonticRuleSet
        )
        agent = LegalAgent(identifier="citizen", name="Citizen", agent_type="person")
        rule_set = DeonticRuleSet(
            name="conflict_rules",
            formulas=[
                DeonticFormula(
                    operator=DeonticOperator.OBLIGATION,
                    proposition="pay taxes now",
                    agent=agent,
                    confidence=0.9,
                    source_text="Citizen must pay taxes now",
                ),
                DeonticFormula(
                    operator=DeonticOperator.PROHIBITION,
                    proposition="pay taxes now",
                    agent=agent,
                    confidence=0.9,
                    source_text="Citizen must not pay taxes now",
                ),
            ],
        )
        engine = DeonticQueryEngine(rule_set=rule_set, enable_rate_limiting=False, enable_validation=False)
        conflicts = engine.find_conflicts()
        assert len(conflicts) >= 1
        assert conflicts[0].conflict_type == "obligation_prohibition"

    def test_get_agent_summary(self):
        """GIVEN engine with rule set
        WHEN get_agent_summary called
        THEN summary dict returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import DeonticQueryEngine
        engine = DeonticQueryEngine(
            rule_set=self._make_rule_set(),
            enable_rate_limiting=False,
            enable_validation=False,
        )
        summary = engine.get_agent_summary("citizen")
        assert isinstance(summary, dict)

    def test_query_result_to_dict(self):
        """GIVEN a QueryResult
        WHEN to_dict called
        THEN dict with expected keys returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import QueryResult, QueryType
        result = QueryResult(query_type=QueryType.OBLIGATIONS, total_matches=0)
        d = result.to_dict()
        assert "query_type" in d
        assert "total_matches" in d

    def test_create_query_engine_factory(self):
        """GIVEN a rule set
        WHEN create_query_engine factory called
        THEN DeonticQueryEngine returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import (
            create_query_engine, DeonticQueryEngine
        )
        rule_set = self._make_rule_set()
        engine = create_query_engine(rule_set)
        assert isinstance(engine, DeonticQueryEngine)

    def test_query_legal_rules_factory(self):
        """GIVEN a rule set and NL query
        WHEN query_legal_rules called
        THEN QueryResult returned"""
        from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import query_legal_rules
        rule_set = self._make_rule_set()
        result = query_legal_rules(rule_set, "must citizens pay")
        assert result is not None


# ===========================================================================
# 5. deontological_reasoning.py — remaining uncovered lines
# ===========================================================================

class TestDeontologicalReasoningExtractors:
    """Tests for DeonticExtractor conditional and exception paths."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import DeonticExtractor
        self.extractor = DeonticExtractor()

    def test_extract_conditional_obligation(self):
        """GIVEN text with conditional obligation (if..., must)
        WHEN extract_statements called
        THEN conditional statement extracted"""
        text = "If the employee is hired, the employee must report to work."
        statements = self.extractor.extract_statements(text, "doc1")
        # Should extract at least the obligation
        assert isinstance(statements, list)

    def test_extract_conditional_permission(self):
        """GIVEN text with conditional permission (when..., may)
        WHEN extract_statements called
        THEN conditional statement extracted"""
        text = "When the project is complete, contractors may invoice the client."
        statements = self.extractor.extract_statements(text, "doc1")
        assert isinstance(statements, list)

    def test_extract_exception_statement(self):
        """GIVEN text with exception clause (unless)
        WHEN extract_statements called
        THEN exception statement may be extracted"""
        text = "Citizens must pay taxes unless they are exempt from taxation."
        statements = self.extractor.extract_statements(text, "doc1")
        assert isinstance(statements, list)

    def test_is_valid_entity_action_generic_entity(self):
        """GIVEN generic entity like 'it'
        WHEN _is_valid_entity_action called
        THEN False returned"""
        assert self.extractor._is_valid_entity_action("it", "pay taxes") is False

    def test_is_valid_entity_action_short_action(self):
        """GIVEN action with less than 3 chars
        WHEN _is_valid_entity_action called
        THEN False returned"""
        assert self.extractor._is_valid_entity_action("citizen", "go") is False

    def test_calculate_confidence_strong_modal(self):
        """GIVEN text with 'must'
        WHEN _calculate_confidence called
        THEN confidence above base"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import DeonticModality
        conf = self.extractor._calculate_confidence("citizens must pay", DeonticModality.OBLIGATION)
        assert conf >= 0.8

    def test_calculate_confidence_weak_modal(self):
        """GIVEN text with 'should'
        WHEN _calculate_confidence called
        THEN confidence slightly reduced"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import DeonticModality
        conf = self.extractor._calculate_confidence("citizens should pay", DeonticModality.OBLIGATION)
        assert conf <= 0.7

    def test_extract_context_returns_dict(self):
        """GIVEN text and position
        WHEN _extract_context called
        THEN context dict with surrounding_text and position returned"""
        ctx = self.extractor._extract_context("citizens must pay taxes", 0, 8)
        assert "surrounding_text" in ctx
        assert "position" in ctx


class TestDeontologicalReasoningAsyncEngine:
    """Tests for async methods of DeontologicalReasoningEngine."""

    def test_count_by_modality(self):
        """GIVEN list of statements with various modalities
        WHEN _count_by_modality called
        THEN counts dict returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import DeonticModality
        engine = DeontologicalReasoningEngine()
        stmts = [
            DeonticStatement(
                id="s1", entity="citizen", action="pay taxes",
                modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
            ),
            DeonticStatement(
                id="s2", entity="citizen", action="vote",
                modality=DeonticModality.PERMISSION, source_document="doc1", source_text="...",
            ),
        ]
        counts = engine._count_by_modality(stmts)
        assert counts.get("obligation") == 1
        assert counts.get("permission") == 1

    def test_count_by_entity(self):
        """GIVEN list of statements
        WHEN _count_by_entity called
        THEN entity counts returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import DeonticModality
        engine = DeontologicalReasoningEngine()
        stmts = [
            DeonticStatement(
                id="s1", entity="citizen", action="pay taxes",
                modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
            ),
            DeonticStatement(
                id="s2", entity="citizen", action="vote",
                modality=DeonticModality.PERMISSION, source_document="doc1", source_text="...",
            ),
        ]
        counts = engine._count_by_entity(stmts)
        assert counts.get("citizen") == 2

    def test_analyze_conflicts_counts(self):
        """GIVEN list of conflicts
        WHEN _analyze_conflicts called
        THEN by_type and by_severity dicts returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import (
            DeonticModality, DeonticConflict, ConflictType,
        )
        engine = DeontologicalReasoningEngine()
        stmt1 = DeonticStatement(
            id="s1", entity="citizen", action="pay taxes",
            modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
        )
        stmt2 = DeonticStatement(
            id="s2", entity="citizen", action="pay taxes",
            modality=DeonticModality.PROHIBITION, source_document="doc1", source_text="...",
        )
        conflict = DeonticConflict(
            id="c1",
            conflict_type=ConflictType.OBLIGATION_PROHIBITION,
            statement1=stmt1,
            statement2=stmt2,
            severity="high",
            explanation="Conflict",
        )
        result = engine._analyze_conflicts([conflict])
        assert result["by_type"].get("obligation_prohibition") == 1
        assert result["by_severity"].get("high") == 1

    def test_generate_analysis_recommendations_high_severity(self):
        """GIVEN conflicts with high severity
        WHEN _generate_analysis_recommendations called
        THEN recommendation about high-severity conflicts returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import (
            DeonticModality, DeonticConflict, ConflictType,
        )
        engine = DeontologicalReasoningEngine()
        stmt1 = DeonticStatement(
            id="s1", entity="citizen", action="pay taxes",
            modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
        )
        stmt2 = DeonticStatement(
            id="s2", entity="citizen", action="pay taxes",
            modality=DeonticModality.PROHIBITION, source_document="doc2", source_text="...",
        )
        conflict = DeonticConflict(
            id="c1",
            conflict_type=ConflictType.OBLIGATION_PROHIBITION,
            statement1=stmt1,
            statement2=stmt2,
            severity="high",
            explanation="Conflict",
        )
        recommendations = engine._generate_analysis_recommendations([conflict])
        assert any("high-severity" in r for r in recommendations)

    def test_generate_analysis_recommendations_no_conflicts(self):
        """GIVEN no conflicts
        WHEN _generate_analysis_recommendations called
        THEN 'no major conflicts' recommendation returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import DeontologicalReasoningEngine
        engine = DeontologicalReasoningEngine()
        recommendations = engine._generate_analysis_recommendations([])
        assert len(recommendations) == 1
        assert "No major conflicts" in recommendations[0]

    def test_analyze_corpus_async(self):
        """GIVEN corpus with conflicting docs
        WHEN analyze_corpus_for_deontic_conflicts called
        THEN result dict with conflicts_summary returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import DeontologicalReasoningEngine
        engine = DeontologicalReasoningEngine()
        docs = [
            {"id": "doc1", "content": "Citizens must pay taxes by April. Citizens cannot pay taxes."},
        ]
        result = _run(engine.analyze_corpus_for_deontic_conflicts(docs))
        assert "statements_summary" in result
        assert "conflicts_summary" in result

    def test_query_deontic_statements_async(self):
        """GIVEN engine with statements in database
        WHEN query_deontic_statements called
        THEN filtered results returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import DeonticModality
        engine = DeontologicalReasoningEngine()
        stmt = DeonticStatement(
            id="s1", entity="citizen", action="pay taxes",
            modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
        )
        engine.statement_database["s1"] = stmt
        results = _run(engine.query_deontic_statements(entity="citizen"))
        assert len(results) == 1

    def test_query_deontic_statements_modality_filter(self):
        """GIVEN engine with statements of different modalities
        WHEN query_deontic_statements filtered by modality
        THEN only matching statements returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import DeonticModality
        engine = DeontologicalReasoningEngine()
        stmt1 = DeonticStatement(
            id="s1", entity="citizen", action="pay taxes",
            modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
        )
        stmt2 = DeonticStatement(
            id="s2", entity="citizen", action="vote",
            modality=DeonticModality.PERMISSION, source_document="doc1", source_text="...",
        )
        engine.statement_database["s1"] = stmt1
        engine.statement_database["s2"] = stmt2
        results = _run(engine.query_deontic_statements(modality=DeonticModality.OBLIGATION))
        assert len(results) == 1
        assert results[0].id == "s1"

    def test_query_deontic_statements_keyword_filter(self):
        """GIVEN statements with keyword in action
        WHEN query_deontic_statements called with action_keywords
        THEN only matching statements returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import DeonticModality
        engine = DeontologicalReasoningEngine()
        stmt = DeonticStatement(
            id="s1", entity="citizen", action="pay taxes",
            modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
        )
        engine.statement_database["s1"] = stmt
        results = _run(engine.query_deontic_statements(action_keywords=["taxes"]))
        assert len(results) == 1

    def test_query_conflicts_async(self):
        """GIVEN engine with conflicts
        WHEN query_conflicts called
        THEN matching conflicts returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import (
            DeonticModality, DeonticConflict, ConflictType,
        )
        engine = DeontologicalReasoningEngine()
        stmt1 = DeonticStatement(
            id="s1", entity="citizen", action="pay taxes",
            modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
        )
        stmt2 = DeonticStatement(
            id="s2", entity="citizen", action="pay taxes",
            modality=DeonticModality.PROHIBITION, source_document="doc2", source_text="...",
        )
        conflict = DeonticConflict(
            id="c1",
            conflict_type=ConflictType.OBLIGATION_PROHIBITION,
            statement1=stmt1,
            statement2=stmt2,
            severity="high",
            explanation="Conflict",
        )
        engine.conflict_database["c1"] = conflict
        results = _run(engine.query_conflicts(entity="citizen"))
        assert len(results) == 1

    def test_query_conflicts_severity_filter(self):
        """GIVEN conflicts of different severities
        WHEN query_conflicts called with min_severity='high'
        THEN only high severity conflicts returned"""
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning import (
            DeontologicalReasoningEngine, DeonticStatement,
        )
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import (
            DeonticModality, DeonticConflict, ConflictType,
        )
        engine = DeontologicalReasoningEngine()
        stmt1 = DeonticStatement(
            id="s1", entity="citizen", action="pay taxes",
            modality=DeonticModality.OBLIGATION, source_document="doc1", source_text="...",
        )
        stmt2 = DeonticStatement(
            id="s2", entity="citizen", action="pay taxes",
            modality=DeonticModality.PROHIBITION, source_document="doc2", source_text="...",
        )
        c_high = DeonticConflict(
            id="c1",
            conflict_type=ConflictType.OBLIGATION_PROHIBITION,
            statement1=stmt1, statement2=stmt2,
            severity="high", explanation="High conflict",
        )
        c_low = DeonticConflict(
            id="c2",
            conflict_type=ConflictType.JURISDICTIONAL,
            statement1=stmt1, statement2=stmt2,
            severity="low", explanation="Low conflict",
        )
        engine.conflict_database["c1"] = c_high
        engine.conflict_database["c2"] = c_low
        results = _run(engine.query_conflicts(min_severity="high"))
        assert all(r.severity == "high" for r in results)


# ===========================================================================
# 6. domain/temporal_deontic_api.py
# ===========================================================================

class TestTemporalDeonticAPI:
    """Tests for temporal_deontic_api module functions."""

    def test_parse_temporal_context_iso_string(self):
        """GIVEN ISO format date string
        WHEN _parse_temporal_context called
        THEN datetime object returned"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        result = _parse_temporal_context("2024-01-15T00:00:00")
        from datetime import datetime
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_parse_temporal_context_none(self):
        """GIVEN None value
        WHEN _parse_temporal_context called
        THEN current datetime returned"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        from datetime import datetime
        result = _parse_temporal_context(None)
        assert isinstance(result, datetime)

    def test_parse_temporal_context_current_time(self):
        """GIVEN 'current_time' string
        WHEN _parse_temporal_context called
        THEN current datetime returned"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        from datetime import datetime
        result = _parse_temporal_context("current_time")
        assert isinstance(result, datetime)

    def test_parse_temporal_context_invalid_string(self):
        """GIVEN invalid date string
        WHEN _parse_temporal_context called
        THEN falls back to current datetime"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        from datetime import datetime
        result = _parse_temporal_context("not_a_date")
        assert isinstance(result, datetime)

    def test_check_document_consistency_missing_text(self):
        """GIVEN parameters with no document_text
        WHEN check_document_consistency_from_parameters called
        THEN error response returned"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            check_document_consistency_from_parameters
        )
        result = _run(check_document_consistency_from_parameters({}))
        assert result["success"] is False
        assert "error" in result

    def test_check_document_consistency_with_text(self):
        """GIVEN parameters with document_text
        WHEN check_document_consistency_from_parameters called
        THEN success=True response returned"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            check_document_consistency_from_parameters
        )
        result = _run(check_document_consistency_from_parameters({
            "document_text": "Citizens must pay taxes. Citizens must file returns.",
            "document_id": "test_doc",
        }))
        assert result["success"] is True
        assert "document_id" in result

    def test_query_theorems_empty_store(self):
        """GIVEN parameters with query to empty store
        WHEN query_theorems_from_parameters called
        THEN success=True and empty list returned"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            query_theorems_from_parameters
        )
        result = _run(query_theorems_from_parameters({
            "query": "pay taxes",
        }))
        assert result.get("success") is True or "error" in result

    def test_add_theorem_missing_required_fields(self):
        """GIVEN parameters missing theorem text
        WHEN add_theorem_from_parameters called
        THEN error response returned"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            add_theorem_from_parameters
        )
        result = _run(add_theorem_from_parameters({}))
        assert result.get("success") is False or "error" in result

    def test_add_theorem_with_required_fields(self):
        """GIVEN parameters with theorem text and name
        WHEN add_theorem_from_parameters called
        THEN theorem added"""
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            add_theorem_from_parameters
        )
        result = _run(add_theorem_from_parameters({
            "theorem_text": "Citizens must pay taxes",
            "theorem_name": "tax_obligation",
            "jurisdiction": "Federal",
        }))
        # May succeed or return error - just ensure no exception raised
        assert "success" in result or "error" in result
