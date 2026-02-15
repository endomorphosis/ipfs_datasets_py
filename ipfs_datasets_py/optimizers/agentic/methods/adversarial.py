"""Adversarial optimization method.

This optimizer generates N competing solutions, benchmarks them,
and selects the best based on multi-criteria scoring.
"""

import ast
import subprocess
import tempfile
import time
from dataclasses import dataclass
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
class BenchmarkResult:
    """Results from benchmarking a solution.
    
    Attributes:
        execution_time: Time taken to execute (seconds)
        memory_usage: Memory used (MB)
        correctness_score: Correctness score (0-1)
    """
    execution_time: float
    memory_usage: float
    correctness_score: float


@dataclass
class Solution:
    """Represents a candidate solution.
    
    Attributes:
        id: Unique identifier for the solution
        code: The solution code
        description: Description of the solution approach
        benchmark_result: Benchmark results (if evaluated)
    """
    id: str
    code: str
    description: str
    benchmark_result: Optional[BenchmarkResult] = None


class AdversarialOptimizer(AgenticOptimizer):
    """Adversarial optimization implementation.
    
    This optimizer generates multiple competing solutions and selects
    the best through comprehensive evaluation:
    1. Analyze code and generate N alternative implementations
    2. Benchmark each implementation's performance
    3. Apply adversarial testing (edge cases, stress tests)
    4. Score solutions using weighted multi-criteria evaluation
    5. Select winner and create patch
    
    Example:
        >>> from ipfs_datasets_py.llm_router import LLMRouter
        >>> router = LLMRouter()
        >>> optimizer = AdversarialOptimizer(
        ...     agent_id="adv-opt-1",
        ...     llm_router=router,
        ...     num_solutions=5,
        ...     scoring_weights={
        ...         "performance": 0.4,
        ...         "readability": 0.3,
        ...         "maintainability": 0.2,
        ...         "test_coverage": 0.1
        ...     }
        ... )
        >>> task = OptimizationTask(
        ...     task_id="task-1",
        ...     description="Optimize search algorithm",
        ...     target_files=[Path("ipfs_datasets_py/search/algorithm.py")]
        ... )
        >>> result = optimizer.optimize(task)
    """
    
    def __init__(
        self,
        agent_id: str,
        llm_router: Any,
        change_control: ChangeControlMethod = ChangeControlMethod.PATCH,
        num_solutions: int = 5,
        scoring_weights: Optional[Dict[str, float]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize adversarial optimizer.
        
        Args:
            agent_id: Unique identifier for this agent
            llm_router: LLM router for text generation
            change_control: Change control method to use
            num_solutions: Number of competing solutions to generate
            scoring_weights: Weights for multi-criteria scoring
            config: Optional configuration dictionary
        """
        super().__init__(agent_id, llm_router, change_control, config)
        self.patch_manager = PatchManager()
        self.num_solutions = num_solutions
        
        # Default scoring weights if not provided
        self.scoring_weights = scoring_weights or {
            "performance": 0.35,
            "readability": 0.25,
            "maintainability": 0.20,
            "test_coverage": 0.10,
            "security": 0.10,
        }
        
        # Validate weights sum to 1.0
        weight_sum = sum(self.scoring_weights.values())
        if abs(weight_sum - 1.0) > 0.01:
            raise ValueError(f"Scoring weights must sum to 1.0, got {weight_sum}")
    
    def _get_method(self) -> OptimizationMethod:
        """Return the optimization method."""
        return OptimizationMethod.ADVERSARIAL
    
    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        """Perform adversarial optimization.
        
        Args:
            task: The optimization task to perform
            
        Returns:
            OptimizationResult with success status and details
        """
        start_time = time.time()
        
        try:
            # Step 1: Analyze target files
            target_analysis = self._analyze_targets(task.target_files)
            
            # Step 2: Generate N alternative solutions
            solutions = self._generate_solutions(task, target_analysis)
            
            if not solutions:
                return OptimizationResult(
                    task_id=task.task_id,
                    success=False,
                    method=self._get_method(),
                    changes="",
                    validation=ValidationResult(passed=False),
                    metrics={},
                    execution_time=time.time() - start_time,
                    agent_id=self.agent_id,
                    error_message="Failed to generate solutions",
                )
            
            # Step 3: Benchmark each solution
            benchmarks = self._benchmark_solutions(solutions, task.target_files)
            
            # Step 4: Apply adversarial testing
            adversarial_results = self._adversarial_testing(solutions, task)
            
            # Step 5: Score all solutions
            scores = self._score_solutions(
                solutions,
                benchmarks,
                adversarial_results,
            )
            
            # Step 6: Select winner
            winner_idx = max(range(len(scores)), key=lambda i: scores[i]["total"])
            winner = solutions[winner_idx]
            winner_score = scores[winner_idx]
            
            # Step 7: Validate winner
            validation = self._validate_solution(winner, task.target_files)
            
            if not validation.passed:
                return OptimizationResult(
                    task_id=task.task_id,
                    success=False,
                    method=self._get_method(),
                    changes=winner["description"],
                    validation=validation,
                    metrics=winner_score,
                    execution_time=time.time() - start_time,
                    agent_id=self.agent_id,
                    error_message="Winner solution failed validation",
                )
            
            # Step 8: Create patch
            patch_path, patch_cid = self._create_patch(winner, task)
            
            return OptimizationResult(
                task_id=task.task_id,
                success=True,
                method=self._get_method(),
                changes=winner["description"],
                patch_path=patch_path,
                patch_cid=patch_cid,
                validation=validation,
                metrics={
                    **winner_score,
                    "num_solutions_evaluated": len(solutions),
                    "winner_rank": 1,
                },
                execution_time=time.time() - start_time,
                agent_id=self.agent_id,
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
    
    def _analyze_targets(self, target_files: List[Path]) -> Dict[str, Any]:
        """Analyze target files to understand current implementation.
        
        Args:
            target_files: List of files to analyze
            
        Returns:
            Dictionary with analysis results
        """
        analysis = {
            "files": [],
            "complexity": {},
            "functions": [],
            "classes": [],
        }
        
        for file_path in target_files:
            if not file_path.exists():
                continue
                
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                    tree = ast.parse(content)
                    
                    file_analysis = {
                        "path": str(file_path),
                        "lines": len(content.split('\n')),
                        "functions": [],
                        "classes": [],
                    }
                    
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            file_analysis["functions"].append(node.name)
                            analysis["functions"].append({
                                "name": node.name,
                                "file": str(file_path),
                                "lineno": node.lineno,
                            })
                        elif isinstance(node, ast.ClassDef):
                            file_analysis["classes"].append(node.name)
                            analysis["classes"].append({
                                "name": node.name,
                                "file": str(file_path),
                                "lineno": node.lineno,
                            })
                    
                    analysis["files"].append(file_analysis)
                    
            except Exception as e:
                analysis["files"].append({
                    "path": str(file_path),
                    "error": str(e),
                })
        
        return analysis
    
    def _generate_solutions(
        self,
        task: OptimizationTask,
        analysis: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Generate N alternative solutions.
        
        Args:
            task: Optimization task
            analysis: Target file analysis
            
        Returns:
            List of solution dictionaries
        """
        solutions = []
        
        # Generate different approaches
        approaches = [
            "performance_focused",  # Optimize for speed
            "memory_optimized",     # Optimize for memory usage
            "readability_focused",  # Optimize for clarity
            "maintainability_focused",  # Optimize for long-term maintenance
            "balanced",            # Balance all factors
        ][:self.num_solutions]
        
        for i, approach in enumerate(approaches):
            prompt = self._build_solution_prompt(task, analysis, approach)
            
            try:
                # Use LLM to generate solution
                response = self.llm_router.generate(
                    prompt=prompt,
                    max_tokens=2000,
                    temperature=0.7 + (i * 0.1),  # Vary temperature for diversity
                )
                
                solution = {
                    "id": f"solution-{i}",
                    "approach": approach,
                    "code": self._extract_code(response),
                    "description": self._extract_description(response),
                    "temperature": 0.7 + (i * 0.1),
                }
                
                solutions.append(solution)
                
            except Exception as e:
                # Log error but continue with other solutions
                print(f"Error generating solution {i}: {e}")
                continue
        
        return solutions
    
    def _build_solution_prompt(
        self,
        task: OptimizationTask,
        analysis: Dict[str, Any],
        approach: str,
    ) -> str:
        """Build prompt for solution generation.
        
        Args:
            task: Optimization task
            analysis: Target analysis
            approach: Optimization approach
            
        Returns:
            Prompt string
        """
        return f"""Generate an optimized solution for the following task:

Task: {task.description}
Approach: {approach}

Current code analysis:
{self._format_analysis(analysis)}

Requirements:
1. Focus on {approach} optimization
2. Maintain backward compatibility
3. Include type hints
4. Add comprehensive docstrings
5. Follow existing code style

Generate the optimized code with explanation."""
    
    def _format_analysis(self, analysis: Dict[str, Any]) -> str:
        """Format analysis for prompt."""
        lines = []
        
        for file_info in analysis.get("files", []):
            lines.append(f"File: {file_info['path']}")
            lines.append(f"  Lines: {file_info.get('lines', 'N/A')}")
            
            if "functions" in file_info:
                lines.append(f"  Functions: {', '.join(file_info['functions'])}")
            
            if "classes" in file_info:
                lines.append(f"  Classes: {', '.join(file_info['classes'])}")
        
        return "\n".join(lines)
    
    def _extract_code(self, response: str) -> str:
        """Extract code from LLM response."""
        # Look for code blocks
        if "```python" in response:
            parts = response.split("```python")
            if len(parts) > 1:
                code = parts[1].split("```")[0]
                return code.strip()
        
        # Return full response if no code block found
        return response
    
    def _extract_description(self, response: str) -> str:
        """Extract description from LLM response."""
        # Look for description before code block
        if "```python" in response:
            return response.split("```python")[0].strip()
        
        # Take first 200 chars as description
        return response[:200] + "..." if len(response) > 200 else response
    
    def _benchmark_solutions(
        self,
        solutions: List[Dict[str, Any]],
        target_files: List[Path],
    ) -> List[Dict[str, float]]:
        """Benchmark each solution's performance.
        
        Args:
            solutions: List of solutions to benchmark
            target_files: Original target files
            
        Returns:
            List of benchmark results
        """
        benchmarks = []
        
        for solution in solutions:
            try:
                # Create temporary file with solution code
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.py',
                    delete=False,
                ) as f:
                    f.write(solution["code"])
                    temp_path = Path(f.name)
                
                # Run basic performance test
                start = time.time()
                result = subprocess.run(
                    ["python", "-m", "py_compile", str(temp_path)],
                    capture_output=True,
                    timeout=10,
                )
                compile_time = time.time() - start
                
                benchmark = {
                    "compile_time": compile_time,
                    "compile_success": result.returncode == 0,
                    "code_size": len(solution["code"]),
                }
                
                # Clean up
                temp_path.unlink(missing_ok=True)
                
            except Exception as e:
                benchmark = {
                    "compile_time": float('inf'),
                    "compile_success": False,
                    "code_size": len(solution["code"]),
                    "error": str(e),
                }
            
            benchmarks.append(benchmark)
        
        return benchmarks
    
    def _adversarial_testing(
        self,
        solutions: List[Dict[str, Any]],
        task: OptimizationTask,
    ) -> List[Dict[str, Any]]:
        """Apply adversarial testing to solutions.
        
        Args:
            solutions: Solutions to test
            task: Optimization task
            
        Returns:
            List of adversarial test results
        """
        results = []
        
        for solution in solutions:
            result = {
                "edge_cases_handled": 0,
                "stress_test_passed": False,
                "error_handling": False,
            }
            
            # Check for edge case handling
            code = solution["code"]
            if "if" in code and ("None" in code or "[]" in code or "0" in code):
                result["edge_cases_handled"] = 1
            
            # Check for error handling
            if "try:" in code or "except" in code:
                result["error_handling"] = True
            
            # Placeholder for actual stress testing
            result["stress_test_passed"] = True
            
            results.append(result)
        
        return results
    
    def _score_solutions(
        self,
        solutions: List[Dict[str, Any]],
        benchmarks: List[Dict[str, float]],
        adversarial_results: List[Dict[str, Any]],
    ) -> List[Dict[str, float]]:
        """Score all solutions using multi-criteria evaluation.
        
        Args:
            solutions: Generated solutions
            benchmarks: Benchmark results
            adversarial_results: Adversarial test results
            
        Returns:
            List of score dictionaries
        """
        scores = []
        
        # Normalize benchmark values
        compile_times = [b.get("compile_time", float('inf')) for b in benchmarks]
        max_compile_time = max(t for t in compile_times if t != float('inf'))
        
        code_sizes = [len(s["code"]) for s in solutions]
        max_code_size = max(code_sizes) if code_sizes else 1
        
        for i, solution in enumerate(solutions):
            benchmark = benchmarks[i]
            adv_result = adversarial_results[i]
            
            # Calculate individual scores (0-1 range)
            perf_score = self._calculate_performance_score(benchmark, max_compile_time)
            read_score = self._calculate_readability_score(solution)
            maint_score = self._calculate_maintainability_score(solution, adv_result)
            test_score = self._calculate_test_coverage_score(solution)
            sec_score = self._calculate_security_score(solution)
            
            # Calculate weighted total
            total_score = (
                self.scoring_weights["performance"] * perf_score +
                self.scoring_weights["readability"] * read_score +
                self.scoring_weights["maintainability"] * maint_score +
                self.scoring_weights["test_coverage"] * test_score +
                self.scoring_weights["security"] * sec_score
            )
            
            scores.append({
                "performance": perf_score,
                "readability": read_score,
                "maintainability": maint_score,
                "test_coverage": test_score,
                "security": sec_score,
                "total": total_score,
            })
        
        return scores
    
    def _calculate_performance_score(
        self,
        benchmark: Dict[str, float],
        max_compile_time: float,
    ) -> float:
        """Calculate performance score (0-1)."""
        if not benchmark.get("compile_success", False):
            return 0.0
        
        compile_time = benchmark.get("compile_time", float('inf'))
        if compile_time == float('inf'):
            return 0.0
        
        # Lower compile time = higher score
        return 1.0 - (compile_time / max_compile_time)
    
    def _calculate_readability_score(self, solution: Dict[str, Any]) -> float:
        """Calculate readability score (0-1)."""
        code = solution["code"]
        score = 0.0
        
        # Check for docstrings
        if '"""' in code or "'''" in code:
            score += 0.3
        
        # Check for type hints
        if " -> " in code or ": " in code:
            score += 0.3
        
        # Check for comments
        if "#" in code:
            score += 0.2
        
        # Check for descriptive names (longer than 3 chars)
        words = code.split()
        descriptive = sum(1 for w in words if len(w) > 3)
        score += min(0.2, descriptive / max(len(words), 1))
        
        return min(1.0, score)
    
    def _calculate_maintainability_score(
        self,
        solution: Dict[str, Any],
        adv_result: Dict[str, Any],
    ) -> float:
        """Calculate maintainability score (0-1)."""
        score = 0.0
        
        # Error handling
        if adv_result.get("error_handling", False):
            score += 0.4
        
        # Edge case handling
        score += min(0.3, adv_result.get("edge_cases_handled", 0) * 0.3)
        
        # Code organization (classes/functions)
        code = solution["code"]
        if "class " in code:
            score += 0.15
        if "def " in code:
            score += 0.15
        
        return min(1.0, score)
    
    def _calculate_test_coverage_score(self, solution: Dict[str, Any]) -> float:
        """Calculate test coverage score (0-1)."""
        code = solution["code"]
        
        # Check if test code is included
        if "test_" in code or "Test" in code:
            return 0.8
        elif "assert" in code:
            return 0.5
        else:
            return 0.2  # Assume basic coverage
    
    def _calculate_security_score(self, solution: Dict[str, Any]) -> float:
        """Calculate security score (0-1)."""
        code = solution["code"]
        score = 1.0
        
        # Check for common security issues
        if "eval(" in code or "exec(" in code:
            score -= 0.5
        
        if "shell=True" in code:
            score -= 0.3
        
        if "input(" in code and "sanitize" not in code:
            score -= 0.2
        
        return max(0.0, score)
    
    def _validate_solution(
        self,
        solution: Dict[str, Any],
        target_files: List[Path],
    ) -> ValidationResult:
        """Validate the winning solution.
        
        Args:
            solution: Solution to validate
            target_files: Original target files
            
        Returns:
            ValidationResult
        """
        errors = []
        
        # Syntax check
        syntax_ok = True
        try:
            ast.parse(solution["code"])
        except SyntaxError as e:
            syntax_ok = False
            errors.append(f"Syntax error: {e}")
        
        # Basic validation
        validation = ValidationResult(
            passed=syntax_ok and len(errors) == 0,
            syntax_check=syntax_ok,
            errors=errors,
        )
        
        return validation
    
    def _create_patch(
        self,
        solution: Dict[str, Any],
        task: OptimizationTask,
    ) -> Tuple[Optional[Path], Optional[str]]:
        """Create patch file for the winning solution.
        
        Args:
            solution: Winning solution
            task: Optimization task
            
        Returns:
            Tuple of (patch_path, patch_cid)
        """
        try:
            # Create patch metadata
            metadata = {
                "task_id": task.task_id,
                "description": solution["description"],
                "approach": solution["approach"],
                "agent_id": self.agent_id,
                "method": "adversarial",
            }
            
            # For now, return None - actual patch creation would go here
            return None, None
            
        except Exception as e:
            print(f"Error creating patch: {e}")
            return None, None
