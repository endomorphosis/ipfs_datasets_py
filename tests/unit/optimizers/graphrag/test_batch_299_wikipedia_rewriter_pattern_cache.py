"""Regression tests for Wikipedia rewriter pattern precompilation."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.wikipedia_optimizer import (
    WikipediaGraphRAGQueryRewriter,
)


def test_wikipedia_rewriter_init_does_not_compile_patterns_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patterns should already be compiled at module import time.
    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.wikipedia_optimizer.re.compile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("compile called")),
    )

    rewriter = WikipediaGraphRAGQueryRewriter()
    assert "definition" in rewriter.domain_patterns


def test_wikipedia_rewriter_pattern_detection_still_works() -> None:
    rewriter = WikipediaGraphRAGQueryRewriter()

    detected = rewriter._detect_query_pattern("What is quantum entanglement")
    assert detected is not None

    pattern_type, entities = detected
    assert pattern_type == "definition"
    assert entities == ["quantum entanglement"]

