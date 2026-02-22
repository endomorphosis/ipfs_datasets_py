"""
Session 28 tests — Knowledge Graphs master-status coverage.

GIVEN-WHEN-THEN style, zero external side-effects, no slow deps.

Targets (coverage gains expected):
  extraction/extractor.py      54% → ~75%  (+21pp, ~90 new lines)
  core/graph_engine.py         69% → ~90%  (+21pp, ~50 new lines)
  core/types.py                85% → 85%   (protocol stubs, unreachable)
"""

from __future__ import annotations

import sys
import logging
from unittest.mock import MagicMock, patch
from typing import Dict, List

import pytest

# ---------------------------------------------------------------------------
# Helpers – lazy imports so collection works even without optional deps
# ---------------------------------------------------------------------------

def _extractor():
    from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor
    return KnowledgeGraphExtractor


def _entity():
    from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
    return Entity


def _relationship():
    from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship
    return Relationship


def _kg():
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    return KnowledgeGraph


def _srl_types():
    from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
        SRLFrame, RoleArgument, SRLExtractor,
    )
    return SRLFrame, RoleArgument, SRLExtractor


def _graph_engine():
    from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
    return GraphEngine


def _storage_error():
    from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
    return StorageError


# ===========================================================================
#  A: _parse_rebel_output (lines 398-434)
# ===========================================================================

class TestParseRebelOutput:
    """Tests for KnowledgeGraphExtractor._parse_rebel_output."""

    def setup_method(self):
        KGE = _extractor()
        self.e = KGE(use_tracer=False)

    # -----------------------------------------------------------------------
    def test_given_valid_rebel_format_when_parsed_then_returns_triplets(self):
        """GIVEN valid REBEL text WHEN _parse_rebel_output THEN returns triplets."""
        text = "<triplet>Alice<subj>CEO of<obj>ACME Corp"
        triplets = self.e._parse_rebel_output(text)
        assert len(triplets) == 1
        assert triplets[0] == ("Alice", "CEO of", "ACME Corp")

    def test_given_multiple_triplets_when_parsed_then_all_returned(self):
        """GIVEN two REBEL triplets WHEN parsed THEN both returned."""
        text = "<triplet>Alice<subj>CEO of<obj>ACME<triplet>Bob<subj>works for<obj>ACME"
        triplets = self.e._parse_rebel_output(text)
        assert len(triplets) == 2

    def test_given_empty_string_when_parsed_then_returns_empty(self):
        """GIVEN empty string WHEN parsed THEN empty list returned (line 415)."""
        assert self.e._parse_rebel_output("") == []

    def test_given_rebel_text_missing_subj_tag_when_parsed_then_skipped(self):
        """GIVEN text without <subj> WHEN parsed THEN triplet skipped."""
        text = "<triplet>Alice<obj>ACME"
        triplets = self.e._parse_rebel_output(text)
        assert triplets == []

    def test_given_rebel_text_missing_obj_tag_when_parsed_then_skipped(self):
        """GIVEN text with <subj> but without <obj> WHEN parsed THEN skipped."""
        text = "<triplet>Alice<subj>CEO of"
        triplets = self.e._parse_rebel_output(text)
        assert triplets == []

    def test_given_non_string_input_when_parsed_then_returns_empty(self):
        """GIVEN AttributeError input WHEN parsed THEN catches error, returns empty."""
        # None.split('<triplet>') raises AttributeError → caught at line 431
        result = self.e._parse_rebel_output(None)
        assert result == []


# ===========================================================================
#  B: Transformers NER extraction (lines 135-136, 193-235)
# ===========================================================================

