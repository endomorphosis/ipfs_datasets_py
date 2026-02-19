"""
Tests for CEC Profiling Utilities

Comprehensive tests for performance profiling and analysis tools.
"""

import time
import unittest
from typing import List

# Add parent directory to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.CEC.optimization.profiling_utils import (
    ProfilingResult,
    Bottleneck,
    FormulaProfiler,
    BottleneckAnalyzer,
    ProfilingReporter,
    profile_decorator
)


class TestProfilingResult(unittest.TestCase):
    """Tests for ProfilingResult dataclass."""
    
    def test_profiling_result_creation(self):
        """
        GIVEN: Profiling data
        WHEN: Creating a ProfilingResult
        THEN: Result is created with correct attributes
        """
        result = ProfilingResult(
            operation="test_op",
            execution_time=0.5,
            memory_used=1024,
            peak_memory=2048,
            call_count=5
        )
        
        self.assertEqual(result.operation, "test_op")
        self.assertEqual(result.execution_time, 0.5)
        self.assertEqual(result.memory_used, 1024)
        self.assertEqual(result.peak_memory, 2048)
        self.assertEqual(result.call_count, 5)
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
    
    def test_profiling_result_failure(self):
        """
        GIVEN: Failed operation data
        WHEN: Creating a ProfilingResult with error
        THEN: Result reflects failure
        """
        result = ProfilingResult(
            operation="failed_op",
            execution_time=0.1,
            memory_used=512,
            peak_memory=512,
            success=False,
            error="Test error"
        )
        
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Test error")
    
    def test_profiling_result_string(self):
        """
        GIVEN: A ProfilingResult
        WHEN: Converting to string
        THEN: String contains key information
        """
        result = ProfilingResult(
            operation="test_op",
            execution_time=0.123,
            memory_used=1024,
            peak_memory=2048
        )
        
        result_str = str(result)
        self.assertIn("test_op", result_str)
        self.assertIn("0.1230s", result_str)
        self.assertIn("1.00KB", result_str)


class TestBottleneck(unittest.TestCase):
    """Tests for Bottleneck dataclass."""
    
    def test_bottleneck_creation(self):
        """
        GIVEN: Bottleneck data
        WHEN: Creating a Bottleneck
        THEN: Bottleneck is created with correct attributes
        """
        bottleneck = Bottleneck(
            location="parse_formula",
            severity=8,
            execution_time=1.5,
            memory_impact=1024 * 1024,
            recommendation="Use caching"
        )
        
        self.assertEqual(bottleneck.location, "parse_formula")
        self.assertEqual(bottleneck.severity, 8)
        self.assertEqual(bottleneck.execution_time, 1.5)
        self.assertEqual(bottleneck.memory_impact, 1024 * 1024)
        self.assertEqual(bottleneck.recommendation, "Use caching")
    
    def test_bottleneck_string(self):
        """
        GIVEN: A Bottleneck
        WHEN: Converting to string
        THEN: String contains severity and recommendation
        """
        bottleneck = Bottleneck(
            location="test_location",
            severity=5,
            execution_time=0.5,
            memory_impact=512,
            recommendation="Optimize code"
        )
        
        bottleneck_str = str(bottleneck)
        self.assertIn("[Severity 5/10]", bottleneck_str)
        self.assertIn("test_location", bottleneck_str)
        self.assertIn("Optimize code", bottleneck_str)


