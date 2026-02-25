"""Hypothesis invariants for backend config constructor adapters."""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies
given = hypothesis.given
settings = hypothesis.settings

from ipfs_datasets_py.optimizers.common.unified_config import (
    backend_config_from_constructor_kwargs,
)


_word = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=16,
)


@given(
    provider=_word,
    model=_word,
    timeout=st.floats(min_value=0.1, max_value=120.0, allow_nan=False, allow_infinity=False),
    retries=st.integers(min_value=0, max_value=10),
    threshold=st.integers(min_value=1, max_value=20),
    use_ipfs=st.booleans(),
)
@settings(max_examples=70)
def test_graphrag_constructor_adapter_preserves_config_values(
    provider: str,
    model: str,
    timeout: float,
    retries: int,
    threshold: int,
    use_ipfs: bool,
) -> None:
    result = backend_config_from_constructor_kwargs(
        "graphrag.ontology_generator",
        ipfs_accelerate_config={
            "provider": provider,
            "model": model,
            "timeout_seconds": timeout,
            "max_retries": retries,
            "circuit_failure_threshold": threshold,
        },
        use_ipfs_accelerate=use_ipfs,
    )

    assert result["provider"] == provider
    assert result["model"] == model
    assert result["use_llm"] is use_ipfs
    assert result["timeout_seconds"] == timeout
    assert result["max_retries"] == retries
    assert result["circuit_failure_threshold"] == threshold


@given(
    has_backend=st.booleans(),
    provider=st.one_of(st.none(), _word),
    model=st.one_of(st.none(), _word),
)
@settings(max_examples=60)
def test_logic_constructor_adapter_emits_required_defaults_when_missing(
    has_backend: bool,
    provider: str | None,
    model: str | None,
) -> None:
    cfg: dict[str, object] = {}
    if provider is not None:
        cfg["provider"] = provider
    if model is not None:
        cfg["model"] = model

    result = backend_config_from_constructor_kwargs(
        "logic_theorem_optimizer.unified_optimizer",
        llm_backend=object() if has_backend else None,
        llm_backend_config=cfg,
    )

    assert result["use_llm"] is has_backend
    assert result["timeout_seconds"] == 30.0
    assert result["max_retries"] == 2
    assert result["circuit_failure_threshold"] == 5


@given(source=_word)
@settings(max_examples=50)
def test_unknown_source_adapter_returns_shared_keys(source: str) -> None:
    result = backend_config_from_constructor_kwargs(source)

    for key in (
        "provider",
        "model",
        "use_llm",
        "timeout_seconds",
        "max_retries",
        "circuit_failure_threshold",
    ):
        assert key in result