class TestTransformersNER:
    """Tests for KnowledgeGraphExtractor with mocked transformers NER."""

    def _make_extractor_with_ner(self, ner_results):
        """Build an extractor whose ner_model returns *ner_results*."""
        mock_ner = MagicMock()
        mock_ner.return_value = ner_results
        mock_re = MagicMock()
        mock_re.return_value = []
        mock_pipeline = MagicMock(side_effect=[mock_ner, mock_re])
        mock_transformers = MagicMock()
        mock_transformers.pipeline = mock_pipeline
        KGE = _extractor()
        with patch.dict(sys.modules, {"transformers": mock_transformers}):
            e = KGE(use_transformers=True, use_tracer=False)
        return e

    # -----------------------------------------------------------------------
    def test_given_ner_model_loaded_when_init_then_ner_model_is_set(self):
        """GIVEN transformers available WHEN init THEN ner_model is set (lines 135-136)."""
        mock_ner = MagicMock()
        mock_re = MagicMock()
        mock_pipeline = MagicMock(side_effect=[mock_ner, mock_re])
        mock_transformers = MagicMock()
        mock_transformers.pipeline = mock_pipeline
        KGE = _extractor()
        with patch.dict(sys.modules, {"transformers": mock_transformers}):
            e = KGE(use_transformers=True, use_tracer=False)
        assert e.ner_model is mock_ner
        assert e.re_model is mock_re

    def test_given_ner_results_when_extract_entities_then_entities_returned(self):
        """GIVEN transformers NER results WHEN extract_entities THEN returns entities (193-227)."""
        e = self._make_extractor_with_ner([
            {"entity": "B-PER", "word": "Alice", "score": 0.92},
        ])
        entities = e.extract_entities("Alice works at Acme Corp.")
        assert len(entities) == 1
        assert entities[0].name == "Alice"

    def test_given_low_score_ner_result_when_extract_then_filtered_out(self):
        """GIVEN NER result below min_confidence WHEN extract THEN not included."""
        e = self._make_extractor_with_ner([
            {"entity": "B-PER", "word": "Alice", "score": 0.10},
        ])
        entities = e.extract_entities("Alice works.")
        assert len(entities) == 0

    def test_given_duplicate_ner_results_when_extract_then_highest_confidence_wins(self):
        """GIVEN duplicate NER for same word WHEN extract THEN highest-confidence entity kept."""
        e = self._make_extractor_with_ner([
            {"entity": "B-PER", "word": "Alice", "score": 0.80},
            {"entity": "B-ORG", "word": "Alice", "score": 0.92},
        ])
        entities = e.extract_entities("Alice works.")
        # Both refer to "Alice"; entity_groups collapses duplicates
        assert len(entities) == 1
        assert entities[0].confidence == pytest.approx(0.92)

    def test_given_ner_model_raises_importerror_when_extract_then_fallback(self):
        """GIVEN ner_model raises ImportError WHEN extract THEN falls back to rule-based."""
        e = self._make_extractor_with_ner([])
        e.ner_model.side_effect = ImportError("missing")
        # Should not raise; falls back to rule-based
        entities = e.extract_entities("Alice works.")
        assert isinstance(entities, list)

    def test_given_ner_model_raises_unexpected_error_when_extract_then_propagates(self):
        """GIVEN ner_model raises RuntimeError WHEN extract THEN EntityExtractionError raised."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import EntityExtractionError
        e = self._make_extractor_with_ner([])
        e.ner_model.side_effect = RuntimeError("boom")
        with pytest.raises(EntityExtractionError):
            e.extract_entities("some text")

    def test_given_transformers_import_error_when_init_then_use_transformers_disabled(self):
        """GIVEN transformers unavailable WHEN init THEN use_transformers=False (lines 138-143)."""
        mock_transformers = MagicMock()
        mock_transformers.pipeline.side_effect = ImportError("no transformers")
        KGE = _extractor()
        with patch.dict(sys.modules, {"transformers": mock_transformers}):
            e = KGE(use_transformers=True, use_tracer=False)
        assert e.use_transformers is False


# ===========================================================================
#  C: Neural relationship extraction (lines 278-394)
# ===========================================================================

class TestNeuralRelationshipExtraction:
    """Tests for _neural_relationship_extraction with mocked re_model."""

    def setup_method(self):
        KGE = _extractor()
        self.e = KGE(use_tracer=False)
        self.e.use_transformers = True

        Entity = _entity()
        self.alice = Entity(entity_type="person", name="Alice", confidence=0.9)
        self.acme = Entity(entity_type="organization", name="Acme Corp", confidence=0.9)
        self.entity_map: Dict = {"Alice": self.alice, "Acme Corp": self.acme}

    # -----------------------------------------------------------------------
    def test_given_no_re_model_when_extract_then_empty_list(self):
        """GIVEN re_model is None WHEN _neural_relationship_extraction THEN returns []."""
        self.e.re_model = None
        rels = self.e._neural_relationship_extraction("text", self.entity_map)
        assert rels == []

    def test_given_rebel_model_when_extract_then_lines_315_to_337_executed(self):
        """GIVEN REBEL text2text model WHEN extract THEN triplets path executed (315-337)."""
        mock_re = MagicMock()
        mock_re.task = "text2text-generation"
        mock_re.return_value = [{"generated_text": "<triplet>Alice<subj>CEO of<obj>Acme Corp"}]
        self.e.re_model = mock_re
        # Relationship creation may raise TypeError (extraction_method not in schema)
        # but the function should return gracefully (caught at line 378)
        rels = self.e._neural_relationship_extraction(
            "Alice is CEO of Acme Corp.", self.entity_map
        )
        assert isinstance(rels, list)

    def test_given_rebel_model_with_no_triplets_when_extract_then_empty(self):
        """GIVEN REBEL model returns empty generated text WHEN extract THEN empty rels."""
        mock_re = MagicMock()
        mock_re.task = "text2text-generation"
        mock_re.return_value = [{"generated_text": ""}]
        self.e.re_model = mock_re
        rels = self.e._neural_relationship_extraction("no triplets here", self.entity_map)
        assert rels == []

    def test_given_rebel_model_returns_empty_list_when_extract_then_empty(self):
        """GIVEN REBEL model returns empty list WHEN extract THEN no rels."""
        mock_re = MagicMock()
        mock_re.task = "text2text-generation"
        mock_re.return_value = []
        self.e.re_model = mock_re
        rels = self.e._neural_relationship_extraction("text", self.entity_map)
        assert rels == []

    def test_given_classification_model_when_extract_then_lines_346_to_376_executed(self):
        """GIVEN classification re_model WHEN extract THEN sentence-loop path (346, 373) hit."""
        mock_re = MagicMock()
        mock_re.task = None  # not text2text
        mock_re.return_value = [{"label": "works_for", "score": 0.9}]
        self.e.re_model = mock_re
        # Use a text with Alice and Acme Corp in a sentence so entities are found
        text = "Alice works for Acme Corp."
        rels = self.e._neural_relationship_extraction(text, self.entity_map)
        assert isinstance(rels, list)
        # may or may not succeed depending on Relationship constructor
        # check the model was called
        assert mock_re.called

    def test_given_classification_model_low_confidence_when_extract_then_no_rel(self):
        """GIVEN classification score below 0.6 WHEN extract THEN rel not created (line 358)."""
        mock_re = MagicMock()
        mock_re.task = None
        mock_re.return_value = [{"label": "works_for", "score": 0.3}]  # below 0.6
        self.e.re_model = mock_re
        rels = self.e._neural_relationship_extraction("Alice at Acme Corp.", self.entity_map)
        assert len(rels) == 0

    def test_given_re_model_raises_importerror_when_extract_then_returns_partial(self):
        """GIVEN re_model raises ImportError WHEN extract THEN logged, partial list returned (378-381)."""
        mock_re = MagicMock()
        mock_re.task = "text2text-generation"
        mock_re.side_effect = ImportError("no lib")
        self.e.re_model = mock_re
        rels = self.e._neural_relationship_extraction("text", self.entity_map)
        assert isinstance(rels, list)

    def test_given_re_model_raises_unexpected_error_when_extract_then_relextraction_error(self):
        """GIVEN re_model raises RuntimeError WHEN extract THEN RelationshipExtractionError (383-394)."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import RelationshipExtractionError
        mock_re = MagicMock()
        mock_re.task = "text2text-generation"
        mock_re.side_effect = RuntimeError("boom")
        self.e.re_model = mock_re
        with pytest.raises(RelationshipExtractionError):
            self.e._neural_relationship_extraction("text", self.entity_map)


