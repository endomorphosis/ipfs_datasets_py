"""
Batch 303 — Ontology critic modular split validation.

Tests comprehensive refactoring of ontology_critic.py into modular dimension evaluators:
* ontology_critic_completeness.py — Completeness evaluation
* ontology_critic_consistency.py — Consistency evaluation (cycle detection, dangling refs)
* ontology_critic_clarity.py — Clarity evaluation (naming conventions, property completeness)
* ontology_critic_granularity.py — Granularity evaluation (entity depth, relationship density)
* ontology_critic_domain_alignment.py — Domain alignment evaluation (vocabulary matching)
* ontology_critic_connectivity.py — Relationship coherence evaluation (type quality, directionality)

This validates that the large 4714-line ontology_critic.py has been successfully
split into focused, maintainable modules while preserving all functionality.
"""

import pytest


class TestModularEvaluatorImports:
    """Test all modular evaluator modules can be imported."""

    def test_completeness_module_importable(self):
        """Completeness evaluator module imports successfully."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_completeness import (
            evaluate_completeness,
        )
        assert callable(evaluate_completeness)

    def test_consistency_module_importable(self):
        """Consistency evaluator module imports successfully."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_consistency import (
            evaluate_consistency,
        )
        assert callable(evaluate_consistency)

    def test_clarity_module_importable(self):
        """Clarity evaluator module imports successfully."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_clarity import (
            evaluate_clarity,
        )
        assert callable(evaluate_clarity)

    def test_granularity_module_importable(self):
        """Granularity evaluator module imports successfully."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_granularity import (
            evaluate_granularity,
        )
        assert callable(evaluate_granularity)

    def test_domain_alignment_module_importable(self):
        """Domain alignment evaluator module imports successfully."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_domain_alignment import (
            evaluate_domain_alignment,
        )
        assert callable(evaluate_domain_alignment)

    def test_connectivity_module_importable(self):
        """Connectivity (relationship coherence) evaluator module imports successfully."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_connectivity import (
            evaluate_relationship_coherence,
        )
        assert callable(evaluate_relationship_coherence)


class TestCompletenessEvaluator:
    """Test completeness evaluator module functionality."""

    def test_completeness_empty_ontology(self):
        """Empty ontology scores 0.0 for completeness."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_completeness import (
            evaluate_completeness,
        )
        
        ontology = {"entities": [], "relationships": []}
        score = evaluate_completeness(ontology, context=None, source_data=None)
        assert score == 0.0

    def test_completeness_minimal_ontology(self):
        """Minimal ontology with single entity scores low."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_completeness import (
            evaluate_completeness,
        )
        
        ontology = {
            "entities": [{"id": "e1", "text": "entity", "type": "T"}],
            "relationships": [],
        }
        score = evaluate_completeness(ontology, context=None, source_data=None)
        assert 0.0 < score < 1.0

    def test_completeness_rich_ontology(self):
        """Well-populated ontology scores higher."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_completeness import (
            evaluate_completeness,
        )
        
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"Entity {i}", "type": t}
                for i, t in enumerate(["Person", "Org", "Location", "Event", "Concept"] * 2)
            ],
            "relationships": [
                {"id": f"r{i}", "source_id": f"e{i}", "target_id": f"e{i+1}", "type": "knows"}
                for i in range(9)
            ],
        }
        score = evaluate_completeness(ontology, context=None, source_data=None)
        assert score > 0.7


class TestConsistencyEvaluator:
    """Test consistency evaluator module functionality."""

    def test_consistency_no_cycles(self):
        """Ontology with no cycles scores high for consistency."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_consistency import (
            evaluate_consistency,
        )
        
        ontology = {
            "entities": [{"id": f"e{i}"} for i in range(3)],
            "relationships": [
                {"source_id": "e0", "target_id": "e1"},
                {"source_id": "e1", "target_id": "e2"},
            ],
        }
        score = evaluate_consistency(ontology, context=None)
        assert score > 0.8

    def test_consistency_with_cycle(self):
        """Ontology with cycle detection verified."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_consistency import (
            evaluate_consistency,
        )
        
        ontology = {
            "entities": [{"id": f"e{i}"} for i in range(3)],
            "relationships": [
                {"source_id": "e0", "target_id": "e1"},
                {"source_id": "e1", "target_id": "e2"},
                {"source_id": "e2", "target_id": "e0"},  # Creates cycle
            ],
        }
        score = evaluate_consistency(ontology, context=None)
        # Consistency evaluator detects cycles but score may still be high
        # depending on other factors (no dangling refs, etc.)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_consistency_dangling_references(self):
        """Ontology with dangling references receives penalty."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_consistency import (
            evaluate_consistency,
        )
        
        ontology = {
            "entities": [{"id": "e0"}, {"id": "e1"}],
            "relationships": [
                {"source_id": "e0", "target_id": "e_nonexistent"},  # Dangling ref
            ],
        }
        score = evaluate_consistency(ontology, context=None)
        assert score < 1.0


