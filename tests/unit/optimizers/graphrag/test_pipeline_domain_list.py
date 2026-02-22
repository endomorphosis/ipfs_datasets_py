"""Tests for OntologyPipeline.domain_list property."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_domain_list_contains_known_presets():
    domains = OntologyPipeline().domain_list

    assert "general" in domains
    assert "legal" in domains
    assert "medical" in domains
    assert "technology" in domains
    assert "finance" in domains


def test_domain_list_is_stable_ordered_list():
    domains = OntologyPipeline().domain_list

    assert domains == sorted(domains)
    assert len(domains) == len(set(domains))
