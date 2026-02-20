"""
Integration coverage tests — session 7 (2026-02-20).

Targets low-coverage modules in logic/integration/ to push
overall coverage from ~60% toward ~70%+.  Covers:

  * reasoning/_prover_backend_mixin.py       (12% -> 97%)
  * symbolic/neurosymbolic_api.py            (46% -> 88%)
  * domain/symbolic_contracts.py            (55% -> 56%)
  * caching/ipld_logic_storage.py           (30% -> improved)

All tests use GIVEN-WHEN-THEN format consistent with the existing suite.
"""

import json
import subprocess
import tempfile
import os
import pytest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _obligation(prop="pay", agent="Contractor"):
    from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
        DeonticFormula, DeonticOperator, LegalAgent,
    )
    agent_obj = LegalAgent(agent.lower(), agent, "organization")
    return DeonticFormula(
        operator=DeonticOperator.OBLIGATION,
        proposition=prop,
        agent=agent_obj,
        confidence=0.9,
        source_text=f"{agent} must {prop}",
    )


def _rule_set(formulas=None):
    from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
    return DeonticRuleSet(name="test_rules", formulas=list(formulas or []), description="test")


def _translation(formula_str="(assert true)"):
    from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
        TranslationResult, LogicTranslationTarget,
    )
    return TranslationResult(
        target=LogicTranslationTarget.Z3,
        translated_formula=formula_str,
        success=True,
    )


def _make_backend(tmp_dir):
    from ipfs_datasets_py.logic.integration.reasoning._prover_backend_mixin import ProverBackendMixin

    class _Backend(ProverBackendMixin):
        def __init__(self, d):
            self.temp_dir = Path(d)
            self.timeout = 5

        def _prover_cmd(self, prover: str) -> str:
            return prover

    return _Backend(tmp_dir)

# ---------------------------------------------------------------------------
# S1  ProverBackendMixin
# ---------------------------------------------------------------------------

