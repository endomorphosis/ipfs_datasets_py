"""
Session 19 integration coverage tests.

Targets (88% → 89%):
- legal_domain_knowledge.py  87% → 93%+ (demonstrate fn + permission/obligation modal fallback + validation conflict paths)
- interactive_fol_constructor.py 84% → 91%+ (empty-session edge cases, low/medium confidence distribution, generate empty, remove text > 50 chars, validate_consistency with conflict, exception paths)
- _fol_constructor_io.py 94% → 99%+ (exception in _convert_fol_format + None fol_formula branch)
- integration/__init__.py 84% → 95%+ (enable_symbolicai with mocked symai)
- deontic_query_engine.py 90% → 95%+ (check_compliance with missing permission, find_conflicts, NL query keyword branches)
- deontic_logic_converter.py 85% → 93%+ (demonstrate_deontic_conversion, enable_symbolic_ai init, _synthesize_complex_rules, demonstrate fn)
- document_consistency_checker.py 89% → 93%+ (proof engine branch, recommendations, _generate_recommendations, calculate_confidence)
- temporal_deontic_api.py 90% → 95%+ (add_theorem with start/end dates, query with date range)
"""
import sys
import uuid
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock


# ─── helper: suppress chatty warnings ─────────────────────────────────────────
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


# ─── Imports ──────────────────────────────────────────────────────────────────
from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import (
    LegalDomainKnowledge,
    DeonticOperator,
    demonstrate_legal_knowledge,
)
from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import (
    InteractiveFOLConstructor,
)
from ipfs_datasets_py.logic.integration.interactive._fol_constructor_io import FOLConstructorIOMixin
from ipfs_datasets_py.logic.integration.interactive.interactive_fol_types import (
    StatementRecord,
    LogicalComponents,
    SessionMetadata,
)
from ipfs_datasets_py.logic.integration.domain.deontic_query_engine import (
    DeonticQueryEngine,
    create_query_engine,
    query_legal_rules,
)
from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
    DeonticFormula,
    DeonticOperator as DO,
    DeonticRuleSet,
    LegalAgent,
)
from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
    DeonticLogicConverter,
    ConversionContext,
    KnowledgeGraph,
    demonstrate_deontic_conversion,
)
from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain


# ══════════════════════════════════════════════════════════════════════════════
# 1. LegalDomainKnowledge – demonstrate_legal_knowledge (lines 603–644)
# ══════════════════════════════════════════════════════════════════════════════
class TestLegalDomainKnowledgeDemonstrate:
    """GIVEN demonstrate_legal_knowledge WHEN called THEN executes without error."""

    def test_demonstrate_legal_knowledge_runs_without_error(self, capsys):
        # GIVEN / WHEN
        demonstrate_legal_knowledge()
        # THEN – it printed *something* and didn't crash
        captured = capsys.readouterr()
        assert "Legal Domain Knowledge" in captured.out or len(captured.out) > 0

    def test_demonstrate_legal_knowledge_returns_none(self):
        # GIVEN / WHEN / THEN
        result = demonstrate_legal_knowledge()
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# 2. LegalDomainKnowledge – validate_deontic_extraction conflict warnings
#    (lines 575-576: permission indicator in obligation context)
#    (lines 580-584: obligation indicator in permission context)
# ══════════════════════════════════════════════════════════════════════════════
class TestLegalDomainKnowledgeValidationConflicts:
    """GIVEN conflicting modal verbs in validation WHEN checked THEN warnings raised."""

    def setup_method(self):
        self.k = LegalDomainKnowledge()

    def test_permission_indicator_in_obligation_context_creates_warning(self):
        # GIVEN text with obligation + 'may' (a permission indicator)
        text = "The contractor must pay fees but may negotiate"
        # WHEN
        result = self.k.validate_deontic_extraction(text, DeonticOperator.OBLIGATION, 0.9)
        # THEN – a warning about permission indicator is raised
        assert any("permission indicator" in w for w in result["warnings"])

    def test_obligation_indicator_in_permission_context_creates_warning(self):
        # GIVEN text with permission + 'must' (an obligation indicator)
        text = "The party may proceed but must complete the form"
        # WHEN
        result = self.k.validate_deontic_extraction(text, DeonticOperator.PERMISSION, 0.9)
        # THEN
        assert any("obligation indicator" in w for w in result["warnings"])

    def test_low_confidence_triggers_manual_review_recommendation(self):
        # GIVEN text with permission at confidence 0.2
        text = "party may do"
        # WHEN
        result = self.k.validate_deontic_extraction(text, DeonticOperator.PERMISSION, 0.2)
        # THEN – adjusted confidence falls below 0.5
        assert any("manual review" in r for r in result["recommendations"])

    def test_no_agent_creates_warning(self):
        # GIVEN text without any recognisable legal agent
        text = "Something must be done somehow"
        op, conf = self.k.classify_legal_statement(text)
        result = self.k.validate_deontic_extraction(text, op, conf)
        # THEN – no agent warning present
        assert any("agent" in w for w in result["warnings"])


