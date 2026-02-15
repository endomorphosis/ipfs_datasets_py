import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock
import threading
import time

# Import the actual classes under test
from batch_processor._batch_result import BatchResult
from core._processing_result import ProcessingResult


class TestBatchResultInitialization(unittest.TestCase):
    """Test BatchResult initialization and post_init behavior."""
    
    def test_initialize_empty_batch_result(self):
        """
        GIVEN no arguments
        WHEN BatchResult() is instantiated
        THEN expect:
            - results is empty list
            - statistics is empty dict
            - start_time is set to current time
            - end_time is None
            - total_files is 0
            - successful_files is 0
            - failed_files is 0
        """
        before_creation = datetime.now()
        batch_result = BatchResult()
        after_creation = datetime.now()
        
        self.assertEqual(batch_result.results, [])
        self.assertEqual(batch_result.statistics, {})
        self.assertIsNone(batch_result.end_time)
        self.assertEqual(batch_result.total_files, 0)
        self.assertEqual(batch_result.successful_files, 0)
        self.assertEqual(batch_result.failed_files, 0)
        
        # Check start_time is within reasonable range
        self.assertGreaterEqual(batch_result.start_time, before_creation)
        self.assertLessEqual(batch_result.start_time, after_creation)
    
    def test_initialize_with_results(self):
        """
        GIVEN a list of ProcessingResult objects
        WHEN BatchResult(results=results_list) is instantiated
        THEN expect:
            - results contains the provided list
            - total_files equals len(results)
            - successful_files equals count of successful results
            - failed_files equals count of failed results
        """
        # Create mock ProcessingResult objects
        successful_result1 = Mock(spec=ProcessingResult)
        successful_result1.success = True
        successful_result1.input_path = "/path/to/file1.txt"
        
        successful_result2 = Mock(spec=ProcessingResult)
        successful_result2.success = True
        successful_result2.input_path = "/path/to/file2.txt"
        
        failed_result = Mock(spec=ProcessingResult)
        failed_result.success = False
        failed_result.input_path = "/path/to/file3.txt"
        
        results_list = [successful_result1, successful_result2, failed_result]
        
        batch_result = BatchResult(results=results_list)
        
        self.assertEqual(batch_result.results, results_list)
        self.assertEqual(batch_result.total_files, 3)
        self.assertEqual(batch_result.successful_files, 2)
        self.assertEqual(batch_result.failed_files, 1)
    
    def test_initialize_with_statistics(self):
        """
        GIVEN a dictionary of statistics
        WHEN BatchResult(statistics=stats_dict) is instantiated
        THEN expect:
            - statistics contains the provided dictionary
            - Other fields initialized to defaults
        """
        stats_dict = {"custom_metric": 42, "processing_mode": "batch"}
        
        batch_result = BatchResult(statistics=stats_dict)
        
        self.assertEqual(batch_result.statistics, stats_dict)
        self.assertEqual(batch_result.results, [])
        self.assertIsNone(batch_result.end_time)
        self.assertEqual(batch_result.total_files, 0)
    
    def test_initialize_with_custom_start_time(self):
        """
        GIVEN a specific datetime object
        WHEN BatchResult(start_time=custom_time) is instantiated
        THEN expect:
            - start_time equals the provided datetime
            - end_time remains None
        """
        custom_time = datetime(2024, 1, 15, 10, 30, 0)
        
        batch_result = BatchResult(start_time=custom_time)
        
        self.assertEqual(batch_result.start_time, custom_time)
        self.assertIsNone(batch_result.end_time)


