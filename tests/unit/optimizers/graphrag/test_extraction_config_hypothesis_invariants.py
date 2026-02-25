"""Hypothesis-based invariants for ExtractionConfig."""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies
given = hypothesis.given
settings = hypothesis.settings

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig


_word = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=10,
)


@st.composite
def extraction_config_strategy(draw: st.DrawFn) -> ExtractionConfig:
    confidence_threshold = draw(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    max_confidence = draw(
        st.floats(
            min_value=confidence_threshold,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    llm_fallback_threshold = draw(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    return ExtractionConfig(
        confidence_threshold=confidence_threshold,
        max_entities=draw(st.integers(min_value=0, max_value=1000)),
        max_relationships=draw(st.integers(min_value=0, max_value=1000)),
        window_size=draw(st.integers(min_value=1, max_value=20)),
        sentence_window=draw(st.integers(min_value=0, max_value=10)),
        include_properties=draw(st.booleans()),
        domain_vocab=draw(st.dictionaries(keys=_word, values=st.lists(_word, max_size=4), max_size=4)),
        custom_rules=draw(st.lists(st.tuples(_word, _word), max_size=4)),
        llm_fallback_threshold=llm_fallback_threshold,
        min_entity_length=draw(st.integers(min_value=1, max_value=16)),
        stopwords=draw(st.lists(_word, max_size=10)),
        allowed_entity_types=draw(st.lists(_word, max_size=8)),
        max_confidence=max_confidence,
        enable_parallel_inference=draw(st.booleans()),
        max_workers=draw(st.integers(min_value=1, max_value=32)),
    )


@given(extraction_config_strategy())
@settings(max_examples=80)
def test_extraction_config_roundtrip_to_from_dict_is_stable(config: ExtractionConfig) -> None:
    config.validate()
    as_dict = config.to_dict()
    restored = ExtractionConfig.from_dict(as_dict)

    assert restored.to_dict() == as_dict
    restored.validate()


@given(extraction_config_strategy(), extraction_config_strategy())
@settings(max_examples=60)
def test_extraction_config_merge_preserves_validity(
    base_config: ExtractionConfig,
    override_config: ExtractionConfig,
) -> None:
    merged = base_config.merge(override_config)
    merged.validate()

    as_dict = merged.to_dict()
    assert 0.0 <= as_dict["confidence_threshold"] <= as_dict["max_confidence"] <= 1.0
    assert as_dict["window_size"] >= 1
    assert as_dict["min_entity_length"] >= 1
    assert as_dict["max_workers"] >= 1
