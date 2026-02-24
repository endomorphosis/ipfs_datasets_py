"""Parametrized test suite: Validate CriticScore dimensions are bounded in [0, 1].

This test suite generates 50 random ontologies across different sizes and
complexities, evaluates them with OntologyCritic, and validates that all 6
dimensions (completeness, consistency, clarity, granularity, relationship_coherence,
domain_alignment) are properly bounded in the range [0, 1].

This is a property-based validation that ensures dimension scoring functions
never produce out-of-range values regardless of ontology structure.
"""

import pytest
import random
from typing import List, Dict, Any
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic


def generate_random_ontology(
    entity_count: int,
    relationship_count: int,
    seed: int,
) -> Dict[str, Any]:
    """Generate a random ontology for testing.
    
    Args:
        entity_count: Number of entities to generate
        relationship_count: Number of relationships to generate  
        seed: Random seed for reproducibility
        
    Returns:
        Dictionary with 'entities' and 'relationships' keys
    """
    random.seed(seed)
    
    entities = []
    entity_types = ["Person", "Organization", "Location", "Concept", "Event", 
                    "Date", "Product", "Document", "Law", "Contract"]
    
    for i in range(entity_count):
        entities.append({
            'id': f"entity_{i}",
            'text': f"Entity_{i}_{random.choice(['Alpha', 'Beta', 'Gamma', 'Delta'])}",
            'type': random.choice(entity_types),
            'confidence': random.uniform(0.3, 0.99),
        })
    
    relationships = []
    rel_types = ["is_a", "part_of", "relates_to", "precedes", "caused_by",
                 "located_in", "employed_by", "owns", "cited_in", "mentions"]
    
    for i in range(relationship_count):
        if entity_count > 1:
            source_idx = random.randint(0, entity_count - 1)
            target_idx = random.randint(0, entity_count - 1)
            
            # Avoid self-loops in some cases
            if source_idx != target_idx or random.random() < 0.2:
                relationships.append({
                    'id': f"rel_{i}",
                    'source_id': f"entity_{source_idx}",
                    'target_id': f"entity_{target_idx}",
                    'type': random.choice(rel_types),
                    'confidence': random.uniform(0.4, 0.95),
                })
    
    return {
        'entities': entities,
        'relationships': relationships,
        'metadata': {
            'source': f'test_seed_{seed}',
            'domain': random.choice(['legal', 'medical', 'technical', 'general']),
        }
    }


# Generate 50 random ontologies with varying complexity
# Structure: (entity_count, relationship_count, seed)
RANDOM_ONTOLOGY_PARAMS = [
    # Very small ontologies (1-5 entities)
    (1, 0, 1001), (2, 1, 1002), (3, 2, 1003), (5, 4, 1004), (5, 8, 1005),
    
    # Small ontologies (10-20 entities)
    (10, 5, 2001), (10, 15, 2002), (15, 10, 2003), (20, 25, 2004), (20, 40, 2005),
    
    # Medium ontologies (30-50 entities)
    (30, 20, 3001), (30, 50, 3002), (40, 60, 3003), (50, 75, 3004), (50, 100, 3005),
    
    # Large ontologies (75-100 entities)
    (75, 100, 4001), (75, 150, 4002), (100, 150, 4003), (100, 200, 4004), (100, 250, 4005),
    
    # Sparse graphs (low relationship/entity ratio)
    (50, 10, 5001), (100, 30, 5002), (75, 20, 5003), (60, 15, 5004), (80, 25, 5005),
    
    # Dense graphs (high relationship/entity ratio)
    (20, 80, 6001), (30, 150, 6002), (40, 200, 6003), (25, 120, 6004), (35, 180, 6005),
    
    # Edge cases
    (0, 0, 7001),  # Empty ontology
    (100, 0, 7002),  # Entities only, no relationships
    (10, 50, 7003),  # Few entities, many relationships
    (50, 50, 7004),  # Balanced
    (1, 10, 7005),  # Single entity with many self-referencing rels
    
    # Random mid-range variations
    (25, 30, 8001), (35, 45, 8002), (45, 60, 8003), (55, 70, 8004), (65, 85, 8005),
    (22, 33, 8006), (38, 52, 8007), (48, 68, 8008), (58, 78, 8009), (68, 88, 8010),
    
    # More varied sizes
    (8, 12, 9001), (12, 18, 9002), (18, 27, 9003), (28, 42, 9004), (42, 63, 9005),
]


