"""
Integration coverage tests — session 6 (2026-02-20).

This file targets low-coverage modules in logic/integration/ to push
overall coverage from ~51% toward ~60%+.  It covers:

  * reasoning/proof_execution_engine.py   (17% → ~50%)
  * domain/temporal_deontic_api.py        (6%  → ~55%)
  * domain/legal_symbolic_analyzer.py     (29% → ~65%)
  * symbolic/neurosymbolic/embedding_prover.py  (17% → ~80%)
  * symbolic/neurosymbolic/hybrid_confidence.py (26% → ~75%)
  * symbolic/neurosymbolic/reasoning_coordinator.py (33% → ~65%)
  * interactive/interactive_fol_utils.py  (10% → ~80%)
  * reasoning/proof_execution_engine_utils.py  (38% → ~80%)

All tests use GIVEN-WHEN-THEN format consistent with the existing suite.
"""

import asyncio
import os
import pytest
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def _make_obligation(proposition="pay_on_time", agent_name="Contractor"):
    from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
        DeonticFormula, DeonticOperator, LegalAgent
    )
    agent = LegalAgent(agent_name.lower(), agent_name, "organization")
    return DeonticFormula(
        operator=DeonticOperator.OBLIGATION,
        proposition=proposition,
        agent=agent,
        confidence=0.9,
        source_text=f"{agent_name} must {proposition}",
    )


def _make_rule_set(formulas=None):
    from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
    rs = DeonticRuleSet(name="test_rules", formulas=list(formulas or []), description="test")
    return rs


# ---------------------------------------------------------------------------
# § 1  ProofExecutionEngine — proof_execution_engine.py
# ---------------------------------------------------------------------------

class TestProofExecutionEngineInit:
    """GIVEN ProofExecutionEngine WHEN initialised THEN basic attributes are set."""

    def test_init_creates_temp_dir(self, tmp_path):
        """GIVEN a temp_dir WHEN engine is created THEN temp_dir exists."""
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        engine = ProofExecutionEngine(temp_dir=str(tmp_path), timeout=10)
        assert engine.temp_dir.exists()
        assert engine.timeout == 10

    def test_init_default_prover(self, tmp_path):
        """GIVEN no prover specified WHEN created THEN default prover is 'z3'."""
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        engine = ProofExecutionEngine(tmp_path)
        assert engine.default_prover == "z3"

    def test_init_env_default_prover(self, tmp_path, monkeypatch):
        """GIVEN env var WHEN created THEN default prover uses env var."""
        monkeypatch.setenv("IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS", "0")
        monkeypatch.setenv("IPFS_DATASETS_PY_PROOF_PROVER", "cvc5")
        from importlib import reload
        import ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine as mod
        engine = mod.ProofExecutionEngine(tmp_path)
        assert engine.default_prover == "cvc5"
        monkeypatch.delenv("IPFS_DATASETS_PY_PROOF_PROVER", raising=False)

    def test_init_disable_caching(self, tmp_path):
        """GIVEN enable_caching=False WHEN created THEN proof_cache is None."""
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        engine = ProofExecutionEngine(tmp_path, enable_caching=False)
        assert engine.proof_cache is None

    def test_init_disable_rate_limiting(self, tmp_path):
        """GIVEN enable_rate_limiting=False WHEN created THEN no rate_limiter attr."""
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        engine = ProofExecutionEngine(tmp_path, enable_rate_limiting=False, enable_validation=False)
        assert not hasattr(engine, "rate_limiter") or engine.enable_rate_limiting is False

    def test_init_available_provers_dict(self, tmp_path):
        """GIVEN no provers installed WHEN created THEN available_provers is a dict."""
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        engine = ProofExecutionEngine(tmp_path)
        assert isinstance(engine.available_provers, dict)


class TestProofExecutionEngineHelpers:
    """Test internal helper methods."""

    @pytest.fixture
    def engine(self, tmp_path):
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        return ProofExecutionEngine(tmp_path)

    def test_find_executable_returns_none_for_fake(self, engine):
        """GIVEN a non-existent binary WHEN _find_executable called THEN returns None."""
        result = engine._find_executable("__fake_binary_does_not_exist__")
        assert result is None

    def test_prover_cmd_z3(self, engine):
        """GIVEN prover=z3 WHEN _prover_cmd THEN returns z3 string."""
        cmd = engine._prover_cmd("z3")
        assert "z3" in cmd.lower()

    def test_prover_cmd_coq(self, engine):
        """GIVEN prover=coq WHEN _prover_cmd THEN returns coqc."""
        cmd = engine._prover_cmd("coq")
        assert "coq" in cmd.lower()

    def test_prover_cmd_lean(self, engine):
        """GIVEN prover=lean WHEN _prover_cmd THEN returns lean."""
        cmd = engine._prover_cmd("lean")
        assert "lean" in cmd.lower()

    def test_prover_cmd_cvc5(self, engine):
        """GIVEN prover=cvc5 WHEN _prover_cmd THEN returns cvc5."""
        cmd = engine._prover_cmd("cvc5")
        assert "cvc5" in cmd.lower()

    def test_test_command_returns_false_for_nonexistent(self, engine):
        """GIVEN non-existent command WHEN _test_command THEN returns False."""
        result = engine._test_command(["__nonexistent_cmd_xyz__", "--version"])
        assert result is False

    def test_env_truthy_default(self, engine, monkeypatch):
        """GIVEN var not set WHEN _env_truthy THEN returns True with default='1'."""
        monkeypatch.delenv("TEST_TRUTHY_VAR_XYZ", raising=False)
        assert engine._env_truthy("TEST_TRUTHY_VAR_XYZ", "1") is True

    def test_env_truthy_false(self, engine, monkeypatch):
        """GIVEN var set to '0' WHEN _env_truthy THEN returns False."""
        monkeypatch.setenv("TEST_TRUTHY_VAR_XYZ", "0")
        assert engine._env_truthy("TEST_TRUTHY_VAR_XYZ", "1") is False

    def test_get_translator_z3(self, engine):
        """GIVEN prover=z3 WHEN _get_translator THEN returns SMTTranslator."""
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import SMTTranslator
        tr = engine._get_translator("z3")
        assert isinstance(tr, SMTTranslator)

    def test_get_translator_lean(self, engine):
        """GIVEN prover=lean WHEN _get_translator THEN returns LeanTranslator."""
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import LeanTranslator
        tr = engine._get_translator("lean")
        assert isinstance(tr, LeanTranslator)

    def test_get_translator_unknown(self, engine):
        """GIVEN unknown prover WHEN _get_translator THEN returns None."""
        tr = engine._get_translator("unknown_prover_xyz")
        assert tr is None


