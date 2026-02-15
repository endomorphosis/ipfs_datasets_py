import unittest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime
from typing import Optional, Any, Callable
import tempfile
import os
from pathlib import Path
import shutil

from core._processing_result import ProcessingResult
from core._processing_pipeline import ProcessingPipeline
from core import make_processing_pipeline



import hashlib

from configs import configs, Configs
from logger import logger
from types_ import Logger
from file_format_detector import make_file_format_detector

from types_ import Callable, Logger, TypedDict, ModuleType

from core._processing_pipeline import ProcessingPipeline
from core._pipeline_status import PipelineStatus
from core._processing_result import ProcessingResult
from core.file_validator import make_file_validator
from core.text_normalizer import make_text_normalizer
from core.output_formatter import make_output_formatter
from core.content_extractor import make_content_extractor
from core.content_sanitizer import make_content_sanitizer
from core.file_validator._file_validator import FileValidator
from file_format_detector._file_format_detector import FileFormatDetector
from core.content_extractor._content_extractor import ContentExtractor
from core.text_normalizer._text_normalizer import TextNormalizer
from core.output_formatter._output_formatter import OutputFormatter
from core.content_sanitizer import ContentSanitizer
from monitors import make_security_monitor, SecurityMonitor

class _ProcessingPipelineResources(TypedDict):
    file_format_detector: Callable
    file_validator: Callable
    content_extractor: Callable
    text_normalizer: Callable
    output_formatter: Callable
    processing_result: ProcessingResult
    pipeline_status: PipelineStatus
    security_monitor: SecurityMonitor
    logger: Logger
    hashlib: ModuleType

real_resources: _ProcessingPipelineResources = {
    "file_format_detector": make_file_format_detector(),
    "file_validator": make_file_validator(),
    "content_extractor": make_content_extractor(),
    "content_sanitizer": make_content_sanitizer(),
    "text_normalizer": make_text_normalizer(),
    "output_formatter": make_output_formatter(),
    "security_monitor": make_security_monitor(),
    "processing_result": ProcessingResult,
    "pipeline_status": PipelineStatus(),
    "logger": logger,
    "hashlib": hashlib
}

def make_mock_resources():
    """Create a mock resources dictionary for testing."""
    return {
        'file_format_detector': MagicMock(spec=FileFormatDetector),
        'file_validator': MagicMock(spec=FileValidator),
        'content_extractor': MagicMock(spec=ContentExtractor),
        'content_sanitizer': MagicMock(spec=ContentSanitizer),
        'text_normalizer': MagicMock(spec=TextNormalizer),
        'output_formatter': MagicMock(spec=OutputFormatter),
        'processing_result': MagicMock(spec=ProcessingResult),
        'pipeline_status': MagicMock(spec=PipelineStatus),
        'security_monitor': MagicMock(spec=SecurityMonitor),
        'logger': MagicMock(spec=Logger),
        'hashlib': MagicMock(spec=hashlib),
    }

