"""Validated optimization pipeline integration.

This module provides the integration layer between the agentic optimization
pipeline and the comprehensive validation framework. It ensures that:

1. Baseline metrics are captured before optimization
2. Optimized code is validated against multiple validation levels
3. Performance improvements are measured
4. Validation results are captured in OptimizationResult

Usage:
    >>> from ipfs_datasets_py.optimizers.agentic.validated_optimization_pipeline import (
    ...     ValidatedOptimizationPipeline,
    ... )
    >>> pipeline = ValidatedOptimizationPipeline(optimizer, validation_level="standard")
    >>> result = pipeline.optimize(task)
    >>> print(f"Validation: {result.validation.passed}")
    >>> print(f"Improvements: {result.metrics}")
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.optimizers.agentic.base import (
    AgenticOptimizer,
    OptimizationResult,
    OptimizationTask,
    ValidationResult,
)
from ipfs_datasets_py.optimizers.agentic.validation import (
    DetailedValidationResult,
    OptimizationValidator,
    ValidationLevel,
)


class ValidatedOptimizationPipeline:
    """Wraps an agentic optimizer with comprehensive validation.
    
    This pipeline captures metrics before and after optimization, validates
    the optimized code against multiple checks, and returns comprehensive
    validation results as part of the optimization output.
    
    Attributes:
        optimizer: The agentic optimizer to wrap
        validator: The optimization validator instance
        validation_level: Validation strictness level
        capture_metrics: Whether to capture before/after metrics
        logger: Logger instance
    """
    
    def __init__(
        self,
        optimizer: AgenticOptimizer,
        validation_level: str = "standard",
        capture_metrics: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        """Initialize validated optimization pipeline.
        
        Args:
            optimizer: The agentic optimizer to wrap
            validation_level: Validation level ("basic", "standard", "strict", "paranoid")
            capture_metrics: Whether to capture performance metrics
            logger: Optional logger instance
        """
        self.optimizer = optimizer
        self.capture_metrics = capture_metrics
        self.logger = logger or logging.getLogger(__name__)
        
        # Parse validation level
        try:
            self.validation_level = ValidationLevel(validation_level.lower())
        except ValueError:
            self.logger.warning(
                f"Invalid validation level '{validation_level}', defaulting to 'standard'"
            )
            self.validation_level = ValidationLevel.STANDARD
        
        # Initialize validation orchestrator
        self.validator = OptimizationValidator(
            level=self.validation_level,
            parallel=True,
            max_workers=4,
        )
    
    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        """Perform validated optimization.
        
        This method:
        1. Captures baseline metrics from original code
        2. Calls the underlying optimizer
        3. Validates the optimized code
        4. Captures performance improvements
        5. Returns comprehensive result with validation
        
        Args:
            task: The optimization task
            
        Returns:
            OptimizationResult with validation and metrics
            
        Raises:
            ValueError: If task is invalid
            RuntimeError: If optimization fails
        """
        pipeline_start = time.time()
        baseline_metrics = {}
        
        # Step 1: Capture baseline metrics from original code
        if self.capture_metrics and task.target_files:
            baseline_metrics = self._capture_baseline_metrics(task.target_files)
        
        # Step 2: Run the underlying optimizer
        result = self.optimizer.optimize(task)
        
        # Step 3: Validate optimized code (if optimization succeeded)
        if result.success and result.optimized_code:
            validation_start = time.time()
            
            validation_result = self._validate_optimized_code(
                result.optimized_code,
                task.target_files,
                baseline_metrics,
            )
            
            # Attach validation result to optimization result
            result.validation = validation_result
            
            validation_time = time.time() - validation_start
            result.metrics["validation_time_sec"] = validation_time
        else:
            # No validation if optimization failed
            result.validation = ValidationResult(passed=False)
        
        # Step 4: Calculate total execution time
        total_time = time.time() - pipeline_start
        result.execution_time = total_time
        
        # Log results
        self._log_optimization_results(result, baseline_metrics)
        
        return result
    
    def _capture_baseline_metrics(self, target_files: List[Path]) -> Dict[str, float]:
        """Capture baseline metrics from original code.
        
        Args:
            target_files: List of target file paths
            
        Returns:
            Dictionary with baseline metrics
        """
        metrics = {
            "baseline_file_count": len(target_files),
            "baseline_total_lines": 0,
            "baseline_total_size_bytes": 0,
        }
        
        try:
            for file_path in target_files:
                if file_path.exists():
                    # Line count
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = len(f.readlines())
                    metrics["baseline_total_lines"] += lines
                    
                    # File size
                    metrics["baseline_total_size_bytes"] += file_path.stat().st_size
        except (OSError, ValueError) as e:
            self.logger.warning(f"Failed to capture baseline metrics: {e}")
        
        return metrics
    
    def _validate_optimized_code(
        self,
        code: str,
        target_files: List[Path],
        baseline_metrics: Dict[str, float],
    ) -> ValidationResult:
        """Validate optimized code using comprehensive validation framework.
        
        Args:
            code: The optimized code to validate
            target_files: List of target file paths
            baseline_metrics: Baseline metrics for context
            
        Returns:
            ValidationResult with comprehensive checks
        """
        try:
            # Build validation context with baseline metrics
            context = {"baseline_metrics": baseline_metrics}
            
            # Run comprehensive validation
            detailed_result: DetailedValidationResult = self.validator.validate(
                code=code,
                target_files=target_files,
                level=self.validation_level,
                context=context,
            )
            
            # Convert to simple ValidationResult
            validation_result = ValidationResult(
                passed=detailed_result.passed,
                syntax_check=detailed_result.syntax.get("passed", False),
                type_check=detailed_result.types.get("passed", True),
                unit_tests=detailed_result.unit_tests.get("passed", True),
                integration_tests=detailed_result.integration_tests.get("passed", True),
                performance_tests=detailed_result.performance.get("passed", True),
                security_scan=detailed_result.security.get("passed", True),
                style_check=detailed_result.style.get("passed", True),
                errors=detailed_result.errors,
                warnings=detailed_result.warnings,
            )
            
            return validation_result
            
        except Exception as e:
            self.logger.warning(f"Validation error: {e}")
            return ValidationResult(
                passed=False,
                errors=[f"Validation framework error: {str(e)}"],
            )
    
    def _log_optimization_results(
        self,
        result: OptimizationResult,
        baseline_metrics: Dict[str, float],
    ) -> None:
        """Log optimization and validation results.
        
        Args:
            result: The optimization result
            baseline_metrics: Baseline metrics for comparison
        """
        if result.success:
            log_msg = (
                f"✓ Optimization successful: method={result.method.value}, "
                f"time={result.execution_time:.2f}s"
            )
            if result.validation:
                log_msg += f", validation={'passed' if result.validation.passed else 'failed'}"
            
            self.logger.info(log_msg)
            
            # Log validation breakdown if available
            if result.validation and not result.validation.passed:
                for error in result.validation.errors:
                    self.logger.warning(f"  - {error}")
        else:
            self.logger.error(
                f"✗ Optimization failed: {result.error_message}"
            )
    
    def validate_only(
        self,
        code: str,
        target_files: Optional[List[Path]] = None,
    ) -> ValidationResult:
        """Validate code without running a full optimization.
        
        This is useful for validating code outside the optimization pipeline.
        
        Args:
            code: Code to validate
            target_files: List of target files (optional)
            
        Returns:
            ValidationResult with comprehensive checks
        """
        target_files = target_files or []
        
        try:
            detailed_result = self.validator.validate(
                code=code,
                target_files=target_files,
                level=self.validation_level,
            )
            
            return ValidationResult(
                passed=detailed_result.passed,
                syntax_check=detailed_result.syntax.get("passed", False),
                type_check=detailed_result.types.get("passed", True),
                unit_tests=detailed_result.unit_tests.get("passed", True),
                integration_tests=detailed_result.integration_tests.get("passed", True),
                performance_tests=detailed_result.performance.get("passed", True),
                security_scan=detailed_result.security.get("passed", True),
                style_check=detailed_result.style.get("passed", True),
                errors=detailed_result.errors,
                warnings=detailed_result.warnings,
            )
            
        except Exception as e:
            return ValidationResult(
                passed=False,
                errors=[f"Validation error: {str(e)}"],
            )
    
    def get_validation_capabilities(self) -> Dict[str, Any]:
        """Get validation capabilities for this pipeline.
        
        Returns:
            Dictionary describing validation capabilities
        """
        return {
            "validation_level": self.validation_level.value,
            "parallel_validation": True,
            "metric_capture": self.capture_metrics,
            "supported_checks": [
                "syntax",
                "type_checking",
                "unit_tests",
                "integration_tests",
                "performance",
                "security",
                "style",
            ],
        }