class TestBatchResultAddResult(unittest.TestCase):
    """Test adding results to BatchResult."""
    
    def setUp(self):
        self.batch_result = BatchResult()
    
    def test_add_single_successful_result(self):
        """
        GIVEN an empty BatchResult
        WHEN add_result is called with a successful ProcessingResult
        THEN expect:
            - results list contains the new result
            - total_files increments to 1
            - successful_files increments to 1
            - failed_files remains 0
        """
        successful_result = Mock(spec=ProcessingResult)
        successful_result.success = True
        successful_result.file_path = "/path/to/success.txt"
        
        self.batch_result.add_result(successful_result)
        
        self.assertIn(successful_result, self.batch_result.results)
        self.assertEqual(self.batch_result.total_files, 1)
        self.assertEqual(self.batch_result.successful_files, 1)
        self.assertEqual(self.batch_result.failed_files, 0)
    
    def test_add_single_failed_result(self):
        """
        GIVEN an empty BatchResult
        WHEN add_result is called with a failed ProcessingResult
        THEN expect:
            - results list contains the new result
            - total_files increments to 1
            - successful_files remains 0
            - failed_files increments to 1
        """
        failed_result = Mock(spec=ProcessingResult)
        failed_result.success = False
        failed_result.file_path = "/path/to/failed.txt"
        
        self.batch_result.add_result(failed_result)
        
        self.assertIn(failed_result, self.batch_result.results)
        self.assertEqual(self.batch_result.total_files, 1)
        self.assertEqual(self.batch_result.successful_files, 0)
        self.assertEqual(self.batch_result.failed_files, 1)
    
    def test_add_multiple_mixed_results(self):
        """
        GIVEN an empty BatchResult
        WHEN add_result is called multiple times with mix of successful/failed results
        THEN expect:
            - results list contains all results in order
            - total_files equals total number of results
            - successful_files equals count of successful results
            - failed_files equals count of failed results
        """
        results = []
        
        # Add 3 successful results
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = True
            result.file_path = f"/path/to/success{i}.txt"
            results.append(result)
            self.batch_result.add_result(result)
        
        # Add 2 failed results
        for i in range(2):
            result = Mock(spec=ProcessingResult)
            result.success = False
            result.file_path = f"/path/to/failed{i}.txt"
            results.append(result)
            self.batch_result.add_result(result)
        
        self.assertEqual(self.batch_result.results, results)
        self.assertEqual(self.batch_result.total_files, 5)
        self.assertEqual(self.batch_result.successful_files, 3)
        self.assertEqual(self.batch_result.failed_files, 2)
    
    def test_add_result_updates_statistics(self):
        """
        GIVEN a BatchResult with existing statistics
        WHEN add_result is called
        THEN expect:
            - statistics are updated appropriately
            - Existing statistics are preserved
        """
        self.batch_result.statistics = {"initial_stat": "preserved"}
        
        result = Mock(spec=ProcessingResult)
        result.success = True
        result.file_path = "/path/to/file.txt"
        
        self.batch_result.add_result(result)
        
        # Check that existing statistics are preserved
        self.assertIn("initial_stat", self.batch_result.statistics)
        self.assertEqual(self.batch_result.statistics["initial_stat"], "preserved")


class TestBatchResultComplete(unittest.TestCase):
    """Test completing batch processing."""
    
    def setUp(self):
        self.batch_result = BatchResult()
    
    def test_complete_sets_end_time(self):
        """
        GIVEN a BatchResult with end_time=None
        WHEN mark_as_complete() is called
        THEN expect:
            - end_time is set to current time
            - end_time is after start_time
        """
        start_time = self.batch_result.start_time
        before_complete = datetime.now()
        
        self.batch_result.mark_as_complete()
        
        after_complete = datetime.now()
        
        self.assertIsNotNone(self.batch_result.end_time)
        self.assertGreaterEqual(self.batch_result.end_time, before_complete)
        self.assertLessEqual(self.batch_result.end_time, after_complete)
        self.assertGreaterEqual(self.batch_result.end_time, start_time)
    
    def test_complete_when_already_completed(self):
        """
        GIVEN a BatchResult with end_time already set
        WHEN mark_as_complete() is called again
        THEN expect:
            - end_time remains unchanged
            - No errors raised
        """
        # Complete once
        self.batch_result.mark_as_complete()
        original_end_time = self.batch_result.end_time

        # Complete again
        self.batch_result.mark_as_complete()

        self.assertEqual(self.batch_result.end_time, original_end_time)
    
    def test_complete_updates_statistics(self):
        """
        GIVEN a BatchResult with results
        WHEN mark_as_complete() is called
        THEN expect:
            - statistics includes duration_seconds
            - statistics includes success_rate
            - Other relevant statistics are calculated
        """
        # Add some results first
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = i % 2 == 0  # Mix of success/failure
            result.file_path = f"/path/to/file{i}.txt"
            self.batch_result.add_result(result)
        
        self.batch_result.mark_as_complete()
        
        # Check that statistics were updated
        self.assertIn("duration_seconds", self.batch_result.statistics)
        self.assertIn("success_rate", self.batch_result.statistics)
        self.assertIsInstance(self.batch_result.statistics["duration_seconds"], float)
        self.assertIsInstance(self.batch_result.statistics["success_rate"], float)
        
        # Verify the success rate calculation
        expected_success_rate = (2 / 3) * 100  # 2 out of 3 files successful
        self.assertAlmostEqual(self.batch_result.statistics["success_rate"], expected_success_rate, places=1)