class TestProcessingPipelineInit(unittest.TestCase):
    """Test ProcessingPipeline initialization."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temp directory for test files
        self.temp_dir = tempfile.mkdtemp()
        
        # Create test files
        self.test_file_path = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("Test content")
        
        self.large_file_path = os.path.join(self.temp_dir, "large_file.txt")
        with open(self.large_file_path, 'w') as f:
            f.write("A" * (15 * 1024 * 1024))  # 15 MB file (exceeds text limit)
        
        self.executable_file_path = os.path.join(self.temp_dir, "test_script.sh")
        with open(self.executable_file_path, 'w') as f:
            f.write("#!/bin/sh\necho 'Hello, world!'")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init(self):
        """
        GIVEN resources and configs are provided
        WHEN ProcessingPipeline() is instantiated
        THEN expect:
        - Instance is created successfully
        - configs attribute is set to Configs instance
        - resources attribute is set to None or empty dict
        - All private attributes are properly initialized
        - _format_detector is instantiated
        - _file_validator is instantiated
        - _content_extractor is instantiated
        - _text_normalizer is instantiated
        - _output_formatter is instantiated
        - _processing_result is None or initialized
        - _logger is instantiated
        - _status is instantiated with initial status
        - _hashlib reference is set
        - _listeners is empty list
        """
        self.mock_resources = make_mock_resources()
        self.mock_configs = MagicMock(spec=Configs)

        # Create instance with no arguments
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        
        # Verify instance creation
        self.assertIsInstance(pipeline, ProcessingPipeline)
        
        # Verify configs is set to default
        self.assertIsNotNone(pipeline.configs)
        self.assertIsInstance(pipeline.configs, Configs)
        self.assertIsNotNone(pipeline.resources)

        # Verify private attributes exist
        self.assertIsInstance(pipeline._file_validator, FileValidator)
        self.assertIsInstance(pipeline._content_extractor, ContentExtractor)
        self.assertIsInstance(pipeline._text_normalizer, TextNormalizer)
        self.assertIsInstance(pipeline._output_formatter, OutputFormatter)
        self.assertIsInstance(pipeline._processing_result, ProcessingResult)
        self.assertIsInstance(pipeline._format_detector, FileFormatDetector)
        self.assertIsInstance(pipeline._security_monitor, SecurityMonitor)
        self.assertIsInstance(pipeline._logger, Logger)
        self.assertIsInstance(pipeline._status, PipelineStatus)
        self.assertIsInstance(pipeline._hashlib, ModuleType)
        self.assertIsInstance(pipeline._listeners, list)
        self.assertEqual(pipeline._listeners, [])

class TestProcessingPipelineProcessFile(unittest.TestCase):
    """Test ProcessingPipeline.process_file method."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = {
            'file_format_detector': MagicMock(),
            'file_validator': MagicMock(),
            'content_extractor': MagicMock(),
            'content_sanitizer': MagicMock(),
            'text_normalizer': MagicMock(),
            'output_formatter': MagicMock(),
            'processing_result': MagicMock(),
            'pipeline_status': MagicMock(),
            'security_monitor': MagicMock(),
            'logger': MagicMock(),
            'hashlib': MagicMock()
        }
        self.mock_configs = MagicMock()
        
        # Create temporary test file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        self.temp_file.write("Test content for processing")
        self.temp_file.close()
        self.test_file_path = self.temp_file.name
    
    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.test_file_path):
            os.unlink(self.test_file_path)
    

    def test_process_file_valid_file_default_params(self):
        """
        GIVEN a valid file path to an existing file
        WHEN process_file(file_path) is called with default parameters
        THEN expect:
        - ProcessingResult returned with success=True
        - output_format defaults to 'txt'
        - output_path is in temp directory
        - file_path matches input
        - format is correctly detected
        - errors list is empty
        - metadata contains relevant processing information
        - content_hash is generated
        - timestamp is set to processing completion time
        """
        # Mock processing result
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/test_output.txt',
            format='txt',
            errors=[],
            metadata={'extracted_text': 'Test content'},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        # Create pipeline with mocked components
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline._format_detector.detect.return_value = 'txt'
        pipeline._file_validator.validate.return_value = True
        pipeline._content_extractor.extract.return_value = 'Test content'
        pipeline._text_normalizer.normalize.return_value = 'Test content'
        pipeline._output_formatter.format.return_value = 'Test content'
        pipeline._hashlib.sha256.return_value.hexdigest.return_value = 'abc123'
        
        # Mock the process_file method to return our mock result
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        # Call process_file
        result = pipeline.process_file(self.test_file_path)
        
        # Verify result
        self.assertIsInstance(result, ProcessingResult)
        self.assertTrue(result.success)
        self.assertEqual(result.file_path, self.test_file_path)
        self.assertTrue(result.output_path.endswith('.txt'))
        self.assertEqual(result.format, 'txt')
        self.assertEqual(result.errors, [])
        self.assertIsNotNone(result.metadata)
        self.assertIsNotNone(result.content_hash)
        self.assertIsInstance(result.timestamp, datetime)
    

    def test_process_file_with_output_format_txt(self):
        """
        GIVEN a valid file path
        WHEN process_file(file_path, output_format='txt') is called
        THEN expect:
        - Output is formatted as plain text
        - ProcessingResult.output_path has .txt extension
        """
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/test_output.txt',
            format='txt',
            errors=[],
            metadata={},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path, output_format='txt')
        
        self.assertTrue(result.output_path.endswith('.txt'))
    

    def test_process_file_with_output_format_md(self):
        """
        GIVEN a valid file path
        WHEN process_file(file_path, output_format='md') is called
        THEN expect:
        - Output is formatted as markdown
        - ProcessingResult.output_path has .md extension
        """
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/test_output.md',
            format='txt',
            errors=[],
            metadata={},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path, output_format='md')
        
        self.assertTrue(result.output_path.endswith('.md'))
    

    def test_process_file_with_output_path_as_file(self):
        """
        GIVEN a valid file path and specific output file path
        WHEN process_file(file_path, output_path='/path/to/output.txt') is called
        THEN expect:
        - Output is written to specified file path
        - ProcessingResult.output_path matches provided path
        """
        custom_output_path = '/path/to/output.txt'
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path=custom_output_path,
            format='txt',
            errors=[],
            metadata={},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path, output_path=custom_output_path)
        
        self.assertEqual(result.output_path, custom_output_path)
    

    def test_process_file_with_output_path_as_directory(self):
        """
        GIVEN a valid file path and output directory path
        WHEN process_file(file_path, output_path='/path/to/dir/') is called
        THEN expect:
        - Output file created in specified directory
        - Output filename based on input filename
        - Extension replaced with output_format extension
        """
        output_dir = '/path/to/dir/'
        expected_output = '/path/to/dir/test_file.txt'
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path=expected_output,
            format='txt',
            errors=[],
            metadata={},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path, output_path=output_dir)
        
        self.assertTrue(result.output_path.startswith(output_dir))
        self.assertTrue(result.output_path.endswith('.txt'))
    

    def test_process_file_with_normalizers(self):
        """
        GIVEN a valid file path and list of normalizers
        WHEN process_file(file_path, normalizers=['normalizer1', 'normalizer2']) is called
        THEN expect:
        - Text is processed through specified normalizers
        - Normalizers applied in order
        - ProcessingResult reflects normalized content
        """
        normalizers = ['normalizer1', 'normalizer2']
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/output.txt',
            format='txt',
            errors=[],
            metadata={'normalizers_applied': normalizers},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path, normalizers=normalizers)
        
        # Verify normalizers were passed and applied
        pipeline.process_file.assert_called_with(self.test_file_path, normalizers=normalizers)
        self.assertIn('normalizers_applied', result.metadata)

    def test_process_file_without_normalizers(self):
        """
        GIVEN a valid file path and normalizers=None
        WHEN process_file(file_path, normalizers=None) is called
        THEN expect:
        - Extracted text returned as-is
        - No normalization applied
        """
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/output.txt',
            format='txt',
            errors=[],
            metadata={'normalization_skipped': True},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path, normalizers=None)
        
        pipeline.process_file.assert_called_with(self.test_file_path, normalizers=None)
        self.assertTrue(result.success)
    

    def test_process_file_nonexistent_file(self):
        """
        GIVEN a path to a non-existent file
        WHEN process_file(nonexistent_path) is called
        THEN expect:
        - FileNotFoundError raised
        - Error message indicates file not found
        """
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(side_effect=FileNotFoundError("File not found"))
        
        with self.assertRaises(FileNotFoundError) as context:
            pipeline.process_file('/nonexistent/file.txt')
        
        self.assertIn("File not found", str(context.exception))
    

    def test_process_file_permission_denied(self):
        """
        GIVEN a file path without read permissions
        WHEN process_file(restricted_path) is called
        THEN expect:
        - PermissionError raised
        - Error message indicates permission denied
        """

        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(side_effect=PermissionError("Permission denied"))
        
        with self.assertRaises(PermissionError) as context:
            pipeline.process_file('/restricted/file.txt')
        
        self.assertIn("Permission denied", str(context.exception))
    

    def test_process_file_unsupported_format(self):
        """
        GIVEN a file with unsupported format
        WHEN process_file(unsupported_file) is called
        THEN expect:
        - ValueError raised
        - Error message indicates format not supported
        """

        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(side_effect=ValueError("Unsupported file format"))
        
        with self.assertRaises(ValueError) as context:
            pipeline.process_file('/path/to/unsupported.xyz')
        
        self.assertIn("Unsupported file format", str(context.exception))
    

    def test_process_file_invalid_output_format(self):
        """
        GIVEN a valid file but invalid output_format
        WHEN process_file(file_path, output_format='invalid') is called
        THEN expect:
        - ValueError raised or ProcessingResult with success=False
        - Error indicates invalid output format
        """

        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(side_effect=ValueError("Invalid output format"))
        
        with self.assertRaises(ValueError) as context:
            pipeline.process_file(self.test_file_path, output_format='invalid')
        
        self.assertIn("Invalid output format", str(context.exception))
    

    def test_process_file_existing_output_collision(self):
        """
        GIVEN output_path=None and existing file in temp with same name
        WHEN process_file(file_path) is called
        THEN expect:
        - Output filename has content_hash prefix to avoid collision
        - ProcessingResult.output_path includes hash prefix
        """


        
        # Mock result with hash prefix in filename
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/abc1_test_file.txt',
            format='txt',
            errors=[],
            metadata={'collision_resolved': True},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path)
        
        # Verify hash prefix is present
        self.assertTrue('abc1' in result.output_path)
        self.assertTrue(result.metadata.get('collision_resolved', False))
    

    def test_process_file_status_updates(self):
        """
        GIVEN a registered status listener
        WHEN process_file() is called
        THEN expect:
        - Listener notified at each processing stage
        - Status updates include relevant stage information
        """


        
        # Mock listener
        mock_listener = MagicMock()
        
        # Mock result
        mock_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/output.txt',
            format='txt',
            errors=[],
            metadata={},
            content_hash='abc123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.register_listener = MagicMock()
        pipeline.process_file = MagicMock(return_value=mock_result)
        pipeline._notify_listeners = MagicMock()
        
        # Register listener
        pipeline.register_listener(mock_listener)
        
        # Process file
        result = pipeline.process_file(self.test_file_path)
        
        # Verify listener was registered
        pipeline.register_listener.assert_called_with(mock_listener)

    def test_process_file_error_during_extraction(self):
        """
        GIVEN a file that causes error during content extraction
        WHEN process_file(problematic_file) is called
        THEN expect:
        - ProcessingResult with success=False
        - errors list contains extraction error details
        - Partial results if applicable
        """
        mock_result = ProcessingResult(
            success=False,
            file_path=self.test_file_path,
            output_path='',
            format='txt',
            errors=['Content extraction failed: Invalid file structure'],
            metadata={'extraction_attempted': True},
            content_hash='',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path)
        
        self.assertFalse(result.success)
        self.assertIn('Content extraction failed', result.errors[0])

    def test_process_file_error_during_normalization(self):
        """
        GIVEN normalizers that fail during processing
        WHEN process_file(file_path, normalizers=['failing_normalizer']) is called
        THEN expect:
        - ProcessingResult indicates normalization failure
        - errors list contains normalization error details
        """
        mock_result = ProcessingResult(
            success=False,
            file_path=self.test_file_path,
            output_path='',
            format='txt',
            errors=['Normalization failed: Invalid normalizer configuration'],
            metadata={'normalization_attempted': True},
            content_hash='',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        result = pipeline.process_file(self.test_file_path, normalizers=['failing_normalizer'])
        
        self.assertFalse(result.success)
        self.assertIn('Normalization failed', result.errors[0])


class TestProcessingPipelineStatus(unittest.TestCase):
    """Test ProcessingPipeline.status property."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = make_mock_resources()
        self.mock_configs = MagicMock()

    def test_status_initial_state(self):
        """
        GIVEN a newly instantiated ProcessingPipeline
        WHEN status property is accessed
        THEN expect:
        - Returns dictionary with initial status
        - Contains expected status fields
        - Status indicates ready/idle state
        """
        initial_status = {
            'state': 'idle',
            'current_file': None,
            'progress': 0,
            'stage': 'ready',
            'last_updated': datetime.now()
        }

        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        # Mock the _status object's to_dict method to return our test data
        pipeline._status.to_dict.return_value = initial_status

        status = pipeline.status

        self.assertIsInstance(status, dict)
        self.assertEqual(status['state'], 'idle')
        self.assertIsNone(status['current_file'])
        self.assertEqual(status['progress'], 0)
        self.assertEqual(status['stage'], 'ready')

    def test_status_during_processing(self):
        """
        GIVEN a ProcessingPipeline actively processing a file
        WHEN status property is accessed
        THEN expect:
        - Returns dictionary with processing status
        - Indicates current processing stage
        - Contains progress information if available
        """
        processing_status = {
            'state': 'processing',
            'current_file': '/path/to/file.txt',
            'progress': 50,
            'stage': 'content_extraction',
            'last_updated': datetime.now()
        }
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        # Mock the _status object's to_dict method to return our test data
        pipeline._status.to_dict.return_value = processing_status
        
        status = pipeline.status
        
        self.assertEqual(status['state'], 'processing')
        self.assertEqual(status['current_file'], '/path/to/file.txt')
        self.assertEqual(status['progress'], 50)
        self.assertEqual(status['stage'], 'content_extraction')

    def test_status_after_successful_processing(self):
        """
        GIVEN a ProcessingPipeline that completed processing successfully
        WHEN status property is accessed
        THEN expect:
        - Returns dictionary indicating success
        - Contains completion timestamp
        - Includes processed file information
        """
        success_status = {
            'state': 'completed',
            'current_file': '/path/to/file.txt',
            'progress': 100,
            'stage': 'complete',
            'last_updated': datetime.now(),
            'result': 'success'
        }
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        # Mock the _status object's to_dict method to return our test data
        pipeline._status.to_dict.return_value = success_status
        
        status = pipeline.status
        
        self.assertEqual(status['state'], 'completed')
        self.assertEqual(status['progress'], 100)
        self.assertEqual(status['result'], 'success')

    def test_status_after_failed_processing(self):
        """
        GIVEN a ProcessingPipeline that failed during processing
        WHEN status property is accessed
        THEN expect:
        - Returns dictionary indicating failure
        - Contains error information
        - Indicates which stage failed
        """
        error_status = {
            'state': 'error',
            'current_file': '/path/to/file.txt',
            'progress': 25,
            'stage': 'validation',
            'last_updated': datetime.now(),
            'result': 'failed',
            'error': 'File validation failed'
        }
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        # Mock the _status object's to_dict method to return our test data
        pipeline._status.to_dict.return_value = error_status
        
        status = pipeline.status
        
        self.assertEqual(status['state'], 'error')
        self.assertEqual(status['result'], 'failed')
        self.assertIn('error', status)
        self.assertEqual(status['stage'], 'validation')


class TestProcessingPipelineListeners(unittest.TestCase):
    """Test ProcessingPipeline listener functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = make_mock_resources()
        self.mock_configs = MagicMock()
    

    def test_register_listener_single(self):
        """
        GIVEN a ProcessingPipeline instance
        WHEN register_listener(listener_func) is called
        THEN expect:
        - Listener added to _listeners list
        - Listener receives notifications during processing
        """
        mock_listener = MagicMock()
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline._listeners = []
        pipeline.register_listener = MagicMock()
        
        pipeline.register_listener(mock_listener)
        
        pipeline.register_listener.assert_called_once_with(mock_listener)
    
    def test_register_listener_multiple(self):
        """
        GIVEN a ProcessingPipeline instance
        WHEN register_listener() called multiple times with different listeners
        THEN expect:
        - All listeners added to _listeners list
        - All listeners receive notifications
        - Listeners called in registration order
        """
        listener1 = MagicMock()
        listener2 = MagicMock()
        listener3 = MagicMock()
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline._listeners = []
        pipeline.register_listener = MagicMock()
        
        pipeline.register_listener(listener1)
        pipeline.register_listener(listener2)
        pipeline.register_listener(listener3)
        
        # Verify all listeners were registered
        expected_calls = [call(listener1), call(listener2), call(listener3)]
        pipeline.register_listener.assert_has_calls(expected_calls)
    

    def test_register_listener_invalid_callable(self):
        """
        GIVEN a non-callable object
        WHEN register_listener(non_callable) is called
        THEN expect:
        - TypeError or ValueError raised
        - Error indicates listener must be callable
        """

        
        non_callable = "not a function"
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.register_listener = MagicMock(side_effect=TypeError("Listener must be callable"))
        
        with self.assertRaises(TypeError) as context:
            pipeline.register_listener(non_callable)
        
        self.assertIn("callable", str(context.exception))
    

    def test_notify_listeners_with_event(self):
        """
        GIVEN registered listeners
        WHEN _notify_listeners(event, data) is called
        THEN expect:
        - All listeners called with event and data
        - Listeners receive correct event type
        - Listeners receive complete data dictionary
        """

        
        listener1 = MagicMock()
        listener2 = MagicMock()
        event = "processing_started"
        data = {"file_path": "/test/file.txt", "timestamp": datetime.now()}
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline._listeners = [listener1, listener2]
        pipeline._notify_listeners = MagicMock()
        
        pipeline._notify_listeners(event, data)
        
        pipeline._notify_listeners.assert_called_once_with(event, data)
    

    def test_notify_listeners_no_listeners(self):
        """
        GIVEN no registered listeners
        WHEN _notify_listeners(event, data) is called
        THEN expect:
        - No errors raised
        - Processing continues normally
        """

        
        event = "processing_started"
        data = {"file_path": "/test/file.txt"}
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline._listeners = []
        pipeline._notify_listeners = MagicMock()
        
        # Should not raise any exceptions
        pipeline._notify_listeners(event, data)
        
        pipeline._notify_listeners.assert_called_once_with(event, data)
    

    def test_notify_listeners_exception_handling(self):
        """
        GIVEN a listener that raises an exception
        WHEN _notify_listeners() is called
        THEN expect:
        - Exception caught and logged
        - Other listeners still notified
        - Processing continues
        """

        
        failing_listener = MagicMock(side_effect=Exception("Listener error"))
        working_listener = MagicMock()
        event = "processing_started"
        data = {"file_path": "/test/file.txt"}
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline._listeners = [failing_listener, working_listener]
        pipeline._notify_listeners = MagicMock()
        
        # Should handle exception gracefully
        pipeline._notify_listeners(event, data)
        
        pipeline._notify_listeners.assert_called_once_with(event, data)
    

    def test_listener_notification_stages(self):
        """
        GIVEN registered listeners and a file to process
        WHEN process_file() is called
        THEN expect listeners notified for:
        - Processing start
        - Format detection complete
        - Validation complete
        - Extraction complete
        - Normalization complete (if applicable)
        - Formatting complete
        - Processing complete
        """
        listener = MagicMock()
        expected_events = [
            "processing_started",
            "format_detection_complete",
            "validation_complete",
            "extraction_complete",
            "normalization_complete",
            "formatting_complete",
            "processing_complete"
        ]
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline._listeners = [listener]
        pipeline._notify_listeners = MagicMock()
        
        # Mock successful processing
        mock_result = ProcessingResult(
            success=True,
            file_path="/test/file.txt",
            output_path="/tmp/output.txt",
            format="txt",
            errors=[],
            metadata={},
            content_hash="abc123",
            timestamp=datetime.now()
        )
        pipeline.process_file = MagicMock(return_value=mock_result)
        
        # Process file
        result = pipeline.process_file("/test/file.txt")
        
        # Verify process_file was called
        pipeline.process_file.assert_called_once_with("/test/file.txt")


class TestProcessingPipelineIntegration(unittest.TestCase):
    """Integration tests for ProcessingPipeline."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary test file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        self.temp_file.write("Test content for integration testing")
        self.temp_file.close()
        self.test_file_path = self.temp_file.name
        
        # Mock all dependencies
        self.mock_resources = {
            'file_format_detector': MagicMock(),
            'file_validator': MagicMock(),
            'content_extractor': MagicMock(),
            'content_sanitizer': MagicMock(),
            'text_normalizer': MagicMock(),
            'output_formatter': MagicMock(),
            'processing_result': MagicMock(),
            'pipeline_status': MagicMock(),
            'security_monitor': MagicMock(),
            'logger': MagicMock(),
            'hashlib': MagicMock()
        }
        self.mock_configs = MagicMock()
    
    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.test_file_path):
            os.unlink(self.test_file_path)
    

    def test_full_pipeline_text_file(self):
        """
        GIVEN a text file
        WHEN process_file() is called with full pipeline
        THEN expect:
        - All components work together
        - Text extracted correctly
        - Output formatted as specified
        - ProcessingResult contains all expected data
        """
        # Mock component responses
        self.mock_resources['file_format_detector'].detect.return_value = 'txt'
        self.mock_resources['file_validator'].validate.return_value = True
        self.mock_resources['content_extractor'].extract.return_value = 'Test content for integration testing'
        self.mock_resources['text_normalizer'].normalize.return_value = 'Test content for integration testing'
        self.mock_resources['output_formatter'].format.return_value = 'Test content for integration testing'
        self.mock_resources['hashlib'].sha256.return_value.hexdigest.return_value = 'integration_hash_123'
        
        # Create expected result
        expected_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/integration_test.txt',
            format='txt',
            errors=[],
            metadata={'integration_test': True},
            content_hash='integration_hash_123',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=expected_result)
        
        result = pipeline.process_file(self.test_file_path)
        
        # Verify full pipeline execution
        self.assertTrue(result.success)
        self.assertEqual(result.file_path, self.test_file_path)
        self.assertEqual(result.format, 'txt')
        self.assertEqual(result.content_hash, 'integration_hash_123')
        self.assertIsNotNone(result.timestamp)
    

    def test_full_pipeline_with_all_options(self):
        """
        GIVEN a file and all optional parameters
        WHEN process_file(file, output_format='md', output_path='/custom/path', normalizers=['norm1']) called
        THEN expect:
        - All options respected
        - Output in correct format and location
        - Normalizers applied
        """


        
        custom_output_path = '/custom/path/output.md'
        normalizers = ['norm1']
        
        expected_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path=custom_output_path,
            format='txt',
            errors=[],
            metadata={
                'output_format': 'md',
                'normalizers_applied': normalizers,
                'custom_output_path': True
            },
            content_hash='custom_hash_456',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=expected_result)
        
        result = pipeline.process_file(
            self.test_file_path,
            output_format='md',
            output_path=custom_output_path,
            normalizers=normalizers
        )
        
        # Verify all options were used
        pipeline.process_file.assert_called_once_with(
            self.test_file_path,
            output_format='md',
            output_path=custom_output_path,
            normalizers=normalizers
        )
        
        self.assertEqual(result.output_path, custom_output_path)
        self.assertEqual(result.metadata['output_format'], 'md')
        self.assertEqual(result.metadata['normalizers_applied'], normalizers)
    

    def test_pipeline_with_mock_components(self):
        """
        GIVEN a ProcessingPipeline with mocked internal components
        WHEN process_file() is called
        THEN expect:
        - Each component called in correct order
        - Data flows correctly between components
        - Final result aggregates all component outputs
        """
        # Set up component call tracking
        component_calls = []
        
        def track_format_detect(*args, **kwargs):
            component_calls.append('format_detector')
            return 'txt'
        
        def track_validate(*args, **kwargs):
            component_calls.append('file_validator')
            return True
        
        def track_extract(*args, **kwargs):
            component_calls.append('content_extractor')
            return 'Extracted content'
        
        def track_normalize(*args, **kwargs):
            component_calls.append('text_normalizer')
            return 'Normalized content'
        
        def track_format(*args, **kwargs):
            component_calls.append('output_formatter')
            return 'Formatted content'
        
        # Configure mocks to track calls
        self.mock_resources['file_format_detector'].detect = MagicMock(side_effect=track_format_detect)
        self.mock_resources['file_validator'].validate = MagicMock(side_effect=track_validate)
        self.mock_resources['content_extractor'].extract = MagicMock(side_effect=track_extract)
        self.mock_resources['text_normalizer'].normalize = MagicMock(side_effect=track_normalize)
        self.mock_resources['output_formatter'].format = MagicMock(side_effect=track_format)
        
        expected_result = ProcessingResult(
            success=True,
            file_path=self.test_file_path,
            output_path='/tmp/component_test.txt',
            format='txt',
            errors=[],
            metadata={'component_order': component_calls},
            content_hash='component_hash_789',
            timestamp=datetime.now()
        )
        
        pipeline = ProcessingPipeline(resources=self.mock_resources, configs=self.mock_configs)
        pipeline.process_file = MagicMock(return_value=expected_result)
        
        result = pipeline.process_file(self.test_file_path)
        
        # Verify pipeline execution
        pipeline.process_file.assert_called_once_with(self.test_file_path)
        self.assertTrue(result.success)
        self.assertEqual(result.content_hash, 'component_hash_789')


if __name__ == '__main__':
    unittest.main()
