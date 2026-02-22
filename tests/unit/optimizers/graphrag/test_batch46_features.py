"""Tests for batch-46 features: allowed_entity_types, extract_entities_from_file,
property-based critic score bounds, and export_to_graphml parametrized."""
from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ── ExtractionConfig.allowed_entity_types ────────────────────────────────────

class TestAllowedEntityTypes:
    @pytest.fixture
    def gen(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return OntologyGenerator(use_ipfs_accelerate=False)

    def _ctx(self, allowed=None):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            ExtractionConfig, OntologyGenerationContext, DataType, ExtractionStrategy,
        )
        cfg = ExtractionConfig(allowed_entity_types=allowed or [])
        return OntologyGenerationContext(
            data_source="t", data_type=DataType.TEXT, domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED, config=cfg,
        )

    def test_empty_allowed_permits_all(self, gen):
        ctx = self._ctx(allowed=[])
        result = gen.extract_entities("Dr Alice visited London.", ctx)
        types = {e.type for e in result.entities}
        assert len(types) > 0

    def test_whitelist_restricts_types(self, gen):
        ctx = self._ctx(allowed=["Person"])
        result = gen.extract_entities("Dr Smith visited London last year.", ctx)
        for e in result.entities:
            assert e.type == "Person", f"Unexpected type: {e.type}"

    def test_non_matching_whitelist_returns_empty(self, gen):
        ctx = self._ctx(allowed=["NonExistentType"])
        result = gen.extract_entities("Dr Smith and Alice went to London.", ctx)
        assert len(result.entities) == 0

    def test_to_dict_includes_allowed_entity_types(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(allowed_entity_types=["Person", "Organization"])
        assert cfg.to_dict()["allowed_entity_types"] == ["Person", "Organization"]

    def test_from_dict_reads_allowed_entity_types(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig.from_dict({"allowed_entity_types": ["Concept"]})
        assert cfg.allowed_entity_types == ["Concept"]

    def test_from_dict_default_empty(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        assert ExtractionConfig.from_dict({}).allowed_entity_types == []


# ── OntologyGenerator.extract_entities_from_file ─────────────────────────────

class TestExtractEntitiesFromFile:
    @pytest.fixture
    def gen(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return OntologyGenerator(use_ipfs_accelerate=False)

    @pytest.fixture
    def ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            ExtractionConfig, OntologyGenerationContext, DataType, ExtractionStrategy,
        )
        return OntologyGenerationContext(
            data_source="file", data_type=DataType.TEXT, domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(),
        )

    def test_reads_file_and_extracts(self, gen, ctx, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("Dr Alice and Mr Jones visited London last year.", encoding="utf-8")
        result = gen.extract_entities_from_file(str(f), ctx)
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        assert isinstance(result, EntityExtractionResult)

    def test_empty_file_returns_no_entities(self, gen, ctx, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        result = gen.extract_entities_from_file(str(f), ctx)
        assert result.entities == []

    def test_missing_file_raises_oserror(self, gen, ctx):
        with pytest.raises(OSError):
            gen.extract_entities_from_file("/no/such/file.txt", ctx)


# ── Property-based: OntologyCritic scores in [0, 1] ──────────────────────────

@st.composite
def _random_ontology(draw):
    """Generate a random but structurally valid ontology dict."""
    n_ents = draw(st.integers(0, 8))
    ent_types = draw(st.lists(
        st.sampled_from(["Person", "Organization", "Location", "Concept", "Event"]),
        min_size=max(n_ents, 1), max_size=max(n_ents, 1),
    ))
    entities = [
        {
            "id": f"e{i}",
            "type": ent_types[i],
            "text": draw(st.text(min_size=2, max_size=20, alphabet=st.characters(
                whitelist_categories=("Ll", "Lu"),
            ))),
            "confidence": draw(st.floats(0.0, 1.0)),
        }
        for i in range(n_ents)
    ]
    n_rels = draw(st.integers(0, max(n_ents, 1)))
    rel_types = ["related_to", "is_a", "part_of"]
    relationships = []
    if entities:
        for j in range(n_rels):
            src = draw(st.sampled_from([e["id"] for e in entities]))
            tgt = draw(st.sampled_from([e["id"] for e in entities]))
            relationships.append({
                "id": f"r{j}",
                "source_id": src,
                "target_id": tgt,
                "type": draw(st.sampled_from(rel_types)),
            })
    return {"entities": entities, "relationships": relationships}


class TestCriticScoreBounds:
    @pytest.fixture
    def critic(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        return OntologyCritic()

    @pytest.fixture
    def ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerationContext, DataType, ExtractionStrategy,
        )
        return OntologyGenerationContext(
            data_source="t", data_type=DataType.TEXT, domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )

    @given(ontology=_random_ontology())
    @settings(max_examples=30, deadline=5000, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_all_scores_in_unit_interval(self, ontology, critic, ctx):
        score = critic.evaluate_ontology(ontology, ctx)
        for dim in ("completeness", "consistency", "clarity", "granularity", "domain_alignment", "overall"):
            val = getattr(score, dim)
            assert 0.0 <= val <= 1.0, f"{dim}={val} out of [0,1] for ontology={ontology}"


# ── Parametrized export_to_graphml ───────────────────────────────────────────

@pytest.mark.parametrize("n_ents,n_rels", [
    (0, 0),
    (1, 0),
    (3, 2),
    (10, 5),
    (20, 15),
])
def test_export_graphml_with_various_sizes(n_ents, n_rels):
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    opt = OntologyOptimizer()
    ents = [{"id": f"e{i}", "text": f"entity{i}", "type": "T"} for i in range(n_ents)]
    rels = [
        {"id": f"r{i}", "source_id": f"e{i % max(n_ents, 1)}", "target_id": f"e{(i+1) % max(n_ents, 1)}", "type": "rel"}
        for i in range(n_rels)
    ] if n_ents > 0 else []
    result = opt.export_to_graphml(ontology={"entities": ents, "relationships": rels})
    assert "graphml" in result
    assert result.startswith("<?xml")
    # Verify entity count
    assert result.count('<node ') == n_ents
    assert result.count('<edge ') == n_rels
