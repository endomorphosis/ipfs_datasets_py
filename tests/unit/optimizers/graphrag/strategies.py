"""Hypothesis strategies for optimizer test helpers.

Provides reusable ``@st.composite`` strategies for generating valid instances
of common optimizer types.  Import these in any test file that needs
property-based inputs.

Usage::

    from tests.unit.optimizers.graphrag.strategies import valid_extraction_config

    @given(config=valid_extraction_config())
    def test_something(config):
        ...
"""
from __future__ import annotations

from hypothesis import strategies as st


@st.composite
def valid_extraction_config(draw) -> "ExtractionConfig":  # type: ignore[return]
    """Generate a valid, fully-constrained :class:`ExtractionConfig`.

    All generated configs satisfy the documented invariants:
    - ``confidence_threshold`` in (0.0, 1.0]
    - ``max_entities`` >= 1
    - ``max_relationships`` >= 0
    - ``window_size`` >= 1
    - ``min_entity_length`` >= 1
    - ``llm_fallback_threshold`` in [0.0, 1.0]
    - ``stopwords`` is a list of non-empty lowercase strings
    - ``allowed_entity_types`` is a list of non-empty strings
    - ``domain_vocab`` maps str → list[str]
    - ``custom_rules`` is a list of `(pattern, ent_type)` tuples
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig

    confidence_threshold = draw(st.floats(min_value=0.01, max_value=1.0, allow_nan=False))
    max_entities = draw(st.integers(min_value=1, max_value=500))
    max_relationships = draw(st.integers(min_value=0, max_value=500))
    window_size = draw(st.integers(min_value=1, max_value=20))
    include_properties = draw(st.booleans())
    min_entity_length = draw(st.integers(min_value=1, max_value=10))
    llm_fallback_threshold = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))

    _word = st.text(
        alphabet=st.characters(whitelist_categories=("Ll",)),
        min_size=2, max_size=12,
    )
    stopwords = draw(st.lists(_word, min_size=0, max_size=10))
    allowed_entity_types = draw(
        st.lists(
            st.sampled_from(["Person", "Organization", "Location", "Event", "Concept"]),
            min_size=0, max_size=5,
            unique=True,
        )
    )
    domain_vocab = draw(
        st.dictionaries(
            keys=_word,
            values=st.lists(_word, min_size=0, max_size=5),
            min_size=0, max_size=3,
        )
    )
    # custom_rules: list of (pattern_str, entity_type) tuples
    _ent_types = st.sampled_from(["Person", "Organization", "Location", "Event", "Concept"])
    custom_rules = draw(
        st.lists(
            st.tuples(_word, _ent_types),
            min_size=0, max_size=3,
        )
    )

    return ExtractionConfig(
        confidence_threshold=confidence_threshold,
        max_entities=max_entities,
        max_relationships=max_relationships,
        window_size=window_size,
        include_properties=include_properties,
        domain_vocab=domain_vocab,
        custom_rules=custom_rules,
        llm_fallback_threshold=llm_fallback_threshold,
        min_entity_length=min_entity_length,
        stopwords=stopwords,
        allowed_entity_types=list(allowed_entity_types),
    )


@st.composite
def valid_entity(draw) -> "Entity":  # type: ignore[return]
    """Generate a valid :class:`Entity` instance.

    All generated entities satisfy documented constraints:
    - ``id`` is a non-empty string
    - ``type`` is one of the known entity types
    - ``text`` is a non-empty string
    - ``confidence`` is in [0.0, 1.0]
    - ``properties`` is a dict with string keys
    - ``source_span`` is either None or a (start, end) tuple with start < end

    Returns:
        A randomly-generated Entity instance.
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity

    entity_id = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc")),
        min_size=1, max_size=20,
    ))
    entity_type = draw(st.sampled_from([
        "Person", "Organization", "Location", "Event", "Concept",
        "Obligation", "Date", "Legal", "Medical", "Technical"
    ]))
    text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "P", "Zs")),
        min_size=1, max_size=100,
    ))
    confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    
    # Properties: dict with string keys and various JSON-compatible values
    properties = draw(st.dictionaries(
        keys=st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd")),
            min_size=1, max_size=20,
        ),
        values=st.one_of(
            st.none(),
            st.booleans(),
            st.integers(min_value=-1000000, max_value=1000000),
            st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            st.text(max_size=50),
        ),
        min_size=0, max_size=5,
    ))
    
    # source_span: either None or (start, end) with start < end
    has_span = draw(st.booleans())
    if has_span:
        start = draw(st.integers(min_value=0, max_value=10000))
        length = draw(st.integers(min_value=1, max_value=200))
        source_span = (start, start + length)
    else:
        source_span = None

    return Entity(
        id=entity_id,
        type=entity_type,
        text=text,
        confidence=confidence,
        properties=properties,
        source_span=source_span,
    )