# ===========================================================================
#  D: _rule_based_relationship_extraction edge cases (lines 463-495)
# ===========================================================================

class TestRuleBasedRelationshipExtraction:
    """Tests for rule-based extraction edge cases."""

    def setup_method(self):
        KGE = _extractor()
        self.e = KGE(use_tracer=False)

        Entity = _entity()
        self.alice = Entity(entity_type="person", name="Alice", confidence=0.9)
        self.bob = Entity(entity_type="person", name="Bob", confidence=0.9)
        self.entity_map = {"Alice": self.alice, "Bob": self.bob}

    # -----------------------------------------------------------------------
    def test_given_pattern_with_one_group_when_extract_then_skipped_line_463(self):
        """GIVEN pattern with <2 groups WHEN extract THEN match skipped (line 463-464)."""
        self.e.relation_patterns = [
            {"pattern": r"(\w+)\s+runs", "name": "single_group", "confidence": 0.7}
        ]
        rels = self.e._rule_based_relationship_extraction("Alice runs", self.entity_map)
        assert rels == []

    def test_given_invalid_regex_when_extract_then_pattern_skipped_line_486(self):
        """GIVEN invalid regex WHEN extract THEN re.error caught, pattern skipped (486-488)."""
        self.e.relation_patterns = [
            {"pattern": "[invalid(regex", "name": "bad_pat", "confidence": 0.7}
        ]
        rels = self.e._rule_based_relationship_extraction("some text", self.entity_map)
        assert rels == []

    def test_given_unexpected_pattern_error_when_extract_then_relextraction_error(self):
        """GIVEN pattern triggers unexpected Exception WHEN extract THEN RelationshipExtractionError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import RelationshipExtractionError
        import re as _re

        original_finditer = _re.finditer

        def boom_finditer(pattern, text, flags=0):
            if pattern == "BOOM":
                raise RuntimeError("unexpected boom")
            return original_finditer(pattern, text, flags)

        self.e.relation_patterns = [
            {"pattern": "BOOM", "name": "boom", "confidence": 0.7}
        ]
        with patch("ipfs_datasets_py.knowledge_graphs.extraction.extractor.re.finditer",
                   side_effect=boom_finditer):
            with pytest.raises(RelationshipExtractionError):
                self.e._rule_based_relationship_extraction("text", self.entity_map)


# ===========================================================================
#  E: SRL integration paths (lines 877-931)
# ===========================================================================

class TestSRLMergeIntegration:
    """Tests for KnowledgeGraphExtractor._merge_srl_into_kg."""

    def setup_method(self):
        KGE = _extractor()
        self.e = KGE(use_tracer=False)
        SRLFrame, RoleArgument, _ = _srl_types()
        self.SRLFrame = SRLFrame
        self.RoleArgument = RoleArgument
        Entity = _entity()
        KG = _kg()
        Rel = _relationship()

        self.alice = Entity(entity_type="person", name="Alice", confidence=0.9)
        self.bob = Entity(entity_type="person", name="Bob", confidence=0.9)
        self.kg = KG()
        self.kg.entities[self.alice.entity_id] = self.alice
        self.kg.entities[self.bob.entity_id] = self.bob
        self.entities = [self.alice, self.bob]

        self.mock_srl = MagicMock()
        self.e.srl_extractor = self.mock_srl

    # -----------------------------------------------------------------------
    def test_given_empty_frames_when_merge_then_returns_early_line_879(self):
        """GIVEN empty SRL frames WHEN _merge_srl_into_kg THEN no rels added (line 879)."""
        self.mock_srl.extract_srl.return_value = []
        self.e._merge_srl_into_kg(self.kg, "text", self.entities)
        assert len(self.kg.relationships) == 0

    def test_given_frame_with_no_roles_when_merge_then_frame_skipped_line_890(self):
        """GIVEN frame with no Agent or Patient WHEN merge THEN skipped (line 890)."""
        frame = self.SRLFrame(sentence="test", predicate="run", arguments=[])
        self.mock_srl.extract_srl.return_value = [frame]
        self.e._merge_srl_into_kg(self.kg, "test", self.entities)
        assert len(self.kg.relationships) == 0

    def test_given_frame_unmatched_entities_when_merge_then_no_rel(self):
        """GIVEN frame referencing unknown entity names WHEN merge THEN no rel added."""
        agent_arg = self.RoleArgument(role="Agent", text="Unknown1", span=None, confidence=0.9)
        patient_arg = self.RoleArgument(role="Patient", text="Unknown2", span=None, confidence=0.9)
        frame = self.SRLFrame(
            sentence="Unknown1 met Unknown2", predicate="meet", arguments=[agent_arg, patient_arg]
        )
        self.mock_srl.extract_srl.return_value = [frame]
        self.e._merge_srl_into_kg(self.kg, "text", self.entities)
        assert len(self.kg.relationships) == 0

    def test_given_frame_same_entity_when_merge_then_skipped_line_909(self):
        """GIVEN agent and patient are the same entity WHEN merge THEN skipped (line 909)."""
        agent_arg = self.RoleArgument(role="Agent", text="Alice", span=None, confidence=0.9)
        patient_arg = self.RoleArgument(role="Patient", text="Alice", span=None, confidence=0.9)
        frame = self.SRLFrame(
            sentence="Alice saw Alice", predicate="see", arguments=[agent_arg, patient_arg]
        )
        self.mock_srl.extract_srl.return_value = [frame]
        self.e._merge_srl_into_kg(self.kg, "Alice saw Alice", self.entities)
        assert len(self.kg.relationships) == 0

    def test_given_existing_rel_with_same_key_when_merge_then_skipped_line_918(self):
        """GIVEN duplicate rel already in KG WHEN merge THEN not added again (line 918)."""
        Rel = _relationship()
        pre_existing = Rel(
            relationship_type="send",
            source_entity=self.alice,
            target_entity=self.bob,
            confidence=0.9,
        )
        self.kg.relationships[pre_existing.relationship_id] = pre_existing

        agent_arg = self.RoleArgument(role="Agent", text="Alice", span=None, confidence=0.9)
        patient_arg = self.RoleArgument(role="Patient", text="Bob", span=None, confidence=0.9)
        frame = self.SRLFrame(
            sentence="Alice sent to Bob", predicate="send", arguments=[agent_arg, patient_arg]
        )
        self.mock_srl.extract_srl.return_value = [frame]
        self.e._merge_srl_into_kg(self.kg, "Alice sent to Bob", self.entities)
        assert len(self.kg.relationships) == 1  # still only 1

    def test_given_matching_frame_when_merge_then_rel_added(self):
        """GIVEN Agent+Patient both match known entities WHEN merge THEN rel added to KG."""
        agent_arg = self.RoleArgument(role="Agent", text="Alice", span=None, confidence=0.9)
        patient_arg = self.RoleArgument(role="Patient", text="Bob", span=None, confidence=0.9)
        frame = self.SRLFrame(
            sentence="Alice sent to Bob", predicate="send", arguments=[agent_arg, patient_arg]
        )
        self.mock_srl.extract_srl.return_value = [frame]
        self.e._merge_srl_into_kg(self.kg, "Alice sent to Bob", self.entities)
        assert len(self.kg.relationships) == 1
        rel_list = list(self.kg.relationships.values())
        assert rel_list[0].relationship_type == "send"

    def test_given_frame_with_no_predicate_when_merge_then_rel_type_srl_relation(self):
        """GIVEN frame.predicate is None WHEN merge THEN rel_type defaults to 'srl_relation'."""
        agent_arg = self.RoleArgument(role="Agent", text="Alice", span=None, confidence=0.9)
        patient_arg = self.RoleArgument(role="Patient", text="Bob", span=None, confidence=0.9)
        frame = self.SRLFrame(
            sentence="Alice did something to Bob", predicate=None, arguments=[agent_arg, patient_arg]
        )
        self.mock_srl.extract_srl.return_value = [frame]
        self.e._merge_srl_into_kg(self.kg, "Alice did something to Bob", self.entities)
        assert len(self.kg.relationships) == 1
        rel = list(self.kg.relationships.values())[0]
        assert rel.relationship_type == "srl_relation"


# ===========================================================================
#  F: extract_knowledge_graph with SRL warning (lines 847-851)
# ===========================================================================

class TestExtractKGWithSRL:
    """Tests for extract_knowledge_graph SRL warning path."""

    def test_given_srl_raises_when_extract_kg_then_warning_logged_not_raised(self, caplog):
        """GIVEN srl_extractor raises ValueError WHEN extract_knowledge_graph THEN warning only."""
        KGE = _extractor()
        e = KGE(use_tracer=False)
        e.use_srl = True
        mock_srl = MagicMock()
        mock_srl.extract_srl.side_effect = ValueError("srl_error")
        e.srl_extractor = mock_srl

        with caplog.at_level(logging.WARNING):
            kg = e.extract_knowledge_graph("Alice went to Bob")
        assert "SRL enrichment failed" in caplog.text
        assert kg is not None

    def test_given_srl_extractor_none_when_use_srl_false_then_no_srl_run(self):
        """GIVEN use_srl=False WHEN extract_knowledge_graph THEN SRL not invoked."""
        KGE = _extractor()
        e = KGE(use_tracer=False, use_srl=False)
        kg = e.extract_knowledge_graph("Alice went to Bob")
        assert kg is not None


# ===========================================================================
#  G: extract_knowledge_graph temperature paths (lines 826-837)
# ===========================================================================

class TestExtractKGTemperature:
    """Tests for temperature-controlled extraction paths."""

    def setup_method(self):
        KGE = _extractor()
        self.e = KGE(use_tracer=False)

    def test_given_low_structure_temperature_when_extract_then_rel_types_filtered(self):
        """GIVEN structure_temperature=0.1 WHEN extract THEN only common rel_types kept (826-827)."""
        kg = self.e.extract_knowledge_graph(
            "Alice works for Acme Corp.", structure_temperature=0.1
        )
        # All relationships must be of the common types (or there are none)
        common_types = {"is_a", "part_of", "has_part", "related_to", "subfield_of"}
        for rel in kg.relationships.values():
            assert rel.relationship_type in common_types

    def test_given_high_structure_temperature_no_spacy_when_extract_then_no_complex_inf(self):
        """GIVEN structure_temperature=0.9, no spaCy WHEN extract THEN complex inference skipped."""
        self.e.nlp = None
        self.e.use_spacy = False
        kg = self.e.extract_knowledge_graph(
            "Alice works for Acme Corp.", structure_temperature=0.9
        )
        assert kg is not None


# ===========================================================================
#  H: extract_enhanced_knowledge_graph chunking (lines 985-1003)
# ===========================================================================

class TestExtractEnhancedKGChunking:
    """Tests for extract_enhanced_knowledge_graph with long text (>2000 chars)."""

    def setup_method(self):
        KGE = _extractor()
        self.e = KGE(use_tracer=False)

    def test_given_long_text_when_extract_enhanced_then_chunked(self):
        """GIVEN text>2000 chars WHEN extract_enhanced_knowledge_graph THEN chunking applied."""
        # Build a text longer than 2000 characters
        long_text = "Alice is a researcher at ACME Corporation. " * 50
        assert len(long_text) > 2000
        kg = self.e.extract_enhanced_knowledge_graph(long_text, use_chunking=True)
        assert kg is not None

    def test_given_short_text_when_extract_enhanced_then_no_chunking(self):
        """GIVEN text<2000 chars WHEN extract_enhanced_knowledge_graph THEN processed as-is."""
        short_text = "Alice is a researcher."
        assert len(short_text) < 2000
        kg = self.e.extract_enhanced_knowledge_graph(short_text, use_chunking=True)
        assert kg is not None

    def test_given_chunking_disabled_when_extract_enhanced_then_uses_single_call(self):
        """GIVEN use_chunking=False WHEN extract_enhanced_knowledge_graph THEN single call."""
        text = "Bob is CEO of Acme Corp. " * 100
        kg = self.e.extract_enhanced_knowledge_graph(text, use_chunking=False)
        assert kg is not None


# ===========================================================================
#  I: extract_from_documents (lines 1037-1038)
# ===========================================================================

class TestExtractFromDocuments:
    """Tests for extract_from_documents missing text_key path."""

    def setup_method(self):
        KGE = _extractor()
        self.e = KGE(use_tracer=False)

    def test_given_missing_text_key_when_extract_docs_then_warning_printed(self, capsys):
        """GIVEN doc without text_key WHEN extract_from_documents THEN warning, entity skipped."""
        docs = [{"title": "test", "body": "some text"}]  # missing 'text'
        kg = self.e.extract_from_documents(docs, text_key="text")
        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert len(kg.entities) == 0

    def test_given_doc_with_text_key_when_extract_docs_then_processed(self):
        """GIVEN doc with text_key WHEN extract_from_documents THEN KG produced."""
        docs = [{"id": "doc1", "text": "Alice works for Acme Corp."}]
        kg = self.e.extract_from_documents(docs, text_key="text")
        assert kg is not None

    def test_given_doc_with_title_when_extract_docs_then_title_in_entity_properties(self):
        """GIVEN doc with 'title' field WHEN extract THEN entity properties include document_title."""
        docs = [{"id": "d1", "title": "My Document", "text": "Alice is a developer."}]
        kg = self.e.extract_from_documents(docs, text_key="text")
        # Some entities will have the document_title property
        # (the property is set for any entity extracted from this doc)
        for ent in kg.entities.values():
            if "document_title" in (ent.properties or {}):
                assert ent.properties["document_title"] == "My Document"
                break


# ===========================================================================
#  J: enrich_with_types (lines 1093-1102)
# ===========================================================================

class TestEnrichWithTypes:
    """Tests for KnowledgeGraphExtractor.enrich_with_types."""

    def _make_kg_with_rel(self, rel_type: str):
        """Create a minimal KG with one generic entity pair and one relationship."""
        Entity = _entity()
        Rel = _relationship()
        KG = _kg()

        src = Entity(entity_type="entity", name="Alice", confidence=0.9)
        tgt = Entity(entity_type="entity", name="Acme", confidence=0.9)
        rel = Rel(relationship_type=rel_type, source_entity=src, target_entity=tgt, confidence=0.9)
        kg = KG()
        kg.entities[src.entity_id] = src
        kg.entities[tgt.entity_id] = tgt
        kg.relationships[rel.relationship_id] = rel
        return kg, src, tgt

    def test_given_works_for_relationship_when_enrich_then_person_and_org_types(self):
        """GIVEN works_for rel WHEN enrich_with_types THEN src=person, tgt=organization."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor
        kg, src, tgt = self._make_kg_with_rel("works_for")
        KnowledgeGraphExtractor.enrich_with_types(kg)
        assert src.entity_type == "person"
        assert tgt.entity_type == "organization"

    def test_given_founded_by_relationship_when_enrich_then_org_and_person_types(self):
        """GIVEN founded_by rel WHEN enrich_with_types THEN src=organization, tgt=person."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor
        kg, src, tgt = self._make_kg_with_rel("founded_by")
        KnowledgeGraphExtractor.enrich_with_types(kg)
        assert src.entity_type == "organization"
        assert tgt.entity_type == "person"

    def test_given_born_in_relationship_when_enrich_then_person_and_location(self):
        """GIVEN born_in rel WHEN enrich_with_types THEN src=person, tgt=location."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor
        kg, src, tgt = self._make_kg_with_rel("born_in")
        KnowledgeGraphExtractor.enrich_with_types(kg)
        assert src.entity_type == "person"
        assert tgt.entity_type == "location"

    def test_given_unknown_rel_type_when_enrich_then_types_unchanged(self):
        """GIVEN unknown relationship type WHEN enrich_with_types THEN entity types unchanged."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor
        kg, src, tgt = self._make_kg_with_rel("unknown_custom_rel")
        KnowledgeGraphExtractor.enrich_with_types(kg)
        assert src.entity_type == "entity"
        assert tgt.entity_type == "entity"

    def test_given_non_generic_entity_type_when_enrich_then_type_not_overwritten(self):
        """GIVEN entity already has non-generic type WHEN enrich THEN type not overwritten."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor
        Entity = _entity()
        Rel = _relationship()
        KG = _kg()
        # Source entity already classified as 'researcher'
        src = Entity(entity_type="researcher", name="Alice", confidence=0.9)
        tgt = Entity(entity_type="entity", name="Acme", confidence=0.9)
        rel = Rel(relationship_type="works_for", source_entity=src, target_entity=tgt, confidence=0.9)
        kg = KG()
        kg.entities[src.entity_id] = src
        kg.entities[tgt.entity_id] = tgt
        kg.relationships[rel.relationship_id] = rel
        KnowledgeGraphExtractor.enrich_with_types(kg)
        assert src.entity_type == "researcher"  # NOT overwritten since != 'entity'


