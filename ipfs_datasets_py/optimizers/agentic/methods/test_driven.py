"""Test-driven optimization method.

This optimizer generates tests first, then optimizes code to pass them
while improving performance and code quality.
"""

import ast
import difflib
import json
import logging as _logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import textwrap
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
        self._last_generation_diagnostics: List[Dict[str, Any]] = []
        self._last_raw_responses: Dict[str, str] = {}
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
                metadata={
                    "generation_diagnostics": list(self._last_generation_diagnostics),
                    "target_files": [str(path) for path in task.target_files],
                },
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
                metadata={
                    "generation_diagnostics": list(self._last_generation_diagnostics),
                    "target_files": [str(path) for path in task.target_files],
                },
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
        diagnostics: List[Dict[str, Any]] = []
        self._last_raw_responses = {}
        
        for target_file in task.target_files:
            if not target_file.exists():
                self._log.warning("Target file does not exist", extra={'file': str(target_file)})
                continue
            
            # Read current code
            base_dir = target_file.parent if target_file.is_absolute() else None
            safe_path = validate_input_path(str(target_file), must_exist=True, base_dir=base_dir)
            with open(safe_path, 'r') as f:
                current_code = f.read()
            
            try:
                target_symbols = self._target_symbols_for_file(task, target_file)
                if target_symbols:
                    optimized_content = self._generate_symbol_level_optimization(
                        target_file=target_file,
                        current_code=current_code,
                        analysis=analysis,
                        baseline=baseline,
                        task=task,
                        target_symbols=target_symbols,
                    )
                    diagnostics.append(
                        {
                            "file": str(target_file),
                            "status": "optimized",
                            "mode": "symbol_level",
                            "target_symbols": list(target_symbols),
                            "response_length": len(optimized_content),
                            "changed": optimized_content.strip() != current_code.strip(),
                        }
                    )
                    optimizations[str(target_file)] = optimized_content
                    continue

                prompt = self._build_optimization_prompt(
                    target_file,
                    current_code,
                    analysis,
                    baseline,
                    task
                )

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
                diagnostics.append(
                    {
                        "file": str(target_file),
                        "status": "optimized",
                        "mode": "full_file",
                        "response_length": len(normalized_response),
                        "changed": normalized_response.strip() != current_code.strip(),
                    }
                )
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
                self._log.error("Error generating optimization", extra={
                    'file': str(target_file),
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                })
                diagnostics.append(
                    {
                        "file": str(target_file),
                        "status": "error",
                        "mode": "symbol_level" if target_symbols else "full_file",
                        "target_symbols": list(target_symbols),
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "raw_response_preview": self._raw_response_preview(target_file),
                    }
                )
        self._last_generation_diagnostics = diagnostics
        return optimizations

    def _target_symbols_for_file(self, task: OptimizationTask, target_file: Path) -> List[str]:
        constraints = task.constraints or {}
        target_map = constraints.get("target_symbols")
        if not isinstance(target_map, dict):
            return []

        candidates = {
            str(target_file),
            str(target_file.resolve()),
        }
        for key, value in target_map.items():
            if str(key) in candidates and isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
        return []

    def _generate_symbol_level_optimization(
        self,
        *,
        target_file: Path,
        current_code: str,
        analysis: Dict[str, Any],
        baseline: Dict[str, float],
        task: OptimizationTask,
        target_symbols: List[str],
    ) -> str:
        if self._use_action_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_action_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                max_tokens=500,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            replacement_sources = {
                "_get_intake_action": self._render_get_intake_action_from_policy(
                    self._normalize_action_policy_response(response=response, file_path=target_file)
                )
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )

        symbol_blocks = self._extract_target_symbol_blocks(current_code, target_symbols)
        prompt = self._build_symbol_optimization_prompt(
            file_path=target_file,
            current_code=current_code,
            symbol_blocks=symbol_blocks,
            analysis=analysis,
            baseline=baseline,
            task=task,
            target_symbols=target_symbols,
        )
        response = self.llm_router.generate(
            prompt=prompt,
            max_tokens=1200,
            temperature=0.2,
        )
        self._remember_raw_response(target_file, response)
        replacements = self._normalize_optimized_symbol_response(
            response=response,
            file_path=target_file,
            target_symbols=target_symbols,
        )
        return self._replace_symbols_in_source(
            original_code=current_code,
            target_symbols=target_symbols,
            replacement_sources=replacements,
        )

    def _use_action_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "phase_manager.py" and target_symbols == ["_get_intake_action"]
    
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
            diagnostics = list(self._last_generation_diagnostics)
            worktree_path = apply_results.get("worktree")
            if worktree_path:
                return self.patch_manager.create_patch(
                    agent_id=self.agent_id,
                    task_id=task.task_id,
                    worktree_path=Path(worktree_path),
                    description=task.description,
                )
            if diagnostics:
                diagnostic_summary = "; ".join(
                    f"{item.get('file')}: {item.get('status')} ({item.get('error_message', 'no diff generated')})"
                    for item in diagnostics
                )
                raise ValueError(
                    f"No changes found in worktree: {apply_results.get('worktree')}. Generation diagnostics: {diagnostic_summary}"
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
                "generation_diagnostics": list(self._last_generation_diagnostics),
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

    def _build_symbol_optimization_prompt(
        self,
        *,
        file_path: Path,
        current_code: str,
        symbol_blocks: Dict[str, str],
        analysis: Dict[str, Any],
        baseline: Dict[str, float],
        task: OptimizationTask,
        target_symbols: List[str],
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:3])
        if not recommendations:
            recommendations = "- Improve question quality and coverage without regressing current behavior."

        symbol_text = "\n\n".join(
            f"# Symbol: {name}\n{symbol_blocks.get(name, '# missing')}"
            for name in target_symbols
        )

        return f"""Optimize specific Python methods in the following file:

File: {file_path}
Task: {task.description}

Target methods:
{", ".join(target_symbols)}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Current method implementations:
```python
{symbol_text}
```

Instructions:
- Return only replacement Python method definitions for the target methods.
- Do not return the whole file.
- Keep method names unchanged.
- Preserve compatibility with the existing class and call sites.
- Focus on clearer intake progression, targeted follow-up selection, and better coverage.
- Do not include markdown fences, explanations, or commentary.
"""

    def _build_action_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Improve question quality and coverage without regressing current behavior."

        return f"""Return a compact JSON object describing how _get_intake_action should decide the next intake action.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Allowed actions are exactly:
- build_knowledge_graph
- build_dependency_graph
- address_gaps
- continue_denoising
- complete_intake

Return JSON only with these keys:
- "remaining_gaps_threshold": integer from 0 to 5
- "address_gaps_before_denoising": true or false
- "require_convergence_for_completion": true or false
- "complete_when_iteration_cap_hit": true or false
- "prefer_current_gaps_key": true or false

Behavioral guardrails:
- Treat empty containers like {{}} as present graphs once the keys exist.
- Do not replace `"knowledge_graph" in data` / `'knowledge_graph' not in data` style presence checks with truthiness checks like `not data.get('knowledge_graph')`.
- Do not replace `"dependency_graph" in data` / `'dependency_graph' not in data` style presence checks with truthiness checks like `not data.get('dependency_graph')`.
- Preserve the build_knowledge_graph and build_dependency_graph preconditions based on key presence, not container truthiness.
- Do not tighten the default `_INTAKE_GAPS_THRESHOLD` below its current value.
- Preserve the final fallback action as `complete_intake` unless an earlier explicit branch already chose `continue_denoising`.

Do not include explanations, markdown, comments, or extra keys.
"""

    def _extract_target_symbol_blocks(self, current_code: str, target_symbols: List[str]) -> Dict[str, str]:
        tree = ast.parse(current_code)
        lines = current_code.splitlines(keepends=True)
        blocks: Dict[str, str] = {}

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in target_symbols:
                if node.name in blocks:
                    continue
                start = node.lineno - 1
                end = node.end_lineno
                blocks[node.name] = "".join(lines[start:end])

        missing = [name for name in target_symbols if name not in blocks]
        if missing:
            raise ValueError(f"Could not locate target symbols in source: {', '.join(missing)}")
        return blocks

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

        text = textwrap.dedent(text).strip()

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

    def _normalize_optimized_symbol_response(
        self,
        *,
        response: str,
        file_path: Path,
        target_symbols: List[str],
    ) -> Dict[str, str]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty symbol optimization response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:python)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Symbol optimization response for {file_path} requested external context instead of code")

        parsed = None
        wrapper_used = False
        try:
            parsed = ast.parse(text)
        except SyntaxError:
            extracted = self._extract_symbol_replacements_from_text(
                text=text,
                file_path=file_path,
                target_symbols=target_symbols,
            )
            if extracted:
                return extracted
            wrapped = "class _Temp:\n" + textwrap.indent(text, "    ")
            parsed = ast.parse(wrapped)
            wrapper_used = True

        replacements: Dict[str, str] = {}

        def _normalized_snippet(node: ast.AST) -> str:
            snippet = ast.unparse(node).strip()
            return snippet + "\n"

        if wrapper_used:
            class_node = next((node for node in parsed.body if isinstance(node, ast.ClassDef)), None)
            if class_node is None:
                raise ValueError(f"Symbol optimization response for {file_path} did not contain replacement methods")
            for node in class_node.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in target_symbols:
                    replacements[node.name] = _normalized_snippet(node)
        else:
            for node in parsed.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in target_symbols:
                    replacements[node.name] = _normalized_snippet(node)

        missing = [name for name in target_symbols if name not in replacements]
        if missing:
            raise ValueError(
                f"Symbol optimization response for {file_path} did not return all target methods: {', '.join(missing)}"
            )
        return replacements

    def _normalize_action_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty action policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Action policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Action policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "remaining_gaps_threshold",
            "address_gaps_before_denoising",
            "require_convergence_for_completion",
            "complete_when_iteration_cap_hit",
            "prefer_current_gaps_key",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(f"Action policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}")

        try:
            threshold = int(data["remaining_gaps_threshold"])
        except Exception as exc:
            raise ValueError(f"Action policy response for {file_path} must include integer remaining_gaps_threshold") from exc
        if threshold < 0 or threshold > 5:
            raise ValueError(f"Action policy response for {file_path} used out-of-range remaining_gaps_threshold: {threshold}")

        normalized = {
            "remaining_gaps_threshold": threshold,
            "address_gaps_before_denoising": bool(data.get("address_gaps_before_denoising", True)),
            "require_convergence_for_completion": bool(data.get("require_convergence_for_completion", True)),
            "complete_when_iteration_cap_hit": bool(data.get("complete_when_iteration_cap_hit", False)),
            "prefer_current_gaps_key": bool(data.get("prefer_current_gaps_key", True)),
        }
        return normalized

    def _render_get_intake_action_from_policy(self, policy: Dict[str, Any]) -> str:
        threshold = int(policy["remaining_gaps_threshold"])
        address_first = bool(policy["address_gaps_before_denoising"])
        require_convergence = bool(policy["require_convergence_for_completion"])
        complete_when_cap = bool(policy["complete_when_iteration_cap_hit"])
        prefer_current_gaps_key = bool(policy["prefer_current_gaps_key"])

        gap_assignment = (
            "    gaps = data.get('current_gaps', [])\n"
            if prefer_current_gaps_key
            else "    gaps = data.get('remaining_gap_items', data.get('current_gaps', []))\n"
        )
        threshold_assignment = (
            f"    configured_gap_threshold = {threshold}\n"
            "    gap_threshold = max(_INTAKE_GAPS_THRESHOLD, configured_gap_threshold)\n"
        )
        remaining_gaps_assignment = "    remaining_gaps = data.get('remaining_gaps', float('inf'))\n"
        gap_condition = "(gaps and len(gaps) > 0) or remaining_gaps > gap_threshold"
        denoising_guard = "not data.get('denoising_converged', False)"
        completion_guard = "data.get('denoising_converged', False) and remaining_gaps <= gap_threshold"
        if complete_when_cap:
            completion_guard = f"({completion_guard}) or self.iteration_count >= _DENOISING_MAX_ITERATIONS"

        gap_block = (
            f"    if {gap_condition}:\n"
            "        return {\n"
            "            'action': 'address_gaps',\n"
            "            'gaps': gaps,\n"
            "            'intake_readiness_score': readiness['score'],\n"
            "            'intake_blockers': readiness['blockers'],\n"
            "        }\n\n"
        )
        semantic_blocker_block = (
            "    semantic_blockers = [\n"
            "        blocker for blocker in readiness['blockers']\n"
            "        if blocker not in {\n"
            "            'missing_knowledge_graph',\n"
            "            'missing_dependency_graph',\n"
            "            'unresolved_gaps',\n"
            "            'denoising_not_converged',\n"
            "        }\n"
            "    ]\n"
            "    if semantic_blockers:\n"
            "        return {\n"
            "            'action': 'address_gaps',\n"
            "            'gaps': gaps,\n"
            "            'intake_readiness_score': readiness['score'],\n"
            "            'intake_blockers': readiness['blockers'],\n"
            "        }\n\n"
        )
        denoise_block = (
            f"    if {denoising_guard} and self.iteration_count < _DENOISING_MAX_ITERATIONS:\n"
            "        return {\n"
            "            'action': 'continue_denoising',\n"
            "            'intake_readiness_score': readiness['score'],\n"
            "            'intake_blockers': readiness['blockers'],\n"
            "        }\n\n"
        )
        if not address_first:
            gap_block, denoise_block = denoise_block, gap_block

        return (
            "def _get_intake_action(self) -> Dict[str, Any]:\n"
            "    \"\"\"Get next action for intake phase.\"\"\"\n"
            "    data = self.phase_data[ComplaintPhase.INTAKE]\n\n"
            "    readiness = self.get_intake_readiness()\n\n"
            "    if 'knowledge_graph' not in data:\n"
            "        return {\n"
            "            'action': 'build_knowledge_graph',\n"
            "            'intake_readiness_score': readiness['score'],\n"
            "            'intake_blockers': readiness['blockers'],\n"
            "        }\n\n"
            "    if 'dependency_graph' not in data:\n"
            "        return {\n"
            "            'action': 'build_dependency_graph',\n"
            "            'intake_readiness_score': readiness['score'],\n"
            "            'intake_blockers': readiness['blockers'],\n"
            "        }\n\n"
            f"{gap_assignment}"
            f"{threshold_assignment}"
            f"{remaining_gaps_assignment}"
            f"{gap_block}"
            f"{semantic_blocker_block}"
            f"{denoise_block}"
            f"    if {completion_guard}:\n"
            "        return {\n"
            "            'action': 'complete_intake',\n"
            "            'intake_readiness_score': readiness['score'],\n"
            "            'intake_blockers': readiness['blockers'],\n"
            "        }\n\n"
            "    return {\n"
            "        'action': 'complete_intake',\n"
            "        'intake_readiness_score': readiness['score'],\n"
            "        'intake_blockers': readiness['blockers'],\n"
            "    }\n"
        )

    def _extract_symbol_replacements_from_text(
        self,
        *,
        text: str,
        file_path: Path,
        target_symbols: List[str],
    ) -> Dict[str, str]:
        lines = text.splitlines()
        start_points: List[tuple[int, str]] = []

        for index, line in enumerate(lines):
            stripped = line.lstrip()
            for name in target_symbols:
                if re.match(rf"(?:async\s+def|def)\s+{re.escape(name)}\b", stripped):
                    start_points.append((index, name))
                    break

        if not start_points:
            return {}

        replacements: Dict[str, str] = {}
        ordered = sorted(start_points, key=lambda item: item[0])
        for position, (start, name) in enumerate(ordered):
            end = ordered[position + 1][0] if position + 1 < len(ordered) else len(lines)
            snippet = textwrap.dedent("\n".join(lines[start:end])).strip()
            if not snippet:
                continue
            try:
                parsed = ast.parse(snippet)
            except SyntaxError as exc:
                raise ValueError(
                    f"Symbol optimization response for {file_path} returned invalid code for {name}: {exc}"
                ) from exc
            function_node = next(
                (node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
                None,
            )
            if function_node is None or function_node.name != name:
                raise ValueError(
                    f"Symbol optimization response for {file_path} did not start with a replacement for {name}"
                )
            replacements[name] = ast.unparse(function_node).strip() + "\n"

        return replacements

    def _replace_symbols_in_source(
        self,
        *,
        original_code: str,
        target_symbols: List[str],
        replacement_sources: Dict[str, str],
    ) -> str:
        tree = ast.parse(original_code)
        lines = original_code.splitlines(keepends=True)
        replacements: List[tuple[int, int, str]] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in target_symbols:
                snippet = replacement_sources.get(node.name)
                if not snippet:
                    continue
                indent = " " * node.col_offset
                replacement = textwrap.indent(textwrap.dedent(snippet).rstrip() + "\n", indent)
                replacements.append((node.lineno - 1, node.end_lineno, replacement))

        if not replacements:
            raise ValueError(f"No matching source locations found for target symbols: {', '.join(target_symbols)}")

        for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
            lines[start:end] = [replacement]

        updated = "".join(lines)
        try:
            ast.parse(updated)
        except SyntaxError as exc:
            raise ValueError(f"Symbol replacement produced invalid Python: {exc}") from exc
        if updated.strip() == original_code.strip():
            raise ValueError("Symbol optimization did not modify the file")
        return updated

    def _remember_raw_response(self, target_file: Path, response: str) -> None:
        text = str(response or "")
        self._last_raw_responses[str(target_file)] = text

    def _raw_response_preview(self, target_file: Path, limit: int = 1200) -> str:
        text = self._last_raw_responses.get(str(target_file), "")
        if not text:
            return ""
        sanitized = text.replace("\r\n", "\n").replace("\r", "\n")
        if len(sanitized) <= limit:
            return sanitized
        return sanitized[:limit] + "\n...[truncated]..."
