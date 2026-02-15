"""
Test suite for batch_processor/_batch_result.py converted from unittest to pytest.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock
import threading
import time

# Import the actual classes under test
from batch_processor._batch_result import BatchResult
from core._processing_result import ProcessingResult


# Test Constants
EXPECTED_EMPTY_LIST = []
EXPECTED_EMPTY_DICT = {}
EXPECTED_ZERO_COUNT = 0
EXPECTED_SUCCESS_RATE_ZERO = 0.0
EXPECTED_SUCCESS_RATE_SIXTY = 60.0
EXPECTED_SUCCESS_RATE_SEVENTY_FIVE = 75.0
EXPECTED_TOTAL_FILES_THREE = 3
EXPECTED_TOTAL_FILES_FIVE = 5
EXPECTED_SUCCESSFUL_FILES_TWO = 2
EXPECTED_SUCCESSFUL_FILES_THREE = 3
EXPECTED_FAILED_FILES_ONE = 1
EXPECTED_FAILED_FILES_TWO = 2
SUCCESS_FILE_PATH = "/path/to/success.txt"
FAILED_FILE_PATH = "/path/to/failed.txt"
PERFORMANCE_TIME_LIMIT = 10.0
LARGE_BATCH_SIZE = 1000
CONCURRENT_THREADS = 10
RESULTS_PER_THREAD = 100


@pytest.fixture
def batch_result():
    """Create a fresh BatchResult instance for each test."""
    return BatchResult()


@pytest.fixture
def successful_result():
    """Create a mock successful ProcessingResult."""
    result = Mock(spec=ProcessingResult)
    result.success = True
    result.file_path = SUCCESS_FILE_PATH
    result.input_path = SUCCESS_FILE_PATH
    return result


@pytest.fixture
def failed_result():
    """Create a mock failed ProcessingResult."""
    result = Mock(spec=ProcessingResult)
    result.success = False
    result.file_path = FAILED_FILE_PATH
    result.input_path = FAILED_FILE_PATH
    return result


@pytest.fixture
def multiple_successful_results():
    """Create multiple mock successful ProcessingResults."""
    results = []
    for i in range(EXPECTED_SUCCESSFUL_FILES_THREE):
        result = Mock(spec=ProcessingResult)
        result.success = True
        result.file_path = f"/path/to/success{i}.txt"
        results.append(result)
    return results


@pytest.fixture
def multiple_failed_results():
    """Create multiple mock failed ProcessingResults."""
    results = []
    for i in range(EXPECTED_FAILED_FILES_TWO):
        result = Mock(spec=ProcessingResult)
        result.success = False
        result.file_path = f"/path/to/failed{i}.txt"
        results.append(result)
    return results


@pytest.fixture
def mixed_results(multiple_successful_results, multiple_failed_results):
    """Create a mix of successful and failed results."""
    return multiple_successful_results + multiple_failed_results


@pytest.mark.unit
class TestBatchResultInitialization:
    """
    Tests for BatchResult initialization behavior.
    Class under test: BatchResult.__init__
    """
    
    def test_when_no_args_provided_then_results_is_empty_list(self):
        """
        GIVEN no arguments
        WHEN BatchResult is instantiated
        THEN expect results attribute equals empty list
        """
        batch_result = BatchResult()
        
        assert batch_result.results == EXPECTED_EMPTY_LIST, f"Expected {EXPECTED_EMPTY_LIST}, got {batch_result.results}"

    def test_when_no_args_provided_then_statistics_is_empty_dict(self):
        """
        GIVEN no arguments
        WHEN BatchResult is instantiated
        THEN expect statistics attribute equals empty dict
        """
        batch_result = BatchResult()
        
        assert batch_result.statistics == EXPECTED_EMPTY_DICT, f"Expected {EXPECTED_EMPTY_DICT}, got {batch_result.statistics}"

    def test_when_no_args_provided_then_end_time_is_none(self):
        """
        GIVEN no arguments
        WHEN BatchResult is instantiated
        THEN expect end_time attribute equals None
        """
        batch_result = BatchResult()
        
        assert batch_result.end_time is None, f"Expected None, got {batch_result.end_time}"

    def test_when_no_args_provided_then_total_files_is_zero(self):
        """
        GIVEN no arguments
        WHEN BatchResult is instantiated
        THEN expect total_files attribute equals zero
        """
        batch_result = BatchResult()
        
        assert batch_result.total_files == EXPECTED_ZERO_COUNT, f"Expected {EXPECTED_ZERO_COUNT}, got {batch_result.total_files}"

    def test_when_no_args_provided_then_successful_files_is_zero(self):
        """
        GIVEN no arguments
        WHEN BatchResult is instantiated
        THEN expect successful_files attribute equals zero
        """
        batch_result = BatchResult()
        
        assert batch_result.successful_files == EXPECTED_ZERO_COUNT, f"Expected {EXPECTED_ZERO_COUNT}, got {batch_result.successful_files}"

    def test_when_no_args_provided_then_failed_files_is_zero(self):
        """
        GIVEN no arguments
        WHEN BatchResult is instantiated
        THEN expect failed_files attribute equals zero
        """
        batch_result = BatchResult()
        
        assert batch_result.failed_files == EXPECTED_ZERO_COUNT, f"Expected {EXPECTED_ZERO_COUNT}, got {batch_result.failed_files}"

    def test_when_no_args_provided_then_start_time_is_recent(self):
        """
        GIVEN no arguments
        WHEN BatchResult is instantiated
        THEN expect start_time attribute is within last minute
        """
        before_creation = datetime.now()
        batch_result = BatchResult()
        after_creation = datetime.now()
        
        assert batch_result.start_time >= before_creation, f"Expected start_time >= {before_creation}, got {batch_result.start_time}"
        assert batch_result.start_time <= after_creation, f"Expected start_time <= {after_creation}, got {batch_result.start_time}"
    
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
        
        assert batch_result.results == results_list
        assert batch_result.total_files == 3
        assert batch_result.successful_files == 2
        assert batch_result.failed_files == 1
    
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
        
        assert batch_result.statistics == stats_dict
        assert batch_result.results == []
        assert batch_result.end_time is None
        assert batch_result.total_files == 0
    
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
        
        assert batch_result.start_time == custom_time
        assert batch_result.end_time is None


@pytest.mark.unit
class TestBatchResultAddResult:
    """Test adding results to BatchResult."""
    
    def test_add_single_successful_result(self, batch_result, successful_result):
        """
        GIVEN an empty BatchResult
        WHEN add_result is called with a successful ProcessingResult
        THEN expect:
            - results list contains the new result
            - total_files increments to 1
            - successful_files increments to 1
            - failed_files remains 0
        """
        batch_result.add_result(successful_result)
        
        assert successful_result in batch_result.results
        assert batch_result.total_files == 1
        assert batch_result.successful_files == 1
        assert batch_result.failed_files == 0
    
    def test_add_single_failed_result(self, batch_result, failed_result):
        """
        GIVEN an empty BatchResult
        WHEN add_result is called with a failed ProcessingResult
        THEN expect:
            - results list contains the new result
            - total_files increments to 1
            - successful_files remains 0
            - failed_files increments to 1
        """
        batch_result.add_result(failed_result)
        
        assert failed_result in batch_result.results
        assert batch_result.total_files == 1
        assert batch_result.successful_files == 0
        assert batch_result.failed_files == 1
    
    def test_when_multiple_results_added_then_results_list_contains_all_results(self, batch_result, mixed_results):
        """
        GIVEN an empty BatchResult and mix of successful/failed results
        WHEN add_result is called multiple times with mixed results
        THEN expect results list contains all results in order
        """
        for result in mixed_results:
            batch_result.add_result(result)
        
        assert batch_result.results == mixed_results, f"Expected {mixed_results}, got {batch_result.results}"

    def test_when_multiple_results_added_then_total_files_equals_count(self, batch_result, mixed_results):
        """
        GIVEN an empty BatchResult and mix of successful/failed results
        WHEN add_result is called multiple times with mixed results
        THEN expect total_files equals total number of results
        """
        for result in mixed_results:
            batch_result.add_result(result)
        
        assert batch_result.total_files == EXPECTED_TOTAL_FILES_FIVE, f"Expected {EXPECTED_TOTAL_FILES_FIVE}, got {batch_result.total_files}"

    def test_when_multiple_results_added_then_successful_files_equals_successful_count(self, batch_result, mixed_results):
        """
        GIVEN an empty BatchResult and mix of successful/failed results  
        WHEN add_result is called multiple times with mixed results
        THEN expect successful_files equals count of successful results
        """
        for result in mixed_results:
            batch_result.add_result(result)
        
        assert batch_result.successful_files == EXPECTED_SUCCESSFUL_FILES_THREE, f"Expected {EXPECTED_SUCCESSFUL_FILES_THREE}, got {batch_result.successful_files}"

    def test_when_multiple_results_added_then_failed_files_equals_failed_count(self, batch_result, mixed_results):
        """
        GIVEN an empty BatchResult and mix of successful/failed results
        WHEN add_result is called multiple times with mixed results
        THEN expect failed_files equals count of failed results
        """
        for result in mixed_results:
            batch_result.add_result(result)
        
        assert batch_result.failed_files == EXPECTED_FAILED_FILES_TWO, f"Expected {EXPECTED_FAILED_FILES_TWO}, got {batch_result.failed_files}"
    
    def test_add_result_updates_statistics(self, batch_result):
        """
        GIVEN a BatchResult with existing statistics
        WHEN add_result is called
        THEN expect:
            - statistics are updated appropriately
            - Existing statistics are preserved
        """
        batch_result.statistics = {"initial_stat": "preserved"}
        
        result = Mock(spec=ProcessingResult)
        result.success = True
        result.file_path = "/path/to/file.txt"
        
        batch_result.add_result(result)
        
        # Check that existing statistics are preserved
        assert "initial_stat" in batch_result.statistics
        assert batch_result.statistics["initial_stat"] == "preserved"


@pytest.mark.unit
class TestBatchResultComplete:
    """Test completing batch processing."""
    
    def test_complete_sets_end_time(self, batch_result):
        """
        GIVEN a BatchResult with end_time=None
        WHEN mark_as_complete() is called
        THEN expect:
            - end_time is set to current time
            - end_time is after start_time
        """
        start_time = batch_result.start_time
        before_complete = datetime.now()
        
        batch_result.mark_as_complete()
        
        after_complete = datetime.now()
        
        assert batch_result.end_time is not None
        assert batch_result.end_time >= before_complete
        assert batch_result.end_time <= after_complete
        assert batch_result.end_time >= start_time
    
    def test_complete_when_already_completed(self, batch_result):
        """
        GIVEN a BatchResult with end_time already set
        WHEN mark_as_complete() is called again
        THEN expect:
            - end_time remains unchanged
            - No errors raised
        """
        # Complete once
        batch_result.mark_as_complete()
        original_end_time = batch_result.end_time

        # Complete again
        batch_result.mark_as_complete()

        assert batch_result.end_time == original_end_time
    
    def test_complete_updates_statistics(self, batch_result):
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
            batch_result.add_result(result)
        
        batch_result.mark_as_complete()
        
        # Check that statistics were updated
        assert "duration_seconds" in batch_result.statistics
        assert "success_rate" in batch_result.statistics
        assert isinstance(batch_result.statistics["duration_seconds"], float)
        assert isinstance(batch_result.statistics["success_rate"], float)
        
        # Verify the success rate calculation
        expected_success_rate = (2 / 3) * 100  # 2 out of 3 files successful
        assert pytest.approx(batch_result.statistics["success_rate"], abs=0.1) == expected_success_rate


@pytest.mark.unit
class TestBatchResultGetSummary:
    """Test getting batch processing summary."""
    
    def test_get_summary_empty_batch(self, batch_result):
        """
        GIVEN an empty BatchResult
        WHEN get_summary() is called
        THEN expect:
            - Dictionary with all zero counts
            - start_time included
            - end_time is None
            - No errors on empty data
        """
        summary = batch_result.get_summary()
        
        assert isinstance(summary, dict)
        assert summary["total_files"] == 0
        assert summary["successful_files"] == 0
        assert summary["failed_files"] == 0
        assert "start_time" in summary
        assert summary.get("end_time") is None
    
    def test_get_summary_completed_batch(self, batch_result):
        """
        GIVEN a completed BatchResult with mixed results
        WHEN get_summary() is called
        THEN expect:
            - Dictionary with accurate counts
            - Duration calculated correctly
            - Success rate percentage included
            - All relevant statistics included
        """
        # Add mixed results
        for i in range(5):
            result = Mock(spec=ProcessingResult)
            result.success = i < 3  # 3 successful, 2 failed
            result.file_path = f"/path/to/file{i}.txt"
            batch_result.add_result(result)
        
        batch_result.mark_as_complete()
        summary = batch_result.get_summary()
        
        assert summary["total_files"] == 5
        assert summary["successful_files"] == 3
        assert summary["failed_files"] == 2
        assert "duration" in summary
        assert "success_rate" in summary
        assert summary["success_rate"] == 60.0  # 3/5 * 100
    
    def test_get_summary_in_progress_batch(self, batch_result):
        """
        GIVEN a BatchResult with results but not completed
        WHEN get_summary() is called
        THEN expect:
            - Dictionary with current counts
            - Duration calculated from start to now
            - Indication that processing is ongoing
        """
        # Add some results but don't complete
        result = Mock(spec=ProcessingResult)
        result.success = True
        result.file_path = "/path/to/file.txt"
        batch_result.add_result(result)
        
        summary = batch_result.get_summary()
        
        assert summary["total_files"] == 1
        assert "duration_seconds" in summary
        assert "status" in summary
        assert summary["status"] == "in_progress"


@pytest.mark.unit
class TestBatchResultGetFailedFiles:
    """Test retrieving failed files."""
    
    def test_get_failed_files_when_none_failed(self, batch_result):
        """
        GIVEN a BatchResult with only successful results
        WHEN get_failed_files() is called
        THEN expect:
            - Empty list returned
            - No errors
        """
        # Add only successful results
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = True
            result.file_path = f"/path/to/success{i}.txt"
            batch_result.add_result(result)
        
        failed_files = batch_result.get_failed_files()
        
        assert failed_files == []
        assert isinstance(failed_files, list)
    
    def test_get_failed_files_returns_all_failed(self, batch_result):
        """
        GIVEN a BatchResult with multiple failed results
        WHEN get_failed_files() is called
        THEN expect:
            - List contains all failed file paths
            - Order matches insertion order
            - No successful files included
        """
        failed_paths = ["/path/to/failed1.txt", "/path/to/failed2.txt", "/path/to/failed3.txt"]
        
        # Add only failed results
        for path in failed_paths:
            result = Mock(spec=ProcessingResult)
            result.success = False
            result.file_path = path
            batch_result.add_result(result)
        
        failed_files = batch_result.get_failed_files()
        
        assert failed_files == failed_paths
        assert len(failed_files) == 3
    
    def test_get_failed_files_with_mixed_results(self, batch_result):
        """
        GIVEN a BatchResult with mix of successful and failed results
        WHEN get_failed_files() is called
        THEN expect:
            - List contains only failed file paths
            - Count matches failed_files attribute
        """
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
        
        assert failed_files == failed_paths
        assert len(failed_files) == batch_result.failed_files


@pytest.mark.unit
class TestBatchResultGetSuccessfulFiles:
    """Test retrieving successful files."""
    
    def test_get_successful_files_when_none_succeeded(self, batch_result):
        """
        GIVEN a BatchResult with only failed results
        WHEN get_successful_files() is called
        THEN expect:
            - Empty list returned
            - No errors
        """
        # Add only failed results
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = False
            result.file_path = f"/path/to/failed{i}.txt"
            batch_result.add_result(result)
        
        successful_files = batch_result.get_successful_files()
        
        assert successful_files == []
        assert isinstance(successful_files, list)
    
    def test_get_successful_files_returns_all_successful(self, batch_result):
        """
        GIVEN a BatchResult with multiple successful results
        WHEN get_successful_files() is called
        THEN expect:
            - List contains all successful file paths
            - Order matches insertion order
            - No failed files included
        """
        successful_paths = ["/path/to/success1.txt", "/path/to/success2.txt", "/path/to/success3.txt"]
        
        # Add only successful results
        for path in successful_paths:
            result = Mock(spec=ProcessingResult)
            result.success = True
            result.file_path = path
            batch_result.add_result(result)
        
        successful_files = batch_result.get_successful_files()
        
        assert successful_files == successful_paths
        assert len(successful_files) == 3
    
    def test_get_successful_files_with_mixed_results(self, batch_result):
        """
        GIVEN a BatchResult with mix of successful and failed results
        WHEN get_successful_files() is called
        THEN expect:
            - List contains only successful file paths
            - Count matches successful_files attribute
        """
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
        
        assert successful_files == successful_paths
        assert len(successful_files) == batch_result.successful_files


@pytest.mark.unit
class TestBatchResultToDict:
    """Test dictionary conversion."""
    
    def test_to_dict_empty_batch(self, batch_result):
        """
        GIVEN an empty BatchResult
        WHEN to_dict() is called
        THEN expect:
            - Dictionary with all expected keys
            - results is empty list
            - statistics is empty dict
            - Datetime objects serialized to strings
        """
        result_dict = batch_result.to_dict()
        
        expected_keys = ["results", "statistics", "start_time", "end_time", 
                        "total_files", "successful_files", "failed_files"]
        
        for key in expected_keys:
            assert key in result_dict
        
        assert result_dict["results"] == []
        assert result_dict["statistics"] == {}
        assert isinstance(result_dict["start_time"], str)
        assert result_dict["end_time"] is None
        assert result_dict["total_files"] == 0
    
    def test_to_dict_with_results(self, batch_result):
        """
        GIVEN a BatchResult with multiple results
        WHEN to_dict() is called
        THEN expect:
            - Dictionary contains all results as dicts
            - Each result properly converted
            - All attributes included
        """
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
        
        assert len(result_dict["results"]) == 3
        assert isinstance(result_dict["results"], list)
        
        # Check each result was converted to dict
        for i, result_data in enumerate(result_dict["results"]):
            assert isinstance(result_data, dict)
            assert "success" in result_data
            assert "input_path" in result_data
    
    def test_to_dict_completed_batch(self, batch_result):
        """
        GIVEN a completed BatchResult
        WHEN to_dict() is called
        THEN expect:
            - end_time included and serialized
            - Duration calculated and included
            - All statistics preserved
        """
        batch_result.mark_as_complete()
        
        result_dict = batch_result.to_dict()
        
        assert result_dict["end_time"] is not None
        assert isinstance(result_dict["end_time"], str)
        assert "duration_seconds" in result_dict["statistics"]
    
    def test_to_dict_preserves_custom_statistics(self, batch_result):
        """
        GIVEN a BatchResult with custom statistics
        WHEN to_dict() is called
        THEN expect:
            - All custom statistics included
            - No data loss or modification
            - Nested structures preserved
        """
        custom_stats = {
            "custom_metric": 42,
            "nested_data": {"level1": {"level2": "value"}},
            "list_data": [1, 2, 3]
        }
        batch_result.statistics.update(custom_stats)
        
        result_dict = batch_result.to_dict()
        
        for key, value in custom_stats.items():
            assert key in result_dict["statistics"]
            assert result_dict["statistics"][key] == value


@pytest.mark.unit
class TestBatchResultStringRepresentation:
    """Test string representation."""
    
    def test_str_empty_batch(self, batch_result):
        """
        GIVEN an empty BatchResult
        WHEN str() is called
        THEN expect:
            - Human-readable summary
            - Shows zero counts
            - Indicates no processing done
        """
        str_repr = str(batch_result)
        
        assert isinstance(str_repr, str)
        assert "0" in str_repr  # Should show zero counts
        assert len(str_repr) > 0
    
    def test_str_in_progress_batch(self, batch_result):
        """
        GIVEN a BatchResult with results but not completed
        WHEN str() is called
        THEN expect:
            - Shows current progress
            - Indicates "in progress" status
            - Includes file counts
        """
        # Add some results but don't complete
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = i < 2  # 2 successful, 1 failed
            result.file_path = f"/path/to/file{i}.txt"
            batch_result.add_result(result)
        
        str_repr = str(batch_result)
        
        assert "3" in str_repr  # Total files
        assert "2" in str_repr  # Successful files
        assert "1" in str_repr  # Failed files
        assert "progress" in str_repr.lower()
    
    def test_str_completed_batch(self, batch_result):
        """
        GIVEN a completed BatchResult
        WHEN str() is called
        THEN expect:
            - Shows final summary
            - Includes duration
            - Shows success rate
            - Lists counts for all categories
        """
        # Add results and complete
        for i in range(4):
            result = Mock(spec=ProcessingResult)
            result.success = i < 3  # 3 successful, 1 failed
            result.file_path = f"/path/to/file{i}.txt"
            batch_result.add_result(result)
        
        batch_result.mark_as_complete()
        str_repr = str(batch_result)
        
        assert "4" in str_repr  # Total files
        assert "3" in str_repr  # Successful files
        assert "1" in str_repr  # Failed files
        assert "duration" in str_repr.lower()
        assert "75" in str_repr  # Success rate percentage
    
    def test_str_with_all_failures(self, batch_result):
        """
        GIVEN a BatchResult where all files failed
        WHEN str() is called
        THEN expect:
            - Clear indication of complete failure
            - Shows 0% success rate
            - Appropriate formatting
        """
        # Add only failed results
        for i in range(3):
            result = Mock(spec=ProcessingResult)
            result.success = False
            result.file_path = f"/path/to/failed{i}.txt"
            batch_result.add_result(result)
        
        batch_result.mark_as_complete()
        str_repr = str(batch_result)
        
        assert "3" in str_repr  # Total files
        assert "0" in str_repr  # Successful files
        assert "0%" in str_repr  # Success rate


@pytest.mark.unit
class TestBatchResultEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_add_none_result(self, batch_result):
        """
        GIVEN a BatchResult
        WHEN add_result(None) is called
        THEN expect:
            - TypeError or graceful handling
            - BatchResult state unchanged
            - Clear error message if exception
        """
        initial_count = batch_result.total_files
        
        with pytest.raises((TypeError, AttributeError, ValueError)):
            batch_result.add_result(None)
        
        # State should be unchanged
        assert batch_result.total_files == initial_count
    
    def test_add_result_with_missing_attributes(self, batch_result):
        """
        GIVEN a BatchResult and ProcessingResult missing required attributes
        WHEN add_result is called
        THEN expect:
            - Graceful handling or clear error
            - Partial data handled appropriately
        """
        # Create result without required attributes
        incomplete_result = MagicMock(spec=ProcessingResult)
        # Don't set success or input_path attributes
        
        with pytest.raises((AttributeError, ValueError)):
            batch_result.add_result(incomplete_result)
    
    @pytest.mark.slow
    def test_very_large_batch_performance(self, batch_result):
        """
        GIVEN a BatchResult
        WHEN adding 1000 results
        THEN expect:
            - No memory issues
            - Reasonable performance
            - Accurate counts maintained
        """
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
        assert processing_time < 10.0
        
        # Counts should be accurate
        assert batch_result.total_files == num_results
        assert batch_result.successful_files == num_results // 2
        assert batch_result.failed_files == num_results // 2
    
    def test_concurrent_add_operations(self, batch_result):
        """
        GIVEN a BatchResult and multiple threads
        WHEN add_result is called concurrently
        THEN expect:
            - Thread-safe operation or clear documentation
            - No lost results
            - Accurate final counts
        """
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
        assert batch_result.total_files == expected_total
        assert len(batch_result.results) == expected_total
    
    def test_serialization_with_non_serializable_statistics(self, batch_result):
        """
        GIVEN a BatchResult with lambda/function in statistics
        WHEN to_dict() is called
        THEN expect:
            - Graceful handling of non-serializable items
            - Other data preserved
            - Clear indication of what was omitted
        """
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
            assert "normal_data" in result_dict["statistics"]
            assert "nested_normal" in result_dict["statistics"]
        except (TypeError, ValueError) as e:
            # Clear error message expected
            assert isinstance(str(e), str)
            assert len(str(e)) > 0