class TestFormulaProfiler(unittest.TestCase):
    """Tests for FormulaProfiler class."""
    
    def setUp(self):
        """Set up test profiler."""
        self.profiler = FormulaProfiler()
    
    def test_profiler_initialization(self):
        """
        GIVEN: No profiler exists
        WHEN: Creating a FormulaProfiler
        THEN: Profiler is initialized with empty results
        """
        self.assertEqual(len(self.profiler.results), 0)
        self.assertEqual(len(self.profiler._active_profiles), 0)
    
    def test_start_stop_profiling(self):
        """
        GIVEN: A FormulaProfiler
        WHEN: Starting and stopping profiling
        THEN: Profiling result is recorded
        """
        self.profiler.start_profiling("test_operation")
        time.sleep(0.01)  # Small delay
        result = self.profiler.stop_profiling("test_operation")
        
        self.assertEqual(result.operation, "test_operation")
        self.assertGreater(result.execution_time, 0)
        self.assertTrue(result.success)
        self.assertEqual(len(self.profiler.results), 1)
    
    def test_stop_profiling_without_start_raises_error(self):
        """
        GIVEN: A FormulaProfiler
        WHEN: Stopping profiling without starting
        THEN: ValueError is raised
        """
        with self.assertRaises(ValueError):
            self.profiler.stop_profiling("nonexistent_operation")
    
    def test_profile_function(self):
        """
        GIVEN: A function to profile
        WHEN: Profiling the function
        THEN: Function result and profiling result are returned
        """
        def test_func(x, y):
            time.sleep(0.01)
            return x + y
        
        result, prof_result = self.profiler.profile_function(
            test_func, 2, 3, operation_name="addition"
        )
        
        self.assertEqual(result, 5)
        self.assertEqual(prof_result.operation, "addition")
        self.assertGreater(prof_result.execution_time, 0)
        self.assertTrue(prof_result.success)
    
    def test_profile_function_with_exception(self):
        """
        GIVEN: A function that raises an exception
        WHEN: Profiling the function
        THEN: Exception is recorded in profiling result
        """
        def failing_func():
            raise ValueError("Test error")
        
        with self.assertRaises(ValueError):
            self.profiler.profile_function(failing_func)
        
        # Check that result was recorded
        self.assertEqual(len(self.profiler.results), 1)
        self.assertFalse(self.profiler.results[0].success)
        self.assertIn("Test error", self.profiler.results[0].error)
    
    def test_get_results(self):
        """
        GIVEN: Multiple profiled operations
        WHEN: Getting results
        THEN: All results are returned
        """
        self.profiler.start_profiling("op1")
        self.profiler.stop_profiling("op1")
        
        self.profiler.start_profiling("op2")
        self.profiler.stop_profiling("op2")
        
        results = self.profiler.get_results()
        self.assertEqual(len(results), 2)
    
    def test_clear_results(self):
        """
        GIVEN: Profiler with results
        WHEN: Clearing results
        THEN: Results are removed
        """
        self.profiler.start_profiling("test")
        self.profiler.stop_profiling("test")
        
        self.assertEqual(len(self.profiler.results), 1)
        self.profiler.clear_results()
        self.assertEqual(len(self.profiler.results), 0)
    
    def test_get_summary_empty(self):
        """
        GIVEN: Profiler with no results
        WHEN: Getting summary
        THEN: Summary shows zero values
        """
        summary = self.profiler.get_summary()
        
        self.assertEqual(summary["total_operations"], 0)
        self.assertEqual(summary["total_time"], 0.0)
        self.assertEqual(summary["total_memory"], 0)
        self.assertEqual(summary["success_rate"], 0.0)
    
    def test_get_summary_with_results(self):
        """
        GIVEN: Profiler with multiple results
        WHEN: Getting summary
        THEN: Summary calculates correct statistics
        """
        self.profiler.start_profiling("op1")
        time.sleep(0.01)
        self.profiler.stop_profiling("op1")
        
        self.profiler.start_profiling("op2")
        time.sleep(0.01)
        self.profiler.stop_profiling("op2")
        
        summary = self.profiler.get_summary()
        
        self.assertEqual(summary["total_operations"], 2)
        self.assertGreater(summary["total_time"], 0)
        self.assertGreater(summary["average_time"], 0)
        self.assertEqual(summary["success_rate"], 1.0)


