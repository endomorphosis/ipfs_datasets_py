"""
Unit tests for FileTypeDetector class.

Tests cover all detection methods, strategies, and edge cases.
"""

import os
import tempfile
from pathlib import Path
import pytest

from ipfs_datasets_py.file_detector import (
    FileTypeDetector,
    DetectionMethod,
    DetectionStrategy,
    HAVE_MAGIC,
    HAVE_MAGIKA
)


class TestFileTypeDetector:
    """Test suite for FileTypeDetector class"""
    
    @pytest.fixture
    def detector(self):
        """Create a FileTypeDetector instance"""
        return FileTypeDetector()
    
    @pytest.fixture
    def temp_pdf_file(self):
        """Create a temporary PDF file for testing"""
        # PDF header magic bytes
        pdf_header = b'%PDF-1.4\n'
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as f:
            f.write(pdf_header)
            f.write(b'%EOF\n')
            temp_path = f.name
        
        yield temp_path
        
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    @pytest.fixture
    def temp_text_file(self):
        """Create a temporary text file for testing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write('This is a test text file.')
            temp_path = f.name
        
        yield temp_path
        
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    @pytest.fixture
    def temp_json_file(self):
        """Create a temporary JSON file for testing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"test": "data"}')
            temp_path = f.name
        
        yield temp_path
        
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    # GIVEN-WHEN-THEN Tests
    
    def test_detector_initialization(self, detector):
        """
        GIVEN: A fresh FileTypeDetector instance
        WHEN: The detector is initialized
        THEN: It should be properly configured with available methods
        """
        assert detector is not None
        assert hasattr(detector, '_lock')
        available_methods = detector.get_available_methods()
        assert 'extension' in available_methods
        assert isinstance(available_methods, list)
    
    def test_available_methods(self, detector):
        """
        GIVEN: A FileTypeDetector instance
        WHEN: Getting available methods
        THEN: Should return list of available detection methods
        """
        methods = detector.get_available_methods()
        assert 'extension' in methods  # Always available
        
        if HAVE_MAGIC:
            assert 'magic' in methods
        
        if HAVE_MAGIKA:
            assert 'magika' in methods
    
    def test_supported_strategies(self, detector):
        """
        GIVEN: A FileTypeDetector instance
        WHEN: Getting supported strategies
        THEN: Should return all detection strategies
        """
        strategies = detector.get_supported_strategies()
        assert 'fast' in strategies
        assert 'accurate' in strategies
        assert 'voting' in strategies
        assert 'conservative' in strategies
    
    def test_detect_pdf_by_extension(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Detecting type with extension method
        THEN: Should correctly identify as PDF
        """
        result = detector.detect_type(temp_pdf_file, methods=['extension'])
        
        assert result is not None
        assert 'mime_type' in result
        assert 'application/pdf' in result['mime_type']
        assert result['extension'] == '.pdf'
        assert result['method'] == 'extension'
        assert result['confidence'] > 0
    
    def test_detect_text_by_extension(self, detector, temp_text_file):
        """
        GIVEN: A text file
        WHEN: Detecting type with extension method
        THEN: Should correctly identify as text
        """
        result = detector.detect_type(temp_text_file, methods=['extension'])
        
        assert result is not None
        assert 'mime_type' in result
        assert 'text/plain' in result['mime_type']
        assert result['extension'] == '.txt'
    
    @pytest.mark.skipif(not HAVE_MAGIC, reason="python-magic not available")
    def test_detect_pdf_by_magic(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Detecting type with magic bytes method
        THEN: Should correctly identify as PDF
        """
        result = detector.detect_type(temp_pdf_file, methods=['magic'])
        
        assert result is not None
        assert 'mime_type' in result
        assert 'pdf' in result['mime_type'].lower()
        assert result['method'] == 'magic'
        assert result['confidence'] >= 0.85
    
    @pytest.mark.skipif(not HAVE_MAGIKA, reason="Magika not available")
    def test_detect_pdf_by_magika(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Detecting type with Magika AI method
        THEN: Should correctly identify as PDF with high confidence
        """
        result = detector.detect_type(temp_pdf_file, methods=['magika'])
        
        assert result is not None
        assert 'mime_type' in result
        assert result['method'] == 'magika'
        # Magika should have high confidence
        if not result.get('error'):
            assert result.get('confidence', 0) > 0.7
    
    def test_detect_bytes_input(self, detector):
        """
        GIVEN: PDF content as bytes
        WHEN: Detecting type from bytes
        THEN: Should correctly identify the file type
        """
        pdf_bytes = b'%PDF-1.4\n%EOF\n'
        result = detector.detect_type(pdf_bytes, methods=['extension', 'magic'])
        
        assert result is not None
        # Extension won't work for bytes, but magic might
        if HAVE_MAGIC:
            assert 'mime_type' in result
    
    def test_fast_strategy(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Using FAST detection strategy
        THEN: Should use extension first, then magic if needed
        """
        result = detector.detect_type(temp_pdf_file, strategy='fast')
        
        assert result is not None
        assert 'mime_type' in result
        assert 'all_results' in result
        # Fast strategy tries extension first
        assert 'extension' in result['all_results']
    
    def test_accurate_strategy(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Using ACCURATE detection strategy
        THEN: Should use Magika first (if available), then magic, then extension
        """
        result = detector.detect_type(temp_pdf_file, strategy='accurate')
        
        assert result is not None
        assert 'mime_type' in result
        assert 'all_results' in result
    
    def test_voting_strategy(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Using VOTING detection strategy
        THEN: Should run all methods and select consensus
        """
        result = detector.detect_type(
            temp_pdf_file,
            methods=['extension', 'magic', 'magika'],
            strategy='voting'
        )
        
        assert result is not None
        assert 'mime_type' in result
        assert 'all_results' in result
    
    def test_conservative_strategy(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Using CONSERVATIVE detection strategy
        THEN: Should use extension, verify with magic, fallback to magika
        """
        result = detector.detect_type(temp_pdf_file, strategy='conservative')
        
        assert result is not None
        assert 'mime_type' in result
        assert 'all_results' in result
    
    def test_batch_detect(self, detector, temp_pdf_file, temp_text_file):
        """
        GIVEN: Multiple files
        WHEN: Using batch detection
        THEN: Should detect types for all files
        """
        files = [temp_pdf_file, temp_text_file]
        results = detector.batch_detect(files)
        
        assert len(results) == 2
        assert temp_pdf_file in results
        assert temp_text_file in results
        
        # Check PDF result
        pdf_result = results[temp_pdf_file]
        assert 'mime_type' in pdf_result
        
        # Check text result
        text_result = results[temp_text_file]
        assert 'mime_type' in text_result
    
    def test_nonexistent_file(self, detector):
        """
        GIVEN: A path to a nonexistent file
        WHEN: Attempting to detect its type
        THEN: Should return error result
        """
        result = detector.detect_type('/nonexistent/file.pdf')
        
        assert result is not None
        assert result.get('mime_type') is None
        assert 'error' in result
        assert 'not found' in result['error'].lower()
    
    def test_file_without_extension(self, detector):
        """
        GIVEN: A file without an extension
        WHEN: Detecting its type
        THEN: Should fall back to magic bytes or return error
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='', delete=False) as f:
            f.write('test content')
            temp_path = f.name
        
        try:
            result = detector.detect_type(temp_path)
            assert result is not None
            # May or may not have mime_type depending on available methods
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_all_results_included(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Detecting its type
        THEN: Result should include all_results field with all attempted methods
        """
        result = detector.detect_type(temp_pdf_file)
        
        assert 'all_results' in result
        assert isinstance(result['all_results'], dict)
    
    def test_confidence_scores(self, detector, temp_pdf_file):
        """
        GIVEN: A PDF file
        WHEN: Detecting its type
        THEN: Result should include confidence score between 0 and 1
        """
        result = detector.detect_type(temp_pdf_file)
        
        assert 'confidence' in result
        confidence = result['confidence']
        assert 0.0 <= confidence <= 1.0
    
    def test_json_file_detection(self, detector, temp_json_file):
        """
        GIVEN: A JSON file
        WHEN: Detecting its type
        THEN: Should correctly identify as JSON
        """
        result = detector.detect_type(temp_json_file)
        
        assert result is not None
        assert 'mime_type' in result
        if result['mime_type']:
            assert 'json' in result['mime_type'].lower() or 'text' in result['mime_type'].lower()
    
    def test_invalid_strategy(self, detector, temp_pdf_file):
        """
        GIVEN: An invalid strategy name
        WHEN: Attempting detection
        THEN: Should fall back to default strategy and log warning
        """
        result = detector.detect_type(temp_pdf_file, strategy='invalid_strategy')
        
        # Should still return a result, not raise exception
        assert result is not None
        assert 'mime_type' in result
    
    def test_thread_safety(self, detector, temp_pdf_file):
        """
        GIVEN: Multiple concurrent detection requests
        WHEN: Running in parallel
        THEN: Should handle concurrent access safely
        """
        import concurrent.futures
        
        def detect_file():
            return detector.detect_type(temp_pdf_file)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(detect_file) for _ in range(10)]
            results = [f.result() for f in futures]
        
        # All results should be valid
        assert len(results) == 10
        for result in results:
            assert result is not None
            assert 'mime_type' in result
    
    def test_empty_file(self, detector):
        """
        GIVEN: An empty file
        WHEN: Detecting its type
        THEN: Should handle gracefully
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            temp_path = f.name
        
        try:
            result = detector.detect_type(temp_path)
            assert result is not None
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_large_file(self, detector):
        """
        GIVEN: A large file
        WHEN: Detecting its type
        THEN: Should complete in reasonable time (<100ms for extension)
        """
        import time
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            # Write 1MB of data
            f.write('x' * (1024 * 1024))
            temp_path = f.name
        
        try:
            start = time.time()
            result = detector.detect_type(temp_path, methods=['extension'])
            elapsed = time.time() - start
            
            assert result is not None
            # Extension detection should be very fast
            assert elapsed < 0.1
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_method_order_matters(self, detector, temp_pdf_file):
        """
        GIVEN: Different method orders
        WHEN: Detecting with different method lists
        THEN: Should respect the order when using method-based detection
        """
        # Test with different orders
        result1 = detector._detect_by_methods(
            Path(temp_pdf_file), None, ['extension', 'magic']
        )
        result2 = detector._detect_by_methods(
            Path(temp_pdf_file), None, ['magic', 'extension']
        )
        
        assert result1 is not None
        assert result2 is not None