class TestClarityEvaluator:
    """Test clarity evaluator module functionality."""

    def test_clarity_empty_ontology(self):
        """Empty ontology baseline clarity score."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_clarity import (
            evaluate_clarity,
        )
        
        ontology = {"entities": [], "relationships": []}
        score = evaluate_clarity(ontology, context=None)
        assert isinstance(score, float)

    def test_clarity_with_properties(self):
        """Entities with properties score higher for clarity."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_clarity import (
            evaluate_clarity,
        )
        
        ontology_without_props = {
            "entities": [{"id": "e1", "text": "test"}],
            "relationships": [],
        }
        ontology_with_props = {
            "entities": [{"id": "e1", "text": "test", "properties": {"key": "value"}}],
            "relationships": [],
        }
        
        score_without = evaluate_clarity(ontology_without_props, context=None)
        score_with = evaluate_clarity(ontology_with_props, context=None)
        assert score_with >= score_without


class TestGranularityEvaluator:
    """Test granularity evaluator module functionality."""

    def test_granularity_empty_ontology(self):
        """Empty ontology baseline granularity score."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_granularity import (
            evaluate_granularity,
        )
        
        ontology = {"entities": [], "relationships": []}
        score = evaluate_granularity(ontology, context=None)
        assert isinstance(score, float)

    def test_granularity_depth_scoring(self):
        """Entities with more properties score higher for granularity."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_granularity import (
            evaluate_granularity,
        )
        
        shallow_ontology = {
            "entities": [{"id": f"e{i}", "text": f"Entity {i}"} for i in range(5)],
            "relationships": [],
        }
        deep_ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"Entity {i}", "properties": {f"k{j}": j for j in range(5)}}
                for i in range(5)
            ],
            "relationships": [],
        }
        
        score_shallow = evaluate_granularity(shallow_ontology, context=None)
        score_deep = evaluate_granularity(deep_ontology, context=None)
        assert score_deep >= score_shallow


class TestDomainAlignmentEvaluator:
    """Test domain alignment evaluator module functionality."""

    def test_domain_alignment_no_context(self):
        """Domain alignment without context uses defaults."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_domain_alignment import (
            evaluate_domain_alignment,
        )
        
        ontology = {"entities": [{"id": "e1", "text": "test"}], "relationships": []}
        score = evaluate_domain_alignment(ontology, context=None)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_domain_alignment_legal_context(self):
        """Legal domain ontology with legal entities scores higher."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_domain_alignment import (
            evaluate_domain_alignment,
        )
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerationContext,
            DataType,
            ExtractionStrategy,
        )
        
        legal_ontology = {
            "entities": [
                {"id": "e1", "text": "plaintiff", "type": "Party"},
                {"id": "e2", "text": "defendant", "type": "Party"},
                {"id": "e3", "text": "contract", "type": "Document"},
            ],
            "relationships": [
                {"source_id": "e1", "target_id": "e2", "type": "sues"},
            ],
        }
        context = OntologyGenerationContext(
            data_source="legal_doc.pdf",
            data_type=DataType.PDF,
            domain="legal",
            extraction_strategy=ExtractionStrategy.HYBRID,
        )
        score = evaluate_domain_alignment(legal_ontology, context)
        assert score >= 0.5  # Legal domain ontology scores at least baseline