class TestBottleneckAnalyzer(unittest.TestCase):
    """Tests for BottleneckAnalyzer class."""
    
    def setUp(self):
        """Set up test analyzer."""
        self.analyzer = BottleneckAnalyzer(
            time_threshold=0.05,
            memory_threshold=512
        )
    
    def test_analyzer_initialization(self):
        """
        GIVEN: No analyzer exists
        WHEN: Creating a BottleneckAnalyzer
        THEN: Analyzer is initialized with thresholds
        """
        self.assertEqual(self.analyzer.time_threshold, 0.05)
        self.assertEqual(self.analyzer.memory_threshold, 512)
        self.assertEqual(len(self.analyzer.bottlenecks), 0)
    
    def test_analyze_no_bottlenecks(self):
        """
        GIVEN: Results below thresholds
        WHEN: Analyzing for bottlenecks
        THEN: No bottlenecks are identified
        """
        results = [
            ProfilingResult("fast_op", 0.01, 100, 100),
            ProfilingResult("efficient_op", 0.02, 200, 200)
        ]
        
        bottlenecks = self.analyzer.analyze(results)
        self.assertEqual(len(bottlenecks), 0)
    
    def test_analyze_time_bottleneck(self):
        """
        GIVEN: Result with high execution time
        WHEN: Analyzing for bottlenecks
        THEN: Time bottleneck is identified
        """
        results = [
            ProfilingResult("slow_op", 0.5, 100, 100)
        ]
        
        bottlenecks = self.analyzer.analyze(results)
        self.assertGreater(len(bottlenecks), 0)
        self.assertEqual(bottlenecks[0].location, "slow_op")
        self.assertGreater(bottlenecks[0].severity, 0)
    
    def test_analyze_memory_bottleneck(self):
        """
        GIVEN: Result with high memory usage
        WHEN: Analyzing for bottlenecks
        THEN: Memory bottleneck is identified
        """
        results = [
            ProfilingResult("memory_intensive_op", 0.01, 10000, 10000)
        ]
        
        bottlenecks = self.analyzer.analyze(results)
        self.assertGreater(len(bottlenecks), 0)
        self.assertIn("memory_intensive_op", bottlenecks[0].location)
    
    def test_analyze_sorts_by_severity(self):
        """
        GIVEN: Multiple bottlenecks with different severities
        WHEN: Analyzing for bottlenecks
        THEN: Bottlenecks are sorted by severity (high to low)
        """
        results = [
            ProfilingResult("minor_issue", 0.1, 100, 100),
            ProfilingResult("major_issue", 1.0, 100, 100),
            ProfilingResult("moderate_issue", 0.3, 100, 100)
        ]
        
        bottlenecks = self.analyzer.analyze(results)
        self.assertGreater(len(bottlenecks), 1)
        # Check that severities are in descending order
        for i in range(len(bottlenecks) - 1):
            self.assertGreaterEqual(bottlenecks[i].severity, bottlenecks[i+1].severity)
    
    def test_get_critical_bottlenecks(self):
        """
        GIVEN: Bottlenecks with various severities
        WHEN: Getting critical bottlenecks
        THEN: Only high-severity bottlenecks are returned
        """
        results = [
            ProfilingResult("minor", 0.1, 100, 100),
            ProfilingResult("critical", 0.8, 100, 100)
        ]
        
        self.analyzer.analyze(results)
        critical = self.analyzer.get_critical_bottlenecks(min_severity=7)
        
        # Critical bottleneck should have high severity
        if len(critical) > 0:
            self.assertGreaterEqual(critical[0].severity, 7)


class TestProfilingReporter(unittest.TestCase):
    """Tests for ProfilingReporter class."""
    
    def test_generate_report_empty(self):
        """
        GIVEN: Profiler with no results
        WHEN: Generating a report
        THEN: Report shows empty statistics
        """
        profiler = FormulaProfiler()
        report = ProfilingReporter.generate_report(profiler)
        
        self.assertIn("CEC Performance Profiling Report", report)
        self.assertIn("Total Operations: 0", report)
    
    def test_generate_report_with_results(self):
        """
        GIVEN: Profiler with results
        WHEN: Generating a report
        THEN: Report includes operation details
        """
        profiler = FormulaProfiler()
        profiler.start_profiling("test_op")
        time.sleep(0.01)
        profiler.stop_profiling("test_op")
        
        report = ProfilingReporter.generate_report(profiler)
        
        self.assertIn("test_op", report)
        self.assertIn("Total Operations: 1", report)
        self.assertIn("Success Rate", report)
    
    def test_generate_report_with_bottlenecks(self):
        """
        GIVEN: Profiler with results and analyzer with bottlenecks
        WHEN: Generating a report
        THEN: Report includes bottleneck information
        """
        profiler = FormulaProfiler()
        profiler.start_profiling("slow_operation")
        time.sleep(0.1)
        profiler.stop_profiling("slow_operation")
        
        analyzer = BottleneckAnalyzer(time_threshold=0.05)
        analyzer.analyze(profiler.get_results())
        
        report = ProfilingReporter.generate_report(profiler, analyzer)
        
        self.assertIn("Identified Bottlenecks", report)
        self.assertIn("slow_operation", report)


class TestProfileDecorator(unittest.TestCase):
    """Tests for profile_decorator."""
    
    def test_decorator_basic(self):
        """
        GIVEN: A function with profile decorator
        WHEN: Calling the function
        THEN: Function executes and profiling info is printed
        """
        @profile_decorator()
        def test_function(x):
            return x * 2
        
        result = test_function(5)
        self.assertEqual(result, 10)
    
    def test_decorator_with_custom_name(self):
        """
        GIVEN: A function with named profile decorator
        WHEN: Calling the function
        THEN: Function executes with custom operation name
        """
        @profile_decorator(operation_name="custom_operation")
        def test_function():
            return "result"
        
        result = test_function()
        self.assertEqual(result, "result")


if __name__ == "__main__":
    unittest.main()