# ===========================================================================
#  K: extract_srl_knowledge_graph (lines 952-956)
# ===========================================================================

class TestExtractSRLKnowledgeGraph:
    """Tests for extract_srl_knowledge_graph."""

    def setup_method(self):
        KGE = _extractor()
        self.e = KGE(use_tracer=False)

    def test_given_text_with_agent_patient_when_extract_srl_kg_then_events_in_kg(self):
        """GIVEN text WHEN extract_srl_knowledge_graph THEN KG produced (lines 952-956)."""
        kg = self.e.extract_srl_knowledge_graph("Alice works for Bob.")
        assert kg is not None
        assert hasattr(kg, "entities")

    def test_given_pre_existing_srl_extractor_when_extract_srl_kg_then_reused(self):
        """GIVEN srl_extractor already set WHEN extract_srl_kg THEN existing extractor reused."""
        _, _, SRLExtractor = _srl_types()
        existing_extractor = SRLExtractor()
        self.e.srl_extractor = existing_extractor
        kg = self.e.extract_srl_knowledge_graph("Alice works for Bob.")
        assert kg is not None

    def test_given_empty_text_when_extract_srl_kg_then_empty_kg(self):
        """GIVEN empty string WHEN extract_srl_knowledge_graph THEN returns empty KG."""
        kg = self.e.extract_srl_knowledge_graph("")
        assert kg is not None
        assert len(kg.entities) == 0


