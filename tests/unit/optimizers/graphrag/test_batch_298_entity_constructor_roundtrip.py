"""Entity constructor round-trip regression tests."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity


def test_entity_constructor_roundtrip_from_to_dict_identity() -> None:
    original = Entity(
        id="e-1",
        type="Person",
        text="Alice",
        confidence=0.87,
        properties={"role": "engineer"},
        source_span=(2, 17),
        last_seen=1700000000.5,
    )

    reconstructed = Entity(**original.to_dict())

    assert reconstructed == original


def test_entity_constructor_normalizes_source_span_list_to_tuple() -> None:
    entity = Entity(
        id="e-2",
        type="Org",
        text="Acme",
        source_span=[5, 11],  # type: ignore[list-item]
    )

    assert entity.source_span == (5, 11)
