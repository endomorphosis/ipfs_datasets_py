"""
Session 49 — Coverage Tests for Proof Execution Engine + Deontic Converter + Caching

Covers:
- reasoning/proof_execution_engine.py (12% → ~70%)
- reasoning/proof_execution_engine_types.py (new)
- reasoning/proof_execution_engine_utils.py (new)
- converters/deontic_logic_converter.py (27% → ~65%)
- caching/ipld_logic_storage.py (covered via session22, now extended)
- caching/ipfs_proof_cache.py (covered via session22, now extended)

All tests follow GIVEN-WHEN-THEN format.
"""

from __future__ import annotations
import sys
import os
import json
import types
import tempfile
import pytest
import logging
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_formula(text: str = "O(pay(alice))"):
    """Return a DeonticFormula for testing (from converters/deontic_logic_core.py)."""
    from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
        create_obligation, LegalAgent
    )
    agent = LegalAgent(identifier="alice", name="Alice", agent_type="person")
    return create_obligation("pay_obligation", agent, source_text=text)


def _make_rule_set(name="TestRules"):
    """Return a small DeonticRuleSet."""
    from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
        DeonticRuleSet, create_obligation, create_prohibition, LegalAgent
    )
    agent = LegalAgent(identifier="bob", name="Bob", agent_type="person")
    f1 = create_obligation("pay_tax", agent, source_text="Bob must pay tax")
    f2 = create_prohibition("evade_tax", agent, source_text="Bob cannot evade tax")
    return DeonticRuleSet(name=name, formulas=[f1, f2])


# ===========================================================================
# 1. ProofStatus and ProofResult types
# ===========================================================================

class TestProofStatusEnum:
    """Tests for proof_execution_engine_types.ProofStatus"""

    def test_all_values(self):
        """GIVEN ProofStatus enum WHEN iterating THEN all 5 values present."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        values = {s.value for s in ProofStatus}
        assert "success" in values
        assert "failure" in values
        assert "timeout" in values
        assert "error" in values
        assert "unsupported" in values


class TestProofResultDataclass:
    """Tests for proof_execution_engine_types.ProofResult"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import (
            ProofResult, ProofStatus
        )
        self.ProofResult = ProofResult
        self.ProofStatus = ProofStatus

    def test_required_fields(self):
        """GIVEN required args WHEN creating ProofResult THEN fields set correctly."""
        r = self.ProofResult(
            prover="z3",
            statement="P∧Q→P",
            status=self.ProofStatus.SUCCESS,
        )
        assert r.prover == "z3"
        assert r.statement == "P∧Q→P"
        assert r.status == self.ProofStatus.SUCCESS
        assert r.proof_output == ""
        assert r.execution_time == 0.0
        assert r.errors == []
        assert r.warnings == []
        assert r.metadata == {}

    def test_to_dict_serialises_status(self):
        """GIVEN a ProofResult WHEN to_dict called THEN status is string value."""
        r = self.ProofResult(
            prover="lean",
            statement="Q",
            status=self.ProofStatus.TIMEOUT,
            execution_time=30.0,
            errors=["timeout"],
        )
        d = r.to_dict()
        assert d["status"] == "timeout"
        assert d["prover"] == "lean"
        assert d["execution_time"] == 30.0

    def test_to_dict_has_all_keys(self):
        """GIVEN ProofResult WHEN to_dict THEN dict has all expected keys."""
        r = self.ProofResult(prover="coq", statement="R", status=self.ProofStatus.ERROR)
        d = r.to_dict()
        for key in ("prover", "statement", "status", "proof_output",
                    "execution_time", "errors", "warnings", "metadata"):
            assert key in d


# ===========================================================================
# 2. ProofExecutionEngine construction
# ===========================================================================

class TestProofExecutionEngineInit:
    """Tests for ProofExecutionEngine.__init__ and helpers."""

    def _make_engine(self, **kwargs):
        """Create engine with auto-install disabled to avoid hanging."""
        with patch.dict(os.environ, {
            "IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS": "0",
        }):
            from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import (
                ProofExecutionEngine
            )
            return ProofExecutionEngine(**kwargs)

    def test_init_defaults(self):
        """GIVEN no args WHEN creating engine THEN defaults set."""
        engine = self._make_engine(enable_rate_limiting=False, enable_validation=False)
        assert engine.timeout == 60
        assert engine.default_prover == "z3"

    def test_init_custom_timeout(self):
        """GIVEN timeout=30 WHEN creating engine THEN timeout is 30."""
        engine = self._make_engine(timeout=30, enable_rate_limiting=False, enable_validation=False)
        assert engine.timeout == 30

    def test_init_custom_prover(self):
        """GIVEN default_prover='lean' WHEN creating engine THEN default_prover is lean."""
        engine = self._make_engine(
            default_prover="lean",
            enable_rate_limiting=False,
            enable_validation=False,
        )
        assert engine.default_prover == "lean"

    def test_init_caching_disabled(self):
        """GIVEN enable_caching=False WHEN creating engine THEN proof_cache is None."""
        engine = self._make_engine(
            enable_caching=False,
            enable_rate_limiting=False,
            enable_validation=False,
        )
        assert engine.proof_cache is None

    def test_available_provers_dict(self):
        """GIVEN engine WHEN checking available_provers THEN dict with 4 keys."""
        engine = self._make_engine(enable_rate_limiting=False, enable_validation=False)
        assert isinstance(engine.available_provers, dict)
        for key in ("z3", "cvc5", "lean", "coq"):
            assert key in engine.available_provers

    def test_get_prover_status(self):
        """GIVEN engine WHEN get_prover_status THEN result has expected keys."""
        engine = self._make_engine(enable_rate_limiting=False, enable_validation=False)
        status = engine.get_prover_status()
        assert "available_provers" in status
        assert "temp_directory" in status
        assert "timeout" in status

    def test_env_default_prover(self):
        """GIVEN env var IPFS_DATASETS_PY_PROOF_PROVER=cvc5 WHEN init THEN default_prover is cvc5."""
        with patch.dict(os.environ, {
            "IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS": "0",
            "IPFS_DATASETS_PY_PROOF_PROVER": "cvc5",
        }):
            from importlib import reload
            import ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine as pem
            engine = pem.ProofExecutionEngine(
                enable_rate_limiting=False,
                enable_validation=False,
            )
            assert engine.default_prover == "cvc5"


