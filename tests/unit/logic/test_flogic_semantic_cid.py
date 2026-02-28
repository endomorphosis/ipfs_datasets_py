"""
Tests for:
- SemanticNormalizer (dict-only mode)
- IPFS CID-based cache key in CachedErgoAIWrapper
- Synonym-sharing in the proof cache
- flogic_normalize_term MCP tool
"""

from __future__ import annotations

import asyncio


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# SemanticNormalizer
# ---------------------------------------------------------------------------


class TestSemanticNormalizer:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.semantic_normalizer import (
            SemanticNormalizer,
            DEFAULT_SYNONYM_MAP,
            get_global_normalizer,
            _SYMAI_AVAILABLE,
        )
        self.SemanticNormalizer = SemanticNormalizer
        self.DEFAULT_SYNONYM_MAP = DEFAULT_SYNONYM_MAP
        self.get_global_normalizer = get_global_normalizer
        self._SYMAI_AVAILABLE = _SYMAI_AVAILABLE

    def _make(self, **kwargs):
        return self.SemanticNormalizer(use_symai=False, **kwargs)

    # term normalization
    def test_term_in_default_map(self):
        n = self._make()
        assert n.normalize_term("canine") == "dog"

    def test_term_in_default_map_case_insensitive(self):
        n = self._make()
        assert n.normalize_term("Canine") == "dog"
        assert n.normalize_term("CANINE") == "dog"

    def test_unknown_term_lowercased(self):
        n = self._make()
        assert n.normalize_term("Xenomorph") == "xenomorph"

    def test_already_canonical(self):
        n = self._make()
        assert n.normalize_term("dog") == "dog"

    def test_add_synonym(self):
        n = self._make()
        n.add_synonym("wolfhound", "dog")
        assert n.normalize_term("wolfhound") == "dog"

    def test_caller_supplied_map(self):
        n = self._make(synonym_map={"kitten": "cat"})
        assert n.normalize_term("kitten") == "cat"

    # goal normalization
    def test_normalize_goal_replaces_synonym(self):
        n = self._make()
        assert n.normalize_goal("?X : Canine") == "?X : dog"

    def test_normalize_goal_single_letter_variable_preserved(self):
        n = self._make()
        # ?X is a variable, X alone should be preserved as single-letter uppercase
        result = n.normalize_goal("?X : Dog")
        assert "?X" in result or "X" in result  # variable part not removed

    def test_normalize_goal_quoted_literal_not_touched(self):
        n = self._make()
        result = n.normalize_goal('?X[name -> "Canine"]')
        # "Canine" inside quotes should NOT be replaced
        assert '"Canine"' in result

    def test_normalize_goal_idempotent(self):
        n = self._make()
        g1 = n.normalize_goal("?X : Canine")
        g2 = n.normalize_goal(g1)
        assert g1 == g2

    # canonical form for caching
    def test_synonym_goals_produce_same_normalized_form(self):
        n = self._make()
        g1 = n.normalize_goal("?X : Dog")
        g2 = n.normalize_goal("?X : Canine")
        # Both should have the same type token ("dog")
        assert g1 == g2, f"{g1!r} != {g2!r}"

    # get_map_snapshot
    def test_get_map_snapshot_contains_defaults(self):
        n = self._make()
        snap = n.get_map_snapshot()
        assert "canine" in snap
        assert snap["canine"] == "dog"

    # singleton
    def test_get_global_normalizer_singleton(self):
        n1 = self.get_global_normalizer(use_symai=False)
        n2 = self.get_global_normalizer()
        assert n1 is n2

    def test_symai_flag(self):
        n = self._make()
        assert n.symai_available is False

    # legal/deontic synonyms
    def test_deontic_synonyms(self):
        n = self._make()
        assert n.normalize_term("prohibited") == "forbidden"
        assert n.normalize_term("permitted") == "allowed"
        assert n.normalize_term("obligatory") == "required"


# ---------------------------------------------------------------------------
# IPFS CID cache keys
# ---------------------------------------------------------------------------