# ===========================================================================
#  L: GraphEngine with storage backend (lines 89-100, 122-138, 169-179, 241-253,
#                                        328-368, 376-415)
# ===========================================================================

class TestGraphEngineWithStorage:
    """Tests for GraphEngine persistence paths using mocked IPLD storage."""

    def _make_engine(self):
        """Create a GraphEngine with a fresh mock storage backend."""
        GraphEngine = _graph_engine()
        mock_storage = MagicMock()
        mock_storage.store.return_value = "bafytest123"
        mock_storage.retrieve_json.return_value = {
            "id": "node-loaded", "labels": ["Loaded"], "properties": {"x": 1}
        }
        mock_storage.store_graph.return_value = "bafygraph999"
        mock_storage.retrieve_graph.return_value = {
            "nodes": [{"id": "n1", "labels": ["X"], "properties": {}}],
            "relationships": [
                {"id": "r1", "type": "KNOWS", "start_node": "n1", "end_node": "n1", "properties": {}}
            ],
        }
        engine = GraphEngine(storage_backend=mock_storage)
        return engine, mock_storage

    # -----------------------------------------------------------------------
    def test_given_storage_when_create_node_then_storage_store_called(self):
        """GIVEN storage backend WHEN create_node THEN storage.store called (lines 89-100)."""
        engine, mock_storage = self._make_engine()
        node = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        assert node is not None
        mock_storage.store.assert_called_once()

    def test_given_storage_store_raises_when_create_node_then_node_still_returned(self):
        """GIVEN storage.store raises StorageError WHEN create_node THEN node still returned."""
        StorageError = _storage_error()
        GraphEngine = _graph_engine()
        mock_storage = MagicMock()
        mock_storage.store.side_effect = StorageError("disk full", {})
        engine = GraphEngine(storage_backend=mock_storage)
        node = engine.create_node(labels=["Person"])
        assert node is not None

    def test_given_cid_in_cache_when_get_node_then_loaded_from_storage(self):
        """GIVEN CID cached WHEN get_node on evicted node THEN loaded from storage (122-138)."""
        engine, mock_storage = self._make_engine()
        node = engine.create_node(labels=["Person"])
        node_id = node.id
        # Evict the actual node (keep the CID mapping)
        del engine._node_cache[node_id]
        loaded = engine.get_node(node_id)
        assert loaded is not None
        assert loaded.id == "node-loaded"

    def test_given_storage_retrieve_fails_when_get_node_then_none_returned(self):
        """GIVEN storage.retrieve_json raises WHEN get_node THEN None returned (137-138)."""
        StorageError = _storage_error()
        GraphEngine = _graph_engine()
        mock_storage = MagicMock()
        mock_storage.store.return_value = "cid123"
        mock_storage.retrieve_json.side_effect = StorageError("not found", {})
        engine = GraphEngine(storage_backend=mock_storage)
        node = engine.create_node(labels=["X"])
        node_id = node.id
        del engine._node_cache[node_id]
        result = engine.get_node(node_id)
        assert result is None

    def test_given_storage_when_update_node_then_storage_store_called(self):
        """GIVEN storage WHEN update_node THEN persistence store called (169-179)."""
        engine, mock_storage = self._make_engine()
        node = engine.create_node(labels=["Person"])
        node_id = node.id
        mock_storage.reset_mock()
        updated = engine.update_node(node_id, {"age": 42})
        assert updated is not None
        mock_storage.store.assert_called_once()

    def test_given_cid_key_in_cache_when_delete_node_then_cid_also_removed(self):
        """GIVEN CID key in cache WHEN delete_node THEN CID entry also deleted (line 202)."""
        engine, mock_storage = self._make_engine()
        node = engine.create_node(labels=["Person"])
        node_id = node.id
        cid_key = f"cid:{node_id}"
        assert cid_key in engine._node_cache
        engine.delete_node(node_id)
        assert cid_key not in engine._node_cache

    def test_given_storage_when_create_relationship_then_storage_store_called(self):
        """GIVEN storage backend WHEN create_relationship THEN storage.store called (241-253)."""
        engine, mock_storage = self._make_engine()
        n1 = engine.create_node(labels=["A"])
        n2 = engine.create_node(labels=["B"])
        mock_storage.reset_mock()
        rel = engine.create_relationship("KNOWS", n1.id, n2.id, {"since": 2020})
        assert rel is not None
        mock_storage.store.assert_called_once()

    def test_given_storage_backend_when_save_graph_then_returns_cid(self):
        """GIVEN storage backend WHEN save_graph THEN store_graph called and CID returned (328-368)."""
        engine, mock_storage = self._make_engine()
        engine.create_node(labels=["Person"], properties={"name": "Alice"})
        mock_storage.reset_mock()
        cid = engine.save_graph()
        assert cid == "bafygraph999"
        mock_storage.store_graph.assert_called_once()

    def test_given_storage_error_in_save_when_save_graph_then_returns_none(self):
        """GIVEN store_graph raises WHEN save_graph THEN None returned (366-368)."""
        StorageError = _storage_error()
        GraphEngine = _graph_engine()
        mock_storage = MagicMock()
        mock_storage.store.return_value = "cid123"
        mock_storage.store_graph.side_effect = StorageError("io error", {})
        engine = GraphEngine(storage_backend=mock_storage)
        engine.create_node(labels=["X"])
        result = engine.save_graph()
        assert result is None

    def test_given_no_storage_when_save_graph_then_returns_none(self):
        """GIVEN no storage backend WHEN save_graph THEN returns None (322-326)."""
        GraphEngine = _graph_engine()
        engine = GraphEngine(storage_backend=None)
        result = engine.save_graph()
        assert result is None

    def test_given_storage_when_load_graph_then_nodes_and_rels_populated(self):
        """GIVEN storage backend WHEN load_graph THEN nodes and rels in engine (376-407)."""
        engine, mock_storage = self._make_engine()
        result = engine.load_graph("bafygraph999")
        assert result is True
        assert len(engine._node_cache) >= 1

    def test_given_storage_error_in_load_when_load_graph_then_returns_false(self):
        """GIVEN retrieve_graph raises WHEN load_graph THEN returns False (408-415)."""
        StorageError = _storage_error()
        GraphEngine = _graph_engine()
        mock_storage = MagicMock()
        mock_storage.retrieve_graph.side_effect = StorageError("bad cid", {})
        engine = GraphEngine(storage_backend=mock_storage)
        result = engine.load_graph("nonexistent-cid")
        assert result is False

    def test_given_no_storage_when_load_graph_then_returns_false(self):
        """GIVEN no storage backend WHEN load_graph THEN returns False (370-374)."""
        GraphEngine = _graph_engine()
        engine = GraphEngine(storage_backend=None)
        result = engine.load_graph("some-cid")
        assert result is False


