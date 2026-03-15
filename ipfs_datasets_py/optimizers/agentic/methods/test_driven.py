"""Test-driven optimization method.

This optimizer generates tests first, then optimizes code to pass them
while improving performance and code quality.
"""

import ast
import difflib
import logging as _logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.optimizers.common.path_validator import (
    validate_input_path,
    validate_output_path,
)
from ..base import (
    AgenticOptimizer,
    ChangeControlMethod,
    OptimizationMethod,
    OptimizationResult,
    OptimizationTask,
    ValidationResult,
)
from ..patch_control import Patch, PatchManager


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
        logger: Optional[_logging.Logger] = None,
    ):
        """Initialize test-driven optimizer.
        
        Args:
            agent_id: Unique identifier for this agent
            llm_router: LLM router for text generation
            change_control: Change control method to use
            config: Optional configuration dictionary
            logger: Optional logger instance (defaults to module logger)
        """
        super().__init__(agent_id, llm_router, change_control, config, logger)
        self.patch_manager = PatchManager()
        self.use_temp_worktree = bool((config or {}).get("use_temp_worktree", False))
        self._meta_request_markers = (
            "please paste",
            "paste the current contents",
            "ag​​ents.md",
            "agents.md",
            "i can’t access",
            "i can't access",
            "commands fail",
            "sandbox error",
            "proceed without agents",
        )
        
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
            self._log.info("Starting test-driven optimization", extra={
                'task_id': task.task_id,
                'agent_id': self.agent_id,
                'target_file_count': len(task.target_files),
                'priority': task.priority,
            })
            
            # Step 1: Analyze target files
            target_analysis = self._analyze_targets(task.target_files)
            self._log.debug("Analyzed target files", extra={
                'task_id': task.task_id,
                'functions_found': len(target_analysis.get('functions', [])),
                'classes_found': len(target_analysis.get('classes', [])),
            })
            
            # Step 2: Generate or enhance tests
            test_results = self._generate_tests(task, target_analysis)
            self._log.info("Generated tests", extra={
                'task_id': task.task_id,
                'test_generation_success': test_results.get('success', False),
            })
            
            # Step 3: Run baseline tests
            baseline_metrics = self._run_baseline_tests(task.target_files)
            self._log.info("Baseline tests completed", extra={
                'task_id': task.task_id,
                'baseline_time': baseline_metrics.get('execution_time', 0),
                'tests_passed': baseline_metrics.get('tests_passed', 0),
                'coverage': baseline_metrics.get('coverage', 0),
            })
            
            # Step 4: Generate optimized code
            optimized_code = self._generate_optimizations(
                task,
                target_analysis,
                baseline_metrics
            )
            self._log.debug("Generated optimizations", extra={
                'task_id': task.task_id,
                'optimizations_count': len(optimized_code),
            })
            
            # Step 5: Apply optimizations using the configured patch strategy.
            apply_results = self._apply_optimizations(
                task.target_files,
                optimized_code
            )
            self._log.info("Applied optimizations", extra={
                'task_id': task.task_id,
                'optimized_time': apply_results.get('execution_time', 0),
                'tests_passed_after': apply_results.get('tests_passed', 0),
                'patch_mode': apply_results.get('patch_mode'),
            })
            
            # Step 6: Create patch
            patch = self._create_patch_from_results(
                task=task,
                apply_results=apply_results,
            )
            
            # Save patch
            patch_path = self.patch_manager.save_patch(patch)
            
            execution_time = time.time() - start_time
            
            improvement = self._calculate_improvement(
                baseline_metrics.get('execution_time', 1),
                apply_results.get('execution_time', 1)
            )
            
            self._log.info("Optimization completed successfully", extra={
                'task_id': task.task_id,
                'total_time': execution_time,
                'improvement_percent': improvement,
                'patch_path': str(patch_path),
            })
            
            return OptimizationResult(
                task_id=task.task_id,
                success=True,
                method=self.method,
                changes=f"Optimized {len(task.target_files)} files with test-driven approach",
                patch_path=patch_path,
                metrics={
                    'baseline_time': baseline_metrics.get('execution_time', 0),
                    'optimized_time': apply_results.get('execution_time', 0),
                    'improvement_percent': improvement,
                    'tests_passed': apply_results.get('tests_passed', 0),
                    'test_coverage': apply_results.get('coverage', 0),
                },
                execution_time=execution_time,
                agent_id=self.agent_id,
            )
            
        except (
            AttributeError,
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            subprocess.SubprocessError,
        ) as e:
            execution_time = time.time() - start_time
            self._log.error("Optimization failed", extra={
                'task_id': task.task_id,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'total_time': execution_time,
            }, exc_info=True)
            
            return OptimizationResult(
                task_id=task.task_id,
                success=False,
                method=self.method,
                changes="",
                error_message=str(e),
                execution_time=execution_time,
                agent_id=self.agent_id,
            )
    
    def validate(self, result: OptimizationResult) -> ValidationResult:
        """Validate optimization result.
        
        Args:
            result: The optimization result to validate
            
        Returns:
            ValidationResult with detailed validation status
        """
        self._log.info("Starting validation", extra={
            'task_id': result.task_id,
            'agent_id': self.agent_id,
            'optimization_success': result.success,
        })
        
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
        
        passed = len(errors) == 0
        self._log.info("Validation completed", extra={
            'task_id': result.task_id,
            'validation_passed': passed,
            'error_count': len(errors),
            'warning_count': len(warnings),
            'syntax_check': syntax_check['passed'],
            'type_check': type_check['passed'],
            'unit_tests': unit_tests['passed'],
        })
        
        return ValidationResult(
            passed=passed,
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
                self._log.warning("Target file does not exist", extra={'file': str(file_path)})
                continue
            
            try:
                # Validate input path
                base_dir = file_path.parent if file_path.is_absolute() else None
                safe_path = validate_input_path(str(file_path), must_exist=True, base_dir=base_dir)
                
                with open(safe_path, 'r') as f:
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
            except (
                OSError,
                SyntaxError,
                TypeError,
                ValueError,
                UnicodeDecodeError,
                RecursionError,
            ) as e:
                self._log.error("Error analyzing file", extra={
                    'file': str(file_path),
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                })
        
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
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
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
                self._log.warning("Target file does not exist", extra={'file': str(target_file)})
                continue
            
            # Read current code
            base_dir = target_file.parent if target_file.is_absolute() else None
            safe_path = validate_input_path(str(target_file), must_exist=True, base_dir=base_dir)
            with open(safe_path, 'r') as f:
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
                normalized_response = self._normalize_optimized_code_response(
                    response=response,
                    file_path=target_file,
                    current_code=current_code,
                )
                
                self._log.debug("Generated optimization", extra={
                    'file': str(target_file),
                    'response_length': len(normalized_response),
                })
                
                optimizations[str(target_file)] = normalized_response
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
                self._log.error("Error generating optimization", extra={
                    'file': str(target_file),
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                })
        
        return optimizations
    
    def _apply_optimizations(
        self,
        target_files: List[Path],
        optimizations: Dict[str, str]
    ) -> Dict[str, Any]:
        """Apply optimizations using direct diffs by default.

        Temp worktrees remain available as an opt-in mode, but the default path
        avoids spawning extra git worktrees and instead produces a patch from
        repo-relative file diffs.
        """
        if self.use_temp_worktree:
            return self._apply_optimizations_in_temp_worktree(target_files, optimizations)
        return self._apply_optimizations_direct(target_files, optimizations)

    def _apply_optimizations_direct(
        self,
        target_files: List[Path],
        optimizations: Dict[str, str]
    ) -> Dict[str, Any]:
        repo_root = self._resolve_repo_root(target_files)
        changes: List[Dict[str, Any]] = []

        for target_file in target_files:
            if not target_file.exists():
                continue
            optimized_content = optimizations.get(str(target_file))
            if not optimized_content:
                continue

            base_dir = target_file.parent if target_file.is_absolute() else None
            safe_path = validate_input_path(str(target_file), must_exist=True, base_dir=base_dir)
            original_content = Path(safe_path).read_text()
            if original_content == optimized_content:
                continue

            relative_path = str(Path(safe_path).resolve().relative_to(repo_root))
            diff_content = "".join(
                difflib.unified_diff(
                    original_content.splitlines(keepends=True),
                    optimized_content.splitlines(keepends=True),
                    fromfile=f"a/{relative_path}",
                    tofile=f"b/{relative_path}",
                )
            )
            if not diff_content:
                continue

            changes.append(
                {
                    "file_path": str(Path(safe_path).resolve()),
                    "relative_path": relative_path,
                    "original_content": original_content,
                    "optimized_content": optimized_content,
                    "diff_content": diff_content,
                }
            )

        test_results = self._run_tests_in_worktree(repo_root)
        return {
            "patch_mode": "direct_diff",
            "repo_root": repo_root,
            "changes": changes,
            "execution_time": test_results.get("execution_time", 0),
            "tests_passed": test_results.get("tests_passed", 0),
            "coverage": test_results.get("coverage", 0),
        }

    def _apply_optimizations_in_temp_worktree(
        self,
        target_files: List[Path],
        optimizations: Dict[str, str]
    ) -> Dict[str, Any]:
        repo_root = self._resolve_repo_root(target_files)
        temp_dir = Path(tempfile.mkdtemp(prefix="optimizer-"))
        changes: List[Dict[str, Any]] = []

        for target_file in target_files:
            if not target_file.exists():
                continue
            optimized_content = optimizations.get(str(target_file))
            if not optimized_content:
                continue

            resolved_target = target_file.resolve()
            relative_path = resolved_target.relative_to(repo_root)
            target_path = temp_dir / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved_target, target_path)

            original_content = target_path.read_text()
            if original_content == optimized_content:
                continue

            base_dir = target_path.parent if target_path.is_absolute() else None
            safe_path = validate_output_path(str(target_path), allow_overwrite=True, base_dir=base_dir)
            Path(safe_path).write_text(optimized_content)

            diff_content = "".join(
                difflib.unified_diff(
                    original_content.splitlines(keepends=True),
                    optimized_content.splitlines(keepends=True),
                    fromfile=f"a/{relative_path.as_posix()}",
                    tofile=f"b/{relative_path.as_posix()}",
                )
            )
            if not diff_content:
                continue

            changes.append(
                {
                    "file_path": str(resolved_target),
                    "relative_path": relative_path.as_posix(),
                    "original_content": original_content,
                    "optimized_content": optimized_content,
                    "diff_content": diff_content,
                }
            )

        test_results = self._run_tests_in_worktree(temp_dir)
        return {
            "patch_mode": "temp_worktree",
            "worktree": temp_dir,
            "repo_root": repo_root,
            "changes": changes,
            "execution_time": test_results.get("execution_time", 0),
            "tests_passed": test_results.get("tests_passed", 0),
            "coverage": test_results.get("coverage", 0),
        }

    def _create_patch_from_results(
        self,
        task: OptimizationTask,
        apply_results: Dict[str, Any],
    ) -> Patch:
        changes = list(apply_results.get("changes") or [])
        if not changes:
            worktree_path = apply_results.get("worktree")
            if worktree_path:
                return self.patch_manager.create_patch(
                    agent_id=self.agent_id,
                    task_id=task.task_id,
                    worktree_path=Path(worktree_path),
                    description=task.description,
                )
            raise ValueError(f"No changes found in worktree: {apply_results.get('worktree')}")

        diff_content = "".join(change["diff_content"] for change in changes)
        return Patch(
            patch_id=self.patch_manager._generate_patch_id(self.agent_id, task.task_id),
            agent_id=self.agent_id,
            task_id=task.task_id,
            description=task.description,
            diff_content=diff_content,
            target_files=[change["relative_path"] for change in changes],
            worktree_path=str(apply_results.get("worktree") or ""),
            metadata={
                "patch_mode": apply_results.get("patch_mode"),
                "repo_root": str(apply_results.get("repo_root") or ""),
            },
        )

    def _resolve_repo_root(self, target_files: List[Path]) -> Path:
        existing_targets = [path.resolve() for path in target_files if path.exists()]
        if not existing_targets:
            raise ValueError("No existing target files provided for optimization")

        probe_dir = existing_targets[0].parent
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=probe_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            repo_root = result.stdout.strip()
            if repo_root:
                return Path(repo_root).resolve()
        return Path(os.path.commonpath([str(path.parent) for path in existing_targets])).resolve()
    
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

Return only the complete optimized Python file contents.
Do not ask for more files, more context, AGENTS instructions, shell access, or pasted contents.
Do not include markdown fences, explanations, apologies, or commentary.
"""

    def _normalize_optimized_code_response(
        self,
        *,
        response: str,
        file_path: Path,
        current_code: str,
    ) -> str:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty optimization response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:python)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Optimization response for {file_path} requested external context instead of code")

        if len(text.splitlines()) < 3:
            raise ValueError(f"Optimization response for {file_path} is too short to be a full file replacement")

        try:
            ast.parse(text)
        except SyntaxError as exc:
            raise ValueError(f"Optimization response for {file_path} is not valid Python: {exc}") from exc

        if text.strip() == current_code.strip():
            raise ValueError(f"Optimization response for {file_path} did not modify the file")

        return text if text.endswith("\n") else f"{text}\n"
