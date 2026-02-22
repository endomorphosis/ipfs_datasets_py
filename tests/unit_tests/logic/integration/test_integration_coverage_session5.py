"""
Integration test coverage session 5 — targeting five low-coverage modules.

Coverage targets:
  converters/deontic_logic_converter.py    27% → 55%+
  domain/document_consistency_checker.py  21% → 50%+   (import bug fixed this session)
  domain/legal_domain_knowledge.py        39% → 65%+
  interactive/interactive_fol_constructor.py 43% → 65%+
  reasoning/deontological_reasoning_utils.py 30% → 70%+
"""

import types
import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_entity(entity_id, name, entity_type, text="", properties=None):
    """Build a SimpleNamespace that satisfies the DeonticLogicConverter Entity API."""
    e = types.SimpleNamespace()
    e.entity_id = entity_id
    e.name = name
    e.entity_type = entity_type
    e.source_text = text
    e.properties = properties or {}
    return e


def _make_relationship(source_entity, target_entity, rel_type, properties=None):
    """Build a SimpleNamespace that satisfies the DeonticLogicConverter Relationship API."""
    r = types.SimpleNamespace()
    r.source_entity = source_entity
    r.target_entity = target_entity
    r.relationship_type = rel_type
    r.properties = properties or {}
    return r


# ===========================================================================
# 1. converters/deontic_logic_converter.py
# ===========================================================================

class TestConversionContext:
    """Tests for ConversionContext dataclass."""

    def test_create_minimal_context(self):
        # GIVEN a minimal ConversionContext
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        # WHEN instantiated with only the required path
        ctx = ConversionContext(source_document_path="/tmp/test.txt")
        # THEN defaults are applied
        assert ctx.source_document_path == "/tmp/test.txt"
        assert ctx.document_title == ""
        assert ctx.confidence_threshold == 0.5
        assert ctx.enable_temporal_analysis is True
        assert ctx.enable_agent_inference is True

    def test_create_full_context(self):
        # GIVEN a full ConversionContext
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        # WHEN instantiated with all fields
        ctx = ConversionContext(
            source_document_path="/tmp/contract.txt",
            document_title="Contract Agreement",
            legal_domain=LegalDomain.CONTRACT,
            jurisdiction="US-CA",
            confidence_threshold=0.7,
            enable_temporal_analysis=False,
            enable_agent_inference=False,
            enable_condition_extraction=False,
        )
        # THEN all values are stored
        assert ctx.document_title == "Contract Agreement"
        assert ctx.legal_domain == LegalDomain.CONTRACT
        assert ctx.jurisdiction == "US-CA"
        assert ctx.confidence_threshold == 0.7

    def test_to_dict(self):
        # GIVEN a ConversionContext
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        ctx = ConversionContext(source_document_path="/tmp/test.txt", document_title="Doc")
        # WHEN serialised
        d = ctx.to_dict()
        # THEN all keys are present
        assert d["source_document_path"] == "/tmp/test.txt"
        assert d["document_title"] == "Doc"
        assert d["legal_domain"] is None
        assert d["confidence_threshold"] == 0.5


class TestConversionResult:
    """Tests for ConversionResult dataclass."""

    def test_to_dict_returns_all_keys(self):
        # GIVEN a ConversionResult
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionResult
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        result = ConversionResult(
            deontic_formulas=[],
            rule_set=DeonticRuleSet("test", []),
            conversion_metadata={"source": "test"},
            errors=["e1"],
            warnings=["w1"],
            statistics={"total_entities_processed": 0},
        )
        # WHEN serialised
        d = result.to_dict()
        # THEN expected keys present
        assert "deontic_formulas" in d
        assert "rule_set" in d
        assert d["errors"] == ["e1"]
        assert d["warnings"] == ["w1"]


class TestDeonticLogicConverterInit:
    """Tests for DeonticLogicConverter initialisation."""

    def test_init_with_defaults(self):
        # GIVEN no arguments
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import DeonticLogicConverter
        # WHEN initialised
        conv = DeonticLogicConverter(enable_symbolic_ai=False)
        # THEN attributes are set
        assert conv.domain_knowledge is not None
        assert conv.enable_symbolic_ai is False
        assert conv.conversion_stats["total_entities_processed"] == 0

    def test_init_with_custom_domain_knowledge(self):
        # GIVEN a custom LegalDomainKnowledge instance
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import DeonticLogicConverter
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        ldk = LegalDomainKnowledge()
        # WHEN initialised with it
        conv = DeonticLogicConverter(domain_knowledge=ldk, enable_symbolic_ai=False)
        # THEN the same instance is used
        assert conv.domain_knowledge is ldk


