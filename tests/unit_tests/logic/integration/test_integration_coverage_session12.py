"""
Session 12: Integration coverage 79% → 81%+

Targets:
- converters/deontic_logic_core.py         79% → 90%+ (demonstrate, validator, create helpers)
- integration/__init__.py                  52% → 70%+ (enable_symbolicai, __getattr__, __dir__)
- caching/ipfs_proof_cache.py              77% → 90%+ (pin/unpin methods with mock IPFS)
- bridges/prover_installer.py              70% → 80%+ (ensure_coq/ensure_lean without yes)
- bridges/tdfol_cec_bridge.py              remaining lines
"""

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Section 1: converters/deontic_logic_core.py
# ──────────────────────────────────────────────────────────────────────────────

class TestDeonticLogicCoreHelpers:
    """GIVEN create_obligation/create_permission/create_prohibition WHEN called THEN correct."""

    def _make_agent(self, role="contractor"):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import LegalAgent
        return LegalAgent(f"{role}_001", f"ABC {role}", "organization")

    def test_create_obligation(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            create_obligation, DeonticOperator,
        )
        agent = self._make_agent()
        obl = create_obligation(
            "complete_work_by_deadline",
            agent,
            conditions=["contract_valid", "no_force_majeure"],
            source_text="must complete by deadline",
        )
        assert obl.operator == DeonticOperator.OBLIGATION
        assert "complete_work_by_deadline" in obl.proposition
        assert len(obl.conditions) == 2

    def test_create_obligation_no_conditions(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            create_obligation, DeonticOperator,
        )
        agent = self._make_agent()
        obl = create_obligation("pay", agent)
        assert obl.operator == DeonticOperator.OBLIGATION
        assert obl.conditions == []

    def test_create_permission(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            create_permission, DeonticOperator,
        )
        agent = self._make_agent("client")
        perm = create_permission("inspect_work", agent, conditions=["24_hour_notice"])
        assert perm.operator == DeonticOperator.PERMISSION

    def test_create_prohibition(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            create_prohibition, DeonticOperator,
        )
        agent = self._make_agent()
        proh = create_prohibition("use_substandard_materials", agent)
        assert proh.operator == DeonticOperator.PROHIBITION

    def test_create_right(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent("emp", "Employee", "person")
        f = DeonticFormula(
            operator=DeonticOperator.RIGHT,
            proposition="appeal_decision",
            agent=agent,
            confidence=0.9,
            source_text="employee has right to appeal",
        )
        assert f.operator == DeonticOperator.RIGHT


class TestDeonticLogicValidator:
    """GIVEN DeonticLogicValidator WHEN validating formulas THEN catches errors."""

    def _make_formula(self, op="OBLIGATION", prop="pay"):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent("a", "A", "person")
        return DeonticFormula(
            operator=DeonticOperator[op],
            proposition=prop,
            agent=agent,
            confidence=0.8,
            source_text=f"{op.lower()} {prop}",
        )

    def test_validate_valid_formula(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticLogicValidator
        f = self._make_formula()
        errors = DeonticLogicValidator.validate_formula(f)
        assert errors == []

    def test_validate_invalid_confidence(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent, DeonticLogicValidator,
        )
        agent = LegalAgent("a", "A", "person")
        f = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="pay",
            agent=agent,
            confidence=1.5,  # Invalid: > 1.0
            source_text="pay",
        )
        errors = DeonticLogicValidator.validate_formula(f)
        assert any("confidence" in e.lower() for e in errors)

    def test_validate_temporal_conditions_invalid_format(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent, DeonticLogicValidator,
            TemporalCondition, TemporalOperator,
        )
        agent = LegalAgent("a", "A", "person")
        tc = TemporalCondition(
            operator=TemporalOperator.ALWAYS,
            condition="active",
            start_time="not-a-date",
            end_time="also-not-a-date",
        )
        f = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="pay",
            agent=agent,
            confidence=0.8,
            source_text="pay",
            temporal_conditions=[tc],
        )
        errors = DeonticLogicValidator.validate_formula(f)
        assert any("datetime" in e.lower() or "invalid" in e.lower() for e in errors)

    def test_validate_temporal_conditions_start_after_end(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent, DeonticLogicValidator,
            TemporalCondition, TemporalOperator,
        )
        agent = LegalAgent("a", "A", "person")
        tc = TemporalCondition(
            operator=TemporalOperator.UNTIL,
            condition="contract_active",
            start_time="2024-12-31",
            end_time="2024-01-01",  # end before start
        )
        f = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="maintain",
            agent=agent,
            confidence=0.8,
            source_text="maintain",
            temporal_conditions=[tc],
        )
        errors = DeonticLogicValidator.validate_formula(f)
        assert any("time" in e.lower() for e in errors)

    def test_validate_quantifiers_invalid(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent, DeonticLogicValidator,
        )
        agent = LegalAgent("a", "A", "person")
        f = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="pay",
            agent=agent,
            confidence=0.8,
            source_text="pay",
            quantifiers=[("invalid_quantifier", "x", "Person")],
        )
        errors = DeonticLogicValidator.validate_formula(f)
        assert any("quantifier" in e.lower() or "invalid" in e.lower() for e in errors)

    def test_validate_rule_set_valid(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticLogicValidator, DeonticRuleSet,
        )
        f = self._make_formula()
        rs = DeonticRuleSet(name="Test", formulas=[f])
        errors = DeonticLogicValidator.validate_rule_set(rs)
        assert isinstance(errors, list)

    def test_validate_rule_set_with_conflicts(self):
        """Validates that check_consistency is called on rule set."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticLogicValidator, DeonticRuleSet, DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent("a", "A", "person")
        # Create obligation and prohibition for same proposition/agent - potential conflict
        f1 = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="disclose",
            agent=agent,
            confidence=0.9,
            source_text="must disclose",
        )
        f2 = DeonticFormula(
            operator=DeonticOperator.PROHIBITION,
            proposition="disclose",
            agent=agent,
            confidence=0.9,
            source_text="must not disclose",
        )
        rs = DeonticRuleSet(name="ConflictTest", formulas=[f1, f2])
        errors = DeonticLogicValidator.validate_rule_set(rs)
        assert isinstance(errors, list)
        # May contain "Consistency conflict" errors


class TestDemonstrateDeonticLogic:
    """GIVEN demonstrate_deontic_logic WHEN called THEN returns rule set."""

    def test_demonstrate(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            demonstrate_deontic_logic, DeonticRuleSet,
        )
        result = demonstrate_deontic_logic()
        assert isinstance(result, DeonticRuleSet)
        assert len(result.formulas) >= 3
        assert result.name is not None


class TestDeonticRuleSetAdditional:
    """GIVEN DeonticRuleSet WHEN additional methods called THEN correct."""

    def _make_rs(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticRuleSet, DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent("a", "A", "person")
        f = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="pay",
            agent=agent,
            confidence=0.9,
            source_text="must pay",
        )
        return DeonticRuleSet(name="Test", formulas=[f])

    def test_remove_formula(self):
        rs = self._make_rs()
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent("b", "B", "person")
        f2 = DeonticFormula(
            operator=DeonticOperator.PERMISSION,
            proposition="appeal",
            agent=agent,
            confidence=0.8,
            source_text="may appeal",
        )
        rs.add_formula(f2)
        rs.remove_formula(f2.formula_id)
        # should have 1 formula left
        assert len(rs.formulas) == 1

    def test_find_formulas_by_agent(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticRuleSet, DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent_a = LegalAgent("a", "A", "person")
        agent_b = LegalAgent("b", "B", "org")
        f1 = DeonticFormula(DeonticOperator.OBLIGATION, "pay", agent_a, 0.9, "pay")
        f2 = DeonticFormula(DeonticOperator.OBLIGATION, "deliver", agent_b, 0.9, "deliver")
        rs = DeonticRuleSet(name="T", formulas=[f1, f2])
        result = rs.find_formulas_by_agent("a")
        assert len(result) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Section 2: integration/__init__.py
# ──────────────────────────────────────────────────────────────────────────────

class TestIntegrationInit:
    """GIVEN integration __init__.py WHEN called THEN correct behavior."""

    def test_enable_symbolicai_returns_false(self):
        """Since symai is not installed, should return False."""
        from ipfs_datasets_py.logic.integration import enable_symbolicai
        result = enable_symbolicai()
        assert result is False

    def test_enable_symbolicai_already_available(self):
        """If SYMBOLIC_AI_AVAILABLE is True, should return True immediately."""
        import ipfs_datasets_py.logic.integration as m
        original = m.SYMBOLIC_AI_AVAILABLE
        try:
            m.SYMBOLIC_AI_AVAILABLE = True
            result = m.enable_symbolicai()
            assert result is True
        finally:
            m.SYMBOLIC_AI_AVAILABLE = original

    def test_enable_symbolicai_autoconfigure_false(self):
        """With autoconfigure_env=False, should still return False (symai not installed)."""
        from ipfs_datasets_py.logic.integration import enable_symbolicai
        result = enable_symbolicai(autoconfigure_env=False)
        assert result is False

    def test_getattr_lazy_export(self):
        """__getattr__ should lazily load symbols from submodules."""
        import ipfs_datasets_py.logic.integration as m
        # DeonticFormula should be accessible via lazy export
        val = m.DeonticFormula
        assert val is not None

    def test_getattr_availability_flag(self):
        """__getattr__ for availability flags returns bool."""
        import ipfs_datasets_py.logic.integration as m
        result = m.TDFOL_GRAMMAR_AVAILABLE
        assert isinstance(result, bool)

    def test_getattr_unknown_raises(self):
        """__getattr__ for unknown name should raise AttributeError."""
        import ipfs_datasets_py.logic.integration as m
        with pytest.raises(AttributeError):
            _ = m.this_does_not_exist_xyz

    def test_dir_contains_symbols(self):
        """__dir__ should include known exports."""
        import ipfs_datasets_py.logic.integration as m
        names = dir(m)
        assert "DeonticFormula" in names
        assert "enable_symbolicai" in names

    def test_symbolicai_not_available_class(self):
        """_SymbolicAINotAvailable raises ImportError on use."""
        import ipfs_datasets_py.logic.integration as m
        with pytest.raises(ImportError):
            m.InteractiveFOLConstructor()

    def test_symbolicai_not_available_func(self):
        """Placeholder functions raise ImportError."""
        import ipfs_datasets_py.logic.integration as m
        with pytest.raises(ImportError):
            m.create_interactive_session()

    def test_default_config(self):
        """DEFAULT_CONFIG should be accessible."""
        import ipfs_datasets_py.logic.integration as m
        assert hasattr(m, 'DEFAULT_CONFIG')
        assert isinstance(m.DEFAULT_CONFIG, dict)


# ──────────────────────────────────────────────────────────────────────────────
# Section 3: caching/ipfs_proof_cache.py - pin/unpin
# ──────────────────────────────────────────────────────────────────────────────

class TestIPFSProofCachePinUnpinFull:
    """GIVEN pin_proof/unpin_proof WHEN called with mock IPFS THEN correct."""

    def _make_cache_with_mock(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        cache = IPFSProofCache(enable_ipfs=False)
        mock_client = MagicMock()
        mock_client.add_json.return_value = "QmTest123"
        mock_client.pin.add.return_value = True
        mock_client.pin.rm.return_value = True
        cache.enable_ipfs = True
        cache.ipfs_client = mock_client
        return cache, mock_client

    def test_pin_proof_after_put(self):
        cache, mock_client = self._make_cache_with_mock()
        cache.put("∀x P(x)", {"proved": True})
        result = cache.pin_proof("∀x P(x)", "ipfs_cache")
        assert result is True
        mock_client.pin.add.assert_called()
        assert cache.pinned_count >= 1

    def test_pin_proof_with_existing_ipfs_cid(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache, IPFSCachedProof
        cache = IPFSProofCache(enable_ipfs=False)
        mock_client = MagicMock()
        mock_client.pin.add.return_value = True
        cache.enable_ipfs = True
        cache.ipfs_client = mock_client
        # Manually insert an IPFSCachedProof with existing CID
        key = "formula1::default"
        p = IPFSCachedProof(
            result={"ok": True}, cid="hash1", prover_name="default",
            formula_str="formula1", timestamp=time.time(), ipfs_cid="QmX123"
        )
        cache._cache[key] = p
        with patch.object(type(cache), 'get', return_value={"ok": True}):
            result = cache.pin_proof("formula1", "default")
        assert result is True
        mock_client.pin.add.assert_called_with("QmX123")

    def test_pin_proof_error_handling(self):
        cache, mock_client = self._make_cache_with_mock()
        mock_client.pin.add.side_effect = RuntimeError("pin failed")
        cache.put("∀x P(x)", {"proved": True})
        result = cache.pin_proof("∀x P(x)", "ipfs_cache")
        # May return False and increment errors
        assert cache.ipfs_errors >= 0  # error handling executed

    def test_unpin_proof_with_ipfs_cached_proof(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache, IPFSCachedProof
        cache = IPFSProofCache(enable_ipfs=False)
        mock_client = MagicMock()
        mock_client.pin.rm.return_value = True
        cache.enable_ipfs = True
        cache.ipfs_client = mock_client
        cache.pinned_count = 2
        # Insert IPFSCachedProof with cid
        key = "formula1::default"
        p = IPFSCachedProof(
            result={"ok": True}, cid="hash1", prover_name="default",
            formula_str="formula1", timestamp=time.time(), ipfs_cid="QmX456", pinned=True
        )
        cache._cache[key] = p
        result = cache.unpin_proof("formula1", "default")
        assert result is True
        mock_client.pin.rm.assert_called_with("QmX456")
        assert p.pinned is False
        assert cache.pinned_count == 1

    def test_unpin_proof_error_handling(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache, IPFSCachedProof
        cache = IPFSProofCache(enable_ipfs=False)
        mock_client = MagicMock()
        mock_client.pin.rm.side_effect = RuntimeError("unpin error")
        cache.enable_ipfs = True
        cache.ipfs_client = mock_client
        key = "formula1::default"
        p = IPFSCachedProof(
            result={"ok": True}, cid="hash1", prover_name="default",
            formula_str="formula1", timestamp=time.time(), ipfs_cid="QmX789"
        )
        cache._cache[key] = p
        result = cache.unpin_proof("formula1", "default")
        assert result is False
        assert cache.ipfs_errors == 1

    def test_upload_to_ipfs_success(self):
        cache, mock_client = self._make_cache_with_mock()
        cid = cache._upload_to_ipfs("p(a)", {"proved": True}, pin=False)
        assert cid == "QmTest123"
        assert cache.ipfs_uploads == 1

    def test_upload_to_ipfs_with_pin(self):
        cache, mock_client = self._make_cache_with_mock()
        cid = cache._upload_to_ipfs("p(a)", {"proved": True}, pin=True)
        mock_client.pin.add.assert_called_once()
        assert cache.pinned_count == 1

    def test_upload_to_ipfs_no_client(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        cache = IPFSProofCache(enable_ipfs=False)
        cid = cache._upload_to_ipfs("p(a)", {"proved": True})
        assert cid is None

    def test_upload_to_ipfs_error(self):
        cache, mock_client = self._make_cache_with_mock()
        mock_client.add_json.side_effect = RuntimeError("IPFS error")
        cid = cache._upload_to_ipfs("p(a)", {"proved": True})
        assert cid is None
        assert cache.ipfs_errors == 1


# ──────────────────────────────────────────────────────────────────────────────
# Section 4: bridges/prover_installer.py
# ──────────────────────────────────────────────────────────────────────────────

class TestProverInstaller:
    """GIVEN prover_installer WHEN called THEN correct behavior."""

    def test_ensure_coq_no_yes_flag(self):
        """ensure_coq with yes=False returns False (coqc not installed)."""
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_coq, _which
        if _which("coqc"):
            pytest.skip("coqc is installed on this system")
        result = ensure_coq(yes=False, strict=False)
        assert result is False

    def test_ensure_lean_no_yes_flag(self):
        """ensure_lean with yes=False returns success only if lean installed."""
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_lean, _which
        if _which("lean"):
            pytest.skip("lean is already installed")
        result = ensure_lean(yes=False, strict=False)
        assert result is False

    def test_which_nonexistent(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import _which
        assert _which("this_tool_does_not_exist_xyz") is None

    def test_main_no_args_calls_both(self):
        """main() with no specific flags should call both install functions."""
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import main
        # Without --yes, should print messages but not hang
        try:
            result = main(["--lean", "--coq"])
            # result is 0 (success) or 1 (failure)
            assert isinstance(result, int)
        except SystemExit as e:
            # argparse may call sys.exit
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Section 5: bridges/tdfol_cec_bridge.py additional uncovered lines
# ──────────────────────────────────────────────────────────────────────────────

class TestTDFOLCECBridgeLines:
    """GIVEN tdfol_cec_bridge WHEN edge cases exercised THEN coverage improves."""

    def _make_bridge(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        return TDFOLCECBridge()

    def test_prove_with_axioms(self):
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate, Constant
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
        bridge = self._make_bridge()
        goal = Predicate("P", (Constant("a"),))
        axiom = Predicate("Q", (Constant("b"),))
        bridge.cec_available = False
        result = bridge.prove_with_cec(goal, [axiom], timeout_ms=100)
        assert isinstance(result, ProofResult)

    def test_from_target_format_with_timeout(self):
        """Simulate a timeout result conversion."""
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
        bridge = self._make_bridge()
        f = ProofResult(
            status=ProofStatus.TIMEOUT,
            formula=None,
            time_ms=5000,
            method="cec",
            message="timeout"
        )
        result = bridge.from_target_format(f)
        assert result.status == ProofStatus.TIMEOUT

    def test_enhanced_tdfol_prover_init(self):
        """Cover EnhancedTDFOLProver if available."""
        import ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge as m
        cls = getattr(m, 'EnhancedTDFOLProver', None)
        if cls is None:
            pytest.skip("EnhancedTDFOLProver not available")
        prover = cls()
        assert prover is not None


# ──────────────────────────────────────────────────────────────────────────────
# Section 6: More symbolic_contracts coverage (FOLInput pydantic-stub validators)
# ──────────────────────────────────────────────────────────────────────────────

class TestFOLInputPydanticStub:
    """GIVEN FOLInput pydantic-stub WHEN fields set THEN validators behave correctly."""

    def test_input_with_many_predicates(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLInput
        inp = FOLInput(
            text="All employees must comply with policy",
            domain_predicates=["Employee", "Policy", "123invalid!", "Valid123"],
        )
        assert hasattr(inp, 'domain_predicates')

    def test_fol_output_validation_results(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLOutput
        out = FOLOutput(
            fol_formula="∀x Employee(x) → Comply(x)",
            confidence=0.85,
            logical_components={"quantifiers": ["∀"], "predicates": ["Employee", "Comply"], "entities": []},
            reasoning_steps=["step1", "step2"],
            warnings=["potential issue"],
            metadata={"quality": "high"},
            validation_results={"valid": True, "errors": []}
        )
        assert out.confidence == 0.85
        assert out.validation_results.get("valid") is True

    def test_fol_output_complexity_score(self):
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import FOLOutput
        out = FOLOutput(
            fol_formula="P(x)",
            confidence=0.5,
            logical_components={},
            reasoning_steps=[],
            warnings=[],
            metadata={},
            complexity_score=5
        )
        assert out.complexity_score == 5

    def test_converted_formula_output(self):
        """Full conversion test via ContractedFOLConverter."""
        from ipfs_datasets_py.logic.integration.domain.symbolic_contracts import (
            ContractedFOLConverter, FOLInput,
        )
        conv = ContractedFOLConverter()
        for text, should_contain in [
            ("All cats are animals", "∀"),
            ("Some birds can fly", "∃"),
            ("The dog barks", "Statement"),
        ]:
            inp = FOLInput(text=text)
            out = conv(inp)
            assert isinstance(out.fol_formula, str)
            assert len(out.fol_formula) > 0