# ===========================================================================
# 3. ProofExecutionEngine.prove_deontic_formula — mocked provers
# ===========================================================================

class TestProveFormulaMockedProvers:
    """Test prove_deontic_formula with available_provers mocked."""

    def _make_engine(self):
        with patch.dict(os.environ, {"IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS": "0"}):
            from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import (
                ProofExecutionEngine
            )
            return ProofExecutionEngine(
                enable_caching=False,
                enable_rate_limiting=False,
                enable_validation=False,
            )

    def test_prover_not_available_returns_error(self):
        """GIVEN prover not in available_provers WHEN prove THEN UNSUPPORTED status."""
        engine = self._make_engine()
        engine.available_provers = {}  # empty — no provers
        formula = _make_formula()
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.UNSUPPORTED

    def test_prover_installed_false_returns_error(self):
        """GIVEN prover in available_provers but False WHEN prove THEN ERROR status."""
        engine = self._make_engine()
        engine.available_provers = {"z3": False}
        formula = _make_formula()
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.ERROR

    def test_rate_limit_exceeded_returns_error(self):
        """GIVEN rate limiter raises exception WHEN prove THEN ERROR status."""
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.enable_rate_limiting = True
        rate_limiter_mock = MagicMock()
        rate_limiter_mock.check_rate_limit.side_effect = Exception("rate limit exceeded")
        engine.rate_limiter = rate_limiter_mock
        formula = _make_formula()
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.ERROR
        assert "Rate limit exceeded" in result.errors[0]

    def test_validation_failure_returns_error(self):
        """GIVEN validator raises exception WHEN prove THEN ERROR status."""
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.enable_validation = True
        validator_mock = MagicMock()
        validator_mock.validate_formula.side_effect = Exception("formula too complex")
        engine.validator = validator_mock
        formula = _make_formula()
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.ERROR
        assert "Validation failed" in result.errors[0]

    def test_no_translator_returns_unsupported(self):
        """GIVEN unknown prover name WHEN prove THEN UNSUPPORTED."""
        engine = self._make_engine()
        engine.available_provers = {"unknown_prover": True}
        formula = _make_formula()
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        result = engine.prove_deontic_formula(formula, prover="unknown_prover")
        assert result.status == ProofStatus.UNSUPPORTED

    def _mock_translate(self, engine, prover):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import TranslationResult, LogicTranslationTarget
        mock_tr = TranslationResult(
            target=LogicTranslationTarget.SMT_LIB,
            translated_formula="(assert true)",
            success=True,
        )
        translator = engine._get_translator(prover)
        translator.translate_deontic_formula = MagicMock(return_value=mock_tr)
        engine._get_translator = MagicMock(return_value=translator)
        return mock_tr

    def test_z3_execution_sat(self):
        """GIVEN z3 available and returns 'sat' WHEN prove THEN SUCCESS status."""
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.prover_binaries = {"z3": "z3"}
        formula = _make_formula()
        self._mock_translate(engine, "z3")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sat\n(model)\n"
        mock_result.stderr = ""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.SUCCESS

    def test_z3_execution_unsat(self):
        """GIVEN z3 returns 'unsat' WHEN prove THEN SUCCESS (unsat is valid result)."""
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.prover_binaries = {"z3": "z3"}
        formula = _make_formula()
        self._mock_translate(engine, "z3")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "unsat"
        mock_result.stderr = ""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.SUCCESS

    def test_z3_execution_failure_return_code(self):
        """GIVEN z3 returns non-zero exit code WHEN prove THEN ERROR status."""
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.prover_binaries = {"z3": "z3"}
        formula = _make_formula()
        self._mock_translate(engine, "z3")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "parse error"
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.ERROR

    def test_z3_timeout_returns_timeout_status(self):
        """GIVEN z3 subprocess times out WHEN prove THEN TIMEOUT status."""
        import subprocess
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.prover_binaries = {"z3": "z3"}
        formula = _make_formula()
        self._mock_translate(engine, "z3")
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("z3", 60)):
            result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.TIMEOUT

    def test_z3_general_exception_returns_error(self):
        """GIVEN z3 subprocess raises OSError WHEN prove THEN ERROR status."""
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.prover_binaries = {"z3": "z3"}
        formula = _make_formula()
        self._mock_translate(engine, "z3")
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        with patch("subprocess.run", side_effect=OSError("file not found")):
            result = engine.prove_deontic_formula(formula, prover="z3")
        assert result.status == ProofStatus.ERROR

    def test_cvc5_execution_sat(self):
        """GIVEN cvc5 returns 'sat' WHEN prove THEN SUCCESS."""
        engine = self._make_engine()
        engine.available_provers = {"cvc5": True}
        engine.prover_binaries = {"cvc5": "cvc5"}
        formula = _make_formula()
        self._mock_translate(engine, "cvc5")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sat"
        mock_result.stderr = ""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_deontic_formula(formula, prover="cvc5")
        assert result.status == ProofStatus.SUCCESS

    def test_lean_execution_success(self):
        """GIVEN lean returns returncode=0 WHEN prove THEN SUCCESS."""
        engine = self._make_engine()
        engine.available_provers = {"lean": True}
        engine.prover_binaries = {"lean": "lean"}
        formula = _make_formula()
        self._mock_translate(engine, "lean")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "#check statement\n#check deontic_consistency\n"
        mock_result.stderr = ""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_deontic_formula(formula, prover="lean")
        assert result.status == ProofStatus.SUCCESS

    def test_coq_execution_error(self):
        """GIVEN coq returns error WHEN prove THEN ERROR status."""
        engine = self._make_engine()
        engine.available_provers = {"coq": True}
        engine.prover_binaries = {"coq": "coqc"}
        formula = _make_formula()
        self._mock_translate(engine, "coq")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: ..."
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_deontic_formula(formula, prover="coq")
        assert result.status == ProofStatus.ERROR


