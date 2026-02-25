"""Hypothesis invariants for unified domain normalization helpers."""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies
given = hypothesis.given
settings = hypothesis.settings

from ipfs_datasets_py.optimizers.common.unified_config import (
    DomainType,
    domain_type_from_value,
)


_ALIASES = {
    "graphrag": DomainType.GRAPHRAG,
    "graph": DomainType.GRAPHRAG,
    "logic": DomainType.LOGIC,
    "agentic": DomainType.AGENTIC,
    "code": DomainType.CODE,
    "hybrid": DomainType.HYBRID,
}


@given(
    st.sampled_from(list(_ALIASES.keys())),
    st.booleans(),
    st.booleans(),
)
@settings(max_examples=50)
def test_domain_type_from_value_known_aliases_are_case_and_trim_stable(
    alias: str,
    uppercase: bool,
    padded: bool,
) -> None:
    rendered = alias.upper() if uppercase else alias
    if padded:
        rendered = f"  {rendered}  "

    assert domain_type_from_value(rendered) == _ALIASES[alias]


@given(
    st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=1,
        max_size=24,
    ).filter(lambda s: s not in _ALIASES)
)
@settings(max_examples=80)
def test_domain_type_from_value_unknown_strings_default_to_hybrid(value: str) -> None:
    assert domain_type_from_value(value) == DomainType.HYBRID