class TestBatchResultGetSummary(unittest.TestCase):
    """Test getting batch processing summary."""
    
    def test_get_summary_empty_batch(self):
        """
        GIVEN an empty BatchResult
        WHEN get_summary() is called
        THEN expect:
            - Dictionary with all zero counts
            - start_time included
            - end_time is None
            - No errors on empty data
        """
        batch_result = BatchResult()
        summary = batch_result.get_summary()
        
        self.assertIsInstance(summary, dict)
        self.assertEqual(summary["total_files"], 0)
        self.assertEqual(summary["successful_files"], 0)
        self.assertEqual(summary["failed_files"], 0)
        self.assertIn("start_time", summary)
        self.assertIsNone(summary.get("end_time"))
    
    def test_get_summary_completed_batch(self):
        """
        GIVEN a completed BatchResult with mixed results
        WHEN get_summary() is called
        THEN expect:
            - Dictionary with accurate counts
            - Duration calculated correctly
            - Success rate percentage included
            - All relevant statistics included
        """
        batch_result = BatchResult()
        
        # Add mixed results
        for i in range(5):
            result = Mock(spec=ProcessingResult)
            result.success = i < 3  # 3 successful, 2 failed
            result.file_path = f"/path/to/file{i}.txt"
            batch_result.add_result(result)
        
        batch_result.mark_as_complete()
        summary = batch_result.get_summary()
        
        self.assertEqual(summary["total_files"], 5)
        self.assertEqual(summary["successful_files"], 3)
        self.assertEqual(summary["failed_files"], 2)
        self.assertIn("duration", summary)
        self.assertIn("success_rate", summary)
        self.assertEqual(summary["success_rate"], 60.0)  # 3/5 * 100
    
    def test_get_summary_in_progress_batch(self):
        """
        GIVEN a BatchResult with results but not completed
        WHEN get_summary() is called
        THEN expect:
            - Dictionary with current counts
            - Duration calculated from start to now
            - Indication that processing is ongoing
        """
        batch_result = BatchResult()
        
        # Add some results but don't complete
        result = Mock(spec=ProcessingResult)
        result.success = True
        result.file_path = "/path/to/file.txt"
        batch_result.add_result(result)
        
        summary = batch_result.get_summary()
        
        self.assertEqual(summary["total_files"], 1)
        self.assertIn("duration_seconds", summary)
        self.assertIn("status", summary)
        self.assertEqual(summary["status"], "in_progress")


class TestBatchResultGetFailedFiles(unittest.TestCase):
    """Test retrieving failed files."""
    
    def test_get_failed_files_when_none_failed(self):
        """
        GIVEN a BatchResult with only successful results
        WHEN get_failed_files() is called
        THEN expect:
            - Empty list returned
            - No errors
        """
        batch_result = BatchResult()
        
        # Add only successful results
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = True
            result.file_path = f"/path/to/success{i}.txt"
            batch_result.add_result(result)
        
        failed_files = batch_result.get_failed_files()
        
        self.assertEqual(failed_files, [])
        self.assertIsInstance(failed_files, list)
    
    def test_get_failed_files_returns_all_failed(self):
        """
        GIVEN a BatchResult with multiple failed results
        WHEN get_failed_files() is called
        THEN expect:
            - List contains all failed file paths
            - Order matches insertion order
            - No successful files included
        """
        batch_result = BatchResult()
        failed_paths = ["/path/to/failed1.txt", "/path/to/failed2.txt", "/path/to/failed3.txt"]
        
        # Add only failed results
        for path in failed_paths:
            result = Mock(spec=ProcessingResult)
            result.success = False
            result.file_path = path
            batch_result.add_result(result)
        
        failed_files = batch_result.get_failed_files()
        
        self.assertEqual(failed_files, failed_paths)
        self.assertEqual(len(failed_files), 3)
    
    def test_get_failed_files_with_mixed_results(self):
        """
        GIVEN a BatchResult with mix of successful and failed results
        WHEN get_failed_files() is called
        THEN expect:
            - List contains only failed file paths
            - Count matches failed_files attribute
        """
        batch_result = BatchResult()
        failed_paths = []
        
        # Add mixed results
        for i in range(5):
            result = Mock(spec=ProcessingResult)
            result.success = i % 2 == 0  # Alternate success/failure
            result.file_path = f"/path/to/file{i}.txt"
            
            if not result.success:
                failed_paths.append(result.file_path)
            
            batch_result.add_result(result)
        
        failed_files = batch_result.get_failed_files()
        
        self.assertEqual(failed_files, failed_paths)
        self.assertEqual(len(failed_files), batch_result.failed_files)


