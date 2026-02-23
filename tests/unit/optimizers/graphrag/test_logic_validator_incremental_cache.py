"""Tests for LogicValidator incremental cache behavior."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


def test_incremental_cache_hits_on_structurally_equal_ontology():
    validator = LogicValidator(use_cache=True)

    ontology = {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice"},
            {"id": "e2", "type": "Organization", "text": "Acme"},
        ],
        "relationships": [
            {"id": "r1", "type": "works_for", "source_id": "e1", "target_id": "e2"}
        ],
        "metadata": {"note": "first"},
    }

    result1 = validator.check_consistency(ontology)
    stats1 = validator.incremental_cache_stats()
    assert stats1["misses"] == 1
    assert stats1["hits"] == 0

    # Same structure, different metadata should hit incremental cache
    ontology2 = {
        "entities": ontology["entities"],
        "relationships": ontology["relationships"],
        "metadata": {"note": "second"},
    }

    result2 = validator.check_consistency(ontology2)
    stats2 = validator.incremental_cache_stats()

    assert result2.is_consistent == result1.is_consistent
    assert stats2["hits"] == 1
    assert stats2["misses"] == 1