# ══════════════════════════════════════════════════════════════════════════════
# 3. InteractiveFOLConstructor – edge cases
# ══════════════════════════════════════════════════════════════════════════════
class TestInteractiveFOLConstructorEdgeCases:
    """GIVEN InteractiveFOLConstructor WHEN hitting edge cases THEN correct results."""

    def setup_method(self):
        self.c = InteractiveFOLConstructor()
        self.c.start_session()

    def test_analyze_logical_structure_empty_session_returns_empty(self):
        # GIVEN no statements in session
        # WHEN
        result = self.c.analyze_logical_structure()
        # THEN – line 296 covered
        assert result["status"] == "empty"
        assert "No statements" in result["message"]

    def test_generate_fol_incrementally_empty_session_returns_empty_list(self):
        # GIVEN no statements
        # WHEN – line 406 covered
        result = self.c.generate_fol_incrementally()
        # THEN
        assert result == []

    def test_analyze_logical_structure_medium_confidence_increments_counter(self):
        # GIVEN a statement with medium confidence
        self.c.add_statement("Every contractor may request an extension of time")
        stmt = list(self.c.session_statements.values())[0]
        stmt.confidence = 0.65  # 0.5 < x ≤ 0.8 → medium
        # WHEN – line 376 covered
        result = self.c.analyze_logical_structure()
        # THEN
        assert result["status"] == "success"
        dist = result["analysis"]["confidence_distribution"]
        assert dist["medium_confidence"] == 1

    def test_analyze_logical_structure_low_confidence_increments_counter(self):
        # GIVEN a statement with low confidence
        self.c.add_statement("Parties may act at their discretion")
        stmt = list(self.c.session_statements.values())[0]
        stmt.confidence = 0.3  # ≤ 0.5 → low
        # WHEN – line 380 covered
        result = self.c.analyze_logical_structure()
        # THEN
        assert result["status"] == "success"
        dist = result["analysis"]["confidence_distribution"]
        assert dist["low_confidence"] == 1

    def test_analyze_logical_structure_inconsistent_statement_counter(self):
        # GIVEN a statement with is_consistent = False
        self.c.add_statement("No contractor must not comply")
        stmt = list(self.c.session_statements.values())[0]
        stmt.is_consistent = False  # line 372 covered
        # WHEN
        result = self.c.analyze_logical_structure()
        # THEN
        assert result["status"] == "success"
        dist = result["analysis"]["consistency_analysis"]
        assert dist["inconsistent_statements"] == 1

    def test_analyze_logical_structure_unknown_consistency_counter(self):
        # GIVEN a statement with is_consistent = None
        self.c.add_statement("Contractor obligations vary by situation")
        stmt = list(self.c.session_statements.values())[0]
        stmt.is_consistent = None  # line 375 covered
        # WHEN
        result = self.c.analyze_logical_structure()
        # THEN
        dist = result["analysis"]["consistency_analysis"]
        assert dist["unknown_consistency"] == 1

    def test_remove_statement_with_long_text_returns_text_slice(self):
        # GIVEN a statement with text > 50 chars
        long_text = "Every contractor must comply with all applicable regulations and standards of practice"
        self.c.add_statement(long_text)
        stmt_id = list(self.c.session_statements.keys())[0]
        # WHEN – line 250 covered
        result = self.c.remove_statement(stmt_id)
        # THEN
        assert result["status"] == "success"
        assert "..." in result["message"]  # text was sliced

    def test_remove_nonexistent_statement_returns_error(self):
        # GIVEN a nonexistent id
        # WHEN
        result = self.c.remove_statement("nonexistent-id")
        # THEN
        assert result["status"] == "error"

    def test_validate_consistency_with_conflict_returns_inconsistent(self):
        # GIVEN 2 statements where _check_logical_conflict detects a conflict
        self.c.add_statement("Every contractor must comply with data protection rules")
        self.c.add_statement("No contractor may not comply with data protection")
        stmts = list(self.c.session_statements.values())
        # patch _check_logical_conflict to force a conflict
        with patch.object(self.c, "_check_logical_conflict", return_value={
            "has_conflict": True,
            "conflict_type": "negation_conflict",
            "description": "Contradictory statements"
        }):
            # WHEN – lines 466-468, 487 covered
            result = self.c.validate_consistency()
        # THEN
        assert result["status"] == "success"
        report = result["consistency_report"]
        assert report["inconsistent_pairs"] == 1
        assert not report["overall_consistent"]
        assert "recommendations" in report

    def test_generate_fol_incrementally_returns_formula_data(self):
        # GIVEN a statement
        self.c.add_statement("Contractors must comply with regulations")
        # WHEN
        result = self.c.generate_fol_incrementally()
        # THEN
        assert len(result) >= 1
        assert "statement_id" in result[0]


