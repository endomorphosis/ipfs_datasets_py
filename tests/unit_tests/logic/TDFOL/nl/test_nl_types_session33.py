"""
Session 33 - Tests for TDFOL NL dataclasses and non-spaCy methods.

Covers:
- PatternType enum (tdfol_nl_patterns)
- Pattern dataclass construction, __hash__, equality
- PatternMatch dataclass construction
- PatternMatcher.get_patterns_by_type, get_pattern_count, _deduplicate_matches (via object.__new__ bypass)
- EntityType enum (tdfol_nl_preprocessor)
- Entity, TemporalExpression, DependencyRelation, ProcessedDocument dataclasses
- NLPreprocessor._extract_temporal_expressions and .extract_agents_actions_objects (bypass)
- ParseOptions/ParseResult dataclasses (tdfol_nl_api)
- NLParser/parse_natural_language ImportError when spaCy not installed
"""

import pytest

from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import (
    PatternType,
    Pattern,
    PatternMatch,
    PatternMatcher,
)
from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_preprocessor import (
    EntityType,
    Entity,
    TemporalExpression,
    DependencyRelation,
    ProcessedDocument,
    NLPreprocessor,
)
from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import (
    ParseOptions,
    ParseResult,
    NLParser,
    parse_natural_language,
    parse_natural_language_batch,
)


# ---------------------------------------------------------------------------
# PatternType enum
# ---------------------------------------------------------------------------

class TestPatternTypeEnum:
    """Test PatternType enum values."""

    def test_all_six_types_defined(self):
        types = list(PatternType)
        assert len(types) == 6

    def test_enum_values(self):
        assert PatternType.UNIVERSAL_QUANTIFICATION.value == "universal_quantification"
        assert PatternType.OBLIGATION.value == "obligation"
        assert PatternType.PERMISSION.value == "permission"
        assert PatternType.PROHIBITION.value == "prohibition"
        assert PatternType.TEMPORAL.value == "temporal"
        assert PatternType.CONDITIONAL.value == "conditional"


# ---------------------------------------------------------------------------
# Pattern dataclass
# ---------------------------------------------------------------------------

class TestPatternDataclass:
    """Test Pattern dataclass construction and behaviour."""

    def test_basic_construction(self):
        p = Pattern(name="test_pattern", type=PatternType.OBLIGATION)
        assert p.name == "test_pattern"
        assert p.type == PatternType.OBLIGATION

    def test_optional_fields_default(self):
        p = Pattern(name="p", type=PatternType.PERMISSION)
        assert p.text_pattern is None
        assert p.token_pattern is None
        assert p.description == ""
        assert p.examples == []
        assert p.metadata == {}

    def test_construction_with_all_fields(self):
        p = Pattern(
            name="full",
            type=PatternType.TEMPORAL,
            text_pattern=r"within\s+\d+\s+days?",
            token_pattern=[{"LOWER": "within"}],
            description="time pattern",
            examples=["within 30 days"],
            metadata={"priority": 1},
        )
        assert p.text_pattern is not None
        assert p.description == "time pattern"
        assert p.examples == ["within 30 days"]
        assert p.metadata["priority"] == 1

    def test_hash_consistency(self):
        p = Pattern(name="p1", type=PatternType.OBLIGATION)
        assert hash(p) == hash(p)

    def test_hash_same_name_type(self):
        p1 = Pattern(name="same", type=PatternType.OBLIGATION)
        p2 = Pattern(name="same", type=PatternType.OBLIGATION)
        assert hash(p1) == hash(p2)

    def test_hash_different_name(self):
        p1 = Pattern(name="a", type=PatternType.OBLIGATION)
        p2 = Pattern(name="b", type=PatternType.OBLIGATION)
        assert hash(p1) != hash(p2)

    def test_hash_different_type(self):
        p1 = Pattern(name="p", type=PatternType.OBLIGATION)
        p2 = Pattern(name="p", type=PatternType.PERMISSION)
        assert hash(p1) != hash(p2)

    def test_pattern_usable_in_set(self):
        """Pattern must be hashable to be stored in a set."""
        p1 = Pattern(name="p1", type=PatternType.OBLIGATION)
        p2 = Pattern(name="p2", type=PatternType.PERMISSION)
        s = {p1, p2, p1}  # p1 should appear only once
        assert len(s) == 2


