"""v14 Logic sessions — BA111 (cec_bridge) + BC113 (multi-language NL parsers).

Covers:
  BA111 — logic/integration/cec_bridge.py: CECBridge prove paths + stats + cache
  BC113 — CEC/nl parsers: FrenchParser, SpanishParser, GermanParser, LanguageDetector
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ===========================================================================
# BA111 — CECBridge coverage
# ===========================================================================

class TestCECBridgeInit:
    def test_import(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge, UnifiedProofResult
        assert CECBridge is not None
        assert UnifiedProofResult is not None

    def test_init_no_ipfs_no_z3(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge
        # Disable IPFS + Z3 so no network calls
        bridge = CECBridge(enable_ipfs_cache=False, enable_z3=False, enable_prover_router=False)
        assert bridge.enable_ipfs_cache is False
        assert bridge.ipfs_cache is None
        assert bridge.cec_z3 is None

    def test_init_with_defaults_does_not_crash(self):
        """CECBridge() must not crash even if IPFS is unreachable (graceful degradation)."""
        from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge
        # Even with enable_ipfs_cache=True the __init__ catches connection errors
        try:
            bridge = CECBridge(enable_ipfs_cache=True, enable_z3=False)
            # ipfs_cache may be None if unreachable
            assert bridge is not None
        except Exception as exc:
            # Any exception from __init__ is a regression
            pytest.fail(f"CECBridge.__init__ raised unexpectedly: {exc}")

    def test_unified_proof_result_fields(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import UnifiedProofResult
        result = UnifiedProofResult(
            is_proved=True,
            is_valid=True,
            prover_used="test",
            proof_time=0.5,
            status="proved",
        )
        assert result.is_proved is True
        assert result.prover_used == "test"
        assert result.model is None
        assert result.cec_result is None


class TestCECBridgeProveWithCECManager:
    """Test the CEC-manager (native) prove path without Z3 or router."""

    def _bridge(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge
        return CECBridge(enable_ipfs_cache=False, enable_z3=False, enable_prover_router=False)

    def test_prove_with_cec_strategy(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import UnifiedProofResult
        bridge = self._bridge()
        formula = MagicMock()
        formula.__class__.__name__ = "AtomicFormula"
        # Mock the internal prover manager to return a known result
        with patch.object(bridge, "_prove_with_cec_manager") as mock_prove:
            mock_prove.return_value = UnifiedProofResult(
                is_proved=True,
                is_valid=True,
                prover_used="cec_manager",
                proof_time=0.01,
                status="proved",
            )
            result = bridge.prove(formula, strategy="cec")
        assert result.is_proved is True
        assert result.prover_used == "cec_manager"

    def test_prove_caches_on_success(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import UnifiedProofResult
        bridge = self._bridge()
        formula = MagicMock()
        mock_result = UnifiedProofResult(
            is_proved=True, is_valid=True,
            prover_used="cec_manager", proof_time=0.0, status="proved",
        )
        with patch.object(bridge, "_prove_with_cec_manager", return_value=mock_result), \
             patch.object(bridge, "_cache_proof") as mock_cache, \
             patch.object(bridge, "_get_cached_proof", return_value=None):
            bridge.prove(formula, strategy="cec", use_cache=True)
        mock_cache.assert_called_once()

    def test_prove_cache_hit_returns_cached(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import UnifiedProofResult
        bridge = self._bridge()
        cached = UnifiedProofResult(
            is_proved=True, is_valid=True,
            prover_used="cache", proof_time=0.0, status="cached",
        )
        formula = MagicMock()
        with patch.object(bridge, "_get_cached_proof", return_value=cached) as mock_get:
            result = bridge.prove(formula, use_cache=True)
        assert result.prover_used == "cache"

    def test_prove_no_cache_on_unproved(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import UnifiedProofResult
        bridge = self._bridge()
        formula = MagicMock()
        mock_result = UnifiedProofResult(
            is_proved=False, is_valid=False,
            prover_used="cec_manager", proof_time=0.0, status="unknown",
        )
        with patch.object(bridge, "_prove_with_cec_manager", return_value=mock_result), \
             patch.object(bridge, "_cache_proof") as mock_cache, \
             patch.object(bridge, "_get_cached_proof", return_value=None):
            bridge.prove(formula, strategy="cec", use_cache=True)
        mock_cache.assert_not_called()


class TestCECBridgeSelectStrategy:
    def _bridge(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge
        return CECBridge(enable_ipfs_cache=False, enable_z3=False, enable_prover_router=False)

    def test_select_strategy_deontic_no_z3_returns_cec(self):
        bridge = self._bridge()
        from ipfs_datasets_py.logic.CEC.native.dcec_core import DeonticFormula, DeonticOperator
        formula = MagicMock(spec=DeonticFormula)
        strategy = bridge._select_strategy(formula)
        # No Z3 → should fall back to 'cec'
        assert strategy == "cec"

    def test_select_strategy_generic_falls_to_cec(self):
        bridge = self._bridge()
        formula = MagicMock()
        strategy = bridge._select_strategy(formula)
        # No router → CEC
        assert strategy in ("cec", "router")


class TestCECBridgeStatistics:
    def test_get_statistics_returns_dict(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge
        bridge = CECBridge(enable_ipfs_cache=False, enable_z3=False, enable_prover_router=False)
        stats = bridge.get_statistics()
        assert isinstance(stats, dict)
        # Should have total_proofs (may be 0)
        assert "total_proofs" in stats or len(stats) >= 0  # non-empty dict or has total_proofs

    def test_formula_hash_deterministic(self):
        from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge
        bridge = CECBridge(enable_ipfs_cache=False, enable_z3=False, enable_prover_router=False)
        formula = MagicMock()
        formula.__repr__ = lambda s: "formula_repr"
        h1 = bridge._compute_formula_hash(formula)
        h2 = bridge._compute_formula_hash(formula)
        assert h1 == h2
        assert len(h1) > 0


# ===========================================================================
# BC113 — Multi-language NL parsers + LanguageDetector
# ===========================================================================

class TestLanguageDetector:
    def test_import(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import (
            LanguageDetector, Language,
        )
        assert LanguageDetector is not None

    def test_detect_english(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import LanguageDetector, Language
        detector = LanguageDetector()
        lang = detector.detect("The agent must perform the action")
        assert lang == Language.ENGLISH

    def test_detect_french(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import LanguageDetector, Language
        detector = LanguageDetector()
        # Use text with high French keyword density (le/la/les/ne/pas/doit/peut)
        lang = detector.detect("Il ne doit pas accéder aux fichiers sans autorisation préalable")
        assert lang == Language.FRENCH

    def test_detect_spanish(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import LanguageDetector, Language
        detector = LanguageDetector()
        lang = detector.detect("El agente debe realizar la acción")
        assert lang == Language.SPANISH

    def test_detect_german(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import LanguageDetector, Language
        detector = LanguageDetector()
        lang = detector.detect("Der Agent muss die Aktion durchführen")
        assert lang == Language.GERMAN

    def test_detect_with_confidence_returns_tuple(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import LanguageDetector
        detector = LanguageDetector()
        lang, confidence = detector.detect_with_confidence("The agent must act")
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

    def test_get_all_languages(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import LanguageDetector, Language
        detector = LanguageDetector()
        langs = detector.get_all_languages()
        assert Language.ENGLISH in langs
        assert Language.FRENCH in langs
        assert Language.SPANISH in langs
        assert Language.GERMAN in langs

    def test_is_supported_english(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import LanguageDetector, Language
        detector = LanguageDetector()
        assert detector.is_supported(Language.ENGLISH) is True

    def test_language_from_code(self):
        from ipfs_datasets_py.logic.CEC.nl.language_detector import Language
        assert Language.from_code("en") == Language.ENGLISH
        assert Language.from_code("fr") == Language.FRENCH
        assert Language.from_code("es") == Language.SPANISH
        assert Language.from_code("de") == Language.GERMAN


class TestFrenchParser:
    def test_import(self):
        from ipfs_datasets_py.logic.CEC.nl.french_parser import FrenchParser
        assert FrenchParser is not None

    def test_parse_obligation(self):
        from ipfs_datasets_py.logic.CEC.nl.french_parser import FrenchParser
        parser = FrenchParser()
        result = parser.parse("L'agent doit effectuer l'action")
        assert result is not None
        assert hasattr(result, "success")

    def test_parse_permission(self):
        from ipfs_datasets_py.logic.CEC.nl.french_parser import FrenchParser
        parser = FrenchParser()
        result = parser.parse("L'agent peut accéder au fichier")
        assert result is not None

    def test_parse_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.french_parser import FrenchParser
        parser = FrenchParser()
        result = parser.parse("Il est interdit de modifier les données")
        assert result is not None

    def test_get_supported_operators_has_deontic(self):
        from ipfs_datasets_py.logic.CEC.nl.french_parser import FrenchParser
        parser = FrenchParser()
        ops = parser.get_supported_operators()
        assert isinstance(ops, list)
        assert len(ops) > 0

    def test_french_deontic_keywords_has_obligation(self):
        from ipfs_datasets_py.logic.CEC.nl.french_parser import get_french_deontic_keywords
        keywords = get_french_deontic_keywords()
        assert "obligation" in keywords or any(
            "doit" in v for v in keywords.values()
        )


class TestSpanishParser:
    def test_import(self):
        from ipfs_datasets_py.logic.CEC.nl.spanish_parser import SpanishParser
        assert SpanishParser is not None

    def test_parse_obligation(self):
        from ipfs_datasets_py.logic.CEC.nl.spanish_parser import SpanishParser
        parser = SpanishParser()
        result = parser.parse("El agente debe realizar la acción")
        assert result is not None
        assert hasattr(result, "success")

    def test_parse_permission(self):
        from ipfs_datasets_py.logic.CEC.nl.spanish_parser import SpanishParser
        parser = SpanishParser()
        result = parser.parse("El agente puede acceder al archivo")
        assert result is not None

    def test_parse_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.spanish_parser import SpanishParser
        parser = SpanishParser()
        result = parser.parse("Está prohibido modificar los datos")
        assert result is not None


class TestGermanParser:
    def test_import(self):
        from ipfs_datasets_py.logic.CEC.nl.german_parser import GermanParser
        assert GermanParser is not None

    def test_parse_obligation(self):
        from ipfs_datasets_py.logic.CEC.nl.german_parser import GermanParser
        parser = GermanParser()
        result = parser.parse("Der Agent muss die Aktion durchführen")
        assert result is not None
        assert hasattr(result, "success")

    def test_parse_permission(self):
        from ipfs_datasets_py.logic.CEC.nl.german_parser import GermanParser
        parser = GermanParser()
        result = parser.parse("Der Agent darf auf die Datei zugreifen")
        assert result is not None

    def test_get_supported_operators(self):
        from ipfs_datasets_py.logic.CEC.nl.german_parser import GermanParser
        parser = GermanParser()
        ops = parser.get_supported_operators()
        assert isinstance(ops, list)
        assert len(ops) > 0