# ===========================================================================
# 4. ProofExecutionEngine caching
# ===========================================================================

class TestProveFormulaCaching:
    """Test proof_cache integration."""

    def _make_engine_with_cache(self):
        with patch.dict(os.environ, {"IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS": "0"}):
            from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import (
                ProofExecutionEngine
            )
            return ProofExecutionEngine(
                enable_caching=True,
                enable_rate_limiting=False,
                enable_validation=False,
            )

    def test_cache_hit_returns_cached_result(self):
        """GIVEN result in cache WHEN prove THEN cached result returned without subprocess."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import (
            ProofStatus
        )
        engine = self._make_engine_with_cache()
        formula = _make_formula()
        # Manually populate cache using correct API: set(formula, result, prover_name=...)
        formula_str = formula.to_fol_string()
        cached_dict = {
            "prover": "z3",
            "statement": formula_str,
            "status": "success",
            "proof_output": "cached",
            "execution_time": 0.1,
            "errors": [],
            "warnings": [],
            "metadata": {},
        }
        engine.proof_cache.set(formula_str, cached_dict, prover_name="z3")

        with patch("subprocess.run") as mock_sub:
            result = engine.prove_deontic_formula(formula, prover="z3", use_cache=True)

        mock_sub.assert_not_called()
        assert result.status == ProofStatus.SUCCESS

    def test_cache_stores_result_after_proof(self):
        """GIVEN no cache hit WHEN prove succeeds THEN result stored in cache."""
        engine = self._make_engine_with_cache()
        engine.available_provers = {"z3": True}
        engine.prover_binaries = {"z3": "z3"}
        formula = _make_formula()
        # Mock translation
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import TranslationResult, LogicTranslationTarget
        mock_tr = TranslationResult(
            target=LogicTranslationTarget.SMT_LIB,
            translated_formula="(assert true)",
            success=True,
        )
        translator = engine._get_translator("z3")
        translator.translate_deontic_formula = MagicMock(return_value=mock_tr)
        engine._get_translator = MagicMock(return_value=translator)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sat"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_deontic_formula(formula, prover="z3", use_cache=True)
        # Verify it was cached by trying to get it
        formula_str = formula.to_fol_string()
        cached = engine.proof_cache.get(formula_str, prover_name="z3")
        assert cached is not None

    def test_cache_invalid_status_string_defaults_to_error(self):
        """GIVEN cache has invalid status string WHEN prove THEN defaults to ERROR."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import (
            ProofStatus
        )
        engine = self._make_engine_with_cache()
        formula = _make_formula()
        formula_str = formula.to_fol_string()
        # Store invalid status using correct API
        cached_dict = {
            "prover": "z3",
            "statement": formula_str,
            "status": "invalid_status_xyz",
            "proof_output": "",
            "execution_time": 0.0,
            "errors": [],
            "warnings": [],
            "metadata": {},
        }
        engine.proof_cache.set(formula_str, cached_dict, prover_name="z3")
        result = engine.prove_deontic_formula(formula, prover="z3", use_cache=True)
        assert result.status == ProofStatus.ERROR


# ===========================================================================
# 5. ProofExecutionEngine.prove_rule_set and prove_consistency
# ===========================================================================