class TestBatchResultGetSuccessfulFiles(unittest.TestCase):
    """Test retrieving successful files."""
    
    def test_get_successful_files_when_none_succeeded(self):
        """
        GIVEN a BatchResult with only failed results
        WHEN get_successful_files() is called
        THEN expect:
            - Empty list returned
            - No errors
        """
        batch_result = BatchResult()
        
        # Add only failed results
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = False
            result.file_path = f"/path/to/failed{i}.txt"
            batch_result.add_result(result)
        
        successful_files = batch_result.get_successful_files()
        
        self.assertEqual(successful_files, [])
        self.assertIsInstance(successful_files, list)
    
    def test_get_successful_files_returns_all_successful(self):
        """
        GIVEN a BatchResult with multiple successful results
        WHEN get_successful_files() is called
        THEN expect:
            - List contains all successful file paths
            - Order matches insertion order
            - No failed files included
        """
        batch_result = BatchResult()
        successful_paths = ["/path/to/success1.txt", "/path/to/success2.txt", "/path/to/success3.txt"]
        
        # Add only successful results
        for path in successful_paths:
            result = Mock(spec=ProcessingResult)
            result.success = True
            result.file_path = path
            batch_result.add_result(result)
        
        successful_files = batch_result.get_successful_files()
        
        self.assertEqual(successful_files, successful_paths)
        self.assertEqual(len(successful_files), 3)
    
    def test_get_successful_files_with_mixed_results(self):
        """
        GIVEN a BatchResult with mix of successful and failed results
        WHEN get_successful_files() is called
        THEN expect:
            - List contains only successful file paths
            - Count matches successful_files attribute
        """
        batch_result = BatchResult()
        successful_paths = []
        
        # Add mixed results
        for i in range(5):
            result = Mock(spec=ProcessingResult)
            result.success = i % 2 == 0  # Alternate success/failure
            result.file_path = f"/path/to/file{i}.txt"
            
            if result.success:
                successful_paths.append(result.file_path)
            
            batch_result.add_result(result)
        
        successful_files = batch_result.get_successful_files()
        
        self.assertEqual(successful_files, successful_paths)
        self.assertEqual(len(successful_files), batch_result.successful_files)


