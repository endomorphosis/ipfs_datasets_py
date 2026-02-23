"""Shared pytest fixtures for optimizer tests.

This module provides factory fixtures for creating test data across GraphRAG,
logic, and agentic optimizer tests. Centralizing mock creation reduces duplication
and ensures consistency across test files.

Factory Patterns:
    - Fixtures return functions that generate objects with sensible defaults
    - All parameters are optional and have meaningful defaults
    - Use incrementing IDs/names when creating multiple objects
    - Return rich, realistic data structures for integration tests

Usage:
    def test_something(ontology_factory):
        # Get default ontology
        ont = ontology_factory()
        
        # Customize parameters
        ont = ontology_factory(entity_count=10, relationship_count=5)
"""

import logging
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Entity Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def entity_factory():
    """Factory for creating Entity dataclass instances.
    
    Returns:
        Callable that creates Entity objects with customizable parameters.
        
    Example:
        >>> entity = entity_factory(id="e1", text="Alice", type="Person")
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    
    def _create(
        id: str = "e1",
        text: str = "Alice",
        type: str = "Person",
        confidence: float = 0.85,
        start_char: int = 0,
        end_char: Optional[int] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Entity:
        return Entity(
            id=id,
            text=text,
            type=type,
            confidence=confidence,
            start_char=start_char,
            end_char=end_char if end_char is not None else start_char + len(text),
            properties=properties if properties is not None else {},
        )
    
    return _create


@pytest.fixture
def entities_factory(entity_factory):
    """Factory for creating lists of Entity objects.
    
    Returns:
        Callable that creates a list of Entity objects.
        
    Example:
        >>> entities = entities_factory(count=5)  # 5 entities with auto IDs
        >>> entities = entities_factory(types=["Person", "Organization"])
    """
    def _create(count: int = 3, types: Optional[List[str]] = None) -> List:
        if types is None:
            types = ["Person", "Organization", "Location", "Date", "Concept"]
        
        entities = []
        for i in range(count):
            type_name = types[i % len(types)]
            entities.append(
                entity_factory(
                    id=f"e{i+1}",
                    text=f"{type_name} {i+1}",
                    type=type_name,
                    confidence=0.7 + (i * 0.05),  # Gradual confidence increase
                    start_char=i * 10,
                    end_char=(i * 10) + 5 + i,
                )
            )
        return entities
    
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# Relationship Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def relationship_factory():
    """Factory for creating Relationship dataclass instances.
    
    Returns:
        Callable that creates Relationship objects with customizable parameters.
        
    Example:
        >>> rel = relationship_factory(source_id="e1", target_id="e2", type="knows")
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    
    def _create(
        id: str = "r1",
        source_id: str = "e1",
        target_id: str = "e2",
        type: str = "related_to",
        confidence: float = 0.75,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Relationship:
        return Relationship(
            id=id,
            source_id=source_id,
            target_id=target_id,
            type=type,
            confidence=confidence,
            properties=properties if properties is not None else {},
        )
    
    return _create


@pytest.fixture
def relationships_factory(relationship_factory):
    """Factory for creating lists of Relationship objects.
    
    Returns:
        Callable that creates a list of Relationship objects.
        
    Example:
        >>> rels = relationships_factory(count=5)
        >>> rels = relationships_factory(count=3, types=["knows", "works_for"])
    """
    def _create(
        count: int = 2,
        types: Optional[List[str]] = None,
        entity_count: int = 5,
    ) -> List:
        if types is None:
            types = ["related_to", "knows", "works_for", "located_in", "part_of"]
        
        relationships = []
        for i in range(count):
            type_name = types[i % len(types)]
            # Create relationships between existing entities (circular pattern)
            source_idx = i % entity_count
            target_idx = (i + 1) % entity_count
            
            relationships.append(
                relationship_factory(
                    id=f"r{i+1}",
                    source_id=f"e{source_idx+1}",
                    target_id=f"e{target_idx+1}",
                    type=type_name,
                    confidence=0.65 + (i * 0.05),
                )
            )
        return relationships
    
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# Ontology Dict Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def ontology_dict_factory():
    """Factory for creating ontology dictionaries (plain dict format).
    
    Returns:
        Callable that creates ontology dicts with entities and relationships.
        
    Example:
        >>> ont = ontology_dict_factory()  # Default 3 entities, 2 relationships
        >>> ont = ontology_dict_factory(entity_count=10, relationship_count=5)
        >>> ont = ontology_dict_factory(domain="legal", metadata={"source": "test"})
    """
    def _create(
        entity_count: int = 3,
        relationship_count: int = 2,
        domain: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
        entity_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if entity_types is None:
            entity_types = ["Person", "Organization", "Location", "Date", "Concept"]
        
        # Build entities
        entities = []
        for i in range(entity_count):
            entity_type = entity_types[i % len(entity_types)]
            entities.append({
                "id": f"e{i+1}",
                "text": f"{entity_type} {i+1}",
                "type": entity_type,
                "confidence": 0.7 + (i * 0.03),
                "properties": {},
            })
        
        # Build relationships
        relationships = []
        rel_types = ["related_to", "knows", "works_for", "located_in", "part_of"]
        for i in range(relationship_count):
            rel_type = rel_types[i % len(rel_types)]
            source_idx = i % entity_count
            target_idx = (i + 1) % entity_count
            
            relationships.append({
                "id": f"r{i+1}",
                "source_id": f"e{source_idx+1}",
                "target_id": f"e{target_idx+1}",
                "type": rel_type,
                "confidence": 0.65 + (i * 0.05),
            })
        
        ontology = {
            "entities": entities,
            "relationships": relationships,
        }
        
        # Add metadata if provided
        if metadata is not None or domain != "general":
            ontology["metadata"] = metadata if metadata is not None else {}
            if domain != "general":
                ontology["metadata"]["domain"] = domain
        
        return ontology
    
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# CriticScore Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def critic_score_factory():
    """Factory for creating CriticScore instances.
    
    Returns:
        Callable that creates CriticScore objects with customizable dimensions.
        
    Example:
        >>> score = critic_score_factory()  # All dimensions ~0.80
        >>> score = critic_score_factory(overall=0.95, completeness=0.90)
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    
    def _create(
        completeness: float = 0.80,
        consistency: float = 0.82,
        clarity: float = 0.78,
        granularity: float = 0.81,
        relationship_coherence: float = 0.79,
        domain_alignment: float = 0.83,
        strengths: Optional[List[str]] = None,
        weaknesses: Optional[List[str]] = None,
        recommendations: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CriticScore:
        return CriticScore(
            completeness=completeness,
            consistency=consistency,
            clarity=clarity,
            granularity=granularity,
            relationship_coherence=relationship_coherence,
            domain_alignment=domain_alignment,
            strengths=strengths if strengths is not None else ["clear entity names", "good type coverage"],
            weaknesses=weaknesses if weaknesses is not None else ["missing properties", "sparse relationships"],
            recommendations=recommendations if recommendations is not None else [
                "add entity properties",
                "infer more relationships",
            ],
            metadata=metadata if metadata is not None else {},
        )
    
    return _create


@pytest.fixture
def mock_feedback_factory():
    """Factory for creating Mock feedback objects (for use with mock critics).
    
    Returns:
        Callable that creates Mock objects with CriticScore-like attributes.
        
    Example:
        >>> feedback = mock_feedback_factory(overall=0.75)
        >>> assert feedback.overall == 0.75
    """
    def _create(
        overall: float = 0.80,
        completeness: float = 0.80,
        consistency: float = 0.82,
        clarity: float = 0.78,
        granularity: float = 0.81,
        relationship_coherence: float = 0.79,
        domain_alignment: float = 0.83,
        recommendations: Optional[List[str]] = None,
    ) -> Mock:
        feedback = Mock()
        feedback.overall = overall
        feedback.completeness = completeness
        feedback.consistency = consistency
        feedback.clarity = clarity
        feedback.granularity = granularity
        feedback.relationship_coherence = relationship_coherence
        feedback.domain_alignment = domain_alignment
        feedback.recommendations = recommendations if recommendations is not None else [
            "add missing entity properties",
            "normalize entity types",
        ]
        return feedback
    
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# Configuration Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def extraction_config_factory():
    """Factory for creating ExtractionConfig instances.
    
    Returns:
        Callable that creates ExtractionConfig objects with sensible defaults.
        
    Example:
        >>> config = extraction_config_factory()  # All defaults
        >>> config = extraction_config_factory(confidence_threshold=0.75, max_entities=100)
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
    
    def _create(
        confidence_threshold: float = 0.5,
        max_entities: int = 0,
        max_relationships: int = 0,
        window_size: int = 5,
        include_properties: bool = True,
        domain_vocab: Optional[Dict[str, List[str]]] = None,
        custom_rules: Optional[List[tuple]] = None,
        llm_fallback_threshold: float = 0.0,
        min_entity_length: int = 2,
        stopwords: Optional[List[str]] = None,
        allowed_entity_types: Optional[List[str]] = None,
        max_confidence: float = 1.0,
    ) -> ExtractionConfig:
        return ExtractionConfig(
            confidence_threshold=confidence_threshold,
            max_entities=max_entities,
            max_relationships=max_relationships,
            window_size=window_size,
            include_properties=include_properties,
            domain_vocab=domain_vocab if domain_vocab is not None else {},
            custom_rules=custom_rules if custom_rules is not None else [],
            llm_fallback_threshold=llm_fallback_threshold,
            min_entity_length=min_entity_length,
            stopwords=stopwords if stopwords is not None else [],
            allowed_entity_types=allowed_entity_types if allowed_entity_types is not None else [],
            max_confidence=max_confidence,
        )
    
    return _create


@pytest.fixture
def generation_context_factory(extraction_config_factory):
    """Factory for creating OntologyGenerationContext instances.
    
    Returns:
        Callable that creates OntologyGenerationContext objects.
        
    Example:
        >>> ctx = generation_context_factory(domain="legal")
        >>> ctx = generation_context_factory(data_source="contract.pdf", domain="legal")
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType,
    )
    
    def _create(
        data_source: str = "test_data",
        data_type: str = "text",
        domain: str = "general",
        extraction_strategy: Optional[str] = None,
        config: Optional[Any] = None,
    ) -> OntologyGenerationContext:
        if extraction_strategy is None:
            extraction_strategy = ExtractionStrategy.RULE_BASED
        elif isinstance(extraction_strategy, str):
            extraction_strategy = ExtractionStrategy(extraction_strategy)
        
        if isinstance(data_type, str):
            data_type = DataType(data_type)
        
        if config is None:
            config = extraction_config_factory()
        
        return OntologyGenerationContext(
            data_source=data_source,
            data_type=data_type,
            domain=domain,
            extraction_strategy=extraction_strategy,
            config=config,
        )
    
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# Component Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def ontology_generator_factory():
    """Factory for creating OntologyGenerator instances.
    
    Returns:
        Callable that creates OntologyGenerator objects.
        
    Example:
        >>> generator = ontology_generator_factory()
        >>> generator = ontology_generator_factory(llm_backend=my_backend)
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    
    def _create(
        ipfs_accelerate_config: Optional[Dict[str, Any]] = None,
        use_ipfs_accelerate: bool = False,  # Default to False for tests
        logger: Optional[Any] = None,
        llm_backend: Optional[Any] = None,
    ) -> OntologyGenerator:
        return OntologyGenerator(
            ipfs_accelerate_config=ipfs_accelerate_config,
            use_ipfs_accelerate=use_ipfs_accelerate,
            logger=logger,
            llm_backend=llm_backend,
        )
    
    return _create


@pytest.fixture
def ontology_critic_factory():
    """Factory for creating OntologyCritic instances.
    
    Returns:
        Callable that creates OntologyCritic objects.
        
    Example:
        >>> critic = ontology_critic_factory()
        >>> critic = ontology_critic_factory(use_llm=False)
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    
    def _create(
        backend_config: Optional[Any] = None,
        use_llm: bool = False,
        logger: Optional[Any] = None,
    ) -> OntologyCritic:
        return OntologyCritic(
            backend_config=backend_config,
            use_llm=use_llm,
            logger=logger,
        )
    
    return _create


@pytest.fixture
def ontology_optimizer_factory():
    """Factory for creating OntologyOptimizer instances.
    
    Returns:
        Callable that creates OntologyOptimizer objects.
        
    Example:
        >>> optimizer = ontology_optimizer_factory()
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    
    def _create() -> OntologyOptimizer:
        return OntologyOptimizer()
    
    return _create


@pytest.fixture
def ontology_pipeline_factory(ontology_generator_factory, ontology_critic_factory):
    """Factory for creating OntologyPipeline instances.
    
    Returns:
        Callable that creates OntologyPipeline objects.
        
    Example:
        >>> pipeline = ontology_pipeline_factory()
        >>> pipeline = ontology_pipeline_factory(domain="legal", use_llm=False)
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    
    def _create(
        domain: str = "general",
        use_llm: bool = False,
        max_rounds: int = 3,
        logger: Optional[Any] = None,
    ) -> OntologyPipeline:
        return OntologyPipeline(
            domain=domain,
            use_llm=use_llm,
            max_rounds=max_rounds,
            logger=logger,
        )
    
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# Result Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def extraction_result_factory(entities_factory, relationships_factory):
    """Factory for creating EntityExtractionResult instances.
    
    Returns:
        Callable that creates EntityExtractionResult objects.
        
    Example:
        >>> result = extraction_result_factory(entity_count=5, relationship_count=3)
    """
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    
    def _create(
        entity_count: int = 3,
        relationship_count: int = 2,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EntityExtractionResult:
        return EntityExtractionResult(
            entities=entities_factory(count=entity_count),
            relationships=relationships_factory(count=relationship_count, entity_count=entity_count),
            metadata=metadata if metadata is not None else {},
        )
    
    return _create


@pytest.fixture
def pipeline_result_factory(ontology_dict_factory, critic_score_factory):
    """Factory for creating PipelineResult instances (for OntologyPipeline).
    
    Returns:
        Callable that creates PipelineResult objects.
        
    Example:
        >>> result = pipeline_result_factory(entity_count=10, score_overall=0.85)
        >>> result = pipeline_result_factory(entity_count=5, rel_count=3)  # alias
    """
    def _create(
        entity_count: int = 5,
        relationship_count: Optional[int] = None,
        rel_count: Optional[int] = None,  # Alias for relationship_count
        score_overall: Optional[float] = None,
        score_val: Optional[float] = None,  # Alias for score_overall
        actions_applied: Optional[List[str]] = None,
        actions: Optional[List[str]] = None,  # Alias for actions_applied
    ):
        from unittest.mock import Mock
        
        # Handle parameter aliases
        if relationship_count is None and rel_count is not None:
            relationship_count = rel_count
        elif relationship_count is None:
            relationship_count = 3
        
        if score_overall is None and score_val is not None:
            score_overall = score_val
        elif score_overall is None:
            score_overall = 0.75
        
        if actions_applied is None and actions is not None:
            actions_applied = actions
        elif actions_applied is None:
            actions_applied = []
        
        ontology = ontology_dict_factory(
            entity_count=entity_count,
            relationship_count=relationship_count,
        )
        
        # Create mock score
        score = Mock()
        score.overall = score_overall
        score.completeness = score_overall + 0.02
        score.consistency = score_overall - 0.03
        
        # Mock PipelineResult structure
        result = Mock()
        result.ontology = ontology
        result.score = score
        result.entities = ontology["entities"]
        result.relationships = ontology["relationships"]
        result.actions_applied = actions_applied
        
        return result
    
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# TypedDict Fixtures (for ontology_types.py structures)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def entity_typeddict_factory():
    """Factory for creating Entity TypedDict instances (from ontology_types.py).
    
    These are plain dicts conforming to the Entity TypedDict schema, used for
    JSON serialization and API contracts.
    
    Returns:
        Callable that creates Entity TypedDict dicts.
        
    Example:
        >>> entity = entity_typeddict_factory(id="e1", text="Alice")
        >>> entities = [entity_typeddict_factory(id=f"e{i}") for i in range(5)]
    """
    def _create(
        id: str = "e1",
        text: str = "Alice",
        type: str = "Person",
        confidence: float = 0.85,
        properties: Optional[Dict[str, Any]] = None,
        context: Optional[str] = None,
        source_span: Optional[tuple] = None,
    ) -> Dict[str, Any]:
        entity = {
            "id": id,
            "text": text,
            "type": type,
            "confidence": confidence,
        }
        if properties is not None:
            entity["properties"] = properties
        if context is not None:
            entity["context"] = context
        if source_span is not None:
            entity["source_span"] = source_span
        return entity
    
    return _create


@pytest.fixture
def relationship_typeddict_factory():
    """Factory for creating Relationship TypedDict instances (from ontology_types.py).
    
    Returns:
        Callable that creates Relationship TypedDict dicts.
        
    Example:
        >>> rel = relationship_typeddict_factory(source_id="e1", target_id="e2")
    """
    def _create(
        id: str = "r1",
        source_id: str = "e1",
        target_id: str = "e2",
        type: str = "related_to",
        confidence: float = 0.75,
        properties: Optional[Dict[str, Any]] = None,
        context: Optional[str] = None,
        distance: Optional[int] = None,
    ) -> Dict[str, Any]:
        relationship = {
            "id": id,
            "source_id": source_id,
            "target_id": target_id,
            "type": type,
            "confidence": confidence,
        }
        if properties is not None:
            relationship["properties"] = properties
        if context is not None:
            relationship["context"] = context
        if distance is not None:
            relationship["distance"] = distance
        return relationship
    
    return _create


@pytest.fixture
def critic_score_typeddict_factory():
    """Factory for creating CriticScore TypedDict instances (from ontology_types.py).
    
    Creates a dict conforming to the CriticScore TypedDict schema.
    
    Returns:
        Callable that creates CriticScore TypedDict dicts.
        
    Example:
        >>> score = critic_score_typeddict_factory()
        >>> score = critic_score_typeddict_factory(overall=0.95, completeness=0.90)
    """
    def _create(
        overall: float = 0.80,
        completeness: Optional[float] = None,
        consistency: Optional[float] = None,
        clarity: Optional[float] = None,
        granularity: Optional[float] = None,
        domain_alignment: Optional[float] = None,
        relationship_coherence: Optional[float] = None,
        dimensions: Optional[List[Dict[str, Any]]] = None,
        recommendations: Optional[List[str]] = None,
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        score = {"overall": overall}
        
        if completeness is not None:
            score["completeness"] = completeness
        if consistency is not None:
            score["consistency"] = consistency
        if clarity is not None:
            score["clarity"] = clarity
        if granularity is not None:
            score["granularity"] = granularity
        if domain_alignment is not None:
            score["domain_alignment"] = domain_alignment
        if relationship_coherence is not None:
            score["relationship_coherence"] = relationship_coherence
        if dimensions is not None:
            score["dimensions"] = dimensions
        if recommendations is not None:
            score["recommendations"] = recommendations
        if timestamp is not None:
            score["timestamp"] = timestamp
        
        return score
    
    return _create


@pytest.fixture
def ontology_session_typeddict_factory(ontology_dict_factory, critic_score_typeddict_factory):
    """Factory for creating OntologySession TypedDict instances (from ontology_types.py).
    
    Returns:
        Callable that creates OntologySession TypedDict dicts.
        
    Example:
        >>> session = ontology_session_typeddict_factory(session_id="sess1")
        >>> session = ontology_session_typeddict_factory(current_round=3, convergence_threshold=0.85)
    """
    def _create(
        session_id: str = "sess1",
        data_source: str = "test_data.txt",
        domain: str = "general",
        current_round: int = 1,
        rounds: Optional[List[Dict[str, Any]]] = None,
        critic_scores: Optional[List[Dict[str, Any]]] = None,
        convergence_threshold: float = 0.85,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        import time
        
        session = {
            "session_id": session_id,
            "data_source": data_source,
            "domain": domain,
            "current_round": current_round,
            "convergence_threshold": convergence_threshold,
        }
        
        if rounds is not None:
            session["rounds"] = rounds
        
        if critic_scores is not None:
            session["critic_scores"] = critic_scores
        elif current_round > 1:
            # Generate mock critic scores for each round
            session["critic_scores"] = [
                critic_score_typeddict_factory(overall=0.70 + (i * 0.05))
                for i in range(current_round)
            ]
        
        if start_time_ms is not None:
            session["start_time_ms"] = start_time_ms
        else:
            session["start_time_ms"] = int(time.time() * 1000)
        
        if end_time_ms is not None:
            session["end_time_ms"] = end_time_ms
        
        return session
    
    return _create


@pytest.fixture
def feedback_record_typeddict_factory():
    """Factory for creating FeedbackRecord TypedDict instances (from ontology_types.py).
    
    Creates structured feedback for ontology refinement.
    
    Returns:
        Callable that creates FeedbackRecord TypedDict dicts.
        
    Example:
        >>> feedback = feedback_record_typeddict_factory()
        >>> feedback = feedback_record_typeddict_factory(
        ...     entities_to_remove=["e1", "e2"],
        ...     entities_to_merge=[["e3", "e4"]]
        ... )
    """
    def _create(
        entities_to_remove: Optional[List[str]] = None,
        entities_to_merge: Optional[List[List[str]]] = None,
        relationships_to_remove: Optional[List[str]] = None,
        relationships_to_add: Optional[List[Dict[str, Any]]] = None,
        type_corrections: Optional[Dict[str, str]] = None,
        confidence_floor: Optional[float] = None,
    ) -> Dict[str, Any]:
        feedback = {}
        
        if entities_to_remove is not None:
            feedback["entities_to_remove"] = entities_to_remove
        if entities_to_merge is not None:
            feedback["entities_to_merge"] = entities_to_merge
        if relationships_to_remove is not None:
            feedback["relationships_to_remove"] = relationships_to_remove
        if relationships_to_add is not None:
            feedback["relationships_to_add"] = relationships_to_add
        if type_corrections is not None:
            feedback["type_corrections"] = type_corrections
        if confidence_floor is not None:
            feedback["confidence_floor"] = confidence_floor
        
        return feedback
    
    return _create