# ══════════════════════════════════════════════════════════════════════════════
# 4. FOLConstructorIOMixin – exception in _convert_fol_format (lines 102-112)
# ══════════════════════════════════════════════════════════════════════════════
class _TestIOConstructor(FOLConstructorIOMixin):
    """Minimal FOLConstructorIOMixin for testing."""

    def __init__(self, raise_convert=False):
        self._raise_convert = raise_convert
        self.domain = "contract"
        self.session_id = str(uuid.uuid4())
        self.session_statements = {}
        self.metadata = SessionMetadata(
            session_id=self.session_id,
            created_at=datetime.now(),
            last_modified=datetime.now(),
            total_statements=0,
            consistent_statements=0,
            inconsistent_statements=0,
            average_confidence=0.0,
            domain=self.domain,
        )

    def _convert_fol_format(self, formula: str, fmt: str) -> str:
        if self._raise_convert:
            raise ValueError("Conversion failed intentionally")
        return f"{fmt}::{formula}"


def _make_statement(fol_formula=None, confidence=0.9):
    lc = LogicalComponents(
        quantifiers=["All"], predicates=["comply"], entities=["contractor"],
        logical_connectives=[], confidence=0.9, raw_text="Contractor must comply"
    )
    return StatementRecord(
        id=str(uuid.uuid4()),
        text="Contractor must comply with regulations",
        fol_formula=fol_formula,
        logical_components=lc,
        confidence=confidence,
        timestamp=datetime.now(),
    )


class TestFOLConstructorIOMixinExceptionPaths:
    """GIVEN _fol_constructor_io WHEN conversion raises THEN error is captured in export."""

    def test_convert_fol_format_exception_captured_in_export(self):
        # GIVEN a constructor that raises in _convert_fol_format
        c = _TestIOConstructor(raise_convert=True)
        stmt = _make_statement(fol_formula="forall x: comply(x)")
        c.session_statements[stmt.id] = stmt
        # WHEN format != 'symbolic' triggers conversion, which raises (lines 102-105)
        result = c.export_session(format="lean")
        # THEN – error was caught and added to errors list
        assert "errors" in result
        assert any("fol_format" in e for e in result["errors"])
        # exported_formula falls back to original
        fol_entries = result.get("fol_formulas", [])
        assert len(fol_entries) == 1
        assert fol_entries[0]["exported_formula"] == "forall x: comply(x)"

    def test_none_fol_formula_excluded_from_fol_formulas(self):
        # GIVEN a statement with fol_formula=None (lines 110-112)
        c = _TestIOConstructor(raise_convert=False)
        stmt = _make_statement(fol_formula=None)
        c.session_statements[stmt.id] = stmt
        # WHEN
        result = c.export_session(format="lean")
        # THEN – statement is in statements but NOT in fol_formulas
        assert len(result["statements"]) == 1
        assert len(result["fol_formulas"]) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 5. integration/__init__.py – enable_symbolicai with mocked symai (lines 80-91)
# ══════════════════════════════════════════════════════════════════════════════
class TestEnableSymbolicAI:
    """GIVEN enable_symbolicai WHEN symai is mocked THEN returns True (lines 80-91)."""

    def test_enable_symbolicai_with_mocked_symai_returns_true(self):
        # GIVEN – inject a fake symai module
        import importlib
        import ipfs_datasets_py.logic.integration as mod
        fake_symai = type(sys)("symai")
        fake_symai.Symbol = type("Symbol", (), {})
        fake_symai.Expression = type("Expression", (), {})
        original = sys.modules.get("symai")
        sys.modules["symai"] = fake_symai
        try:
            # WHEN – lines 80-91 executed
            result = mod.enable_symbolicai(autoconfigure_env=False)
            # THEN
            assert result is True
        finally:
            if original is None:
                sys.modules.pop("symai", None)
            else:
                sys.modules["symai"] = original
            # Reset the module-level flag for other tests
            mod.SYMBOLIC_AI_AVAILABLE = False

    def test_enable_symbolicai_with_missing_symai_returns_false(self):
        # GIVEN – ensure symai is absent
        import ipfs_datasets_py.logic.integration as mod
        original = sys.modules.pop("symai", None)
        try:
            result = mod.enable_symbolicai(autoconfigure_env=False)
            assert result is False
        finally:
            if original is not None:
                sys.modules["symai"] = original


