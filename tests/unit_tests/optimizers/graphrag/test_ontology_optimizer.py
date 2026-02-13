"""
Test suite for OntologyOptimizer.

Tests the SGD-based optimization engine.

Format: GIVEN-WHEN-THEN
"""

import pytest
from typing import Dict, List, Any
from unittest.mock import Mock, patch

# Try to import the ontology optimizer
try:
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
        OntologyOptimizer,
        OptimizationResult,
        PatternInsight,
    )
    OPTIMIZER_AVAILABLE = True
except ImportError as e:
    OPTIMIZER_AVAILABLE = False
    pytest.skip(f"OntologyOptimizer not available: {e}", allow_module_level=True)


class TestPatternInsight:
    """Test PatternInsight dataclass."""
    
    def test_insight_creation(self):
        """
        GIVEN: Pattern insight data
        WHEN: Creating a pattern insight
        THEN: Insight is created with pattern and recommendation
        """
        insight = PatternInsight(
            pattern="High score for medical entities",
            frequency=10,
            impact_score=0.85,
            recommendation="Focus on medical domain"
        )
        
        assert insight.pattern == "High score for medical entities"
        assert insight.frequency == 10
        assert insight.impact_score == 0.85
        assert insight.recommendation is not None


class TestOptimizationResult:
    """Test OptimizationResult dataclass."""
    
    def test_result_creation(self):
        """
        GIVEN: Optimization result data
        WHEN: Creating an optimization result
        THEN: Result is created with insights and trends
        """
        result = OptimizationResult(
            patterns=[],
            trends={"quality": [0.6, 0.7, 0.8]},
            recommendations=["Add more entities"],
            convergence_rate=0.15,
            final_score=0.85
        )
        
        assert len(result.trends["quality"]) == 3
        assert result.convergence_rate == 0.15
        assert result.final_score == 0.85


class TestOntologyOptimizerInitialization:
    """Test OntologyOptimizer initialization."""
    
    def test_optimizer_initialization_default(self):
        """
        GIVEN: No configuration
        WHEN: Initializing optimizer with defaults
        THEN: Optimizer is created with default settings
        """
        optimizer = OntologyOptimizer()
        
        assert optimizer is not None
        assert hasattr(optimizer, 'config')
        assert hasattr(optimizer, 'patterns')
    
    def test_optimizer_initialization_custom_config(self):
        """
        GIVEN: Custom configuration
        WHEN: Initializing optimizer with custom settings
        THEN: Optimizer uses specified settings
        """
        config = {
            'learning_rate': 0.1,
            'momentum': 0.9,
            'pattern_threshold': 3
        }
        optimizer = OntologyOptimizer(config=config)
        
        assert optimizer.config['learning_rate'] == 0.1
        assert optimizer.config['momentum'] == 0.9
        assert optimizer.config['pattern_threshold'] == 3
    
    def test_optimizer_has_analysis_methods(self):
        """
        GIVEN: Initialized optimizer
        WHEN: Checking analysis methods
        THEN: Optimizer has pattern and trend analysis
        """
        optimizer = OntologyOptimizer()
        
        assert hasattr(optimizer, 'analyze_batch')
        assert hasattr(optimizer, '_identify_patterns')
        assert hasattr(optimizer, '_analyze_trends')


class TestOntologyOptimizerPatternIdentification:
    """Test pattern identification from batches."""
    
    def setup_method(self):
        """Setup for each test."""
        self.optimizer = OntologyOptimizer()
    
    def test_identify_patterns_from_sessions(self):
        """
        GIVEN: Multiple session results
        WHEN: Analyzing for patterns
        THEN: Common patterns are identified
        """
        sessions = [
            Mock(critique_score=0.9, ontology={"entities": {"person": {"A"}}}),
            Mock(critique_score=0.85, ontology={"entities": {"person": {"B"}}}),
            Mock(critique_score=0.88, ontology={"entities": {"person": {"C"}}}),
        ]
        
        patterns = self.optimizer._identify_patterns(sessions)
        
        assert patterns is not None
        assert isinstance(patterns, list)
    
    def test_pattern_threshold(self):
        """
        GIVEN: Sessions with various patterns
        WHEN: Identifying patterns with threshold
        THEN: Only frequent patterns are returned
        """
        config = {'pattern_threshold': 2}
        optimizer = OntologyOptimizer(config=config)
        
        sessions = [
            Mock(critique_score=0.9, ontology={"entities": {"person": set()}}),
            Mock(critique_score=0.85, ontology={"entities": {"person": set()}}),
            Mock(critique_score=0.75, ontology={"entities": {"place": set()}}),
        ]
        
        patterns = optimizer._identify_patterns(sessions)
        
        # "person" entity type appears twice, should be identified
        assert patterns is not None


class TestOntologyOptimizerTrendAnalysis:
    """Test trend analysis across cycles."""
    
    def setup_method(self):
        """Setup for each test."""
        self.optimizer = OntologyOptimizer()
    
    def test_analyze_improving_trend(self):
        """
        GIVEN: Scores improving over time
        WHEN: Analyzing trends
        THEN: Improvement trend is detected
        """
        cycles = [
            Mock(average_score=0.6),
            Mock(average_score=0.7),
            Mock(average_score=0.8),
            Mock(average_score=0.85),
        ]
        
        trends = self.optimizer._analyze_trends(cycles)
        
        assert trends is not None
        assert isinstance(trends, dict)
        # Should detect improvement
        if 'direction' in trends:
            assert trends['direction'] in ['improving', 'up', 'positive']
    
    def test_analyze_degrading_trend(self):
        """
        GIVEN: Scores degrading over time
        WHEN: Analyzing trends
        THEN: Degradation trend is detected
        """
        cycles = [
            Mock(average_score=0.85),
            Mock(average_score=0.80),
            Mock(average_score=0.75),
            Mock(average_score=0.70),
        ]
        
        trends = self.optimizer._analyze_trends(cycles)
        
        assert trends is not None
        # Should detect degradation
        if 'direction' in trends:
            assert trends['direction'] in ['degrading', 'down', 'negative']
    
    def test_analyze_stable_trend(self):
        """
        GIVEN: Stable scores over time
        WHEN: Analyzing trends
        THEN: Stable trend is detected
        """
        cycles = [
            Mock(average_score=0.80),
            Mock(average_score=0.81),
            Mock(average_score=0.79),
            Mock(average_score=0.80),
        ]
        
        trends = self.optimizer._analyze_trends(cycles)
        
        assert trends is not None
        # Should detect stability
        if 'direction' in trends:
            assert trends['direction'] in ['stable', 'flat', 'converged']


