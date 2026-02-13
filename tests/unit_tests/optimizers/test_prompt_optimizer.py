"""Tests for Prompt Optimizer.

This module contains comprehensive tests for the prompt optimization system
that improves logic extraction quality through intelligent prompt engineering.
"""

import pytest
import json
import tempfile
import os
from unittest.mock import Mock, patch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prompt_optimizer import (
    PromptOptimizer,
    OptimizationStrategy,
    PromptMetrics,
    PromptTemplate,
    OptimizationResult,
)


class TestOptimizationStrategy:
    """Tests for OptimizationStrategy enum."""
    
    def test_optimization_strategy_values(self):
        """
        GIVEN the OptimizationStrategy enum
        WHEN accessing strategy values
        THEN all expected strategies should be available
        """
        assert OptimizationStrategy.AB_TESTING.value == "ab_testing"
        assert OptimizationStrategy.MULTI_ARMED_BANDIT.value == "multi_armed_bandit"
        assert OptimizationStrategy.GENETIC_ALGORITHM.value == "genetic_algorithm"
        assert OptimizationStrategy.HILL_CLIMBING.value == "hill_climbing"
        assert OptimizationStrategy.SIMULATED_ANNEALING.value == "simulated_annealing"
        assert OptimizationStrategy.REINFORCEMENT_LEARNING.value == "reinforcement_learning"


class TestPromptMetrics:
    """Tests for PromptMetrics dataclass."""
    
    def test_prompt_metrics_creation(self):
        """
        GIVEN prompt metrics data
        WHEN creating PromptMetrics
        THEN metrics should have correct attributes
        """
        metrics = PromptMetrics(
            prompt_id="test_prompt",
            total_uses=10,
            success_rate=0.8,
            avg_confidence=0.85,
            avg_critic_score=0.9,
            avg_extraction_time=1.5
        )
        
        assert metrics.prompt_id == "test_prompt"
        assert metrics.total_uses == 10
        assert metrics.success_rate == 0.8
        assert metrics.avg_confidence == 0.85
        assert metrics.avg_critic_score == 0.9
        assert metrics.avg_extraction_time == 1.5
    
    def test_get_overall_score(self):
        """
        GIVEN prompt metrics
        WHEN computing overall score
        THEN score should be weighted combination of metrics
        """
        metrics = PromptMetrics(
            prompt_id="test",
            success_rate=0.8,
            avg_critic_score=0.9,
            avg_confidence=0.85,
            avg_extraction_time=2.0
        )
        
        score = metrics.get_overall_score()
        
        # Score = 0.3*0.8 + 0.3*0.9 + 0.2*0.85 + 0.2*(1-2/10)
        expected = 0.3 * 0.8 + 0.3 * 0.9 + 0.2 * 0.85 + 0.2 * 0.8
        assert abs(score - expected) < 0.01
    
    def test_get_overall_score_slow_prompt(self):
        """
        GIVEN a slow prompt (>10s)
        WHEN computing overall score
        THEN time penalty should be capped
        """
        metrics = PromptMetrics(
            prompt_id="slow",
            success_rate=1.0,
            avg_critic_score=1.0,
            avg_confidence=1.0,
            avg_extraction_time=20.0  # Very slow
        )
        
        score = metrics.get_overall_score()
        
        # Time penalty should be capped at 0
        assert score >= 0.0
        assert score <= 1.0