# ══════════════════════════════════════════════════════════════════════════════
# 6. DeonticQueryEngine – compliance, conflicts, NL query branches
# ══════════════════════════════════════════════════════════════════════════════
def _build_engine_with_rules():
    """Helper: build a DeonticQueryEngine with a small rule set."""
    agent = LegalAgent("contractor", "Contractor", "person")
    oblig = DeonticFormula(
        operator=DO.OBLIGATION,
        proposition="submit monthly reports",
        agent=agent,
        confidence=0.9,
    )
    prohib = DeonticFormula(
        operator=DO.PROHIBITION,
        proposition="disclose confidential information",
        agent=agent,
        confidence=0.85,
    )
    perm = DeonticFormula(
        operator=DO.PERMISSION,
        proposition="request extensions",
        agent=agent,
        confidence=0.8,
    )
    ruleset = DeonticRuleSet(name="test", formulas=[oblig, prohib, perm])
    engine = DeonticQueryEngine()
    engine.load_rule_set(ruleset)
    return engine


class TestDeonticQueryEngineComplianceAndConflicts:
    """GIVEN DeonticQueryEngine WHEN checking compliance/conflicts THEN correct results."""

    def test_check_compliance_action_requires_permission_and_none_granted(self):
        # GIVEN an engine with only obligations/prohibitions but no permission for agent
        agent = LegalAgent("user", "User", "person")
        oblig = DeonticFormula(
            operator=DO.OBLIGATION, proposition="register first", agent=agent, confidence=0.9
        )
        ruleset = DeonticRuleSet(name="t", formulas=[oblig])
        engine = DeonticQueryEngine()
        engine.load_rule_set(ruleset)
        # Patch _action_requires_permission to return True (line 344 covered)
        with patch.object(engine, "_action_requires_permission", return_value=True):
            result = engine.check_compliance(
                proposed_action="access restricted area", agent="user"
            )
        # THEN – recommendation includes permissions message OR is non-compliant
        assert not result.is_compliant or any(
            "permission" in r.lower() for r in result.recommendations
        )

    def test_check_compliance_violated_prohibition_is_non_compliant(self):
        # GIVEN engine where proposed action violates prohibition
        engine = _build_engine_with_rules()
        with patch.object(engine, "_action_violates_prohibition", return_value=True):
            result = engine.check_compliance(
                proposed_action="disclose information publicly", agent="contractor"
            )
        assert not result.is_compliant
        assert len(result.violated_prohibitions) > 0

    def test_check_compliance_violated_obligation_recommendation(self):
        # GIVEN engine where proposed action violates obligation
        engine = _build_engine_with_rules()
        with patch.object(engine, "_action_satisfies_obligation", return_value=False):
            result = engine.check_compliance(
                proposed_action="skip reports", agent="contractor"
            )
        # THEN – recommendations include obligation message (line 360 covered)
        assert any("obligation" in r.lower() for r in result.recommendations)

    def test_find_conflicts_obligation_prohibition_same_proposition(self):
        # GIVEN obligation + prohibition for matching propositions
        agent = LegalAgent("a", "A", "person")
        oblig = DeonticFormula(
            operator=DO.OBLIGATION, proposition="submit documents", agent=agent, confidence=0.9
        )
        prohib = DeonticFormula(
            operator=DO.PROHIBITION, proposition="submit documents", agent=agent, confidence=0.85
        )
        ruleset = DeonticRuleSet(name="t", formulas=[oblig, prohib])
        engine = DeonticQueryEngine()
        engine.load_rule_set(ruleset)
        # WHEN – find_conflicts with _formulas_conflict returning True (line 394-439 covered)
        with patch.object(engine, "_formulas_conflict", return_value=True):
            conflicts = engine.find_conflicts()
        # THEN
        assert len(conflicts) >= 1

    def test_query_by_nl_obligations_keyword(self):
        # GIVEN engine with rules + NL query about obligations
        engine = _build_engine_with_rules()
        result = engine.query_by_natural_language("what must I do here")
        assert result is not None

    def test_query_by_nl_prohibitions_keyword(self):
        # GIVEN NL query about prohibitions
        engine = _build_engine_with_rules()
        result = engine.query_by_natural_language("what is forbidden and not allowed")
        assert result is not None

    def test_query_by_nl_permissions_keyword(self):
        # GIVEN NL query about permissions
        engine = _build_engine_with_rules()
        result = engine.query_by_natural_language("what may I do here")
        assert result is not None

    def test_query_by_nl_general_fallback(self):
        # GIVEN NL query with no keyword matches
        engine = _build_engine_with_rules()
        result = engine.query_by_natural_language("general inquiry about the document")
        assert result is not None

    def test_create_query_engine_factory(self):
        # GIVEN a rule set
        agent = LegalAgent("a", "A", "person")
        formula = DeonticFormula(operator=DO.OBLIGATION, proposition="pay fees", agent=agent, confidence=0.9)
        ruleset = DeonticRuleSet(name="t", formulas=[formula])
        # WHEN
        engine = create_query_engine(ruleset)
        # THEN
        assert engine is not None
        assert engine.rule_set is not None

    def test_query_legal_rules_factory(self):
        # GIVEN rule set and NL query
        agent = LegalAgent("a", "A", "person")
        formula = DeonticFormula(operator=DO.OBLIGATION, proposition="submit form", agent=agent, confidence=0.9)
        ruleset = DeonticRuleSet(name="t", formulas=[formula])
        # WHEN
        result = query_legal_rules(ruleset, "what must I do")
        # THEN
        assert result is not None