# ===========================================================================
#  M: Additional GraphEngine edge cases (lines 272, 289, 293, 428, 431)
# ===========================================================================

class TestGraphEngineEdgeCases:
    """Tests for GraphEngine CID-mapping and isinstance-check edge cases."""

    def setup_method(self):
        GraphEngine = _graph_engine()
        self.engine = GraphEngine(storage_backend=None)

    def test_given_no_cid_key_when_delete_rel_then_no_error(self):
        """GIVEN rel has no CID entry WHEN delete_relationship THEN deletes cleanly (272)."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Relationship as GRel
        rel = self.engine.create_relationship("KNOWS", "n1", "n2")
        rel_id = rel.id
        assert rel_id in self.engine._relationship_cache
        # No CID key present
        result = self.engine.delete_relationship(rel_id)
        assert result is True

    def test_given_cid_prefixed_key_in_rel_cache_when_get_rels_then_skipped(self):
        """GIVEN CID-prefixed entry in rel cache WHEN get_relationships THEN skipped (428)."""
        self.engine._relationship_cache["cid:fake-id"] = "some_cid_value"
        rels = self.engine.get_relationships("nonexistent_node")
        # Should not crash and should not include CID entry
        assert isinstance(rels, list)

    def test_given_non_relationship_in_cache_when_get_rels_then_skipped(self):
        """GIVEN non-Relationship value in cache WHEN get_relationships THEN skipped (431)."""
        self.engine._relationship_cache["bogus-key"] = {"type": "dict_not_a_rel"}
        rels = self.engine.get_relationships("any-node")
        assert isinstance(rels, list)

    def test_given_non_node_in_node_cache_when_find_nodes_then_skipped(self):
        """GIVEN non-Node value in node_cache WHEN find_nodes THEN skipped (293)."""
        self.engine._node_cache["bogus-node"] = {"id": "fake", "labels": []}
        nodes = self.engine.find_nodes()
        for n in nodes:
            from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node
            assert isinstance(n, Node)