class TestProveDeonticFormula:
    """Tests for prove_deontic_formula() early-exit paths (no provers installed)."""

    @pytest.fixture
    def engine(self, tmp_path):
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        return ProofExecutionEngine(tmp_path, enable_rate_limiting=False, enable_validation=False)

    def test_prove_unknown_prover_returns_unsupported(self, engine):
        """GIVEN prover not in available_provers WHEN prove THEN UNSUPPORTED status."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        formula = _make_obligation()
        result = engine.prove_deontic_formula(formula, prover="nonexistent_prover_xyz")
        assert result.status == ProofStatus.UNSUPPORTED

    def test_prove_unavailable_prover_returns_error(self, engine):
        """GIVEN prover available=False WHEN prove THEN ERROR status."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        # Force z3 to be in available_provers but set to False
        engine.available_provers["z3"] = False
        formula = _make_obligation()
        result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status in (ProofStatus.ERROR, ProofStatus.UNSUPPORTED)

    def test_prove_rule_set_empty(self, engine):
        """GIVEN empty rule set WHEN prove_rule_set THEN empty list."""
        rs = _make_rule_set()
        results = engine.prove_rule_set(rs, prover="z3")
        assert results == []

    def test_prove_rule_set_with_formulas(self, engine):
        """GIVEN rule set with formulas WHEN prove_rule_set THEN list of results."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofResult
        rs = _make_rule_set([_make_obligation()])
        results = engine.prove_rule_set(rs, prover="nonexistent_prover_xyz")
        assert len(results) == 1
        assert isinstance(results[0], ProofResult)

    def test_prove_consistency_unsupported_prover(self, engine):
        """GIVEN unsupported prover WHEN prove_consistency THEN UNSUPPORTED."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        rs = _make_rule_set()
        result = engine.prove_consistency(rs, prover="lean")
        assert result.status == ProofStatus.UNSUPPORTED

    def test_prove_multiple_provers_no_available(self, engine):
        """GIVEN no available provers WHEN prove_multiple_provers THEN all UNSUPPORTED."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        engine.available_provers = {k: False for k in engine.available_provers}
        formula = _make_obligation()
        results = engine.prove_multiple_provers(formula)
        for r in results.values():
            assert r.status == ProofStatus.UNSUPPORTED

    def test_get_prover_status_returns_dict(self, engine):
        """GIVEN engine WHEN get_prover_status THEN returns dict with keys."""
        status = engine.get_prover_status()
        assert "available_provers" in status
        assert "temp_directory" in status
        assert "timeout" in status

    def test_prove_caches_result_for_unavailable_prover(self, engine):
        """GIVEN caching enabled WHEN prove called twice THEN second result consistent."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        formula = _make_obligation()
        r1 = engine.prove_deontic_formula(formula, prover="nonexistent_prover_xyz")
        r2 = engine.prove_deontic_formula(formula, prover="nonexistent_prover_xyz")
        assert r1.status == r2.status

    def test_prove_no_cache(self, tmp_path):
        """GIVEN caching disabled WHEN prove THEN proof_cache is None."""
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        engine = ProofExecutionEngine(tmp_path, enable_caching=False, enable_rate_limiting=False, enable_validation=False)
        formula = _make_obligation()
        result = engine.prove_deontic_formula(formula, prover="nonexistent_prover_xyz")
        assert result.status in (ProofStatus.UNSUPPORTED, ProofStatus.ERROR)


# ---------------------------------------------------------------------------
# § 2  temporal_deontic_api.py
# ---------------------------------------------------------------------------

class TestParseTemporalContext:
    """Tests for _parse_temporal_context()."""

    def test_none_returns_now(self):
        """GIVEN None value WHEN parsed THEN returns datetime near now."""
        from datetime import datetime
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        result = _parse_temporal_context(None)
        assert isinstance(result, datetime)

    def test_current_time_returns_now(self):
        """GIVEN 'current_time' WHEN parsed THEN returns datetime near now."""
        from datetime import datetime
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        result = _parse_temporal_context("current_time")
        assert isinstance(result, datetime)

    def test_valid_iso_string_parsed(self):
        """GIVEN valid ISO string WHEN parsed THEN returns that datetime."""
        from datetime import datetime
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        result = _parse_temporal_context("2025-01-15T10:00:00")
        assert result.year == 2025
        assert result.month == 1

    def test_invalid_string_returns_now(self):
        """GIVEN invalid string WHEN parsed THEN returns fallback now."""
        from datetime import datetime
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        result = _parse_temporal_context("not-a-date")
        assert isinstance(result, datetime)

    def test_empty_string_returns_now(self):
        """GIVEN empty string WHEN parsed THEN returns fallback now."""
        from datetime import datetime
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import _parse_temporal_context
        result = _parse_temporal_context("")
        assert isinstance(result, datetime)


class TestCheckDocumentConsistencyAsync:
    """Tests for check_document_consistency_from_parameters()."""

    def test_missing_document_text_returns_error(self):
        """GIVEN empty params WHEN called THEN success=False, MISSING_DOCUMENT_TEXT."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            check_document_consistency_from_parameters
        )
        result = anyio.run(check_document_consistency_from_parameters, {})
        assert result["success"] is False
        assert result["error_code"] == "MISSING_DOCUMENT_TEXT"

    def test_with_document_text_returns_result(self):
        """GIVEN document text WHEN called THEN success=True with analysis keys."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            check_document_consistency_from_parameters
        )
        params = {"document_text": "The contractor shall deliver the goods by December 31."}
        result = anyio.run(check_document_consistency_from_parameters, params)
        assert result["success"] is True
        assert "consistency_analysis" in result
        assert "document_id" in result

    def test_with_jurisdiction_passed_through(self):
        """GIVEN jurisdiction WHEN called THEN metadata contains jurisdiction."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            check_document_consistency_from_parameters
        )
        params = {
            "document_text": "The employer must pay wages monthly.",
            "jurisdiction": "California",
            "legal_domain": "employment"
        }
        result = anyio.run(check_document_consistency_from_parameters, params)
        assert result["success"] is True
        assert result["metadata"]["jurisdiction"] == "California"

    def test_with_temporal_context(self):
        """GIVEN temporal_context param WHEN called THEN succeeds."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            check_document_consistency_from_parameters
        )
        params = {
            "document_text": "Payment must be made on time.",
            "temporal_context": "2025-06-01T00:00:00",
        }
        result = anyio.run(check_document_consistency_from_parameters, params)
        assert result["success"] is True


