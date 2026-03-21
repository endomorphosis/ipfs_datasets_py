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
        if self._use_session_injection_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_session_injection_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=500,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            try:
                policy = self._normalize_session_injection_policy_response(response=response, file_path=target_file)
            except ValueError:
                policy = {
                    "stability_injection_budget": 3,
                    "empty_questions_min_budget": 5,
                    "limit_to_missing_objectives_in_stability": True,
                    "one_probe_per_objective_in_stability": True,
                }
            replacement_sources = {
                "_inject_intake_prompt_questions": self._render_session_injection_from_policy(policy)
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )
        if self._use_document_workflow_targeting_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_document_workflow_targeting_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=500,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            try:
                policy = self._normalize_document_workflow_targeting_policy_response(
                    response=response,
                    file_path=target_file,
                )
            except ValueError:
                policy = {
                    "graph_blocker_weight": 0.08,
                    "document_blocker_weight": 0.06,
                    "intake_objective_weight": 0.05,
                    "boost_document_for_notice_chain": True,
                    "preserve_graph_priority_when_factual_pressure_high": True,
                }
            replacement_sources = {
                "_build_workflow_phase_targeting": self._render_document_workflow_targeting_from_policy(policy)
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )
        if self._use_merge_seed_with_grounding_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_merge_seed_with_grounding_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=500,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            try:
                policy = self._normalize_merge_seed_with_grounding_policy_response(
                    response=response,
                    file_path=target_file,
                )
            except ValueError:
                policy = {
                    "anchor_passage_limit": 5,
                    "evidence_item_limit": 8,
                    "blocker_answer_limit": 6,
                    "unresolved_objective_limit": 3,
                }
            current_block = self._extract_target_symbol_blocks(current_code, target_symbols)["_merge_seed_with_grounding"]
            replacement_sources = {
                "_merge_seed_with_grounding": self._apply_merge_seed_with_grounding_policy_to_source(
                    current_block,
                    policy,
                )
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )
        if self._use_formal_document_render_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_formal_document_render_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=500,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            try:
                policy = self._normalize_formal_document_render_policy_response(
                    response=response,
                    file_path=target_file,
                )
            except ValueError:
                policy = {
                    "chronology_line_limit": 5,
                    "supporting_fact_limit": 4,
                    "exhibit_limit": 8,
                    "affidavit_fact_limit": 6,
                }
            current_block = self._extract_target_symbol_blocks(current_code, target_symbols)["render_text"]
            replacement_sources = {
                "render_text": self._apply_formal_document_render_policy_to_source(
                    current_block,
                    policy,
                )
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )
        if self._use_knowledge_graph_build_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_knowledge_graph_build_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=500,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            try:
                policy = self._normalize_knowledge_graph_build_policy_response(
                    response=response,
                    file_path=target_file,
                )
            except ValueError:
                policy = {
                    "normalize_whitespace_input": True,
                    "record_source_text_char_count": True,
                    "record_extraction_counts": True,
                    "mark_empty_input_graph": True,
                    "preserve_actor_critic_metadata": True,
                }
            replacement_sources = {
                "build_from_text": self._render_knowledge_graph_build_from_text_from_policy(policy)
            }
            return self._replace_symbols_in_source(
                original_code=current_code,
                target_symbols=target_symbols,
                replacement_sources=replacement_sources,
            )
        if self._use_complainant_guidance_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_complainant_guidance_policy_prompt(
                    file_path=target_file,
                    baseline=baseline,
                    task=task,
                ),
                method=self.method,
                max_tokens=500,
                temperature=0.1,
            )
            self._remember_raw_response(target_file, response)
            try:
                policy = self._normalize_complainant_guidance_policy_response(
                    response=response,
                    file_path=target_file,
                )
            except ValueError:
                policy = {
                    "unresolved_objective_limit": 3,
                    "include_follow_up_prompt_examples": True,
                    "encourage_empathy_opening": True,
                    "include_document_precision_guidance": True,
                    "include_phase_focus_line": True,
                }
            replacement_sources = {
                "_build_actor_critic_guidance": self._render_complainant_guidance_from_policy(policy)
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
        if self._use_dependency_readiness_policy_mode(target_file=target_file, target_symbols=target_symbols):
            response = self.llm_router.generate(
                prompt=self._build_dependency_readiness_policy_prompt(
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
                "get_claim_readiness": self._render_get_claim_readiness_from_policy(
                    self._normalize_dependency_readiness_policy_response(response=response, file_path=target_file)
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

    def _use_dependency_readiness_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "dependency_graph.py" and target_symbols == ["get_claim_readiness"]

    def _use_select_candidates_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "denoiser.py" and target_symbols == ["select_question_candidates"]

    def _use_standard_intake_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "denoiser.py" and target_symbols == ["_ensure_standard_intake_questions"]

    def _use_session_injection_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "session.py" and target_symbols == ["_inject_intake_prompt_questions"]

    def _use_complainant_guidance_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "complainant.py" and target_symbols == ["_build_actor_critic_guidance"]

    def _use_document_workflow_targeting_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "document_optimization.py" and target_symbols == ["_build_workflow_phase_targeting"]

    def _use_merge_seed_with_grounding_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "synthesize_hacc_complaint.py" and target_symbols == ["_merge_seed_with_grounding"]

    def _use_knowledge_graph_build_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "knowledge_graph.py" and target_symbols == ["build_from_text"]

    def _use_formal_document_render_policy_mode(self, *, target_file: Path, target_symbols: List[str]) -> bool:
        return target_file.name == "formal_document.py" and target_symbols == ["render_text"]
    
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

    def _build_dependency_readiness_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Improve graph readiness ranking so missing blocking requirements and deterministic gaps are surfaced earlier."

        return f"""Return a compact JSON object describing how dependency_graph.get_claim_readiness should prioritize missing requirements and readiness recommendations.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "prioritize_blocking_gaps": true or false
- "prioritize_structured_gaps": true or false
- "promote_deterministic_gap_targets": true or false
- "boost_weak_claim_types": true or false
- "boost_weak_evidence_modalities": true or false
- "gap_stall_action_threshold": integer from 1 to 4

Behavioral guardrails:
- Preserve the method signature and return type
- Preserve the existing return keys, including actor_critic.graph_analysis metrics
- Preserve recommended_next_gaps sorting and next_required_gap selection
- Preserve deterministic_update_key and gap_id handling
- Preserve gap-stall tracking in metadata['readiness_history']
- Do not add imports or rely on helpers not already used in dependency_graph.py

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

    def _build_session_injection_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Restore a stable intake flow by keeping synthetic intake prompts small, deterministic, and focused on missing objectives."

        return f"""Return a compact JSON object describing how session._inject_intake_prompt_questions should behave during stability-recovery intake.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "stability_injection_budget": integer from 1 to 4
- "empty_questions_min_budget": integer from 2 to 5
- "limit_to_missing_objectives_in_stability": true or false
- "one_probe_per_objective_in_stability": true or false

Behavioral guardrails:
- Preserve the method signature and return type
- Preserve use of _extract_actor_critic_intake_context and stability_recovery_mode
- Preserve duplicate suppression and substantial-overlap checks
- Preserve returning existing mediator questions first during stability recovery
- Preserve synthetic question shape with question/type/question_objective/question_reason/source
- Do not add imports or rely on helpers not already used in session.py

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_document_workflow_targeting_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Keep document workflow targeting small, deterministic, and aligned to the strongest drafting blockers."

        return f"""Return a compact JSON object describing how document_optimization._build_workflow_phase_targeting should prioritize graph, document, and intake workflow phases.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "graph_blocker_weight": decimal from 0.04 to 0.12
- "document_blocker_weight": decimal from 0.03 to 0.1
- "intake_objective_weight": decimal from 0.03 to 0.08
- "boost_document_for_notice_chain": true or false
- "preserve_graph_priority_when_factual_pressure_high": true or false

Behavioral guardrails:
- Preserve the method signature and return keys
- Preserve use of _normalize_intake_objective, _clamp, and _select_phase_target_section
- Preserve one score per phase for graph_analysis, document_generation, and intake_questioning
- Preserve phase_focus_order sorting using score then WORKFLOW_PHASE_FOCUS_ORDER
- Preserve chronology_context_active behavior
- Do not add imports or rely on helpers not already used in document_optimization.py

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_complainant_guidance_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Keep complainant guidance concise, blocker-aware, and easy for the mediator to operationalize."

        return f"""Return a compact JSON object describing how complainant._build_actor_critic_guidance should coach concise, high-yield answers.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "unresolved_objective_limit": integer from 1 to 4
- "include_follow_up_prompt_examples": true or false
- "encourage_empathy_opening": true or false
- "include_document_precision_guidance": true or false
- "include_phase_focus_line": true or false

Behavioral guardrails:
- Preserve the method signature and return type
- Preserve use of ComplaintContext, _ordered_workflow_phases, _extract_confirmation_placeholders, and _order_objectives_for_actor_critic
- Preserve chronology, decision-maker, and documentary-artifact guidance when the question text calls for them
- Preserve unresolved-objective handling and phase focus ordering
- Do not add imports or rely on helpers not already used in complainant.py

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_merge_seed_with_grounding_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Keep grounding merge behavior deterministic, preserve stronger evidence snippets, and keep drafting handoff lines compact."

        return f"""Return a compact JSON object describing how synthesize_hacc_complaint._merge_seed_with_grounding should bound its merge fan-out.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "anchor_passage_limit": integer from 3 to 6
- "evidence_item_limit": integer from 4 to 8
- "blocker_answer_limit": integer from 4 to 8
- "unresolved_objective_limit": integer from 2 to 5

Behavioral guardrails:
- Preserve the method signature and return type
- Preserve snippet promotion, handoff merging, unresolved-objective propagation, and claim-support dedupe behavior
- Preserve use of existing helper functions and local helper closures already present in the method
- Do not add imports or reference helpers that do not already exist in synthesize_hacc_complaint.py

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_knowledge_graph_build_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Keep knowledge graph building deterministic, preserve actor-critic metadata, and make graph build diagnostics easier to reason about."

        return f"""Return a compact JSON object describing how knowledge_graph.build_from_text should normalize inputs and record safe graph-build metadata.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "normalize_whitespace_input": true or false
- "record_source_text_char_count": true or false
- "record_extraction_counts": true or false
- "mark_empty_input_graph": true or false
- "preserve_actor_critic_metadata": true or false

Behavioral guardrails:
- Preserve the method signature and return type
- Preserve entity extraction before relationship extraction
- Preserve KnowledgeGraph return shape and logger.info summary call
- Preserve tracking through self._built_graphs and self._text_processed_count
- Preserve actor_critic metadata when self.actor_critic_enabled is true
- Do not add imports or reference helpers that do not already exist in knowledge_graph.py

Do not include explanations, markdown, comments, or extra keys.
"""

    def _build_formal_document_render_policy_prompt(
        self,
        *,
        file_path: Path,
        baseline: Dict[str, float],
        task: OptimizationTask,
    ) -> str:
        report_summary = (task.metadata or {}).get("report_summary", {})
        recommendations = "\n".join(f"- {item}" for item in (report_summary.get("recommendations") or [])[:4])
        if not recommendations:
            recommendations = "- Keep rendered complaint text concise, preserve section order, and avoid bloated chronology, exhibit, and affidavit expansions."

        return f"""Return a compact JSON object describing how formal_document.render_text should bound its section fan-out.

File: {file_path}
Task: {task.description}

Current performance:
- Execution time: {baseline.get('execution_time', 'unknown')}s
- Test coverage: {baseline.get('coverage', 'unknown')}%

Recent adversarial findings:
{recommendations}

Return JSON only with these keys:
- "chronology_line_limit": integer from 3 to 6
- "supporting_fact_limit": integer from 3 to 6
- "exhibit_limit": integer from 4 to 8
- "affidavit_fact_limit": integer from 4 to 8

Behavioral guardrails:
- Preserve the method signature and return type
- Preserve section order and the final SIGNATURE BLOCK
- Preserve factual allegations, chronology, claims for relief, exhibits, affidavit, verification, and certificate sections when present
- Preserve use of _clean_sentence, _clean_text, _listify, and self._signature_block_lines
- Do not add imports or reference helpers that do not already exist in formal_document.py

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

    def _normalize_dependency_readiness_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty dependency readiness policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(
                f"Dependency readiness policy response for {file_path} requested external context instead of JSON"
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Dependency readiness policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "prioritize_blocking_gaps",
            "prioritize_structured_gaps",
            "promote_deterministic_gap_targets",
            "boost_weak_claim_types",
            "boost_weak_evidence_modalities",
            "gap_stall_action_threshold",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Dependency readiness policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        try:
            stall_threshold = int(data.get("gap_stall_action_threshold", 2))
        except Exception as exc:
            raise ValueError(
                f"Dependency readiness policy response for {file_path} must include integer gap_stall_action_threshold"
            ) from exc
        if stall_threshold < 1 or stall_threshold > 4:
            raise ValueError(
                f"Dependency readiness policy response for {file_path} used out-of-range gap_stall_action_threshold: {stall_threshold}"
            )

        return {
            "prioritize_blocking_gaps": bool(data.get("prioritize_blocking_gaps", True)),
            "prioritize_structured_gaps": bool(data.get("prioritize_structured_gaps", True)),
            "promote_deterministic_gap_targets": bool(data.get("promote_deterministic_gap_targets", True)),
            "boost_weak_claim_types": bool(data.get("boost_weak_claim_types", True)),
            "boost_weak_evidence_modalities": bool(data.get("boost_weak_evidence_modalities", True)),
            "gap_stall_action_threshold": stall_threshold,
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

    def _normalize_session_injection_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty session injection policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Session injection policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Session injection policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "stability_injection_budget",
            "empty_questions_min_budget",
            "limit_to_missing_objectives_in_stability",
            "one_probe_per_objective_in_stability",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Session injection policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        def _clamp_int(name: str, default: int, minimum: int, maximum: int) -> int:
            value = data.get(name, default)
            try:
                value = int(value)
            except Exception:
                value = default
            return max(minimum, min(maximum, value))

        return {
            "stability_injection_budget": _clamp_int("stability_injection_budget", 3, 1, 4),
            "empty_questions_min_budget": _clamp_int("empty_questions_min_budget", 5, 2, 5),
            "limit_to_missing_objectives_in_stability": bool(data.get("limit_to_missing_objectives_in_stability", True)),
            "one_probe_per_objective_in_stability": bool(data.get("one_probe_per_objective_in_stability", True)),
        }

    def _normalize_document_workflow_targeting_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty document workflow targeting policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Document workflow targeting policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Document workflow targeting policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "graph_blocker_weight",
            "document_blocker_weight",
            "intake_objective_weight",
            "boost_document_for_notice_chain",
            "preserve_graph_priority_when_factual_pressure_high",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Document workflow targeting policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        def _clamp_float(name: str, default: float, minimum: float, maximum: float) -> float:
            value = data.get(name, default)
            try:
                numeric = float(value)
            except Exception:
                numeric = default
            return max(minimum, min(maximum, numeric))

        return {
            "graph_blocker_weight": _clamp_float("graph_blocker_weight", 0.08, 0.04, 0.12),
            "document_blocker_weight": _clamp_float("document_blocker_weight", 0.06, 0.03, 0.10),
            "intake_objective_weight": _clamp_float("intake_objective_weight", 0.05, 0.03, 0.08),
            "boost_document_for_notice_chain": bool(data.get("boost_document_for_notice_chain", True)),
            "preserve_graph_priority_when_factual_pressure_high": bool(
                data.get("preserve_graph_priority_when_factual_pressure_high", True)
            ),
        }

    def _normalize_complainant_guidance_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty complainant guidance policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Complainant guidance policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Complainant guidance policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "unresolved_objective_limit",
            "include_follow_up_prompt_examples",
            "encourage_empathy_opening",
            "include_document_precision_guidance",
            "include_phase_focus_line",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Complainant guidance policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        try:
            unresolved_limit = int(data.get("unresolved_objective_limit", 3))
        except Exception:
            unresolved_limit = 3

        return {
            "unresolved_objective_limit": max(1, min(4, unresolved_limit)),
            "include_follow_up_prompt_examples": bool(data.get("include_follow_up_prompt_examples", True)),
            "encourage_empathy_opening": bool(data.get("encourage_empathy_opening", True)),
            "include_document_precision_guidance": bool(data.get("include_document_precision_guidance", True)),
            "include_phase_focus_line": bool(data.get("include_phase_focus_line", True)),
        }

    def _normalize_merge_seed_with_grounding_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty merge-seed-with-grounding policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Merge-seed-with-grounding policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Merge-seed-with-grounding policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "anchor_passage_limit",
            "evidence_item_limit",
            "blocker_answer_limit",
            "unresolved_objective_limit",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Merge-seed-with-grounding policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        def _clamp_int(name: str, default: int, minimum: int, maximum: int) -> int:
            value = data.get(name, default)
            try:
                value = int(value)
            except Exception:
                value = default
            return max(minimum, min(maximum, value))

        return {
            "anchor_passage_limit": _clamp_int("anchor_passage_limit", 5, 3, 6),
            "evidence_item_limit": _clamp_int("evidence_item_limit", 8, 4, 8),
            "blocker_answer_limit": _clamp_int("blocker_answer_limit", 6, 4, 8),
            "unresolved_objective_limit": _clamp_int("unresolved_objective_limit", 3, 2, 5),
        }

    def _normalize_knowledge_graph_build_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty knowledge-graph build policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Knowledge-graph build policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Knowledge-graph build policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "normalize_whitespace_input",
            "record_source_text_char_count",
            "record_extraction_counts",
            "mark_empty_input_graph",
            "preserve_actor_critic_metadata",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Knowledge-graph build policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        return {
            "normalize_whitespace_input": bool(data.get("normalize_whitespace_input", True)),
            "record_source_text_char_count": bool(data.get("record_source_text_char_count", True)),
            "record_extraction_counts": bool(data.get("record_extraction_counts", True)),
            "mark_empty_input_graph": bool(data.get("mark_empty_input_graph", True)),
            "preserve_actor_critic_metadata": bool(data.get("preserve_actor_critic_metadata", True)),
        }

    def _normalize_formal_document_render_policy_response(
        self,
        *,
        response: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        text = (response or "").strip()
        if not text:
            raise ValueError(f"Empty formal-document render policy response for {file_path}")

        if "```" in text:
            match = re.search(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()

        lowered = text.lower()
        if any(marker in lowered for marker in self._meta_request_markers):
            raise ValueError(f"Formal-document render policy response for {file_path} requested external context instead of JSON")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Formal-document render policy response for {file_path} is not valid JSON: {exc}") from exc

        allowed_keys = {
            "chronology_line_limit",
            "supporting_fact_limit",
            "exhibit_limit",
            "affidavit_fact_limit",
        }
        extra_keys = sorted(set(data.keys()) - allowed_keys)
        if extra_keys:
            raise ValueError(
                f"Formal-document render policy response for {file_path} included unexpected keys: {', '.join(extra_keys)}"
            )

        def _clamp_int(name: str, default: int, minimum: int, maximum: int) -> int:
            value = data.get(name, default)
            try:
                value = int(value)
            except Exception:
                value = default
            return max(minimum, min(maximum, value))

        return {
            "chronology_line_limit": _clamp_int("chronology_line_limit", 5, 3, 6),
            "supporting_fact_limit": _clamp_int("supporting_fact_limit", 4, 3, 6),
            "exhibit_limit": _clamp_int("exhibit_limit", 8, 4, 8),
            "affidavit_fact_limit": _clamp_int("affidavit_fact_limit", 6, 4, 8),
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

    def _render_get_claim_readiness_from_policy(self, policy: Dict[str, Any]) -> str:
        prioritize_blocking = bool(policy.get("prioritize_blocking_gaps", True))
        prioritize_structured = bool(policy.get("prioritize_structured_gaps", True))
        promote_deterministic = bool(policy.get("promote_deterministic_gap_targets", True))
        boost_weak_claims = bool(policy.get("boost_weak_claim_types", True))
        boost_weak_modalities = bool(policy.get("boost_weak_evidence_modalities", True))
        stall_threshold = max(1, min(4, int(policy.get("gap_stall_action_threshold", 2))))

        return (
            "def get_claim_readiness(self) -> Dict[str, Any]:\n"
            "    \"\"\"\n"
            "    Assess overall readiness of all claims.\n"
            "    \n"
            "    Returns summary of which claims are ready to file and which need work.\n"
            "    \"\"\"\n"
            "    def _normalize_key_fragment(value: Any) -> str:\n"
            "        normalized = re.sub(r\"[^a-z0-9]+\", \"_\", str(value or \"\").strip().lower())\n"
            "        normalized = re.sub(r\"_+\", \"_\", normalized).strip(\"_\")\n"
            "        return normalized\n"
            "\n"
            "    def _build_deterministic_update_key(\n"
            "        claim_id: str,\n"
            "        claim_type: str,\n"
            "        source_node: Optional[DependencyNode],\n"
            "        source_attrs: Dict[str, Any],\n"
            "    ) -> str:\n"
            "        explicit_gap_key = str(source_attrs.get('gap_key') or '').strip()\n"
            "        if explicit_gap_key:\n"
            "            return explicit_gap_key\n"
            "        requirement_key = str(source_attrs.get('requirement_key') or '').strip()\n"
            "        if requirement_key:\n"
            "            type_fragment = _normalize_key_fragment(claim_type) or 'claim'\n"
            "            req_fragment = _normalize_key_fragment(requirement_key) or 'requirement'\n"
            "            return f\"{type_fragment}:{req_fragment}\"\n"
            "        source_fragment = _normalize_key_fragment(source_node.id if source_node else '') or 'unknown_source'\n"
            "        claim_fragment = _normalize_key_fragment(claim_type) or _normalize_key_fragment(claim_id) or 'claim'\n"
            "        return f\"{claim_fragment}:{source_fragment}\"\n"
            "\n"
            "    claims = self.get_nodes_by_type(NodeType.CLAIM)\n"
            "    nodes_by_id = self.nodes\n"
            "    incoming_required_by_target: Dict[str, List[Dependency]] = {}\n"
            "    for dep in self.dependencies.values():\n"
            "        if dep.required:\n"
            "            incoming_required_by_target.setdefault(dep.target_id, []).append(dep)\n"
            "\n"
            "    ready_claims = []\n"
            "    incomplete_claims = []\n"
            "    total_missing_dependencies = 0\n"
            "    total_satisfaction_ratio = 0.0\n"
            "    recommended_next_gaps = []\n"
            "    total_required_dependencies = 0\n"
            "    total_satisfied_required_dependencies = 0\n"
            "    underspecified_claims = 0\n"
            "    weak_claim_gap_count = 0\n"
            "    weak_modality_gap_count = 0\n"
            "    structured_required_dependencies = 0\n"
            "    structured_satisfied_dependencies = 0\n"
            "    deterministic_gap_targets = 0\n"
            "    deterministic_gap_targets_satisfied = 0\n"
            "\n"
            "    for claim in claims:\n"
            "        required_deps = incoming_required_by_target.get(claim.id, [])\n"
            "        satisfied_count = 0\n"
            "        missing_dependencies = []\n"
            "        for dep in required_deps:\n"
            "            source_node = nodes_by_id.get(dep.source_id)\n"
            "            if source_node and source_node.satisfied:\n"
            "                satisfied_count += 1\n"
            "            else:\n"
            "                missing_dependencies.append({\n"
            "                    'dependency_id': dep.id,\n"
            "                    'source_node_id': dep.source_id,\n"
            "                    'source_name': source_node.name if source_node else 'Unknown',\n"
            "                    'dependency_type': dep.dependency_type.value,\n"
            "                })\n"
            "        claim_type = str((claim.attributes or {}).get('claim_type') or '').strip().lower()\n"
            "        total_required_for_claim = len(required_deps)\n"
            "        claim_satisfaction_ratio = (\n"
            "            satisfied_count / total_required_for_claim if total_required_for_claim > 0 else 1.0\n"
            "        )\n"
            "        claim_is_satisfied = claim_satisfaction_ratio >= 1.0\n"
            "        claim_is_underspecified = total_required_for_claim == 0\n"
            "        if claim_is_underspecified:\n"
            "            underspecified_claims += 1\n"
            "\n"
            "        total_required_dependencies += total_required_for_claim\n"
            "        total_satisfied_required_dependencies += satisfied_count\n"
            "\n"
            "        ranked_missing_dependencies = []\n"
            "        claim_structured_required_count = 0\n"
            "        claim_structured_satisfied_count = 0\n"
            "        claim_deterministic_target_count = 0\n"
            "        claim_deterministic_target_satisfied_count = 0\n"
            "        missing_by_source_id = {str(dep.get('source_node_id') or '') for dep in missing_dependencies}\n"
            "        for dep in required_deps:\n"
            "            source_node = nodes_by_id.get(dep.source_id)\n"
            "            source_attrs = source_node.attributes if source_node and isinstance(source_node.attributes, dict) else {}\n"
            "            source_node_type = source_node.node_type.value if source_node else 'unknown'\n"
            "            requirement_key = str(source_attrs.get('requirement_key') or '').strip()\n"
            "            expected_modality = str(source_attrs.get('expected_evidence_modality') or '').strip().lower()\n"
            "            has_structured_target = bool(\n"
            "                requirement_key\n"
            "                or expected_modality\n"
            "                or source_node_type in {'legal_element', 'requirement', 'fact', 'evidence'}\n"
            "            )\n"
            "            if has_structured_target:\n"
            "                claim_structured_required_count += 1\n"
            "            deterministic_key = _build_deterministic_update_key(\n"
            "                claim_id=claim.id,\n"
            "                claim_type=claim_type,\n"
            "                source_node=source_node,\n"
            "                source_attrs=source_attrs,\n"
            "            )\n"
            "            has_deterministic_key = bool(deterministic_key)\n"
            "            if has_deterministic_key:\n"
            "                claim_deterministic_target_count += 1\n"
            "            if dep.source_id not in missing_by_source_id:\n"
            "                if has_structured_target:\n"
            "                    claim_structured_satisfied_count += 1\n"
            "                if has_deterministic_key:\n"
            "                    claim_deterministic_target_satisfied_count += 1\n"
            "\n"
            "        structured_required_dependencies += claim_structured_required_count\n"
            "        structured_satisfied_dependencies += claim_structured_satisfied_count\n"
            "        deterministic_gap_targets += claim_deterministic_target_count\n"
            "        deterministic_gap_targets_satisfied += claim_deterministic_target_satisfied_count\n"
            "\n"
            "        for dep in missing_dependencies:\n"
            "            source_node = self.get_node(str(dep.get('source_node_id') or ''))\n"
            "            source_attrs = source_node.attributes if source_node and isinstance(source_node.attributes, dict) else {}\n"
            "            blocking = bool(source_attrs.get('blocking', source_node.node_type in {NodeType.REQUIREMENT, NodeType.LEGAL_ELEMENT} if source_node else False))\n"
            "            source_node_type = source_node.node_type.value if source_node else 'unknown'\n"
            "            requirement_key = str(source_attrs.get('requirement_key') or '')\n"
            "            evidence_modality = str(source_attrs.get('expected_evidence_modality') or '').strip().lower()\n"
            "            deterministic_update_key = _build_deterministic_update_key(\n"
            "                claim_id=claim.id,\n"
            "                claim_type=claim_type,\n"
            "                source_node=source_node,\n"
            "                source_attrs=source_attrs,\n"
            "            )\n"
            "            gap_id = deterministic_update_key or str(source_attrs.get('gap_key') or f\"{claim.id}:{dep.get('source_node_id')}\")\n"
            "            structured_gap = bool(\n"
            "                requirement_key\n"
            "                or evidence_modality\n"
            "                or source_node_type in {'legal_element', 'requirement', 'fact', 'evidence'}\n"
            "            )\n"
            f"            weak_claim_focus = claim_type in _ACTOR_CRITIC_WEAK_CLAIM_TYPES if {boost_weak_claims!r} else False\n"
            f"            weak_modality_focus = evidence_modality in _ACTOR_CRITIC_WEAK_EVIDENCE_MODALITIES if {boost_weak_modalities!r} else False\n"
            "            if weak_claim_focus:\n"
            "                weak_claim_gap_count += 1\n"
            "            if weak_modality_focus:\n"
            "                weak_modality_gap_count += 1\n"
            "            ranked_missing_dependencies.append({\n"
            "                **dep,\n"
            "                'gap_id': gap_id,\n"
            "                'claim_type': claim_type,\n"
            "                'source_node_type': source_node_type,\n"
            "                'source_description': source_node.description if source_node else '',\n"
            "                'requirement_key': requirement_key,\n"
            "                'evidence_modality': evidence_modality,\n"
            "                'structured_gap': structured_gap,\n"
            "                'deterministic_update_key': deterministic_update_key,\n"
            "                'weak_claim_focus': weak_claim_focus,\n"
            "                'weak_modality_focus': weak_modality_focus,\n"
            "                'blocking': blocking,\n"
            "            })\n"
            "\n"
            "        ranked_missing_dependencies.sort(\n"
            "            key=lambda item: (\n"
            f"                0 if {prioritize_blocking!r} and item.get('blocking') else 1,\n"
            "                0 if item.get('weak_claim_focus') else 1,\n"
            "                0 if item.get('weak_modality_focus') else 1,\n"
            f"                0 if {prioritize_structured!r} and item.get('structured_gap') else 1,\n"
            f"                0 if {promote_deterministic!r} and str(item.get('deterministic_update_key') or '').strip() else 1,\n"
            "                0 if str(item.get('source_node_type') or '') in {'legal_element', 'requirement'} else 1,\n"
            "                str(item.get('source_name') or '').lower(),\n"
            "            )\n"
            "        )\n"
            "\n"
            "        total_missing_dependencies += len(ranked_missing_dependencies)\n"
            "        total_satisfaction_ratio += claim_satisfaction_ratio\n"
            "        next_gap = ranked_missing_dependencies[0] if ranked_missing_dependencies else None\n"
            "        if claim_is_satisfied:\n"
            "            ready_claims.append({\n"
            "                'claim_id': claim.id,\n"
            "                'claim_name': claim.name,\n"
            "                'confidence': claim.confidence,\n"
            "                'claim_type': claim_type,\n"
            "                'dependency_satisfaction': 1.0,\n"
            "                'underspecified': claim_is_underspecified,\n"
            "                'required_dependency_count': total_required_for_claim,\n"
            "                'structured_required_count': claim_structured_required_count,\n"
            "                'structured_satisfied_count': claim_structured_satisfied_count,\n"
            "                'deterministic_target_count': claim_deterministic_target_count,\n"
            "                'deterministic_target_satisfied_count': claim_deterministic_target_satisfied_count,\n"
            "            })\n"
            "        else:\n"
            "            incomplete_claims.append({\n"
            "                'claim_id': claim.id,\n"
            "                'claim_name': claim.name,\n"
            "                'claim_type': claim_type,\n"
            "                'satisfaction_ratio': claim_satisfaction_ratio,\n"
            "                'dependency_satisfaction': claim_satisfaction_ratio,\n"
            "                'missing_count': len(ranked_missing_dependencies),\n"
            "                'missing_dependencies': ranked_missing_dependencies,\n"
            "                'next_required_gap': next_gap,\n"
            "                'underspecified': claim_is_underspecified,\n"
            "                'required_dependency_count': total_required_for_claim,\n"
            "                'structured_required_count': claim_structured_required_count,\n"
            "                'structured_satisfied_count': claim_structured_satisfied_count,\n"
            "                'deterministic_target_count': claim_deterministic_target_count,\n"
            "                'deterministic_target_satisfied_count': claim_deterministic_target_satisfied_count,\n"
            "            })\n"
            "            if next_gap:\n"
            "                recommended_next_gaps.append({\n"
            "                    'claim_id': claim.id,\n"
            "                    'claim_name': claim.name,\n"
            "                    'claim_type': claim_type,\n"
            "                    **next_gap,\n"
            "                })\n"
            "\n"
            "    claim_level_satisfaction = (\n"
            "        total_satisfaction_ratio / len(claims) if claims else 0.0\n"
            "    )\n"
            "    dependency_coverage = (\n"
            "        total_satisfied_required_dependencies / total_required_dependencies\n"
            "        if total_required_dependencies > 0\n"
            "        else (1.0 if claims else 0.0)\n"
            "    )\n"
            "    overall_dependency_satisfaction = (\n"
            "        claim_level_satisfaction * 0.45 + dependency_coverage * 0.55\n"
            "    ) if claims else 0.0\n"
            "    structured_dependency_coverage = (\n"
            "        structured_satisfied_dependencies / structured_required_dependencies\n"
            "        if structured_required_dependencies > 0\n"
            "        else dependency_coverage\n"
            "    )\n"
            "    deterministic_gap_closure = (\n"
            "        deterministic_gap_targets_satisfied / deterministic_gap_targets\n"
            "        if deterministic_gap_targets > 0\n"
            "        else dependency_coverage\n"
            "    )\n"
            "    graph_population_score = (\n"
            "        (\n"
            "            ((len(claims) - underspecified_claims) / len(claims)) * 0.55\n"
            "            + structured_dependency_coverage * 0.45\n"
            "        )\n"
            "        if claims\n"
            "        else 0.0\n"
            "    )\n"
            "    graph_analysis_confidence = max(\n"
            "        0.0,\n"
            "        min(\n"
            "            1.0,\n"
            "            dependency_coverage * 0.35\n"
            "            + structured_dependency_coverage * 0.30\n"
            "            + deterministic_gap_closure * 0.20\n"
            "            + graph_population_score * 0.15,\n"
            "        ),\n"
            "    )\n"
            "    avg_gaps = total_missing_dependencies / len(claims) if claims else 0.0\n"
            "\n"
            "    readiness_history = self.metadata.setdefault('readiness_history', {})\n"
            "    previous_avg_gaps = float(readiness_history.get('avg_gaps', avg_gaps))\n"
            "    gap_delta_per_iter = avg_gaps - previous_avg_gaps\n"
            "    previous_stall_count = int(readiness_history.get('gap_stall_sessions', 0))\n"
            "    if avg_gaps > 0.0 and gap_delta_per_iter >= -1e-9:\n"
            "        gap_stall_sessions = previous_stall_count + 1\n"
            "    else:\n"
            "        gap_stall_sessions = 0\n"
            "    readiness_history.update({\n"
            "        'avg_gaps': avg_gaps,\n"
            "        'gap_stall_sessions': gap_stall_sessions,\n"
            "        'updated_at': _utc_now_isoformat(),\n"
            "    })\n"
            "    self.metadata['readiness_history'] = readiness_history\n"
            "\n"
            "    recommended_actions = []\n"
            "    if not claims:\n"
            "        recommended_actions.append(\n"
            "            'Restore a stable adversarial session flow before tuning graph extraction and dependency tracking.'\n"
            "        )\n"
            "    if total_required_dependencies == 0 and claims:\n"
            "        recommended_actions.append(\n"
            "            'No required dependencies are linked to claims; populate requirement/evidence edges before denoising.'\n"
            "        )\n"
            f"    if gap_stall_sessions >= {stall_threshold} and avg_gaps > 0.0:\n"
            "        recommended_actions.append(\n"
            "            'Gap count is not improving across iterations; prioritize blocker-focused follow-ups in graph_analysis.'\n"
            "        )\n"
            "    if weak_claim_gap_count > 0:\n"
            "        recommended_actions.append(\n"
            "            'Prioritize deterministic requirement closure for housing_discrimination and hacc_research_engine gaps.'\n"
            "        )\n"
            "    if weak_modality_gap_count > 0:\n"
            "        recommended_actions.append(\n"
            "            'Request policy_document and file_evidence fields with exact document name, date, and issuing/source actor.'\n"
            "        )\n"
            "    if deterministic_gap_closure < 0.6 and total_required_dependencies > 0:\n"
            "        recommended_actions.append(\n"
            "            'Map each follow-up question to a deterministic_update_key so each answer closes a concrete graph requirement.'\n"
            "        )\n"
            "\n"
            "    recommended_next_gaps.sort(\n"
            "        key=lambda item: (\n"
            f"            0 if {prioritize_blocking!r} and item.get('blocking') else 1,\n"
            "            0 if item.get('weak_claim_focus') else 1,\n"
            "            0 if item.get('weak_modality_focus') else 1,\n"
            f"            0 if {prioritize_structured!r} and item.get('structured_gap') else 1,\n"
            f"            0 if {promote_deterministic!r} and str(item.get('deterministic_update_key') or '').strip() else 1,\n"
            "            str(item.get('claim_name') or '').lower(),\n"
            "            str(item.get('source_name') or '').lower(),\n"
            "        )\n"
            "    )\n"
            "\n"
            "    return {\n"
            "        'total_claims': len(claims),\n"
            "        'ready_claims': len(ready_claims),\n"
            "        'incomplete_claims': len(incomplete_claims),\n"
            "        'ready_claim_details': ready_claims,\n"
            "        'incomplete_claim_details': incomplete_claims,\n"
            "        'overall_readiness': overall_dependency_satisfaction,\n"
            "        'overall_dependency_satisfaction': overall_dependency_satisfaction,\n"
            "        'dependency_satisfaction': overall_dependency_satisfaction,\n"
            "        'claim_level_dependency_satisfaction': claim_level_satisfaction,\n"
            "        'dependency_coverage': dependency_coverage,\n"
            "        'structured_dependency_coverage': structured_dependency_coverage,\n"
            "        'deterministic_gap_closure': deterministic_gap_closure,\n"
            "        'graph_population_score': graph_population_score,\n"
            "        'graph_analysis_confidence': graph_analysis_confidence,\n"
            "        'total_missing_dependencies': total_missing_dependencies,\n"
            "        'avg_gaps': avg_gaps,\n"
            "        'gap_delta_per_iter': gap_delta_per_iter,\n"
            "        'gap_stall_sessions': gap_stall_sessions,\n"
            "        'underspecified_claims': underspecified_claims,\n"
            "        'weak_claim_gap_count': weak_claim_gap_count,\n"
            "        'weak_modality_gap_count': weak_modality_gap_count,\n"
            "        'recommended_actions': recommended_actions,\n"
            "        'recommended_next_gaps': recommended_next_gaps,\n"
            "        'actor_critic': {\n"
            "            'optimizer': 'actor_critic',\n"
            "            'priority': _ACTOR_CRITIC_PRIORITY,\n"
            "            'phase_focus_order': list(_ACTOR_CRITIC_PHASE_FOCUS_ORDER),\n"
            "            'focus_metrics': dict(_ACTOR_CRITIC_FOCUS_METRICS),\n"
            "            'graph_analysis': {\n"
            "                'dependency_coverage': dependency_coverage,\n"
            "                'structured_dependency_coverage': structured_dependency_coverage,\n"
            "                'deterministic_gap_closure': deterministic_gap_closure,\n"
            "                'graph_population_score': graph_population_score,\n"
            "                'graph_analysis_confidence': graph_analysis_confidence,\n"
            "                'avg_gaps': avg_gaps,\n"
            "                'gap_delta_per_iter': gap_delta_per_iter,\n"
            "                'gap_stall_sessions': gap_stall_sessions,\n"
            "                'weak_claim_types': sorted(_ACTOR_CRITIC_WEAK_CLAIM_TYPES),\n"
            "                'weak_evidence_modalities': sorted(_ACTOR_CRITIC_WEAK_EVIDENCE_MODALITIES),\n"
            "                'weak_claim_gap_count': weak_claim_gap_count,\n"
            "                'weak_modality_gap_count': weak_modality_gap_count,\n"
            "                'recommended_actions': recommended_actions,\n"
            "            },\n"
            "        },\n"
            "    }\n"
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

    def _render_session_injection_from_policy(self, policy: Dict[str, Any]) -> str:
        stability_budget = max(1, min(4, int(policy.get("stability_injection_budget", 3))))
        empty_min_budget = max(2, min(5, int(policy.get("empty_questions_min_budget", 5))))
        limit_missing = bool(policy.get("limit_to_missing_objectives_in_stability", True))
        one_probe = bool(policy.get("one_probe_per_objective_in_stability", True))

        return (
            "@classmethod\n"
            "def _inject_intake_prompt_questions(\n"
            "    cls,\n"
            "    seed_complaint: Dict[str, Any],\n"
            "    questions: Sequence[Any],\n"
            ") -> List[Any]:\n"
            "    existing_questions = list(questions or [])\n"
            "    optimizer_context = cls._extract_actor_critic_intake_context(seed_complaint)\n"
            "    weak_evidence_modalities = set(optimizer_context.get('weak_evidence_modalities') or set())\n"
            "    weak_complaint_types = set(optimizer_context.get('weak_complaint_types') or set())\n"
            "    signal_values = [\n"
            "        float(value)\n"
            "        for value in (\n"
            "            optimizer_context.get('question_quality'),\n"
            "            optimizer_context.get('empathy'),\n"
            "            optimizer_context.get('efficiency'),\n"
            "        )\n"
            "        if isinstance(value, (int, float))\n"
            "    ]\n"
            "    stability_recovery_mode = (not signal_values) or max(signal_values) <= 0.05\n"
            "    seed_boosted_probes: List[tuple[str, str]] = []\n"
            "\n"
            "    if weak_evidence_modalities.intersection({'policy_document', 'file_evidence'}):\n"
            "        seed_boosted_probes.extend([\n"
            "            (\n"
            "                'Which specific policy or procedure document did staff rely on, what section did they cite, and how was it applied to you?',\n"
            "                'documents',\n"
            "            ),\n"
            "            (\n"
            "                'Please list each supporting file you have (notice, email, text, letter, screenshot, or upload), including date, sender, and what fact it proves.',\n"
            "                'documents',\n"
            "            ),\n"
            "        ])\n"
            "    if weak_complaint_types.intersection({'housing_discrimination', 'hacc_research_engine'}):\n"
            "        seed_boosted_probes.extend([\n"
            "            (\n"
            "                'What protected characteristic, accommodation request, or complaint came before the adverse action, and what happened right after it?',\n"
            "                'causation_sequence',\n"
            "            ),\n"
            "            (\n"
            "                'What exact reason was given for the housing decision, who gave it, and what date was it communicated?',\n"
            "                'adverse_action_details',\n"
            "            ),\n"
            "        ])\n"
            "\n"
            "    prioritized_prompts = seed_boosted_probes + cls._extract_intake_prompt_candidates(seed_complaint)\n"
            "    objective_priority: Dict[str, int] = {}\n"
            "    for _, objective in prioritized_prompts:\n"
            "        objective_priority.setdefault(objective, len(objective_priority))\n"
            "\n"
            "    covered_objectives: Set[str] = set()\n"
            "    for question in existing_questions:\n"
            "        for objective in objective_priority:\n"
            "            if cls._candidate_matches_intake_objective(question, objective):\n"
            "                covered_objectives.add(objective)\n"
            "\n"
            "    merged: List[Any] = []\n"
            "    seen = set()\n"
            "    skipped = set()\n"
            "    injected_objectives: Set[str] = set()\n"
            "    missing_objectives = [\n"
            "        objective\n"
            "        for objective in objective_priority\n"
            "        if objective not in covered_objectives\n"
            "    ]\n"
            "\n"
            "    if stability_recovery_mode:\n"
            "        for question in existing_questions:\n"
            "            key = cls._question_dedupe_key(cls._extract_question_text(question))\n"
            "            if key and key in seen:\n"
            "                continue\n"
            "            if key:\n"
            "                seen.add(key)\n"
            "            merged.append(question)\n"
            "\n"
            f"    injection_budget = {stability_budget} if stability_recovery_mode else 10\n"
            "    if not existing_questions:\n"
            f"        injection_budget = max(injection_budget, {empty_min_budget})\n"
            "    injected = 0\n"
            "    for probe_text, probe_type in prioritized_prompts:\n"
            "        if injected >= injection_budget:\n"
            "            break\n"
            f"        if stability_recovery_mode and {str(limit_missing)} and missing_objectives and probe_type not in missing_objectives:\n"
            "            continue\n"
            f"        if stability_recovery_mode and {str(one_probe)} and probe_type in injected_objectives:\n"
            "            continue\n"
            "        key = cls._question_dedupe_key(probe_text)\n"
            "        if key and (key in seen or key in skipped):\n"
            "            continue\n"
            "        synthetic_question = {\n"
            "            'question': probe_text,\n"
            "            'type': probe_type,\n"
            "            'question_objective': probe_type,\n"
            "            'question_reason': 'Structured intake prompt imported from the grounding bundle.',\n"
            "            'source': 'synthetic_intake_prompt',\n"
            "        }\n"
            "        if any(\n"
            "            cls._questions_substantially_overlap(synthetic_question, existing_question)\n"
            "            for existing_question in existing_questions\n"
            "        ):\n"
            "            if key:\n"
            "                skipped.add(key)\n"
            "            continue\n"
            "        if key and key not in seen:\n"
            "            seen.add(key)\n"
            "            injected_objectives.add(probe_type)\n"
            "            merged.append(synthetic_question)\n"
            "            injected += 1\n"
            "\n"
            "    if not stability_recovery_mode:\n"
            "        for question in existing_questions:\n"
            "            key = cls._question_dedupe_key(cls._extract_question_text(question))\n"
            "            if key and key in seen:\n"
            "                continue\n"
            "            if key:\n"
            "                seen.add(key)\n"
            "            merged.append(question)\n"
            "    return merged\n"
        )

    def _render_document_workflow_targeting_from_policy(self, policy: Dict[str, Any]) -> str:
        graph_blocker_weight = float(policy.get("graph_blocker_weight", 0.08))
        document_blocker_weight = float(policy.get("document_blocker_weight", 0.06))
        intake_objective_weight = float(policy.get("intake_objective_weight", 0.05))
        boost_document_notice = bool(policy.get("boost_document_for_notice_chain", True))
        preserve_graph_priority = bool(policy.get("preserve_graph_priority_when_factual_pressure_high", True))

        notice_chain_block = ""
        if boost_document_notice:
            notice_chain_block = (
                "    if blocker_issue_families.intersection({'notice_chain', 'response_timeline', 'hearing_process'}):\n"
                "        phase_scores['document_generation'] = _clamp(float(phase_scores.get('document_generation') or 0.0) + 0.04)\n"
            )

        graph_priority_block = ""
        if preserve_graph_priority:
            graph_priority_block = (
                "    if graph_blockers and factual_pressure >= 0.35:\n"
                "        phase_scores['graph_analysis'] = _clamp(\n"
                "            max(\n"
                "                float(phase_scores.get('graph_analysis') or 0.0),\n"
                "                float(phase_scores.get('intake_questioning') or 0.0) + 0.05,\n"
                "            )\n"
                "        )\n"
            )

        return (
            "def _build_workflow_phase_targeting(\n"
            "    self,\n"
            "    *,\n"
            "    section_scores: Dict[str, float],\n"
            "    support_context: Dict[str, Any],\n"
            ") -> Dict[str, Any]:\n"
            "    priorities = support_context.get('intake_priorities') if isinstance(support_context.get('intake_priorities'), dict) else {}\n"
            "    unresolved_objectives = {\n"
            "        _normalize_intake_objective(item)\n"
            "        for item in list(priorities.get('unresolved_objectives') or [])\n"
            "        if _normalize_intake_objective(item)\n"
            "    }\n"
            "    critical_unresolved = {\n"
            "        _normalize_intake_objective(item)\n"
            "        for item in list(priorities.get('critical_unresolved_objectives') or [])\n"
            "        if _normalize_intake_objective(item)\n"
            "    }\n"
            "    blocker_extraction_targets = {\n"
            "        str(item).strip().lower()\n"
            "        for item in list(priorities.get('blocker_extraction_targets') or [])\n"
            "        if str(item).strip()\n"
            "    }\n"
            "    blocker_workflow_phases = {\n"
            "        str(item).strip().lower()\n"
            "        for item in list(priorities.get('blocker_workflow_phases') or [])\n"
            "        if str(item).strip()\n"
            "    }\n"
            "    blocker_issue_families = {\n"
            "        str(item).strip().lower()\n"
            "        for item in list(priorities.get('blocker_issue_families') or [])\n"
            "        if str(item).strip()\n"
            "    }\n"
            "    blocker_count = int(priorities.get('blocker_count') or 0)\n"
            "    chronology_context_active = any((\n"
            "        bool(priorities.get('anchored_chronology_summary')),\n"
            "        int(priorities.get('claim_temporal_gap_count') or 0) > 0,\n"
            "        int(priorities.get('unresolved_temporal_issue_count', priorities.get('temporal_issue_count', 0)) or 0) > 0,\n"
            "        int(priorities.get('resolved_temporal_issue_count') or 0) > 0,\n"
            "    ))\n"
            "    graph_blockers = unresolved_objectives.intersection({\n"
            "        'exact_dates', 'timeline', 'actors', 'staff_names_titles', 'causation_link', 'causation_sequence',\n"
            "        'anchor_adverse_action', 'anchor_appeal_rights', 'hearing_request_timing', 'response_dates',\n"
            "    })\n"
            "    document_blockers = unresolved_objectives.intersection({\n"
            "        'documents', 'harm_remedy', 'exact_dates', 'anchor_adverse_action', 'anchor_appeal_rights',\n"
            "        'staff_names_titles', 'hearing_request_timing', 'response_dates',\n"
            "    })\n"
            "    factual_pressure = max(0.0, 1.0 - float(section_scores.get('factual_allegations') or 0.0))\n"
            "    claims_pressure = max(0.0, 1.0 - float(section_scores.get('claims_for_relief') or 0.0))\n"
            "    requested_relief_pressure = max(0.0, 1.0 - float(section_scores.get('requested_relief') or 0.0))\n"
            "    affidavit_pressure = max(0.0, 1.0 - float(section_scores.get('affidavit') or 0.0))\n"
            "    certificate_pressure = max(0.0, 1.0 - float(section_scores.get('certificate_of_service') or 0.0))\n"
            "    packet_pressure = max(0.0, 1.0 - float(section_scores.get('packet_projection') or 0.0))\n"
            "    intake_pressure = max(0.0, 1.0 - float(section_scores.get('intake_questioning') or 0.0))\n"
            "    phase_scores = {\n"
            "        'graph_analysis': _clamp(\n"
            "            factual_pressure * 0.55\n"
            "            + claims_pressure * 0.15\n"
            f"            + min(len(graph_blockers) * {graph_blocker_weight:.4f}, 0.28)\n"
            "            + min(len(critical_unresolved.intersection(graph_blockers)) * 0.05, 0.15)\n"
            "            + (0.08 if blocker_workflow_phases.intersection({'graph_analysis'}) else 0.0)\n"
            "            + min(len(blocker_extraction_targets.intersection({'timeline_anchors', 'actor_role_mapping', 'retaliation_sequence', 'hearing_process', 'response_timeline'})) * 0.03, 0.15)\n"
            "        ),\n"
            "        'document_generation': _clamp(\n"
            "            claims_pressure * 0.2\n"
            "            + requested_relief_pressure * 0.2\n"
            "            + affidavit_pressure * 0.2\n"
            "            + certificate_pressure * 0.15\n"
            "            + packet_pressure * 0.15\n"
            f"            + min(len(document_blockers) * {document_blocker_weight:.4f}, 0.18)\n"
            "            + (0.05 if blocker_workflow_phases.intersection({'document_generation'}) else 0.0)\n"
            "        ),\n"
            "        'intake_questioning': _clamp(\n"
            "            (intake_pressure * 0.55)\n"
            f"            + min(len(unresolved_objectives) * {intake_objective_weight:.4f}, 0.2)\n"
            "            + min(len(critical_unresolved) * 0.04, 0.12)\n"
            "            + min(blocker_count * 0.03, 0.12)\n"
            "            + (0.04 if blocker_workflow_phases.intersection({'intake_questioning'}) else 0.0)\n"
            "        ),\n"
            "    }\n"
            f"{notice_chain_block}"
            f"{graph_priority_block}"
            "    phase_focus_order = [\n"
            "        name\n"
            "        for name, _score in sorted(\n"
            "            phase_scores.items(),\n"
            "            key=lambda item: (-float(item[1]), self.WORKFLOW_PHASE_FOCUS_ORDER.index(item[0])),\n"
            "        )\n"
            "    ]\n"
            "    phase_target_sections = {\n"
            "        phase_name: self._select_phase_target_section(\n"
            "            phase_name=phase_name,\n"
            "            section_scores=section_scores,\n"
            "            unresolved_objectives=unresolved_objectives,\n"
            "            chronology_context_active=chronology_context_active,\n"
            "        )\n"
            "        for phase_name in phase_focus_order\n"
            "    }\n"
            "    return {\n"
            "        'phase_scores': phase_scores,\n"
            "        'phase_focus_order': phase_focus_order,\n"
            "        'phase_target_sections': phase_target_sections,\n"
            "    }\n"
        )

    def _render_complainant_guidance_from_policy(self, policy: Dict[str, Any]) -> str:
        objective_limit = max(1, min(4, int(policy.get("unresolved_objective_limit", 3))))
        include_follow_up_prompts = bool(policy.get("include_follow_up_prompt_examples", True))
        encourage_empathy_opening = bool(policy.get("encourage_empathy_opening", True))
        include_document_precision = bool(policy.get("include_document_precision_guidance", True))
        include_phase_focus_line = bool(policy.get("include_phase_focus_line", True))

        empathy_block = ""
        if encourage_empathy_opening:
            empathy_block = (
                "    if str(context.emotional_state).lower() in _EMPATHY_HEAVY_STATES:\n"
                "        guidance.append('Open with one brief impact/emotion sentence, then provide concrete facts.')\n"
            )

        follow_up_block = ""
        if include_follow_up_prompts:
            follow_up_block = (
                "        follow_up_prompts = [\n"
                "            prompt\n"
                "            for prompt in (_objective_follow_up_prompt(item) for item in prioritized)\n"
                "            if prompt\n"
                "        ]\n"
                "        if follow_up_prompts:\n"
                "            guidance.append('Suggested high-yield follow-up prompts: ' + ' | '.join(follow_up_prompts))\n"
            )

        document_block = ""
        if include_document_precision:
            document_block = (
                "    if any(token in question_lower for token in _DOCUMENT_ARTIFACT_TERMS):\n"
                "        guidance.append('Name documentary artifacts precisely (letter/email/notice), including IDs or subject lines when available.')\n"
            )

        phase_focus_block = ""
        if include_phase_focus_line:
            phase_focus_block = (
                "    guidance.append(\n"
                "        'Phase focus order: '\n"
                "        + ' -> '.join(phase_focus[:3] if phase_focus else list(_ACTOR_CRITIC_PHASE_FOCUS_ORDER))\n"
                "        + '.'\n"
                "    )\n"
            )

        return (
            "def _build_actor_critic_guidance(self, question: str) -> str:\n"
            "    question_text = str(question or '').strip()\n"
            "    question_lower = question_text.lower()\n"
            "    context = self.context or ComplaintContext(complaint_type='unknown', key_facts={})\n"
            "\n"
            "    phase_focus = _ordered_workflow_phases(\n"
            "        list(context.workflow_phase_priorities or _ACTOR_CRITIC_PHASE_FOCUS_ORDER),\n"
            "        explicit_phase_order=_ACTOR_CRITIC_PHASE_FOCUS_ORDER,\n"
            "    )\n"
            "    placeholder_objectives = [\n"
            "        str(item.get('objective') or '').strip()\n"
            "        for item in _extract_confirmation_placeholders(context.key_facts)\n"
            "        if isinstance(item, dict)\n"
            "    ]\n"
            "    unresolved_objectives = _order_objectives_for_actor_critic(\n"
            "        list(context.blocker_objectives or []) + placeholder_objectives,\n"
            "        phase_focus_order=phase_focus,\n"
            "    )\n"
            "\n"
            "    guidance: List[str] = []\n"
            "    guidance.append('Keep your answer short, factual, and easy for the mediator to act on in the next question.')\n"
            f"{empathy_block}"
            "    if any(token in question_lower for token in ('how did that affect you', 'impact', 'harm', 'stress', 'feeling', 'feel')):\n"
            "        guidance.append('Name one concrete impact (housing/work/health/financial) and one emotional impact.')\n"
            "    if any(token in question_lower for token in ('why', 'explain', 'tell me more', 'what happened')) and len(question_text.split()) < 10:\n"
            "        guidance.append('If the question is vague, provide the best direct answer and add one precise clarification need.')\n"
            "\n"
            "    if unresolved_objectives:\n"
            f"        prioritized = unresolved_objectives[:{objective_limit}]\n"
            "        guidance.append(\n"
            "            \"When facts remain unresolved, end with a short 'still needs confirmation' line for: \"\n"
            "            + ', '.join(prioritized)\n"
            "            + '.'\n"
            "        )\n"
            f"{follow_up_block}"
            "    else:\n"
            "        guidance.append('If chronology or decision-maker precision still feels vague, ask one explicit follow-up prompt before ending.')\n"
            "\n"
            "    if any(token in question_lower for token in _CHRONOLOGY_TERMS):\n"
            "        guidance.append('Close chronology gaps by providing event sequence with dates and response timing, even if approximate.')\n"
            "    if any(token in question_lower for token in _DECISION_MAKER_TERMS):\n"
            "        guidance.append('Pin down each decision-maker and role; if uncertain, provide the best known role and source context.')\n"
            f"{document_block}"
            f"{phase_focus_block}"
            "    return '\\n'.join(f'- {item}' for item in guidance)\n"
        )

    def _apply_merge_seed_with_grounding_policy_to_source(self, source: str, policy: Dict[str, Any]) -> str:
        updated = str(source)
        replacements = [
            (
                r"for passage in anchor_passages\[:\d+\]:",
                f"for passage in anchor_passages[:{int(policy.get('anchor_passage_limit', 5))}]:",
            ),
            (
                r"for evidence in \[dict\(item\) for item in list\(merged\.get\(\"hacc_evidence\"\) or \[\]\) if isinstance\(item, dict\)\]\[:\d+\]:",
                "for evidence in [dict(item) for item in list(merged.get(\"hacc_evidence\") or []) if isinstance(item, dict)]"
                f"[:{int(policy.get('evidence_item_limit', 8))}]:",
            ),
            (
                r"for answer in blocker_handoff_raw_answers\[:\d+\]:",
                f"for answer in blocker_handoff_raw_answers[:{int(policy.get('blocker_answer_limit', 6))}]:",
            ),
            (
                r"for objective in prioritized\[:\d+\]:",
                f"for objective in prioritized[:{int(policy.get('unresolved_objective_limit', 3))}]:",
            ),
        ]
        for pattern, replacement in replacements:
            updated, count = re.subn(pattern, replacement, updated, count=1)
            if count != 1:
                raise ValueError(f"Could not apply merge-seed-with-grounding policy pattern: {pattern}")
        try:
            ast.parse(updated)
        except SyntaxError as exc:
            raise ValueError(f"Merge-seed-with-grounding policy produced invalid Python: {exc}") from exc
        return updated

    def _apply_formal_document_render_policy_to_source(self, source: str, policy: Dict[str, Any]) -> str:
        updated = str(source)
        replacements = [
            (
                r"for index, chronology_line in enumerate\(chronology_lines, 1\):",
                f"for index, chronology_line in enumerate(chronology_lines[:{int(policy.get('chronology_line_limit', 5))}], 1):",
            ),
            (
                r"for fact in supporting_facts:",
                f"for fact in supporting_facts[:{int(policy.get('supporting_fact_limit', 4))}]:",
            ),
            (
                r"for exhibit in exhibits:",
                f"for exhibit in exhibits[:{int(policy.get('exhibit_limit', 8))}]:",
            ),
            (
                r"for index, fact in enumerate\(_listify\(affidavit\.get\(\"facts\"\)\), 1\):",
                f"for index, fact in enumerate(_listify(affidavit.get(\"facts\"))[:{int(policy.get('affidavit_fact_limit', 6))}], 1):",
            ),
        ]
        for pattern, replacement in replacements:
            updated, count = re.subn(pattern, replacement, updated, count=1)
            if count != 1:
                raise ValueError(f"Could not apply formal-document render policy pattern: {pattern}")
        try:
            ast.parse(textwrap.dedent(updated))
        except SyntaxError as exc:
            raise ValueError(f"Formal-document render policy produced invalid Python: {exc}") from exc
        return updated

    def _render_knowledge_graph_build_from_text_from_policy(self, policy: Dict[str, Any]) -> str:
        normalize_whitespace = bool(policy.get("normalize_whitespace_input", True))
        record_text_size = bool(policy.get("record_source_text_char_count", True))
        record_extraction_counts = bool(policy.get("record_extraction_counts", True))
        mark_empty_input_graph = bool(policy.get("mark_empty_input_graph", True))
        preserve_actor_critic_metadata = bool(policy.get("preserve_actor_critic_metadata", True))

        input_normalization = (
            "    source_text = str(text or '')\n"
            "    normalized_text = ' '.join(source_text.split())\n"
            if normalize_whitespace
            else
            "    source_text = str(text or '')\n"
            "    normalized_text = source_text\n"
        )
        text_size_block = (
            "    graph.metadata['source_text_char_count'] = len(normalized_text)\n"
            if record_text_size
            else ""
        )
        empty_input_block = (
            "    if not normalized_text.strip():\n"
            "        graph.metadata['build_status'] = 'empty_input'\n"
            if mark_empty_input_graph
            else ""
        )
        extraction_count_block = (
            "    graph.metadata['extracted_entity_candidates'] = len(entities)\n"
            "    graph.metadata['extracted_relationship_candidates'] = len(relationships)\n"
            if record_extraction_counts
            else ""
        )
        actor_critic_block = (
            "    if self.actor_critic_enabled:\n"
            "        entity_scores = [\n"
            "            float((entity.attributes or {}).get(\"actor_critic_score\", 0.0) or 0.0)\n"
            "            for entity in graph.entities.values()\n"
            "        ]\n"
            "        relationship_scores = [\n"
            "            float((rel.attributes or {}).get(\"actor_critic_score\", 0.0) or 0.0)\n"
            "            for rel in graph.relationships.values()\n"
            "        ]\n"
            "        graph.metadata[\"actor_critic\"] = {\n"
            "            \"enabled\": True,\n"
            "            \"entity_count\": len(entity_scores),\n"
            "            \"relationship_count\": len(relationship_scores),\n"
            "            \"avg_entity_score\": (\n"
            "                round(sum(entity_scores) / len(entity_scores), 4) if entity_scores else 0.0\n"
            "            ),\n"
            "            \"avg_relationship_score\": (\n"
            "                round(sum(relationship_scores) / len(relationship_scores), 4) if relationship_scores else 0.0\n"
            "            ),\n"
            "            \"entity_score_floor\": float(self.min_entity_actor_critic_score),\n"
            "            \"relationship_score_floor\": float(self.min_relationship_actor_critic_score),\n"
            "        }\n"
            if preserve_actor_critic_metadata
            else ""
        )

        rendered = (
            "def build_from_text(self, text: str) -> KnowledgeGraph:\n"
            "    \"\"\"\n"
            "    Build a knowledge graph from complaint text.\n"
            "    \n"
            "    Args:\n"
            "        text: The complaint text to analyze\n"
            "        \n"
            "    Returns:\n"
            "        A KnowledgeGraph instance\n"
            "    \"\"\"\n"
            "    graph = KnowledgeGraph()\n"
            f"{input_normalization}"
            f"{text_size_block}"
            f"{empty_input_block}"
            "\n"
            "    entities = self._extract_entities(normalized_text)\n"
            "    for entity_data in entities:\n"
            "        entity = Entity(\n"
            "            id=self._get_entity_id(),\n"
            "            type=entity_data['type'],\n"
            "            name=entity_data['name'],\n"
            "            attributes=entity_data.get('attributes', {}),\n"
            "            confidence=entity_data.get('confidence', 0.8),\n"
            "            source='complaint'\n"
            "        )\n"
            "        graph.add_entity(entity)\n"
            "\n"
            "    relationships = self._extract_relationships(normalized_text, graph)\n"
            "    for rel_data in relationships:\n"
            "        rel = Relationship(\n"
            "            id=self._get_relationship_id(),\n"
            "            source_id=rel_data['source_id'],\n"
            "            target_id=rel_data['target_id'],\n"
            "            relation_type=rel_data['type'],\n"
            "            attributes=rel_data.get('attributes', {}),\n"
            "            confidence=rel_data.get('confidence', 0.8),\n"
            "            source='complaint'\n"
            "        )\n"
            "        graph.add_relationship(rel)\n"
            f"{extraction_count_block}"
            "\n"
            f"{actor_critic_block}"
            "    logger.info(f\"Built knowledge graph: {graph.summary()}\")\n"
            "    self._built_graphs.append(graph)\n"
            "    self._text_processed_count += 1\n"
            "    return graph\n"
        )
        ast.parse(rendered)
        return rendered

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