class TestPromptTemplate:
    """Tests for PromptTemplate dataclass."""
    
    def test_prompt_template_creation(self):
        """
        GIVEN template data
        WHEN creating PromptTemplate
        THEN template should have correct attributes
        """
        template = PromptTemplate(
            template_id="test_template",
            template="Extract logic from: {data}",
            version=1,
            parameters={"param1": "value1"},
            metadata={"author": "test"}
        )
        
        assert template.template_id == "test_template"
        assert template.template == "Extract logic from: {data}"
        assert template.version == 1
        assert template.parameters == {"param1": "value1"}
        assert template.metadata == {"author": "test"}
    
    def test_instantiate_template(self):
        """
        GIVEN a prompt template with placeholders
        WHEN instantiating with values
        THEN placeholders should be replaced
        """
        template = PromptTemplate(
            template_id="test",
            template="Extract {formalism} logic from: {data}",
            version=1
        )
        
        result = template.instantiate(formalism="FOL", data="sample text")
        
        assert result == "Extract FOL logic from: sample text"
    
    def test_instantiate_with_default_parameters(self):
        """
        GIVEN a template with default parameters
        WHEN instantiating without providing those parameters
        THEN default values should be used
        """
        template = PromptTemplate(
            template_id="test",
            template="Extract {formalism} logic",
            version=1,
            parameters={"formalism": "TDFOL"}
        )
        
        result = template.instantiate()
        
        assert result == "Extract TDFOL logic"
    
    def test_instantiate_missing_parameter(self):
        """
        GIVEN a template with required placeholder
        WHEN instantiating without the parameter
        THEN original template should be returned
        """
        template = PromptTemplate(
            template_id="test",
            template="Extract logic from: {data}",
            version=1
        )
        
        result = template.instantiate()
        
        # Should return original template when parameter missing
        assert "{data}" in result


class TestOptimizationResult:
    """Tests for OptimizationResult dataclass."""
    
    def test_optimization_result_creation(self):
        """
        GIVEN optimization result data
        WHEN creating OptimizationResult
        THEN result should have correct attributes
        """
        template = PromptTemplate("best", "prompt", 1)
        history = [("prompt1", 0.8), ("prompt2", 0.9)]
        
        result = OptimizationResult(
            best_prompt=template,
            best_score=0.9,
            optimization_history=history,
            total_iterations=10,
            convergence_achieved=True,
            improvement_over_baseline=0.15
        )
        
        assert result.best_prompt == template
        assert result.best_score == 0.9
        assert result.total_iterations == 10
        assert result.convergence_achieved is True
        assert result.improvement_over_baseline == 0.15