class TestBatchResultToDict(unittest.TestCase):
    """Test dictionary conversion."""
    
    def test_to_dict_empty_batch(self):
        """
        GIVEN an empty BatchResult
        WHEN to_dict() is called
        THEN expect:
            - Dictionary with all expected keys
            - results is empty list
            - statistics is empty dict
            - Datetime objects serialized to strings
        """
        batch_result = BatchResult()
        result_dict = batch_result.to_dict()
        
        expected_keys = ["results", "statistics", "start_time", "end_time", 
                        "total_files", "successful_files", "failed_files"]
        
        for key in expected_keys:
            self.assertIn(key, result_dict)
        
        self.assertEqual(result_dict["results"], [])
        self.assertEqual(result_dict["statistics"], {})
        self.assertIsInstance(result_dict["start_time"], str)
        self.assertIsNone(result_dict["end_time"])
        self.assertEqual(result_dict["total_files"], 0)
    
    def test_to_dict_with_results(self):
        """
        GIVEN a BatchResult with multiple results
        WHEN to_dict() is called
        THEN expect:
            - Dictionary contains all results as dicts
            - Each result properly converted
            - All attributes included
        """
        batch_result = BatchResult()
        
        # Mock ProcessingResult to_dict method
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = i % 2 == 0
            result.file_path = f"/path/to/file{i}.txt"
            result.to_dict.return_value = {
                "success": result.success,
                "input_path": result.file_path,
                "output_path": f"/output/file{i}.txt"
            }
            batch_result.add_result(result)
        
        result_dict = batch_result.to_dict()
        
        self.assertEqual(len(result_dict["results"]), 3)
        self.assertIsInstance(result_dict["results"], list)
        
        # Check each result was converted to dict
        for i, result_data in enumerate(result_dict["results"]):
            self.assertIsInstance(result_data, dict)
            self.assertIn("success", result_data)
            self.assertIn("input_path", result_data)
    
    def test_to_dict_completed_batch(self):
        """
        GIVEN a completed BatchResult
        WHEN to_dict() is called
        THEN expect:
            - end_time included and serialized
            - Duration calculated and included
            - All statistics preserved
        """
        batch_result = BatchResult()
        batch_result.mark_as_complete()
        
        result_dict = batch_result.to_dict()
        
        self.assertIsNotNone(result_dict["end_time"])
        self.assertIsInstance(result_dict["end_time"], str)
        self.assertIn("duration_seconds", result_dict["statistics"])
    
    def test_to_dict_preserves_custom_statistics(self):
        """
        GIVEN a BatchResult with custom statistics
        WHEN to_dict() is called
        THEN expect:
            - All custom statistics included
            - No data loss or modification
            - Nested structures preserved
        """
        batch_result = BatchResult()
        custom_stats = {
            "custom_metric": 42,
            "nested_data": {"level1": {"level2": "value"}},
            "list_data": [1, 2, 3]
        }
        batch_result.statistics.update(custom_stats)
        
        result_dict = batch_result.to_dict()
        
        for key, value in custom_stats.items():
            self.assertIn(key, result_dict["statistics"])
            self.assertEqual(result_dict["statistics"][key], value)


class TestBatchResultStringRepresentation(unittest.TestCase):
    """Test string representation."""
    
    def test_str_empty_batch(self):
        """
        GIVEN an empty BatchResult
        WHEN str() is called
        THEN expect:
            - Human-readable summary
            - Shows zero counts
            - Indicates no processing done
        """
        batch_result = BatchResult()
        str_repr = str(batch_result)
        
        self.assertIsInstance(str_repr, str)
        self.assertIn("0", str_repr)  # Should show zero counts
        self.assertTrue(len(str_repr) > 0)
    
    def test_str_in_progress_batch(self):
        """
        GIVEN a BatchResult with results but not completed
        WHEN str() is called
        THEN expect:
            - Shows current progress
            - Indicates "in progress" status
            - Includes file counts
        """
        batch_result = BatchResult()
        
        # Add some results but don't complete
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = i < 2  # 2 successful, 1 failed
            result.file_path = f"/path/to/file{i}.txt"
            batch_result.add_result(result)
        
        str_repr = str(batch_result)
        
        self.assertIn("3", str_repr)  # Total files
        self.assertIn("2", str_repr)  # Successful files
        self.assertIn("1", str_repr)  # Failed files
        self.assertIn("progress", str_repr.lower())
    
    def test_str_completed_batch(self):
        """
        GIVEN a completed BatchResult
        WHEN str() is called
        THEN expect:
            - Shows final summary
            - Includes duration
            - Shows success rate
            - Lists counts for all categories
        """
        batch_result = BatchResult()
        
        # Add results and complete
        for i in range(4):
            result = Mock(spec=ProcessingResult)
            result.success = i < 3  # 3 successful, 1 failed
            result.file_path = f"/path/to/file{i}.txt"
            batch_result.add_result(result)
        
        batch_result.mark_as_complete()
        str_repr = str(batch_result)
        
        self.assertIn("4", str_repr)  # Total files
        self.assertIn("3", str_repr)  # Successful files
        self.assertIn("1", str_repr)  # Failed files
        self.assertIn("duration", str_repr.lower())
        self.assertIn("75", str_repr)  # Success rate percentage
    
    def test_str_with_all_failures(self):
        """
        GIVEN a BatchResult where all files failed
        WHEN str() is called
        THEN expect:
            - Clear indication of complete failure
            - Shows 0% success rate
            - Appropriate formatting
        """
        batch_result = BatchResult()
        
        # Add only failed results
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = False
            result.file_path = f"/path/to/failed{i}.txt"
            batch_result.add_result(result)
        
        batch_result.mark_as_complete()
        str_repr = str(batch_result)
        
        self.assertIn("3", str_repr)  # Total files
        self.assertIn("0", str_repr)  # Successful files
        self.assertIn("0%", str_repr)  # Success rate


class TestBatchResultEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""
    
    def test_add_none_result(self):
        """
        GIVEN a BatchResult
        WHEN add_result(None) is called
        THEN expect:
            - TypeError or graceful handling
            - BatchResult state unchanged
            - Clear error message if exception
        """
        batch_result = BatchResult()
        initial_count = batch_result.total_files
        
        with self.assertRaises((TypeError, AttributeError, ValueError)):
            batch_result.add_result(None)
        
        # State should be unchanged
        self.assertEqual(batch_result.total_files, initial_count)
    
    def test_add_result_with_missing_attributes(self):
        """
        GIVEN a BatchResult and ProcessingResult missing required attributes
        WHEN add_result is called
        THEN expect:
            - Graceful handling or clear error
            - Partial data handled appropriately
        """
        batch_result = BatchResult()
        
        # Create result without required attributes
        incomplete_result = MagicMock(spec=ProcessingResult)
        # Don't set success or input_path attributes
        
        with self.assertRaises((AttributeError, ValueError)):
            batch_result.add_result(incomplete_result)
    
    def test_very_large_batch_performance(self):
        """
        GIVEN a BatchResult
        WHEN adding 10,000+ results
        THEN expect:
            - No memory issues
            - Reasonable performance
            - Accurate counts maintained
        """
        batch_result = BatchResult()
        num_results = 1000  # Reduced for test speed
        
        start_time = time.time()
        
        for i in range(num_results):
            result = Mock(spec=ProcessingResult)
            result.success = i % 2 == 0
            result.file_path = f"/path/to/file{i}.txt"
            batch_result.add_result(result)
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Should complete in reasonable time (less than 10 seconds)
        self.assertLess(processing_time, 10.0)
        
        # Counts should be accurate
        self.assertEqual(batch_result.total_files, num_results)
        self.assertEqual(batch_result.successful_files, num_results // 2)
        self.assertEqual(batch_result.failed_files, num_results // 2)
    
    def test_concurrent_add_operations(self):
        """
        GIVEN a BatchResult and multiple threads
        WHEN add_result is called concurrently
        THEN expect:
            - Thread-safe operation or clear documentation
            - No lost results
            - Accurate final counts
        """
        batch_result = BatchResult()
        num_threads = 10
        results_per_thread = 100
        
        def add_results(thread_id):
            for i in range(results_per_thread):
                result = Mock(spec=ProcessingResult)
                result.success = (thread_id + i) % 2 == 0
                result.file_path = f"/path/to/thread{thread_id}_file{i}.txt"
                batch_result.add_result(result)
        
        threads = []
        for i in range(num_threads):
            thread = threading.Thread(target=add_results, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        expected_total = num_threads * results_per_thread
        self.assertEqual(batch_result.total_files, expected_total)
        self.assertEqual(len(batch_result.results), expected_total)
    
    def test_serialization_with_non_serializable_statistics(self):
        """
        GIVEN a BatchResult with lambda/function in statistics
        WHEN to_dict() is called
        THEN expect:
            - Graceful handling of non-serializable items
            - Other data preserved
            - Clear indication of what was omitted
        """
        batch_result = BatchResult()
        
        # Add non-serializable items to statistics
        batch_result.statistics = {
            "normal_data": "serializable",
            "lambda_func": lambda x: x * 2,
            "nested_normal": {"key": "value"},
            "function": len
        }
        
        # Should either handle gracefully or raise clear error
        try:
            result_dict = batch_result.to_dict()
            # If it doesn't raise an error, check that normal data is preserved
            self.assertIn("normal_data", result_dict["statistics"])
            self.assertIn("nested_normal", result_dict["statistics"])
        except (TypeError, ValueError) as e:
            # Clear error message expected
            self.assertIsInstance(str(e), str)
            self.assertTrue(len(str(e)) > 0)


if __name__ == "__main__":
    unittest.main()