# ---------------------------------------------------------------------------
# PatternMatch dataclass
# ---------------------------------------------------------------------------

class TestPatternMatchDataclass:
    """Test PatternMatch dataclass construction."""

    def _make_pattern(self):
        return Pattern(name="test", type=PatternType.OBLIGATION)

    def test_basic_construction(self):
        p = self._make_pattern()
        pm = PatternMatch(
            pattern=p,
            span=(0, 4),
            text="must",
            entities={"agent": "Alice"},
            confidence=0.9,
        )
        assert pm.text == "must"
        assert pm.confidence == 0.9
        assert pm.entities["agent"] == "Alice"

    def test_optional_fields_default(self):
        p = self._make_pattern()
        pm = PatternMatch(
            pattern=p, span=(0, 5), text="test", entities={}, confidence=0.8
        )
        assert pm.spacy_span is None
        assert pm.metadata == {}

    def test_span_tuple(self):
        p = self._make_pattern()
        pm = PatternMatch(pattern=p, span=(10, 20), text="pay", entities={}, confidence=0.7)
        assert pm.span == (10, 20)
        assert pm.span[0] == 10
        assert pm.span[1] == 20


# ---------------------------------------------------------------------------
# PatternMatcher non-spaCy methods (via object.__new__ bypass)
# ---------------------------------------------------------------------------

class TestPatternMatcherBypassMethods:
    """Test PatternMatcher methods that don't require spaCy."""

    def _make_matcher_with_patterns(self):
        matcher = object.__new__(PatternMatcher)
        matcher.patterns = [
            Pattern(name="obl1", type=PatternType.OBLIGATION),
            Pattern(name="obl2", type=PatternType.OBLIGATION),
            Pattern(name="perm1", type=PatternType.PERMISSION),
            Pattern(name="temp1", type=PatternType.TEMPORAL),
        ]
        return matcher

    def test_get_patterns_by_type_obligation(self):
        matcher = self._make_matcher_with_patterns()
        result = matcher.get_patterns_by_type(PatternType.OBLIGATION)
        assert len(result) == 2
        assert all(p.type == PatternType.OBLIGATION for p in result)

    def test_get_patterns_by_type_empty(self):
        matcher = self._make_matcher_with_patterns()
        result = matcher.get_patterns_by_type(PatternType.PROHIBITION)
        assert result == []

    def test_get_pattern_count_returns_all_types(self):
        matcher = self._make_matcher_with_patterns()
        counts = matcher.get_pattern_count()
        assert counts[PatternType.OBLIGATION] == 2
        assert counts[PatternType.PERMISSION] == 1
        assert counts[PatternType.TEMPORAL] == 1
        assert counts[PatternType.PROHIBITION] == 0

    def test_deduplicate_matches_empty(self):
        matcher = object.__new__(PatternMatcher)
        result = matcher._deduplicate_matches([])
        assert result == []

    def test_deduplicate_matches_no_overlap(self):
        matcher = object.__new__(PatternMatcher)
        p = Pattern(name="p", type=PatternType.OBLIGATION)
        m1 = PatternMatch(pattern=p, span=(0, 5), text="must", entities={}, confidence=0.9)
        m2 = PatternMatch(pattern=p, span=(10, 15), text="shall", entities={}, confidence=0.8)
        result = matcher._deduplicate_matches([m1, m2])
        assert len(result) == 2

    def test_deduplicate_matches_with_overlap(self):
        """GIVEN overlapping spans THEN lower confidence match is removed."""
        matcher = object.__new__(PatternMatcher)
        p = Pattern(name="p", type=PatternType.OBLIGATION)
        m1 = PatternMatch(pattern=p, span=(0, 10), text="must pay", entities={}, confidence=0.9)
        m2 = PatternMatch(pattern=p, span=(5, 15), text="pay taxes", entities={}, confidence=0.8)
        result = matcher._deduplicate_matches([m1, m2])
        assert len(result) == 1
        assert result[0].text == "must pay"

    def test_deduplicate_matches_single(self):
        matcher = object.__new__(PatternMatcher)
        p = Pattern(name="p", type=PatternType.OBLIGATION)
        m = PatternMatch(pattern=p, span=(0, 5), text="must", entities={}, confidence=0.9)
        result = matcher._deduplicate_matches([m])
        assert result == [m]