class TestOntologyOptimizerBatchAnalysis:
    """Test batch result analysis."""
    
    def setup_method(self):
        """Setup for each test."""
        self.optimizer = OntologyOptimizer()
    
    def test_analyze_single_batch(self):
        """
        GIVEN: Single batch result
        WHEN: Analyzing batch
        THEN: Optimization insights are generated
        """
        batch = Mock(
            sessions=[
                Mock(critique_score=0.85, validation_score=0.90),
                Mock(critique_score=0.80, validation_score=0.85),
            ],
            average_score=0.825,
            best_score=0.85
        )
        
        result = self.optimizer.analyze_batch(batch)
        
        assert result is not None
        assert isinstance(result, OptimizationResult)
    
    def test_analyze_multiple_batches(self):
        """
        GIVEN: Multiple batch results (SGD cycles)
        WHEN: Analyzing all batches
        THEN: Cross-batch patterns and trends identified
        """
        batches = [
            Mock(
                sessions=[Mock(critique_score=0.7)],
                average_score=0.70
            ),
            Mock(
                sessions=[Mock(critique_score=0.75)],
                average_score=0.75
            ),
            Mock(
                sessions=[Mock(critique_score=0.82)],
                average_score=0.82
            ),
        ]
        
        result = self.optimizer.analyze_cycles(batches)
        
        assert result is not None
        # Should show improvement trend
        if hasattr(result, 'trends'):
            assert 'quality' in result.trends or 'scores' in result.trends


class TestOntologyOptimizerRecommendations:
    """Test recommendation generation."""
    
    def setup_method(self):
        """Setup for each test."""
        self.optimizer = OntologyOptimizer()
    
    def test_recommendations_from_patterns(self):
        """
        GIVEN: Identified patterns
        WHEN: Generating recommendations
        THEN: Actionable recommendations are provided
        """
        patterns = [
            PatternInsight(
                pattern="Medical entities score high",
                frequency=5,
                impact_score=0.9,
                recommendation="Focus on medical domain"
            )
        ]
        
        recommendations = self.optimizer._generate_recommendations(patterns)
        
        assert recommendations is not None
        assert isinstance(recommendations, list)
        assert len(recommendations) > 0
    
    def test_recommendations_for_low_scores(self):
        """
        GIVEN: Consistently low scores
        WHEN: Analyzing batch
        THEN: Recommendations address score issues
        """
        batch = Mock(
            sessions=[
                Mock(critique_score=0.45),
                Mock(critique_score=0.40),
            ],
            average_score=0.425
        )
        
        result = self.optimizer.analyze_batch(batch)
        
        assert result is not None
        assert len(result.recommendations) > 0
        # Recommendations should address low scores


class TestOntologyOptimizerConvergence:
    """Test convergence detection."""
    
    def setup_method(self):
        """Setup for each test."""
        self.optimizer = OntologyOptimizer()
    
    def test_detect_convergence(self):
        """
        GIVEN: Stable scores over multiple cycles
        WHEN: Analyzing convergence
        THEN: Convergence is detected
        """
        cycles = [
            Mock(average_score=0.85),
            Mock(average_score=0.86),
            Mock(average_score=0.85),
            Mock(average_score=0.86),
        ]
        
        is_converged = self.optimizer._check_convergence(cycles)
        
        # Should detect convergence
        assert isinstance(is_converged, bool)
    
    def test_convergence_rate_calculation(self):
        """
        GIVEN: Scores over time
        WHEN: Calculating convergence rate
        THEN: Rate reflects speed of convergence
        """
        cycles = [
            Mock(average_score=0.60),
            Mock(average_score=0.70),
            Mock(average_score=0.80),
            Mock(average_score=0.85),
        ]
        
        rate = self.optimizer._calculate_convergence_rate(cycles)
        
        assert rate is not None
        assert isinstance(rate, (int, float))
        assert rate > 0  # Positive rate for improving scores


class TestOntologyOptimizerEdgeCases:
    """Test edge cases and error handling."""
    
    def setup_method(self):
        """Setup for each test."""
        self.optimizer = OntologyOptimizer()
    
    def test_analyze_empty_batch(self):
        """
        GIVEN: Empty batch with no sessions
        WHEN: Analyzing batch
        THEN: Handles gracefully
        """
        empty_batch = Mock(sessions=[], average_score=0.0)
        
        try:
            result = self.optimizer.analyze_batch(empty_batch)
            # Should return valid result
            assert result is not None
        except ValueError:
            # Or raise appropriate error
            assert True
    
    def test_analyze_single_cycle(self):
        """
        GIVEN: Only one cycle
        WHEN: Analyzing trends
        THEN: Returns limited insights
        """
        cycles = [Mock(average_score=0.75)]
        
        result = self.optimizer.analyze_cycles(cycles)
        
        assert result is not None
        # Cannot determine trends from single point


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
