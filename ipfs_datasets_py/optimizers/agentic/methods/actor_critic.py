"""Actor-Critic optimization method.

This optimizer uses reinforcement learning principles with an actor
(code generator) and critic (code evaluator) in a feedback loop.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..base import (
    AgenticOptimizer,
    ChangeControlMethod,
    OptimizationMethod,
    OptimizationResult,
    OptimizationTask,
    ValidationResult,
)
from ..patch_control import PatchManager


@dataclass
class CriticFeedback:
    """Feedback from the critic evaluating a solution.
    
    Attributes:
        correctness_score: Score for correctness (0-1)
        performance_score: Score for performance (0-1)
        style_score: Score for code style (0-1)
        overall_score: Overall weighted score (0-1)
        comments: List of feedback comments
    """
    correctness_score: float
    performance_score: float
    style_score: float
    overall_score: float
    comments: List[str] = field(default_factory=list)


@dataclass
class Policy:
    """Represents a learned policy for code generation.
    
    Attributes:
        patterns: Learned code patterns that work well
        rewards: Cumulative rewards for each pattern
        usage_count: How many times each pattern was used
        success_rate: Success rate for each pattern
    """
    
    patterns: Dict[str, str] = field(default_factory=dict)
    rewards: Dict[str, float] = field(default_factory=dict)
    usage_count: Dict[str, int] = field(default_factory=dict)
    success_rate: Dict[str, float] = field(default_factory=dict)
    
    def add_pattern(self, pattern_id: str, pattern: str, reward: float):
        """Add or update a pattern."""
        self.patterns[pattern_id] = pattern
        self.rewards[pattern_id] = self.rewards.get(pattern_id, 0.0) + reward
        self.usage_count[pattern_id] = self.usage_count.get(pattern_id, 0) + 1
        
        # Update success rate (reward > 0 = success)
        successes = sum(1 for r in [reward] if r > 0)
        self.success_rate[pattern_id] = successes / self.usage_count[pattern_id]
    
    def get_best_patterns(self, n: int = 5) -> List[Tuple[str, str, float]]:
        """Get top N patterns by reward."""
        sorted_patterns = sorted(
            self.patterns.items(),
            key=lambda x: self.rewards.get(x[0], 0.0),
            reverse=True,
        )
        return [
            (pid, pattern, self.rewards.get(pid, 0.0))
            for pid, pattern in sorted_patterns[:n]
        ]
    
    def save(self, path: Path):
        """Save policy to file."""
        data = {
            "patterns": self.patterns,
            "rewards": self.rewards,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load(cls, path: Path) -> 'Policy':
        """Load policy from file."""
        with open(path, 'r') as f:
            data = json.load(f)
        
        policy = cls()
        policy.patterns = data.get("patterns", {})
        policy.rewards = data.get("rewards", {})
        policy.usage_count = data.get("usage_count", {})
        policy.success_rate = data.get("success_rate", {})
        return policy


class ActorCriticOptimizer(AgenticOptimizer):
    """Actor-Critic optimization implementation.
    
    This optimizer uses reinforcement learning with:
    - Actor: Proposes code changes based on learned patterns
    - Critic: Evaluates proposals and provides feedback
    - Learning: Improves over time based on success/failure
    
    The optimizer learns which patterns work well and applies them
    to future optimization tasks.
    
    Example:
        >>> from ipfs_datasets_py.llm_router import LLMRouter
        >>> router = LLMRouter()
        >>> optimizer = ActorCriticOptimizer(
        ...     agent_id="ac-opt-1",
        ...     llm_router=router,
        ...     learning_rate=0.1,
        ...     exploration_rate=0.2
        ... )
        >>> task = OptimizationTask(
        ...     task_id="task-1",
        ...     description="Optimize caching logic",
        ...     target_files=[Path("ipfs_datasets_py/cache.py")]
        ... )
        >>> result = optimizer.optimize(task)
    """
    
    def __init__(
        self,
        agent_id: str,
        llm_router: Any,
        change_control: ChangeControlMethod = ChangeControlMethod.PATCH,
        learning_rate: float = 0.1,
        exploration_rate: float = 0.2,
        policy_path: Optional[Path] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize actor-critic optimizer.
        
        Args:
            agent_id: Unique identifier for this agent
            llm_router: LLM router for text generation
            change_control: Change control method to use
            learning_rate: Learning rate for policy updates
            exploration_rate: Probability of exploring new patterns
            policy_path: Path to save/load learned policy
            config: Optional configuration dictionary
        """
        super().__init__(agent_id, llm_router, change_control, config)
        self.patch_manager = PatchManager()
        self.learning_rate = learning_rate
        self.exploration_rate = exploration_rate
        
        # Load or initialize policy
        if policy_path and policy_path.exists():
            self.policy = Policy.load(policy_path)
        else:
            self.policy = Policy()
        
        self.policy_path = policy_path or Path(f".optimizer-policy-{agent_id}.json")
    
    def _get_method(self) -> OptimizationMethod:
        """Return the optimization method."""
        return OptimizationMethod.ACTOR_CRITIC
    
    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        """Perform actor-critic optimization.
        
        Args:
            task: The optimization task to perform
            
        Returns:
            OptimizationResult with success status and details
        """
        start_time = time.time()
        
        try:
            # Step 1: Actor proposes change
            proposal = self._actor_propose(task)
            
            # Step 2: Critic evaluates proposal
            evaluation = self._critic_evaluate(proposal, task)
            
            # Step 3: Update policy based on feedback
            self._update_policy(proposal, evaluation)
            
            # Step 4: Validate if evaluation was positive
            if evaluation["reward"] > 0:
                validation = self._validate_proposal(proposal, task.target_files)
                
                if validation.passed:
                    # Create patch
                    patch_path, patch_cid = self._create_patch(proposal, task)
                    
                    return OptimizationResult(
                        task_id=task.task_id,
                        success=True,
                        method=self._get_method(),
                        changes=proposal["description"],
                        patch_path=patch_path,
                        patch_cid=patch_cid,
                        validation=validation,
                        metrics={
                            "reward": evaluation["reward"],
                            "correctness": evaluation["correctness"],
                            "performance": evaluation["performance"],
                            "style": evaluation["style"],
                        },
                        execution_time=time.time() - start_time,
                        agent_id=self.agent_id,
                    )
            
            # Proposal not good enough
            return OptimizationResult(
                task_id=task.task_id,
                success=False,
                method=self._get_method(),
                changes=proposal["description"],
                validation=ValidationResult(passed=False),
                metrics={
                    "reward": evaluation["reward"],
                    "correctness": evaluation.get("correctness", 0.0),
                },
                execution_time=time.time() - start_time,
                agent_id=self.agent_id,
                error_message="Proposal did not meet quality threshold",
            )
            
        except Exception as e:
            return OptimizationResult(
                task_id=task.task_id,
                success=False,
                method=self._get_method(),
                changes="",
                validation=ValidationResult(passed=False),
                metrics={},
                execution_time=time.time() - start_time,
                agent_id=self.agent_id,
                error_message=str(e),
            )
        finally:
            # Save policy after each optimization
            self._save_policy()
    
    def _actor_propose(self, task: OptimizationTask) -> Dict[str, Any]:
        """Actor proposes a code change.
        
        Args:
            task: Optimization task
            
        Returns:
            Proposal dictionary with code and metadata
        """
        import random
        
        # Decide: exploit learned patterns or explore new ones
        explore = random.random() < self.exploration_rate
        
        if explore or not self.policy.patterns:
            # Explore: Generate new proposal using LLM
            proposal = self._generate_new_proposal(task)
            proposal["strategy"] = "explore"
        else:
            # Exploit: Use learned patterns
            proposal = self._generate_from_policy(task)
            proposal["strategy"] = "exploit"
        
        return proposal
    
    def _generate_new_proposal(self, task: OptimizationTask) -> Dict[str, Any]:
        """Generate new proposal by exploring.
        
        Args:
            task: Optimization task
            
        Returns:
            Proposal dictionary
        """
        prompt = f"""Propose an optimization for the following task:

Task: {task.description}
Target files: {', '.join(str(f) for f in task.target_files)}

Requirements:
1. Improve performance or code quality
2. Maintain backward compatibility
3. Include type hints and docstrings
4. Follow best practices

Generate optimized code with explanation."""
        
        try:
            response = self.llm_router.generate(
                prompt=prompt,
                max_tokens=1500,
                temperature=0.8,  # Higher temperature for exploration
            )
            
            return {
                "id": f"proposal-{int(time.time())}",
                "code": self._extract_code(response),
                "description": self._extract_description(response),
                "pattern_id": None,  # New pattern
            }
            
        except Exception as e:
            return {
                "id": f"proposal-{int(time.time())}",
                "code": "",
                "description": f"Error generating proposal: {e}",
                "pattern_id": None,
            }
    
    def _generate_from_policy(self, task: OptimizationTask) -> Dict[str, Any]:
        """Generate proposal using learned policy.
        
        Args:
            task: Optimization task
            
        Returns:
            Proposal dictionary
        """
        # Get best patterns
        best_patterns = self.policy.get_best_patterns(n=3)
        
        if not best_patterns:
            return self._generate_new_proposal(task)
        
        # Use top pattern
        pattern_id, pattern_code, reward = best_patterns[0]
        
        # Adapt pattern to current task using LLM
        prompt = f"""Adapt the following proven pattern to solve this task:

Task: {task.description}
Target files: {', '.join(str(f) for f in task.target_files)}

Proven Pattern (reward: {reward:.2f}):
{pattern_code}

Generate adapted code that follows this pattern."""
        
        try:
            response = self.llm_router.generate(
                prompt=prompt,
                max_tokens=1500,
                temperature=0.5,  # Lower temperature for exploitation
            )
            
            return {
                "id": f"proposal-{int(time.time())}",
                "code": self._extract_code(response),
                "description": self._extract_description(response),
                "pattern_id": pattern_id,
            }
            
        except Exception as e:
            return {
                "id": f"proposal-{int(time.time())}",
                "code": pattern_code,
                "description": f"Using pattern {pattern_id}",
                "pattern_id": pattern_id,
            }
    
    def _critic_evaluate(
        self,
        proposal: Dict[str, Any],
        task: OptimizationTask,
    ) -> Dict[str, float]:
        """Critic evaluates the proposal.
        
        Args:
            proposal: Proposal to evaluate
            task: Optimization task
            
        Returns:
            Evaluation dictionary with scores
        """
        code = proposal["code"]
        
        # Evaluate correctness (syntax, basic checks)
        correctness = self._evaluate_correctness(code)
        
        # Evaluate performance (code quality indicators)
        performance = self._evaluate_performance(code)
        
        # Evaluate style (follows best practices)
        style = self._evaluate_style(code)
        
        # Calculate overall reward
        reward = (
            0.4 * correctness +
            0.4 * performance +
            0.2 * style
        )
        
        return {
            "correctness": correctness,
            "performance": performance,
            "style": style,
            "reward": reward,
        }
    
    def _evaluate_correctness(self, code: str) -> float:
        """Evaluate code correctness.
        
        Args:
            code: Code to evaluate
            
        Returns:
            Score from 0.0 to 1.0
        """
        import ast
        
        score = 0.0
        
        # Check syntax
        try:
            ast.parse(code)
            score += 0.5
        except SyntaxError:
            return 0.0  # Syntax errors are fatal
        
        # Check for common issues
        if "TODO" in code or "FIXME" in code:
            score -= 0.1
        
        # Check for error handling
        if "try:" in code or "except" in code:
            score += 0.3
        
        # Check for type hints
        if " -> " in code or ": " in code:
            score += 0.2
        
        return min(1.0, max(0.0, score))
    
    def _evaluate_performance(self, code: str) -> float:
        """Evaluate code performance indicators.
        
        Args:
            code: Code to evaluate
            
        Returns:
            Score from 0.0 to 1.0
        """
        score = 0.5  # Start at neutral
        
        # Good patterns
        if "cache" in code.lower():
            score += 0.2
        
        if "async " in code or "await " in code:
            score += 0.2
        
        if "yield " in code:  # Generator usage
            score += 0.1
        
        # Bad patterns
        if "global " in code:
            score -= 0.2
        
        if code.count("for ") > 3:  # Nested loops
            score -= 0.1
        
        return min(1.0, max(0.0, score))
    
    def _evaluate_style(self, code: str) -> float:
        """Evaluate code style.
        
        Args:
            code: Code to evaluate
            
        Returns:
            Score from 0.0 to 1.0
        """
        score = 0.0
        
        # Docstrings
        if '"""' in code or "'''" in code:
            score += 0.3
        
        # Comments
        comment_ratio = code.count('#') / max(len(code.split('\n')), 1)
        score += min(0.2, comment_ratio * 5)
        
        # Naming (descriptive names)
        words = code.split()
        long_names = sum(1 for w in words if len(w) > 5)
        score += min(0.3, long_names / max(len(words), 1) * 3)
        
        # Organization
        if "class " in code:
            score += 0.1
        
        if "def " in code:
            score += 0.1
        
        return min(1.0, score)
    
    def _update_policy(
        self,
        proposal: Dict[str, Any],
        evaluation: Dict[str, float],
    ):
        """Update policy based on feedback.
        
        Args:
            proposal: Proposal that was evaluated
            evaluation: Evaluation results
        """
        pattern_id = proposal.get("pattern_id")
        reward = evaluation["reward"]
        
        # Create pattern ID if new
        if pattern_id is None:
            pattern_id = proposal["id"]
        
        # Update policy with this experience
        self.policy.add_pattern(
            pattern_id=pattern_id,
            pattern=proposal["code"],
            reward=reward,
        )
    
    def _save_policy(self):
        """Save current policy to disk."""
        try:
            self.policy.save(self.policy_path)
        except Exception as e:
            print(f"Warning: Failed to save policy: {e}")
    
    def _extract_code(self, response: str) -> str:
        """Extract code from LLM response."""
        if "```python" in response:
            parts = response.split("```python")
            if len(parts) > 1:
                code = parts[1].split("```")[0]
                return code.strip()
        
        return response
    
    def _extract_description(self, response: str) -> str:
        """Extract description from LLM response."""
        if "```python" in response:
            return response.split("```python")[0].strip()
        
        return response[:200] + "..." if len(response) > 200 else response
    
    def _validate_proposal(
        self,
        proposal: Dict[str, Any],
        target_files: List[Path],
    ) -> ValidationResult:
        """Validate the proposal.
        
        Args:
            proposal: Proposal to validate
            target_files: Original target files
            
        Returns:
            ValidationResult
        """
        import ast
        
        errors = []
        
        # Syntax check
        syntax_ok = True
        try:
            ast.parse(proposal["code"])
        except SyntaxError as e:
            syntax_ok = False
            errors.append(f"Syntax error: {e}")
        
        validation = ValidationResult(
            passed=syntax_ok and len(errors) == 0,
            syntax_check=syntax_ok,
            errors=errors,
        )
        
        return validation
    
    def _create_patch(
        self,
        proposal: Dict[str, Any],
        task: OptimizationTask,
    ) -> Tuple[Optional[Path], Optional[str]]:
        """Create patch file for the proposal.
        
        Args:
            proposal: Proposal to create patch for
            task: Optimization task
            
        Returns:
            Tuple of (patch_path, patch_cid)
        """
        try:
            metadata = {
                "task_id": task.task_id,
                "description": proposal["description"],
                "agent_id": self.agent_id,
                "method": "actor_critic",
                "strategy": proposal.get("strategy", "unknown"),
            }
            
            # Actual patch creation would go here
            return None, None
            
        except Exception as e:
            print(f"Error creating patch: {e}")
            return None, None