# ---------------------------------------------------------------------------
# EntityType enum
# ---------------------------------------------------------------------------

class TestEntityTypeEnum:
    """Test EntityType enum values."""

    def test_all_seven_types(self):
        assert len(list(EntityType)) == 7

    def test_enum_values(self):
        assert EntityType.AGENT.value == "agent"
        assert EntityType.ACTION.value == "action"
        assert EntityType.OBJECT.value == "object"
        assert EntityType.TIME.value == "time"
        assert EntityType.CONDITION.value == "condition"
        assert EntityType.MODALITY.value == "modality"
        assert EntityType.UNKNOWN.value == "unknown"


# ---------------------------------------------------------------------------
# Entity dataclass
# ---------------------------------------------------------------------------

class TestEntityDataclass:
    """Test Entity dataclass construction and hashing."""

    def test_basic_construction(self):
        e = Entity(text="contractors", type=EntityType.AGENT, start=4, end=15)
        assert e.text == "contractors"
        assert e.type == EntityType.AGENT

    def test_optional_fields_default(self):
        e = Entity(text="pay", type=EntityType.ACTION, start=0, end=3)
        assert e.lemma is None
        assert e.metadata == {}

    def test_with_lemma_and_metadata(self):
        e = Entity(text="paying", type=EntityType.ACTION, start=0, end=6,
                   lemma="pay", metadata={"pos": "VERB"})
        assert e.lemma == "pay"
        assert e.metadata["pos"] == "VERB"

    def test_hash_consistency(self):
        e = Entity(text="t", type=EntityType.AGENT, start=0, end=1)
        assert hash(e) == hash(e)

    def test_hash_same_fields(self):
        e1 = Entity(text="t", type=EntityType.AGENT, start=0, end=1)
        e2 = Entity(text="t", type=EntityType.AGENT, start=0, end=1)
        assert hash(e1) == hash(e2)

    def test_usable_in_set(self):
        e1 = Entity(text="A", type=EntityType.AGENT, start=0, end=1)
        e2 = Entity(text="B", type=EntityType.AGENT, start=2, end=3)
        s = {e1, e2, e1}
        assert len(s) == 2


# ---------------------------------------------------------------------------
# TemporalExpression dataclass
# ---------------------------------------------------------------------------

class TestTemporalExpressionDataclass:
    """Test TemporalExpression construction."""

    def test_basic_construction(self):
        t = TemporalExpression(text="within 30 days", type="deadline", value="30 days")
        assert t.text == "within 30 days"
        assert t.type == "deadline"
        assert t.value == "30 days"

    def test_start_end_defaults(self):
        t = TemporalExpression(text="always", type="adverb")
        assert t.start == 0
        assert t.end == 0

    def test_with_positions(self):
        t = TemporalExpression(text="always", type="adverb", value="always", start=10, end=16)
        assert t.start == 10
        assert t.end == 16


# ---------------------------------------------------------------------------
# DependencyRelation dataclass
# ---------------------------------------------------------------------------

class TestDependencyRelationDataclass:
    """Test DependencyRelation construction."""

    def test_construction(self):
        d = DependencyRelation(head="pay", dependent="taxes", relation="dobj")
        assert d.head == "pay"
        assert d.dependent == "taxes"
        assert d.relation == "dobj"


# ---------------------------------------------------------------------------
# ProcessedDocument dataclass
# ---------------------------------------------------------------------------

