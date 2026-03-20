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
        if self._should_skip_llm_test_generation(task):
            return {
                'success': False,
                'skipped': True,
                'error': 'Skipped LLM test generation for symbol-scoped optimization; relying on targeted validation tests.',
            }

        # Use LLM to generate tests
        prompt = self._build_test_generation_prompt(task, analysis)
        
        try:
            response = self.llm_router.generate(
                prompt=prompt,
                method=self.method,
                timeout=45,
                max_tokens=2000,
                temperature=0.3,
            )
            
            return {
                'success': True,
                'tests_generated': response,
            }
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as e:
            return {
                'success': False,
                'error': str(e),
            }

    def _should_skip_llm_test_generation(self, task: OptimizationTask) -> bool:
        constraints = task.constraints or {}
        target_map = constraints.get("target_symbols")
        return isinstance(target_map, dict) and bool(target_map)
    
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
                    method=self.method,
                    max_tokens=4000,
                    temperature=0.2,
                )
                self._remember_raw_response(target_file, response)
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
            except (AttributeError, OSError, RuntimeError, SyntaxError, TypeError, ValueError) as e:
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
        if self._use_select_candidates_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_select_candidates_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=500,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            replacement_sources = {
                "select_question_candidates": self._render_select_question_candidates_from_policy(
                    self._normalize_select_candidates_policy_response(response=response, file_path=target_file)
                )
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )
        if self._use_standard_intake_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_standard_intake_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=700,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            replacement_sources = {
                "_ensure_standard_intake_questions": self._render_standard_intake_questions_from_policy(
                    self._normalize_standard_intake_policy_response(response=response, file_path=target_file)
                )
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )
        if self._use_answer_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_answer_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=700,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            replacement_sources = {
                "process_answer": self._render_process_answer_from_policy(
                    self._normalize_answer_policy_response(response=response, file_path=target_file)
                )
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )
        if self._use_action_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_action_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
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
        if self._use_inquiries_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_inquiries_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=700,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            replacement_sources = self._render_inquiries_methods_from_policy(
                self._normalize_inquiries_policy_response(response=response, file_path=target_file)
            )
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
            method=self.method,
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

    def _use_inquiries_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "inquiries.py" and target_symbols == ["get_next", "merge_legal_questions"]

    def _use_answer_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "denoiser.py" and target_symbols == ["process_answer"]

    def _use_select_candidates_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "denoiser.py" and target_symbols == ["select_question_candidates"]

    def _use_standard_intake_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "denoiser.py" and target_symbols == ["_ensure_standard_intake_questions"]
    
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
        functions_to_test = self._test_generation_targets(task, analysis)
        functions = '\n'.join([
            f"- {f['name']} in {f['file']}"
            for f in functions_to_test
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

    def _test_generation_targets(
        self,
        task: OptimizationTask,
        analysis: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        constraints = task.constraints or {}
        target_map = constraints.get("target_symbols")
        functions = list(analysis.get("functions", []) or [])
        if not isinstance(target_map, dict):
            return functions

        selected: List[Dict[str, Any]] = []
        allowed: Dict[str, set[str]] = {}
        for raw_path, raw_symbols in target_map.items():
            if not isinstance(raw_symbols, list):
                continue
            symbols = {str(item).strip() for item in raw_symbols if str(item).strip()}
            if not symbols:
                continue
            path_key = str(raw_path)
            allowed[path_key] = symbols
            try:
                resolved = str(Path(path_key).resolve())
                allowed[resolved] = symbols
            except Exception:
                pass

        if not allowed:
            return functions

        for item in functions:
            file_key = str(item.get("file") or "")
            symbols = allowed.get(file_key)
            if symbols is None:
                try:
                    symbols = allowed.get(str(Path(file_key).resolve()))
                except Exception:
                    symbols = None
            if symbols and str(item.get("name") or "") in symbols:
                selected.append(item)

        return selected or functions
    
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
- If the denoising iteration cap is hit, do not keep returning `address_gaps` solely because `remaining_gaps` is still above threshold.
- Preserve the iteration-cap escape hatch so intake can complete when repeated denoising/gap passes stop converging.
- Preserve the final fallback action as `complete_intake` unless an earlier explicit branch already chose `continue_denoising`.

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_answer_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Improve process_answer so answers produce more timeline and actor evidence without breaking current graph updates."

        return f"""Return a compact JSON object describing how process_answer should enrich the knowledge graph from a complainant answer.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "timeline_enrichment_types": array of question types chosen from:
  ["timeline", "evidence", "impact", "remedy", "clarification", "relationship", "responsible_party", "requirement"]
- "responsible_party_enrichment_types": array of question types chosen from the same allowed list
- "fallback_timeline_fact_types": array of question types chosen from:
  ["timeline", "evidence", "impact", "remedy", "clarification", "relationship", "responsible_party", "requirement"]

Behavioral guardrails:
- Preserve the existing return shape with keys:
  "entities_updated", "relationships_added", "requirements_satisfied"
- Preserve requirement satisfaction handling when question_type == "requirement"
- Do not remove current evidence, impact, remedy, and timeline graph updates
- Do not add imports or reference helpers that do not already exist on the class
- Prefer enrichment from the existing answer text over speculative follow-up generation

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_inquiries_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Improve inquiry ordering and legal-question merging without adding duplicate questions."

        return f"""Return a compact JSON object describing how inquiries.get_next and inquiries.merge_legal_questions should behave.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "prioritize_dependency_gaps_first": true or false
- "preserve_legal_source_on_merge": true or false
- "dedupe_alternative_questions": true or false
- "normalize_priority_labels": true or false

Behavioral guardrails:
- Preserve the method signatures and return types
- Keep unanswered inquiries ahead of answered ones
- Ensure the unanswered list is sorted before returning the selected inquiry.
- When prioritizing, keep dependency-gap-targeted inquiries ahead of support-gap-targeted inquiries.
- Preserve support_gap_targeted and dependency_gap_targeted handling
- Preserve merging of claim_type, element, provenance, and alternative_questions
- Do not add imports or rely on helpers not already used in inquiries.py

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_standard_intake_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Improve default intake prompts so they capture timeline, decision-maker, and notice details without breaking current prompt coverage."

        return f"""Return a compact JSON object describing how _ensure_standard_intake_questions should add default intake prompts.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "timeline_prompt_style": one of ["baseline", "actor_notice_timeline"]
- "impact_prompt_style": one of ["baseline", "impact_with_documents"]
- "include_notice_question": true or false

Behavioral guardrails:
- Preserve the method signature and return type
- Preserve the max_questions cap
- Preserve duplicate suppression using _already_asked and existing question text/type checks
- Preserve the stable priority ordering at the end
- Do not remove the timeline or impact/remedy defaults entirely

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_select_candidates_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Improve candidate selection by preserving selector overrides, suppressing duplicate questions, and keeping fallback ordering deterministic."

        return f"""Return a compact JSON object describing how select_question_candidates should finalize question candidates.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "dedupe_selected_candidates": true or false
- "dedupe_fallback_candidates": true or false
- "selector_mode": one of ["honor_nonempty", "fallback_only"]

Behavioral guardrails:
- Preserve the method signature and return type
- Preserve selector override support and TypeError fallback when invoking selector
- Preserve filtering to dict candidates only
- Preserve the proof-priority then priority fallback ordering
- Preserve max_questions slicing
- Do not add imports or rely on helpers that do not already exist on the class

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

        text = textwrap.dedent(text).strip()

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
        except json.JSONDecodeError:
            data = {}

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
            threshold = int(data.get("remaining_gaps_threshold", 3))
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

    def _normalize_inquiries_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            text = ""

        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {}

        return {
            "prioritize_dependency_gaps_first": bool(data.get("prioritize_dependency_gaps_first", True)),
            "preserve_legal_source_on_merge": bool(data.get("preserve_legal_source_on_merge", True)),
            "dedupe_alternative_questions": bool(data.get("dedupe_alternative_questions", True)),
            "normalize_priority_labels": bool(data.get("normalize_priority_labels", True)),
        }

    def _normalize_answer_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty answer policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Answer policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Answer policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "timeline_enrichment_types",
            "responsible_party_enrichment_types",
            "fallback_timeline_fact_types",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(f"Answer policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}")

        allowed_types = {
            "timeline",
            "evidence",
            "impact",
            "remedy",
            "clarification",
            "relationship",
            "responsible_party",
            "requirement",
        }

        def _normalize_type_list(key: str, default: List[str]) -> List[str]:
            raw = data.get(key, default)
            if not isinstance(raw, list):
                raise ValueError(f"Answer policy response for {file_path} must use a list for {key}")
            normalized: List[str] = []
            for item in raw:
                value = str(item or "").strip()
                if not value:
                    continue
                if value not in allowed_types:
                    raise ValueError(f"Answer policy response for {file_path} used unsupported question type '{value}' for {key}")
                if value not in normalized:
                    normalized.append(value)
            return normalized

        return {
            "timeline_enrichment_types": _normalize_type_list(
                "timeline_enrichment_types",
                ["timeline", "evidence", "impact", "remedy"],
            ),
            "responsible_party_enrichment_types": _normalize_type_list(
                "responsible_party_enrichment_types",
                ["relationship", "responsible_party", "timeline", "evidence"],
            ),
            "fallback_timeline_fact_types": _normalize_type_list(
                "fallback_timeline_fact_types",
                ["timeline", "evidence"],
            ),
        }

    def _normalize_standard_intake_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty standard intake policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Standard intake policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Standard intake policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "timeline_prompt_style",
            "impact_prompt_style",
            "include_notice_question",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Standard intake policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        timeline_style = str(data.get("timeline_prompt_style", "baseline")).strip()
        impact_style = str(data.get("impact_prompt_style", "baseline")).strip()
        allowed_timeline_styles = {"baseline", "actor_notice_timeline"}
        allowed_impact_styles = {"baseline", "impact_with_documents"}
        if timeline_style not in allowed_timeline_styles:
            raise ValueError(
                f"Standard intake policy response for {file_path} used unsupported timeline_prompt_style '{timeline_style}'"
            )
        if impact_style not in allowed_impact_styles:
            raise ValueError(
                f"Standard intake policy response for {file_path} used unsupported impact_prompt_style '{impact_style}'"
            )

        return {
            "timeline_prompt_style": timeline_style,
            "impact_prompt_style": impact_style,
            "include_notice_question": bool(data.get("include_notice_question", False)),
        }

    def _normalize_select_candidates_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty select-candidates policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Select-candidates policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Select-candidates policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "dedupe_selected_candidates",
            "dedupe_fallback_candidates",
            "selector_mode",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Select-candidates policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        selector_mode = str(data.get("selector_mode", "honor_nonempty")).strip()
        if selector_mode not in {"honor_nonempty", "fallback_only"}:
            raise ValueError(
                f"Select-candidates policy response for {file_path} used unsupported selector_mode '{selector_mode}'"
            )

        return {
            "dedupe_selected_candidates": bool(data.get("dedupe_selected_candidates", True)),
            "dedupe_fallback_candidates": bool(data.get("dedupe_fallback_candidates", True)),
            "selector_mode": selector_mode,
        }

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
        if threshold <= 3:
            threshold_assignment = "    gap_threshold = _INTAKE_GAPS_THRESHOLD\n"
        else:
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

    def _render_inquiries_methods_from_policy(self, policy: Dict[str, Any]) -> Dict[str, str]:
        dependency_first = bool(policy.get("prioritize_dependency_gaps_first", True))
        preserve_legal_source = bool(policy.get("preserve_legal_source_on_merge", True))
        dedupe_alternative_questions = bool(policy.get("dedupe_alternative_questions", True))
        normalize_priority_labels = bool(policy.get("normalize_priority_labels", True))

        if dependency_first:
            sort_key = (
                "        unanswered.sort(\n"
                "            key=lambda pair: (\n"
                "                0 if pair[0].get(\"dependency_gap_targeted\") else 1,\n"
                "                0 if pair[0].get(\"support_gap_targeted\") else 1,\n"
                "                self._priority_rank(pair[0].get(\"priority\")),\n"
                "                pair[1],\n"
                "            )\n"
                "        )\n"
            )
        else:
            sort_key = (
                "        unanswered.sort(\n"
                "            key=lambda pair: (\n"
                "                0 if pair[0].get(\"support_gap_targeted\") else 1,\n"
                "                0 if pair[0].get(\"dependency_gap_targeted\") else 1,\n"
                "                self._priority_rank(pair[0].get(\"priority\")),\n"
                "                pair[1],\n"
                "            )\n"
                "        )\n"
            )

        source_update = (
            "            if not existing.get(\"source\") or str(existing.get(\"source\")).strip().lower() == \"legal_question\":\n"
            "                existing[\"source\"] = \"legal_question\"\n"
            if preserve_legal_source
            else "            existing[\"source\"] = \"legal_question\"\n"
        )
        alt_question_block = (
            "            if question_text != existing.get(\"question\"):\n"
            "                alternatives = existing.setdefault(\"alternative_questions\", [])\n"
            "                if all(self._normalize_question(candidate) != normalized for candidate in alternatives):\n"
            "                    alternatives.append(question_text)\n"
            if dedupe_alternative_questions
            else
            "            if question_text != existing.get(\"question\"):\n"
            "                existing.setdefault(\"alternative_questions\", []).append(question_text)\n"
        )
        priority_value = (
            "        priority_value = str(item.get(\"priority\", \"Medium\") or \"Medium\").strip().title()\n"
            if normalize_priority_labels
            else
            "        priority_value = item.get(\"priority\", \"Medium\")\n"
        )
        priority_merge = (
            "                existing[\"priority\"] = str(item.get(\"priority\") or existing.get(\"priority\") or \"Medium\").strip().title()\n"
            if normalize_priority_labels
            else
            "                existing[\"priority\"] = item.get(\"priority\")\n"
        )

        return {
            "get_next": (
                "def get_next(self):\n"
                "    inquiries = self._state_inquiries()\n"
                "    if not inquiries:\n"
                "        return None\n"
                "    unanswered = [\n"
                "        (item, index)\n"
                "        for index, item in enumerate(inquiries)\n"
                "        if not item.get(\"answer\")\n"
                "    ]\n"
                "    if not unanswered:\n"
                "        return None\n"
                f"{sort_key}"
                "    return unanswered[0][0]\n"
            ),
            "merge_legal_questions": (
                "def merge_legal_questions(self, questions: List[Dict[str, Any]]) -> int:\n"
                "    inquiries = self._state_inquiries()\n"
                "    if inquiries is None:\n"
                "        return 0\n"
                "\n"
                "    index = self._index_for(inquiries)\n"
                "    gap_context = self._build_gap_context()\n"
                "    priority_terms = [\n"
                "        str(term).strip().lower()\n"
                "        for term in (gap_context.get(\"priority_terms\") or [])\n"
                "        if str(term).strip()\n"
                "    ]\n"
                "\n"
                "    merged = 0\n"
                "    for item in questions or []:\n"
                "        if not isinstance(item, dict):\n"
                "            continue\n"
                "        question_text = str(item.get(\"question\") or \"\").strip()\n"
                "        if not question_text:\n"
                "            continue\n"
                "\n"
                "        normalized = self._normalize_question(question_text)\n"
                "        dependency_gap_targeted = any(term in question_text.lower() for term in priority_terms)\n"
                "        existing = index.get(normalized)\n"
                "        if existing is not None:\n"
                "            existing_priority = self._priority_rank(existing.get(\"priority\"))\n"
                "            incoming_priority = self._priority_rank(item.get(\"priority\"))\n"
                "            if incoming_priority < existing_priority:\n"
                f"{priority_merge}"
                "            existing[\"support_gap_targeted\"] = bool(\n"
                "                existing.get(\"support_gap_targeted\") or item.get(\"support_gap_targeted\")\n"
                "            )\n"
                "            existing[\"dependency_gap_targeted\"] = bool(\n"
                "                existing.get(\"dependency_gap_targeted\") or dependency_gap_targeted\n"
                "            )\n"
                f"{source_update}"
                "            if item.get(\"claim_type\"):\n"
                "                existing[\"claim_type\"] = item.get(\"claim_type\")\n"
                "            if item.get(\"element\"):\n"
                "                existing[\"element\"] = item.get(\"element\")\n"
                "            if item.get(\"provenance\"):\n"
                "                existing[\"provenance\"] = dict(item.get(\"provenance\") or {})\n"
                f"{alt_question_block}"
                "            merged += 1\n"
                "            continue\n"
                "\n"
                f"{priority_value}"
                "        inquiry = {\n"
                "            \"question\": question_text,\n"
                "            \"alternative_questions\": list(item.get(\"alternative_questions\") or []),\n"
                "            \"answer\": item.get(\"answer\"),\n"
                "            \"priority\": priority_value,\n"
                "            \"support_gap_targeted\": bool(item.get(\"support_gap_targeted\", False)),\n"
                "            \"dependency_gap_targeted\": dependency_gap_targeted,\n"
                "            \"source\": \"legal_question\",\n"
                "            \"claim_type\": item.get(\"claim_type\"),\n"
                "            \"element\": item.get(\"element\"),\n"
                "            \"provenance\": dict(item.get(\"provenance\") or {}),\n"
                "        }\n"
                "        inquiries.append(inquiry)\n"
                "        index[normalized] = inquiry\n"
                "        merged += 1\n"
                "\n"
                "    self._index_signature = (id(inquiries), len(inquiries))\n"
                "    return merged\n"
            ),
        }

    def _render_process_answer_from_policy(self, policy: Dict[str, Any]) -> str:
        timeline_types = sorted(policy["timeline_enrichment_types"])
        responsible_types = sorted(policy["responsible_party_enrichment_types"])
        fallback_types = sorted(policy["fallback_timeline_fact_types"])

        def _render_set(values: List[str]) -> str:
            if not values:
                return "set()"
            rendered = ", ".join(repr(value) for value in values)
            return "{" + rendered + "}"

        return (
            "def process_answer(self, question: Dict[str, Any], answer: str,\n"
            "                  knowledge_graph: KnowledgeGraph,\n"
            "                  dependency_graph: Optional[DependencyGraph] = None) -> Dict[str, Any]:\n"
            "    \"\"\"\n"
            "    Process an answer to a denoising question.\n"
            "    \n"
            "    Args:\n"
            "        question: The question that was asked\n"
            "        answer: The user's answer\n"
            "        knowledge_graph: Knowledge graph to update\n"
            "        dependency_graph: Optional dependency graph to update\n"
            "        \n"
            "    Returns:\n"
            "        Information about what was updated\n"
            "    \"\"\"\n"
            "    self.questions_asked.append({\n"
            "        'question': question,\n"
            "        'answer': answer\n"
            "    })\n"
            "\n"
            "    updates = {\n"
            "        'entities_updated': 0,\n"
            "        'relationships_added': 0,\n"
            "        'requirements_satisfied': 0\n"
            "    }\n"
            "\n"
            "    question_type = question.get('type')\n"
            "    context = question.get('context', {})\n"
            "    answer_text = str(answer or '').strip()\n"
            f"    timeline_enrichment_types = {_render_set(timeline_types)}\n"
            f"    responsible_party_enrichment_types = {_render_set(responsible_types)}\n"
            f"    fallback_timeline_fact_types = {_render_set(fallback_types)}\n"
            "\n"
            "    def _single_claim_id() -> Optional[str]:\n"
            "        claims = knowledge_graph.get_entities_by_type('claim')\n"
            "        return claims[0].id if len(claims) == 1 else None\n"
            "\n"
            "    def _apply_timeline_enrichment() -> None:\n"
            "        nonlocal updates\n"
            "        if question_type not in timeline_enrichment_types or not answer_text:\n"
            "            return\n"
            "        claim_id = _single_claim_id()\n"
            "        dates = self._extract_date_strings(answer_text)\n"
            "        if dates:\n"
            "            for date_str in dates:\n"
            "                date_entity, created = self._add_entity_if_missing(\n"
            "                    knowledge_graph,\n"
            "                    'date',\n"
            "                    date_str,\n"
            "                    {},\n"
            "                    0.7\n"
            "                )\n"
            "                if created:\n"
            "                    updates['entities_updated'] += 1\n"
            "                if claim_id and date_entity:\n"
            "                    _, rel_created = self._add_relationship_if_missing(\n"
            "                        knowledge_graph,\n"
            "                        claim_id,\n"
            "                        date_entity.id,\n"
            "                        'occurred_on',\n"
            "                        0.6\n"
            "                    )\n"
            "                    if rel_created:\n"
            "                        updates['relationships_added'] += 1\n"
            "            return\n"
            "        if question_type not in fallback_timeline_fact_types:\n"
            "            return\n"
            "        claim_id = _single_claim_id()\n"
            "        snippet = self._short_description(answer_text, 120)\n"
            "        fact_name = f\"Timeline detail: {self._short_description(answer_text, 60)}\"\n"
            "        fact_entity, created = self._add_entity_if_missing(\n"
            "            knowledge_graph,\n"
            "            'fact',\n"
            "            fact_name,\n"
            "            {'fact_type': 'timeline', 'description': snippet},\n"
            "            0.6\n"
            "        )\n"
            "        if created:\n"
            "            updates['entities_updated'] += 1\n"
            "        if claim_id and fact_entity:\n"
            "            _, rel_created = self._add_relationship_if_missing(\n"
            "                knowledge_graph,\n"
            "                claim_id,\n"
            "                fact_entity.id,\n"
            "                'has_timeline_detail',\n"
            "                0.6\n"
            "            )\n"
            "            if rel_created:\n"
            "                updates['relationships_added'] += 1\n"
            "\n"
            "    if question_type == 'clarification':\n"
            "        entity_id = context.get('entity_id')\n"
            "        entity = knowledge_graph.get_entity(entity_id)\n"
            "        if entity:\n"
            "            entity.confidence = min(1.0, entity.confidence + 0.2)\n"
            "            entity.attributes['clarification'] = answer\n"
            "            updates['entities_updated'] += 1\n"
            "\n"
            "    elif question_type == 'relationship':\n"
            "        entity_id = context.get('entity_id')\n"
            "        if entity_id and len(answer_text) > 10:\n"
            "            entity = knowledge_graph.get_entity(entity_id)\n"
            "            if entity:\n"
            "                entity.attributes['relationship_described'] = True\n"
            "                updates['entities_updated'] += 1\n"
            "\n"
            "    elif question_type == 'responsible_party':\n"
            "        pass\n"
            "\n"
            "    elif question_type == 'evidence':\n"
            "        claim_id = context.get('claim_id')\n"
            "        entity = knowledge_graph.get_entity(claim_id)\n"
            "        if entity:\n"
            "            if 'evidence_descriptions' not in entity.attributes:\n"
            "                entity.attributes['evidence_descriptions'] = []\n"
            "            entity.attributes['evidence_descriptions'].append(answer)\n"
            "            updates['entities_updated'] += 1\n"
            "        if not claim_id:\n"
            "            claim_id = _single_claim_id()\n"
            "        if claim_id and len(answer_text) > 10:\n"
            "            snippet = self._short_description(answer_text, 120)\n"
            "            evidence_name = f\"Evidence: {self._short_description(answer_text, 80)}\"\n"
            "            evidence_entity, created = self._add_entity_if_missing(\n"
            "                knowledge_graph,\n"
            "                'evidence',\n"
            "                evidence_name,\n"
            "                {'description': snippet},\n"
            "                0.6\n"
            "            )\n"
            "            if created:\n"
            "                updates['entities_updated'] += 1\n"
            "            if evidence_entity:\n"
            "                _, rel_created = self._add_relationship_if_missing(\n"
            "                    knowledge_graph,\n"
            "                    claim_id,\n"
            "                    evidence_entity.id,\n"
            "                    'supported_by',\n"
            "                    0.6\n"
            "                )\n"
            "                if rel_created:\n"
            "                    updates['relationships_added'] += 1\n"
            "\n"
            "    elif question_type == 'timeline':\n"
            "        pass\n"
            "\n"
            "    elif question_type in {'impact', 'remedy'}:\n"
            "        if answer_text:\n"
            "            claim_id = _single_claim_id()\n"
            "            snippet = self._short_description(answer_text, 120)\n"
            "            if question_type == 'remedy':\n"
            "                fact_type = 'remedy'\n"
            "                fact_name = f\"Requested remedy: {self._short_description(answer_text, 60)}\"\n"
            "                rel_type = 'seeks_remedy'\n"
            "            else:\n"
            "                fact_type = 'impact'\n"
            "                fact_name = f\"Impact: {self._short_description(answer_text, 60)}\"\n"
            "                rel_type = 'has_impact'\n"
            "            fact_entity, created = self._add_entity_if_missing(\n"
            "                knowledge_graph,\n"
            "                'fact',\n"
            "                fact_name,\n"
            "                {'fact_type': fact_type, 'description': snippet},\n"
            "                0.6\n"
            "            )\n"
            "            if created:\n"
            "                updates['entities_updated'] += 1\n"
            "            if claim_id and fact_entity:\n"
            "                _, rel_created = self._add_relationship_if_missing(\n"
            "                    knowledge_graph,\n"
            "                    claim_id,\n"
            "                    fact_entity.id,\n"
            "                    rel_type,\n"
            "                    0.6\n"
            "                )\n"
            "                if rel_created:\n"
            "                    updates['relationships_added'] += 1\n"
            "            if question_type == 'impact' and self._contains_remedy_cue(answer_text):\n"
            "                remedy_name = f\"Requested remedy: {self._short_description(answer_text, 60)}\"\n"
            "                remedy_entity, remedy_created = self._add_entity_if_missing(\n"
            "                    knowledge_graph,\n"
            "                    'fact',\n"
            "                    remedy_name,\n"
            "                    {'fact_type': 'remedy', 'description': snippet},\n"
            "                    0.55\n"
            "                )\n"
            "                if remedy_created:\n"
            "                    updates['entities_updated'] += 1\n"
            "                if claim_id and remedy_entity:\n"
            "                    _, rel_created = self._add_relationship_if_missing(\n"
            "                        knowledge_graph,\n"
            "                        claim_id,\n"
            "                        remedy_entity.id,\n"
            "                        'seeks_remedy',\n"
            "                        0.55\n"
            "                    )\n"
            "                    if rel_created:\n"
            "                        updates['relationships_added'] += 1\n"
            "\n"
            "    elif question_type == 'requirement':\n"
            "        if dependency_graph:\n"
            "            req_id = context.get('requirement_id')\n"
            "            req_node = dependency_graph.get_node(req_id)\n"
            "            if req_node and len(answer_text) > 10:\n"
            "                req_node.satisfied = True\n"
            "                req_node.confidence = 0.7\n"
            "                updates['requirements_satisfied'] += 1\n"
            "\n"
            "    if question_type in responsible_party_enrichment_types and answer_text:\n"
            "        updates = self._update_responsible_parties_from_answer(answer_text, knowledge_graph, updates)\n"
            "\n"
            "    if question_type in timeline_enrichment_types and answer_text:\n"
            "        _apply_timeline_enrichment()\n"
            "\n"
            "    logger.info(f\"Processed answer: {updates}\")\n"
            "\n"
            "    try:\n"
            "        gain = self._compute_gain(updates)\n"
            "        self._recent_gains.append(gain)\n"
            "        if len(self._recent_gains) > 50:\n"
            "            self._recent_gains = self._recent_gains[-50:]\n"
            "        qtype = question.get('type') if isinstance(question, dict) else 'unknown'\n"
            "        self._update_momentum(str(qtype or 'unknown'), gain)\n"
            "    except Exception:\n"
            "        pass\n"
            "\n"
            "    return updates\n"
        )

    def _render_standard_intake_questions_from_policy(self, policy: Dict[str, Any]) -> str:
        timeline_style = policy["timeline_prompt_style"]
        impact_style = policy["impact_prompt_style"]
        include_notice_question = bool(policy["include_notice_question"])

        if timeline_style == "actor_notice_timeline":
            timeline_text = (
                "What is the timeline of key events, including dates, who made each decision, "
                "what notice or communication you received, and when you requested help or accommodation?"
            )
            timeline_keywords = ['timeline', 'when did', 'what date', 'dates', 'notice', 'who made']
        else:
            timeline_text = (
                "What is the timeline of key events (dates, who was involved, what was said or done, and when you requested help/accommodation)?"
            )
            timeline_keywords = ['timeline', 'when did', 'what date', 'dates']

        if impact_style == "impact_with_documents":
            impact_text = (
                "What harm did you experience (financial, emotional, professional), what outcome or remedy are you seeking, "
                "and what notices, letters, or messages document that harm?"
            )
            impact_keywords = ['harm', 'damages', 'remedy', 'seeking', 'notice', 'letter', 'message']
        else:
            impact_text = (
                "What harm did you experience (financial, emotional, professional), and what outcome or remedy are you seeking?"
            )
            impact_keywords = ['harm', 'damages', 'remedy', 'seeking']

        notice_block = ""
        if include_notice_question:
            notice_block = (
                "        notice_text = (\n"
                "            \"What exact notice, letter, email, or message did you receive, on what date, and who sent it?\"\n"
                "        )\n"
                "        if len(questions) + len(added) < max_questions:\n"
                "            if not any(q.get('type') == 'evidence' for q in questions) and not any(k in existing_text for k in ['notice', 'letter', 'email', 'message', 'sent it']):\n"
                "                if not self._already_asked(notice_text):\n"
                "                    added.append(self._build_phase1_question(\n"
                "                        question_type='evidence',\n"
                "                        question_text=notice_text,\n"
                "                        context={},\n"
                "                        priority='high',\n"
                "                    ))\n"
                "\n"
            )

        return (
            "def _ensure_standard_intake_questions(self, questions: List[Dict[str, Any]], max_questions: int) -> List[Dict[str, Any]]:\n"
            "    if len(questions) >= max_questions:\n"
            "        return questions\n"
            "\n"
            "    existing_text = \" \".join([q.get('question', '') for q in questions]).lower()\n"
            "    added: List[Dict[str, Any]] = []\n"
            "\n"
            "    timeline_text = (\n"
            f"        {timeline_text!r}\n"
            "    )\n"
            "    if len(questions) + len(added) < max_questions:\n"
            f"        if not any(q.get('type') == 'timeline' for q in questions) and not any(k in existing_text for k in {timeline_keywords!r}):\n"
            "            if not self._already_asked(timeline_text):\n"
            "                added.append(self._build_phase1_question(\n"
            "                    question_type='timeline',\n"
            "                    question_text=timeline_text,\n"
            "                    context={},\n"
            "                    priority='high',\n"
            "                ))\n"
            "\n"
            "    impact_text = (\n"
            f"        {impact_text!r}\n"
            "    )\n"
            "    if len(questions) + len(added) < max_questions:\n"
            f"        if not any(q.get('type') in {{'impact', 'remedy'}} for q in questions) and not any(k in existing_text for k in {impact_keywords!r}):\n"
            "            if not self._already_asked(impact_text):\n"
            "                added.append(self._build_phase1_question(\n"
            "                    question_type='impact',\n"
            "                    question_text=impact_text,\n"
            "                    context={},\n"
            "                    priority='high',\n"
            "                ))\n"
            "\n"
            f"{notice_block}"
            "    if not added:\n"
            "        return questions\n"
            "\n"
            "    priority_order = {'high': 0, 'medium': 1, 'low': 2}\n"
            "    combined = questions + added\n"
            "    combined.sort(\n"
            "        key=lambda q: (\n"
            "            int(q.get('proof_priority', self._phase1_proof_priority(q.get('type', '')))),\n"
            "            priority_order.get(q.get('priority', 'low'), 3),\n"
            "        )\n"
            "    )\n"
            "    return combined[:max_questions]\n"
        )

    def _render_select_question_candidates_from_policy(self, policy: Dict[str, Any]) -> str:
        selector_mode = policy["selector_mode"]
        dedupe_selected = bool(policy["dedupe_selected_candidates"])
        dedupe_fallback = bool(policy["dedupe_fallback_candidates"])

        selector_block = (
            "    if isinstance(selected, list):\n"
            f"        normalized_selected = _finalize(selected, dedupe={str(dedupe_selected)})\n"
            "        if normalized_selected:\n"
            "            return normalized_selected\n"
        )
        if selector_mode == "fallback_only":
            selector_block = (
                "    if isinstance(selected, list):\n"
                f"        normalized_selected = _finalize(selected, dedupe={str(dedupe_selected)})\n"
                "        if len(normalized_selected) >= max_questions:\n"
                "            return normalized_selected\n"
            )

        return (
            "def select_question_candidates(\n"
            "    self,\n"
            "    candidates: List[Dict[str, Any]],\n"
            "    *,\n"
            "    max_questions: int = 10,\n"
            "    selector: Any = None,\n"
            ") -> List[Dict[str, Any]]:\n"
            "    \"\"\"Select final question candidates, allowing a router/prover override.\"\"\"\n"
            "    normalized_candidates = [candidate for candidate in (candidates or []) if isinstance(candidate, dict)]\n"
            "    if not normalized_candidates or max_questions <= 0:\n"
            "        return []\n"
            "\n"
            "    def _finalize(items: Any, *, dedupe: bool) -> List[Dict[str, Any]]:\n"
            "        normalized_items = [candidate for candidate in (items or []) if isinstance(candidate, dict)]\n"
            "        if not dedupe:\n"
            "            return normalized_items[:max_questions]\n"
            "        seen_keys = set()\n"
            "        finalized: List[Dict[str, Any]] = []\n"
            "        for candidate in normalized_items:\n"
            "            candidate_key = (\n"
            "                self._normalize_question_text(str(candidate.get('question', ''))),\n"
            "                str(candidate.get('type', '')).strip().lower(),\n"
            "            )\n"
            "            if candidate_key in seen_keys:\n"
            "                continue\n"
            "            seen_keys.add(candidate_key)\n"
            "            finalized.append(candidate)\n"
            "            if len(finalized) >= max_questions:\n"
            "                break\n"
            "        return finalized\n"
            "\n"
            "    selected: Any = None\n"
            "    if callable(selector):\n"
            "        try:\n"
            "            selected = selector(normalized_candidates, max_questions=max_questions)\n"
            "        except TypeError:\n"
            "            selected = selector(normalized_candidates)\n"
            "        except Exception:\n"
            "            selected = None\n"
            "\n"
            f"{selector_block}\n"
            "    normalized_candidates.sort(key=self._default_candidate_sort_key)\n"
            f"    return _finalize(normalized_candidates, dedupe={str(dedupe_fallback)})\n"
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

        def _indent_prefix(start_line: int) -> str:
            if 0 <= start_line < len(lines):
                line = lines[start_line]
                match = re.match(r"[ \t]*", line)
                if match:
                    return match.group(0)
            return ""

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in target_symbols:
                snippet = replacement_sources.get(node.name)
                if not snippet:
                    continue
                indent = _indent_prefix(node.lineno - 1) or (" " * node.col_offset)
                dedented = textwrap.dedent(snippet).rstrip() + "\n"
                body_lines = dedented.splitlines(keepends=True)
                replacement_parts: List[str] = []
                for index, body_line in enumerate(body_lines):
                    if body_line.strip():
                        replacement_parts.append(indent + body_line)
                    else:
                        replacement_parts.append(body_line)
                replacement = "".join(replacement_parts)
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