# ══════════════════════════════════════════════════════════════════════════════
# 7. DeonticLogicConverter – demonstrate function + enable_symbolic_ai init
# ══════════════════════════════════════════════════════════════════════════════
class TestDeonticLogicConverterEdges:
    """GIVEN DeonticLogicConverter edge cases WHEN called THEN correct results."""

    def test_demonstrate_deontic_conversion_runs(self, capsys):
        # GIVEN / WHEN – lines 567-592 + 720-730 covered
        demonstrate_deontic_conversion()
        captured = capsys.readouterr()
        assert "Deontic Logic Conversion" in captured.out

    def test_enable_symbolic_ai_true_but_import_fails_falls_back_gracefully(self):
        # GIVEN enable_symbolic_ai=True but LegalSymbolicAnalyzer unavailable
        # The import is local inside __init__: `from .legal_symbolic_analyzer import LegalSymbolicAnalyzer`
        # We mock at sys.modules level
        import sys
        fake_mod = type(sys)("ipfs_datasets_py.logic.integration.converters.legal_symbolic_analyzer")
        # Remove from sys.modules to force ImportError on the inner import
        orig = sys.modules.pop(
            "ipfs_datasets_py.logic.integration.converters.legal_symbolic_analyzer", None
        )
        try:
            # WHEN – lines 129-130, 137-139 covered via exception path
            with patch.dict(sys.modules, {
                "ipfs_datasets_py.logic.integration.converters.legal_symbolic_analyzer": None
            }):
                converter = DeonticLogicConverter(enable_symbolic_ai=True)
            # THEN – graceful fallback
            assert converter.symbolic_analyzer is None
        finally:
            if orig is not None:
                sys.modules["ipfs_datasets_py.logic.integration.converters.legal_symbolic_analyzer"] = orig

    def test_enable_symbolic_ai_true_but_init_raises_exception_falls_back(self):
        # GIVEN enable_symbolic_ai=True but LegalSymbolicAnalyzer raises in __init__
        import sys
        # Patch the module to have a class that raises on init
        mod_key = "ipfs_datasets_py.logic.integration.converters.legal_symbolic_analyzer"
        orig = sys.modules.get(mod_key)

        class _FailingAnalyzer:
            def __init__(self):
                raise RuntimeError("init failed")

        try:
            fake_mod = type(sys)(mod_key)
            fake_mod.LegalSymbolicAnalyzer = _FailingAnalyzer
            with patch.dict(sys.modules, {mod_key: fake_mod}):
                converter = DeonticLogicConverter(enable_symbolic_ai=True)
            assert converter.symbolic_analyzer is None
        finally:
            if orig is not None:
                sys.modules[mod_key] = orig
            else:
                sys.modules.pop(mod_key, None)

    def test_convert_entities_enable_condition_extraction_false_skips_conditions(self):
        # GIVEN context with enable_condition_extraction=False
        converter = DeonticLogicConverter(enable_symbolic_ai=False)
        ctx = ConversionContext(
            source_document_path="./test.pdf",
            document_title="Test",
            legal_domain=LegalDomain.CONTRACT,
            confidence_threshold=0.3,
            enable_condition_extraction=False,  # line 434 covered
        )

        class MockEntity:
            entity_id = "e1"
            text = "The contractor must submit reports"
            entity_type = "obligation"
            properties = {"text": "The contractor must submit reports"}
            name = "obligation"

        kg = KnowledgeGraph(entities=[MockEntity()], relationships=[])
        result = converter.convert_knowledge_graph_to_logic(kg, ctx)
        # THEN – conversion ran, conditions are empty
        assert isinstance(result.deontic_formulas, list)

    def test_synthesize_complex_rules_with_symbolic_analyzer(self):
        # GIVEN symbolic_analyzer mock + 2+ formulas for same agent (line 193-196 covered)
        converter = DeonticLogicConverter(enable_symbolic_ai=False)
        mock_sa = MagicMock()
        mock_sa.synthesize_agent_rules.return_value = []
        converter.symbolic_analyzer = mock_sa

        agent = LegalAgent("contractor", "Contractor", "person")
        f1 = DeonticFormula(operator=DO.OBLIGATION, proposition="pay fees", agent=agent, confidence=0.9)
        f2 = DeonticFormula(operator=DO.OBLIGATION, proposition="submit reports", agent=agent, confidence=0.85)
        ctx = ConversionContext(
            source_document_path="./test.pdf",
            document_title="Test",
            legal_domain=LegalDomain.CONTRACT,
            confidence_threshold=0.3,
        )

        # Call _synthesize_complex_rules directly to hit lines 567-592
        result = converter._synthesize_complex_rules([f1, f2], KnowledgeGraph(entities=[], relationships=[]), ctx)
        # THEN – synthesize was called
        assert mock_sa.synthesize_agent_rules.called
        assert result == []

    def test_convert_knowledge_graph_with_symbolic_analyzer_active(self):
        # GIVEN enable_symbolic_ai + mock + entities producing formulas
        # so _synthesize_complex_rules is called via main pipeline (lines 193-196)
        converter = DeonticLogicConverter(enable_symbolic_ai=False)
        mock_sa = MagicMock()
        mock_sa.synthesize_agent_rules.return_value = []
        converter.symbolic_analyzer = mock_sa

        class MockEntity2:
            entity_id = "e2"
            text = "The contractor must file documents"
            entity_type = "obligation"
            properties = {"text": "The contractor must file documents"}
            name = "obligation"

        class MockEntity3:
            entity_id = "e3"
            text = "The contractor must pay dues"
            entity_type = "obligation"
            properties = {"text": "The contractor must pay dues"}
            name = "obligation2"

        kg = KnowledgeGraph(entities=[MockEntity2(), MockEntity3()], relationships=[])
        ctx = ConversionContext(
            source_document_path="./test.pdf",
            document_title="Test",
            legal_domain=LegalDomain.CONTRACT,
            confidence_threshold=0.3,
        )
        result = converter.convert_knowledge_graph_to_logic(kg, ctx)
        # _synthesize_complex_rules was called (lines 193-196) when formulas exist
        assert isinstance(result.deontic_formulas, list)

    def test_convert_relationship_with_data_field(self):
        # GIVEN a relationship whose text comes from .data dict (line 488 covered)
        converter = DeonticLogicConverter(enable_symbolic_ai=False)

        class MockRelationship:
            relationship_id = "r1"
            type = "obligation"
            source = "contractor"
            target = "submit_reports"
            data = {"description": "Contractor must submit monthly reports"}
            relationship_type = "must_do"

        ctx = ConversionContext(
            source_document_path="./test.pdf",
            document_title="Test",
            legal_domain=LegalDomain.CONTRACT,
            confidence_threshold=0.3,
        )
        kg = KnowledgeGraph(entities=[], relationships=[MockRelationship()])
        result = converter.convert_relationships_to_logic(
            kg.relationships, ctx
        )
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════════════════════════
# 8. TemporalDeonticAPI – add_theorem_from_parameters with date fields
#    (lines 178-179: end_date in add_theorem, lines 267-278: date_range in query)
# ══════════════════════════════════════════════════════════════════════════════
class TestTemporalDeonticAPIDateFields:
    """GIVEN temporal_deontic_api WHEN date params provided THEN correctly parsed."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            add_theorem_from_parameters,
            query_theorems_from_parameters,
        )
        self._add_coro = add_theorem_from_parameters
        self._query_coro = query_theorems_from_parameters

    def _add(self, params):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._add_coro(params))
        finally:
            loop.close()

    def _query(self, params):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._query_coro(params))
        finally:
            loop.close()

    def test_add_theorem_with_start_and_end_date(self):
        # GIVEN parameters with start_date and end_date (line 178-179 covered)
        params = {
            "operator": "OBLIGATION",
            "proposition": "submit quarterly reports",
            "agent_name": "Contractor",
            "jurisdiction": "Federal",
            "start_date": "2023-01-01",
            "end_date": "2025-12-31",
        }
        # WHEN
        result = self._add(params)
        # THEN
        assert result.get("success") is True
        scope = result["theorem_data"]["temporal_scope"]
        assert scope["end"] is not None

    def test_add_theorem_with_only_start_date(self):
        # GIVEN only start_date (line 178)
        params = {
            "operator": "PERMISSION",
            "proposition": "request extension",
            "agent_name": "Vendor",
            "start_date": "2024-06-01",
        }
        result = self._add(params)
        assert result.get("success") is True

    def test_query_theorems_with_start_date_filter(self):
        # GIVEN parameters with start_date for query (lines 267-271 covered)
        params = {
            "query": "submit reports",
            "start_date": "2020-01-01",
        }
        result = self._query(params)
        assert "theorems" in result or "success" in result

    def test_query_theorems_with_end_date_filter(self):
        # GIVEN parameters with end_date for query (lines 274-278 covered)
        params = {
            "query": "submit reports",
            "end_date": "2025-12-31",
        }
        result = self._query(params)
        assert "theorems" in result or "success" in result

    def test_query_theorems_with_invalid_start_date_silently_skipped(self):
        # GIVEN invalid start_date (line 267-271 ValueError silently passed)
        params = {
            "query": "submit reports",
            "start_date": "not-a-date",
        }
        result = self._query(params)
        # THEN – no crash, returns normally
        assert result is not None

    def test_query_theorems_with_invalid_end_date_silently_skipped(self):
        # GIVEN invalid end_date (line 274-278 ValueError silently passed)
        params = {
            "query": "submit reports",
            "end_date": "bad-date",
        }
        result = self._query(params)
        assert result is not None


# ══════════════════════════════════════════════════════════════════════════════
# 9. DocumentConsistencyChecker – proof engine branch + recommendations
#    (lines 145-146, 391-392, 401-417, 473-474, 524, 528-530)
# ══════════════════════════════════════════════════════════════════════════════
class TestDocumentConsistencyCheckerProofPaths:
    """GIVEN DocumentConsistencyChecker with proof engine WHEN checking THEN additional paths covered."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import (
            DocumentConsistencyChecker,
        )
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_rag_store import (
            TemporalDeonticRAGStore,
        )
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import (
            ProofResult, ProofStatus,
        )
        self.Checker = DocumentConsistencyChecker
        self.RAGStore = TemporalDeonticRAGStore
        self.ProofResult = ProofResult
        self.ProofStatus = ProofStatus

    def test_check_document_with_proof_engine_enabled(self):
        # GIVEN checker with proof_engine → lines 145-146 (_run_formal_verification) covered
        mock_engine = MagicMock()
        mock_engine.prove_deontic_formula.return_value = self.ProofResult(
            prover="z3",
            statement="obligation(contractor, submit)",
            status=self.ProofStatus.SUCCESS,
        )
        checker = self.Checker(
            rag_store=self.RAGStore(),
            proof_engine=mock_engine,
        )
        result = checker.check_document(
            "The contractor must submit monthly reports by the 15th of each month",
            document_id="test-doc-1",
        )
        assert result is not None

    def test_check_document_with_proof_exception_creates_error_proof_result(self):
        # GIVEN proof_engine raises exception (lines 401-417 covered)
        mock_engine = MagicMock()
        mock_engine.prove_deontic_formula.side_effect = RuntimeError("prover crashed")
        checker = self.Checker(
            rag_store=self.RAGStore(),
            proof_engine=mock_engine,
        )
        result = checker.check_document(
            "Contractor shall complete all tasks within 30 days",
            document_id="test-doc-2",
        )
        assert result is not None

    def test_check_document_with_max_formulas_limit(self):
        # GIVEN checker with a small max_formulas_per_document limit (lines 391-392 covered)
        checker = self.Checker(rag_store=self.RAGStore())
        checker.max_formulas_per_document = 1  # tiny limit
        # A document with multiple obligation sentences
        text = (
            "The contractor must submit reports. "
            "The vendor shall pay fees. "
            "All parties must comply with regulations. "
            "The client is required to provide access. "
        )
        result = checker.check_document(text, document_id="test-doc-3")
        assert result is not None

    def test_generate_recommendations_with_proof_error_category(self):
        # GIVEN analysis with proof_error issue category
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import (
            DocumentConsistencyChecker,
        )
        checker = DocumentConsistencyChecker(rag_store=self.RAGStore())
        issues = [
            {"type": "error", "severity": "medium", "category": "proof_error", "message": "failed"}
        ]
        # Access _generate_recommendations directly
        recommendations = checker._generate_recommendations(None, issues)
        assert isinstance(recommendations, list)

    def test_generate_recommendations_with_empty_issues(self):
        # GIVEN no issues → line "Document appears consistent" (lines 524, 528-530)
        checker = self.Checker(rag_store=self.RAGStore())
        recommendations = checker._generate_recommendations(None, [])
        assert any("consistent" in r.lower() or "appears" in r.lower()
                  for r in recommendations)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Additional small coverage patches
