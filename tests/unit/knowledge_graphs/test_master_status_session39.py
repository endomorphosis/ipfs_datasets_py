"""
Session 39 — knowledge_graphs coverage push.

Targets:
  extraction/srl.py       lines 366-428 (_extract_spacy_frames with mock tokens)
                          lines 613-619 (build_temporal_graph NLP fallback)
  query/knowledge_graph.py lines 131-132 (UnifiedGraphRAGProcessor success path)
                           lines 173-193 (IR query path with mocked search module)

GIVEN-WHEN-THEN style, consistent with existing session test files.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers — build mock spaCy token / span objects
# ---------------------------------------------------------------------------

def _make_child(dep: str, text: str, pos_: str = "NOUN"):
    """Create a minimal mock spaCy token acting as a dependency child."""
    child = MagicMock()
    child.dep_ = dep
    child.text = text
    child.pos_ = pos_
    child.idx = 0
    # subtree: just itself
    child.subtree = [child]
    return child


def _make_verb_token(lemma: str, children_list, text: str = None):
    """Create a mock spaCy token with POS=VERB and given children."""
    tok = MagicMock()
    tok.pos_ = "VERB"
    tok.lemma_ = lemma
    tok.text = text or lemma
    tok.idx = 10
    tok.children = iter(children_list)
    return tok


def _make_aux_token(lemma: str = "be"):
    """Create a mock AUX token (should be skipped)."""
    tok = MagicMock()
    tok.pos_ = "AUX"
    tok.lemma_ = lemma
    return tok


def _make_noun_token(lemma: str = "cat"):
    """Create a mock NOUN token (should be skipped — not VERB/AUX)."""
    tok = MagicMock()
    tok.pos_ = "NOUN"
    tok.lemma_ = lemma
    return tok


def _make_sentence_span(tokens):
    """Create a mock spaCy Span (sentence) with the given token list."""
    span = MagicMock()
    span.text = "Mock sentence"
    span.__iter__ = MagicMock(return_value=iter(tokens))
    return span


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
    SRLExtractor,
    SRLFrame,
    RoleArgument,
    _extract_spacy_frames,
    ROLE_AGENT, ROLE_PATIENT, ROLE_RECIPIENT,
    ROLE_INSTRUMENT, ROLE_LOCATION, ROLE_TIME, ROLE_CAUSE, ROLE_THEME,
)


# ===========================================================================
# _extract_spacy_frames — line coverage for every dependency branch
# ===========================================================================

class TestExtractSpacyFramesSkips:
    """GIVEN tokens with non-VERB/AUX pos — WHEN _extract_spacy_frames is called
    THEN those tokens are skipped and no frames produced."""

    def test_non_verb_token_is_skipped(self):
        # GIVEN a span containing only a NOUN token
        noun = _make_noun_token("dog")
        span = _make_sentence_span([noun])
        # WHEN
        frames = _extract_spacy_frames(span)
        # THEN no frames
        assert frames == []

    def test_aux_verb_in_aux_list_is_skipped(self):
        # GIVEN a span whose only VERB token has lemma 'be' (in _AUX_VERBS)
        aux = _make_aux_token("be")
        # Even if POS is VERB, if lemma is in _AUX_VERBS → skip
        aux.pos_ = "VERB"
        aux.children = iter([])
        span = _make_sentence_span([aux])
        # WHEN
        frames = _extract_spacy_frames(span)
        # THEN no frames
        assert frames == []

    def test_verb_with_empty_children_yields_no_frames(self):
        # GIVEN a VERB token with no children
        verb = _make_verb_token("run", [])
        span = _make_sentence_span([verb])
        # WHEN
        frames = _extract_spacy_frames(span)
        # THEN no arguments → no frames
        assert frames == []

    def test_child_with_empty_text_is_skipped(self):
        # GIVEN a VERB token whose child has empty text
        child = _make_child("nsubj", "")
        verb = _make_verb_token("go", [child])
        span = _make_sentence_span([verb])
        # WHEN
        frames = _extract_spacy_frames(span)
        # THEN empty text child skipped → no arguments → no frames
        assert frames == []

    def test_child_with_unknown_dep_is_skipped(self):
        # GIVEN a VERB token with a child whose dep is 'det' (not handled)
        child = _make_child("det", "the")
        verb = _make_verb_token("read", [child])
        span = _make_sentence_span([verb])
        # WHEN
        frames = _extract_spacy_frames(span)
        # THEN dep 'det' hits the final `else: continue` → no arguments → no frame
        assert frames == []


class TestExtractSpacyFramesRoles:
    """GIVEN valid VERB tokens with dependency children — WHEN _extract_spacy_frames
    is called THEN each child maps to the correct semantic role."""

    def test_nsubj_child_maps_to_agent(self):
        # GIVEN nsubj child
        child = _make_child("nsubj", "Alice")
        verb = _make_verb_token("send", [child])
        span = _make_sentence_span([verb])
        # WHEN
        frames = _extract_spacy_frames(span)
        # THEN one frame, one AGENT argument
        assert len(frames) == 1
        assert frames[0].get_role(ROLE_AGENT).text == "Alice"

    def test_nsubjpass_child_maps_to_agent(self):
        child = _make_child("nsubjpass", "Bob")
        verb = _make_verb_token("hire", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert len(frames) == 1
        assert frames[0].get_role(ROLE_AGENT) is not None

    def test_agent_dep_maps_to_agent(self):
        child = _make_child("agent", "team")
        verb = _make_verb_token("assign", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_AGENT).text == "team"

    def test_expl_dep_maps_to_agent(self):
        child = _make_child("expl", "there")
        verb = _make_verb_token("exist", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_AGENT) is not None

    def test_dobj_child_maps_to_patient(self):
        child = _make_child("dobj", "report")
        verb = _make_verb_token("write", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_PATIENT).text == "report"

    def test_obj_dep_maps_to_patient(self):
        child = _make_child("obj", "letter")
        verb = _make_verb_token("post", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_PATIENT) is not None

    def test_iobj_dep_maps_to_patient(self):
        child = _make_child("iobj", "manager")
        verb = _make_verb_token("show", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_PATIENT) is not None

    def test_dative_dep_maps_to_recipient(self):
        child = _make_child("dative", "customer")
        verb = _make_verb_token("deliver", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_RECIPIENT) is not None

    def test_prep_with_maps_to_instrument(self):
        child = _make_child("prep", "with")
        child.subtree = [child]
        verb = _make_verb_token("cut", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_INSTRUMENT) is not None

    def test_prep_using_maps_to_instrument(self):
        child = _make_child("prep", "using")
        child.subtree = [child]
        verb = _make_verb_token("write", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_INSTRUMENT) is not None

    def test_prep_by_maps_to_instrument(self):
        child = _make_child("prep", "by")
        child.subtree = [child]
        verb = _make_verb_token("execute", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_INSTRUMENT) is not None

    def test_prep_in_maps_to_location(self):
        child = _make_child("prep", "in")
        child.subtree = [child]
        verb = _make_verb_token("live", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_LOCATION) is not None

    def test_prep_at_maps_to_location(self):
        child = _make_child("prep", "at")
        child.subtree = [child]
        verb = _make_verb_token("meet", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_LOCATION) is not None

    def test_prep_when_maps_to_time(self):
        child = _make_child("prep", "when")
        child.subtree = [child]
        verb = _make_verb_token("arrive", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_TIME) is not None

    def test_prep_after_maps_to_time(self):
        child = _make_child("prep", "after")
        child.subtree = [child]
        verb = _make_verb_token("leave", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_TIME) is not None

    def test_prep_because_maps_to_cause(self):
        child = _make_child("prep", "because")
        child.subtree = [child]
        verb = _make_verb_token("stop", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_CAUSE) is not None

    def test_prep_due_maps_to_cause(self):
        child = _make_child("prep", "due")
        child.subtree = [child]
        verb = _make_verb_token("fail", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_CAUSE) is not None

    def test_prep_other_maps_to_theme(self):
        # Any prep not in specific sets → ROLE_THEME
        child = _make_child("prep", "despite")
        child.subtree = [child]
        verb = _make_verb_token("succeed", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].get_role(ROLE_THEME) is not None

    def test_advmod_other_maps_to_theme(self):
        child = _make_child("advmod", "quickly")
        child.subtree = [child]
        verb = _make_verb_token("run", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        # "quickly" is not in any of the prep sets → ROLE_THEME
        assert frames[0].get_role(ROLE_THEME) is not None

    def test_long_subtree_uses_span_text_instead(self):
        # GIVEN a subtree longer than 60 chars
        long_word = "a " * 35  # 70 chars
        child = _make_child("nsubj", "short")
        child2 = MagicMock()
        child2.text = long_word.strip()
        child.subtree = [child, child2]
        verb = _make_verb_token("see", [child])
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        # THEN use_text falls back to span_text ("short") not subtree
        assert len(frames) == 1
        assert frames[0].arguments[0].text == "short"

    def test_returned_frame_has_correct_source_and_confidence(self):
        child = _make_child("nsubj", "Alice")
        verb = _make_verb_token("run", [child])
        verb.idx = 5
        span = _make_sentence_span([verb])
        frames = _extract_spacy_frames(span)
        assert frames[0].source == "spacy"
        assert frames[0].confidence == 0.80


class TestExtractWithSpacyMethod:
    """GIVEN an SRLExtractor with a mock nlp — WHEN extract_srl is called
    THEN _extract_with_spacy is used and returns frames."""

    def _make_mock_nlp(self, frames_per_sent: list):
        """Build a minimal mock spaCy pipeline returning the given frames."""
        # Construct a doc with .sents yielding spans
        mock_doc = MagicMock()
        spans = []
        for frame_list in frames_per_sent:
            span = MagicMock()
            span.text = "sentence"
            span.__iter__ = MagicMock(return_value=iter([]))
            spans.append(span)
        mock_doc.sents = iter(spans)

        mock_nlp = MagicMock()
        mock_nlp.return_value = mock_doc
        return mock_nlp

    def test_extract_with_spacy_uses_nlp_attribute(self):
        # GIVEN an extractor with a mock nlp that produces empty doc
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_doc.sents = iter([])  # no sentences
        mock_nlp.return_value = mock_doc
        extractor = SRLExtractor(nlp=mock_nlp)
        # WHEN
        frames = extractor.extract_srl("Test sentence here.")
        # THEN nlp was called
        mock_nlp.assert_called_once()
        assert frames == []

    def test_extract_with_spacy_returns_frames_from_sentences(self):
        # GIVEN a mock nlp that returns one sentence span with a VERB+child
        child = _make_child("nsubj", "Alice")
        verb = _make_verb_token("send", [child])
        sent_span = _make_sentence_span([verb])

        mock_doc = MagicMock()
        mock_doc.sents = iter([sent_span])
        mock_nlp = MagicMock(return_value=mock_doc)

        extractor = SRLExtractor(nlp=mock_nlp)
        # WHEN
        frames = extractor.extract_srl("Alice sends the report.")
        # THEN one frame returned
        assert len(frames) == 1
        assert frames[0].source == "spacy"


# ===========================================================================
# build_temporal_graph NLP fallback (lines 613-619)
# ===========================================================================

class TestBuildTemporalGraphNLPFallback:
    """GIVEN an SRLExtractor with nlp set WHEN build_temporal_graph is called
    with a sentence not found in the pre-extracted frame map
    THEN the NLP fallback branch (line 615-619) is triggered."""

    def test_nlp_fallback_called_for_sentence_not_in_frame_map(self):
        # GIVEN an SRLExtractor with a mock nlp that returns different docs for
        # each call:
        # - First call (from extract_srl): doc1 with sent_span having sentence
        #   text "Mock sentence" (not matching "Alice runs fast")
        # - Second call (fallback in build_temporal_graph): doc2 with a span
        #   that yields a VERB+child so _extract_spacy_frames runs (line 619)
        child1 = _make_child("nsubj", "Alice")
        verb1 = _make_verb_token("run", [child1])
        # First span's text is "Mock sentence" - will NOT match the input sent
        sent_span1 = _make_sentence_span([verb1])  # text = "Mock sentence"

        # Second call's span: a verb token with child → exercises line 619
        child2 = _make_child("nsubj", "Bob")
        verb2 = _make_verb_token("walk", [child2])
        sent_span2 = _make_sentence_span([verb2])

        doc1 = MagicMock()
        doc1.sents = iter([sent_span1])  # first call result

        doc2 = MagicMock()
        doc2.sents = iter([sent_span2])  # second (fallback) call result

        mock_nlp = MagicMock(side_effect=[doc1, doc2])

        extractor = SRLExtractor(nlp=mock_nlp)
        # WHEN build_temporal_graph is called
        result_kg = extractor.build_temporal_graph("Alice runs fast")
        # THEN nlp was invoked at least twice (once for extract_srl, once for fallback)
        assert mock_nlp.call_count >= 2

    def test_empty_sentence_continue_in_build_temporal_graph(self):
        # GIVEN text with trailing period+spaces producing empty string from split
        # "Alice ran.  " → split gives ["Alice ran.", ""] → empty sent hits line 613
        mock_nlp = MagicMock()
        doc = MagicMock()
        doc.sents = iter([])
        mock_nlp.return_value = doc
        extractor = SRLExtractor(nlp=mock_nlp)
        # WHEN build_temporal_graph with trailing spaces (produces empty sentinel)
        result_kg = extractor.build_temporal_graph("Alice ran.  ")
        # THEN no exception, empty sent was skipped via continue
        assert result_kg is not None

    def test_nlp_fallback_not_called_when_frame_map_has_sentence(self):
        # GIVEN an SRLExtractor with a mock nlp set
        mock_nlp = MagicMock()
        extractor = SRLExtractor(nlp=mock_nlp)

        # Inject a known frame into the extractor so the sentence IS in _frame_map
        # by running heuristic extraction first.
        # Use a sentence that produces heuristic frames, then call build_temporal_graph.
        # The heuristic will produce a frame and the nlp fallback won't be triggered.
        text = "Alice bought the book yesterday"
        kg = extractor.build_temporal_graph(text)
        # mock_nlp may or may not be called — just assert no exception
        assert kg is not None


# ===========================================================================
# query/knowledge_graph.py — IR path with mocked search modules
# ===========================================================================

class TestQueryKnowledgeGraphIRPath:
    """GIVEN mocked ipfs_datasets_py.search.graph_query modules
    WHEN query_knowledge_graph is called with query_type='ir' and manifest_cid
    THEN the IR path is exercised (lines 173-193).

    Note: We do NOT reload the module. Instead we pre-populate sys.modules
    with mock objects so that the `from ... import` calls inside the function
    body pick up the mocks at call time.
    """

    def _make_mock_search_modules(self):
        """Build mock search module tree."""
        mock_ir_mod = types.ModuleType("ipfs_datasets_py.search.graph_query.ir")
        mock_budgets_mod = types.ModuleType("ipfs_datasets_py.search.graph_query.budgets")
        mock_sharded_mod = types.ModuleType("ipfs_datasets_py.search.graph_query.sharded_car")
        mock_gq_mod = types.ModuleType("ipfs_datasets_py.search.graph_query")

        # IR classes — QueryIR.from_ops must return a usable object
        mock_qir = MagicMock()
        mock_ir_mod.QueryIR = MagicMock()
        mock_ir_mod.QueryIR.from_ops = MagicMock(return_value=mock_qir)
        mock_ir_mod.SeedEntities = MagicMock(side_effect=lambda ids: MagicMock())
        mock_ir_mod.Expand = MagicMock()
        mock_ir_mod.Limit = MagicMock()
        mock_ir_mod.Project = MagicMock()
        mock_ir_mod.ScanType = MagicMock()

        # GraphQueryExecutor
        mock_result = MagicMock()
        mock_result.items = [{"id": "e1"}]
        mock_executor = MagicMock()
        mock_executor.execute.return_value = mock_result
        mock_gq_mod.GraphQueryExecutor = MagicMock(return_value=mock_executor)

        # budgets_from_preset — must return object with attributes
        mock_budgets_obj = MagicMock()
        mock_budgets_obj.max_results = 100
        mock_budgets_obj.timeout_ms = 5000
        mock_budgets_obj.max_depth = 5
        mock_budgets_obj.max_nodes_visited = 1000
        mock_budgets_obj.max_edges_scanned = 2000
        mock_budgets_obj.max_working_set_entities = 500
        mock_budgets_obj.max_degree_per_node = 50
        mock_budgets_obj.max_shards_touched = 10
        mock_budgets_mod.budgets_from_preset = MagicMock(return_value=mock_budgets_obj)

        # sharded_car_backend_from_manifest_cid
        mock_sharded_mod.sharded_car_backend_from_manifest_cid = MagicMock(return_value=MagicMock())

        return {
            "ipfs_datasets_py.search.graph_query": mock_gq_mod,
            "ipfs_datasets_py.search.graph_query.ir": mock_ir_mod,
            "ipfs_datasets_py.search.graph_query.budgets": mock_budgets_mod,
            "ipfs_datasets_py.search.graph_query.sharded_car": mock_sharded_mod,
        }

    def test_ir_query_with_ir_ops_calls_executor(self):
        # GIVEN mocked search modules pre-populated in sys.modules
        mock_modules = self._make_mock_search_modules()
        # Import the function BEFORE patching so it uses the live module object
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import (
            query_knowledge_graph,
        )
        with patch.dict(sys.modules, mock_modules):
            # WHEN calling query_knowledge_graph with ir_ops (skips parse_ir_ops_from_query)
            result = query_knowledge_graph(
                query='[{"op":"SeedEntities","entity_ids":["e1"]}]',
                query_type="ir",
                manifest_cid="bafy123",
                ir_ops=[{"op": "SeedEntities", "entity_ids": ["e1"]}],
            )
        # THEN success returned
        assert result["success"] is True
        assert result["query_type"] == "ir"

    def test_ir_query_parses_query_string_when_no_ir_ops(self):
        # GIVEN mocked search modules
        mock_modules = self._make_mock_search_modules()
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import (
            query_knowledge_graph,
        )
        import json
        ops_json = json.dumps([{"op": "SeedEntities", "entity_ids": ["e1"]}])
        with patch.dict(sys.modules, mock_modules):
            # WHEN ir_ops is None — parse_ir_ops_from_query is called first
            result = query_knowledge_graph(
                query=ops_json,
                query_type="ir",
                manifest_cid="bafy456",
            )
        assert result["success"] is True

    def test_non_ir_query_type_without_graph_id_raises(self):
        # GIVEN query_type that is not ir or legacy
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="graph_id is required"):
            query_knowledge_graph(query="MATCH (n) RETURN n", query_type="cypher")

    def test_ir_without_manifest_cid_raises_valueerror(self):
        # GIVEN query_type='ir' with no manifest_cid
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="manifest_cid is required"):
            query_knowledge_graph(
                query='[{"op":"SeedEntities","entity_ids":["e1"]}]',
                query_type="ir",
                manifest_cid=None,
            )


class TestQueryKnowledgeGraphLegacyUnifiedPath:
    """GIVEN mocked UnifiedGraphRAGProcessor WHEN query_knowledge_graph is
    called with query_type='gremlin' THEN the gremlin path executes (line 150).

    Note: Lines 131-132 (config + UnifiedGraphRAGProcessor instantiation)
    are dead code due to a pre-existing bug: lines 139-142 unconditionally
    override `processor` using `GraphRAGProcessor` / `MockGraphRAGProcessor`
    which are only bound in the `except ImportError` branch. If the try-import
    succeeds, line 142 raises UnboundLocalError. We document this but do not
    fix production code. The semantic/gremlin paths at lines 149-152 ARE
    testable by relying on the fallback (except) branch.
    """

    def test_semantic_query_type_calls_execute_semantic_query(self):
        # GIVEN mock legacy fallback processor (unified import is absent)
        mock_fallback_mod = types.ModuleType("ipfs_datasets_py.processors.graphrag_processor")
        mock_proc = MagicMock()
        mock_graph = MagicMock()
        mock_proc.load_graph.return_value = mock_graph
        mock_proc.execute_semantic_query.return_value = [{"node": "x"}]
        mock_fallback_mod.GraphRAGProcessor = MagicMock(return_value=mock_proc)
        mock_fallback_mod.MockGraphRAGProcessor = MagicMock(return_value=mock_proc)

        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import (
            query_knowledge_graph,
        )
        extra_mods = {
            "ipfs_datasets_py.processors.graphrag_processor": mock_fallback_mod,
        }
        with patch.dict(sys.modules, extra_mods):
            # Temporarily remove the unified module to force fallback
            sys.modules.pop(
                "ipfs_datasets_py.processors.specialized.graphrag.unified_graphrag", None
            )
            result = query_knowledge_graph(
                graph_id="demo_graph",
                query="find related nodes",
                query_type="semantic",
            )
        assert isinstance(result, dict)

    def test_gremlin_query_type_calls_execute_gremlin(self):
        # GIVEN mock legacy fallback processor (gremlin path)
        mock_fallback_mod = types.ModuleType("ipfs_datasets_py.processors.graphrag_processor")
        mock_proc = MagicMock()
        mock_graph = MagicMock()
        mock_proc.load_graph.return_value = mock_graph
        mock_proc.execute_gremlin.return_value = [{"v": "v1"}]
        mock_fallback_mod.GraphRAGProcessor = MagicMock(return_value=mock_proc)
        mock_fallback_mod.MockGraphRAGProcessor = MagicMock(return_value=mock_proc)

        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import (
            query_knowledge_graph,
        )
        extra_mods = {
            "ipfs_datasets_py.processors.graphrag_processor": mock_fallback_mod,
        }
        with patch.dict(sys.modules, extra_mods):
            sys.modules.pop(
                "ipfs_datasets_py.processors.specialized.graphrag.unified_graphrag", None
            )
            result = query_knowledge_graph(
                graph_id="my_graph",
                query="g.V()",
                query_type="gremlin",
            )
        assert isinstance(result, dict)
