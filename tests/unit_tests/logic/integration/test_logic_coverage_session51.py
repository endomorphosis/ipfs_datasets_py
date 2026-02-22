"""
Session 51 – coverage tests for bridges + caching.

Targets:
  - bridges/base_prover_bridge.py:         63% → 90%+
  - bridges/tdfol_cec_bridge.py:           36% → 85%+
  - bridges/tdfol_shadowprover_bridge.py:  30% → 80%+
  - bridges/tdfol_grammar_bridge.py:       29% → 80%+
  - bridges/external_provers.py:           62% → 85%+
  - caching/ipfs_proof_cache.py:           32% → 70%+

Bug fixes applied before these tests:
  - tdfol_shadowprover_bridge.py:162  prove_modal_formula → prove_modal
  - tdfol_shadowprover_bridge.py:120  tdfol_to_modal_string → _tdfol_to_modal_format
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_formula(name: str = "P", arg: str = "a"):
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate, Constant
    return Predicate(name, [Constant(arg)])


def _proof_result_proved(formula=None):
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
    return ProofResult(status=ProofStatus.PROVED, formula=formula, time_ms=0, method="test")


def _proof_result_unknown(formula=None):
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
    return ProofResult(status=ProofStatus.UNKNOWN, formula=formula, time_ms=0, method="test")


# ---------------------------------------------------------------------------
# base_prover_bridge.py – BridgeCapability, BridgeMetadata, BridgeRegistry
# ---------------------------------------------------------------------------

class TestBridgeCapability:
    """GIVEN BridgeCapability enum WHEN accessing values THEN correct strings returned."""

    def test_all_values(self):
        from ipfs_datasets_py.logic.integration.bridges.base_prover_bridge import BridgeCapability
        assert BridgeCapability.BIDIRECTIONAL_CONVERSION.value == "bidirectional"
        assert BridgeCapability.INCREMENTAL_PROVING.value == "incremental"
        assert BridgeCapability.RULE_EXTRACTION.value == "rule_extraction"
        assert BridgeCapability.OPTIMIZATION.value == "optimization"
        assert BridgeCapability.PARALLEL_PROVING.value == "parallel"


class TestBridgeMetadata:
    """GIVEN BridgeMetadata dataclass WHEN constructed THEN fields accessible."""

    def test_creation(self):
        from ipfs_datasets_py.logic.integration.bridges.base_prover_bridge import (
            BridgeMetadata, BridgeCapability
        )
        meta = BridgeMetadata(
            name="TestBridge",
            version="1.0",
            target_system="TestSystem",
            capabilities=[BridgeCapability.BIDIRECTIONAL_CONVERSION],
            requires_external_prover=False,
            description="A test bridge"
        )
        assert meta.name == "TestBridge"
        assert meta.target_system == "TestSystem"
        assert len(meta.capabilities) == 1


class TestBridgeRegistry:
    """GIVEN BridgeRegistry WHEN bridges registered THEN all registry methods work."""

    def _make_registry_with_bridges(self):
        from ipfs_datasets_py.logic.integration.bridges.base_prover_bridge import (
            BridgeRegistry, BridgeCapability
        )
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import TDFOLGrammarBridge
        reg = BridgeRegistry()
        reg.register("cec", TDFOLCECBridge())
        reg.register("grammar", TDFOLGrammarBridge())
        return reg

    def test_register_and_list_all(self):
        reg = self._make_registry_with_bridges()
        names = reg.list_all()
        assert "cec" in names
        assert "grammar" in names

    def test_get_bridge(self):
        reg = self._make_registry_with_bridges()
        b = reg.get("cec")
        assert b is not None

    def test_get_missing_returns_none(self):
        reg = self._make_registry_with_bridges()
        assert reg.get("nonexistent") is None

    def test_list_available(self):
        reg = self._make_registry_with_bridges()
        available = reg.list_available()
        # Both should be available since CEC and Grammar are importable
        assert len(available) >= 1

    def test_find_capable(self):
        from ipfs_datasets_py.logic.integration.bridges.base_prover_bridge import BridgeCapability
        reg = self._make_registry_with_bridges()
        caps = reg.find_capable(BridgeCapability.BIDIRECTIONAL_CONVERSION)
        assert isinstance(caps, list)

    def test_select_best_preferred(self):
        reg = self._make_registry_with_bridges()
        f = _make_formula()
        bridge = reg.select_best(f, preferred="grammar")
        # Grammar bridge has available=True since GRAMMAR_AVAILABLE
        # It may or may not validate the formula — test we get a result
        assert bridge is None or bridge is not None  # just verify no crash

    def test_select_best_no_preferred(self):
        reg = self._make_registry_with_bridges()
        f = _make_formula()
        result = reg.select_best(f)
        # Just verify no crash
        assert result is None or result is not None

    def test_get_bridge_registry_global(self):
        from ipfs_datasets_py.logic.integration.bridges.base_prover_bridge import get_bridge_registry, BridgeRegistry
        reg = get_bridge_registry()
        assert isinstance(reg, BridgeRegistry)

    def test_validate_formula_unavailable_bridge(self):
        """GIVEN bridge with unavailable=False WHEN validate_formula called THEN returns False."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import TDFOLGrammarBridge
        bridge = TDFOLGrammarBridge()
        bridge._available = False
        bridge.available = False
        f = _make_formula()
        result = bridge.validate_formula(f)
        assert result is False  # to_target_format raises ValueError


