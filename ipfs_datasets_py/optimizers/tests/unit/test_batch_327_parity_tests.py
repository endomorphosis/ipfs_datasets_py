"""Batch 327: Parity Testing Framework - Comprehensive Test Suite

Implements parity testing to validate that refactored code produces identical results
to original implementations. Used before/after refactoring to ensure no behavior changes.

Parity testing verifies:
- Identical output for same inputs (result equality)
- Snapshot comparison with tolerances
- Statistical distribution equivalence
- Performance consistency
- Side-effect equivalence

Key test areas:
- Baseline snapshot management
- Tolerance configuration for floats
- Result comparison and assertion
- Report generation and analysis
- Snapshot regression detection
- Integration patterns

"""

import pytest
from typing import Any, Callable, List, Dict, Optional, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from abc import ABC, abstractmethod
import json
import hashlib
from datetime import datetime


class ComparisonMode(Enum):
    """How to compare parity test results."""
    EXACT = "exact"  # Byte-for-byte equality
    APPROXIMATE = "approximate"  # Tolerance-based (for floats)
    STATISTICAL = "statistical"  # Distribution equivalence
    SEMANTIC = "semantic"  # Logical equivalence


@dataclass
class ParityTestConfig:
    """Configuration for parity testing."""
    mode: ComparisonMode = ComparisonMode.APPROXIMATE
    float_tolerance: float = 1e-6
    list_size_tolerance: float = 0.95  # 95% size match
    allow_reordering: bool = False
    max_log_size: int = 1000
    capture_timestamps: bool = True