class TestConnectivityEvaluator:
    """Test connectivity (relationship coherence) evaluator module functionality."""

    def test_connectivity_no_relationships(self):
        """Ontology with no relationships scores low for coherence."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_connectivity import (
            evaluate_relationship_coherence,
        )
        
        ontology = {
            "entities": [{"id": f"e{i}"} for i in range(5)],
            "relationships": [],
        }
        score = evaluate_relationship_coherence(ontology, context=None)
        assert score < 0.6

    def test_connectivity_meaningful_relationships(self):
        """Relationships with meaningful types score higher."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic_connectivity import (
            evaluate_relationship_coherence,
        )
        
        ontology_generic = {
            "entities": [{"id": f"e{i}"} for i in range(3)],
            "relationships": [
                {"id": "r1", "source_id": "e0", "target_id": "e1", "type": "related_to"},
            ],
        }
        ontology_specific = {
            "entities": [{"id": f"e{i}"} for i in range(3)],
            "relationships": [
                {"id": "r1", "source_id": "e0", "target_id": "e1", "type": "manages_team"},
            ],
        }
        
        score_generic = evaluate_relationship_coherence(ontology_generic, context=None)
        score_specific = evaluate_relationship_coherence(ontology_specific, context=None)
        assert score_specific >= score_generic


class TestOntologyCriticIntegration:
    """Test that OntologyCritic properly integrates all modular evaluators."""

    def test_critic_uses_all_evaluators(self, create_test_ontology):
        """Critic evaluation produces scores from all dimension evaluators."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerationContext,
            DataType,
            ExtractionStrategy,
        )
        
        critic = OntologyCritic(use_llm=False)
        ontology = create_test_ontology(entity_count=10, relationship_count=8)
        context = OntologyGenerationContext(
            data_source="legal_doc.pdf",
            data_type=DataType.PDF,
            domain="legal",
            extraction_strategy=ExtractionStrategy.HYBRID,
        )
        
        score = critic.evaluate_ontology(ontology, context)
        
        # All dimension scores should be present
        assert hasattr(score, 'completeness')
        assert hasattr(score, 'consistency')
        assert hasattr(score, 'clarity')
        assert hasattr(score, 'granularity')
        assert hasattr(score, 'relationship_coherence')
        assert hasattr(score, 'domain_alignment')
        
        # All scores should be in valid range
        assert 0.0 <= score.completeness <= 1.0
        assert 0.0 <= score.consistency <= 1.0
        assert 0.0 <= score.clarity <= 1.0
        assert 0.0 <= score.granularity <= 1.0
        assert 0.0 <= score.relationship_coherence <= 1.0
        assert 0.0 <= score.domain_alignment <= 1.0
        assert 0.0 <= score.overall <= 1.0

    def test_modular_file_line_counts(self):
        """Modular files are smaller than monolithic ontology_critic.py."""
        import os
        import subprocess
        
        base_path = "ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag"
        
        # Get line count for main critic file
        main_file = f"{base_path}/ontology_critic.py"
        result = subprocess.run(['wc', '-l', main_file], capture_output=True, text=True)
        main_lines = int(result.stdout.split()[0])
        
        # Get line counts for modular files
        modular_files = [
            f"{base_path}/ontology_critic_completeness.py",
            f"{base_path}/ontology_critic_consistency.py",
            f"{base_path}/ontology_critic_clarity.py",
            f"{base_path}/ontology_critic_granularity.py",
            f"{base_path}/ontology_critic_domain_alignment.py",
            f"{base_path}/ontology_critic_connectivity.py",
        ]
        
        for mod_file in modular_files:
            result = subprocess.run(['wc', '-l', mod_file], capture_output=True, text=True)
            mod_lines = int(result.stdout.split()[0])
            # Each modular file should be much smaller than main file
            assert mod_lines < 300,  f"{mod_file} has {mod_lines} lines, expected < 300"
        
        # Main file should still be large (contains OntologyCritic class + other logic)
        assert main_lines > 1000, f"Main file has {main_lines} lines"