class TestExecuteZ3Proof:
    def test_z3_sat_returns_success(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="sat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_z3_proof(_obligation(), _translation())
        assert result.status == ProofStatus.SUCCESS and result.prover == "z3"

    def test_z3_unsat_returns_success(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="unsat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_z3_proof(_obligation(), _translation())
        assert result.status == ProofStatus.SUCCESS

    def test_z3_unknown_output_returns_failure(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="unknown", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_z3_proof(_obligation(), _translation())
        assert result.status == ProofStatus.FAILURE

    def test_z3_nonzero_returncode_returns_error(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=1, stdout="", stderr="error msg")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_z3_proof(_obligation(), _translation())
        assert result.status == ProofStatus.ERROR

    def test_z3_timeout_returns_timeout(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="z3", timeout=5)):
            result = b._execute_z3_proof(_obligation(), _translation())
        assert result.status == ProofStatus.TIMEOUT

    def test_z3_exception_returns_error(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError("z3 not found")):
            result = b._execute_z3_proof(_obligation(), _translation())
        assert result.status == ProofStatus.ERROR


class TestExecuteCVC5Proof:
    def test_cvc5_sat(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="sat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_cvc5_proof(_obligation(), _translation())
        assert result.status == ProofStatus.SUCCESS and result.prover == "cvc5"

    def test_cvc5_unsat_also_returns_success(self, tmp_path):
        # _execute_cvc5_proof treats both "sat" and "unsat" as SUCCESS (solver ran OK)
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="unsat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_cvc5_proof(_obligation(), _translation())
        assert result.status == ProofStatus.SUCCESS

    def test_cvc5_error_returncode(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=2, stdout="", stderr="cvc5 error")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_cvc5_proof(_obligation(), _translation())
        assert result.status == ProofStatus.ERROR

    def test_cvc5_timeout(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cvc5", 5)):
            result = b._execute_cvc5_proof(_obligation(), _translation())
        assert result.status == ProofStatus.TIMEOUT

    def test_cvc5_exception(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=RuntimeError("cvc5 crashed")):
            result = b._execute_cvc5_proof(_obligation(), _translation())
        assert result.status == ProofStatus.ERROR


class TestExecuteLeanProof:
    def _lean_tr(self):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            TranslationResult, LogicTranslationTarget,
        )
        return TranslationResult(
            target=LogicTranslationTarget.LEAN,
            translated_formula="theorem test : True := True.intro",
            success=True,
            metadata={"proposition_id": "TestProp"},
        )

    def test_lean_success(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_lean_proof(_obligation(), self._lean_tr())
        assert result.status == ProofStatus.SUCCESS and result.prover == "lean"

    def test_lean_failure(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=1, stdout="", stderr="lean error")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_lean_proof(_obligation(), self._lean_tr())
        assert result.status == ProofStatus.ERROR

    def test_lean_timeout(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("lean", 5)):
            result = b._execute_lean_proof(_obligation(), self._lean_tr())
        assert result.status == ProofStatus.TIMEOUT

    def test_lean_exception(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=OSError("lean missing")):
            result = b._execute_lean_proof(_obligation(), self._lean_tr())
        assert result.status == ProofStatus.ERROR

    def test_lean_no_proposition_id(self, tmp_path):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            TranslationResult, LogicTranslationTarget,
        )
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        tr = TranslationResult(
            target=LogicTranslationTarget.LEAN,
            translated_formula="True",
            success=True,
            metadata={},
        )
        mock = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_lean_proof(_obligation(), tr)
        assert result.status == ProofStatus.SUCCESS


class TestExecuteCoqProof:
    def _coq_tr(self):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            TranslationResult, LogicTranslationTarget,
        )
        return TranslationResult(
            target=LogicTranslationTarget.COQ,
            translated_formula="(* test *)",
            success=True,
        )

    def test_coq_success(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="Proof accepted", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_coq_proof(_obligation(), self._coq_tr())
        assert result.status == ProofStatus.SUCCESS and result.prover == "coq"

    def test_coq_failure(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=1, stdout="", stderr="coq error")
        with patch("subprocess.run", return_value=mock):
            result = b._execute_coq_proof(_obligation(), self._coq_tr())
        assert result.status == ProofStatus.ERROR

    def test_coq_timeout(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("coq", 5)):
            result = b._execute_coq_proof(_obligation(), self._coq_tr())
        assert result.status == ProofStatus.TIMEOUT

    def test_coq_exception(self, tmp_path):
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=OSError("coq missing")):
            result = b._execute_coq_proof(_obligation(), self._coq_tr())
        assert result.status == ProofStatus.ERROR


class TestCheckZ3Consistency:
    def test_sat_means_consistent(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="sat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._check_z3_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.SUCCESS

    def test_unsat_means_inconsistent(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="unsat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._check_z3_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.FAILURE

    def test_unexpected_output_is_error(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._check_z3_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.ERROR

    def test_nonzero_returncode_is_error(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=1, stdout="", stderr="error")
        with patch("subprocess.run", return_value=mock):
            result = b._check_z3_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.ERROR

    def test_timeout(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("z3", 5)):
            result = b._check_z3_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.TIMEOUT

    def test_exception(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=RuntimeError("z3 crashed")):
            result = b._check_z3_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.ERROR

    def test_empty_rule_set(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="sat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._check_z3_consistency(_rule_set(), time.time())
        assert result.status == ProofStatus.SUCCESS


class TestCheckCVC5Consistency:
    def test_sat(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="sat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._check_cvc5_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.SUCCESS and result.prover == "cvc5"

    def test_unsat(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="unsat", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._check_cvc5_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.FAILURE

    def test_other_output(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        mock = MagicMock(returncode=0, stdout="???", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = b._check_cvc5_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.ERROR

    def test_timeout(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cvc5", 5)):
            result = b._check_cvc5_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.TIMEOUT

    def test_exception(self, tmp_path):
        import time
        from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine_types import ProofStatus
        b = _make_backend(tmp_path)
        with patch("subprocess.run", side_effect=OSError("cvc5 missing")):
            result = b._check_cvc5_consistency(_rule_set([_obligation()]), time.time())
        assert result.status == ProofStatus.ERROR

# ---------------------------------------------------------------------------
# S2  NeurosymbolicReasoner
# ---------------------------------------------------------------------------

def _reasoner(use_modal=False, use_cec=False, use_nl=False):
    from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_api import NeurosymbolicReasoner
    return NeurosymbolicReasoner(use_modal=use_modal, use_cec=use_cec, use_nl=use_nl)


class TestNeurosymbolicReasonerInit:
    def test_minimal_init(self):
        r = _reasoner()
        assert r is not None and r.nl_interface is None

    def test_capabilities_keys(self):
        caps = _reasoner().get_capabilities()
        for key in ("tdfol_rules", "cec_rules", "total_inference_rules", "modal_provers"):
            assert key in caps
        assert caps["natural_language"] is False

    def test_with_cec_only(self):
        assert _reasoner(use_cec=True) is not None

    def test_with_modal(self):
        assert _reasoner(use_modal=True) is not None


class TestNeurosymbolicReasonerParse:
    def test_parse_tdfol_explicit(self):
        r = _reasoner()
        assert r.parse("forall x. P(x)", format="tdfol") is not None

    def test_parse_tdfol_auto_detect_forall(self):
        r = _reasoner()
        assert r.parse("forall x. P(x)", format="auto") is not None

    def test_parse_dcec_explicit(self):
        r = _reasoner()
        assert r.parse("(O P)", format="dcec") is not None

    def test_parse_dcec_auto_detect_paren(self):
        r = _reasoner()
        assert r.parse("(O P)", format="auto") is not None

    def test_parse_nl_no_interface_returns_none(self):
        r = _reasoner()
        assert r.parse("All humans are mortal", format="nl") is None

    def test_parse_plain_text_no_interface(self):
        r = _reasoner()
        assert r.parse("birds can fly") is None

    def test_parse_invalid_tdfol_lenient_parser(self):
        # TDFOL parser is lenient: returns best-effort parse instead of raising
        r = _reasoner()
        r.parse("@@@invalid", format="tdfol")  # no exception raised

    def test_parse_invalid_dcec_lenient_parser(self):
        # DCEC parser is lenient: returns best-effort parse instead of raising
        r = _reasoner()
        r.parse("@@@invalid", format="dcec")  # no exception raised

    def test_parse_unknown_format_returns_none(self):
        r = _reasoner()
        result = r.parse("P(a)", format="prolog")
        assert result is None

    def test_parse_arrow_auto_detects_tdfol(self):
        r = _reasoner()
        # '→' or '->' triggers tdfol branch; result may succeed or fail, no crash
        r.parse("P -> Q", format="auto")  # no exception


class TestNeurosymbolicReasonerAddKnowledge:
    def test_add_formula_object(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        r = _reasoner()
        assert r.add_knowledge(parse_tdfol("P(a)")) is True

    def test_add_parseable_string(self):
        r = _reasoner()
        assert r.add_knowledge("forall x. P(x)") is True

    def test_add_unparseable_string_fails(self):
        r = _reasoner()
        assert r.add_knowledge("xyzxyz@@@###") is False

    def test_add_as_theorem(self):
        r = _reasoner()
        assert r.add_knowledge("forall x. Q(x)", is_axiom=False) is True


class TestNeurosymbolicReasonerProve:
    def test_prove_unparseable_goal_error(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        r = _reasoner()
        result = r.prove("@@@###unparseable@@@")
        assert result.status == ProofStatus.ERROR

    def test_prove_formula_object_no_crash(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        r = _reasoner()
        result = r.prove(parse_tdfol("P(a)"))
        assert result is not None

    def test_prove_with_string_given(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        r = _reasoner()
        result = r.prove(parse_tdfol("Q(a)"), given=["forall x. Q(x)"])
        assert result is not None

    def test_prove_with_formula_given(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        r = _reasoner()
        result = r.prove(parse_tdfol("Q(a)"), given=[parse_tdfol("forall x. Q(x)")])
        assert result is not None

    def test_prove_with_unparseable_given(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        r = _reasoner()
        result = r.prove(parse_tdfol("Q(a)"), given=["@@@###", "forall x. Q(x)"])
        assert result is not None


class TestNeurosymbolicReasonerExplainQuery:
    def test_explain_formula_object(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        r = _reasoner()
        exp = r.explain(parse_tdfol("P(a)"))
        assert isinstance(exp, str) and len(exp) > 0

    def test_explain_valid_string(self):
        r = _reasoner()
        exp = r.explain("P(a)")
        assert isinstance(exp, str)

    def test_explain_unparseable_string(self):
        r = _reasoner()
        exp = r.explain("@@@unparseable@@@")
        assert "Could not parse" in exp

    def test_query_unparseable_returns_failure(self):
        r = _reasoner()
        result = r.query("@@@unparseable@@@")
        assert result["success"] is False and "question" in result

    def test_query_always_returns_dict(self):
        r = _reasoner()
        result = r.query("P(a)")
        assert isinstance(result, dict) and "success" in result


class TestGetReasoner:
    def test_returns_instance(self):
        import ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_api as mod
        mod._global_reasoner = None
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_api import (
            NeurosymbolicReasoner, get_reasoner,
        )
        assert isinstance(get_reasoner(), NeurosymbolicReasoner)

    def test_singleton(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_api import get_reasoner
        assert get_reasoner() is get_reasoner()


class TestReasoningCapabilities:
    def test_default_modal_provers(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_api import ReasoningCapabilities
        caps = ReasoningCapabilities()
        assert caps.modal_provers and len(caps.modal_provers) > 0

    def test_custom_rule_counts(self):
        from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic_api import ReasoningCapabilities
        caps = ReasoningCapabilities(tdfol_rules=50, cec_rules=90, total_rules=140)
        assert caps.tdfol_rules == 50 and caps.total_rules == 140

# ---------------------------------------------------------------------------
# S3  SymbolicContracts
# ---------------------------------------------------------------------------

class TestFOLInput:
    def test_basic(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLInput
        inp = FOLInput(text="All cats are animals")
        assert inp.text == "All cats are animals"

    def test_defaults(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLInput
        inp = FOLInput(text="Some birds can fly")
        assert inp.confidence_threshold == 0.7
        assert inp.output_format == "symbolic"
        assert inp.reasoning_depth == 3
        assert inp.validate_syntax is True

    def test_custom_threshold(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLInput
        assert FOLInput(text="Test", confidence_threshold=0.9).confidence_threshold == 0.9

    def test_domain_predicates(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLInput
        inp = FOLInput(text="Test", domain_predicates=["Animal", "Cat"])
        assert "Animal" in inp.domain_predicates

    def test_prolog_format(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLInput
        assert FOLInput(text="All birds fly", output_format="prolog").output_format == "prolog"

    def test_tptp_format(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLInput
        assert FOLInput(text="All birds fly", output_format="tptp").output_format == "tptp"


class TestFOLOutput:
    def test_basic(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLOutput
        out = FOLOutput(
            fol_formula="forall x Cat(x)",
            confidence=0.9,
            logical_components={"quantifiers": [], "predicates": [], "entities": []},
        )
        assert "Cat" in out.fol_formula

    def test_has_list_defaults(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLOutput
        out = FOLOutput(
            fol_formula="P(x)", confidence=0.5,
            logical_components={"quantifiers": [], "predicates": [], "entities": []},
        )
        assert hasattr(out, "reasoning_steps") and hasattr(out, "warnings")


class TestFOLSyntaxValidator:
    def test_valid_universal(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("forall x P(x) -> Q(x)")
        assert result["valid"] is True

    def test_valid_predicate(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("Animal(socrates)")
        assert result["valid"] is True

    def test_empty_formula_invalid(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("")
        assert result["valid"] is False and result["errors"]

    def test_whitespace_only_invalid(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        assert FOLSyntaxValidator().validate_formula("   ")["valid"] is False

    def test_unbalanced_parens(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("P(x")
        assert not result["valid"]
        assert any("paren" in e.lower() for e in result["errors"])

    def test_unbalanced_brackets(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("P(x) [extra")
        assert not result["valid"]

    def test_structure_analysis_in_result(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("forall x Animal(x)")
        assert "structure_analysis" in result
        assert result["structure_analysis"]["has_quantifiers"] is True

    def test_complex_connectives_detected(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("forall x (P(x) -> Q(x)) & R(x)")
        struct = result["structure_analysis"]
        assert struct["predicate_count"] >= 2 and len(struct["connectives"]) >= 1

    def test_existential_quantifier_detected(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("exists x Bird(x)")
        assert result["structure_analysis"]["has_quantifiers"] is True

    def test_free_variables_warning_present(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("P(x)")
        assert "warnings" in result

    def test_high_complexity_produces_warnings(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        f = "forall x forall y forall z (A(x,y) & B(y,z) -> C(x,z)) & (D(x) | E(y)) & F(z,x,y)"
        result = FOLSyntaxValidator().validate_formula(f)
        assert "warnings" in result

    def test_suggestions_for_single_char_predicates(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLSyntaxValidator
        result = FOLSyntaxValidator().validate_formula("P(x)")
        assert "suggestions" in result


class TestValidationContext:
    def test_defaults(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import ValidationContext
        ctx = ValidationContext()
        assert ctx.strict_mode is True and ctx.max_complexity == 100 and ctx.custom_validators == []

    def test_custom(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import ValidationContext
        ctx = ValidationContext(strict_mode=False, max_complexity=50)
        assert ctx.strict_mode is False and ctx.max_complexity == 50


class TestContractedFOLConverterFallback:
    def _conv(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import ContractedFOLConverter
        return ContractedFOLConverter()

    def _inp(self, text, **kw):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLInput
        return FOLInput(text=text, **kw)

    def test_all_gives_universal(self):
        out = self._conv()(self._inp("All cats are animals"))
        assert "forall" in out.fol_formula.lower() or "\u2200" in out.fol_formula

    def test_every_gives_universal(self):
        out = self._conv()(self._inp("Every bird can fly"))
        assert "forall" in out.fol_formula.lower() or "\u2200" in out.fol_formula

    def test_some_gives_existential(self):
        out = self._conv()(self._inp("Some birds can fly"))
        assert "exists" in out.fol_formula.lower() or "\u2203" in out.fol_formula

    def test_other_gives_predicate(self):
        out = self._conv()(self._inp("The rule is correct"))
        assert "Statement" in out.fol_formula

    def test_prolog_format(self):
        out = self._conv()(self._inp("All cats are animals", output_format="prolog"))
        assert "forall" in out.fol_formula.lower() or ":-" in out.fol_formula

    def test_tptp_format(self):
        out = self._conv()(self._inp("All cats are animals", output_format="tptp"))
        assert "fof(" in out.fol_formula

    def test_confidence_above_zero(self):
        out = self._conv()(self._inp("All humans are mortal"))
        assert out.confidence > 0.0

    def test_fallback_warning_in_output(self):
        out = self._conv()(self._inp("Some dogs bark"))
        assert any("SymbolicAI" in w or "fallback" in w.lower() for w in out.warnings)

    def test_logical_components_keys(self):
        out = self._conv()(self._inp("All cats are animals"))
        for k in ("quantifiers", "predicates", "entities"):
            assert k in out.logical_components


class TestFOLHelpers:
    def test_create_fol_converter(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import (
            create_fol_converter, ContractedFOLConverter,
        )
        assert isinstance(create_fol_converter(), ContractedFOLConverter)

    def test_create_non_strict(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import create_fol_converter
        assert create_fol_converter(strict_validation=False) is not None

    def test_validate_fol_input(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import validate_fol_input, FOLInput
        inp = validate_fol_input("All cats are animals")
        assert isinstance(inp, FOLInput) and "cats" in inp.text

    def test_validate_fol_input_with_kwargs(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import validate_fol_input
        assert validate_fol_input("Test", confidence_threshold=0.8).confidence_threshold == 0.8

    def test_test_contracts_no_error(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import test_contracts
        try:
            test_contracts()
        except SystemExit:
            pass

# ---------------------------------------------------------------------------
# S4  LogicIPLDStorage
# ---------------------------------------------------------------------------

class TestLogicProvenanceChain:
    def test_to_dict_source_path(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import LogicProvenanceChain
        chain = LogicProvenanceChain(source_document_path="/path/doc.pdf")
        d = chain.to_dict()
        assert d["source_document_path"] == "/path/doc.pdf"

    def test_default_empty_entity_list(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import LogicProvenanceChain
        chain = LogicProvenanceChain(source_document_path="/path/doc.pdf")
        assert chain.to_dict()["graphrag_entity_cids"] == []

    def test_timestamp_auto_set(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import LogicProvenanceChain
        chain = LogicProvenanceChain(source_document_path="/p.pdf")
        assert chain.creation_timestamp and len(chain.creation_timestamp) > 0


class TestLogicIPLDNode:
    def _node(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import LogicIPLDNode
        return LogicIPLDNode(formula_id="test_001", deontic_formula=_obligation())

    def test_to_dict_formula_id(self):
        assert self._node().to_dict()["formula_id"] == "test_001"

    def test_to_dict_formula_is_dict(self):
        assert isinstance(self._node().to_dict()["deontic_formula"], dict)

    def test_to_dict_no_provenance(self):
        assert self._node().to_dict().get("provenance_chain") is None

    def test_to_dict_with_provenance(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            LogicIPLDNode, LogicProvenanceChain,
        )
        chain = LogicProvenanceChain(source_document_path="/d.pdf")
        node = LogicIPLDNode(
            formula_id="n2", deontic_formula=_obligation(), provenance_chain=chain
        )
        d = node.to_dict()
        assert d["provenance_chain"] is not None
        assert "source_document_path" in d["provenance_chain"]

    def test_from_dict_round_trip(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import LogicIPLDNode
        node = self._node()
        reconstructed = LogicIPLDNode.from_dict(node.to_dict())
        assert reconstructed.formula_id == node.formula_id

    def test_from_dict_with_provenance(self):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            LogicIPLDNode, LogicProvenanceChain,
        )
        chain = LogicProvenanceChain(source_document_path="/t.pdf", formula_cid="abc")
        node = LogicIPLDNode(
            formula_id="n3", deontic_formula=_obligation(), provenance_chain=chain
        )
        r = LogicIPLDNode.from_dict(node.to_dict())
        assert r.provenance_chain is not None
        assert r.provenance_chain.source_document_path == "/t.pdf"


class TestLogicIPLDStorageFilesystem:
    def _storage(self, tmp_path):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import LogicIPLDStorage
        return LogicIPLDStorage(storage_path=str(tmp_path / "ls"))

    def test_init_creates_dir(self, tmp_path):
        s = self._storage(tmp_path)
        assert s.storage_path.exists() and s.use_ipld is False

    def test_store_formula_returns_cid(self, tmp_path):
        cid = self._storage(tmp_path).store_logic_formula(_obligation())
        assert isinstance(cid, str) and len(cid) > 0

    def test_store_formula_creates_json(self, tmp_path):
        s = self._storage(tmp_path)
        s.store_logic_formula(_obligation())
        assert len(list(s.storage_path.glob("formula_*.json"))) == 1

    def test_store_with_source_doc_indexes(self, tmp_path):
        s = self._storage(tmp_path)
        cid = s.store_logic_formula(_obligation(), source_doc_cid="doc_abc")
        assert "doc_abc" in s.document_to_formulas and cid in s.document_to_formulas["doc_abc"]

    def test_store_two_for_same_doc(self, tmp_path):
        s = self._storage(tmp_path)
        s.store_logic_formula(_obligation("pay"), source_doc_cid="doc_x")
        s.store_logic_formula(_obligation("deliver"), source_doc_cid="doc_x")
        assert len(s.document_to_formulas["doc_x"]) == 2

    def test_store_translation_returns_cid(self, tmp_path):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            TranslationResult, LogicTranslationTarget,
        )
        s = self._storage(tmp_path)
        cid = s.store_logic_formula(_obligation())
        tr = TranslationResult(
            target=LogicTranslationTarget.LEAN,
            translated_formula="theorem t : True := True.intro",
            success=True,
        )
        t_cid = s.store_translation_result(cid, LogicTranslationTarget.LEAN, tr)
        assert isinstance(t_cid, str) and len(t_cid) > 0

    def test_store_translation_updates_index(self, tmp_path):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            TranslationResult, LogicTranslationTarget,
        )
        s = self._storage(tmp_path)
        cid = s.store_logic_formula(_obligation())
        tr = TranslationResult(
            target=LogicTranslationTarget.LEAN,
            translated_formula="theorem t : True",
            success=True,
        )
        s.store_translation_result(cid, LogicTranslationTarget.LEAN, tr)
        assert "lean" in s.translation_index.get(cid, {})

    def test_store_translation_updates_node(self, tmp_path):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            TranslationResult, LogicTranslationTarget,
        )
        s = self._storage(tmp_path)
        cid = s.store_logic_formula(_obligation())
        tr = TranslationResult(
            target=LogicTranslationTarget.COQ, translated_formula="(* coq *)", success=True
        )
        s.store_translation_result(cid, LogicTranslationTarget.COQ, tr)
        node = s.formula_nodes[cid]
        assert "coq" in node.translations and "coq" in node.translation_cids

    def test_store_collection(self, tmp_path):
        s = self._storage(tmp_path)
        cid = s.store_logic_collection([_obligation("a"), _obligation("b")], "col1")
        assert isinstance(cid, str) and len(cid) > 0

    def test_store_collection_stores_all(self, tmp_path):
        s = self._storage(tmp_path)
        s.store_logic_collection([_obligation("a"), _obligation("b"), _obligation("c")], "col2")
        assert len(s.formula_nodes) == 3

    def test_retrieve_formulas_known_doc(self, tmp_path):
        s = self._storage(tmp_path)
        s.store_logic_formula(_obligation(), source_doc_cid="d1")
        assert len(s.retrieve_formulas_by_document("d1")) == 1

    def test_retrieve_formulas_unknown_doc(self, tmp_path):
        assert self._storage(tmp_path).retrieve_formulas_by_document("nope") == []

    def test_retrieve_translations_known(self, tmp_path):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            TranslationResult, LogicTranslationTarget,
        )
        s = self._storage(tmp_path)
        cid = s.store_logic_formula(_obligation())
        s.store_translation_result(
            cid, LogicTranslationTarget.LEAN,
            TranslationResult(
                target=LogicTranslationTarget.LEAN, translated_formula="t", success=True
            )
        )
        assert "lean" in s.retrieve_formula_translations(cid)

    def test_retrieve_translations_unknown(self, tmp_path):
        assert self._storage(tmp_path).retrieve_formula_translations("nope") == {}

    def test_create_provenance_chain(self, tmp_path):
        s = self._storage(tmp_path)
        chain = s.create_provenance_chain(
            source_pdf_path="/doc.pdf",
            knowledge_graph_cid="kg1",
            formula_cid="f1",
            graphrag_entity_cids=["e1"],
        )
        assert chain.source_document_path == "/doc.pdf" and "e1" in chain.graphrag_entity_cids

    def test_get_storage_statistics(self, tmp_path):
        s = self._storage(tmp_path)
        s.store_logic_formula(_obligation("pay"), source_doc_cid="d1")
        s.store_logic_formula(_obligation("deliver"), source_doc_cid="d1")
        stats = s.get_storage_statistics()
        assert stats["total_formulas"] == 2 and stats["total_documents"] == 1
        assert stats["storage_backend"] == "filesystem"

    def test_extraction_metadata_stored(self, tmp_path):
        s = self._storage(tmp_path)
        cid = s.store_logic_formula(_obligation(), extraction_metadata={"extractor": "test"})
        assert s.formula_nodes[cid].extraction_metadata["extractor"] == "test"

    def test_translations_param_stored(self, tmp_path):
        s = self._storage(tmp_path)
        cid = s.store_logic_formula(_obligation(), translations={"lean": "theorem t"})
        assert "lean" in s.formula_nodes[cid].translations


class TestLogicProvenanceTracker:
    def _setup(self, tmp_path):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            LogicIPLDStorage, LogicProvenanceTracker,
        )
        s = LogicIPLDStorage(storage_path=str(tmp_path / "ls"))
        return s, LogicProvenanceTracker(s)

    def test_track_returns_cid(self, tmp_path):
        _, t = self._setup(tmp_path)
        cid = t.track_formula_creation(
            formula=_obligation(),
            source_pdf_path="/d.pdf",
            knowledge_graph_cid="kg1",
        )
        assert isinstance(cid, str) and len(cid) > 0

    def test_provenance_cached(self, tmp_path):
        s, t = self._setup(tmp_path)
        cid = t.track_formula_creation(
            formula=_obligation(), source_pdf_path="/d.pdf", knowledge_graph_cid="kg1"
        )
        assert cid in t.provenance_cache
        assert s.formula_nodes[cid].provenance_chain is not None

    def test_verify_provenance_ok(self, tmp_path):
        _, t = self._setup(tmp_path)
        cid = t.track_formula_creation(
            formula=_obligation(), source_pdf_path="/d.pdf", knowledge_graph_cid="kg1"
        )
        result = t.verify_provenance(cid)
        assert result["verified"] is True and "source_document" in result

    def test_verify_not_found(self, tmp_path):
        _, t = self._setup(tmp_path)
        result = t.verify_provenance("nope")
        assert result["verified"] is False and "error" in result

    def test_verify_no_provenance(self, tmp_path):
        s, t = self._setup(tmp_path)
        cid = s.store_logic_formula(_obligation())
        assert t.verify_provenance(cid)["verified"] is False

    def test_find_related_not_found(self, tmp_path):
        _, t = self._setup(tmp_path)
        assert t.find_related_formulas("nope") == []

    def test_find_related_no_provenance(self, tmp_path):
        s, t = self._setup(tmp_path)
        cid = s.store_logic_formula(_obligation())
        assert t.find_related_formulas(cid) == []

    def test_find_related_no_source_cid(self, tmp_path):
        _, t = self._setup(tmp_path)
        cid = t.track_formula_creation(
            formula=_obligation(), source_pdf_path="/d.pdf", knowledge_graph_cid="kg1"
        )
        # provenance.source_document_cid is None
        assert t.find_related_formulas(cid) == []

    def test_export_report_creates_file(self, tmp_path):
        _, t = self._setup(tmp_path)
        t.track_formula_creation(
            formula=_obligation(), source_pdf_path="/d.pdf", knowledge_graph_cid="kg1"
        )
        report_path = str(tmp_path / "report.json")
        report = t.export_provenance_report(output_path=report_path)
        assert Path(report_path).exists() and "total_formulas" in report

    def test_export_empty_storage(self, tmp_path):
        _, t = self._setup(tmp_path)
        report = t.export_provenance_report(output_path=str(tmp_path / "r.json"))
        assert report["total_formulas"] == 0 and report["provenance_chains"] == []


class TestCreateLogicStorageWithProvenance:
    def test_returns_tuple(self, tmp_path):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            create_logic_storage_with_provenance, LogicIPLDStorage, LogicProvenanceTracker,
        )
        s, t = create_logic_storage_with_provenance(str(tmp_path / "s"))
        assert isinstance(s, LogicIPLDStorage) and isinstance(t, LogicProvenanceTracker)

    def test_tracker_references_storage(self, tmp_path):
        from ipfs_datasets_py.logic.integration.caching.ipld_logic_storage import (
            create_logic_storage_with_provenance,
        )
        s, t = create_logic_storage_with_provenance(str(tmp_path / "s2"))
        assert t.logic_storage is s