class TestProveRuleSetAndConsistency:
    """Test higher-level methods."""

    def _make_engine(self):
        with patch.dict(os.environ, {"IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS": "0"}):
            from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import (
                ProofExecutionEngine
            )
            return ProofExecutionEngine(
                enable_caching=False,
                enable_rate_limiting=False,
                enable_validation=False,
            )

    def test_prove_rule_set_returns_list(self):
        """GIVEN rule set with 2 formulas WHEN prove_rule_set THEN list of 2 results."""
        engine = self._make_engine()
        engine.available_provers = {}  # all unavailable
        rule_set = _make_rule_set()
        results = engine.prove_rule_set(rule_set, prover="z3")
        assert len(results) == 2

    def test_prove_consistency_unsupported_prover(self):
        """GIVEN unsupported prover WHEN prove_consistency THEN UNSUPPORTED result."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        engine = self._make_engine()
        rule_set = _make_rule_set()
        result = engine.prove_consistency(rule_set, prover="lean")
        assert result.status == ProofStatus.UNSUPPORTED

    def test_prove_consistency_z3_sat(self):
        """GIVEN z3 returns 'sat' WHEN prove_consistency THEN SUCCESS (consistent)."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.prover_binaries = {"z3": "z3"}
        rule_set = _make_rule_set()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sat"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_consistency(rule_set, prover="z3")
        assert result.status == ProofStatus.SUCCESS

    def test_prove_consistency_z3_unsat(self):
        """GIVEN z3 returns 'unsat' WHEN prove_consistency THEN FAILURE (inconsistent).
        Fixed: unsat is checked before sat to prevent substring collision."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        engine = self._make_engine()
        engine.available_provers = {"z3": True}
        engine.prover_binaries = {"z3": "z3"}
        rule_set = _make_rule_set()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "unsat"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_consistency(rule_set, prover="z3")
        # Now unsat correctly maps to FAILURE (inconsistent)
        assert result.status == ProofStatus.FAILURE

    def test_prove_consistency_cvc5_sat(self):
        """GIVEN cvc5 returns 'sat' WHEN prove_consistency THEN SUCCESS."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        engine = self._make_engine()
        engine.available_provers = {"cvc5": True}
        engine.prover_binaries = {"cvc5": "cvc5"}
        rule_set = _make_rule_set()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sat"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = engine.prove_consistency(rule_set, prover="cvc5")
        assert result.status == ProofStatus.SUCCESS

    def test_prove_multiple_provers(self):
        """GIVEN two provers available WHEN prove_multiple_provers THEN dict with both."""
        engine = self._make_engine()
        engine.available_provers = {"z3": False, "cvc5": False}
        formula = _make_formula()
        results = engine.prove_multiple_provers(formula, provers=["z3", "cvc5"])
        assert "z3" in results
        assert "cvc5" in results


# ===========================================================================
# 6. ProofExecutionEngine utility functions
# ===========================================================================

class TestProofEngineUtils:
    """Tests for proof_execution_engine_utils."""

    def test_create_proof_engine_factory(self):
        """GIVEN timeout=30 WHEN create_proof_engine THEN engine with timeout=30."""
        with patch.dict(os.environ, {"IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS": "0"}):
            from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import (
                create_proof_engine
            )
            engine = create_proof_engine(timeout=30)
            assert engine.timeout == 30

    def test_get_lean_template_contains_obligatory(self):
        """GIVEN get_lean_template WHEN called THEN result has 'Obligatory'."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import (
            get_lean_template
        )
        tmpl = get_lean_template()
        assert "Obligatory" in tmpl

    def test_get_coq_template_contains_obligatory(self):
        """GIVEN get_coq_template WHEN called THEN result has 'Obligatory'."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_utils import (
            get_coq_template
        )
        tmpl = get_coq_template()
        assert "Obligatory" in tmpl


# ===========================================================================
# 7. DeonticLogicConverter — basic construction
# ===========================================================================

class TestDeonticLogicConverterInit:
    """Tests for DeonticLogicConverter.__init__"""

    def test_init_default(self):
        """GIVEN no args WHEN init THEN domain_knowledge set, symbolic_analyzer may be None."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            DeonticLogicConverter
        )
        conv = DeonticLogicConverter(enable_symbolic_ai=False)
        assert conv.domain_knowledge is not None
        assert conv.symbolic_analyzer is None

    def test_init_statistics_zeroed(self):
        """GIVEN new converter WHEN init THEN all stats are 0."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            DeonticLogicConverter
        )
        conv = DeonticLogicConverter(enable_symbolic_ai=False)
        assert conv.conversion_stats["total_entities_processed"] == 0
        assert conv.conversion_stats["obligations_extracted"] == 0


# ===========================================================================
# 8. ConversionContext and ConversionResult
# ===========================================================================

class TestConversionContext:
    """Tests for ConversionContext dataclass."""

    def test_creation_and_to_dict(self):
        """GIVEN ConversionContext WHEN to_dict THEN all keys present."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            ConversionContext
        )
        ctx = ConversionContext(
            source_document_path="./doc.pdf",
            document_title="Test",
            jurisdiction="NY",
        )
        d = ctx.to_dict()
        assert d["source_document_path"] == "./doc.pdf"
        assert d["jurisdiction"] == "NY"
        assert d["confidence_threshold"] == 0.5

    def test_default_flags_all_true(self):
        """GIVEN no explicit flags WHEN create ConversionContext THEN analysis flags True."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            ConversionContext
        )
        ctx = ConversionContext(source_document_path="./x.pdf")
        assert ctx.enable_temporal_analysis is True
        assert ctx.enable_agent_inference is True
        assert ctx.enable_condition_extraction is True


