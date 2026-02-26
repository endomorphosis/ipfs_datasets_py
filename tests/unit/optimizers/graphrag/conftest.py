"""Shared fixtures for GraphRAG optimizer unit tests."""

from typing import Any, Dict, List, Optional

import pytest


@pytest.fixture
def make_entity():
    """Factory fixture for creating Entity objects with defaults.
    
    Usage:
        def test_foo(make_entity):
            e1 = make_entity("e1")
            e2 = make_entity("e2", confidence=0.9, entity_type="Person")
    """
    def _make(
        entity_id: str,
        confidence: float = 0.8,
        *,
        entity_type: str = "T",
        text: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        source_span: Optional[tuple] = None,
        last_seen: Optional[float] = None,
    ):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        if text is None:
            text = entity_id
        return Entity(
            id=entity_id,
            type=entity_type,
            text=text,
            confidence=confidence,
            properties=properties,
            source_span=source_span,
            last_seen=last_seen,
        )
    return _make


@pytest.fixture
def make_relationship():
    """Factory fixture for creating Relationship objects with defaults.
    
    Usage:
        def test_foo(make_relationship):
            r1 = make_relationship("e1", "e2")
            r2 = make_relationship("e1", "e3", rel_type="knows", confidence=0.95)
    """
    def _make(
        source_id: str,
        target_id: str,
        *,
        rel_type: str = "RELATED",
        rel_id: Optional[str] = None,
        confidence: float = 0.8,
        properties: Optional[Dict[str, Any]] = None,
        direction: str = "unknown",
    ):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        if rel_id is None:
            rel_id = f"rel_{source_id}_{target_id}"
        return Relationship(
            id=rel_id,
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            confidence=confidence,
            properties=properties,
            direction=direction,
        )
    return _make


@pytest.fixture
def make_extraction_result():
    """Factory fixture for creating EntityExtractionResult objects.
    
    Usage:
        def test_foo(make_extraction_result, make_entity):
            result = make_extraction_result([make_entity("e1"), make_entity("e2")])
    """
    def _make(
        entities: Optional[List] = None,
        relationships: Optional[List] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        errors: Optional[List[str]] = None,
    ):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        return EntityExtractionResult(
            entities=entities or [],
            relationships=relationships or [],
            confidence=confidence,
            metadata=metadata or {},
            errors=errors or [],
        )
    return _make


@pytest.fixture
def make_critic_score():
    """Factory fixture for creating CriticScore objects with defaults.
    
    Usage:
        def test_foo(make_critic_score):
            score = make_critic_score()  # All dimensions 0.5
            score2 = make_critic_score(completeness=0.9, consistency=0.8)
    """
    def _make(
        completeness: float = 0.5,
        consistency: float = 0.5,
        clarity: float = 0.5,
        granularity: float = 0.5,
        relationship_coherence: float = 0.5,
        domain_alignment: float = 0.5,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        recommendations: Optional[List[str]] = None,
    ):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        return CriticScore(
            completeness=completeness,
            consistency=consistency,
            clarity=clarity,
            granularity=granularity,
            relationship_coherence=relationship_coherence,
            domain_alignment=domain_alignment,
            metadata=metadata or {},
            recommendations=recommendations or [],
        )
    return _make


@pytest.fixture
def create_test_ontology():
    """Factory fixture for lightweight ontology dictionaries used in batch tests."""

    def _build(
        entity_count: int = 5,
        relationship_count: int = 3,
        *,
        entity_prefix: str = "e",
        relationship_prefix: str = "r",
        include_ontology_id: bool = True,
        ontology_id: str = "test_ontology",
        domain: str = "legal",
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        entities = [
            {
                "id": f"{entity_prefix}{i}",
                "text": f"Entity{i}",
                "type": "Person" if i % 2 == 0 else "Organization",
                "confidence": 0.6 + (i * 0.08),
            }
            for i in range(entity_count)
        ]
        relationships = [
            {
                "id": f"{relationship_prefix}{i}",
                "source_id": f"{entity_prefix}{i % entity_count}",
                "target_id": f"{entity_prefix}{(i + 1) % entity_count}",
                "type": "works_for",
                "confidence": 0.75 + (i * 0.05),
            }
            for i in range(relationship_count)
        ]
        ontology = {
            "entities": entities,
            "relationships": relationships,
            "metadata": {"domain": domain, **(metadata or {})},
        }

        if include_ontology_id:
            ontology["id"] = ontology_id

        return ontology

    return _build
