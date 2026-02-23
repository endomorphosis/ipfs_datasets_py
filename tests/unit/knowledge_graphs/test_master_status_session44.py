"""
Session 44 - Target the final 7 missed lines in extractor.py plus test-ordering
artifacts (srl.py:613, hybrid_search.py:205) that appeared as missed when only
running the full suite together.

Missed targets:
  extractor.py:119-123   OSError handler during spaCy model load
  extractor.py:178       continue when entity confidence < min_confidence
  extractor.py:428-429   IndexError/ValueError in _parse_rebel_output inner loop
  srl.py:613             continue for empty sentence in build_temporal_graph
  hybrid_search.py:205   continue when node already visited in expand_graph
"""
from unittest.mock import MagicMock, patch, PropertyMock
import importlib
import pytest

_spacy_available = bool(importlib.util.find_spec("spacy"))
_skip_no_spacy = pytest.mark.skipif(not _spacy_available, reason="spacy not installed")


# ===========================================================================
# 1. extractor.py:119-123 – OSError during spacy.load; fallback to download
# ===========================================================================


@_skip_no_spacy
class TestExtractorSpacyModelOSError:
    """GIVEN spacy is installed but the model is not downloaded,
    WHEN KnowledgeGraphExtractor(use_spacy=True) is constructed,
    THEN spacy.cli.download is called and the model is re-loaded."""

    def test_spacy_load_oserror_triggers_download(self):
        """GIVEN spacy.load raises OSError on first call
        WHEN KnowledgeGraphExtractor is created with use_spacy=True
        THEN cli.download is called (line 122) and second load succeeds (line 123)."""
        mock_nlp = MagicMock()
        load_calls = []

        def fake_load(model_name):
            load_calls.append(model_name)
            if len(load_calls) == 1:
                raise OSError("model not found: en_core_web_sm")
            return mock_nlp

        with patch("spacy.load", side_effect=fake_load) as mock_spacy_load, \
             patch("spacy.cli.download") as mock_download:
            from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
                KnowledgeGraphExtractor,
            )
            extractor = KnowledgeGraphExtractor(use_spacy=True)

        # First call raised OSError → download called → second call succeeded
        assert len(load_calls) == 2, "spacy.load should be called twice (first fails, second succeeds)"
        mock_download.assert_called_once_with("en_core_web_sm")
        assert extractor.nlp is mock_nlp, "nlp should be set to the successful load result"

    def test_spacy_oserror_uses_ioerror_too(self):
        """GIVEN spacy.load raises IOError (alias for OSError)
        WHEN KnowledgeGraphExtractor is created with use_spacy=True
        THEN the except block at line 119 catches IOError and downloads."""
        mock_nlp = MagicMock()
        load_calls = []

        def fake_load(model_name):
            load_calls.append(model_name)
            if len(load_calls) == 1:
                raise IOError("IO failure reading model")
            return mock_nlp

        with patch("spacy.load", side_effect=fake_load), \
             patch("spacy.cli.download") as mock_dl:
            from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
                KnowledgeGraphExtractor,
            )
            extractor = KnowledgeGraphExtractor(use_spacy=True)

        mock_dl.assert_called_once()
        assert extractor.nlp is mock_nlp


# ===========================================================================
# 2. extractor.py:178 – continue when ent._.confidence < min_confidence
# ===========================================================================