@pytest.mark.parametrize("entity_count,relationship_count,seed", RANDOM_ONTOLOGY_PARAMS)
def test_critic_score_dimensions_bounded(entity_count, relationship_count, seed):
    """Test that all CriticScore dimensions are bounded in [0, 1] for random ontologies.
    
    This property-based test validates that regardless of ontology structure:
    - completeness ∈ [0, 1]
    - consistency ∈ [0, 1]
    - clarity ∈ [0, 1]
    - granularity ∈ [0, 1]
    - relationship_coherence ∈ [0, 1]
    - domain_alignment ∈ [0, 1]
    - overall (weighted average) ∈ [0, 1]
    """
    # Generate random ontology
    ontology = generate_random_ontology(entity_count, relationship_count, seed)
    
    # Create minimal context
    class Context:
        domain = ontology.get('metadata', {}).get('domain', 'general')
        strategy = 'test'
    
    # Evaluate with critic
    critic = OntologyCritic(use_llm=False)
    score = critic.evaluate_ontology(ontology, Context())
    
    # Validate all dimensions are in [0, 1]
    assert 0.0 <= score.completeness <= 1.0, \
        f"completeness={score.completeness} out of bounds for seed={seed}"
    
    assert 0.0 <= score.consistency <= 1.0, \
        f"consistency={score.consistency} out of bounds for seed={seed}"
    
    assert 0.0 <= score.clarity <= 1.0, \
        f"clarity={score.clarity} out of bounds for seed={seed}"
    
    assert 0.0 <= score.granularity <= 1.0, \
        f"granularity={score.granularity} out of bounds for seed={seed}"
    
    assert 0.0 <= score.relationship_coherence <= 1.0, \
        f"relationship_coherence={score.relationship_coherence} out of bounds for seed={seed}"
    
    assert 0.0 <= score.domain_alignment <= 1.0, \
        f"domain_alignment={score.domain_alignment} out of bounds for seed={seed}"
    
    # Validate overall score (weighted average should also be in [0, 1])
    assert 0.0 <= score.overall <= 1.0, \
        f"overall={score.overall} out of bounds for seed={seed}"
    
    # Additional sanity checks
    assert isinstance(score.completeness, float), "completeness must be float"
    assert isinstance(score.consistency, float), "consistency must be float"
    assert isinstance(score.clarity, float), "clarity must be float"
    assert isinstance(score.granularity, float), "granularity must be float"
    assert isinstance(score.relationship_coherence, float), "relationship_coherence must be float"
    assert isinstance(score.domain_alignment, float), "domain_alignment must be float"
    assert isinstance(score.overall, float), "overall must be float"


def test_critic_score_dimensions_summary():
    """Summary test showing distribution of scores across all 50 ontologies."""
    all_scores = []
    
    for entity_count, relationship_count, seed in RANDOM_ONTOLOGY_PARAMS:
        ontology = generate_random_ontology(entity_count, relationship_count, seed)
        
        class Context:
            domain = ontology.get('metadata', {}).get('domain', 'general')
            strategy = 'test'
        
        critic = OntologyCritic(use_llm=False)
        score = critic.evaluate_ontology(ontology, Context())
        all_scores.append(score)
    
    # Compute summary statistics
    assert len(all_scores) == 50, "Should have evaluated exactly 50 ontologies"
    
    # Check that we have variety in scores (not all identical)
    overall_scores = [s.overall for s in all_scores]
    assert min(overall_scores) < max(overall_scores), "Should have variation in scores"
    
    # Check that all dimensions were exercised across the range
    for dim in ['completeness', 'consistency', 'clarity', 'granularity', 
                'relationship_coherence', 'domain_alignment']:
        dim_scores = [getattr(s, dim) for s in all_scores]
        assert all(0.0 <= score <= 1.0 for score in dim_scores), \
            f"{dim} has out-of-bounds values"
    
    # Log summary (for manual inspection during test runs)
    print(f"\n=== Dimension Summary (50 Random Ontologies) ===")
    print(f"Overall: min={min(overall_scores):.3f}, max={max(overall_scores):.3f}, "
          f"mean={sum(overall_scores)/len(overall_scores):.3f}")
    
    for dim in ['completeness', 'consistency', 'clarity', 'granularity',
                'relationship_coherence', 'domain_alignment']:
        dim_scores = [getattr(s, dim) for s in all_scores]
        print(f"{dim}: min={min(dim_scores):.3f}, max={max(dim_scores):.3f}, "
              f"mean={sum(dim_scores)/len(dim_scores):.3f}")