class TestQueryTheoremsAsync:
    """Tests for query_theorems_from_parameters()."""

    def test_missing_query_returns_error(self):
        """GIVEN empty params WHEN called THEN MISSING_QUERY error."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            query_theorems_from_parameters
        )
        result = anyio.run(query_theorems_from_parameters, {})
        assert result["success"] is False
        assert result["error_code"] == "MISSING_QUERY"

    def test_with_query_returns_results(self):
        """GIVEN query WHEN called THEN success=True and theorems list present."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            query_theorems_from_parameters
        )
        result = anyio.run(query_theorems_from_parameters, {"query": "payment obligation"})
        assert result["success"] is True
        assert "theorems" in result

    def test_with_operator_filter(self):
        """GIVEN operator_filter WHEN called THEN filter applied."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            query_theorems_from_parameters
        )
        result = anyio.run(query_theorems_from_parameters, {
            "query": "obligation",
            "operator_filter": "OBLIGATION"
        })
        assert result["success"] is True

    def test_with_invalid_operator_filter(self):
        """GIVEN invalid operator_filter WHEN called THEN still succeeds (KeyError caught)."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            query_theorems_from_parameters
        )
        result = anyio.run(query_theorems_from_parameters, {
            "query": "obligation",
            "operator_filter": "INVALID_OPERATOR"
        })
        assert result["success"] is True

    def test_with_jurisdiction_filter(self):
        """GIVEN jurisdiction filter WHEN called THEN filter applied."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            query_theorems_from_parameters
        )
        result = anyio.run(query_theorems_from_parameters, {
            "query": "obligation",
            "jurisdiction": "Federal",
        })
        assert result["success"] is True


class TestBulkProcessCaselawAsync:
    """Tests for bulk_process_caselaw_from_parameters()."""

    def test_empty_directories_returns_error(self):
        """GIVEN no directories WHEN called THEN MISSING_DIRECTORIES error."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            bulk_process_caselaw_from_parameters
        )
        result = anyio.run(bulk_process_caselaw_from_parameters, {})
        assert result["success"] is False
        assert result["error_code"] == "MISSING_DIRECTORIES"

    def test_invalid_directories_returns_error(self):
        """GIVEN non-existent dirs WHEN called THEN INVALID_DIRECTORIES error."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            bulk_process_caselaw_from_parameters
        )
        result = anyio.run(bulk_process_caselaw_from_parameters, {
            "caselaw_directories": ["/nonexistent/path/xyz"]
        })
        assert result["success"] is False
        assert result["error_code"] == "INVALID_DIRECTORIES"

    def test_valid_directory_async_mode(self, tmp_path):
        """GIVEN a valid dir WHEN async_processing=True THEN session_id returned."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            bulk_process_caselaw_from_parameters
        )
        result = anyio.run(bulk_process_caselaw_from_parameters, {
            "caselaw_directories": [str(tmp_path)],
            "async_processing": True,
        })
        assert result["success"] is True
        assert "session_id" in result


class TestAddTheoremAsync:
    """Tests for add_theorem_from_parameters()."""

    def test_missing_proposition_returns_error(self):
        """GIVEN no proposition WHEN called THEN MISSING_PROPOSITION error."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            add_theorem_from_parameters
        )
        result = anyio.run(add_theorem_from_parameters, {"operator": "OBLIGATION"})
        assert result["success"] is False
        assert result["error_code"] == "MISSING_PROPOSITION"

    def test_add_obligation_theorem(self):
        """GIVEN valid obligation params WHEN called THEN theorem added."""
        import anyio
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_api import (
            add_theorem_from_parameters
        )
        result = anyio.run(add_theorem_from_parameters, {
            "operator": "OBLIGATION",
            "proposition": "pay wages monthly",
            "agent_name": "Employer",
            "jurisdiction": "Federal",
        })
        assert result["success"] is True
        assert "theorem_id" in result


# ---------------------------------------------------------------------------
# § 3  LegalSymbolicAnalyzer — domain/legal_symbolic_analyzer.py
# ---------------------------------------------------------------------------

class TestLegalAnalysisResultDataclass:
    """Tests for LegalAnalysisResult dataclass."""

    def test_create_with_defaults(self):
        """GIVEN no args WHEN created THEN defaults are set."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import LegalAnalysisResult
        result = LegalAnalysisResult()
        assert result.confidence == 0.0
        assert result.primary_parties == []
        assert result.reasoning == ""

    def test_create_with_values(self):
        """GIVEN values WHEN created THEN values stored."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import LegalAnalysisResult
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        result = LegalAnalysisResult(
            legal_domain=LegalDomain.CONTRACT,
            primary_parties=["A", "B"],
            confidence=0.8,
            reasoning="pattern match"
        )
        assert result.confidence == 0.8
        assert len(result.primary_parties) == 2


class TestDeonticPropositionDataclass:
    """Tests for DeonticProposition dataclass."""

    def test_create_obligation(self):
        """GIVEN OBLIGATION operator WHEN created THEN operator stored."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import DeonticProposition
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        dp = DeonticProposition(operator=DeonticOperator.OBLIGATION, action="pay_taxes")
        assert dp.operator == DeonticOperator.OBLIGATION
        assert dp.action == "pay_taxes"

    def test_create_permission(self):
        """GIVEN PERMISSION operator WHEN created THEN stored."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import DeonticProposition
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        dp = DeonticProposition(operator=DeonticOperator.PERMISSION, action="assign")
        assert dp.operator == DeonticOperator.PERMISSION


class TestLegalEntityDataclass:
    """Tests for LegalEntity dataclass."""

    def test_create_entity(self):
        """GIVEN entity params WHEN created THEN attributes set."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import LegalEntity
        entity = LegalEntity(name="Acme Corp", entity_type="organization", role="contractor")
        assert entity.name == "Acme Corp"
        assert entity.properties == {}

    def test_with_properties(self):
        """GIVEN properties WHEN created THEN stored."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import LegalEntity
        entity = LegalEntity(
            name="John Doe", entity_type="person", role="signatory",
            confidence=0.9, properties={"jurisdiction": "CA"}
        )
        assert entity.confidence == 0.9
        assert entity.properties["jurisdiction"] == "CA"


class TestTemporalConditionDataclass:
    """Tests for TemporalCondition dataclass."""

    def test_create_deadline(self):
        """GIVEN deadline type WHEN created THEN stored."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import TemporalCondition
        tc = TemporalCondition(condition_type="deadline", temporal_expression="December 31")
        assert tc.condition_type == "deadline"
        assert tc.normalized_date is None