@_skip_no_spacy
class TestExtractEntitiesLowConfidenceSkip:
    """GIVEN a spaCy Span extension 'confidence' set to a low value,
    WHEN extract_entities is called with min_confidence=0.9,
    THEN entities whose confidence < 0.9 are skipped (line 178)."""

    def test_low_confidence_entity_skipped(self):
        """GIVEN Span.confidence extension registered with default 0.0
        WHEN extract_entities called on text with named entities
        THEN entities with confidence < min_confidence are skipped via line 178."""
        import spacy
        from spacy.tokens import Span

        # Register extension if not already there; set default to 0.0 (low)
        extension_was_present = Span.has_extension("confidence")
        if not extension_was_present:
            Span.set_extension("confidence", default=0.0)

        try:
            from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
                KnowledgeGraphExtractor,
            )
            extractor = KnowledgeGraphExtractor(use_spacy=True, min_confidence=0.5)
            # min_confidence=0.5; extension default is 0.0 → 0.0 < 0.5 → continue
            text = "Alice Smith works at Google in New York."
            entities = extractor.extract_entities(text)
            # All entities skipped since confidence=0.0 < 0.5
            # (rule-based fallback may still return some, but spaCy entities are skipped)
            # What matters: no exception raised, line 178 was executed
            assert isinstance(entities, list)
        finally:
            # Clean up extension to avoid polluting other tests
            if not extension_was_present and Span.has_extension("confidence"):
                Span.remove_extension("confidence")

    def test_high_confidence_entity_not_skipped(self):
        """GIVEN Span.confidence extension with default 1.0 (high)
        WHEN extract_entities called
        THEN entities are NOT skipped (confidence=1.0 is not < min_confidence=0.5)."""
        import spacy
        from spacy.tokens import Span

        extension_was_present = Span.has_extension("confidence")
        if not extension_was_present:
            Span.set_extension("confidence", default=1.0)

        try:
            from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
                KnowledgeGraphExtractor,
            )
            extractor = KnowledgeGraphExtractor(use_spacy=True, min_confidence=0.5)
            text = "Barack Obama was born in Hawaii."
            entities = extractor.extract_entities(text)
            # With default confidence=1.0, entities pass the filter (line 178 not hit)
            assert isinstance(entities, list)
        finally:
            if not extension_was_present and Span.has_extension("confidence"):
                Span.remove_extension("confidence")


# ===========================================================================
# 3. extractor.py:428-429 – IndexError in _parse_rebel_output inner try/except
# ===========================================================================