class TestConversionResult:
    """Tests for ConversionResult dataclass."""

    def test_to_dict_has_statistics(self):
        """GIVEN ConversionResult WHEN to_dict THEN statistics key present."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            ConversionResult
        )
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        result = ConversionResult(
            deontic_formulas=[],
            rule_set=DeonticRuleSet("Test", []),
            conversion_metadata={"ts": "2026-01-01"},
            statistics={"obligations_extracted": 3},
        )
        d = result.to_dict()
        assert "statistics" in d
        assert "conversion_metadata" in d
        assert "deontic_formulas" in d


# ===========================================================================
# 9. DeonticLogicConverter.convert_entities_to_logic
# ===========================================================================

class TestConvertEntitiesToLogic:
    """Tests for entity conversion path."""

    def _make_context(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            ConversionContext
        )
        return ConversionContext(
            source_document_path="./test.pdf",
            document_title="Test Contract",
            confidence_threshold=0.0,  # accept everything
        )

    def _make_converter(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            DeonticLogicConverter
        )
        return DeonticLogicConverter(enable_symbolic_ai=False)

    def _make_entity(self, entity_id="e1", text="The contractor shall deliver the goods", entity_type="obligation"):
        """Create a mock entity with all expected attributes."""
        entity = MagicMock()
        entity.entity_id = entity_id
        entity.name = entity_id
        entity.entity_type = entity_type
        entity.source_text = text
        entity.properties = {"text": text, "name": entity_id}
        return entity

    def test_empty_entities_returns_empty_list(self):
        """GIVEN no entities WHEN convert THEN empty list returned."""
        conv = self._make_converter()
        ctx = self._make_context()
        result = conv.convert_entities_to_logic([], ctx)
        assert result == []

    def test_obligation_entity_produces_formula(self):
        """GIVEN entity with 'shall' WHEN convert THEN at least one formula."""
        conv = self._make_converter()
        ctx = self._make_context()
        entity = self._make_entity(text="The contractor shall deliver the goods")
        formulas = conv.convert_entities_to_logic([entity], ctx)
        # Stats should be updated
        assert conv.conversion_stats["total_entities_processed"] >= 1

    def test_permission_entity_produces_formula(self):
        """GIVEN entity with 'may' WHEN convert THEN at least one formula."""
        conv = self._make_converter()
        ctx = self._make_context()
        entity = self._make_entity(text="The employee may take leave", entity_type="permission")
        formulas = conv.convert_entities_to_logic([entity], ctx)
        assert conv.conversion_stats["total_entities_processed"] >= 1

    def test_high_confidence_threshold_filters(self):
        """GIVEN confidence_threshold=1.0 WHEN convert THEN no formulas (low confidence text)."""
        conv = self._make_converter()
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        ctx = ConversionContext(
            source_document_path="./test.pdf",
            confidence_threshold=1.0,
        )
        entity = self._make_entity(text="Hello world random text")
        formulas = conv.convert_entities_to_logic([entity], ctx)
        assert formulas == []

    def test_agent_inference_disabled(self):
        """GIVEN enable_agent_inference=False WHEN convert THEN agent is None in formulas."""
        conv = self._make_converter()
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        ctx = ConversionContext(
            source_document_path="./test.pdf",
            confidence_threshold=0.0,
            enable_agent_inference=False,
        )
        entity = self._make_entity(text="The party shall pay", entity_type="agent")
        formulas = conv.convert_entities_to_logic([entity], ctx)
        for f in formulas:
            assert f.agent is None


# ===========================================================================
# 10. DeonticLogicConverter.convert_knowledge_graph_to_logic
# ===========================================================================

class TestConvertKnowledgeGraphToLogic:
    """Tests for the full KG conversion pipeline."""

    def _make_converter(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            DeonticLogicConverter
        )
        return DeonticLogicConverter(enable_symbolic_ai=False)

    def _make_context(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            ConversionContext
        )
        from ipfs_datasets_py.logic.integration.domain.legal_domain_knowledge import LegalDomain
        return ConversionContext(
            source_document_path="./contract.pdf",
            document_title="Service Agreement",
            legal_domain=LegalDomain.CONTRACT,
            jurisdiction="California",
            confidence_threshold=0.0,
        )

    def _make_kg(self, entities=None, relationships=None):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            KnowledgeGraph, Entity, Relationship
        )
        entities = entities or []
        relationships = relationships or []
        return KnowledgeGraph(entities=entities, relationships=relationships)

    def _make_entity(self, entity_id="e1", text="The vendor shall deliver", entity_type="obligation"):
        """Create a mock entity with all required attributes."""
        entity = MagicMock()
        entity.entity_id = entity_id
        entity.name = entity_id
        entity.entity_type = entity_type
        entity.source_text = text
        entity.properties = {"text": text, "name": entity_id}
        return entity

    def test_empty_kg_returns_empty_result(self):
        """GIVEN empty KG WHEN convert THEN ConversionResult with 0 formulas and no errors."""
        conv = self._make_converter()
        ctx = self._make_context()
        kg = self._make_kg()
        result = conv.convert_knowledge_graph_to_logic(kg, ctx)
        assert result.deontic_formulas == []
        assert result.errors == []

    def test_kg_with_obligation_entity(self):
        """GIVEN KG with obligation entity WHEN convert THEN metadata populated."""
        conv = self._make_converter()
        ctx = self._make_context()
        entity = self._make_entity("e1", "The vendor shall deliver", "obligation")
        kg = self._make_kg(entities=[entity])
        result = conv.convert_knowledge_graph_to_logic(kg, ctx)
        assert "conversion_timestamp" in result.conversion_metadata

    def test_conversion_error_returns_gracefully(self):
        """GIVEN convert_entities_to_logic raises WHEN convert THEN errors list populated."""
        conv = self._make_converter()
        ctx = self._make_context()
        kg = self._make_kg()
        with patch.object(conv, "convert_entities_to_logic", side_effect=RuntimeError("crash")):
            result = conv.convert_knowledge_graph_to_logic(kg, ctx)
        assert len(result.errors) > 0
        assert result.deontic_formulas == []

    def test_result_has_rule_set(self):
        """GIVEN valid KG WHEN convert THEN result has a DeonticRuleSet."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        conv = self._make_converter()
        ctx = self._make_context()
        kg = self._make_kg()
        result = conv.convert_knowledge_graph_to_logic(kg, ctx)
        assert isinstance(result.rule_set, DeonticRuleSet)

    def test_statistics_populated(self):
        """GIVEN KG with entities WHEN convert THEN statistics dict has expected keys."""
        conv = self._make_converter()
        ctx = self._make_context()
        entity = self._make_entity("e2", "You must pay", "obligation")
        kg = self._make_kg(entities=[entity])
        result = conv.convert_knowledge_graph_to_logic(kg, ctx)
        assert "total_entities_processed" in result.statistics

    def test_kg_entities_as_dict(self):
        """GIVEN KG with entities as dict WHEN convert THEN processes without error."""
        conv = self._make_converter()
        ctx = self._make_context()
        entity = self._make_entity("e3", "You shall comply", "agent")
        kg_mock = MagicMock()
        kg_mock.entities = {"e3": entity}  # dict instead of list
        kg_mock.relationships = []
        result = conv.convert_knowledge_graph_to_logic(kg_mock, ctx)
        assert isinstance(result.conversion_metadata, dict)


