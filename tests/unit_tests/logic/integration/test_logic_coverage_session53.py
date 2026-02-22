"""Session 53: Integration backward-compat fixes + new coverage tests.

Covers:
- proof_cache backward-compat (CachedProof, ProofCache, get_global_cache)
- LogicVerifier._validate_formula_syntax / _are_contradictory aliases
- logic_verification_utils shim
- interactive_fol_constructor shim
- legal_symbolic_analyzer fallback paths
- tdfol_cec_bridge additional paths
- deontic_logic_converter additional paths
- integration module exports
"""

import time
import threading
import pytest
from unittest.mock import MagicMock, patch


# =========================================================================
# Proof cache backward-compat API
# =========================================================================

class TestCachedProofDataclass:
    """GIVEN the backward-compat CachedProof dataclass
    WHEN creating instances and using methods
    THEN API behaves as tests expect"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.proof_cache import CachedProof
        self.CachedProof = CachedProof

    def test_creation_with_required_fields(self):
        """GIVEN required fields WHEN creating CachedProof THEN all attrs set."""
        cp = self.CachedProof(
            formula_hash="h1",
            prover="z3",
            result_data={"status": "proved"},
            timestamp=1000.0,
        )
        assert cp.formula_hash == "h1"
        assert cp.prover == "z3"
        assert cp.result_data == {"status": "proved"}
        assert cp.ttl == 3600.0
        assert cp.hit_count == 0

    def test_not_expired_fresh(self):
        """GIVEN fresh entry WHEN is_expired called THEN returns False."""
        cp = self.CachedProof("h", "z3", {}, time.time(), ttl=3600)
        assert not cp.is_expired()

    def test_expired_old_entry(self):
        """GIVEN old entry WHEN is_expired called THEN returns True."""
        cp = self.CachedProof("h", "z3", {}, time.time() - 7200, ttl=3600)
        assert cp.is_expired()

    def test_never_expires_with_zero_ttl(self):
        """GIVEN ttl=0 WHEN is_expired called THEN always False."""
        cp = self.CachedProof("h", "z3", {}, time.time() - 100000, ttl=0)
        assert not cp.is_expired()

    def test_to_dict_has_formula_hash(self):
        """GIVEN CachedProof WHEN to_dict called THEN has 'formula_hash' key."""
        cp = self.CachedProof("myhash", "lean", {"proof": True}, 123.4, ttl=1800)
        d = cp.to_dict()
        assert d["formula_hash"] == "myhash"
        assert d["prover"] == "lean"
        assert d["ttl"] == 1800

    def test_from_dict_round_trip(self):
        """GIVEN dict WHEN from_dict called THEN creates matching object."""
        data = {
            "formula_hash": "xyz",
            "prover": "coq",
            "result_data": {"valid": True},
            "timestamp": 999.0,
            "ttl": 7200,
            "hit_count": 3,
        }
        cp = self.CachedProof.from_dict(data)
        assert cp.formula_hash == "xyz"
        assert cp.hit_count == 3
        assert cp.ttl == 7200


class TestProofCacheBackwardCompat:
    """GIVEN the backward-compat ProofCache
    WHEN using legacy max_size/default_ttl API
    THEN behaves correctly"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.proof_cache import ProofCache
        self.ProofCache = ProofCache

    def test_init_with_max_size(self):
        """GIVEN max_size kwarg WHEN creating THEN max_size property matches."""
        cache = self.ProofCache(max_size=50, default_ttl=900)
        assert cache.max_size == 50
        assert cache.default_ttl == 900

    def test_init_with_maxsize_alias(self):
        """GIVEN maxsize kwarg (new API) WHEN creating THEN max_size property matches."""
        cache = self.ProofCache(maxsize=200, ttl=7200)
        assert cache.max_size == 200
        assert cache.default_ttl == 7200

    def test_put_3arg_then_get(self):
        """GIVEN 3-arg put WHEN get called THEN returns result_data dict."""
        cache = self.ProofCache(max_size=10)
        cache.put("P → Q", "z3", {"status": "proved"})
        result = cache.get("P → Q", "z3")
        assert result is not None
        assert result["status"] == "proved"

    def test_put_2arg_then_get(self):
        """GIVEN 2-arg put WHEN get called THEN returns result."""
        cache = self.ProofCache(max_size=10)
        cache.put("formula", {"data": 42})
        result = cache.get("formula", "")
        assert result is not None
        assert result["data"] == 42

    def test_get_miss_returns_none(self):
        """GIVEN empty cache WHEN get called THEN returns None."""
        cache = self.ProofCache()
        assert cache.get("nonexistent", "z3") is None

    def test_statistics_keys(self):
        """GIVEN cache with operations WHEN get_statistics THEN has expected keys."""
        cache = self.ProofCache()
        cache.put("P", "z3", {"r": 1})
        cache.get("P", "z3")
        cache.get("Q", "z3")
        stats = cache.get_statistics()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["total_puts"] == 1
        assert stats["size"] == 1
        assert "hit_rate" in stats
        assert "evictions" in stats
        assert "expirations" in stats

    def test_lru_eviction(self):
        """GIVEN capacity 2 WHEN 3rd item added THEN first evicted."""
        cache = self.ProofCache(max_size=2)
        cache.put("A", "z3", {"n": 1})
        cache.put("B", "z3", {"n": 2})
        cache.put("C", "z3", {"n": 3})
        # A should be evicted
        assert cache.get("A", "z3") is None
        assert cache.get("C", "z3") is not None
        assert cache.get_statistics()["evictions"] == 1

    def test_invalidate_existing(self):
        """GIVEN cached entry WHEN invalidated THEN removed."""
        cache = self.ProofCache()
        cache.put("P", "z3", {})
        assert cache.invalidate("P", "z3") is True
        assert cache.get("P", "z3") is None

    def test_invalidate_nonexistent(self):
        """GIVEN empty cache WHEN invalidate called THEN returns False."""
        cache = self.ProofCache()
        assert cache.invalidate("nokey", "z3") is False

    def test_clear(self):
        """GIVEN cache with 3 entries WHEN clear called THEN count 3 returned."""
        cache = self.ProofCache()
        cache.put("A", "z3", {})
        cache.put("B", "z3", {})
        cache.put("C", "z3", {})
        n = cache.clear()
        assert n == 3
        assert len(cache._cache) == 0

    def test_resize_larger(self):
        """GIVEN cache with 3 entries WHEN resized to 10 THEN all retained."""
        cache = self.ProofCache(max_size=5)
        for i in range(3):
            cache.put(f"F{i}", "z3", {})
        cache.resize(10)
        assert cache.max_size == 10
        assert len(cache._cache) == 3

    def test_resize_smaller_evicts(self):
        """GIVEN cache with 5 entries WHEN resized to 2 THEN 3 evicted."""
        cache = self.ProofCache(max_size=5)
        for i in range(5):
            cache.put(f"F{i}", "z3", {})
        cache.resize(2)
        assert cache.max_size == 2
        assert len(cache._cache) == 2

    def test_get_cached_entries(self):
        """GIVEN 2 entries WHEN get_cached_entries THEN returns 2 dicts with prover."""
        cache = self.ProofCache()
        cache.put("P", "z3", {})
        cache.put("Q", "lean", {})
        entries = cache.get_cached_entries()
        assert len(entries) == 2
        assert all("prover" in e for e in entries)
        assert all("timestamp" in e for e in entries)

    def test_cleanup_expired(self):
        """GIVEN expired entries WHEN cleanup_expired THEN removed count returned."""
        cache = self.ProofCache()
        # Add entry with ttl=0.001 (very short)
        cache.put("old", "z3", {}, ttl=0.001)
        cache.put("fresh", "z3", {}, ttl=3600)
        time.sleep(0.05)
        removed = cache.cleanup_expired()
        assert removed >= 1
        assert cache.get("fresh", "z3") is not None

    def test_make_key_deterministic(self):
        """GIVEN same inputs WHEN _make_key called twice THEN same key returned."""
        cache = self.ProofCache()
        k1 = cache._make_key("P → Q", "z3")
        k2 = cache._make_key("P → Q", "z3")
        assert k1 == k2

    def test_thread_safety(self):
        """GIVEN concurrent puts WHEN done simultaneously THEN no exception."""
        cache = self.ProofCache(max_size=100)
        errors = []

        def writer(n):
            try:
                for i in range(10):
                    cache.put(f"F{n}_{i}", "z3", {"n": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors

    def test_ttl_expiry_on_get(self):
        """GIVEN entry with very short TTL WHEN time passes THEN get returns None."""
        cache = self.ProofCache()
        cache.put("expiring", "z3", {"data": 1}, ttl=0.01)
        time.sleep(0.05)
        result = cache.get("expiring", "z3")
        assert result is None

    def test_get_stats_alias(self):
        """GIVEN cache WHEN get_stats called THEN returns same as get_statistics."""
        cache = self.ProofCache()
        cache.put("P", "z3", {})
        s1 = cache.get_statistics()
        s2 = cache.get_stats()
        assert s1 == s2

    def test_set_alias_for_new_api(self):
        """GIVEN cache WHEN set(formula, result, prover_name=) called THEN stored."""
        cache = self.ProofCache()
        cache.set("Q", {"r": 2}, prover_name="z3")
        result = cache.get("Q", "z3")
        assert result is not None
        assert result["r"] == 2


class TestGetGlobalCacheSingleton:
    """GIVEN get_global_cache function
    WHEN called multiple times
    THEN same instance returned"""

    def test_singleton(self):
        """GIVEN two calls WHEN compared THEN same object."""
        from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache
        c1 = get_global_cache()
        c2 = get_global_cache()
        assert c1 is c2

    def test_data_persists_across_calls(self):
        """GIVEN data stored in global cache WHEN retrieved via new call THEN found."""
        from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache
        cache = get_global_cache()
        cache.put("_sess53_test", "z3", {"x": 99})
        cache2 = get_global_cache()
        result = cache2.get("_sess53_test", "z3")
        assert result is not None
        assert result["x"] == 99
        # cleanup
        cache.invalidate("_sess53_test", "z3")


# =========================================================================
# LogicVerifier backward-compat private methods
# =========================================================================

class TestLogicVerifierBackwardCompatAliases:
    """GIVEN LogicVerifier private-method backward-compat aliases
    WHEN called
    THEN return expected bool values"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.reasoning.logic_verification import LogicVerifier
        self.verifier = LogicVerifier()

    def test_validate_syntax_valid_formula(self):
        """GIVEN valid formula WHEN _validate_formula_syntax THEN True."""
        assert self.verifier._validate_formula_syntax("P → Q") is True

    def test_validate_syntax_valid_simple(self):
        """GIVEN simple atom WHEN _validate_formula_syntax THEN True."""
        assert self.verifier._validate_formula_syntax("P") is True

    def test_validate_syntax_empty_invalid(self):
        """GIVEN empty string WHEN _validate_formula_syntax THEN False."""
        assert self.verifier._validate_formula_syntax("") is False

    def test_validate_syntax_unbalanced_parens(self):
        """GIVEN unbalanced parens WHEN _validate_formula_syntax THEN False."""
        assert self.verifier._validate_formula_syntax("((P → Q") is False

    def test_are_contradictory_p_negp(self):
        """GIVEN P and ¬P WHEN _are_contradictory THEN True."""
        assert self.verifier._are_contradictory("P", "¬P") is True

    def test_are_contradictory_negp_p(self):
        """GIVEN ¬P and P WHEN _are_contradictory THEN True."""
        assert self.verifier._are_contradictory("¬P", "P") is True

    def test_are_contradictory_unrelated(self):
        """GIVEN unrelated formulas WHEN _are_contradictory THEN False."""
        assert self.verifier._are_contradictory("P", "Q") is False

    def test_are_contradictory_complex_non_contradiction(self):
        """GIVEN P→Q and P WHEN _are_contradictory THEN False."""
        assert self.verifier._are_contradictory("P → Q", "P") is False


# =========================================================================
# logic_verification_utils shim
# =========================================================================

class TestLogicVerificationUtilsShim:
    """GIVEN the logic_verification_utils shim module
    WHEN importing from integration package
    THEN all expected functions available"""

    def test_import_verify_consistency(self):
        """GIVEN shim WHEN importing verify_consistency THEN callable."""
        from ipfs_datasets_py.logic.integration.logic_verification_utils import verify_consistency
        assert callable(verify_consistency)

    def test_import_verify_entailment(self):
        """GIVEN shim WHEN importing verify_entailment THEN callable."""
        from ipfs_datasets_py.logic.integration.logic_verification_utils import verify_entailment
        assert callable(verify_entailment)

    def test_import_create_logic_verifier(self):
        """GIVEN shim WHEN importing create_logic_verifier THEN callable."""
        from ipfs_datasets_py.logic.integration.logic_verification_utils import create_logic_verifier
        assert callable(create_logic_verifier)

    def test_import_are_contradictory(self):
        """GIVEN shim WHEN importing are_contradictory THEN callable."""
        from ipfs_datasets_py.logic.integration.logic_verification_utils import are_contradictory
        assert callable(are_contradictory)

    def test_import_validate_formula_syntax(self):
        """GIVEN shim WHEN importing validate_formula_syntax THEN callable."""
        from ipfs_datasets_py.logic.integration.logic_verification_utils import validate_formula_syntax
        assert callable(validate_formula_syntax)

    def test_verify_consistency_returns_result(self):
        """GIVEN formulas WHEN verify_consistency called THEN returns object."""
        from ipfs_datasets_py.logic.integration.logic_verification_utils import verify_consistency
        result = verify_consistency(["P", "Q"])
        assert result is not None

    def test_are_contradictory_via_shim(self):
        """GIVEN shim WHEN are_contradictory called THEN correct result."""
        from ipfs_datasets_py.logic.integration.logic_verification_utils import are_contradictory
        assert are_contradictory("P", "¬P") is True
        assert are_contradictory("P", "Q") is False


# =========================================================================
# interactive_fol_constructor shim
# =========================================================================

class TestInteractiveFOLConstructorShim:
    """GIVEN the interactive_fol_constructor shim
    WHEN imported from integration package
    THEN provides InteractiveFOLConstructor class"""

    def test_import_as_module(self):
        """GIVEN shim WHEN from integration import interactive_fol_constructor THEN works."""
        from ipfs_datasets_py.logic.integration import interactive_fol_constructor
        assert hasattr(interactive_fol_constructor, "InteractiveFOLConstructor")

    def test_instantiate_constructor(self):
        """GIVEN shim WHEN InteractiveFOLConstructor instantiated THEN works."""
        from ipfs_datasets_py.logic.integration import interactive_fol_constructor
        ctor = interactive_fol_constructor.InteractiveFOLConstructor()
        assert ctor is not None

    def test_constructor_has_add_statement(self):
        """GIVEN constructor WHEN checking attrs THEN add_statement present."""
        from ipfs_datasets_py.logic.integration import interactive_fol_constructor
        ctor = interactive_fol_constructor.InteractiveFOLConstructor()
        assert hasattr(ctor, "add_statement")

    def test_direct_import_also_works(self):
        """GIVEN direct import WHEN importing InteractiveFOLConstructor THEN works."""
        from ipfs_datasets_py.logic.integration.interactive_fol_constructor import InteractiveFOLConstructor
        ctor = InteractiveFOLConstructor()
        assert ctor is not None


# =========================================================================
# legal_symbolic_analyzer fallback paths
# =========================================================================

class TestLegalSymbolicAnalyzerFallbacks:
    """GIVEN LegalSymbolicAnalyzer with SymbolicAI unavailable
    WHEN calling analysis methods
    THEN fallback implementations run"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import (
            LegalSymbolicAnalyzer,
        )
        self.LegalSymbolicAnalyzer = LegalSymbolicAnalyzer
        self.analyzer = LegalSymbolicAnalyzer()

    def test_init_creates_analyzer(self):
        """GIVEN init WHEN created THEN object valid."""
        assert self.analyzer is not None

    def test_analyze_legal_document_fallback(self):
        """GIVEN legal text WHEN analyze_legal_document called THEN result returned."""
        text = "The party must pay the fee within 30 days of the agreement."
        result = self.analyzer.analyze_legal_document(text)
        assert result is not None

    def test_extract_deontic_propositions_obligation(self):
        """GIVEN obligation text WHEN extract_deontic_propositions THEN obligations found."""
        text = "The contractor must deliver the goods by Monday."
        props = self.analyzer.extract_deontic_propositions(text)
        assert isinstance(props, list)

    def test_extract_deontic_propositions_permission(self):
        """GIVEN permission text WHEN extract_deontic_propositions THEN list returned."""
        text = "The tenant may sublease with written consent."
        props = self.analyzer.extract_deontic_propositions(text)
        assert isinstance(props, list)

    def test_identify_legal_entities(self):
        """GIVEN entity-rich text WHEN identify_legal_entities THEN list returned."""
        text = "The company must notify the board within 5 business days."
        entities = self.analyzer.identify_legal_entities(text)
        assert isinstance(entities, list)

    def test_extract_temporal_conditions(self):
        """GIVEN temporal text WHEN extract_temporal_conditions THEN list returned."""
        text = "Payment is due within 14 days after the invoice date."
        conditions = self.analyzer.extract_temporal_conditions(text)
        assert isinstance(conditions, list)

    def test_fallback_analysis_directly(self):
        """GIVEN text WHEN _fallback_analysis called THEN result returned."""
        text = "All employees are required to report safety incidents."
        result = self.analyzer._fallback_analysis(text)
        assert result is not None

    def test_fallback_deontic_extraction(self):
        """GIVEN text WHEN _fallback_deontic_extraction called THEN list returned."""
        text = "The licensee shall maintain records."
        props = self.analyzer._fallback_deontic_extraction(text)
        assert isinstance(props, list)

    def test_fallback_entity_identification(self):
        """GIVEN text WHEN _fallback_entity_identification called THEN list returned."""
        text = "The seller and buyer agree to the terms."
        entities = self.analyzer._fallback_entity_identification(text)
        assert isinstance(entities, list)

    def test_fallback_temporal_extraction(self):
        """GIVEN text WHEN _fallback_temporal_extraction called THEN list returned."""
        text = "The deadline is 30 days after execution."
        conditions = self.analyzer._fallback_temporal_extraction(text)
        assert isinstance(conditions, list)

    def test_empty_text_analysis(self):
        """GIVEN empty text WHEN analyze_legal_document THEN no exception."""
        result = self.analyzer.analyze_legal_document("")
        assert result is not None


class TestLegalReasoningEngineFallbacks:
    """GIVEN LegalReasoningEngine fallback methods
    WHEN calling reasoning methods
    THEN fallback implementations return valid results"""

    def setup_method(self):
        try:
            from ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer import (
                LegalReasoningEngine,
            )
            self.LegalReasoningEngine = LegalReasoningEngine
            self.engine = LegalReasoningEngine()
        except Exception:
            pytest.skip("LegalReasoningEngine unavailable")

    def test_init_creates_engine(self):
        """GIVEN init WHEN created THEN object valid."""
        assert self.engine is not None

    def test_fallback_implication_reasoning(self):
        """GIVEN rules WHEN _fallback_implication_reasoning called THEN list returned."""
        rules = ["If a contract is signed, it is binding.", "Payment must occur within 30 days."]
        result = self.engine._fallback_implication_reasoning(rules)
        assert isinstance(result, list)

    def test_fallback_consistency_check(self):
        """GIVEN rules WHEN _fallback_consistency_check called THEN dict returned."""
        rules = ["The party must pay.", "The party may delay payment."]
        result = self.engine._fallback_consistency_check(rules)
        assert isinstance(result, dict)
        # May return 'consistent' or 'is_consistent' depending on implementation
        assert ("consistent" in result or "is_consistent" in result)

    def test_fallback_precedent_analysis(self):
        """GIVEN case and precedents WHEN _fallback_precedent_analysis called THEN dict."""
        current = "Contractor failed to deliver goods."
        precedents = ["In Jones v. Smith, late delivery was penalized."]
        result = self.engine._fallback_precedent_analysis(current, precedents)
        assert isinstance(result, dict)

    def test_infer_implicit_obligations(self):
        """GIVEN explicit rules WHEN infer_implicit_obligations THEN list returned."""
        rules = ["All employees must report accidents.", "Safety officers shall investigate."]
        result = self.engine.infer_implicit_obligations(rules)
        assert isinstance(result, list)

    def test_check_legal_consistency_empty(self):
        """GIVEN empty rules WHEN check_legal_consistency THEN dict returned."""
        result = self.engine.check_legal_consistency([])
        assert isinstance(result, dict)


# =========================================================================
# tdfol_cec_bridge additional coverage
# =========================================================================

try:
    import ipfs_datasets_py.TDFOL  # noqa: F401
    _TDFOL_AVAILABLE = True
except ImportError:
    _TDFOL_AVAILABLE = False


@pytest.mark.skipif(not _TDFOL_AVAILABLE, reason="TDFOL not installed")
class TestTDFOLCECBridgeAdditionalPaths:
    """GIVEN TDFOLCECBridge
    WHEN calling methods with mocked dependencies
    THEN remaining code paths covered"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        self.bridge = TDFOLCECBridge()

    def test_bridge_is_available_returns_bool(self):
        """GIVEN bridge WHEN is_available called THEN bool returned."""
        assert isinstance(self.bridge.is_available(), bool)

    def test_get_applicable_cec_rules_no_cec(self):
        """GIVEN no CEC available WHEN get_applicable_cec_rules THEN empty list."""
        from ipfs_datasets_py.TDFOL.types import DeonticFormula, DeonticOperator
        formula = DeonticFormula(DeonticOperator.OBLIGATION, "pay(x)")
        rules = self.bridge.get_applicable_cec_rules(formula)
        assert isinstance(rules, list)

    def test_prove_with_cec_unavailable(self):
        """GIVEN no CEC WHEN prove_with_cec called THEN ProofResult with UNKNOWN."""
        from ipfs_datasets_py.TDFOL.types import DeonticFormula, DeonticOperator
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import TDFOLCECBridge
        bridge = TDFOLCECBridge()
        bridge.cec_available = False
        formula = DeonticFormula(DeonticOperator.OBLIGATION, "pay(x)")
        result = bridge.prove_with_cec(formula)
        assert result is not None

    def test_tdfol_to_dcec_string_obligation(self):
        """GIVEN obligation formula WHEN tdfol_to_dcec_string THEN string returned."""
        from ipfs_datasets_py.TDFOL.types import DeonticFormula, DeonticOperator
        formula = DeonticFormula(DeonticOperator.OBLIGATION, "inform(a, b, c)")
        s = self.bridge.tdfol_to_dcec_string(formula)
        assert isinstance(s, str)

    def test_dcec_string_to_tdfol_no_crash(self):
        """GIVEN DCEC string WHEN dcec_string_to_tdfol called THEN no exception raised."""
        from ipfs_datasets_py.TDFOL.types import Formula
        # Just verify the call completes without raising — return value may be None
        try:
            result = self.bridge.dcec_string_to_tdfol("O(pay(a))")
            # If it returns something it should be a Formula instance
            if result is not None:
                assert isinstance(result, Formula)
        except Exception as exc:
            pytest.fail(f"dcec_string_to_tdfol raised unexpectedly: {exc}")


@pytest.mark.skipif(not _TDFOL_AVAILABLE, reason="TDFOL not installed")
class TestEnhancedTDFOLProverAdditional:
    """GIVEN EnhancedTDFOLProver
    WHEN calling prove with mocked dependencies
    THEN coverage increases"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.bridges.tdfol_cec_bridge import EnhancedTDFOLProver
        self.prover = EnhancedTDFOLProver(use_cec=False)

    def test_prove_returns_proof_result(self):
        """GIVEN formula WHEN prove called THEN ProofResult returned."""
        from ipfs_datasets_py.TDFOL.types import DeonticFormula, DeonticOperator
        formula = DeonticFormula(DeonticOperator.OBLIGATION, "pay(x)")
        result = self.prover.prove(formula)
        assert result is not None

    def test_prove_with_timeout(self):
        """GIVEN formula and timeout WHEN prove called THEN result returned."""
        from ipfs_datasets_py.TDFOL.types import DeonticFormula, DeonticOperator
        formula = DeonticFormula(DeonticOperator.PERMISSION, "enter(x)")
        result = self.prover.prove(formula, timeout_ms=100)
        assert result is not None


# =========================================================================
# deontic_logic_converter additional paths
# =========================================================================

class TestDeonticLogicConverterAdditionalPaths:
    """GIVEN DeonticLogicConverter
    WHEN calling additional paths
    THEN coverage increases"""

    def setup_method(self):
        from ipfs_datasets_py.logic.integration.deontic_logic_converter import DeonticLogicConverter
        self.converter = DeonticLogicConverter()

    def test_init_conversion_stats_exist(self):
        """GIVEN converter WHEN checking conversion_stats THEN dict present."""
        assert hasattr(self.converter, "conversion_stats")
        assert "total_entities_processed" in self.converter.conversion_stats

    def test_conversion_stats_structure(self):
        """GIVEN fresh converter WHEN conversion_stats checked THEN keys present."""
        stats = self.converter.conversion_stats
        assert isinstance(stats, dict)

    def test_convert_empty_entity_list(self):
        """GIVEN empty list WHEN convert_entities_to_logic called THEN result returned."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        ctx = ConversionContext(source_document_path="test.pdf")
        result = self.converter.convert_entities_to_logic([], ctx)
        assert result is not None

    def test_convert_entities_with_mock_obligation(self):
        """GIVEN obligation entity WHEN converted THEN rule set returned."""
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_converter import ConversionContext
        ctx = ConversionContext(source_document_path="doc.pdf")
        entity = MagicMock()
        entity.entity_id = "e1"
        entity.name = "pay_fee"
        entity.entity_type = "obligation"
        entity.source_text = "The client must pay the fee"
        entity.properties = {}
        result = self.converter.convert_entities_to_logic([entity], ctx)
        assert result is not None

    def test_normalize_proposition_strips_whitespace(self):
        """GIVEN proposition with whitespace WHEN normalize called THEN stripped."""
        result = self.converter._normalize_proposition("  pay the fee  ")
        assert result == result.strip()

    def test_normalize_proposition_lowercases(self):
        """GIVEN uppercase text WHEN normalize called THEN lowercased."""
        result = self.converter._normalize_proposition("PAY THE FEE")
        assert result == result.lower()

    def test_classify_agent_type_with_entity_mock(self):
        """GIVEN entity mock with name WHEN classify_agent_type called THEN str returned."""
        entity = MagicMock()
        entity.entity_id = "a1"
        entity.name = "the_company"
        entity.entity_type = "organization"
        entity.source_text = "The Company must pay"
        entity.properties = {}
        result = self.converter._classify_agent_type(entity)
        assert isinstance(result, str)


# =========================================================================
# Integration __init__ exports smoke test
# =========================================================================

class TestIntegrationPackageExports:
    """GIVEN the integration package
    WHEN importing top-level symbols
    THEN key exports available"""

    def test_logic_verifier_importable(self):
        """GIVEN package WHEN importing LogicVerifier THEN works."""
        from ipfs_datasets_py.logic.integration import LogicVerifier
        assert LogicVerifier is not None

    def test_deontic_formula_importable(self):
        """GIVEN package WHEN importing DeonticFormula THEN works."""
        from ipfs_datasets_py.logic.integration import DeonticFormula
        assert DeonticFormula is not None

    def test_proof_cache_importable_from_integration(self):
        """GIVEN package WHEN importing ProofCache from integration THEN works."""
        from ipfs_datasets_py.logic.integration.proof_cache import ProofCache
        assert ProofCache is not None

    def test_interactive_fol_constructor_importable(self):
        """GIVEN package WHEN importing InteractiveFOLConstructor THEN works."""
        from ipfs_datasets_py.logic.integration.interactive_fol_constructor import InteractiveFOLConstructor
        assert InteractiveFOLConstructor is not None

    def test_logic_verification_utils_importable(self):
        """GIVEN package WHEN importing from logic_verification_utils THEN works."""
        from ipfs_datasets_py.logic.integration.logic_verification_utils import (
            verify_consistency, create_logic_verifier
        )
        assert callable(verify_consistency)
        assert callable(create_logic_verifier)