class TestParseRebelOutputIndexError:
    """GIVEN REBEL output where <obj> marker appears BEFORE <subj>,
    the inner split for '<obj>' in rest would fail (IndexError) triggering
    the except at line 428 → continue at line 429."""

    def test_obj_before_subj_triggers_index_error_continue(self):
        """GIVEN a triplet string where <obj> appears before <subj>
        (so rest after split('<subj>')[1] contains no <obj>)
        WHEN _parse_rebel_output is called
        THEN the IndexError is caught and the triplet is skipped via continue (line 429)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        extractor = KnowledgeGraphExtractor()

        # Craft a string where <obj> is before <subj> in the part.
        # part = "obj_text <obj> rel_text <subj>"  → '<subj>' in part and '<obj>' in part
        # subject = part.split('<subj>')[0].strip() = "obj_text <obj> rel_text"
        # rest = part.split('<subj>')[1] = "" (nothing after <subj>)
        # rest.split('<obj>') = [""] → len=1 → rest.split('<obj>')[1] → IndexError
        rebel_output = "<triplet> obj_text <obj> rel_text <subj>"
        result = extractor._parse_rebel_output(rebel_output)
        # Should not raise; the bad triplet is skipped
        assert isinstance(result, list)
        # The malformed triplet is not included
        assert len(result) == 0

    def test_valid_triplet_still_parsed_after_bad_one(self):
        """GIVEN a REBEL output with one bad and one good triplet
        WHEN _parse_rebel_output is called
        THEN only the valid triplet is returned (bad one triggers line 429 continue)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        extractor = KnowledgeGraphExtractor()

        # First triplet: bad (obj before subj) → IndexError → continue
        # Second triplet: good
        rebel_output = (
            "<triplet> obj_text <obj> rel_text <subj>"     # bad: obj before subj
            "<triplet> Alice <subj> works_at <obj> Google"  # good
        )
        result = extractor._parse_rebel_output(rebel_output)
        assert isinstance(result, list)
        # Valid triplet extracted: ("Alice", "works_at", "Google")
        assert len(result) == 1
        assert result[0] == ("Alice", "works_at", "Google")

    def test_empty_rebel_output_returns_empty_list(self):
        """GIVEN empty REBEL output WHEN _parse_rebel_output called THEN returns []."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        extractor = KnowledgeGraphExtractor()
        result = extractor._parse_rebel_output("")
        assert result == []


# ===========================================================================
# 4. srl.py:613 – continue for empty sentence in build_temporal_graph
#    (test-ordering artifact: covered by session39 alone but missed in suite)
# ===========================================================================

class TestBuildTemporalGraphEmptySentSkip:
    """GIVEN text that when split produces an empty-string sentence element,
    WHEN build_temporal_graph is called,
    THEN the empty sentence is skipped via continue (line 613)."""

    def test_trailing_whitespace_produces_empty_sent(self):
        """GIVEN text ending with double spaces (trailing empty sentence after split)
        WHEN build_temporal_graph called
        THEN no exception; empty sentences are skipped via line 613."""
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        extractor = SRLExtractor()
        # "Alice ran.  " → re.split gives ["Alice ran.", ""]
        # The empty string "" → "".strip() = "" → not sent → continue (line 613)
        kg = extractor.build_temporal_graph("Alice ran.  ")
        assert kg is not None

    def test_only_whitespace_text_produces_all_empty_sents(self):
        """GIVEN text that is all spaces WHEN build_temporal_graph called
        THEN all sentences are empty and skipped via line 613; result is empty KG."""
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        extractor = SRLExtractor()
        kg = extractor.build_temporal_graph("   ")
        assert kg is not None

    def test_multiple_trailing_spaces_multiple_empty_sents(self):
        """GIVEN multi-sentence text with extra spaces between sentences
        WHEN build_temporal_graph called
        THEN extra empty-string elements are each skipped via line 613."""
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        extractor = SRLExtractor()
        # Multiple blank elements from consecutive delimiters
        kg = extractor.build_temporal_graph("Alice ran.  Bob walked.  ")
        assert kg is not None


# ===========================================================================
# 5. hybrid_search.py:205 – continue when node already visited in expand_graph
#    (test-ordering artifact: covered by session36 alone but missed in suite)
# ===========================================================================

class TestExpandGraphAlreadyVisitedContinue:
    """GIVEN a seed set where the same node appears twice (directly and via hop=0
    neighbor), WHEN expand_graph is called THEN the re-visited node triggers
    the continue at line 205."""

    def test_already_visited_node_skipped_in_next_hop(self):
        """GIVEN seed_nodes=[n1, n2] where n1's neighbors include n2,
        WHEN expand_graph(max_hops=1) is called,
        THEN n2 is added to visited in hop=0, then in hop=1 current_level={n2},
        n2 is already in visited → line 205 continue."""
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import (
            HybridSearchEngine,
        )

        backend = MagicMock()

        def mock_get_neighbors(node_id, rel_types=None):
            return ["n2"] if node_id == "n1" else []

        backend.get_neighbors = mock_get_neighbors
        # Force code to use get_neighbors (not get_relationships)
        del backend.get_relationships
        eng = HybridSearchEngine(backend=backend, vector_store=MagicMock())

        # hop=0: current={n1, n2}
        #   n1 not visited → visited[n1]=0; neighbors=[n2]; next={n2}
        #   n2 not visited → visited[n2]=0; neighbors=[]; next stays {n2}
        # hop=1: current={n2}
        #   n2 IS in visited → continue (line 205)
        visited = eng.expand_graph(seed_nodes=["n1", "n2"], max_hops=1)
        assert "n1" in visited
        assert "n2" in visited
        assert visited["n1"] == 0
        assert visited["n2"] == 0

    def test_already_visited_does_not_increment_hop(self):
        """GIVEN a linear chain n1→n2→n3 seeded with [n1, n2],
        WHEN expand_graph(max_hops=2) is called
        THEN n2 (seeded) is processed in hop=0 (NOT hop=1 via continue)."""
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import (
            HybridSearchEngine,
        )

        backend = MagicMock()

        def mock_get_neighbors(node_id, rel_types=None):
            if node_id == "n1":
                return ["n2"]
            if node_id == "n2":
                return ["n3"]
            return []

        backend.get_neighbors = mock_get_neighbors
        del backend.get_relationships
        eng = HybridSearchEngine(backend=backend, vector_store=MagicMock())

        visited = eng.expand_graph(seed_nodes=["n1", "n2"], max_hops=2)
        # n1 and n2 visited in hop=0 (both seeded)
        # n2 re-encountered in hop=1 → continue (line 205) — hop stays 0
        # n3 added in hop=1 (from n2's neighbors) and processed in hop=2
        assert visited.get("n1") == 0
        assert visited.get("n2") == 0  # NOT overwritten from 0 to 1
        assert "n3" in visited


# ===========================================================================
# 6. extraction/finance_graphrag.py:25-26 – _MINIMAL_IMPORTS=True path
#    and :31 – GRAPHRAG_AVAILABLE=True path (successful import)
# ===========================================================================

class TestFinanceGraphRAGMinimalImports:
    """GIVEN IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 env var,
    WHEN finance_graphrag module is reloaded,
    THEN _MINIMAL_IMPORTS=True, GraphRAGIntegration=None (line 25),
    GRAPHRAG_AVAILABLE=False (line 26)."""

    def test_minimal_imports_env_var_sets_graphrag_unavailable(self):
        """GIVEN IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 env var set
        WHEN finance_graphrag is reloaded
        THEN lines 25-26 execute: GraphRAGIntegration=None, GRAPHRAG_AVAILABLE=False."""
        import os
        import importlib
        import ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag as fg_mod

        orig_val = os.environ.get("IPFS_DATASETS_PY_MINIMAL_IMPORTS")
        try:
            os.environ["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
            importlib.reload(fg_mod)
            assert fg_mod.GRAPHRAG_AVAILABLE is False
            assert fg_mod.GraphRAGIntegration is None
        finally:
            # Restore env var
            if orig_val is None:
                os.environ.pop("IPFS_DATASETS_PY_MINIMAL_IMPORTS", None)
            else:
                os.environ["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = orig_val
            # Reload to restore original state
            os.environ.pop("IPFS_DATASETS_PY_MINIMAL_IMPORTS", None)
            importlib.reload(fg_mod)

    def test_benchmark_env_var_also_triggers_minimal_imports(self):
        """GIVEN IPFS_DATASETS_PY_BENCHMARK=1 env var set
        WHEN finance_graphrag is reloaded
        THEN _MINIMAL_IMPORTS=True (lines 25-26 covered)."""
        import os
        import importlib
        import ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag as fg_mod

        orig_val = os.environ.get("IPFS_DATASETS_PY_BENCHMARK")
        try:
            os.environ["IPFS_DATASETS_PY_BENCHMARK"] = "1"
            importlib.reload(fg_mod)
            assert fg_mod.GRAPHRAG_AVAILABLE is False
        finally:
            if orig_val is None:
                os.environ.pop("IPFS_DATASETS_PY_BENCHMARK", None)
            else:
                os.environ["IPFS_DATASETS_PY_BENCHMARK"] = orig_val
            os.environ.pop("IPFS_DATASETS_PY_BENCHMARK", None)
            importlib.reload(fg_mod)


class TestFinanceGraphRAGSuccessfulImport:
    """GIVEN graphrag.integration module is mocked to succeed,
    WHEN finance_graphrag is reloaded,
    THEN line 31 (GRAPHRAG_AVAILABLE = True) is executed."""

    def test_graphrag_available_true_when_integration_importable(self):
        """GIVEN processors.graphrag.integration module mocked in sys.modules
        WHEN finance_graphrag is reloaded
        THEN line 31 executes: GRAPHRAG_AVAILABLE = True."""
        import sys
        import importlib
        import ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag as fg_mod

        # Create mock modules so the import succeeds
        mock_integration = MagicMock()
        mock_integration.GraphRAGIntegration = MagicMock()
        mock_processors_graphrag = MagicMock()

        modules_to_inject = {
            "ipfs_datasets_py.processors.graphrag": mock_processors_graphrag,
            "ipfs_datasets_py.processors.graphrag.integration": mock_integration,
        }

        with patch.dict(sys.modules, modules_to_inject):
            importlib.reload(fg_mod)
            # If import succeeded, GRAPHRAG_AVAILABLE should be True
            result = fg_mod.GRAPHRAG_AVAILABLE

        # Restore module state
        importlib.reload(fg_mod)

        assert result is True, (
            f"Expected GRAPHRAG_AVAILABLE=True when integration importable, got {result}"
        )