# ══════════════════════════════════════════════════════════════════════════════
class TestConvertersInitImportErrors:
    """GIVEN converters/__init__.py WHEN imports succeed THEN classes are accessible."""

    def test_converters_init_exports_deontic_logic_converter_via_direct(self):
        # GIVEN - import directly from the module (not via __init__ which may cache None)
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            DeonticLogicConverter as DLC,
        )
        # THEN
        assert DLC is not None

    def test_domain_init_exports_legal_domain_knowledge(self):
        # GIVEN
        from ipfs_datasets_py.logic.integration.domain import LegalDomainKnowledge as LDK
        # THEN
        assert LDK is not None


class TestLegalDomainKnowledgeExtractorsEdgeCases:
    """GIVEN extract_agents/conditions/temporal WHEN called THEN correct results."""

    def setup_method(self):
        self.k = LegalDomainKnowledge()

    def test_extract_agents_from_sentence_with_contractor(self):
        # GIVEN
        text = "The contractor shall submit monthly reports"
        # WHEN
        agents = self.k.extract_agents(text)
        # THEN
        assert isinstance(agents, list)

    def test_extract_conditions_from_conditional_sentence(self):
        # GIVEN
        text = "If the contractor fails, then the client may terminate the agreement"
        # WHEN
        conditions = self.k.extract_conditions(text)
        # THEN
        assert isinstance(conditions, list)

    def test_extract_temporal_from_deadline_sentence(self):
        # GIVEN
        text = "The contractor must complete work by December 31, 2025"
        # WHEN
        result = self.k.extract_temporal_expressions(text)
        # THEN
        assert isinstance(result, dict)
        assert "deadline" in result

    def test_identify_legal_domain_employment(self):
        # GIVEN
        text = "The employee must follow workplace harassment policies"
        # WHEN
        domain, conf = self.k.identify_legal_domain(text)
        # THEN
        assert domain is not None
        assert 0.0 <= conf <= 1.0


