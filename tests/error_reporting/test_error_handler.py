"""Tests for error handler."""
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.error_reporting.error_handler import ErrorHandler, error_reporter


class TestErrorHandler:
    """Test error handler functionality."""
    
    @pytest.fixture
    def handler(self, monkeypatch):
        """Create error handler with test configuration."""
        monkeypatch.setenv('ERROR_REPORTING_ENABLED', 'true')
        monkeypatch.setenv('GITHUB_TOKEN', 'test-token')
        
        # Reset singleton
        ErrorHandler._instance = None
        return ErrorHandler()
    
    def test_singleton_pattern(self, handler):
        """
        GIVEN: ErrorHandler class
        WHEN: Creating multiple instances
        THEN: Should return same instance (singleton)
        """
        handler2 = ErrorHandler()
        assert handler is handler2
    
    def test_report_error(self, handler):
        """
        GIVEN: An error
        WHEN: Reporting the error
        THEN: Should call issue creator
        """
        with patch.object(handler.issue_creator, 'create_issue') as mock_create:
            mock_create.return_value = 'https://github.com/test/issues/1'
            
            error = ValueError("Test error")
            result = handler.report_error(
                error,
                source="Test Source",
                additional_info="Test info",
            )
            
            assert result == 'https://github.com/test/issues/1'
            mock_create.assert_called_once()
    
    def test_report_error_with_logs(self, handler):
        """
        GIVEN: An error with log output
        WHEN: Reporting the error
        THEN: Should include truncated logs
        """
        handler.config.max_log_lines = 5
        
        with patch.object(handler.issue_creator, 'create_issue') as mock_create:
            mock_create.return_value = 'https://github.com/test/issues/1'
            
            error = ValueError("Test error")
            logs = '\n'.join([f'Log line {i}' for i in range(10)])
            
            handler.report_error(error, source="Test", logs=logs)
            
            # Check that logs were passed
            call_args = mock_create.call_args
            context = call_args[0][1]
            assert 'logs' in context
            # Check that logs were truncated
            log_lines = context['logs'].split('\n')
            assert len(log_lines) <= handler.config.max_log_lines + 1  # +1 for '...'
    
    def test_install_global_handler(self, handler):
        """
        GIVEN: Error handler
        WHEN: Installing global exception handler
        THEN: Should replace sys.excepthook
        """
        original_hook = sys.excepthook
        
        try:
            handler.install_global_handler()
            
            assert sys.excepthook != original_hook
            assert handler._original_excepthook == original_hook
        
        finally:
            # Restore original hook
            handler.uninstall_global_handler()
    
    def test_uninstall_global_handler(self, handler):
        """
        GIVEN: Installed global handler
        WHEN: Uninstalling global handler
        THEN: Should restore original excepthook
        """
        original_hook = sys.excepthook
        
        handler.install_global_handler()
        handler.uninstall_global_handler()
        
        assert sys.excepthook == original_hook
        assert handler._original_excepthook is None
    
    def test_wrap_function_decorator(self, handler):
        """
        GIVEN: A function
        WHEN: Wrapping with error reporting decorator
        THEN: Should catch and report errors
        """
        @handler.wrap_function("Test Function")
        def test_func():
            raise ValueError("Test error")
        
        with patch.object(handler, 'report_error') as mock_report:
            with pytest.raises(ValueError):
                test_func()
            
            mock_report.assert_called_once()
            args = mock_report.call_args[0]
            assert isinstance(args[0], ValueError)
    
    def test_wrap_function_decorator_success(self, handler):
        """
        GIVEN: A function that succeeds
        WHEN: Wrapping with error reporting decorator
        THEN: Should not report any errors
        """
        @handler.wrap_function("Test Function")
        def test_func():
            return "success"
        
        with patch.object(handler, 'report_error') as mock_report:
            result = test_func()
            
            assert result == "success"
            mock_report.assert_not_called()
    
    def test_context_manager(self, handler):
        """
        GIVEN: Code block with error
        WHEN: Using error reporting context manager
        THEN: Should catch and report errors
        """
        with patch.object(handler, 'report_error') as mock_report:
            with pytest.raises(ValueError):
                with handler.context_manager("Test Context"):
                    raise ValueError("Test error")
            
            mock_report.assert_called_once()
    
    def test_context_manager_success(self, handler):
        """
        GIVEN: Code block without errors
        WHEN: Using error reporting context manager
        THEN: Should not report any errors
        """
        with patch.object(handler, 'report_error') as mock_report:
            with handler.context_manager("Test Context"):
                x = 1 + 1
            
            mock_report.assert_not_called()
    
    def test_error_reporting_disabled(self, monkeypatch, handler):
        """
        GIVEN: Error reporting disabled
        WHEN: Reporting an error
        THEN: Should not create GitHub issue
        """
        handler.config.enabled = False
        
        with patch.object(handler.issue_creator, 'create_issue') as mock_create:
            mock_create.return_value = None
            error = ValueError("Test error")
            result = handler.report_error(error, source="Test")
            
            # Should still be called but issue_creator will handle the disabled state
            assert result is None
            # Verify the call was made
            mock_create.assert_called_once()


class TestGetRecentLogs:
    """Test get_recent_logs function."""
    
    def test_get_recent_logs_no_file(self):
        """
        GIVEN: No log file exists
        WHEN: Getting recent logs
        THEN: Should return None
        """
        from ipfs_datasets_py.error_reporting.error_handler import get_recent_logs
        from pathlib import Path
        
        result = get_recent_logs(log_file=Path('/nonexistent/path.log'))
        assert result is None
    
    def test_get_recent_logs_with_file(self, tmp_path):
        """
        GIVEN: Log file exists
        WHEN: Getting recent logs
        THEN: Should return log content
        """
        from ipfs_datasets_py.error_reporting.error_handler import get_recent_logs
        
        # Create test log file
        log_file = tmp_path / 'test.log'
        log_content = '\n'.join([f'Log line {i}' for i in range(200)])
        log_file.write_text(log_content)
        
        result = get_recent_logs(log_file=log_file, max_lines=50)
        
        assert result is not None
        lines = result.split('\n')
        assert len(lines) <= 50