class TestProcessedDocumentDataclass:
    """Test ProcessedDocument construction."""

    def test_basic_construction(self):
        doc = ProcessedDocument(
            text="All contractors must pay taxes.",
            sentences=["All contractors must pay taxes."],
            entities=[],
            temporal=[],
            modalities=["must"],
            dependencies=[],
        )
        assert doc.text == "All contractors must pay taxes."
        assert doc.modalities == ["must"]

    def test_optional_fields(self):
        doc = ProcessedDocument(text="", sentences=[], entities=[], temporal=[], modalities=[], dependencies=[])
        assert doc.spacy_doc is None
        assert doc.metadata == {}


# ---------------------------------------------------------------------------
# NLPreprocessor._extract_temporal_expressions (via bypass)
# ---------------------------------------------------------------------------

class TestNLPreprocessorTemporalExtraction:
    """Test NLPreprocessor._extract_temporal_expressions without spaCy."""

    def _make_preprocessor(self):
        """Create NLPreprocessor bypassing spaCy __init__."""
        preprocessor = object.__new__(NLPreprocessor)
        preprocessor.temporal_patterns = [
            (r'within\s+(\d+)\s+(day|week|month|year)s?', 'deadline'),
            (r'after\s+(\d+)\s+(day|week|month|year)s?', 'deadline'),
            (r'before\s+(\d+)\s+(day|week|month|year)s?', 'deadline'),
            (r'for\s+(\d+)\s+(day|week|month|year)s?', 'duration'),
            (r'every\s+(\d+)\s+(day|week|month|year)s?', 'frequency'),
        ]
        return preprocessor

    def test_extract_deadline_within(self):
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("within 30 days")
        assert len(result) == 1
        assert result[0].type == "deadline"
        assert result[0].value == "30 days"

    def test_extract_deadline_after(self):
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("after 1 week")
        assert len(result) == 1
        assert result[0].type == "deadline"

    def test_extract_duration(self):
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("for 5 years")
        assert len(result) == 1
        assert result[0].type == "duration"
        assert result[0].value == "5 years"

    def test_extract_frequency(self):
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("every 2 months")
        assert len(result) == 1
        assert result[0].type == "frequency"

    def test_extract_temporal_adverb_always(self):
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("must always comply")
        adverbs = [t for t in result if t.type == "adverb"]
        assert any(t.value == "always" for t in adverbs)

    def test_extract_temporal_adverb_eventually(self):
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("must eventually pay")
        adverbs = [t for t in result if t.type == "adverb"]
        assert any(t.value == "eventually" for t in adverbs)

    def test_extract_no_match_returns_empty(self):
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("The contractor pays taxes.")
        assert result == []

    def test_extract_multiple_expressions(self):
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("within 30 days and always")
        assert len(result) == 2

    def test_singular_duration_unit(self):
        """GIVEN count=1 THEN value is singular."""
        preprocessor = self._make_preprocessor()
        result = preprocessor._extract_temporal_expressions("within 1 day")
        assert len(result) == 1
        assert result[0].value == "1 day"


# ---------------------------------------------------------------------------
# NLPreprocessor.extract_agents_actions_objects (via bypass)
# ---------------------------------------------------------------------------

class TestExtractAgentsActionsObjects:
    """Test extract_agents_actions_objects without spaCy."""

    def _make_doc_with_entities(self):
        agent = Entity(text="contractors", type=EntityType.AGENT, start=4, end=15)
        action = Entity(text="pay", type=EntityType.ACTION, start=20, end=23)
        obj = Entity(text="taxes", type=EntityType.OBJECT, start=24, end=29)
        return ProcessedDocument(
            text="All contractors must pay taxes.",
            sentences=["All contractors must pay taxes."],
            entities=[agent, action, obj],
            temporal=[],
            modalities=["must"],
            dependencies=[],
        )

    def test_extracts_agents(self):
        preprocessor = object.__new__(NLPreprocessor)
        doc = self._make_doc_with_entities()
        agents, actions, objects = preprocessor.extract_agents_actions_objects(doc)
        assert len(agents) == 1
        assert agents[0].text == "contractors"

    def test_extracts_actions(self):
        preprocessor = object.__new__(NLPreprocessor)
        doc = self._make_doc_with_entities()
        agents, actions, objects = preprocessor.extract_agents_actions_objects(doc)
        assert len(actions) == 1
        assert actions[0].text == "pay"

    def test_extracts_objects(self):
        preprocessor = object.__new__(NLPreprocessor)
        doc = self._make_doc_with_entities()
        agents, actions, objects = preprocessor.extract_agents_actions_objects(doc)
        assert len(objects) == 1
        assert objects[0].text == "taxes"

    def test_empty_entities(self):
        preprocessor = object.__new__(NLPreprocessor)
        doc = ProcessedDocument(text="", sentences=[], entities=[], temporal=[], modalities=[], dependencies=[])
        agents, actions, objects = preprocessor.extract_agents_actions_objects(doc)
        assert agents == []
        assert actions == []
        assert objects == []