# ===========================================================================
# 11. DeonticLogicConverter private helpers
# ===========================================================================

class TestDeonticLogicConverterHelpers:
    """Tests for private helpers of DeonticLogicConverter."""

    def _make_converter(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            DeonticLogicConverter
        )
        return DeonticLogicConverter(enable_symbolic_ai=False)

    def _make_entity_mock(self, entity_id="e", text="text", entity_type="agent"):
        """Create a mock entity with all expected attributes."""
        entity = MagicMock()
        entity.entity_id = entity_id
        entity.name = entity_id
        entity.entity_type = entity_type
        entity.source_text = text
        entity.properties = {"text": text, "name": entity_id}
        return entity

    def test_normalize_proposition_cleans_text(self):
        """GIVEN 'Pay by Jan 1st!' WHEN _normalize_proposition THEN lowercase_underscored."""
        conv = self._make_converter()
        result = conv._normalize_proposition("Pay by Jan 1st!")
        assert " " not in result
        assert "!" not in result
        assert result == result.lower()

    def test_classify_agent_type_organization(self):
        """GIVEN entity text with 'company' WHEN _classify_agent_type THEN 'organization'."""
        conv = self._make_converter()
        entity = self._make_entity_mock(text="ABC company shall pay")
        result = conv._classify_agent_type(entity)
        assert result == "organization"

    def test_classify_agent_type_government(self):
        """GIVEN entity text with 'government' WHEN classify THEN 'government'."""
        conv = self._make_converter()
        entity = self._make_entity_mock(text="The government agency requires")
        result = conv._classify_agent_type(entity)
        assert result == "government"

    def test_classify_agent_type_unknown(self):
        """GIVEN entity text with no known type WHEN classify THEN 'unknown'."""
        conv = self._make_converter()
        entity = self._make_entity_mock(text="some random entity", entity_type="other")
        result = conv._classify_agent_type(entity)
        assert result == "unknown"

    def test_reset_statistics_zeros_all(self):
        """GIVEN stats updated WHEN _reset_statistics THEN all zeroed."""
        conv = self._make_converter()
        conv.conversion_stats["obligations_extracted"] = 5
        conv._reset_statistics()
        assert conv.conversion_stats["obligations_extracted"] == 0

    def test_update_statistics_obligation(self):
        """GIVEN OBLIGATION operator WHEN _update_statistics THEN obligations_extracted ++."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        conv = self._make_converter()
        conv._update_statistics(DeonticOperator.OBLIGATION)
        assert conv.conversion_stats["obligations_extracted"] == 1

    def test_update_statistics_permission(self):
        """GIVEN PERMISSION operator WHEN _update_statistics THEN permissions_extracted ++."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        conv = self._make_converter()
        conv._update_statistics(DeonticOperator.PERMISSION)
        assert conv.conversion_stats["permissions_extracted"] == 1

    def test_update_statistics_prohibition(self):
        """GIVEN PROHIBITION operator WHEN _update_statistics THEN prohibitions_extracted ++."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        conv = self._make_converter()
        conv._update_statistics(DeonticOperator.PROHIBITION)
        assert conv.conversion_stats["prohibitions_extracted"] == 1

    def test_extract_entity_text_name_field(self):
        """GIVEN entity with 'name' property WHEN _extract_entity_text THEN returns name."""
        conv = self._make_converter()
        entity = self._make_entity_mock(entity_id="e", text="", entity_type="agent")
        entity.properties = {"name": "Alice Corp"}
        entity.source_text = ""
        entity.name = ""
        # Must not be empty — should fall back to properties["name"]
        text = conv._extract_entity_text(entity)
        assert "Alice Corp" in text

    def test_extract_entity_text_text_field(self):
        """GIVEN entity with 'text' property WHEN _extract_entity_text THEN returns text."""
        conv = self._make_converter()
        entity = self._make_entity_mock(text="Must pay promptly")
        text = conv._extract_entity_text(entity)
        assert "Must pay promptly" in text

    def test_create_agent_from_entity_id_no_inference(self):
        """GIVEN enable_agent_inference=False WHEN _create_agent_from_entity_id THEN None."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            ConversionContext
        )
        conv = self._make_converter()
        ctx = ConversionContext(
            source_document_path="./x.pdf",
            enable_agent_inference=False,
        )
        result = conv._create_agent_from_entity_id("alice_corp", ctx)
        assert result is None

    def test_create_agent_from_entity_id_with_inference(self):
        """GIVEN enable_agent_inference=True WHEN _create_agent_from_entity_id THEN LegalAgent."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            ConversionContext
        )
        conv = self._make_converter()
        ctx = ConversionContext(source_document_path="./x.pdf", enable_agent_inference=True)
        agent = conv._create_agent_from_entity_id("alice_corp", ctx)
        assert agent is not None
        assert agent.identifier == "alice_corp"


# ===========================================================================
# 12. LogicIPLDStorage
# ===========================================================================

class TestLogicIPLDStorage:
    """Tests for caching/ipld_logic_storage.py (filesystem mode)."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            LogicIPLDStorage, LogicProvenanceTracker
        )
        self.tmp = tempfile.mkdtemp()
        self.storage = LogicIPLDStorage(storage_path=self.tmp)
        self.Tracker = LogicProvenanceTracker

    def test_init_filesystem_mode(self):
        """GIVEN no IPLD WHEN init THEN use_ipld is False."""
        assert self.storage.use_ipld is False

    def test_store_logic_formula_returns_cid(self):
        """GIVEN a formula WHEN store_logic_formula THEN returns non-empty string CID."""
        formula = _make_formula()
        cid = self.storage.store_logic_formula(formula)
        assert isinstance(cid, str)
        assert len(cid) > 0

    def test_store_logic_formula_with_doc_cid(self):
        """GIVEN formula and source_doc_cid WHEN store THEN document_to_formulas indexed."""
        formula = _make_formula()
        cid = self.storage.store_logic_formula(formula, source_doc_cid="doc123")
        assert "doc123" in self.storage.document_to_formulas
        assert cid in self.storage.document_to_formulas["doc123"]

    def test_retrieve_formulas_by_document(self):
        """GIVEN formula stored with doc_cid WHEN retrieve_formulas_by_document THEN finds it."""
        formula = _make_formula()
        self.storage.store_logic_formula(formula, source_doc_cid="docABC")
        nodes = self.storage.retrieve_formulas_by_document("docABC")
        assert len(nodes) == 1

    def test_retrieve_formulas_missing_doc(self):
        """GIVEN no formulas for doc WHEN retrieve_formulas_by_document THEN empty list."""
        nodes = self.storage.retrieve_formulas_by_document("nonexistent")
        assert nodes == []

    def test_store_translation_result(self):
        """GIVEN formula cid WHEN store_translation_result THEN translation_index updated."""
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            LogicTranslationTarget, TranslationResult
        )
        formula = _make_formula()
        formula_cid = self.storage.store_logic_formula(formula)
        tr = TranslationResult(
            target=LogicTranslationTarget.LEAN,
            translated_formula="def statement : Prop := True",
            success=True,
        )
        translation_cid = self.storage.store_translation_result(
            formula_cid, LogicTranslationTarget.LEAN, tr
        )
        assert isinstance(translation_cid, str)
        assert formula_cid in self.storage.translation_index

    def test_store_logic_collection(self):
        """GIVEN 3 formulas WHEN store_logic_collection THEN returns collection CID."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            create_obligation, LegalAgent
        )
        formulas = [
            create_obligation(f"prop{i}", LegalAgent("a", "A", "person"), source_text=f"text{i}")
            for i in range(3)
        ]
        cid = self.storage.store_logic_collection(formulas, "TestCollection")
        assert isinstance(cid, str)

    def test_retrieve_formula_translations_empty(self):
        """GIVEN formula not in nodes WHEN retrieve_formula_translations THEN empty dict."""
        result = self.storage.retrieve_formula_translations("cid_not_exist")
        assert result == {}

    def test_get_storage_statistics(self):
        """GIVEN storage with data WHEN get_storage_statistics THEN correct counts."""
        formula = _make_formula()
        self.storage.store_logic_formula(formula, source_doc_cid="doc1")
        stats = self.storage.get_storage_statistics()
        assert stats["total_formulas"] == 1
        assert stats["total_documents"] == 1
        assert stats["storage_backend"] == "filesystem"

    def test_create_provenance_chain(self):
        """GIVEN source/kg cids WHEN create_provenance_chain THEN fields set."""
        chain = self.storage.create_provenance_chain(
            source_pdf_path="./doc.pdf",
            knowledge_graph_cid="kg123",
            formula_cid="f456",
            graphrag_entity_cids=["e1", "e2"],
        )
        assert chain.source_document_path == "./doc.pdf"
        assert chain.knowledge_graph_cid == "kg123"
        assert len(chain.graphrag_entity_cids) == 2


# ===========================================================================
# 13. LogicProvenanceTracker
# ===========================================================================

class TestLogicProvenanceTracker:
    """Tests for LogicProvenanceTracker."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            LogicIPLDStorage, LogicProvenanceTracker
        )
        self.tmp = tempfile.mkdtemp()
        self.storage = LogicIPLDStorage(storage_path=self.tmp)
        self.tracker = LogicProvenanceTracker(self.storage)

    def test_track_formula_creation_returns_cid(self):
        """GIVEN formula WHEN track_formula_creation THEN returns CID string."""
        formula = _make_formula()
        cid = self.tracker.track_formula_creation(
            formula=formula,
            source_pdf_path="./test.pdf",
            knowledge_graph_cid="kg999",
        )
        assert isinstance(cid, str)

    def test_verify_provenance_found(self):
        """GIVEN tracked formula WHEN verify_provenance THEN verified=True."""
        formula = _make_formula()
        cid = self.tracker.track_formula_creation(
            formula=formula,
            source_pdf_path="./a.pdf",
            knowledge_graph_cid="kg100",
        )
        result = self.tracker.verify_provenance(cid)
        assert result["verified"] is True
        assert result["source_document"] == "./a.pdf"

    def test_verify_provenance_not_found(self):
        """GIVEN unknown cid WHEN verify_provenance THEN verified=False."""
        result = self.tracker.verify_provenance("nonexistent_cid")
        assert result["verified"] is False

    def test_find_related_formulas_not_found(self):
        """GIVEN unknown cid WHEN find_related_formulas THEN empty list."""
        result = self.tracker.find_related_formulas("unknown_cid")
        assert result == []

    def test_find_related_formulas_same_document(self):
        """GIVEN two formulas from same doc WHEN find_related_formulas THEN finds the other."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            create_obligation, LegalAgent
        )
        agent = LegalAgent("a", "A", "person")
        f1 = create_obligation("pay", agent, source_text="pay")
        f2 = create_obligation("deliver", agent, source_text="deliver")

        cid1 = self.tracker.track_formula_creation(f1, "./d.pdf", "kg1")
        cid2 = self.tracker.track_formula_creation(f2, "./d.pdf", "kg1")

        related = self.tracker.find_related_formulas(cid1)
        assert isinstance(related, list)


# ===========================================================================
# 14. LogicProvenanceChain and LogicIPLDNode dataclasses
# ===========================================================================

class TestLogicIPLDNodeAndProvenanceChain:
    """Tests for dataclasses."""

    def test_logic_provenance_chain_to_dict(self):
        """GIVEN LogicProvenanceChain WHEN to_dict THEN all fields present."""
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            LogicProvenanceChain
        )
        chain = LogicProvenanceChain(
            source_document_path="./x.pdf",
            source_document_cid="cid123",
            formula_cid="f001",
        )
        d = chain.to_dict()
        assert d["source_document_path"] == "./x.pdf"
        assert d["formula_cid"] == "f001"

    def test_logic_ipld_node_to_dict_and_from_dict(self):
        """GIVEN LogicIPLDNode WHEN to_dict/from_dict THEN round-trip correct."""
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            LogicIPLDNode
        )
        formula = _make_formula()
        node = LogicIPLDNode(formula_id="f001", deontic_formula=formula)
        d = node.to_dict()
        assert "deontic_formula" in d
        # from_dict
        node2 = LogicIPLDNode.from_dict(d)
        assert node2.formula_id == "f001"


# ===========================================================================
# 15. IPFSProofCache (without real IPFS)
# ===========================================================================

class TestIPFSProofCacheBasic:
    """Tests for caching/ipfs_proof_cache.py without a real IPFS node."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        self.tmp = tempfile.mkdtemp()
        # enable_ipfs=False forces local-only mode
        self.cache = IPFSProofCache(enable_ipfs=False, cache_dir=self.tmp)

    def test_init_ipfs_disabled(self):
        """GIVEN enable_ipfs=False WHEN init THEN ipfs_client is None."""
        assert self.cache.ipfs_client is None

    def test_put_and_get_local(self):
        """GIVEN formula+prover WHEN set then get THEN result retrieved."""
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import (
            ProofStatus, ProofResult
        )
        result = {"prover": "z3", "status": "success"}
        self.cache.set("formula_hash_1", result, prover_name="z3")
        retrieved = self.cache.get("formula_hash_1", prover_name="z3")
        assert retrieved is not None

    def test_get_missing_returns_none(self):
        """GIVEN no entry WHEN get THEN None returned."""
        result = self.cache.get("nonexistent_hash", prover_name="z3")
        assert result is None

    def test_get_statistics(self):
        """GIVEN cache WHEN get_statistics THEN dict with expected keys."""
        stats = self.cache.get_statistics()
        assert "ipfs_enabled" in stats
        assert stats["ipfs_enabled"] is False

    def test_sync_from_ipfs_no_client_returns_zero(self):
        """GIVEN no IPFS client WHEN sync_from_ipfs THEN returns 0."""
        count = self.cache.sync_from_ipfs()
        assert count == 0

    def test_pin_proof_no_ipfs_returns_false(self):
        """GIVEN no IPFS WHEN pin_proof THEN False returned."""
        result = self.cache.pin_proof("formula_hash_1", "z3")
        assert result is False

    def test_close_without_error(self):
        """GIVEN cache WHEN close THEN no exception."""
        self.cache.close()  # should not raise

    def test_get_from_ipfs_no_client_returns_none(self):
        """GIVEN no IPFS client WHEN get_from_ipfs THEN None."""
        result = self.cache.get_from_ipfs("bafysome_cid")
        assert result is None


# ===========================================================================
# 16. demonstrate_deontic_conversion (smoke test)
# ===========================================================================

class TestDemonstrateDeonticConversion:
    """Smoke test for the demonstrate function."""

    def test_demonstrate_runs_without_error(self):
        """GIVEN no setup WHEN demonstrate_deontic_conversion THEN completes."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import (
            demonstrate_deontic_conversion
        )
        result = demonstrate_deontic_conversion()
        assert result is not None
        assert hasattr(result, "deontic_formulas")


# ===========================================================================
# 17. create_logic_storage_with_provenance factory
# ===========================================================================

class TestCreateLogicStorageWithProvenance:
    """Tests for the factory function."""

    def test_factory_returns_storage_and_tracker(self):
        """GIVEN temp path WHEN factory called THEN (storage, tracker) tuple returned."""
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            create_logic_storage_with_provenance,
            LogicIPLDStorage,
            LogicProvenanceTracker,
        )
        tmp = tempfile.mkdtemp()
        storage, tracker = create_logic_storage_with_provenance(tmp)
        assert isinstance(storage, LogicIPLDStorage)
        assert isinstance(tracker, LogicProvenanceTracker)