class TestCIDCacheKey:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_proof_cache import (
            CachedErgoAIWrapper,
            _HAVE_CID,
        )
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicClass
        self.CachedErgoAIWrapper = CachedErgoAIWrapper
        self.FLogicClass = FLogicClass
        self._HAVE_CID = _HAVE_CID

    def _make(self):
        return self.CachedErgoAIWrapper(
            enable_caching=True,
            use_global_cache=False,
            cache_size=50,
            enable_normalization=False,
        )

    def test_cid_backend_reported_in_statistics(self):
        ergo = self._make()
        stats = ergo.get_cache_statistics()
        assert "cid_backend" in stats
        # Either ipfs_multiformats or sha256_fallback
        assert stats["cid_backend"] in ("ipfs_multiformats", "sha256_fallback")

    def test_cache_cid_populated_on_miss(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        r = ergo.query("?X : Dog")
        assert r.cache_cid is not None
        assert len(r.cache_cid) > 10  # non-trivial CID

    def test_different_goals_different_cids(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Animal"))
        r1 = ergo.query("?X : Animal")
        r2 = ergo.query("?Y : Cat")
        assert r1.cache_cid != r2.cache_cid

    def test_same_goal_same_cid(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        r1 = ergo.query("?X : Dog")
        r2 = ergo.query("?X : Dog")  # cached
        assert r1.cache_cid == r2.cache_cid

    def test_changing_ontology_changes_cid(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        r1 = ergo.query("?X : Dog")
        ergo.add_class(self.FLogicClass("Animal"))  # changes the program
        r2 = ergo.query("?X : Dog")  # miss due to different ontology
        assert r1.cache_cid != r2.cache_cid

    def test_normalization_enabled_in_statistics(self):
        ergo = self.CachedErgoAIWrapper(
            enable_caching=True,
            use_global_cache=False,
            enable_normalization=True,
        )
        stats = ergo.get_cache_statistics()
        assert stats["normalization_enabled"] is True


# ---------------------------------------------------------------------------
# Synonym sharing
# ---------------------------------------------------------------------------


class TestSynonymCacheSharing:
    """Cache hits across synonym variants."""

    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_proof_cache import CachedErgoAIWrapper
        from ipfs_datasets_py.logic.flogic.semantic_normalizer import SemanticNormalizer
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicClass
        self.CachedErgoAIWrapper = CachedErgoAIWrapper
        self.SemanticNormalizer = SemanticNormalizer
        self.FLogicClass = FLogicClass

    def _make(self):
        return self.CachedErgoAIWrapper(
            enable_caching=True,
            use_global_cache=False,
            cache_size=100,
            enable_normalization=True,
        )

    def test_synonym_queries_share_cache_entry(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Animal"))
        ergo.add_class(self.FLogicClass("Dog", superclasses=["Animal"]))

        r1 = ergo.query("?X : Dog")           # cache miss → stores under "?X : dog" key
        assert not r1.from_cache

        r2 = ergo.query("?X : Canine")        # synonym → normalises to "?X : dog" → HIT
        assert r2.from_cache, "Synonym should share cache entry with 'Dog'"

    def test_original_goal_preserved_in_result(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        ergo.query("?X : Dog")
        r = ergo.query("?X : Canine")
        # The `goal` field should carry the original (un-normalised) query
        assert r.goal == "?X : Canine"

    def test_different_types_dont_share_entry(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        ergo.add_class(self.FLogicClass("Cat"))
        ergo.query("?X : Dog")
        r = ergo.query("?X : Cat")
        assert not r.from_cache

    def test_stats_include_normalization(self):
        ergo = self._make()
        ergo.add_class(self.FLogicClass("Dog"))
        ergo.query("?X : Dog")
        ergo.query("?X : Canine")  # synonym hit
        stats = ergo.get_cache_statistics()
        assert stats["hits"] == 1
        assert stats["misses"] == 1


# ---------------------------------------------------------------------------
# flogic_normalize_term MCP tool
# ---------------------------------------------------------------------------


class TestFlogicNormalizeTermTool:
    def setup_method(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from ipfs_datasets_py.mcp_server.tools.logic_tools.flogic_tool import (
                flogic_normalize_term,
            )
        self.flogic_normalize_term = flogic_normalize_term

    def test_basic_term_normalization(self):
        r = run(self.flogic_normalize_term(["canine", "feline", "Dog"]))
        assert r["success"] is True
        by_input = {x["input"]: x for x in r["normalized"]}
        assert by_input["canine"]["canonical"] == "dog"
        assert by_input["feline"]["canonical"] == "cat"
        assert by_input["Dog"]["canonical"] == "dog"   # maps to canonical "dog"

    def test_unchanged_term(self):
        r = run(self.flogic_normalize_term(["dog"]))
        assert r["success"] is True
        item = r["normalized"][0]
        assert item["canonical"] == "dog"
        assert item["changed"] is False

    def test_changed_flag(self):
        r = run(self.flogic_normalize_term(["canine"]))
        item = r["normalized"][0]
        assert item["changed"] is True

    def test_empty_list(self):
        r = run(self.flogic_normalize_term([]))
        assert r["success"] is True
        assert r["normalized"] == []

    def test_normalize_goals(self):
        r = run(self.flogic_normalize_term(["?X : Canine"], normalize_goals=True))
        assert r["success"] is True
        item = r["normalized"][0]
        assert "dog" in item["canonical"]
        assert item["changed"] is True

    def test_symai_active_flag_present(self):
        r = run(self.flogic_normalize_term(["cat"]))
        assert "symai_active" in r

    def test_mcp_export(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import flogic_normalize_term
        assert callable(flogic_normalize_term)
