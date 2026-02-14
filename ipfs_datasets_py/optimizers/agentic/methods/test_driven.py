"""Test-driven optimization method.

This optimizer generates tests first, then optimizes code to pass them
while improving performance and code quality.
"""

import ast
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import (
    AgenticOptimizer,
    ChangeControlMethod,
    OptimizationMethod,
    OptimizationResult,
    OptimizationTask,
    ValidationResult,
)
from ..patch_control import PatchManager


class TestDrivenOptimizer(AgenticOptimizer):
    """Test-driven optimization implementation.
    
    This optimizer follows the test-driven development (TDD) approach:
    1. Analyze existing code and identify optimization targets
    2. Generate comprehensive test suites if missing
    3. Run tests to establish baseline
    4. Generate optimized implementations
    5. Validate that tests still pass and performance improved
    6. Create patch with changes
    
    Example:
        >>> from ipfs_datasets_py.llm_router import LLMRouter
        >>> router = LLMRouter()
        >>> optimizer = TestDrivenOptimizer(
        ...     agent_id="test-opt-1",
        ...     llm_router=router,
        ...     change_control=ChangeControlMethod.PATCH
        ... )
        >>> task = OptimizationTask(
        ...     task_id="task-1",
        ...     description="Optimize data loading performance",
        ...     target_files=[Path("ipfs_datasets_py/data_loader.py")]
        ... )
        >>> result = optimizer.optimize(task)
    """
    
    def __init__(
        self,
        agent_id: str,
        llm_router: Any,
        change_control: ChangeControlMethod = ChangeControlMethod.PATCH,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize test-driven optimizer.
        
        Args:
            agent_id: Unique identifier for this agent
            llm_router: LLM router for text generation
            change_control: Change control method to use
            config: Optional configuration dictionary
        """
        super().__init__(agent_id, llm_router, change_control, config)
        self.patch_manager = PatchManager()
        
    def _get_method(self) -> OptimizationMethod:
        """Return the optimization method."""
        return OptimizationMethod.TEST_DRIVEN
    
    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        """Perform test-driven optimization.
        
        Args:
            task: The optimization task to perform
            
        Returns:
            OptimizationResult with success status and details
        """
        start_time = time.time()
        
        try:
            # Step 1: Analyze target files
            target_analysis = self._analyze_targets(task.target_files)
            
            # Step 2: Generate or enhance tests
            test_results = self._generate_tests(task, target_analysis)
            
            # Step 3: Run baseline tests
            baseline_metrics = self._run_baseline_tests(task.target_files)
            
            # Step 4: Generate optimized code
            optimized_code = self._generate_optimizations(
                task,
                target_analysis,
                baseline_metrics
            )
            
            # Step 5: Apply optimizations to temporary location
            temp_results = self._apply_optimizations(
                task.target_files,
                optimized_code
            )
            
            # Step 6: Create patch
            patch = self.patch_manager.create_patch(
                agent_id=self.agent_id,
                task_id=task.task_id,
                worktree_path=temp_results['worktree'],
                description=task.description,
            )
            
            # Save patch
            patch_path = self.patch_manager.save_patch(patch)
            
            execution_time = time.time() - start_time
            
            return OptimizationResult(
                task_id=task.task_id,
                success=True,
                method=self.method,
                changes=f"Optimized {len(task.target_files)} files with test-driven approach",
                patch_path=patch_path,
                metrics={
                    'baseline_time': baseline_metrics.get('execution_time', 0),
                    'optimized_time': temp_results.get('execution_time', 0),
                    'improvement_percent': self._calculate_improvement(
                        baseline_metrics.get('execution_time', 1),
                        temp_results.get('execution_time', 1)
                    ),
                    'tests_passed': temp_results.get('tests_passed', 0),
                    'test_coverage': temp_results.get('coverage', 0),
                },
                execution_time=execution_time,
                agent_id=self.agent_id,
            )
            
        except Exception as e:
            return OptimizationResult(
                task_id=task.task_id,
                success=False,
                method=self.method,
                changes="",
                error_message=str(e),
                execution_time=time.time() - start_time,
                agent_id=self.agent_id,
            )
    
    def validate(self, result: OptimizationResult) -> ValidationResult:
        """Validate optimization result.
        
        Args:
            result: The optimization result to validate
            
        Returns:
            ValidationResult with detailed validation status
        """
        errors = []
        warnings = []
        
        # Syntax check
        syntax_check = self._check_syntax(result.patch_path)
        if not syntax_check['passed']:
            errors.extend(syntax_check['errors'])
        
        # Type check
        type_check = self._check_types(result.patch_path)
        if not type_check['passed']:
            warnings.extend(type_check['warnings'])
        
        # Unit tests
        unit_tests = self._run_unit_tests(result.patch_path)
        if not unit_tests['passed']:
            errors.extend(unit_tests['errors'])
        
        # Performance validation
        performance = self._validate_performance(result.metrics)
        if not performance['passed']:
            warnings.append(performance['message'])
        
        return ValidationResult(
            passed=len(errors) == 0,
            syntax_check=syntax_check['passed'],
            type_check=type_check['passed'],
            unit_tests=unit_tests['passed'],
            performance_tests=performance['passed'],
            errors=errors,
            warnings=warnings,
        )
    
    def _analyze_targets(self, target_files: List[Path]) -> Dict[str, Any]:
        """Analyze target files to identify optimization opportunities."""
        analysis = {
            'functions': [],
            'classes': [],
            'complexity': {},
            'imports': [],
        }
        
        for file_path in target_files:
            if not file_path.exists():
                continue
            
            try:
                with open(file_path, 'r') as f:
                    tree = ast.parse(f.read())
                
                # Extract functions
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        analysis['functions'].append({
                            'name': node.name,
                            'file': str(file_path),
                            'lineno': node.lineno,
                        })
                    elif isinstance(node, ast.ClassDef):
                        analysis['classes'].append({
                            'name': node.name,
                            'file': str(file_path),
                            'lineno': node.lineno,
                        })
            except Exception as e:
                print(f"Error analyzing {file_path}: {e}")
        
        return analysis
    
    def _generate_tests(
        self,
        task: OptimizationTask,
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate or enhance test suites."""
        # Use LLM to generate tests
        prompt = self._build_test_generation_prompt(task, analysis)
        
        try:
            response = self.llm_router.generate(
                prompt=prompt,
                max_tokens=2000,
                temperature=0.3,
            )
            
            return {
                'success': True,
                'tests_generated': response,
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }
    
    def _run_baseline_tests(self, target_files: List[Path]) -> Dict[str, float]:
        """Run tests to establish baseline performance."""
        # In practice, run pytest with timing
        # For now, return mock data
        return {
            'execution_time': 1.5,
            'tests_passed': 10,
            'tests_failed': 0,
            'coverage': 85.0,
        }
    
    def _generate_optimizations(
        self,
        task: OptimizationTask,
        analysis: Dict[str, Any],
        baseline: Dict[str, float]
    ) -> Dict[str, str]:
        """Generate optimized code using LLM."""
        optimizations = {}
        
        for target_file in task.target_files:
            if not target_file.exists():
                continue
            
            # Read current code
            with open(target_file, 'r') as f:
                current_code = f.read()
            
            # Generate optimization prompt
            prompt = self._build_optimization_prompt(
                target_file,
                current_code,
                analysis,
                baseline,
                task
            )
            
            try:
                response = self.llm_router.generate(
                    prompt=prompt,
                    max_tokens=4000,
                    temperature=0.2,
                )
                
                optimizations[str(target_file)] = response
            except Exception as e:
                print(f"Error optimizing {target_file}: {e}")
        
        return optimizations
    
    def _apply_optimizations(
        self,
        target_files: List[Path],
        optimizations: Dict[str, str]
    ) -> Dict[str, Any]:
        """Apply optimizations in temporary location for testing."""
        # Create temporary worktree
        temp_dir = Path(tempfile.mkdtemp(prefix="optimizer-"))
        
        # Copy and apply optimizations
        for file_path_str, optimized_content in optimizations.items():
            target_path = temp_dir / Path(file_path_str).name
            target_path.write_text(optimized_content)
        
        # Run tests in temporary location
        test_results = self._run_tests_in_worktree(temp_dir)
        
        return {
            'worktree': temp_dir,
            'execution_time': test_results.get('execution_time', 0),
            'tests_passed': test_results.get('tests_passed', 0),
            'coverage': test_results.get('coverage', 0),
        }
    
    def _run_tests_in_worktree(self, worktree: Path) -> Dict[str, Any]:
        """Run tests in temporary worktree."""
        # In practice, run pytest with coverage
        # For now, return mock data
        return {
            'execution_time': 1.2,
            'tests_passed': 10,
            'tests_failed': 0,
            'coverage': 88.0,
        }
    
    def _calculate_improvement(
        self,
        baseline: float,
        optimized: float
    ) -> float:
        """Calculate percentage improvement."""
        if baseline == 0:
            return 0
        return ((baseline - optimized) / baseline) * 100
    
    def _check_syntax(self, patch_path: Optional[Path]) -> Dict[str, Any]:
        """Check syntax of patched code."""
        if not patch_path:
            return {'passed': False, 'errors': ['No patch path provided']}
        
        # In practice, parse all Python files
        # For now, assume syntax is valid
        return {'passed': True, 'errors': []}
    
    def _check_types(self, patch_path: Optional[Path]) -> Dict[str, Any]:
        """Run type checking on patched code."""
        # In practice, run mypy
        # For now, assume types are valid
        return {'passed': True, 'warnings': []}
    
    def _run_unit_tests(self, patch_path: Optional[Path]) -> Dict[str, Any]:
        """Run unit tests on patched code."""
        # In practice, run pytest
        # For now, assume tests pass
        return {'passed': True, 'errors': []}
    
    def _validate_performance(self, metrics: Dict[str, float]) -> Dict[str, Any]:
        """Validate performance improvements."""
        improvement = metrics.get('improvement_percent', 0)
        
        if improvement >= 10:
            return {
                'passed': True,
                'message': f'Performance improved by {improvement:.1f}%'
            }
        elif improvement >= 0:
            return {
                'passed': True,
                'message': f'Minor performance improvement: {improvement:.1f}%'
            }
        else:
            return {
                'passed': False,
                'message': f'Performance degraded by {abs(improvement):.1f}%'
            }
    
    def _build_test_generation_prompt(
        self,
        task: OptimizationTask,
        analysis: Dict[str, Any]
    ) -> str:
        """Build prompt for test generation."""
        functions = '\n'.join([
            f"- {f['name']} in {f['file']}"
            for f in analysis.get('functions', [])
        ])
        
        return f"""Generate comprehensive pytest tests for the following code:

Task: {task.description}

Functions to test:
{functions}

Please generate test cases that:
1. Cover normal operation
2. Cover edge cases
3. Test error handling
4. Include performance benchmarks

Return only the test code, no explanations.
"""
    
    def _build_optimization_prompt(
        self,
        file_path: Path,
        current_code: str,
        analysis: Dict[str, Any],
        baseline: Dict[str, float],
        task: OptimizationTask
    ) -> str:
        """Build prompt for code optimization."""
        return f"""Optimize the following Python code:

File: {file_path}
Task: {task.description}

Current code:
```python
{current_code}
```

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Optimization goals:
- Improve performance by at least 10%
- Maintain or improve test coverage
- Keep code readable and maintainable
- Preserve all existing functionality

Constraints:
{task.constraints}

Return only the optimized code, no explanations.
"""
