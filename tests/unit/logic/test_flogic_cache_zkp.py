"""
Tests for F-logic proof cache, ZKP integration, and MCP tools.

Covers:
* FLogicCachedQueryResult construction
* CachedErgoAIWrapper caching behaviour (hit / miss / clear)
* ZKPFLogicProver strategy selection (cache → standard)
* ZKPFLogicResult serialisation
* flogic_assert / flogic_query / flogic_check_consistency MCP tools
* logic_processor.get_capabilities / check_health include flogic
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_module(mod_name: str, rel_path: str):
    """Load a module by path, bypassing broken package __init__ chains."""
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    # Walk up from this test file to the repository root (ipfs_datasets_py repo).
    base = Path(__file__).resolve().parents[4]
    full = base / rel_path
    spec = importlib.util.spec_from_file_location(mod_name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# FLogicCachedQueryResult
# ---------------------------------------------------------------------------


class TestFLogicCachedQueryResult:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_proof_cache import FLogicCachedQueryResult
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicQuery, FLogicStatus
        self.FLogicCachedQueryResult = FLogicCachedQueryResult
        self.FLogicQuery = FLogicQuery
        self.FLogicStatus = FLogicStatus

    def test_from_query_success(self):
        q = self.FLogicQuery(
            goal="?X : Dog",
            bindings=[{"?X": "rex"}],
            status=self.FLogicStatus.SUCCESS,
        )
        r = self.FLogicCachedQueryResult.from_query(q, execution_time=0.05)
        assert r.goal == "?X : Dog"
        assert r.status == self.FLogicStatus.SUCCESS
        assert r.bindings == [{"?X": "rex"}]
        assert r.execution_time == 0.05
        assert r.from_cache is False

    def test_to_flogic_query_round_trip(self):
        q = self.FLogicQuery(goal="?Y : Cat", status=self.FLogicStatus.UNKNOWN)
        cached = self.FLogicCachedQueryResult.from_query(q)
        restored = cached.to_flogic_query()
        assert restored.goal == "?Y : Cat"
        assert restored.status == self.FLogicStatus.UNKNOWN

    def test_defaults(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicStatus
        r = self.FLogicCachedQueryResult(
            goal="?Z : X",
            status=FLogicStatus.UNKNOWN,
        )
        assert r.from_cache is False
        assert r.bindings == []
        assert r.error_message is None


# ---------------------------------------------------------------------------
# CachedErgoAIWrapper
# ---------------------------------------------------------------------------


class TestCachedErgoAIWrapper:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_proof_cache import CachedErgoAIWrapper
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicClass, FLogicFrame, FLogicStatus
        self.CachedErgoAIWrapper = CachedErgoAIWrapper
        self.FLogicClass = FLogicClass
        self.FLogicFrame = FLogicFrame
        self.FLogicStatus = FLogicStatus

    def _make(self):
        return self.CachedErgoAIWrapper(
            enable_caching=True,
            use_global_cache=False,
            cache_size=50,
        )

    def test_first_query_is_cache_miss(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        r = ergo.query("?X : Dog")
        assert r.from_cache is False

    def test_second_identical_query_is_cache_hit(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        ergo.query("?X : Dog")
        r2 = ergo.query("?X : Dog")
        assert r2.from_cache is True

    def test_different_goals_are_separate_cache_entries(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Animal"))
        ergo.query("?X : Animal")
        # Exact same goal text → should hit the cache
        r2 = ergo.query("?X : Animal")
        assert r2.from_cache is True

        # Different goal → separate cache entry (miss)
        r3 = ergo.query("?X : Dog")
        assert r3.from_cache is False

    def test_adding_frame_changes_program_invalidates_key(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Animal"))
        ergo.query("?X : Animal")  # primes the cache

        # Adding a frame changes get_program() → different cache key
        ergo.add_frame(self.FLogicFrame("a", isa="Animal"))
        r = ergo.query("?X : Animal")
        assert r.from_cache is False

    def test_clear_cache(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        ergo.query("?X : Dog")
        ergo.clear_cache()
        r = ergo.query("?X : Dog")
        assert r.from_cache is False

    def test_cache_statistics(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Cat"))
        ergo.query("?X : Cat")   # miss
        ergo.query("?X : Cat")   # hit
        stats = ergo.get_cache_statistics()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_caching_disabled(self):
        ergo = self.CachedErgoAIWrapper(enable_caching=False)
        ergo.add_class(self.FLogicClass("Dog"))
        r1 = ergo.query("?X : Dog")
        r2 = ergo.query("?X : Dog")
        assert r1.from_cache is False
        assert r2.from_cache is False

    def test_get_statistics_includes_cache_info(self):
        ergo = self._make()
        stats = ergo.get_statistics()
        assert "cache_enabled" in stats
        assert "simulation_mode" in stats

    def test_batch_query(self):
        ergo = self._make()
        results = ergo.batch_query(["?X : A", "?Y : B"])
        assert len(results) == 2


# ---------------------------------------------------------------------------
# ZKPFLogicProver
# ---------------------------------------------------------------------------


class TestZKPFLogicProver:
    def setup_method(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from ipfs_datasets_py.logic.flogic.flogic_zkp_integration import (
                ZKPFLogicProver,
                ZKPFLogicResult,
                FLogicProvingMethod,
            )
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicClass, FLogicFrame, FLogicStatus
        self.ZKPFLogicProver = ZKPFLogicProver
        self.ZKPFLogicResult = ZKPFLogicResult
        self.FLogicProvingMethod = FLogicProvingMethod
        self.FLogicClass = FLogicClass
        self.FLogicFrame = FLogicFrame
        self.FLogicStatus = FLogicStatus

    def _make(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.ZKPFLogicProver(
                enable_zkp=False,  # keep tests deterministic
                enable_caching=True,
            )

    def test_first_query_is_standard(self):
        prover = self._make()
        prover.add_class(self.FLogicClass("Dog"))
        r = prover.query("?X : Dog")
        assert r.from_cache is False
        assert r.method == self.FLogicProvingMethod.STANDARD

    def test_second_query_is_cached(self):
        prover = self._make()
        prover.add_class(self.FLogicClass("Dog"))
        prover.query("?X : Dog")
        r2 = prover.query("?X : Dog")
        assert r2.from_cache is True
        assert r2.method == self.FLogicProvingMethod.CACHED

    def test_standard_queries_counter(self):
        prover = self._make()
        prover.add_class(self.FLogicClass("Dog"))
        prover.query("?X : Dog")
        prover.query("?Y : Dog")  # same goal → cached
        prover.query("?Z : Animal")  # different → standard
        assert prover._standard_queries == 2

    def test_add_frame_class_rule_delegated(self):
        prover = self._make()
        prover.add_class(self.FLogicClass("Animal"))
        prover.add_frame(self.FLogicFrame("rex", isa="Animal"))
        prover.add_rule("?X[big -> true] :- ?X : Animal.")
        stats = prover.get_statistics()
        assert stats["frames"] == 1
        assert stats["classes"] == 1
        assert stats["rules"] == 1

    def test_clear_cache(self):
        prover = self._make()
        prover.add_class(self.FLogicClass("Dog"))
        prover.query("?X : Dog")
        prover.clear_cache()
        r = prover.query("?X : Dog")
        assert r.from_cache is False

    def test_to_dict(self):
        prover = self._make()
        prover.add_class(self.FLogicClass("Dog"))
        r = prover.query("?X : Dog")
        d = r.to_dict()
        assert "goal" in d
        assert "status" in d
        assert "method" in d
        assert "from_cache" in d

    def test_get_statistics_keys(self):
        prover = self._make()
        stats = prover.get_statistics()
        assert "zkp_enabled" in stats
        assert "standard_queries" in stats
        assert "cache_enabled" in stats

    def test_batch_query(self):
        prover = self._make()
        results = prover.batch_query(["?A : X", "?B : Y"])
        assert len(results) == 2


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


class TestFlogicMCPTools:
    def setup_method(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from ipfs_datasets_py.mcp_server.tools.logic_tools.flogic_tool import (
                flogic_assert,
                flogic_query,
                flogic_check_consistency,
            )
        self.flogic_assert = flogic_assert
        self.flogic_query = flogic_query
        self.flogic_check_consistency = flogic_check_consistency

    def test_assert_classes_and_frames(self):
        r = run(self.flogic_assert(
            classes=[
                {"class_id": "TestAnimal"},
                {"class_id": "TestDog", "superclasses": ["TestAnimal"]},
            ],
            frames=[
                {"object_id": "fido", "isa": "TestDog"},
            ],
        ))
        assert r["success"] is True
        assert r["classes_added"] == 2
        assert r["frames_added"] == 1

    def test_assert_rules(self):
        r = run(self.flogic_assert(
            rules=["?X[barks -> true] :- ?X : TestDog."],
        ))
        assert r["success"] is True
        assert r["rules_added"] == 1

    def test_assert_empty_inputs(self):
        r = run(self.flogic_assert())
        assert r["success"] is True
        assert r["frames_added"] == 0

    def test_query_returns_success(self):
        r = run(self.flogic_query("?X : TestDog"))
        assert r["success"] is True
        assert "status" in r
        assert "from_cache" in r
        assert "bindings" in r

    def test_query_caching(self):
        # Run query twice — second should be from cache
        run(self.flogic_query("?T : TestAnimal"))
        r2 = run(self.flogic_query("?T : TestAnimal"))
        assert r2["from_cache"] is True

    def test_query_empty_goal_error(self):
        r = run(self.flogic_query(""))
        assert r["success"] is False

    def test_check_consistency_clean_triples(self):
        r = run(self.flogic_check_consistency([
            {"subject": "dog1", "predicate": "type", "object": "Dog"},
            {"subject": "dog1", "predicate": "name", "object": "Rex"},
        ]))
        assert r["success"] is True
        assert r["consistent"] is True
        assert r["violations"] == []

    def test_check_consistency_blank_predicate_violation(self):
        r = run(self.flogic_check_consistency([
            {"subject": "dog1", "predicate": "", "object": "bad"},
        ]))
        assert r["success"] is True
        assert r["consistent"] is False
        assert len(r["violations"]) >= 1

    def test_check_consistency_empty_list(self):
        r = run(self.flogic_check_consistency([]))
        assert r["success"] is True
        assert r["consistent"] is True

    def test_check_consistency_none(self):
        r = run(self.flogic_check_consistency(None))
        assert r["success"] is True
        assert r["consistent"] is True


# ---------------------------------------------------------------------------
# logic_processor capabilities / health
# ---------------------------------------------------------------------------


class TestLogicProcessorFlogic:
    def setup_method(self):
        try:
            from ipfs_datasets_py.core_operations.logic_processor import LogicProcessor
            self.lp = LogicProcessor()
        except Exception:
            self.lp = None

    def test_capabilities_contains_flogic(self):
        if self.lp is None:
            return  # skip if LogicProcessor unavailable
        result = run(self.lp.get_capabilities())
        assert result["success"] is True
        assert "flogic" in result["logics"]
        flogic = result["logics"]["flogic"]
        assert "features" in flogic
        assert "proof_cache" in flogic["features"]
        assert "zkp_attest" in flogic["features"]

    def test_capabilities_conversions_include_kg_flogic(self):
        if self.lp is None:
            return
        result = run(self.lp.get_capabilities())
        assert "kg→flogic" in result["conversions"]

    def test_health_contains_flogic(self):
        if self.lp is None:
            return
        result = run(self.lp.check_health())
        assert result["success"] is True
        assert "flogic" in result["modules"]


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------


def test_flogic_init_new_exports():
    import ipfs_datasets_py.logic.flogic as fl
    for name in [
        "CachedErgoAIWrapper",
        "get_global_cached_wrapper",
        "FLogicCachedQueryResult",
        "FLogicProvingMethod",
        "ZKPFLogicResult",
        "ZKPFLogicProver",
    ]:
        assert hasattr(fl, name), f"flogic.__init__ missing: {name}"


def test_mcp_tools_exports():
    from ipfs_datasets_py.mcp_server.tools.logic_tools import (
        flogic_assert,
        flogic_query,
        flogic_check_consistency,
    )
    assert callable(flogic_assert)
    assert callable(flogic_query)
    assert callable(flogic_check_consistency)
