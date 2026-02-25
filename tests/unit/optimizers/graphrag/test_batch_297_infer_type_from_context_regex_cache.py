"""Regression tests for _infer_type_from_context regex caching behavior."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag import ontology_generator as ont_gen_mod
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator


def _make_generator() -> OntologyGenerator:
    return OntologyGenerator()


def test_infer_type_from_context_matches_directional_pattern() -> None:
    generator = _make_generator()

    rel_type, confidence = generator._infer_type_from_context(
        context_window="Alice hired Bob to lead engineering.",
        e1_text="Alice",
        e2_text="Bob",
        e1_type="person",
        e2_type="person",
    )

    assert rel_type == "employs"
    assert confidence == pytest.approx(0.75)


def test_infer_type_from_context_matches_bidirectional_pattern() -> None:
    generator = _make_generator()

    rel_type, confidence = generator._infer_type_from_context(
        context_window="Acme collaborates with Globex on a new battery.",
        e1_text="Acme",
        e2_text="Globex",
        e1_type="organization",
        e2_type="organization",
    )

    assert rel_type == "partners_with"
    assert confidence == pytest.approx(0.70)


def test_infer_type_from_context_uses_precompiled_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = _make_generator()

    # If _infer_type_from_context tried to compile at runtime, this would fail.
    monkeypatch.setattr(
        ont_gen_mod.re,
        "compile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("compile called")),
    )

    rel_type, _confidence = generator._infer_type_from_context(
        context_window="Alice hired Bob.",
        e1_text="Alice",
        e2_text="Bob",
        e1_type="person",
        e2_type="person",
    )

    assert rel_type == "employs"