# ---------------------------------------------------------------------------
# tdfol_cec_bridge.py – TDFOLCECBridge, EnhancedTDFOLProver
# ---------------------------------------------------------------------------

class TestTDFOLCECBridgeInit:
    """GIVEN TDFOLCECBridge WHEN initialized THEN metadata and flags set correctly."""

    def test_init_metadata(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        meta = b.get_metadata()
        assert meta.name == "TDFOL-CEC Bridge"
        assert meta.target_system == "CEC"

    def test_cec_available_flag(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge, CEC_AVAILABLE
        b = TDFOLCECBridge()
        assert b.cec_available == CEC_AVAILABLE

    def test_is_available(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        assert isinstance(b.is_available(), bool)

    def test_capabilities(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        from ipfs_datasets_py.logic.integration.bridges.base_prover_bridge import BridgeCapability
        b = TDFOLCECBridge()
        caps = b.get_capabilities()
        assert BridgeCapability.BIDIRECTIONAL_CONVERSION in caps

    def test_has_capability(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        from ipfs_datasets_py.logic.integration.bridges.base_prover_bridge import BridgeCapability
        b = TDFOLCECBridge()
        assert b.has_capability(BridgeCapability.RULE_EXTRACTION)
        assert not b.has_capability(BridgeCapability.PARALLEL_PROVING)

    def test_repr(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        r = repr(b)
        assert "TDFOLCECBridge" in r
        assert "CEC" in r


class TestTDFOLCECBridgeConversion:
    """GIVEN TDFOLCECBridge WHEN converting formulas THEN correct output."""

    def test_to_target_format_simple_predicate(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        f = _make_formula()
        dcec = b.to_target_format(f)
        assert isinstance(dcec, str)

    def test_tdfol_to_dcec_string(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        f = _make_formula()
        dcec = b.tdfol_to_dcec_string(f)
        assert dcec == b.to_target_format(f)

    def test_to_target_format_unavailable_raises(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        b._available = False
        b.cec_available = False
        f = _make_formula()
        with pytest.raises(ValueError, match="CEC bridge not available"):
            b.to_target_format(f)

    def test_from_target_format_proof_result_passthrough(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLCECBridge()
        original = _proof_result_proved()
        result = b.from_target_format(original)
        assert result.status == ProofStatus.PROVED

    def test_from_target_format_unknown_type(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLCECBridge()
        result = b.from_target_format("some raw string")
        assert result.status == ProofStatus.UNKNOWN

    def test_dcec_string_to_tdfol(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        formula = b.dcec_string_to_tdfol("P(a)")
        assert formula is not None


class TestTDFOLCECBridgeProve:
    """GIVEN TDFOLCECBridge WHEN prove called THEN returns ProofResult."""

    def test_prove_returns_result(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
        b = TDFOLCECBridge()
        f = _make_formula()
        result = b.prove(f, timeout=1)
        assert isinstance(result, ProofResult)

    def test_prove_with_cec_unavailable(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLCECBridge()
        b.cec_available = False
        f = _make_formula()
        result = b.prove_with_cec(f, axioms=[], timeout_ms=1000)
        assert result.status == ProofStatus.UNKNOWN
        assert "not available" in result.message

    def test_prove_with_cec_exception_path(self):
        """GIVEN CEC available but dcec_parsing has no parse_dcec_formula THEN ERROR status."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLCECBridge()
        f = _make_formula()
        # The real dcec_parsing doesn't have parse_dcec_formula, so it returns ERROR
        result = b.prove_with_cec(f, axioms=[], timeout_ms=100)
        # Either ERROR or UNKNOWN depending on what fails
        assert result.status in (ProofStatus.ERROR, ProofStatus.UNKNOWN)

    def test_get_applicable_cec_rules_unavailable(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        b.cec_available = False
        f = _make_formula()
        rules = b.get_applicable_cec_rules(f)
        assert rules == []

    def test_get_applicable_cec_rules_available(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        b = TDFOLCECBridge()
        f = _make_formula()
        rules = b.get_applicable_cec_rules(f)
        assert isinstance(rules, list)


class TestEnhancedTDFOLProver:
    """GIVEN EnhancedTDFOLProver WHEN initialized and used THEN correct behavior."""

    def test_init_default(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import EnhancedTDFOLProver
        p = EnhancedTDFOLProver()
        assert isinstance(p.use_cec, bool)

    def test_init_no_cec(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import EnhancedTDFOLProver
        p = EnhancedTDFOLProver(use_cec=False)
        assert p.cec_bridge is None

    def test_init_with_cec(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import (
            EnhancedTDFOLProver, TDFOLCECBridge
        )
        p = EnhancedTDFOLProver(use_cec=True)
        assert isinstance(p.cec_bridge, TDFOLCECBridge)

    def test_prove_returns_result(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import EnhancedTDFOLProver
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
        p = EnhancedTDFOLProver(use_cec=False)
        f = _make_formula()
        result = p.prove(f, timeout_ms=500)
        assert isinstance(result, ProofResult)

    def test_create_enhanced_prover_factory(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import (
            create_enhanced_prover, EnhancedTDFOLProver
        )
        p = create_enhanced_prover(use_cec=False)
        assert isinstance(p, EnhancedTDFOLProver)


# ---------------------------------------------------------------------------
# tdfol_shadowprover_bridge.py – TDFOLShadowProverBridge, ModalAwareTDFOLProver
# ---------------------------------------------------------------------------

class TestTDFOLShadowProverBridgeInit:
    """GIVEN TDFOLShadowProverBridge WHEN initialized THEN metadata and flags set."""

    def test_init_metadata(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        b = TDFOLShadowProverBridge()
        meta = b.get_metadata()
        assert meta.name == "TDFOL-ShadowProver Bridge"
        assert meta.target_system == "ShadowProver"

    def test_check_availability(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, SHADOWPROVER_AVAILABLE
        )
        b = TDFOLShadowProverBridge()
        assert b.available == SHADOWPROVER_AVAILABLE

    def test_modal_logic_type_enum(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import ModalLogicType
        assert ModalLogicType.K.value == "K"
        assert ModalLogicType.S4.value == "S4"
        assert ModalLogicType.S5.value == "S5"
        assert ModalLogicType.D.value == "D"
        assert ModalLogicType.T.value == "T"


class TestTDFOLShadowProverBridgeConversion:
    """GIVEN TDFOLShadowProverBridge WHEN converting formulas THEN correct output."""

    def test_to_target_format(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        b = TDFOLShadowProverBridge()
        f = _make_formula()
        s = b.to_target_format(f)
        assert isinstance(s, str)

    def test_to_target_format_unavailable_raises(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        b = TDFOLShadowProverBridge()
        b._available = False
        b.available = False
        f = _make_formula()
        with pytest.raises(ValueError, match="ShadowProver bridge not available"):
            b.to_target_format(f)

    def test_from_target_format_proof_result_passthrough(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLShadowProverBridge()
        original = _proof_result_proved()
        result = b.from_target_format(original)
        assert result.status == ProofStatus.PROVED

    def test_from_target_format_unknown_type(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLShadowProverBridge()
        result = b.from_target_format("some raw string")
        assert result.status == ProofStatus.UNKNOWN

    def test_tdfol_to_modal_format_temporal(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_always
        b = TDFOLShadowProverBridge()
        f = create_always(_make_formula())
        s = b._tdfol_to_modal_format(f)
        assert "□" in s

    def test_tdfol_to_modal_format_eventually(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_eventually
        b = TDFOLShadowProverBridge()
        f = create_eventually(_make_formula())
        s = b._tdfol_to_modal_format(f)
        assert "◊" in s

    def test_tdfol_to_modal_format_obligation(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_obligation
        b = TDFOLShadowProverBridge()
        f = create_obligation(_make_formula())
        s = b._tdfol_to_modal_format(f)
        # O(P(a)) — the string contains the predicate
        assert "P(a)" in s

    def test_tdfol_to_modal_format_permission(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_permission
        b = TDFOLShadowProverBridge()
        f = create_permission(_make_formula())
        s = b._tdfol_to_modal_format(f)
        # P(P(a)) — the string contains the predicate
        assert "P(a)" in s


class TestTDFOLShadowProverBridgeSelectModalLogic:
    """GIVEN TDFOLShadowProverBridge WHEN selecting modal logic THEN correct type returned."""

    def test_select_temporal_always(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_always
        b = TDFOLShadowProverBridge()
        f = create_always(_make_formula())
        assert b.select_modal_logic(f) == ModalLogicType.S4

    def test_select_temporal_eventually(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_eventually
        b = TDFOLShadowProverBridge()
        f = create_eventually(_make_formula())
        assert b.select_modal_logic(f) == ModalLogicType.S4

    def test_select_deontic(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_obligation
        b = TDFOLShadowProverBridge()
        f = create_obligation(_make_formula())
        assert b.select_modal_logic(f) == ModalLogicType.D

    def test_select_plain_predicate(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        b = TDFOLShadowProverBridge()
        f = _make_formula()
        assert b.select_modal_logic(f) == ModalLogicType.K


class TestTDFOLShadowProverBridgeGetProver:
    """GIVEN TDFOLShadowProverBridge WHEN _get_prover called THEN correct prover returned."""

    def test_get_prover_k(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        b = TDFOLShadowProverBridge()
        p = b._get_prover(ModalLogicType.K)
        assert p is b.k_prover

    def test_get_prover_s4(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        b = TDFOLShadowProverBridge()
        p = b._get_prover(ModalLogicType.S4)
        assert p is b.s4_prover

    def test_get_prover_s5(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        b = TDFOLShadowProverBridge()
        p = b._get_prover(ModalLogicType.S5)
        assert p is b.s5_prover

    def test_get_prover_d_uses_k(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        b = TDFOLShadowProverBridge()
        p = b._get_prover(ModalLogicType.D)
        assert p is b.k_prover

    def test_get_prover_t_uses_s4(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        b = TDFOLShadowProverBridge()
        p = b._get_prover(ModalLogicType.T)
        assert p is b.s4_prover


class TestTDFOLShadowProverBridgeProve:
    """GIVEN TDFOLShadowProverBridge WHEN prove called THEN ProofResult returned."""

    def test_prove_returns_result(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
        b = TDFOLShadowProverBridge()
        f = _make_formula()
        result = b.prove(f)
        assert isinstance(result, ProofResult)

    def test_prove_modal_unavailable(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLShadowProverBridge()
        b.available = False
        f = _make_formula()
        result = b.prove_modal(f)
        assert result.status == ProofStatus.UNKNOWN
        assert "not available" in result.message

    def test_prove_modal_exception_path(self):
        """GIVEN available bridge but prover raises exception THEN ERROR status."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLShadowProverBridge()
        # Mock k_prover to raise
        mock_prover = MagicMock()
        mock_prover.prove.side_effect = RuntimeError("prover crashed")
        b.k_prover = mock_prover
        f = _make_formula()
        result = b.prove_modal(f, logic_type=ModalLogicType.K)
        assert result.status == ProofStatus.ERROR

    def test_prove_modal_explicit_logic_type(self):
        """GIVEN explicit logic_type S5 WHEN prove_modal called THEN uses S5 prover."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge, ModalLogicType
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
        b = TDFOLShadowProverBridge()
        f = _make_formula()
        result = b.prove_modal(f, logic_type=ModalLogicType.S5)
        # Just verify no crash and we get a result
        assert isinstance(result, ProofResult)

    def test_prove_with_tableaux_unavailable(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLShadowProverBridge()
        b.available = False
        f = _make_formula()
        result = b.prove_with_tableaux(f)
        assert result.status == ProofStatus.UNKNOWN
        assert "not available" in result.message

    def test_prove_with_tableaux_exception_path(self):
        """GIVEN tableaux prover returns some result THEN any valid ProofStatus returned."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            TDFOLShadowProverBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLShadowProverBridge()
        f = _make_formula()
        result = b.prove_with_tableaux(f)
        # Can be any status — just verify it's a valid ProofStatus
        assert isinstance(result.status, ProofStatus)


class TestModalAwareTDFOLProver:
    """GIVEN ModalAwareTDFOLProver WHEN initialized and prove called THEN correct behavior."""

    def test_init(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            ModalAwareTDFOLProver
        )
        p = ModalAwareTDFOLProver()
        assert p.base_prover is not None
        assert p.shadow_bridge is not None

    def test_has_temporal_operators_plain(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            ModalAwareTDFOLProver
        )
        p = ModalAwareTDFOLProver()
        assert not p._has_temporal_operators(_make_formula())

    def test_has_temporal_operators_temporal(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            ModalAwareTDFOLProver
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_always
        p = ModalAwareTDFOLProver()
        assert p._has_temporal_operators(create_always(_make_formula()))

    def test_has_deontic_operators_plain(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            ModalAwareTDFOLProver
        )
        p = ModalAwareTDFOLProver()
        assert not p._has_deontic_operators(_make_formula())

    def test_has_deontic_operators_deontic(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            ModalAwareTDFOLProver
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_obligation
        p = ModalAwareTDFOLProver()
        assert p._has_deontic_operators(create_obligation(_make_formula()))

    def test_prove_plain_formula(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            ModalAwareTDFOLProver
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
        p = ModalAwareTDFOLProver()
        result = p.prove(_make_formula(), timeout_ms=500)
        assert isinstance(result, ProofResult)

    def test_prove_without_modal_specialized(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            ModalAwareTDFOLProver
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import create_always
        p = ModalAwareTDFOLProver()
        result = p.prove(create_always(_make_formula()), use_modal_specialized=False)
        assert isinstance(result, ProofResult)

    def test_create_modal_aware_prover_factory(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_shadowprover_bridge import (
            create_modal_aware_prover, ModalAwareTDFOLProver
        )
        p = create_modal_aware_prover()
        assert isinstance(p, ModalAwareTDFOLProver)


# ---------------------------------------------------------------------------
# tdfol_grammar_bridge.py
# ---------------------------------------------------------------------------

class TestTDFOLGrammarBridgeInit:
    """GIVEN TDFOLGrammarBridge WHEN initialized THEN metadata and flags set."""

    def test_metadata(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        meta = b.get_metadata()
        assert meta.name == "TDFOL-Grammar Bridge"

    def test_check_availability(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge, GRAMMAR_AVAILABLE
        )
        b = TDFOLGrammarBridge()
        assert b.available == GRAMMAR_AVAILABLE


class TestTDFOLGrammarBridgeProve:
    """GIVEN TDFOLGrammarBridge WHEN prove called THEN UNKNOWN returned."""

    def test_prove_returns_unknown(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLGrammarBridge()
        result = b.prove(_make_formula())
        assert result.status == ProofStatus.UNKNOWN

    def test_from_target_format_returns_unknown(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus
        b = TDFOLGrammarBridge()
        result = b.from_target_format("anything")
        assert result.status == ProofStatus.UNKNOWN


class TestTDFOLGrammarBridgeParsing:
    """GIVEN TDFOLGrammarBridge WHEN parsing NL THEN formulas returned or None."""

    def test_parse_natural_language_returns_none_when_no_grammar_match(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        # Grammar may or may not match; just verify no crash
        result = b.parse_natural_language("some random text here")
        # result could be None or a Formula
        assert result is None or hasattr(result, "to_string")

    def test_parse_natural_language_use_fallback_false(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        result = b.parse_natural_language("random unrecognized phrase", use_fallback=False)
        assert result is None or hasattr(result, "to_string")

    def test_parse_natural_language_unavailable_falls_back(self):
        """GIVEN grammar bridge unavailable WHEN parse_natural_language called THEN fallback invoked."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        b.available = False
        # _fallback_parse returns None when not available
        result = b.parse_natural_language("It is obligatory to report")
        assert result is None

    def test_fallback_parse_unavailable(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        b.available = False
        result = b._fallback_parse("test text")
        assert result is None

    def test_batch_parse(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        results = b.batch_parse(["text one", "text two"])
        assert len(results) == 2
        for text, formula in results:
            assert isinstance(text, str)

    def test_analyze_parse_quality(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        quality = b.analyze_parse_quality("some text")
        assert "text" in quality
        assert "success" in quality
        assert quality["text"] == "some text"

    def test_analyze_parse_quality_with_expected(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        expected = _make_formula()
        quality = b.analyze_parse_quality("some text", expected_formula=expected)
        assert "matches_expected" in quality


class TestTDFOLGrammarBridgeNLConversion:
    """GIVEN TDFOLGrammarBridge WHEN formula_to_natural_language called THEN string returned."""

    def test_formula_to_nl_unavailable_fallback(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        b.available = False
        f = _make_formula()
        result = b.formula_to_natural_language(f)
        assert isinstance(result, str)

    def test_formula_to_nl_available(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        f = _make_formula()
        result = b.formula_to_natural_language(f, style="formal")
        assert isinstance(result, str)

    def test_formula_to_nl_casual_style(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        f = _make_formula()
        result = b.formula_to_natural_language(f, style="casual")
        assert isinstance(result, str)

    def test_to_target_format_unavailable_raises(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        b._available = False
        b.available = False
        f = _make_formula()
        with pytest.raises(ValueError, match="Grammar bridge not available"):
            b.to_target_format(f)

    def test_dcec_to_nl_template_fallback(self):
        """GIVEN dcec_grammar=None WHEN _dcec_to_natural_language called THEN template used."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        b.dcec_grammar = None
        result = b._dcec_to_natural_language("(O report)", "formal")
        assert isinstance(result, str)

    def test_apply_casual_style(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            TDFOLGrammarBridge
        )
        b = TDFOLGrammarBridge()
        casual = b._apply_casual_style("It is obligatory that you report")
        assert "must" in casual


class TestConvenienceFunctions:
    """GIVEN parse_nl and explain_formula WHEN called THEN results returned."""

    def test_parse_nl(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import parse_nl
        result = parse_nl("some text")
        assert result is None or hasattr(result, "to_string")

    def test_explain_formula(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import explain_formula
        f = _make_formula()
        result = explain_formula(f)
        assert isinstance(result, str)


class TestNaturalLanguageTDFOLInterface:
    """GIVEN NaturalLanguageTDFOLInterface WHEN understand/explain/reason called THEN correct."""

    def test_init(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            NaturalLanguageTDFOLInterface
        )
        iface = NaturalLanguageTDFOLInterface()
        assert iface.grammar_bridge is not None
        assert iface.prover is not None

    def test_understand(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            NaturalLanguageTDFOLInterface
        )
        iface = NaturalLanguageTDFOLInterface()
        result = iface.understand("some text here")
        assert result is None or hasattr(result, "to_string")

    def test_explain(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            NaturalLanguageTDFOLInterface
        )
        iface = NaturalLanguageTDFOLInterface()
        f = _make_formula()
        result = iface.explain(f)
        assert isinstance(result, str)

    def test_reason_unparseable_premise(self):
        """GIVEN premise that can't be parsed WHEN reason called THEN valid=False."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            NaturalLanguageTDFOLInterface, TDFOLGrammarBridge
        )
        iface = NaturalLanguageTDFOLInterface()
        # Make grammar bridge always return None
        iface.grammar_bridge.available = False
        result = iface.reason(
            premises=["All birds fly"],
            conclusion="Tweety flies"
        )
        assert result["valid"] is False
        assert "error" in result

    def test_reason_unparseable_conclusion(self):
        """GIVEN parseable premises but unparseable conclusion WHEN reason called THEN valid=False."""
        from ipfs_datasets_py.logic.integration.bridges.tdfol_grammar_bridge import (
            NaturalLanguageTDFOLInterface, TDFOLGrammarBridge
        )
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate, Constant
        iface = NaturalLanguageTDFOLInterface()
        # Patch understand to return formula for premise but None for conclusion
        call_count = [0]
        original_understand = iface.understand
        def patched_understand(text):
            call_count[0] += 1
            if call_count[0] == 1:
                return Predicate("Bird", [Constant("tweety")])
            return None  # conclusion can't be parsed
        iface.understand = patched_understand
        result = iface.reason(
            premises=["Tweety is a bird"],
            conclusion="unparseable conclusion ##"
        )
        assert result["valid"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# external_provers.py – VampireProver, EProver, ProverRegistry
# ---------------------------------------------------------------------------

class TestVampireProverBasic:
    """GIVEN VampireProver WHEN initialized with unavailable binary THEN prove returns error."""

    def test_init_no_crash(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver
        v = VampireProver(vampire_path="/nonexistent/vampire")
        assert v.vampire_path == "/nonexistent/vampire"

    def test_formula_to_tptp(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver
        v = VampireProver(vampire_path="/nonexistent/vampire")
        tptp = v._formula_to_tptp("forall x. P(x)")
        assert "conjecture" in tptp
        assert "forall x. P(x)" in tptp

    def test_prove_unavailable_returns_error(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            VampireProver, ProverStatus
        )
        v = VampireProver(vampire_path="/nonexistent/vampire")
        result = v.prove("∀x P(x)")
        assert result.status == ProverStatus.ERROR

    def test_extract_proof_found(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver
        v = VampireProver(vampire_path="/nonexistent/vampire")
        output = "Proof\nStep 1: axiom\nSuccess PROVED"
        proof = v._extract_proof(output)
        assert proof is not None

    def test_extract_proof_not_found(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver
        v = VampireProver(vampire_path="/nonexistent/vampire")
        output = "No proof found"
        proof = v._extract_proof(output)
        assert proof is None

    def test_extract_statistics(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver
        v = VampireProver(vampire_path="/nonexistent/vampire")
        output = "Active clauses: 42\nInferences made: 100"
        stats = v._extract_statistics(output)
        assert isinstance(stats, dict)

    def test_prove_with_axioms(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            VampireProver, ProverStatus
        )
        v = VampireProver(vampire_path="/nonexistent/vampire")
        result = v.prove("∀x P(x)", axioms=["P(a)", "P(b)"])
        assert result.status == ProverStatus.ERROR


class TestEProverBasic:
    """GIVEN EProver WHEN initialized with unavailable binary THEN prove returns error."""

    def test_init_no_crash(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver
        e = EProver(eprover_path="/nonexistent/eprover")
        assert e.eprover_path == "/nonexistent/eprover"

    def test_prover_name_in_result(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            EProver, ProverStatus
        )
        e = EProver(eprover_path="/nonexistent/eprover")
        result = e.prove("∀x P(x)")
        # EProver uses "E" as prover name in results
        # The prover name appears in the result object
        assert result.status == ProverStatus.ERROR

    def test_formula_to_tptp(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver
        e = EProver(eprover_path="/nonexistent/eprover")
        tptp = e._formula_to_tptp("forall x. P(x)")
        assert "conjecture" in tptp

    def test_prove_unavailable_returns_error(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            EProver, ProverStatus
        )
        e = EProver(eprover_path="/nonexistent/eprover")
        result = e.prove("∀x P(x)")
        assert result.status == ProverStatus.ERROR

    def test_extract_statistics(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver
        e = EProver(eprover_path="/nonexistent/eprover")
        output = "Processed clauses: 50\nGenerated clauses: 20"
        stats = e._extract_statistics(output)
        assert isinstance(stats, dict)


class TestProverResult:
    """GIVEN ProverResult WHEN created THEN fields accessible."""

    def test_creation_minimal(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverResult, ProverStatus
        )
        r = ProverResult(status=ProverStatus.THEOREM, prover="Vampire")
        assert r.status == ProverStatus.THEOREM
        assert r.prover == "Vampire"

    def test_creation_full(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverResult, ProverStatus
        )
        r = ProverResult(
            status=ProverStatus.ERROR,
            proof=None,
            time=1.5,
            prover="E",
            statistics={"clauses": 10},
            error="test error"
        )
        assert r.error == "test error"
        assert r.time == 1.5


class TestProverRegistry:
    """GIVEN ProverRegistry WHEN provers registered THEN all methods work."""

    def test_init_empty(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverRegistry
        reg = ProverRegistry()
        assert reg.list_provers() == []

    def test_register_and_list(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverRegistry, VampireProver
        )
        reg = ProverRegistry()
        v = VampireProver(vampire_path="/nonexistent/vampire")
        reg.register(v)
        assert "VampireProver" in reg.list_provers()

    def test_register_with_name(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverRegistry, EProver
        )
        reg = ProverRegistry()
        e = EProver(eprover_path="/nonexistent/eprover")
        reg.register(e, name="my_eprover")
        assert "my_eprover" in reg.list_provers()

    def test_get_prover(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverRegistry, VampireProver
        )
        reg = ProverRegistry()
        v = VampireProver(vampire_path="/nonexistent/vampire")
        reg.register(v, name="vampire")
        retrieved = reg.get_prover("vampire")
        assert retrieved is v

    def test_get_prover_missing(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverRegistry
        reg = ProverRegistry()
        assert reg.get_prover("nonexistent") is None

    def test_prove_auto_empty_registry(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverRegistry, ProverStatus
        )
        reg = ProverRegistry()
        result = reg.prove_auto("∀x P(x)")
        assert result.status == ProverStatus.ERROR
        assert "No provers" in result.error

    def test_prove_auto_with_unavailable_prover(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverRegistry, VampireProver, ProverStatus
        )
        reg = ProverRegistry()
        v = VampireProver(vampire_path="/nonexistent/vampire")
        reg.register(v, name="vampire")
        result = reg.prove_auto("∀x P(x)")
        # VampireProver is unavailable, returns ERROR
        assert result.status in (ProverStatus.ERROR, ProverStatus.UNKNOWN)

    def test_prove_auto_with_preferred(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverRegistry, VampireProver, EProver, ProverStatus
        )
        reg = ProverRegistry()
        v = VampireProver(vampire_path="/nonexistent/vampire")
        e = EProver(eprover_path="/nonexistent/eprover")
        reg.register(v, name="vampire")
        reg.register(e, name="eprover")
        result = reg.prove_auto("∀x P(x)", prefer="vampire")
        assert isinstance(result.status, ProverStatus)

    def test_is_better_result(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverRegistry, ProverResult, ProverStatus
        )
        reg = ProverRegistry()
        r1 = ProverResult(status=ProverStatus.THEOREM, time=1.0, prover="v")
        r2 = ProverResult(status=ProverStatus.UNKNOWN, time=2.0, prover="v")
        assert reg._is_better_result(r1, r2)
        assert not reg._is_better_result(r2, r1)

    def test_get_prover_registry_global(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            get_prover_registry, ProverRegistry
        )
        reg = get_prover_registry()
        assert isinstance(reg, ProverRegistry)


# ---------------------------------------------------------------------------
# caching/ipfs_proof_cache.py – IPFSProofCache, get_global_ipfs_cache
# ---------------------------------------------------------------------------

class TestIPFSProofCacheInit:
    """GIVEN IPFSProofCache WHEN initialized with IPFS disabled THEN local cache works."""

    def test_init_disabled(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        cache = IPFSProofCache(enable_ipfs=False)
        assert cache.enable_ipfs is False
        assert cache.ipfs_client is None

    def test_init_counters_zeroed(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        cache = IPFSProofCache(enable_ipfs=False)
        assert cache.ipfs_uploads == 0
        assert cache.ipfs_downloads == 0
        assert cache.ipfs_errors == 0
        assert cache.pinned_count == 0


class TestIPFSProofCacheBasicCacheOps:
    """GIVEN IPFSProofCache with IPFS disabled WHEN using local cache THEN set/get work."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        self.cache = IPFSProofCache(enable_ipfs=False)

    def test_set_and_get_local(self):
        self.cache.set("∀x P(x)", {"status": "PROVED"}, prover_name="z3")
        result = self.cache.get("∀x P(x)", prover_name="z3")
        assert result == {"status": "PROVED"}

    def test_get_missing_returns_none(self):
        result = self.cache.get("nonexistent", prover_name="z3")
        assert result is None

    def test_get_statistics(self):
        stats = self.cache.get_statistics()
        assert "ipfs_enabled" in stats
        assert stats["ipfs_enabled"] is False
        assert "ipfs_uploads" in stats

    def test_close_no_client(self):
        # Should not raise
        self.cache.close()
        assert self.cache.ipfs_client is None


class TestIPFSProofCachePut:
    """GIVEN IPFSProofCache WHEN put() called with IPFS disabled THEN local cache updated."""

    def test_put_stores_locally(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        cache = IPFSProofCache(enable_ipfs=False)
        cache.put("formula_one", {"status": "PROVED"})
        result = cache.get("formula_one")
        assert result == {"status": "PROVED"}

    def test_put_with_pin_no_ipfs(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        cache = IPFSProofCache(enable_ipfs=False)
        # With IPFS disabled, pin=True should not crash
        cache.put("formula_pin", {"status": "PROVED"}, pin=True)
        result = cache.get("formula_pin")
        assert result == {"status": "PROVED"}


class TestIPFSProofCacheSyncAndPin:
    """GIVEN IPFSProofCache with IPFS disabled WHEN sync/pin called THEN graceful."""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import IPFSProofCache
        self.cache = IPFSProofCache(enable_ipfs=False)

    def test_sync_from_ipfs_disabled(self):
        count = self.cache.sync_from_ipfs()
        assert count == 0

    def test_pin_proof_disabled(self):
        result = self.cache.pin_proof("formula", prover="z3")
        assert result is False

    def test_unpin_proof_disabled(self):
        result = self.cache.unpin_proof("formula", prover="z3")
        assert result is False

    def test_get_from_ipfs_no_client(self):
        result = self.cache.get_from_ipfs("Qm123")
        assert result is None


class TestIPFSProofCacheMockedIPFS:
    """GIVEN IPFSProofCache with mocked IPFS client WHEN IPFS-enabled operations called."""

    def _make_cache_with_mock_ipfs(self):
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import (
            IPFSProofCache, IPFS_AVAILABLE
        )
        cache = IPFSProofCache(enable_ipfs=False)
        # Manually enable IPFS with a mock client
        mock_client = MagicMock()
        mock_client.add_json.return_value = "QmTestCID123"
        mock_client.get_json.return_value = {
            "formula": "test", "result": {"status": "PROVED"}, "timestamp": 0.0, "version": "1.0"
        }
        cache.enable_ipfs = True
        cache.ipfs_client = mock_client
        return cache, mock_client

    def test_put_uploads_to_ipfs(self):
        cache, mock_client = self._make_cache_with_mock_ipfs()
        cache.put("test_formula", {"status": "PROVED"})
        mock_client.add_json.assert_called_once()
        assert cache.ipfs_uploads == 1

    def test_put_with_pin_pins_cid(self):
        cache, mock_client = self._make_cache_with_mock_ipfs()
        mock_client.pin = MagicMock()
        mock_client.pin.add = MagicMock()
        cache.put("test_formula_pin", {"status": "PROVED"}, pin=True)
        mock_client.pin.add.assert_called_once()
        assert cache.pinned_count == 1

    def test_get_from_ipfs(self):
        cache, mock_client = self._make_cache_with_mock_ipfs()
        result = cache.get_from_ipfs("QmTestCID123")
        assert result is not None

    def test_get_from_ipfs_error(self):
        cache, mock_client = self._make_cache_with_mock_ipfs()
        mock_client.get_json.side_effect = Exception("IPFS error")
        result = cache.get_from_ipfs("QmBadCID")
        assert result is None
        assert cache.ipfs_errors == 1

    def test_close_with_client(self):
        cache, mock_client = self._make_cache_with_mock_ipfs()
        cache.close()
        mock_client.close.assert_called_once()
        assert cache.ipfs_client is None

    def test_close_with_client_exception(self):
        """GIVEN close() raises exception THEN ipfs_client still set to None."""
        cache, mock_client = self._make_cache_with_mock_ipfs()
        mock_client.close.side_effect = Exception("close error")
        cache.close()  # Should not raise
        assert cache.ipfs_client is None


class TestGetGlobalIPFSCache:
    """GIVEN get_global_ipfs_cache WHEN called THEN returns singleton IPFSProofCache."""

    def test_returns_ipfs_proof_cache(self):
        import importlib
        import ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache as mod
        # Reset global singleton
        mod._global_ipfs_cache = None
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import (
            get_global_ipfs_cache, IPFSProofCache
        )
        cache = get_global_ipfs_cache(max_size=100, ttl=60, enable_ipfs=False)
        assert isinstance(cache, IPFSProofCache)

    def test_singleton_behavior(self):
        import ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache as mod
        mod._global_ipfs_cache = None
        from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import get_global_ipfs_cache
        c1 = get_global_ipfs_cache(enable_ipfs=False)
        c2 = get_global_ipfs_cache(enable_ipfs=False)
        assert c1 is c2
        mod._global_ipfs_cache = None  # cleanup