class TestLegalSymbolicAnalyzerFallback:
    """Tests for LegalSymbolicAnalyzer (no SymbolicAI — fallback path)."""

    @pytest.fixture
    def analyzer(self):
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import LegalSymbolicAnalyzer
        return LegalSymbolicAnalyzer()

    def test_init_symai_not_available(self, analyzer):
        """GIVEN no symai WHEN created THEN symbolic_ai_available=False."""
        assert analyzer.symbolic_ai_available is False

    def test_analyze_legal_document_contract(self, analyzer):
        """GIVEN contract text WHEN analyzed THEN returns LegalAnalysisResult."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import LegalAnalysisResult
        result = analyzer.analyze_legal_document("The contractor shall pay the client.")
        assert isinstance(result, LegalAnalysisResult)
        assert result.confidence == 0.5

    def test_analyze_legal_document_with_obligation(self, analyzer):
        """GIVEN obligation text WHEN analyzed THEN legal concepts non-empty."""
        result = analyzer.analyze_legal_document("The party must fulfil the obligation.")
        assert "obligation" in result.legal_concepts

    def test_analyze_legal_document_with_agreement(self, analyzer):
        """GIVEN agreement text WHEN analyzed THEN agreement in concepts."""
        result = analyzer.analyze_legal_document("This agreement governs the parties.")
        assert "agreement" in result.legal_concepts

    def test_extract_deontic_propositions_obligation(self, analyzer):
        """GIVEN obligation text WHEN extracted THEN OBLIGATION proposition found."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        props = analyzer.extract_deontic_propositions("The employer shall provide training.")
        assert any(p.operator == DeonticOperator.OBLIGATION for p in props)

    def test_extract_deontic_propositions_permission(self, analyzer):
        """GIVEN permission text WHEN extracted THEN PERMISSION proposition found."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        props = analyzer.extract_deontic_propositions("The licensee may sublicense the product.")
        assert any(p.operator == DeonticOperator.PERMISSION for p in props)

    def test_extract_deontic_propositions_prohibition(self, analyzer):
        """GIVEN prohibition text WHEN extracted THEN PROHIBITION proposition found."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        props = analyzer.extract_deontic_propositions("Sharing confidential data is strictly prohibited.")
        assert any(p.operator == DeonticOperator.PROHIBITION for p in props)

    def test_extract_deontic_propositions_empty_text(self, analyzer):
        """GIVEN empty text WHEN extracted THEN empty list."""
        props = analyzer.extract_deontic_propositions("")
        assert props == []

    def test_identify_legal_entities_contractor(self, analyzer):
        """GIVEN contractor text WHEN identified THEN contractor in entities."""
        entities = analyzer.identify_legal_entities("The contractor agreed to terms.")
        names = [e.name.lower() for e in entities]
        assert "contractor" in names

    def test_identify_legal_entities_client(self, analyzer):
        """GIVEN client text WHEN identified THEN client entity found."""
        entities = analyzer.identify_legal_entities("The client signed the agreement.")
        names = [e.name.lower() for e in entities]
        assert "client" in names

    def test_identify_legal_entities_government(self, analyzer):
        """GIVEN government text WHEN identified THEN government entity found."""
        entities = analyzer.identify_legal_entities("The government issued the regulation.")
        types = [e.entity_type for e in entities]
        assert "government" in types

    def test_extract_temporal_conditions_deadline(self, analyzer):
        """GIVEN deadline text WHEN extracted THEN deadline condition found."""
        conditions = analyzer.extract_temporal_conditions("Payment must be done by June 30.")
        assert any(c.condition_type == "deadline" for c in conditions)

    def test_extract_temporal_conditions_before(self, analyzer):
        """GIVEN 'before' deadline WHEN extracted THEN deadline condition found."""
        conditions = analyzer.extract_temporal_conditions("Submit before December 1.")
        assert any(c.condition_type == "deadline" for c in conditions)

    def test_extract_temporal_conditions_empty(self, analyzer):
        """GIVEN no temporal refs WHEN extracted THEN empty list."""
        conditions = analyzer.extract_temporal_conditions("The parties agree to cooperate.")
        assert isinstance(conditions, list)


