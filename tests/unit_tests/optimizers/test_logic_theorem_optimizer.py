"""Tests for Logic Theorem Optimizer.

This module contains tests for the logic theorem optimizer system.
"""

import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    LogicExtractor,
    LogicExtractionContext,
    ExtractionMode,
    DataType,
    LogicCritic,
    CriticDimensions,
    LogicOptimizer,
    TheoremSession,
    SessionConfig,
    LogicHarness,
    HarnessConfig,
    KnowledgeGraphStabilizer,
    OntologyConsistencyChecker,
)


class TestLogicExtractor:
    """Tests for LogicExtractor."""
    
    def test_init(self):
        """Test extractor initialization."""
        extractor = LogicExtractor(model="gpt-4")
        assert extractor.model == "gpt-4"
        assert extractor.extraction_history == []
    
    def test_extract_basic(self):
        """Test basic extraction."""
        extractor = LogicExtractor()
        context = LogicExtractionContext(
            data="All employees must complete training",
            data_type=DataType.TEXT,
            extraction_mode=ExtractionMode.AUTO,
            domain="general"
        )
        
        result = extractor.extract(context)
        
        assert result is not None
        assert isinstance(result.statements, list)
        assert result.context == context
    
    def test_extract_tdfol(self):
        """Test TDFOL extraction."""
        extractor = LogicExtractor()
        context = LogicExtractionContext(
            data="Employees must complete training within 30 days",
            extraction_mode=ExtractionMode.TDFOL,
            domain="legal"
        )
        
        result = extractor.extract(context)
        
        assert result.success
        assert len(result.statements) > 0
        assert result.statements[0].formalism == "tdfol"


class TestLogicCritic:
    """Tests for LogicCritic."""
    
    def test_init(self):
        """Test critic initialization."""
        critic = LogicCritic(use_provers=['z3'])
        assert 'z3' in critic.use_provers
    
    def test_evaluate(self):
        """Test evaluation."""
        extractor = LogicExtractor()
        context = LogicExtractionContext(
            data="All employees must complete training"
        )
        result = extractor.extract(context)
        
        critic = LogicCritic(use_provers=[])
        score = critic.evaluate(result)
        
        assert score is not None
        assert 0.0 <= score.overall <= 1.0
        assert len(score.dimension_scores) == 6
    
    def test_dimension_weights(self):
        """Test dimension weights sum to 1.0."""
        total_weight = sum(LogicCritic.DIMENSION_WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.001


class TestLogicOptimizer:
    """Tests for LogicOptimizer."""
    
    def test_init(self):
        """Test optimizer initialization."""
        optimizer = LogicOptimizer(convergence_threshold=0.85)
        assert optimizer.convergence_threshold == 0.85
        assert optimizer.score_history == []
    
    def test_analyze_empty_batch(self):
        """Test analyzing empty batch."""
        optimizer = LogicOptimizer()
        report = optimizer.analyze_batch([])
        
        assert report.average_score == 0.0
        assert report.trend == "insufficient_data"


class TestTheoremSession:
    """Tests for TheoremSession."""
    
    def test_init(self):
        """Test session initialization."""
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        
        session = TheoremSession(extractor, critic)
        
        assert session.extractor == extractor
        assert session.critic == critic
        assert isinstance(session.config, SessionConfig)
    
    def test_run_session(self):
        """Test running a session."""
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        
        session = TheoremSession(extractor, critic)
        result = session.run("All employees must complete training")
        
        assert result is not None
        assert isinstance(result.num_rounds, int)
        assert result.num_rounds >= 1


class TestLogicHarness:
    """Tests for LogicHarness."""
    
    def test_init(self):
        """Test harness initialization."""
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        
        harness = LogicHarness(extractor, critic)
        
        assert harness.extractor == extractor
        assert harness.critic == critic
        assert isinstance(harness.config, HarnessConfig)
    
    def test_run_single_session(self):
        """Test running single session."""
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        
        harness = LogicHarness(extractor, critic)
        result = harness.run_sessions(["Test data"])
        
        assert result.total_sessions == 1
        assert result.total_sessions == result.successful_sessions + result.failed_sessions


class TestOntologyConsistencyChecker:
    """Tests for OntologyConsistencyChecker."""
    
    def test_init(self):
        """Test checker initialization."""
        ontology = {
            'terms': ['Employee', 'Training'],
            'relations': ['must', 'complete']
        }
        checker = OntologyConsistencyChecker(ontology)
        
        assert 'Employee' in checker.terms
        assert 'must' in checker.relations
    
    def test_check_empty_statements(self):
        """Test checking empty statement list."""
        checker = OntologyConsistencyChecker()
        report = checker.check_statements([])
        
        assert report.is_consistent


class TestKnowledgeGraphStabilizer:
    """Tests for KnowledgeGraphStabilizer."""
    
    def test_init(self):
        """Test stabilizer initialization."""
        ontology = {'terms': ['Employee']}
        stabilizer = KnowledgeGraphStabilizer(ontology)
        
        assert stabilizer.ontology == ontology
        assert stabilizer.statements == []
    
    def test_get_stability_score_empty(self):
        """Test stability score for empty graph."""
        stabilizer = KnowledgeGraphStabilizer()
        score = stabilizer.get_stability_score()
        
        assert score == 1.0  # Trivially stable
    
    def test_get_statistics(self):
        """Test getting statistics."""
        stabilizer = KnowledgeGraphStabilizer()
        stats = stabilizer.get_statistics()
        
        assert 'num_statements' in stats
        assert 'current_stability' in stats
        assert 'ontology_size' in stats


class TestIntegration:
    """Integration tests for the complete system."""
    
    def test_full_pipeline(self):
        """Test complete pipeline from extraction to optimization."""
        # Create components
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        optimizer = LogicOptimizer()
        harness = LogicHarness(extractor, critic)
        
        # Run batch
        data_samples = [
            "All employees must complete training",
            "Managers may approve exceptions"
        ]
        
        result = harness.run_sessions(data_samples)
        
        # Optimize
        report = optimizer.analyze_batch(result.session_results)
        
        # Verify
        assert result.total_sessions == 2
        assert report.average_score >= 0.0
        assert len(report.recommendations) > 0
    
    def test_with_ontology_stabilizer(self):
        """Test integration with ontology stabilizer."""
        # Setup
        extractor = LogicExtractor()
        ontology = {
            'terms': ['Employee', 'Training', 'Manager'],
            'relations': ['must', 'may', 'complete']
        }
        stabilizer = KnowledgeGraphStabilizer(ontology)
        
        # Extract
        context = LogicExtractionContext(
            data="All employees must complete training",
            ontology=ontology
        )
        result = extractor.extract(context)
        
        # Add to stabilizer
        if result.success:
            added = stabilizer.add_statements(result.statements)
            assert added >= 0
            assert stabilizer.get_stability_score() >= 0.0