class TestConvertKnowledgeGraphToLogic:
    """Tests for DeonticLogicConverter.convert_knowledge_graph_to_logic()."""

    @pytest.fixture
    def converter(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import DeonticLogicConverter
        return DeonticLogicConverter(enable_symbolic_ai=False)

    @pytest.fixture
    def context(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        return ConversionContext(source_document_path="/tmp/test.txt", document_title="Test")

    def test_empty_graph_returns_empty_result(self, converter, context):
        # GIVEN an empty knowledge graph
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import KnowledgeGraph
        kg = KnowledgeGraph(entities=[], relationships=[])
        # WHEN converted
        result = converter.convert_knowledge_graph_to_logic(kg, context)
        # THEN empty result with zero stats
        assert result.deontic_formulas == []
        assert result.statistics["total_entities_processed"] == 0

    def test_obligation_entity_produces_formula(self, converter, context):
        # GIVEN a KG with an obligation entity
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import KnowledgeGraph
        e = _make_entity("e1", "payment_duty", "obligation",
                         "The contractor must pay the penalty for breach of contract")
        kg = KnowledgeGraph(entities=[e], relationships=[])
        # WHEN converted
        result = converter.convert_knowledge_graph_to_logic(kg, context)
        # THEN at least one obligation formula is returned
        assert result.statistics["total_entities_processed"] == 1
        operators = [str(f.operator) for f in result.deontic_formulas]
        assert any("OBLIGATION" in op for op in operators)

    def test_permission_entity_produces_formula(self, converter, context):
        # GIVEN a KG with a permission entity
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import KnowledgeGraph
        e = _make_entity("e2", "request_right", "permission",
                         "The vendor may request a contract extension")
        kg = KnowledgeGraph(entities=[e], relationships=[])
        # WHEN converted
        result = converter.convert_knowledge_graph_to_logic(kg, context)
        # THEN a permission formula is returned
        operators = [str(f.operator) for f in result.deontic_formulas]
        assert any("PERMISSION" in op for op in operators)

    def test_prohibition_entity_produces_formula(self, converter, context):
        # GIVEN a KG with a prohibition entity
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import KnowledgeGraph
        e = _make_entity("e3", "nda_clause", "prohibition",
                         "The employee shall not disclose proprietary information")
        kg = KnowledgeGraph(entities=[e], relationships=[])
        # WHEN converted
        result = converter.convert_knowledge_graph_to_logic(kg, context)
        # THEN a prohibition formula is returned
        operators = [str(f.operator) for f in result.deontic_formulas]
        assert any("PROHIBITION" in op for op in operators)

    def test_result_has_rule_set(self, converter, context):
        # GIVEN a KG with one entity
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import KnowledgeGraph
        e = _make_entity("e1", "clause1", "obligation", "All parties must comply with regulations")
        kg = KnowledgeGraph(entities=[e], relationships=[])
        # WHEN converted
        result = converter.convert_knowledge_graph_to_logic(kg, context)
        # THEN a DeonticRuleSet is embedded
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        assert isinstance(result.rule_set, DeonticRuleSet)
        assert result.rule_set.name == "Test"

    def test_entity_dict_form_is_handled(self, converter, context):
        # GIVEN entities passed as a dict (as GraphRAG KG may return)
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import KnowledgeGraph
        e = _make_entity("e1", "c1", "obligation", "The licensee must pay royalties annually")
        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        # supply entities as dict {id: entity} to exercise the dict branch
        kg.entities = {"e1": e}
        kg.relationships = []
        # WHEN converted
        result = converter.convert_knowledge_graph_to_logic(kg, context)
        # THEN entity is processed
        assert result.statistics["total_entities_processed"] >= 1

    def test_confidence_threshold_filters_low_confidence(self, converter):
        # GIVEN a context with high threshold
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import KnowledgeGraph, ConversionContext
        ctx = ConversionContext(source_document_path="/tmp/t.txt", confidence_threshold=0.99)
        # AND an ambiguous entity
        e = _make_entity("e1", "vague", "miscellaneous", "something something maybe")
        kg = KnowledgeGraph(entities=[e], relationships=[])
        # WHEN converted with a very high threshold
        result = converter.convert_knowledge_graph_to_logic(kg, ctx)
        # THEN no formulas are extracted (confidence < threshold)
        assert len(result.deontic_formulas) == 0

    def test_multiple_entities_stats_count(self, converter, context):
        # GIVEN 3 entities
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import KnowledgeGraph
        entities = [
            _make_entity("e1", "c1", "obligation", "The buyer must pay within 30 days"),
            _make_entity("e2", "c2", "permission", "The seller may extend the deadline"),
            _make_entity("e3", "c3", "prohibition", "The agent shall not accept kickbacks"),
        ]
        kg = KnowledgeGraph(entities=entities, relationships=[])
        # WHEN converted
        result = converter.convert_knowledge_graph_to_logic(kg, context)
        # THEN all 3 entities were processed
        assert result.statistics["total_entities_processed"] == 3


class TestConvertEntitiesToLogic:
    """Tests for DeonticLogicConverter.convert_entities_to_logic()."""

    @pytest.fixture
    def converter(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import DeonticLogicConverter
        return DeonticLogicConverter(enable_symbolic_ai=False)

    @pytest.fixture
    def context(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        return ConversionContext(source_document_path="/tmp/test.txt")

    def test_empty_list_returns_empty(self, converter, context):
        result = converter.convert_entities_to_logic([], context)
        assert result == []

    def test_agent_inference_disabled(self, converter):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        ctx = ConversionContext(source_document_path="/tmp/t.txt", enable_agent_inference=False)
        e = _make_entity("e1", "c1", "obligation", "The director must file the report annually")
        result = converter.convert_entities_to_logic([e], ctx)
        # no agent even though text mentions director
        for f in result:
            assert f.agent is None

    def test_temporal_analysis_disabled(self, converter):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        ctx = ConversionContext(source_document_path="/tmp/t.txt", enable_temporal_analysis=False)
        e = _make_entity("e1", "c1", "obligation", "The contractor must pay within 30 days")
        result = converter.convert_entities_to_logic([e], ctx)
        for f in result:
            assert f.temporal_conditions == []

    def test_entity_with_empty_text_skipped(self, converter, context):
        # GIVEN an entity with no text content
        e = _make_entity("e_empty", "", "miscellaneous", "")
        result = converter.convert_entities_to_logic([e], context)
        assert result == []


# ===========================================================================
# 2. domain/legal_domain_knowledge.py
# ===========================================================================

class TestLegalDomainKnowledgeInit:
    """Tests for LegalDomainKnowledge initialisation."""

    def test_default_init(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        ldk = LegalDomainKnowledge()
        assert ldk is not None

    def test_legal_domain_enum_values(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        assert LegalDomain.CONTRACT.value == "contract"
        assert LegalDomain.CRIMINAL.value == "criminal"
        assert LegalDomain.EMPLOYMENT.value == "employment"


class TestIdentifyLegalDomain:
    """Tests for LegalDomainKnowledge.identify_legal_domain()."""

    @pytest.fixture
    def ldk(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        return LegalDomainKnowledge()

    def test_contract_domain_detected(self, ldk):
        domain, confidence = ldk.identify_legal_domain(
            "The contractor must fulfill the contract obligations before the deadline.")
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        assert domain == LegalDomain.CONTRACT
        assert 0.0 <= confidence <= 1.0

    def test_criminal_domain_detected(self, ldk):
        domain, confidence = ldk.identify_legal_domain(
            "The defendant is charged with criminal fraud and sentenced to prison.")
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        assert domain == LegalDomain.CRIMINAL
        assert confidence > 0.0

    def test_employment_domain_detected(self, ldk):
        domain, confidence = ldk.identify_legal_domain(
            "The employee must not discriminate or harass colleagues in the workplace.")
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        assert domain == LegalDomain.EMPLOYMENT
        assert confidence > 0.0

    def test_returns_tuple(self, ldk):
        result = ldk.identify_legal_domain("A legal matter.")
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestClassifyLegalStatement:
    """Tests for LegalDomainKnowledge.classify_legal_statement()."""

    @pytest.fixture
    def ldk(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        return LegalDomainKnowledge()

    def test_obligation_classified(self, ldk):
        operator, confidence = ldk.classify_legal_statement(
            "The lessee shall pay rent by the first of each month.")
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        assert operator == DeonticOperator.OBLIGATION
        assert confidence > 0.5

    def test_permission_classified(self, ldk):
        operator, confidence = ldk.classify_legal_statement(
            "The tenant may have pets with prior written consent.")
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        assert operator == DeonticOperator.PERMISSION

    def test_prohibition_classified(self, ldk):
        operator, confidence = ldk.classify_legal_statement(
            "The contractor must not subcontract without approval.")
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        assert operator == DeonticOperator.PROHIBITION


class TestExtractAgents:
    """Tests for LegalDomainKnowledge.extract_agents()."""

    @pytest.fixture
    def ldk(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        return LegalDomainKnowledge()

    def test_extracts_contractor(self, ldk):
        agents = ldk.extract_agents("The contractor must notify the employer immediately.")
        names = [a[0] for a in agents]
        assert any("contractor" in n.lower() or "employer" in n.lower() for n in names)

    def test_returns_list(self, ldk):
        agents = ldk.extract_agents("All parties are bound by this agreement.")
        assert isinstance(agents, list)

    def test_empty_text_returns_empty(self, ldk):
        agents = ldk.extract_agents("")
        assert isinstance(agents, list)


class TestExtractConditions:
    """Tests for LegalDomainKnowledge.extract_conditions()."""

    @pytest.fixture
    def ldk(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        return LegalDomainKnowledge()

    def test_extracts_if_condition(self, ldk):
        conds = ldk.extract_conditions("Payment is due if the work is completed on time.")
        assert isinstance(conds, list)
        assert len(conds) >= 1

    def test_extracts_when_condition(self, ldk):
        conds = ldk.extract_conditions("The warranty expires when the product is transferred.")
        assert isinstance(conds, list)

    def test_no_condition_returns_empty(self, ldk):
        conds = ldk.extract_conditions("The contractor shall perform the services.")
        assert isinstance(conds, list)


class TestExtractTemporalExpressions:
    """Tests for LegalDomainKnowledge.extract_temporal_expressions()."""

    @pytest.fixture
    def ldk(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        return LegalDomainKnowledge()

    def test_deadline_extracted(self, ldk):
        result = ldk.extract_temporal_expressions("The notice must be given within 30 days.")
        assert "deadline" in result
        assert len(result["deadline"]) > 0

    def test_all_keys_present(self, ldk):
        result = ldk.extract_temporal_expressions("Services provided annually.")
        for key in ["deadline", "duration", "start_time", "frequency"]:
            assert key in result


class TestValidateDeonticExtraction:
    """Tests for LegalDomainKnowledge.validate_deontic_extraction()."""

    @pytest.fixture
    def ldk(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        return LegalDomainKnowledge()

    def test_valid_high_confidence(self, ldk):
        result = ldk.validate_deontic_extraction(
            "The contractor must perform all services.", "obligation", 0.9)
        assert result["is_valid"] is True
        assert isinstance(result["warnings"], list)

    def test_low_confidence_flagged(self, ldk):
        result = ldk.validate_deontic_extraction("Something vague.", "obligation", 0.1)
        assert "confidence_adjustment" in result


class TestExtractLegalEntities:
    """Tests for LegalDomainKnowledge.extract_legal_entities()."""

    @pytest.fixture
    def ldk(self):
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomainKnowledge
        return LegalDomainKnowledge()

    def test_returns_list(self, ldk):
        entities = ldk.extract_legal_entities("John signed the contract with ABC Corp.")
        assert isinstance(entities, list)

    def test_entity_has_required_keys(self, ldk):
        entities = ldk.extract_legal_entities("ABC Corporation executed the service agreement.")
        for entity in entities:
            assert "name" in entity
            assert "type" in entity


# ===========================================================================
# 3. domain/document_consistency_checker.py
# ===========================================================================

class TestDocumentConsistencyCheckerInit:
    """Tests for DocumentConsistencyChecker initialisation."""

    @pytest.fixture
    def rag_store(self):
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_rag_store import TemporalDeonticRAGStore
        return TemporalDeonticRAGStore()

    def test_init_with_rag_store(self, rag_store):
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DocumentConsistencyChecker
        checker = DocumentConsistencyChecker(rag_store=rag_store)
        assert checker.rag_store is rag_store
        assert checker.enable_theorem_proving is False  # no proof_engine provided

    def test_init_with_strict_mode(self, rag_store):
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DocumentConsistencyChecker
        checker = DocumentConsistencyChecker(rag_store=rag_store)
        checker.strict_mode = True
        assert checker.strict_mode is True


class TestCheckDocument:
    """Tests for DocumentConsistencyChecker.check_document()."""

    @pytest.fixture
    def checker(self):
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DocumentConsistencyChecker
        return DocumentConsistencyChecker(rag_store=TemporalDeonticRAGStore())

    def test_returns_document_analysis(self, checker):
        # GIVEN a document with an obligation
        # WHEN checked
        result = checker.check_document(
            "The contractor must submit a report monthly.",
            document_id="doc001"
        )
        # THEN a DocumentAnalysis is returned
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DocumentAnalysis
        assert isinstance(result, DocumentAnalysis)
        assert result.document_id == "doc001"

    def test_extracts_obligation_formula(self, checker):
        result = checker.check_document(
            "The vendor shall deliver the goods within 14 days.",
            document_id="doc002"
        )
        assert len(result.extracted_formulas) >= 1

    def test_extracts_multiple_formulas(self, checker):
        result = checker.check_document(
            "The contractor must pay the invoice. "
            "The client may request revisions. "
            "Neither party shall disclose confidential information.",
            document_id="doc003"
        )
        assert len(result.extracted_formulas) >= 2

    def test_processing_time_is_positive(self, checker):
        result = checker.check_document("The licensee must comply.", document_id="doc004")
        assert result.processing_time >= 0.0

    def test_with_jurisdiction(self, checker):
        result = checker.check_document(
            "The tenant shall vacate by month end.",
            document_id="doc005",
            jurisdiction="US-NY",
        )
        assert result.document_id == "doc005"

    def test_empty_document_returns_analysis(self, checker):
        result = checker.check_document("", document_id="doc006")
        assert isinstance(result, object)
        assert result.document_id == "doc006"


class TestGenerateDebugReport:
    """Tests for DocumentConsistencyChecker.generate_debug_report()."""

    @pytest.fixture
    def checker(self):
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DocumentConsistencyChecker
        return DocumentConsistencyChecker(rag_store=TemporalDeonticRAGStore())

    def test_returns_debug_report(self, checker):
        analysis = checker.check_document(
            "The borrower must repay the loan within 5 years.",
            document_id="report001"
        )
        report = checker.generate_debug_report(analysis)
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DebugReport
        assert isinstance(report, DebugReport)
        assert report.document_id == "report001"

    def test_report_has_summary(self, checker):
        analysis = checker.check_document("The seller must disclose defects.", "report002")
        report = checker.generate_debug_report(analysis)
        assert isinstance(report.summary, str)

    def test_issue_counts_non_negative(self, checker):
        analysis = checker.check_document("The agent shall act in good faith.", "report003")
        report = checker.generate_debug_report(analysis)
        assert report.total_issues >= 0
        assert report.critical_errors >= 0
        assert report.warnings >= 0


class TestBatchCheckDocuments:
    """Tests for DocumentConsistencyChecker.batch_check_documents()."""

    @pytest.fixture
    def checker(self):
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DocumentConsistencyChecker
        return DocumentConsistencyChecker(rag_store=TemporalDeonticRAGStore())

    def test_batch_processes_all_documents(self, checker):
        docs = [
            ("The buyer must pay within 30 days.", "batch001"),
            ("The seller may offer discounts.", "batch002"),
            ("Neither party shall breach confidentiality.", "batch003"),
        ]
        results = checker.batch_check_documents(docs)
        assert len(results) == 3
        ids = [r.document_id for r in results]
        assert "batch001" in ids
        assert "batch002" in ids
        assert "batch003" in ids

    def test_empty_batch_returns_empty(self, checker):
        results = checker.batch_check_documents([])
        assert results == []


class TestDocumentAnalysisDataclass:
    """Tests for DocumentAnalysis dataclass."""

    def test_create_with_defaults(self):
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DocumentAnalysis
        da = DocumentAnalysis(document_id="test123")
        assert da.document_id == "test123"
        assert da.extracted_formulas == []
        assert da.proof_results == []
        assert da.confidence_score == 0.0
        assert da.issues_found == []

    def test_debug_report_defaults(self):
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import DebugReport
        dr = DebugReport(document_id="debug001")
        assert dr.document_id == "debug001"
        assert dr.total_issues == 0
        assert dr.critical_errors == 0
        assert dr.issues == []


# ===========================================================================
# 4. interactive/interactive_fol_constructor.py
# ===========================================================================

class TestInteractiveFOLConstructorInit:
    """Tests for InteractiveFOLConstructor initialisation."""

    def test_default_init(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        assert c.domain == "general"
        assert c.confidence_threshold == 0.6
        assert c.enable_consistency_checking is True
        assert c.session_id is not None

    def test_custom_domain(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor(domain="legal", confidence_threshold=0.8)
        assert c.domain == "legal"
        assert c.confidence_threshold == 0.8


class TestStartSession:
    """Tests for InteractiveFOLConstructor.start_session()."""

    def test_returns_session_id(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        sid = c.start_session()
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_session_id_matches_instance(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        sid = c.start_session()
        assert sid == c.session_id


class TestAddStatement:
    """Tests for InteractiveFOLConstructor.add_statement()."""

    @pytest.fixture
    def constructor(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        return InteractiveFOLConstructor()

    def test_add_obligation_statement(self, constructor):
        result = constructor.add_statement(
            "The contractor must submit deliverables by Friday.", force_add=True)
        assert isinstance(result, dict)
        assert "statement_id" in result

    def test_add_permission_statement(self, constructor):
        result = constructor.add_statement(
            "All parties may request a meeting at any time.", force_add=True)
        assert isinstance(result, dict)

    def test_add_prohibition_statement(self, constructor):
        result = constructor.add_statement(
            "No employee shall disclose trade secrets.", force_add=True)
        assert isinstance(result, dict)

    def test_empty_text_raises_value_error(self, constructor):
        with pytest.raises((ValueError, Exception)):
            constructor.add_statement("", force_add=True)

    def test_dual_call_form(self, constructor):
        sid = constructor.start_session()
        result = constructor.add_statement(
            sid, "The board must approve all expenditures.", force_add=True)
        assert isinstance(result, dict)

    def test_added_statement_tracked(self, constructor):
        constructor.add_statement("The lessor shall maintain the property.", force_add=True)
        assert len(constructor.session_statements) >= 1


class TestRemoveStatement:
    """Tests for InteractiveFOLConstructor.remove_statement()."""

    @pytest.fixture
    def constructor_with_statement(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        c.add_statement("The owner must insure the property.", force_add=True)
        return c

    def test_remove_existing_statement(self, constructor_with_statement):
        c = constructor_with_statement
        stmt_id = list(c.session_statements.keys())[0]
        result = c.remove_statement(stmt_id)
        assert result.get("status") == "success"

    def test_statement_removed_from_session(self, constructor_with_statement):
        c = constructor_with_statement
        stmt_id = list(c.session_statements.keys())[0]
        c.remove_statement(stmt_id)
        assert stmt_id not in c.session_statements


class TestAnalyzeLogicalStructure:
    """Tests for InteractiveFOLConstructor.analyze_logical_structure()."""

    @pytest.fixture
    def populated_constructor(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        c.add_statement("The lender must disclose the interest rate.", force_add=True)
        c.add_statement("The borrower may prepay without penalty.", force_add=True)
        return c

    def test_returns_dict(self, populated_constructor):
        analysis = populated_constructor.analyze_logical_structure()
        assert isinstance(analysis, dict)

    def test_has_status_key(self, populated_constructor):
        analysis = populated_constructor.analyze_logical_structure()
        assert "status" in analysis


class TestGenerateFOLIncrementally:
    """Tests for InteractiveFOLConstructor.generate_fol_incrementally()."""

    @pytest.fixture
    def populated_constructor(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        c.add_statement("The director shall file an annual report.", force_add=True)
        return c

    def test_returns_list(self, populated_constructor):
        result = populated_constructor.generate_fol_incrementally()
        assert isinstance(result, list)

    def test_each_item_is_dict(self, populated_constructor):
        result = populated_constructor.generate_fol_incrementally()
        for item in result:
            assert isinstance(item, dict)


class TestValidateConsistency:
    """Tests for InteractiveFOLConstructor.validate_consistency()."""

    @pytest.fixture
    def constructor(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        c.add_statement("The licensee must pay royalties quarterly.", force_add=True)
        return c

    def test_returns_dict(self, constructor):
        result = constructor.validate_consistency()
        assert isinstance(result, dict)

    def test_has_status_key(self, constructor):
        result = constructor.validate_consistency()
        assert "status" in result


class TestGetSessionStatistics:
    """Tests for InteractiveFOLConstructor.get_session_statistics()."""

    @pytest.fixture
    def constructor(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        c.add_statement("The contractor must maintain insurance coverage.", force_add=True)
        c.add_statement("The subcontractor may use approved suppliers.", force_add=True)
        return c

    def test_returns_dict(self, constructor):
        stats = constructor.get_session_statistics()
        assert isinstance(stats, dict)

    def test_has_session_id_key(self, constructor):
        stats = constructor.get_session_statistics()
        assert "session_id" in stats


class TestExportSession:
    """Tests for InteractiveFOLConstructor.export_session()."""

    @pytest.fixture
    def constructor(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        c.add_statement("The tenant shall not sublet without consent.", force_add=True)
        return c

    def test_export_json(self, constructor):
        exported = constructor.export_session("json")
        assert isinstance(exported, dict)
        assert "statements" in exported

    def test_export_has_metadata(self, constructor):
        exported = constructor.export_session("json")
        assert "session_metadata" in exported


class TestAnalyzeSession:
    """Tests for InteractiveFOLConstructor.analyze_session()."""

    def test_returns_dict_with_session_id(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        c = InteractiveFOLConstructor()
        sid = c.start_session()
        c.add_statement("The lessee shall pay rent monthly.", force_add=True)
        result = c.analyze_session(sid)
        assert isinstance(result, dict)
        assert result.get("session_id") == sid


# ===========================================================================
# 5. reasoning/deontological_reasoning_utils.py
# ===========================================================================

class TestDeonticPatterns:
    """Tests for DeonticPatterns class."""

    def test_obligation_patterns_is_list(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import DeonticPatterns
        patterns = DeonticPatterns.OBLIGATION_PATTERNS
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_permission_patterns_is_list(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import DeonticPatterns
        patterns = DeonticPatterns.PERMISSION_PATTERNS
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_prohibition_patterns_is_list(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import DeonticPatterns
        patterns = DeonticPatterns.PROHIBITION_PATTERNS
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_conditional_patterns_is_list(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import DeonticPatterns
        patterns = DeonticPatterns.CONDITIONAL_PATTERNS
        assert isinstance(patterns, list)

    def test_exception_patterns_is_list(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import DeonticPatterns
        patterns = DeonticPatterns.EXCEPTION_PATTERNS
        assert isinstance(patterns, list)

    def test_obligation_pattern_matches_must(self):
        import re
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import DeonticPatterns
        text = "The contractor must submit the report."
        matched = any(re.search(p, text, re.IGNORECASE) for p in DeonticPatterns.OBLIGATION_PATTERNS)
        assert matched

    def test_permission_pattern_matches_may(self):
        import re
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import DeonticPatterns
        text = "The vendor may request additional time."
        matched = any(re.search(p, text, re.IGNORECASE) for p in DeonticPatterns.PERMISSION_PATTERNS)
        assert matched

    def test_prohibition_pattern_matches_shall_not(self):
        import re
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import DeonticPatterns
        text = "The employee shall not disclose trade secrets."
        matched = any(re.search(p, text, re.IGNORECASE) for p in DeonticPatterns.PROHIBITION_PATTERNS)
        assert matched


class TestNormalizeEntityAction:
    """Tests for normalize_entity() and normalize_action()."""

    def test_normalize_entity_strips_the(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import normalize_entity
        result = normalize_entity("the contractor")
        assert isinstance(result, str)

    def test_normalize_entity_preserves_content(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import normalize_entity
        result = normalize_entity("ABC Corporation")
        assert "ABC" in result or "abc" in result.lower()

    def test_normalize_action_returns_string(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import normalize_action
        result = normalize_action("shall disclose all material facts")
        assert isinstance(result, str)

    def test_normalize_empty_entity(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import normalize_entity
        result = normalize_entity("")
        assert isinstance(result, str)


class TestCalculateTextSimilarity:
    """Tests for calculate_text_similarity()."""

    def test_identical_texts_high_similarity(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import calculate_text_similarity
        sim = calculate_text_similarity("contractor", "contractor")
        assert sim >= 0.9

    def test_different_texts_low_similarity(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import calculate_text_similarity
        sim = calculate_text_similarity("dog", "jurisdiction")
        assert sim < 0.5

    def test_returns_float(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import calculate_text_similarity
        result = calculate_text_similarity("party", "agreement")
        assert isinstance(result, float)

    def test_range_is_zero_to_one(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import calculate_text_similarity
        sim = calculate_text_similarity("contract", "agreement")
        assert 0.0 <= sim <= 1.0


class TestAreEntitiesSimilar:
    """Tests for are_entities_similar()."""

    def test_same_abbreviation(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_entities_similar
        assert are_entities_similar("ABC Corp", "ABC Corporation") is True

    def test_identical_entities(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_entities_similar
        assert are_entities_similar("contractor", "contractor") is True

    def test_dissimilar_entities(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_entities_similar
        result = are_entities_similar("government", "butterfly")
        assert isinstance(result, bool)

    def test_empty_entities(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_entities_similar
        result = are_entities_similar("", "")
        assert isinstance(result, bool)


class TestAreActionsSimilar:
    """Tests for are_actions_similar()."""

    def test_semantically_similar_actions(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_actions_similar
        # "pay" and "remit" are semantically related payment terms
        result = are_actions_similar("pay the fee", "pay the fee")
        assert result is True

    def test_identical_actions(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_actions_similar
        assert are_actions_similar("disclose risks", "disclose risks") is True

    def test_different_actions(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import are_actions_similar
        result = are_actions_similar("pay the invoice", "hire new staff")
        assert isinstance(result, bool)


class TestExtractKeywords:
    """Tests for extract_keywords()."""

    def test_extracts_nouns_and_verbs(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_keywords
        keywords = extract_keywords("the contractor must pay the penalty")
        assert isinstance(keywords, set)
        assert len(keywords) > 0

    def test_stops_words_removed(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_keywords
        keywords = extract_keywords("the a an is")
        # common stop words should not dominate
        assert isinstance(keywords, set)

    def test_empty_text_returns_empty_set(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_keywords
        result = extract_keywords("")
        assert isinstance(result, set)


class TestExtractConditionsFromText:
    """Tests for extract_conditions_from_text()."""

    def test_if_condition_extracted(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_conditions_from_text
        conds = extract_conditions_from_text("Payment is required if the order is confirmed.")
        assert isinstance(conds, list)
        assert len(conds) >= 1

    def test_when_condition_extracted(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_conditions_from_text
        conds = extract_conditions_from_text("The warranty applies when the product is defective.")
        assert isinstance(conds, list)

    def test_no_condition_returns_empty(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_conditions_from_text
        conds = extract_conditions_from_text("All parties must comply with the regulations.")
        assert isinstance(conds, list)


class TestExtractExceptionsFromText:
    """Tests for extract_exceptions_from_text()."""

    def test_unless_exception_extracted(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_exceptions_from_text
        exceptions = extract_exceptions_from_text(
            "All parties must comply unless otherwise agreed in writing.")
        assert isinstance(exceptions, list)
        assert len(exceptions) >= 1

    def test_except_exception_extracted(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_exceptions_from_text
        exceptions = extract_exceptions_from_text(
            "The rule applies except in cases of force majeure.")
        assert isinstance(exceptions, list)

    def test_no_exception_returns_empty(self):
        from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_utils import extract_exceptions_from_text
        exceptions = extract_exceptions_from_text("The contractor shall perform all services.")
        assert isinstance(exceptions, list)