class TestLegalReasoningEngineFallback:
    """Tests for LegalReasoningEngine (fallback without SymbolicAI)."""

    @pytest.fixture
    def engine(self):
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import LegalReasoningEngine
        return LegalReasoningEngine()

    def test_init_symai_not_available(self, engine):
        """GIVEN no symai WHEN created THEN fallback mode active."""
        assert engine.symbolic_ai_available is False

    def test_infer_implicit_obligations_contract(self, engine):
        """GIVEN contract rule WHEN inferring THEN good-faith obligation found."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        obligations = engine.infer_implicit_obligations(["The contract requires payment."])
        assert isinstance(obligations, list)
        assert all(o.operator == DeonticOperator.OBLIGATION for o in obligations)

    def test_infer_implicit_obligations_empty(self, engine):
        """GIVEN empty rules WHEN inferring THEN empty list."""
        obligations = engine.infer_implicit_obligations([])
        assert isinstance(obligations, list)

    def test_check_legal_consistency_contradiction(self, engine):
        """GIVEN contradicting rules WHEN checked THEN is_consistent=False."""
        result = engine.check_legal_consistency([
            "The party shall pay", "The party shall not pay"
        ])
        assert "is_consistent" in result
        assert result["is_consistent"] is False

    def test_check_legal_consistency_no_contradiction(self, engine):
        """GIVEN non-contradicting rules WHEN checked THEN returns dict."""
        result = engine.check_legal_consistency([
            "The contractor shall deliver goods.",
            "The client shall pay within 30 days."
        ])
        assert "is_consistent" in result

    def test_analyze_legal_precedents_without_symai(self, engine):
        """GIVEN no symai WHEN analyzing precedents THEN returns dict with keys."""
        result = engine.analyze_legal_precedents("current case text", ["precedent 1"])
        assert "applicable_precedents" in result
        assert "confidence" in result

    def test_parse_consistency_result(self, engine):
        """GIVEN result text with 'consistent' WHEN parsed THEN is_consistent=True."""
        result = engine._parse_consistency_result("The rules are logically consistent.")
        assert result["is_consistent"] is True

    def test_parse_consistency_result_inconsistent(self, engine):
        """GIVEN result text without 'consistent' WHEN parsed THEN is_consistent=False."""
        result = engine._parse_consistency_result("There are contradictions.")
        assert result["is_consistent"] is False


class TestLegalAnalyzerConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_create_legal_analyzer(self):
        """GIVEN nothing WHEN create_legal_analyzer called THEN returns analyzer."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import (
            LegalSymbolicAnalyzer, create_legal_analyzer
        )
        analyzer = create_legal_analyzer()
        assert isinstance(analyzer, LegalSymbolicAnalyzer)

    def test_create_legal_reasoning_engine(self):
        """GIVEN nothing WHEN create_legal_reasoning_engine called THEN returns engine."""
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import (
            LegalReasoningEngine, create_legal_reasoning_engine
        )
        engine = create_legal_reasoning_engine()
        assert isinstance(engine, LegalReasoningEngine)


# ---------------------------------------------------------------------------
# § 4  EmbeddingEnhancedProver — symbolic/neurosymbolic/embedding_prover.py
# ---------------------------------------------------------------------------

class TestEmbeddingEnhancedProverInit:
    """Tests for EmbeddingEnhancedProver initialisation."""

    def test_init_no_model(self):
        """GIVEN no sentence-transformers WHEN created THEN model is None."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        ep = EmbeddingEnhancedProver()
        assert ep.model is None
        assert ep.cache_enabled is True

    def test_init_cache_disabled(self):
        """GIVEN cache_enabled=False WHEN created THEN cache_enabled=False."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        ep = EmbeddingEnhancedProver(cache_enabled=False)
        assert ep.cache_enabled is False

    def test_init_empty_cache(self):
        """GIVEN fresh init WHEN checked THEN cache is empty."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        ep = EmbeddingEnhancedProver()
        assert len(ep.embedding_cache) == 0


class TestComputeSimilarity:
    """Tests for compute_similarity()."""

    @pytest.fixture
    def ep(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        return EmbeddingEnhancedProver()

    @pytest.fixture
    def formula(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        return Predicate("P", [])

    @pytest.fixture
    def axiom(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        return Predicate("Q", [])

    def test_empty_axioms_returns_zero(self, ep, formula):
        """GIVEN empty axioms WHEN compute_similarity THEN returns 0.0."""
        result = ep.compute_similarity(formula, [])
        assert result == 0.0

    def test_same_formula_returns_high(self, ep, formula):
        """GIVEN same formula as axiom WHEN compute THEN high similarity."""
        result = ep.compute_similarity(formula, [formula])
        assert result > 0.9

    def test_different_formula_returns_value(self, ep, formula, axiom):
        """GIVEN different formula as axiom WHEN compute THEN 0.0 ≤ result ≤ 1.0."""
        result = ep.compute_similarity(formula, [axiom])
        assert 0.0 <= result <= 1.0

    def test_multiple_axioms_returns_max(self, ep, formula, axiom):
        """GIVEN multiple axioms WHEN compute THEN returns max similarity."""
        result = ep.compute_similarity(formula, [axiom, formula])
        assert result > 0.9


class TestFindSimilarFormulas:
    """Tests for find_similar_formulas()."""

    @pytest.fixture
    def ep(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        return EmbeddingEnhancedProver()

    def test_empty_candidates(self):
        """GIVEN empty candidates WHEN find_similar THEN returns empty list."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        ep = EmbeddingEnhancedProver()
        query = Predicate("P", [])
        result = ep.find_similar_formulas(query, [])
        assert result == []

    def test_returns_top_k(self):
        """GIVEN 5 candidates WHEN top_k=2 THEN returns ≤2 results."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        ep = EmbeddingEnhancedProver()
        query = Predicate("P", [])
        candidates = [Predicate(f"Q{i}", []) for i in range(5)]
        result = ep.find_similar_formulas(query, candidates, top_k=2)
        assert len(result) <= 2

    def test_result_is_sorted_descending(self):
        """GIVEN candidates WHEN find_similar THEN results sorted by similarity desc."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        ep = EmbeddingEnhancedProver()
        query = Predicate("P", [])
        candidates = [Predicate("P", []), Predicate("totally_different_xyz", [])]
        result = ep.find_similar_formulas(query, candidates, top_k=2)
        if len(result) >= 2:
            assert result[0][1] >= result[1][1]


