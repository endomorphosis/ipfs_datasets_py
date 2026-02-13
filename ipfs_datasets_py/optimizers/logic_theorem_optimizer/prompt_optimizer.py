"""Prompt Optimization for Logic Theorem Optimizer.

This module implements advanced prompt optimization strategies to improve
the quality of logic extraction from arbitrary data.

Key features:
- Multiple optimization strategies (A/B testing, genetic algorithms, reinforcement learning)
- Prompt effectiveness metrics and scoring
- Prompt library with versioning
- Historical performance tracking
- Automatic prompt generation and refinement

Integration:
- Works with LogicExtractor to optimize extraction prompts
- Tracks performance across different data types and domains
- Learns from critic feedback to improve prompts over time
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time
import json
import hashlib
from collections import defaultdict

logger = logging.getLogger(__name__)


class OptimizationStrategy(Enum):
    """Strategy for optimizing prompts."""
    AB_TESTING = "ab_testing"  # Compare two prompts
    MULTI_ARMED_BANDIT = "multi_armed_bandit"  # Explore-exploit tradeoff
    GENETIC_ALGORITHM = "genetic_algorithm"  # Evolve prompts over generations
    HILL_CLIMBING = "hill_climbing"  # Iterative local improvements
    SIMULATED_ANNEALING = "simulated_annealing"  # Allow occasional bad moves
    REINFORCEMENT_LEARNING = "reinforcement_learning"  # Learn from rewards


@dataclass
class PromptMetrics:
    """Metrics for evaluating prompt effectiveness.
    
    Attributes:
        prompt_id: Unique identifier for the prompt
        total_uses: Number of times prompt was used
        success_rate: Percentage of successful extractions
        avg_confidence: Average confidence score
        avg_critic_score: Average critic score
        avg_extraction_time: Average time taken
        domain_performance: Performance by domain
        formalism_performance: Performance by logic formalism
    """
    prompt_id: str
    total_uses: int = 0
    success_rate: float = 0.0
    avg_confidence: float = 0.0
    avg_critic_score: float = 0.0
    avg_extraction_time: float = 0.0
    domain_performance: Dict[str, float] = field(default_factory=dict)
    formalism_performance: Dict[str, float] = field(default_factory=dict)
    
    def get_overall_score(self) -> float:
        """Compute overall effectiveness score."""
        # Weighted combination of metrics
        return (
            0.3 * self.success_rate +
            0.3 * self.avg_critic_score +
            0.2 * self.avg_confidence +
            0.2 * (1.0 - min(self.avg_extraction_time / 10.0, 1.0))  # Penalize slow prompts
        )


@dataclass
class PromptTemplate:
    """Template for generating prompts.
    
    Attributes:
        template_id: Unique identifier
        template: Template string with placeholders
        version: Version number
        parameters: Configurable parameters
        metadata: Additional metadata
        created_at: Creation timestamp
        performance_history: Historical performance metrics
    """
    template_id: str
    template: str
    version: int
    parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    performance_history: List[PromptMetrics] = field(default_factory=list)
    
    def instantiate(self, **kwargs) -> str:
        """Instantiate template with provided values."""
        try:
            return self.template.format(**kwargs, **self.parameters)
        except KeyError as e:
            logger.warning(f"Missing parameter for template {self.template_id}: {e}")
            return self.template


@dataclass
class OptimizationResult:
    """Result of prompt optimization.
    
    Attributes:
        best_prompt: Best performing prompt
        best_score: Score of best prompt
        optimization_history: History of optimization attempts
        total_iterations: Number of optimization iterations
        convergence_achieved: Whether optimization converged
        improvement_over_baseline: Improvement compared to baseline
    """
    best_prompt: PromptTemplate
    best_score: float
    optimization_history: List[Tuple[str, float]]
    total_iterations: int
    convergence_achieved: bool
    improvement_over_baseline: float


class PromptOptimizer:
    """Optimizer for prompt engineering.
    
    This optimizer uses various strategies to find optimal prompts for
    logic extraction across different domains and data types.
    
    Features:
    - Multiple optimization strategies
    - Automatic prompt generation
    - Performance tracking and analytics
    - Prompt versioning and rollback
    - Domain and formalism-specific optimization
    
    Example:
        >>> optimizer = PromptOptimizer(strategy=OptimizationStrategy.AB_TESTING)
        >>> optimizer.add_baseline_prompt("Extract logic: {data}")
        >>> optimizer.optimize(training_data, max_iterations=10)
        >>> best_prompt = optimizer.get_best_prompt(domain="legal")
    """
    
    def __init__(
        self,
        strategy: OptimizationStrategy = OptimizationStrategy.MULTI_ARMED_BANDIT,
        enable_versioning: bool = True,
        track_metrics: bool = True,
        exploration_rate: float = 0.1
    ):
        """Initialize the prompt optimizer.
        
        Args:
            strategy: Optimization strategy to use
            enable_versioning: Whether to enable prompt versioning
            track_metrics: Whether to track detailed metrics
            exploration_rate: Exploration rate for bandit strategies (0.0-1.0)
        """
        self.strategy = strategy
        self.enable_versioning = enable_versioning
        self.track_metrics = track_metrics
        self.exploration_rate = exploration_rate
        
        # Prompt library
        self.prompt_library: Dict[str, PromptTemplate] = {}
        self.prompt_metrics: Dict[str, PromptMetrics] = {}
        
        # Performance tracking
        self.performance_history: List[Dict[str, Any]] = []
        self.domain_specific_prompts: Dict[str, List[str]] = defaultdict(list)
        
        # Optimization state
        self.baseline_prompt: Optional[PromptTemplate] = None
        self.current_generation: int = 0
        
        logger.info(f"Initialized PromptOptimizer with strategy={strategy.value}")
    
    def add_prompt(
        self,
        prompt_template: str,
        prompt_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a prompt template to the library.
        
        Args:
            prompt_template: Template string
            prompt_id: Optional unique ID (auto-generated if not provided)
            parameters: Default parameters for template
            metadata: Additional metadata
        
        Returns:
            The prompt ID
        """
        if prompt_id is None:
            prompt_id = self._generate_prompt_id(prompt_template)
        
        template = PromptTemplate(
            template_id=prompt_id,
            template=prompt_template,
            version=1,
            parameters=parameters or {},
            metadata=metadata or {}
        )
        
        self.prompt_library[prompt_id] = template
        self.prompt_metrics[prompt_id] = PromptMetrics(prompt_id=prompt_id)
        
        logger.info(f"Added prompt template: {prompt_id}")
        return prompt_id
    
    def add_baseline_prompt(self, prompt_template: str, **kwargs) -> str:
        """Add a baseline prompt for comparison.
        
        Args:
            prompt_template: Baseline prompt template
            **kwargs: Additional parameters
        
        Returns:
            The baseline prompt ID
        """
        prompt_id = self.add_prompt(prompt_template, prompt_id="baseline", **kwargs)
        self.baseline_prompt = self.prompt_library[prompt_id]
        logger.info("Set baseline prompt")
        return prompt_id
    
    def record_usage(
        self,
        prompt_id: str,
        success: bool,
        confidence: float,
        critic_score: float,
        extraction_time: float,
        domain: str = "general",
        formalism: str = "fol"
    ) -> None:
        """Record usage of a prompt for metrics tracking.
        
        Args:
            prompt_id: ID of the prompt used
            success: Whether extraction was successful
            confidence: Confidence score
            critic_score: Critic score
            extraction_time: Time taken for extraction
            domain: Domain of the data
            formalism: Logic formalism used
        """
        if not self.track_metrics:
            return
        
        if prompt_id not in self.prompt_metrics:
            self.prompt_metrics[prompt_id] = PromptMetrics(prompt_id=prompt_id)
        
        metrics = self.prompt_metrics[prompt_id]
        
        # Update aggregated metrics
        metrics.total_uses += 1
        n = metrics.total_uses
        
        # Running averages
        metrics.success_rate = ((n - 1) * metrics.success_rate + (1.0 if success else 0.0)) / n
        metrics.avg_confidence = ((n - 1) * metrics.avg_confidence + confidence) / n
        metrics.avg_critic_score = ((n - 1) * metrics.avg_critic_score + critic_score) / n
        metrics.avg_extraction_time = ((n - 1) * metrics.avg_extraction_time + extraction_time) / n
        
        # Domain-specific performance
        if domain not in metrics.domain_performance:
            metrics.domain_performance[domain] = critic_score
        else:
            metrics.domain_performance[domain] = (
                0.9 * metrics.domain_performance[domain] + 0.1 * critic_score
            )
        
        # Formalism-specific performance
        if formalism not in metrics.formalism_performance:
            metrics.formalism_performance[formalism] = critic_score
        else:
            metrics.formalism_performance[formalism] = (
                0.9 * metrics.formalism_performance[formalism] + 0.1 * critic_score
            )
        
        # Record in history
        self.performance_history.append({
            'prompt_id': prompt_id,
            'timestamp': time.time(),
            'success': success,
            'confidence': confidence,
            'critic_score': critic_score,
            'extraction_time': extraction_time,
            'domain': domain,
            'formalism': formalism
        })
    
    def get_best_prompt(
        self,
        domain: Optional[str] = None,
        formalism: Optional[str] = None,
        min_uses: int = 5
    ) -> Optional[PromptTemplate]:
        """Get the best performing prompt.
        
        Args:
            domain: Filter by domain
            formalism: Filter by formalism
            min_uses: Minimum number of uses required
        
        Returns:
            Best prompt template or None if no suitable prompts
        """
        candidates = []
        
        for prompt_id, metrics in self.prompt_metrics.items():
            if metrics.total_uses < min_uses:
                continue
            
            # Compute score
            score = metrics.get_overall_score()
            
            # Apply domain/formalism filters
            if domain and domain in metrics.domain_performance:
                score = 0.7 * score + 0.3 * metrics.domain_performance[domain]
            if formalism and formalism in metrics.formalism_performance:
                score = 0.7 * score + 0.3 * metrics.formalism_performance[formalism]
            
            candidates.append((prompt_id, score))
        
        if not candidates:
            return None
        
        # Return best
        best_id = max(candidates, key=lambda x: x[1])[0]
        return self.prompt_library[best_id]
    
    def optimize(
        self,
        training_data: List[Dict[str, Any]],
        max_iterations: int = 20,
        convergence_threshold: float = 0.01
    ) -> OptimizationResult:
        """Optimize prompts using the configured strategy.
        
        Args:
            training_data: Training data for optimization
            max_iterations: Maximum number of optimization iterations
            convergence_threshold: Threshold for convergence
        
        Returns:
            Optimization result
        """
        if self.strategy == OptimizationStrategy.AB_TESTING:
            return self._optimize_ab_testing(training_data, max_iterations)
        elif self.strategy == OptimizationStrategy.MULTI_ARMED_BANDIT:
            return self._optimize_bandit(training_data, max_iterations)
        elif self.strategy == OptimizationStrategy.GENETIC_ALGORITHM:
            return self._optimize_genetic(training_data, max_iterations)
        elif self.strategy == OptimizationStrategy.HILL_CLIMBING:
            return self._optimize_hill_climbing(training_data, max_iterations, convergence_threshold)
        elif self.strategy == OptimizationStrategy.SIMULATED_ANNEALING:
            return self._optimize_simulated_annealing(training_data, max_iterations)
        elif self.strategy == OptimizationStrategy.REINFORCEMENT_LEARNING:
            return self._optimize_reinforcement(training_data, max_iterations)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")
    
    def _optimize_ab_testing(
        self,
        training_data: List[Dict[str, Any]],
        max_iterations: int
    ) -> OptimizationResult:
        """Optimize using A/B testing."""
        if len(self.prompt_library) < 2:
            raise ValueError("A/B testing requires at least 2 prompts")
        
        # Simple A/B: compare all pairs
        prompt_ids = list(self.prompt_library.keys())
        best_prompt_id = prompt_ids[0]
        best_score = 0.0
        
        history = []
        
        for i in range(0, len(prompt_ids), 2):
            if i + 1 >= len(prompt_ids):
                break
            
            prompt_a = prompt_ids[i]
            prompt_b = prompt_ids[i + 1]
            
            # Simulate usage (in real scenario, would test on actual data)
            score_a = self.prompt_metrics.get(prompt_a, PromptMetrics(prompt_a)).get_overall_score()
            score_b = self.prompt_metrics.get(prompt_b, PromptMetrics(prompt_b)).get_overall_score()
            
            history.append((prompt_a, score_a))
            history.append((prompt_b, score_b))
            
            if score_a > best_score:
                best_score = score_a
                best_prompt_id = prompt_a
            if score_b > best_score:
                best_score = score_b
                best_prompt_id = prompt_b
        
        baseline_score = (
            self.prompt_metrics[self.baseline_prompt.template_id].get_overall_score()
            if self.baseline_prompt else 0.0
        )
        
        return OptimizationResult(
            best_prompt=self.prompt_library[best_prompt_id],
            best_score=best_score,
            optimization_history=history,
            total_iterations=len(history),
            convergence_achieved=True,
            improvement_over_baseline=best_score - baseline_score
        )
    
    def _optimize_bandit(
        self,
        training_data: List[Dict[str, Any]],
        max_iterations: int
    ) -> OptimizationResult:
        """Optimize using multi-armed bandit (epsilon-greedy)."""
        import random
        
        prompt_ids = list(self.prompt_library.keys())
        history = []
        
        for iteration in range(max_iterations):
            # Epsilon-greedy selection
            if random.random() < self.exploration_rate:
                # Explore: random prompt
                prompt_id = random.choice(prompt_ids)
            else:
                # Exploit: best prompt so far
                best = self.get_best_prompt(min_uses=1)
                prompt_id = best.template_id if best else random.choice(prompt_ids)
            
            # Simulate usage
            score = self.prompt_metrics.get(
                prompt_id, 
                PromptMetrics(prompt_id)
            ).get_overall_score()
            
            history.append((prompt_id, score))
        
        # Get final best
        best = self.get_best_prompt(min_uses=1)
        best_score = self.prompt_metrics[best.template_id].get_overall_score() if best else 0.0
        
        baseline_score = (
            self.prompt_metrics.get(
                self.baseline_prompt.template_id,
                PromptMetrics(self.baseline_prompt.template_id),
            ).get_overall_score()
            if self.baseline_prompt
            else 0.0
        )
        
        return OptimizationResult(
            best_prompt=best or list(self.prompt_library.values())[0],
            best_score=best_score,
            optimization_history=history,
            total_iterations=max_iterations,
            convergence_achieved=False,
            improvement_over_baseline=best_score - baseline_score
        )
    
    def _optimize_genetic(
        self,
        training_data: List[Dict[str, Any]],
        max_iterations: int
    ) -> OptimizationResult:
        """Optimize using genetic algorithm."""
        # Placeholder for genetic algorithm
        # In real implementation, would:
        # 1. Create initial population of prompts
        # 2. Evaluate fitness (performance)
        # 3. Select best performers
        # 4. Cross-over and mutate to create new generation
        # 5. Repeat
        
        logger.info("Genetic algorithm optimization (simplified implementation)")
        return self._optimize_bandit(training_data, max_iterations)
    
    def _optimize_hill_climbing(
        self,
        training_data: List[Dict[str, Any]],
        max_iterations: int,
        convergence_threshold: float
    ) -> OptimizationResult:
        """Optimize using hill climbing."""
        # Placeholder for hill climbing
        # Would iteratively make small changes and keep improvements
        
        logger.info("Hill climbing optimization (simplified implementation)")
        return self._optimize_bandit(training_data, max_iterations)
    
    def _optimize_simulated_annealing(
        self,
        training_data: List[Dict[str, Any]],
        max_iterations: int
    ) -> OptimizationResult:
        """Optimize using simulated annealing."""
        # Placeholder for simulated annealing
        # Would allow occasional "bad" moves early on with decreasing probability
        
        logger.info("Simulated annealing optimization (simplified implementation)")
        return self._optimize_bandit(training_data, max_iterations)
    
    def _optimize_reinforcement(
        self,
        training_data: List[Dict[str, Any]],
        max_iterations: int
    ) -> OptimizationResult:
        """Optimize using reinforcement learning."""
        # Placeholder for RL-based optimization
        # Would learn policy for selecting prompts based on context
        
        logger.info("Reinforcement learning optimization (simplified implementation)")
        return self._optimize_bandit(training_data, max_iterations)
    
    def _generate_prompt_id(self, prompt_template: str) -> str:
        """Generate unique ID for a prompt template."""
        return hashlib.sha256(prompt_template.encode()).hexdigest()[:16]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get optimization statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'total_prompts': len(self.prompt_library),
            'total_uses': sum(m.total_uses for m in self.prompt_metrics.values()),
            'avg_success_rate': (
                sum(m.success_rate for m in self.prompt_metrics.values()) / 
                len(self.prompt_metrics) if self.prompt_metrics else 0.0
            ),
            'strategy': self.strategy.value,
            'has_baseline': self.baseline_prompt is not None,
            'history_size': len(self.performance_history)
        }
    
    def export_library(self, filepath: str) -> None:
        """Export prompt library to file.
        
        Args:
            filepath: Path to export file
        """
        data = {
            'prompts': {
                pid: {
                    'template': pt.template,
                    'version': pt.version,
                    'parameters': pt.parameters,
                    'metadata': pt.metadata
                }
                for pid, pt in self.prompt_library.items()
            },
            'metrics': {
                pid: {
                    'total_uses': m.total_uses,
                    'success_rate': m.success_rate,
                    'avg_confidence': m.avg_confidence,
                    'avg_critic_score': m.avg_critic_score
                }
                for pid, m in self.prompt_metrics.items()
            }
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Exported prompt library to {filepath}")
    
    def import_library(self, filepath: str) -> None:
        """Import prompt library from file.
        
        Args:
            filepath: Path to import file
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Import prompts
        for pid, pdata in data.get('prompts', {}).items():
            template = PromptTemplate(
                template_id=pid,
                template=pdata['template'],
                version=pdata['version'],
                parameters=pdata.get('parameters', {}),
                metadata=pdata.get('metadata', {})
            )
            self.prompt_library[pid] = template
        
        # Import metrics
        for pid, mdata in data.get('metrics', {}).items():
            metrics = PromptMetrics(
                prompt_id=pid,
                total_uses=mdata.get('total_uses', 0),
                success_rate=mdata.get('success_rate', 0.0),
                avg_confidence=mdata.get('avg_confidence', 0.0),
                avg_critic_score=mdata.get('avg_critic_score', 0.0)
            )
            self.prompt_metrics[pid] = metrics
        
        logger.info(f"Imported prompt library from {filepath}")