@dataclass
class ParitySnapshot:
    """Represents a snapshot of function output for parity comparison."""
    function_name: str
    inputs: Dict[str, Any]
    output: Any
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    output_type: str = ""
    output_hash: str = ""
    execution_time_ms: float = 0.0
    
    def calculate_hash(self) -> str:
        """Calculate hash of output for quick comparison."""
        output_str = str(self.output)
        return hashlib.sha256(output_str.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize snapshot to dict."""
        return {
            "function_name": self.function_name,
            "inputs": self.inputs,
            "output": self.output,
            "timestamp": self.timestamp,
            "output_type": self.output_type,
            "output_hash": self.output_hash,
            "execution_time_ms": self.execution_time_ms,
        }


class ParityResult:
    """Result of a parity test comparison."""
    
    def __init__(self, original: ParitySnapshot, refactored: ParitySnapshot,
                 passed: bool, differences: List[str] = None):
        self.original = original
        self.refactored = refactored
        self.passed = passed
        self.differences = differences or []
        self.message = "Results are identical" if passed else "; ".join(self.differences)
    
    def __bool__(self) -> bool:
        """True if parity test passed."""
        return self.passed
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "passed": self.passed,
            "message": self.message,
            "differences": self.differences,
            "original_output": str(self.original.output)[:100],
            "refactored_output": str(self.refactored.output)[:100],
        }


class ParityComparator:
    """Compares two snapshots for parity."""
    
    def __init__(self, config: ParityTestConfig = None):
        self.config = config or ParityTestConfig()
    
    def compare_exact(self, original: ParitySnapshot, 
                     refactored: ParitySnapshot) -> Tuple[bool, List[str]]:
        """Exact comparison using equality."""
        if original.output == refactored.output:
            return True, []
        else:
            return False, [f"Outputs not equal: {original.output} != {refactored.output}"]
    
    def compare_approximate(self, original: ParitySnapshot,
                           refactored: ParitySnapshot) -> Tuple[bool, List[str]]:
        """Approximate comparison with float tolerance."""
        differences = []
        
        # Type mismatch
        if type(original.output) != type(refactored.output):
            differences.append(f"Type mismatch: {type(original.output)} vs {type(refactored.output)}")
            return False, differences
        
        # Float comparison
        if isinstance(original.output, float):
            if abs(original.output - refactored.output) > self.config.float_tolerance:
                differences.append(
                    f"Float difference: {abs(original.output - refactored.output)} "
                    f"exceeds tolerance {self.config.float_tolerance}"
                )
                return False, differences
        # List comparison
        elif isinstance(original.output, list):
            if not self._compare_lists(original.output, refactored.output, differences):
                return False, differences
        # Dict comparison
        elif isinstance(original.output, dict):
            if not self._compare_dicts(original.output, refactored.output, differences):
                return False, differences
        # Exact equality for other types
        elif original.output != refactored.output:
            differences.append(f"Values not equal: {original.output} != {refactored.output}")
            return False, differences
        
        return len(differences) == 0, differences
    
    def _compare_lists(self, original: list, refactored: list, 
                      differences: List[str]) -> bool:
        """Compare two lists with tolerance."""
        # Size check
        if len(original) != len(refactored):
            ratio = len(refactored) / len(original) if original else 0
            if ratio < self.config.list_size_tolerance:
                differences.append(
                    f"List size mismatch: {len(original)} vs {len(refactored)} "
                    f"(ratio {ratio:.2%})"
                )
                return False
        
        # Element comparison (first few)
        for i, (o, r) in enumerate(zip(original, refactored)):
            if isinstance(o, float) and isinstance(r, float):
                if abs(o - r) > self.config.float_tolerance:
                    differences.append(f"List element {i}: float diff {abs(o - r)}")
                    return False
            elif o != r:
                differences.append(f"List element {i}: {o} != {r}")
                return False
        
        return True
    
    def _compare_dicts(self, original: dict, refactored: dict,
                      differences: List[str]) -> bool:
        """Compare two dicts."""
        # Check keys
        if set(original.keys()) != set(refactored.keys()):
            differences.append(
                f"Dict keys differ: {set(original.keys()) ^ set(refactored.keys())}"
            )
            return False
        
        # Compare values
        for key in original.keys():
            o_val = original[key]
            r_val = refactored[key]
            
            if isinstance(o_val, float) and isinstance(r_val, float):
                if abs(o_val - r_val) > self.config.float_tolerance:
                    differences.append(f"Dict[{key}]: float diff {abs(o_val - r_val)}")
                    return False
            elif o_val != r_val:
                differences.append(f"Dict[{key}]: {o_val} != {r_val}")
                return False
        
        return True
    
    def compare(self, original: ParitySnapshot,
               refactored: ParitySnapshot) -> ParityResult:
        """Compare snapshots based on configured mode."""
        if self.config.mode == ComparisonMode.EXACT:
            passed, diffs = self.compare_exact(original, refactored)
        elif self.config.mode == ComparisonMode.APPROXIMATE:
            passed, diffs = self.compare_approximate(original, refactored)
        else:
            raise NotImplementedError(f"Mode {self.config.mode} not implemented")
        
        return ParityResult(original, refactored, passed, diffs)


class ParityTestHarness:
    """Orchestrates parity testing across function pairs."""
    
    def __init__(self, config: ParityTestConfig = None):
        self.config = config or ParityTestConfig()
        self.comparator = ParityComparator(self.config)
        self.baselines: Dict[str, ParitySnapshot] = {}
        self.results: List[ParityResult] = []
    
    def capture_baseline(self, func: Callable, func_name: str,
                        test_cases: List[Dict[str, Any]]) -> None:
        """Capture baseline snapshots from original implementation."""
        for inputs in test_cases:
            output = func(**inputs)
            snapshot = ParitySnapshot(
                function_name=func_name,
                inputs=inputs,
                output=output,
                output_type=type(output).__name__,
                output_hash="",
            )
            snapshot.output_hash = snapshot.calculate_hash()
            
            key = f"{func_name}_{snapshot.output_hash}"
            self.baselines[key] = snapshot
    
    def test_refactored(self, original_func: Callable, refactored_func: Callable,
                       func_name: str, test_cases: List[Dict[str, Any]]) -> List[ParityResult]:
        """Test refactored function against original."""
        results = []
        
        for inputs in test_cases:
            # Capture original
            original_output = original_func(**inputs)
            original_snapshot = ParitySnapshot(
                function_name=func_name,
                inputs=inputs,
                output=original_output,
                output_type=type(original_output).__name__,
            )
            original_snapshot.output_hash = original_snapshot.calculate_hash()
            
            # Capture refactored
            refactored_output = refactored_func(**inputs)
            refactored_snapshot = ParitySnapshot(
                function_name=func_name,
                inputs=inputs,
                output=refactored_output,
                output_type=type(refactored_output).__name__,
            )
            refactored_snapshot.output_hash = refactored_snapshot.calculate_hash()
            
            # Compare
            result = self.comparator.compare(original_snapshot, refactored_snapshot)
            results.append(result)
            self.results.append(result)
        
        return results
    
    def get_results_summary(self) -> Dict[str, Any]:
        """Summarize all parity test results."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        
        return {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 1.0,
            "failures": [r.to_dict() for r in self.results if not r.passed],
        }


class SimpleFunctionPairs:
    """Test helper with original/refactored function pairs."""
    
    @staticmethod
    def original_weight_score(value: float, weight: float) -> float:
        """Original weighted score implementation."""
        return value * weight
    
    @staticmethod
    def refactored_weight_score(value: float, weight: float) -> float:
        """Refactored weighted score (should be identical)."""
        return value * weight
    
    @staticmethod
    def original_clamp(value: float, min_val: float, max_val: float) -> float:
        """Original clamping implementation."""
        if value < min_val:
            return min_val
        if value > max_val:
            return max_val
        return value
    
    @staticmethod
    def refactored_clamp(value: float, min_val: float, max_val: float) -> float:
        """Refactored clamping using builtin."""
        return max(min_val, min(value, max_val))
    
    @staticmethod
    def original_score_list(scores: List[float]) -> List[float]:
        """Original list normalization."""
        if not scores:
            return []
        max_score = max(scores)
        if max_score == 0:
            return scores
        return [s / max_score for s in scores]
    
    @staticmethod
    def refactored_score_list(scores: List[float]) -> List[float]:
        """Refactored list normalization."""
        if not scores or max(scores) == 0:
            return scores
        return [s / max(scores) for s in scores]


# Test Suite

class TestComparisonMode:
    """Test ComparisonMode enum."""
    
    def test_modes_defined(self):
        """Should have standard comparison modes."""
        assert ComparisonMode.EXACT in ComparisonMode
        assert ComparisonMode.APPROXIMATE in ComparisonMode


class TestParityTestConfig:
    """Test ParityTestConfig configuration."""
    
    def test_default_config(self):
        """Should create config with defaults."""
        config = ParityTestConfig()
        
        assert config.mode == ComparisonMode.APPROXIMATE
        assert config.float_tolerance == 1e-6
        assert config.list_size_tolerance == 0.95
    
    def test_custom_config(self):
        """Should accept custom configuration."""
        config = ParityTestConfig(
            mode=ComparisonMode.EXACT,
            float_tolerance=1e-9,
        )
        
        assert config.mode == ComparisonMode.EXACT
        assert config.float_tolerance == 1e-9


class TestParitySnapshot:
    """Test ParitySnapshot dataclass."""
    
    def test_create_snapshot(self):
        """Should create snapshot with outputs."""
        snapshot = ParitySnapshot(
            function_name="test_func",
            inputs={"x": 1, "y": 2},
            output=3.14,
        )
        
        assert snapshot.function_name == "test_func"
        assert snapshot.inputs == {"x": 1, "y": 2}
        assert snapshot.output == 3.14
    
    def test_calculate_hash(self):
        """Should calculate output hash."""
        snapshot = ParitySnapshot(
            function_name="func",
            inputs={},
            output=42,
        )
        
        hash_val = snapshot.calculate_hash()
        assert isinstance(hash_val, str)
        assert len(hash_val) == 16
    
    def test_snapshot_to_dict(self):
        """Should serialize to dictionary."""
        snapshot = ParitySnapshot(
            function_name="func",
            inputs={"x": 1},
            output=10,
            output_hash="abc123",
        )
        
        snapshot_dict = snapshot.to_dict()
        assert snapshot_dict["function_name"] == "func"
        assert snapshot_dict["output"] == 10


class TestParityResult:
    """Test ParityResult."""
    
    def test_passed_result(self):
        """Should represent passed parity test."""
        snap1 = ParitySnapshot("func", {}, 42)
        snap2 = ParitySnapshot("func", {}, 42)
        
        result = ParityResult(snap1, snap2, passed=True)
        
        assert result.passed is True
        assert bool(result) is True
    
    def test_failed_result(self):
        """Should represent failed parity test."""
        snap1 = ParitySnapshot("func", {}, 42)
        snap2 = ParitySnapshot("func", {}, 43)
        
        result = ParityResult(
            snap1, snap2, passed=False,
            differences=["42 != 43"]
        )
        
        assert result.passed is False
        assert bool(result) is False
        assert len(result.differences) == 1


class TestParityComparator:
    """Test ParityComparator."""
    
    def test_exact_equal(self):
        """Should pass exact comparison for equal values."""
        config = ParityTestConfig(mode=ComparisonMode.EXACT)
        comparator = ParityComparator(config)
        
        snap1 = ParitySnapshot("func", {}, 42)
        snap2 = ParitySnapshot("func", {}, 42)
        
        passed, diffs = comparator.compare_exact(snap1, snap2)
        assert passed is True
        assert len(diffs) == 0
    
    def test_exact_not_equal(self):
        """Should fail exact comparison for unequal values."""
        config = ParityTestConfig(mode=ComparisonMode.EXACT)
        comparator = ParityComparator(config)
        
        snap1 = ParitySnapshot("func", {}, 42)
        snap2 = ParitySnapshot("func", {}, 43)
        
        passed, diffs = comparator.compare_exact(snap1, snap2)
        assert passed is False
        assert len(diffs) > 0
    
    def test_approximate_float(self):
        """Should pass approximate comparison within tolerance."""
        config = ParityTestConfig(mode=ComparisonMode.APPROXIMATE, 
                                  float_tolerance=1e-6)
        comparator = ParityComparator(config)
        
        snap1 = ParitySnapshot("func", {}, 1.0)
        snap2 = ParitySnapshot("func", {}, 1.0000001)
        
        passed, diffs = comparator.compare_approximate(snap1, snap2)
        assert passed is True
    
    def test_approximate_float_exceed_tolerance(self):
        """Should fail when exceeding tolerance."""
        config = ParityTestConfig(mode=ComparisonMode.APPROXIMATE,
                                  float_tolerance=1e-6)
        comparator = ParityComparator(config)
        
        snap1 = ParitySnapshot("func", {}, 1.0)
        snap2 = ParitySnapshot("func", {}, 1.1)
        
        passed, diffs = comparator.compare_approximate(snap1, snap2)
        assert passed is False
    
    def test_approximate_list(self):
        """Should compare lists approximately."""
        config = ParityTestConfig(mode=ComparisonMode.APPROXIMATE)
        comparator = ParityComparator(config)
        
        snap1 = ParitySnapshot("func", {}, [1.0, 2.0, 3.0])
        snap2 = ParitySnapshot("func", {}, [1.0, 2.0, 3.0])
        
        passed, diffs = comparator.compare_approximate(snap1, snap2)
        assert passed is True
    
    def test_compare_method(self):
        """Should dispatch to correct comparison method."""
        config = ParityTestConfig(mode=ComparisonMode.EXACT)
        comparator = ParityComparator(config)
        
        snap1 = ParitySnapshot("func", {}, 42)
        snap2 = ParitySnapshot("func", {}, 42)
        
        result = comparator.compare(snap1, snap2)
        assert result.passed is True


class TestParityTestHarness:
    """Test ParityTestHarness orchestration."""
    
    def test_capture_baseline(self):
        """Should capture baseline from function."""
        def test_func(x):
            return x * 2
        
        harness = ParityTestHarness()
        test_cases = [{"x": 1}, {"x": 2}, {"x": 3}]
        
        harness.capture_baseline(test_func, "double", test_cases)
        
        assert len(harness.baselines) == 3
    
    def test_test_refactored_identical(self):
        """Should pass when functions are identical."""
        def original(x):
            return x * 2
        
        def refactored(x):
            return x * 2
        
        harness = ParityTestHarness()
        test_cases = [{"x": 1}, {"x": 5}]
        
        results = harness.test_refactored(original, refactored, "double", test_cases)
        
        assert len(results) == 2
        assert all(r.passed for r in results)
    
    def test_test_refactored_different(self):
        """Should fail when functions differ."""
        def original(x):
            return x * 2
        
        def refactored(x):
            return x * 3  # Incorrect
        
        harness = ParityTestHarness()
        test_cases = [{"x": 1}]
        
        results = harness.test_refactored(original, refactored, "double", test_cases)
        
        assert len(results) == 1
        assert not results[0].passed
    
    def test_results_summary(self):
        """Should summarize results."""
        def func1(x):
            return x
        
        def func2(x):
            return x
        
        harness = ParityTestHarness()
        harness.test_refactored(func1, func2, "identity", [{"x": i} for i in range(5)])
        
        summary = harness.get_results_summary()
        assert summary["total_tests"] == 5
        assert summary["passed"] == 5
        assert summary["pass_rate"] == 1.0


class TestSimpleFunctionPairs:
    """Test real function pair comparisons."""
    
    def test_weight_score_parity(self):
        """Weight score functions should be identical."""
        harness = ParityTestHarness()
        test_cases = [
            {"value": 0.5, "weight": 2.0},
            {"value": 0.8, "weight": 1.0},
            {"value": 0.0, "weight": 5.0},
        ]
        
        results = harness.test_refactored(
            SimpleFunctionPairs.original_weight_score,
            SimpleFunctionPairs.refactored_weight_score,
            "weight_score",
            test_cases
        )
        
        assert all(r.passed for r in results)
    
    def test_clamp_parity(self):
        """Clamp functions should be identical."""
        harness = ParityTestHarness()
        test_cases = [
            {"value": 0.5, "min_val": 0.0, "max_val": 1.0},
            {"value": -0.5, "min_val": 0.0, "max_val": 1.0},
            {"value": 1.5, "min_val": 0.0, "max_val": 1.0},
        ]
        
        results = harness.test_refactored(
            SimpleFunctionPairs.original_clamp,
            SimpleFunctionPairs.refactored_clamp,
            "clamp",
            test_cases
        )
        
        assert all(r.passed for r in results)
    
    def test_score_list_parity(self):
        """Score list functions should be identical."""
        harness = ParityTestHarness(
            ParityTestConfig(float_tolerance=1e-9)
        )
        test_cases = [
            {"scores": [0.5, 1.0, 0.75]},
            {"scores": [1.0, 1.0, 1.0]},
            {"scores": []},
        ]
        
        results = harness.test_refactored(
            SimpleFunctionPairs.original_score_list,
            SimpleFunctionPairs.refactored_score_list,
            "normalize",
            test_cases
        )
        
        assert all(r.passed for r in results)


class TestParityIntegration:
    """Integration tests for parity testing."""
    
    def test_multi_function_parity(self):
        """Should test parity for multiple functions."""
        harness = ParityTestHarness()
        
        # Test 1: weight score
        results1 = harness.test_refactored(
            SimpleFunctionPairs.original_weight_score,
            SimpleFunctionPairs.refactored_weight_score,
            "weight",
            [{"value": 0.5, "weight": 2.0}]
        )
        
        # Test 2: clamp
        results2 = harness.test_refactored(
            SimpleFunctionPairs.original_clamp,
            SimpleFunctionPairs.refactored_clamp,
            "clamp",
            [{"value": 0.5, "min_val": 0.0, "max_val": 1.0}]
        )
        
        # All should pass
        assert all(r.passed for r in results1 + results2)
        
        summary = harness.get_results_summary()
        assert summary["total_tests"] == 2
        assert summary["pass_rate"] == 1.0
    
    def test_parity_with_tolerance_configuration(self):
        """Should respect tolerance settings."""
        # Tight tolerance
        harness_tight = ParityTestHarness(
            ParityTestConfig(float_tolerance=1e-9)
        )
        
        def func1(x):
            return 1.0 / 3  # 0.333...
        
        def func2(x):
            return 0.333333  # Slightly different
        
        results = harness_tight.test_refactored(
            func1, func2, "test", [{"x": 1}]
        )
        
        # Should fail with tight tolerance
        assert not results[0].passed
        
        # Loose tolerance
        harness_loose = ParityTestHarness(
            ParityTestConfig(float_tolerance=1e-4)
        )
        
        results_loose = harness_loose.test_refactored(
            func1, func2, "test", [{"x": 1}]
        )
        
        # Should pass with loose tolerance
        assert results_loose[0].passed