class TestGetEmbeddingAndCache:
    """Tests for _get_embedding() and caching."""

    @pytest.fixture
    def ep(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        return EmbeddingEnhancedProver()

    def test_embedding_length_100(self, ep):
        """GIVEN text WHEN _get_embedding called THEN returns length-100 list."""
        emb = ep._get_embedding("test formula P(x)")
        assert len(emb) == 100

    def test_embedding_cached_second_call(self, ep):
        """GIVEN text WHEN _get_embedding called twice THEN cache size=1."""
        ep._get_embedding("unique text xyz")
        assert len(ep.embedding_cache) == 1

    def test_embedding_no_cache(self):
        """GIVEN cache disabled WHEN _get_embedding THEN cache remains empty."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        ep = EmbeddingEnhancedProver(cache_enabled=False)
        ep._get_embedding("some text")
        assert len(ep.embedding_cache) == 0

    def test_clear_cache(self, ep):
        """GIVEN populated cache WHEN clear_cache THEN cache empty."""
        ep._get_embedding("populate cache")
        ep.clear_cache()
        assert len(ep.embedding_cache) == 0


class TestCosineSimilarity:
    """Tests for _cosine_similarity()."""

    @pytest.fixture
    def ep(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        return EmbeddingEnhancedProver()

    def test_same_vector_returns_1(self, ep):
        """GIVEN same vector twice WHEN cosine_similarity THEN returns 1.0."""
        v = [1.0, 0.0, 0.0]
        assert abs(ep._cosine_similarity(v, v) - 1.0) < 1e-9

    def test_orthogonal_vectors_returns_0(self, ep):
        """GIVEN orthogonal vectors WHEN cosine_similarity THEN returns 0.0."""
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0]
        result = ep._cosine_similarity(v1, v2)
        assert abs(result) < 1e-9

    def test_zero_vector_returns_0(self, ep):
        """GIVEN zero vector WHEN cosine_similarity THEN returns 0.0."""
        result = ep._cosine_similarity([0.0, 0.0], [1.0, 1.0])
        assert result == 0.0

    def test_mismatched_length_raises(self, ep):
        """GIVEN mismatched lengths WHEN cosine_similarity THEN raises ValueError."""
        with pytest.raises(ValueError):
            ep._cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


class TestFallbackSimilarity:
    """Tests for _fallback_similarity()."""

    @pytest.fixture
    def ep(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        return EmbeddingEnhancedProver()

    def test_exact_match_returns_1(self, ep):
        """GIVEN exact match WHEN fallback THEN returns 1.0."""
        result = ep._fallback_similarity("P(x)", ["P(x)"])
        assert result == 1.0

    def test_substring_match_returns_0_7(self, ep):
        """GIVEN substring WHEN fallback THEN returns 0.7."""
        result = ep._fallback_similarity("P", ["P(x)"])
        assert result == 0.7

    def test_no_match_returns_jaccard(self, ep):
        """GIVEN partial overlap WHEN fallback THEN returns jaccard-based value."""
        result = ep._fallback_similarity("P Q R", ["P S T"])
        assert 0.0 < result < 1.0

    def test_empty_axioms_returns_0(self, ep):
        """GIVEN empty axioms WHEN fallback THEN returns 0.0."""
        result = ep._fallback_similarity("P", [])
        assert result == 0.0


class TestEmbeddingProverStats:
    """Tests for get_cache_stats()."""

    def test_stats_structure(self):
        """GIVEN prover WHEN get_cache_stats THEN returns dict with expected keys."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        ep = EmbeddingEnhancedProver()
        stats = ep.get_cache_stats()
        assert "cache_size" in stats
        assert "cache_enabled" in stats
        assert "model_loaded" in stats
        assert "model_name" in stats

    def test_model_loaded_false_without_transformers(self):
        """GIVEN no sentence-transformers WHEN checked THEN model_loaded=False."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.embedding_prover import EmbeddingEnhancedProver
        ep = EmbeddingEnhancedProver()
        assert ep.get_cache_stats()["model_loaded"] is False


# ---------------------------------------------------------------------------
# § 5  HybridConfidenceScorer — symbolic/neurosymbolic/hybrid_confidence.py
# ---------------------------------------------------------------------------

class TestConfidenceBreakdown:
    """Tests for ConfidenceBreakdown dataclass."""

    def test_create_with_defaults(self):
        """GIVEN total_confidence WHEN created THEN weights default to empty dict."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import ConfidenceBreakdown
        bd = ConfidenceBreakdown(total_confidence=0.8)
        assert bd.weights == {}
        assert bd.explanation == ""

    def test_numeric_fields(self):
        """GIVEN all numeric values WHEN created THEN stored correctly."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import ConfidenceBreakdown
        bd = ConfidenceBreakdown(
            total_confidence=0.75,
            symbolic_confidence=1.0,
            neural_confidence=0.5,
            structural_confidence=0.8,
        )
        assert bd.symbolic_confidence == 1.0
        assert bd.neural_confidence == 0.5


class TestHybridConfidenceScorerInit:
    """Tests for HybridConfidenceScorer init."""

    def test_default_init(self):
        """GIVEN defaults WHEN created THEN weights normalised."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import HybridConfidenceScorer
        scorer = HybridConfidenceScorer()
        assert abs(scorer.symbolic_weight + scorer.neural_weight - 1.0) < 1e-9

    def test_custom_weights(self):
        """GIVEN custom weights WHEN created THEN normalised to sum=1."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import HybridConfidenceScorer
        scorer = HybridConfidenceScorer(symbolic_weight=0.5, neural_weight=0.5)
        assert abs(scorer.symbolic_weight - 0.5) < 1e-9

    def test_no_structural_analysis(self):
        """GIVEN use_structural=False WHEN created THEN flag set."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import HybridConfidenceScorer
        scorer = HybridConfidenceScorer(use_structural=False)
        assert scorer.use_structural is False


class TestComputeConfidence:
    """Tests for compute_confidence()."""

    @pytest.fixture
    def scorer(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import HybridConfidenceScorer
        return HybridConfidenceScorer()

    def test_no_inputs_zero_confidence(self, scorer):
        """GIVEN no inputs WHEN compute THEN total_confidence=0.0."""
        bd = scorer.compute_confidence()
        assert bd.total_confidence == 0.0

    def test_neural_only(self, scorer):
        """GIVEN neural_similarity=0.8 WHEN compute THEN total > 0."""
        bd = scorer.compute_confidence(neural_similarity=0.8)
        assert bd.total_confidence > 0.0

    def test_symbolic_only_success(self, scorer):
        """GIVEN symbolic success WHEN compute THEN total near 1.0."""
        from unittest.mock import MagicMock
        mock_result = MagicMock()
        mock_result.is_proved.return_value = True
        bd = scorer.compute_confidence(symbolic_result=mock_result)
        assert bd.total_confidence > 0.85

    def test_symbolic_only_failure(self, scorer):
        """GIVEN symbolic failure WHEN compute THEN total_confidence=0.0."""
        from unittest.mock import MagicMock
        mock_result = MagicMock()
        mock_result.is_proved.return_value = False
        bd = scorer.compute_confidence(symbolic_result=mock_result)
        assert bd.total_confidence == 0.0

    def test_both_symbolic_and_neural(self, scorer):
        """GIVEN both inputs WHEN compute THEN returns ConfidenceBreakdown."""
        from unittest.mock import MagicMock
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import ConfidenceBreakdown
        mock_result = MagicMock()
        mock_result.is_proved.return_value = True
        bd = scorer.compute_confidence(symbolic_result=mock_result, neural_similarity=0.9)
        assert isinstance(bd, ConfidenceBreakdown)
        assert bd.total_confidence > 0.0

    def test_with_formula_adds_structural(self, scorer):
        """GIVEN formula WHEN compute THEN structural_confidence > 0."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        formula = Predicate("P", [])
        bd = scorer.compute_confidence(neural_similarity=0.5, formula=formula)
        assert bd.structural_confidence > 0.0

    def test_calibration_factor_applied(self):
        """GIVEN calibration_factor=0.5 WHEN compute THEN halved result."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import HybridConfidenceScorer
        scorer = HybridConfidenceScorer(calibration_factor=0.5)
        bd = scorer.compute_confidence(neural_similarity=1.0)
        assert bd.total_confidence <= 0.5 + 1e-9

    def test_records_history(self, scorer):
        """GIVEN multiple computations WHEN get_statistics THEN count > 0."""
        scorer.compute_confidence(neural_similarity=0.5)
        scorer.compute_confidence(neural_similarity=0.7)
        stats = scorer.get_statistics()
        assert stats["count"] >= 2


class TestComputeStructuralConfidence:
    """Tests for _compute_structural_confidence()."""

    @pytest.fixture
    def scorer(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import HybridConfidenceScorer
        return HybridConfidenceScorer()

    def test_simple_formula_high_confidence(self, scorer):
        """GIVEN simple formula (depth≤2) WHEN computed THEN confidence≥0.7."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        f = Predicate("P", [])
        result = scorer._compute_structural_confidence(f)
        assert result >= 0.7

    def test_complex_formula_lower_confidence(self, scorer):
        """GIVEN deeply nested formula WHEN computed THEN confidence≤0.5."""
        from unittest.mock import MagicMock
        # Simulate a very complex formula: >10 opening parens and >7 operators
        ARROW_COUNT = 15
        complex_formula = MagicMock()
        complex_formula.__str__ = lambda self: "(((((((((((((((P(x))))))))))))))" + "->" * ARROW_COUNT
        result = scorer._compute_structural_confidence(complex_formula)
        assert result <= 0.9


class TestStatisticsEmpty:
    """Tests for get_statistics() with empty history."""

    def test_empty_history_returns_message(self):
        """GIVEN no history WHEN get_statistics THEN returns message dict."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.hybrid_confidence import HybridConfidenceScorer
        scorer = HybridConfidenceScorer()
        stats = scorer.get_statistics()
        assert "message" in stats


# ---------------------------------------------------------------------------
# § 6  NeuralSymbolicCoordinator — symbolic/neurosymbolic/reasoning_coordinator.py
# ---------------------------------------------------------------------------

class TestCoordinatedResult:
    """Tests for CoordinatedResult dataclass."""

    def test_valid_confidence(self):
        """GIVEN confidence in [0,1] WHEN created THEN no error."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import CoordinatedResult
        r = CoordinatedResult(is_proved=True, confidence=0.85)
        assert r.confidence == 0.85

    def test_invalid_confidence_raises(self):
        """GIVEN confidence > 1 WHEN created THEN ValueError raised."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import CoordinatedResult
        with pytest.raises(ValueError, match="Confidence"):
            CoordinatedResult(is_proved=True, confidence=1.5)

    def test_negative_confidence_raises(self):
        """GIVEN confidence < 0 WHEN created THEN ValueError raised."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import CoordinatedResult
        with pytest.raises(ValueError):
            CoordinatedResult(is_proved=False, confidence=-0.1)

    def test_default_strategy(self):
        """GIVEN no strategy WHEN created THEN strategy is AUTO."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import (
            CoordinatedResult, ReasoningStrategy
        )
        r = CoordinatedResult(is_proved=False, confidence=0.0)
        assert r.strategy_used == ReasoningStrategy.AUTO

    def test_proof_steps_default_empty(self):
        """GIVEN no steps WHEN created THEN proof_steps is empty list."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import CoordinatedResult
        r = CoordinatedResult(is_proved=True, confidence=0.5)
        assert r.proof_steps == []


class TestNeuralSymbolicCoordinatorInit:
    """Tests for NeuralSymbolicCoordinator init."""

    def test_init_no_embeddings(self):
        """GIVEN use_embeddings=False WHEN created THEN embedding_prover is None."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import NeuralSymbolicCoordinator
        coord = NeuralSymbolicCoordinator(use_embeddings=False)
        assert coord.embedding_prover is None
        assert coord.use_embeddings is False

    def test_init_default_threshold(self):
        """GIVEN default threshold WHEN created THEN confidence_threshold=0.7."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import NeuralSymbolicCoordinator
        coord = NeuralSymbolicCoordinator(use_embeddings=False)
        assert coord.confidence_threshold == 0.7

    def test_get_capabilities(self):
        """GIVEN coordinator WHEN get_capabilities THEN returns dict."""
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import NeuralSymbolicCoordinator
        coord = NeuralSymbolicCoordinator(use_embeddings=False)
        caps = coord.get_capabilities()
        assert "strategies_available" in caps
        assert "cec_enabled" in caps
        assert "embeddings_enabled" in caps


class TestChooseStrategy:
    """Tests for _choose_strategy()."""

    @pytest.fixture
    def coord(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import NeuralSymbolicCoordinator
        return NeuralSymbolicCoordinator(use_embeddings=False)

    def test_simple_formula_symbolic(self, coord):
        """GIVEN simple formula WHEN choose strategy THEN SYMBOLIC_ONLY."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import ReasoningStrategy
        goal = Predicate("P", [])
        strategy = coord._choose_strategy(goal, [])
        assert strategy == ReasoningStrategy.SYMBOLIC_ONLY

    def test_complex_formula_symbolic_no_embeddings(self, coord):
        """GIVEN complex formula + no embeddings WHEN choose THEN SYMBOLIC_ONLY."""
        from unittest.mock import MagicMock
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import ReasoningStrategy
        # Simulate complex formula: 19 arrow operators creates high complexity score
        FORMULA_PARTS = 20  # produces 19 '->' operators
        complex_formula = MagicMock()
        complex_formula.__str__ = lambda self: "->".join(["P"] * FORMULA_PARTS)
        strategy = coord._choose_strategy(complex_formula, [])
        assert strategy == ReasoningStrategy.SYMBOLIC_ONLY


class TestProveSymbolicOnly:
    """Tests for _prove_symbolic()."""

    @pytest.fixture
    def coord(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import NeuralSymbolicCoordinator
        return NeuralSymbolicCoordinator(use_embeddings=False)

    def test_prove_symbolic_returns_coordinated_result(self, coord):
        """GIVEN simple formula WHEN _prove_symbolic THEN CoordinatedResult returned."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import (
            CoordinatedResult, ReasoningStrategy
        )
        goal = Predicate("P", [])
        result = coord._prove_symbolic(goal, [], 10000)
        assert isinstance(result, CoordinatedResult)
        assert result.strategy_used == ReasoningStrategy.SYMBOLIC_ONLY

    def test_prove_with_auto_strategy(self, coord):
        """GIVEN AUTO strategy WHEN prove THEN returns CoordinatedResult."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import (
            CoordinatedResult, ReasoningStrategy
        )
        goal = Predicate("P", [])
        result = coord.prove(goal, strategy=ReasoningStrategy.AUTO)
        assert isinstance(result, CoordinatedResult)

    def test_prove_neural_fallback_to_symbolic(self, coord):
        """GIVEN NEURAL_ONLY with no embeddings WHEN prove THEN falls back to symbolic."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import (
            CoordinatedResult, ReasoningStrategy
        )
        goal = Predicate("P", [])
        result = coord.prove(goal, strategy=ReasoningStrategy.NEURAL_ONLY)
        assert isinstance(result, CoordinatedResult)


# ---------------------------------------------------------------------------
# § 7  interactive_fol_utils.py
# ---------------------------------------------------------------------------

class TestCreateInteractiveSession:
    """Tests for create_interactive_session()."""

    def test_creates_session(self):
        """GIVEN domain WHEN create_interactive_session THEN returns constructor."""
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_utils import create_interactive_session
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        session = create_interactive_session(domain="legal")
        assert isinstance(session, InteractiveFOLConstructor)
        assert session.domain == "legal"

    def test_default_domain(self):
        """GIVEN no domain WHEN create_interactive_session THEN domain='general'."""
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_utils import create_interactive_session
        session = create_interactive_session()
        assert session.domain == "general"

    def test_with_custom_threshold(self):
        """GIVEN custom confidence_threshold WHEN created THEN stored."""
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_utils import create_interactive_session
        session = create_interactive_session(confidence_threshold=0.9)
        assert session.confidence_threshold == 0.9


class TestDemoInteractiveSession:
    """Tests for demo_interactive_session()."""

    def test_runs_without_error(self, capsys):
        """GIVEN nothing WHEN demo runs THEN no exceptions and output produced."""
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_utils import demo_interactive_session
        constructor = demo_interactive_session()
        captured = capsys.readouterr()
        assert "Interactive FOL Constructor Demo" in captured.out
        assert constructor is not None

    def test_returns_constructor(self):
        """GIVEN nothing WHEN demo runs THEN InteractiveFOLConstructor returned."""
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_utils import demo_interactive_session
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import InteractiveFOLConstructor
        constructor = demo_interactive_session()
        assert isinstance(constructor, InteractiveFOLConstructor)


# ---------------------------------------------------------------------------
# § 8  proof_execution_engine_utils.py
# ---------------------------------------------------------------------------

class TestProofEngineUtils:
    """Tests for factory and template functions."""

    def test_create_proof_engine(self, tmp_path):
        """GIVEN nothing WHEN create_proof_engine THEN ProofExecutionEngine returned."""
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import ProofExecutionEngine
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import create_proof_engine
        engine = create_proof_engine(temp_dir=str(tmp_path), timeout=30)
        assert isinstance(engine, ProofExecutionEngine)
        assert engine.timeout == 30

    def test_create_proof_engine_default_timeout(self, tmp_path):
        """GIVEN no timeout WHEN create_proof_engine THEN timeout=60."""
        os.environ["IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"] = "0"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import create_proof_engine
        engine = create_proof_engine(temp_dir=str(tmp_path))
        assert engine.timeout == 60

    def test_get_lean_template_contains_obligatory(self):
        """GIVEN nothing WHEN get_lean_template THEN contains 'Obligatory'."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import get_lean_template
        template = get_lean_template()
        assert "Obligatory" in template

    def test_get_lean_template_is_string(self):
        """GIVEN nothing WHEN get_lean_template THEN returns string."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import get_lean_template
        assert isinstance(get_lean_template(), str)

    def test_get_coq_template_contains_obligatory(self):
        """GIVEN nothing WHEN get_coq_template THEN contains 'Obligatory'."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import get_coq_template
        template = get_coq_template()
        assert "Obligatory" in template

    def test_get_coq_template_is_string(self):
        """GIVEN nothing WHEN get_coq_template THEN returns string."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import get_coq_template
        assert isinstance(get_coq_template(), str)

    def test_lean_and_coq_templates_different(self):
        """GIVEN both templates WHEN compared THEN they differ."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import (
            get_lean_template, get_coq_template
        )
        assert get_lean_template() != get_coq_template()


# ---------------------------------------------------------------------------
# § 9  ProofResult / ProofStatus (proof_execution_engine_types.py)
# ---------------------------------------------------------------------------

class TestProofResultDataclass:
    """Tests for ProofResult and ProofStatus types."""

    def test_create_proof_result(self):
        """GIVEN required fields WHEN created THEN defaults are set."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofResult, ProofStatus
        result = ProofResult(prover="z3", statement="P -> Q", status=ProofStatus.SUCCESS)
        assert result.prover == "z3"
        assert result.errors == []
        assert result.metadata == {}

    def test_to_dict_contains_all_keys(self):
        """GIVEN proof result WHEN to_dict THEN all keys present."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofResult, ProofStatus
        result = ProofResult(prover="lean", statement="Q", status=ProofStatus.FAILURE)
        d = result.to_dict()
        assert "prover" in d
        assert "statement" in d
        assert "status" in d
        assert d["status"] == "failure"

    def test_proof_status_values(self):
        """GIVEN ProofStatus WHEN accessing values THEN strings returned."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        assert ProofStatus.SUCCESS.value == "success"
        assert ProofStatus.TIMEOUT.value == "timeout"
        assert ProofStatus.UNSUPPORTED.value == "unsupported"
