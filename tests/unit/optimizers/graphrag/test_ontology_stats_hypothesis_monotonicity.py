"""Hypothesis invariants for ontology stats monotonic behavior."""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies
given = hypothesis.given
settings = hypothesis.settings

from ipfs_datasets_py.optimizers.graphrag.ontology_stats import compute_relationship_stats


@st.composite
def ontology_pair_with_extra_relationships(
    draw: st.DrawFn,
) -> tuple[dict, dict]:
    entity_count = draw(st.integers(min_value=2, max_value=12))
    entity_ids = [f"e{i}" for i in range(entity_count)]
    entities = [{"id": entity_id, "type": "Entity"} for entity_id in entity_ids]

    base_relationship_count = draw(st.integers(min_value=0, max_value=20))
    extra_relationship_count = draw(st.integers(min_value=1, max_value=20))

    rel_type = draw(st.sampled_from(["related_to", "depends_on", "contains"]))

    def _relationships(n: int) -> list[dict]:
        rels: list[dict] = []
        for idx in range(n):
            src = entity_ids[idx % entity_count]
            tgt = entity_ids[(idx + 1) % entity_count]
            rels.append(
                {
                    "id": f"r{idx}",
                    "source_id": src,
                    "target_id": tgt,
                    "type": rel_type,
                }
            )
        return rels

    base = {
        "entities": entities,
        "relationships": _relationships(base_relationship_count),
    }
    expanded = {
        "entities": entities,
        "relationships": _relationships(base_relationship_count + extra_relationship_count),
    }
    return base, expanded


@given(ontology_pair_with_extra_relationships())
@settings(max_examples=80)
def test_relationship_stats_monotonicity_under_additional_edges(
    ontology_pair: tuple[dict, dict],
) -> None:
    base, expanded = ontology_pair
    base_stats = compute_relationship_stats(base)
    expanded_stats = compute_relationship_stats(expanded)

    assert expanded_stats.total_count >= base_stats.total_count
    assert expanded_stats.avg_relationships_per_entity >= base_stats.avg_relationships_per_entity
    assert 0.0 <= base_stats.relationship_density <= 1.0
    assert 0.0 <= expanded_stats.relationship_density <= 1.0
    assert expanded_stats.relationship_density >= base_stats.relationship_density