class TestPromptOptimizer:
    """Tests for PromptOptimizer."""
    
    def test_init_default_params(self):
        """
        GIVEN default parameters
        WHEN initializing PromptOptimizer
        THEN optimizer should be initialized with correct defaults
        """
        optimizer = PromptOptimizer()
        
        assert optimizer.strategy == OptimizationStrategy.MULTI_ARMED_BANDIT
        assert optimizer.enable_versioning is True
        assert optimizer.track_metrics is True
        assert optimizer.exploration_rate == 0.1
        assert len(optimizer.prompt_library) == 0
    
    def test_init_custom_params(self):
        """
        GIVEN custom parameters
        WHEN initializing PromptOptimizer
        THEN optimizer should use custom values
        """
        optimizer = PromptOptimizer(
            strategy=OptimizationStrategy.AB_TESTING,
            enable_versioning=False,
            track_metrics=False,
            exploration_rate=0.2
        )
        
        assert optimizer.strategy == OptimizationStrategy.AB_TESTING
        assert optimizer.enable_versioning is False
        assert optimizer.track_metrics is False
        assert optimizer.exploration_rate == 0.2
    
    def test_add_prompt(self):
        """
        GIVEN a prompt template
        WHEN adding to optimizer
        THEN prompt should be stored in library
        """
        optimizer = PromptOptimizer()
        
        prompt_id = optimizer.add_prompt("Extract logic: {data}")
        
        assert prompt_id in optimizer.prompt_library
        assert prompt_id in optimizer.prompt_metrics
        assert optimizer.prompt_library[prompt_id].template == "Extract logic: {data}"
    
    def test_add_prompt_with_custom_id(self):
        """
        GIVEN a custom prompt ID
        WHEN adding prompt
        THEN custom ID should be used
        """
        optimizer = PromptOptimizer()
        
        prompt_id = optimizer.add_prompt(
            "Test prompt",
            prompt_id="custom_id"
        )
        
        assert prompt_id == "custom_id"
        assert "custom_id" in optimizer.prompt_library
    
    def test_add_prompt_with_parameters(self):
        """
        GIVEN prompt with parameters
        WHEN adding to optimizer
        THEN parameters should be stored
        """
        optimizer = PromptOptimizer()
        
        prompt_id = optimizer.add_prompt(
            "Extract {formalism}",
            parameters={"formalism": "FOL"}
        )
        
        template = optimizer.prompt_library[prompt_id]
        assert template.parameters == {"formalism": "FOL"}
    
    def test_add_baseline_prompt(self):
        """
        GIVEN a baseline prompt
        WHEN adding as baseline
        THEN it should be set as baseline
        """
        optimizer = PromptOptimizer()
        
        prompt_id = optimizer.add_baseline_prompt("Baseline prompt")
        
        assert optimizer.baseline_prompt is not None
        assert optimizer.baseline_prompt.template_id == "baseline"
        assert optimizer.baseline_prompt.template == "Baseline prompt"
    
    def test_record_usage(self):
        """
        GIVEN prompt usage data
        WHEN recording usage
        THEN metrics should be updated
        """
        optimizer = PromptOptimizer()
        prompt_id = optimizer.add_prompt("Test prompt")
        
        optimizer.record_usage(
            prompt_id=prompt_id,
            success=True,
            confidence=0.9,
            critic_score=0.85,
            extraction_time=1.0,
            domain="legal",
            formalism="tdfol"
        )
        
        metrics = optimizer.prompt_metrics[prompt_id]
        assert metrics.total_uses == 1
        assert metrics.success_rate == 1.0
        assert metrics.avg_confidence == 0.9
        assert metrics.avg_critic_score == 0.85
        assert "legal" in metrics.domain_performance
        assert "tdfol" in metrics.formalism_performance
    
    def test_record_usage_multiple_times(self):
        """
        GIVEN multiple usages
        WHEN recording
        THEN running averages should be computed
        """
        optimizer = PromptOptimizer()
        prompt_id = optimizer.add_prompt("Test prompt")
        
        # First usage
        optimizer.record_usage(prompt_id, True, 0.8, 0.9, 1.0)
        # Second usage
        optimizer.record_usage(prompt_id, False, 0.6, 0.7, 2.0)
        
        metrics = optimizer.prompt_metrics[prompt_id]
        assert metrics.total_uses == 2
        assert metrics.success_rate == 0.5  # (1+0)/2
        assert metrics.avg_confidence == 0.7  # (0.8+0.6)/2
        assert metrics.avg_critic_score == 0.8  # (0.9+0.7)/2
    
    def test_record_usage_tracking_disabled(self):
        """
        GIVEN tracking disabled
        WHEN recording usage
        THEN metrics should not be updated
        """
        optimizer = PromptOptimizer(track_metrics=False)
        prompt_id = optimizer.add_prompt("Test prompt")
        
        optimizer.record_usage(prompt_id, True, 0.9, 0.85, 1.0)
        
        # Should not have recorded anything
        assert len(optimizer.performance_history) == 0
    
    def test_get_best_prompt_single(self):
        """
        GIVEN a single prompt with sufficient uses
        WHEN getting best prompt
        THEN that prompt should be returned
        """
        optimizer = PromptOptimizer()
        prompt_id = optimizer.add_prompt("Test prompt")
        
        # Record sufficient uses
        for _ in range(10):
            optimizer.record_usage(prompt_id, True, 0.9, 0.85, 1.0)
        
        best = optimizer.get_best_prompt()
        
        assert best is not None
        assert best.template_id == prompt_id
    
    def test_get_best_prompt_multiple(self):
        """
        GIVEN multiple prompts
        WHEN getting best prompt
        THEN highest scoring prompt should be returned
        """
        optimizer = PromptOptimizer()
        
        prompt1 = optimizer.add_prompt("Prompt 1")
        prompt2 = optimizer.add_prompt("Prompt 2")
        
        # Prompt 1: lower score
        for _ in range(10):
            optimizer.record_usage(prompt1, True, 0.7, 0.6, 1.0)
        
        # Prompt 2: higher score
        for _ in range(10):
            optimizer.record_usage(prompt2, True, 0.95, 0.9, 1.0)
        
        best = optimizer.get_best_prompt()
        
        assert best.template_id == prompt2
    
    def test_get_best_prompt_insufficient_uses(self):
        """
        GIVEN prompts without sufficient uses
        WHEN getting best prompt
        THEN None should be returned
        """
        optimizer = PromptOptimizer()
        prompt_id = optimizer.add_prompt("Test prompt")
        
        # Only 3 uses, but min_uses=5
        for _ in range(3):
            optimizer.record_usage(prompt_id, True, 0.9, 0.85, 1.0)
        
        best = optimizer.get_best_prompt(min_uses=5)
        
        assert best is None
    
    def test_get_best_prompt_by_domain(self):
        """
        GIVEN domain-specific usage
        WHEN getting best prompt for a domain
        THEN domain performance should be considered
        """
        optimizer = PromptOptimizer()
        
        prompt_id = optimizer.add_prompt("Test prompt")
        
        # Good legal performance
        for _ in range(10):
            optimizer.record_usage(
                prompt_id, True, 0.9, 0.95, 1.0, domain="legal"
            )
        
        best = optimizer.get_best_prompt(domain="legal")
        
        assert best is not None
        assert "legal" in optimizer.prompt_metrics[best.template_id].domain_performance
    
    def test_optimize_ab_testing(self):
        """
        GIVEN AB_TESTING strategy
        WHEN optimizing
        THEN should compare prompts pairwise
        """
        optimizer = PromptOptimizer(strategy=OptimizationStrategy.AB_TESTING)
        
        prompt1 = optimizer.add_prompt("Prompt 1")
        prompt2 = optimizer.add_prompt("Prompt 2")
        
        # Simulate some usage
        for _ in range(5):
            optimizer.record_usage(prompt1, True, 0.8, 0.75, 1.0)
            optimizer.record_usage(prompt2, True, 0.9, 0.85, 1.0)
        
        result = optimizer.optimize([], max_iterations=10)
        
        assert result is not None
        assert result.best_prompt is not None
        assert len(result.optimization_history) > 0
    
    def test_optimize_multi_armed_bandit(self):
        """
        GIVEN MULTI_ARMED_BANDIT strategy
        WHEN optimizing
        THEN should use explore-exploit tradeoff
        """
        optimizer = PromptOptimizer(
            strategy=OptimizationStrategy.MULTI_ARMED_BANDIT,
            exploration_rate=0.2
        )
        
        for i in range(3):
            optimizer.add_prompt(f"Prompt {i}")
        
        result = optimizer.optimize([], max_iterations=20)
        
        assert result is not None
        assert result.total_iterations == 20
        assert len(result.optimization_history) == 20
    
    def test_optimize_with_baseline(self):
        """
        GIVEN a baseline prompt
        WHEN optimizing
        THEN improvement over baseline should be calculated
        """
        optimizer = PromptOptimizer()
        
        baseline_id = optimizer.add_baseline_prompt("Baseline")
        prompt_id = optimizer.add_prompt("Better prompt")
        
        # Baseline: lower performance
        for _ in range(10):
            optimizer.record_usage(baseline_id, True, 0.7, 0.65, 1.0)
        
        # New prompt: higher performance
        for _ in range(10):
            optimizer.record_usage(prompt_id, True, 0.9, 0.85, 1.0)
        
        result = optimizer.optimize([], max_iterations=5)
        
        assert result.improvement_over_baseline > 0
    
    def test_optimize_invalid_strategy(self):
        """
        GIVEN an invalid strategy
        WHEN optimizing
        THEN ValueError should be raised
        """
        optimizer = PromptOptimizer()
        optimizer.strategy = "invalid"  # Hack to set invalid strategy
        
        with pytest.raises(ValueError, match="Unknown strategy"):
            optimizer.optimize([])
    
    def test_get_statistics(self):
        """
        GIVEN an optimizer with usage data
        WHEN getting statistics
        THEN statistics should be accurate
        """
        optimizer = PromptOptimizer()
        
        prompt1 = optimizer.add_prompt("Prompt 1")
        prompt2 = optimizer.add_prompt("Prompt 2")
        optimizer.add_baseline_prompt("Baseline")
        
        for _ in range(5):
            optimizer.record_usage(prompt1, True, 0.9, 0.85, 1.0)
            optimizer.record_usage(prompt2, True, 0.8, 0.75, 1.0)
        
        stats = optimizer.get_statistics()
        
        assert stats['total_prompts'] == 3  # 2 + baseline
        assert stats['total_uses'] == 10
        assert stats['has_baseline'] is True
        assert 'avg_success_rate' in stats
    
    def test_export_import_library(self):
        """
        GIVEN a prompt library
        WHEN exporting and importing
        THEN library should be preserved
        """
        optimizer1 = PromptOptimizer()
        
        prompt_id = optimizer1.add_prompt(
            "Test prompt {data}",
            parameters={"param1": "value1"}
        )
        
        for _ in range(5):
            optimizer1.record_usage(prompt_id, True, 0.9, 0.85, 1.0)
        
        # Export
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name
        
        try:
            optimizer1.export_library(filepath)
            
            # Import to new optimizer
            optimizer2 = PromptOptimizer()
            optimizer2.import_library(filepath)
            
            # Verify
            assert len(optimizer2.prompt_library) == len(optimizer1.prompt_library)
            assert prompt_id in optimizer2.prompt_library
            assert optimizer2.prompt_library[prompt_id].template == "Test prompt {data}"
            assert optimizer2.prompt_metrics[prompt_id].total_uses == 5
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_export_library_creates_file(self):
        """
        GIVEN an optimizer
        WHEN exporting library
        THEN file should be created with valid JSON
        """
        optimizer = PromptOptimizer()
        optimizer.add_prompt("Test prompt")
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name
        
        try:
            optimizer.export_library(filepath)
            
            assert os.path.exists(filepath)
            
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            assert 'prompts' in data
            assert 'metrics' in data
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_domain_specific_prompts(self):
        """
        GIVEN prompts with domain-specific performance
        WHEN recording usage across domains
        THEN domain performance should be tracked separately
        """
        optimizer = PromptOptimizer()
        prompt_id = optimizer.add_prompt("Test prompt")
        
        # Good in legal domain
        for _ in range(5):
            optimizer.record_usage(
                prompt_id, True, 0.95, 0.9, 1.0, domain="legal"
            )
        
        # Poor in technical domain
        for _ in range(5):
            optimizer.record_usage(
                prompt_id, True, 0.6, 0.5, 1.0, domain="technical"
            )
        
        metrics = optimizer.prompt_metrics[prompt_id]
        
        assert "legal" in metrics.domain_performance
        assert "technical" in metrics.domain_performance
        assert metrics.domain_performance["legal"] > metrics.domain_performance["technical"]
    
    def test_formalism_specific_prompts(self):
        """
        GIVEN prompts with formalism-specific performance
        WHEN recording usage across formalisms
        THEN formalism performance should be tracked separately
        """
        optimizer = PromptOptimizer()
        prompt_id = optimizer.add_prompt("Test prompt")
        
        # Good for FOL
        for _ in range(5):
            optimizer.record_usage(
                prompt_id, True, 0.9, 0.85, 1.0, formalism="fol"
            )
        
        # Poor for TDFOL
        for _ in range(5):
            optimizer.record_usage(
                prompt_id, True, 0.6, 0.55, 1.0, formalism="tdfol"
            )
        
        metrics = optimizer.prompt_metrics[prompt_id]
        
        assert "fol" in metrics.formalism_performance
        assert "tdfol" in metrics.formalism_performance
        assert metrics.formalism_performance["fol"] > metrics.formalism_performance["tdfol"]