# ---------------------------------------------------------------------------
# NLPreprocessor.__init__ ImportError
# ---------------------------------------------------------------------------

class TestNLPreprocessorInitError:
    """Test NLPreprocessor raises ImportError when spaCy not available."""

    def test_init_raises_when_spacy_not_available(self):
        """GIVEN spaCy not installed THEN NLPreprocessor() raises ImportError."""
        # In this test environment, spaCy is not installed
        from ipfs_datasets_py.logic.TDFOL.nl.utils import HAVE_SPACY
        if not HAVE_SPACY:
            with pytest.raises(ImportError):
                NLPreprocessor()
        else:
            pytest.skip("spaCy is installed — skip ImportError test")


# ---------------------------------------------------------------------------
# ParseOptions dataclass
# ---------------------------------------------------------------------------

class TestParseOptionsDataclass:
    """Test ParseOptions dataclass."""

    def test_defaults(self):
        opts = ParseOptions()
        assert opts.min_confidence == 0.5
        assert opts.include_metadata is True
        assert opts.resolve_context is True
        assert opts.max_formulas is None
        assert opts.enable_caching is True

    def test_custom_values(self):
        opts = ParseOptions(min_confidence=0.8, max_formulas=5, enable_caching=False)
        assert opts.min_confidence == 0.8
        assert opts.max_formulas == 5
        assert opts.enable_caching is False


# ---------------------------------------------------------------------------
# ParseResult dataclass
# ---------------------------------------------------------------------------

class TestParseResultDataclass:
    """Test ParseResult dataclass."""

    def test_minimal_construction(self):
        result = ParseResult(success=True)
        assert result.success is True
        assert result.num_formulas == 0
        assert result.formulas == []
        assert result.errors == []
        assert result.warnings == []

    def test_with_text(self):
        result = ParseResult(success=False, text="hello world")
        assert result.text == "hello world"
        assert result.success is False

    def test_parse_time_default(self):
        result = ParseResult(success=True)
        assert result.parse_time_ms == 0.0


# ---------------------------------------------------------------------------
# NLParser ImportError
# ---------------------------------------------------------------------------

class TestNLParserImportError:
    """Test NLParser raises ImportError when spaCy not available."""

    def test_nlparser_raises_import_error(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import DEPENDENCIES_AVAILABLE
        if not DEPENDENCIES_AVAILABLE:
            with pytest.raises(ImportError):
                NLParser()
        else:
            pytest.skip("Dependencies are available — skip ImportError test")

    def test_parse_natural_language_raises_import_error(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import DEPENDENCIES_AVAILABLE
        if not DEPENDENCIES_AVAILABLE:
            with pytest.raises(ImportError):
                parse_natural_language("All contractors must pay taxes.")
        else:
            pytest.skip("Dependencies are available — skip ImportError test")

    def test_parse_natural_language_batch_raises_import_error(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import DEPENDENCIES_AVAILABLE
        if not DEPENDENCIES_AVAILABLE:
            with pytest.raises(ImportError):
                parse_natural_language_batch(["All contractors must pay taxes."])
        else:
            pytest.skip("Dependencies are available — skip ImportError test")