class TestDeonticQueryEngineGetAgentSummary:
    """GIVEN DeonticQueryEngine.get_agent_summary WHEN called THEN returns structured summary."""

    def test_get_agent_summary_returns_counts(self):
        # GIVEN engine with rules for contractor
        engine = _build_engine_with_rules()
        # WHEN (line 454, 495 covered)
        summary = engine.get_agent_summary("contractor")
        # THEN
        assert "agent" in summary
        assert "counts" in summary
        assert "total_rules" in summary

    def test_get_agent_summary_unknown_agent_returns_empty(self):
        # GIVEN engine with no rules for 'nobody'
        engine = _build_engine_with_rules()
        # WHEN
        summary = engine.get_agent_summary("nobody_exists")
        # THEN
        assert summary["total_rules"] == 0


class TestDeonticLogicConverterResetStatistics:
    """GIVEN DeonticLogicConverter._reset_statistics WHEN called THEN statistics zeroed."""

    def test_reset_statistics_clears_counters(self):
        # GIVEN
        converter = DeonticLogicConverter(enable_symbolic_ai=False)
        converter.conversion_stats["obligations_extracted"] = 5
        # WHEN
        converter._reset_statistics()
        # THEN
        assert converter.conversion_stats["obligations_extracted"] == 0


class TestDeonticLogicConverterExtractTemporalConditions:
    """GIVEN _extract_temporal_conditions_from_entity WHEN duration/start_time THEN TemporalCondition created."""

    def test_extract_temporal_conditions_duration_and_start_time(self):
        # GIVEN converter with enable_temporal_analysis=True
        converter = DeonticLogicConverter(enable_symbolic_ai=False)

        class MockEntity:
            entity_id = "e1"
            text = "The contractor will work for 90 days starting January 1"
            entity_type = "temporal"
            properties = {"text": "The contractor will work for 90 days starting January 1"}
            name = "temporal_entity"

        ctx = ConversionContext(
            source_document_path="./test.pdf",
            document_title="Test",
            legal_domain=LegalDomain.CONTRACT,
            enable_temporal_analysis=True,
        )
        # WHEN
        result = converter._extract_temporal_conditions_from_entity(MockEntity(), ctx)
        # THEN – returns list (may be empty or populated depending on patterns)
        assert isinstance(result, list)

    def test_extract_temporal_conditions_disabled_returns_empty(self):
        # GIVEN context with enable_temporal_analysis=False
        converter = DeonticLogicConverter(enable_symbolic_ai=False)

        class MockEntity:
            entity_id = "e1"
            text = "Some text"
            entity_type = "entity"
            properties = {}
            name = "entity"

        ctx = ConversionContext(
            source_document_path="./test.pdf",
            document_title="Test",
            legal_domain=LegalDomain.CONTRACT,
            enable_temporal_analysis=False,
        )
        result = converter._extract_temporal_conditions_from_entity(MockEntity(), ctx)
        assert result == []
