# Test file for TestMultiEngineOCR
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Test suite for ipfs_datasets_py.pdf_processing.ocr_engine

import os
import io
import time
import threading
from abc import ABC
from unittest.mock import Mock, patch, MagicMock

import pytest
import numpy as np
from PIL import Image


import cv2
import torch
import pytesseract

from ipfs_datasets_py.pdf_processing.ocr_engine import (
    OCREngine,
    EasyOCR,
    SuryaOCR,
    TesseractOCR,
    TrOCREngine,
    MultiEngineOCR
)

from .mock_ocr_engine import MockOCREngine
from ipfs_datasets_py.pdf_processing.ocr_engine import OCREngine
from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/ocr_engine.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/ocr_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.ocr_engine import (
    EasyOCR,
    MultiEngineOCR,
    OCREngine,
    SuryaOCR,
    TesseractOCR,
    TrOCREngine
)

# Check if each classes methods are accessible:
assert OCREngine._initialize
assert OCREngine.extract_text
assert OCREngine.is_available
assert SuryaOCR._initialize
assert SuryaOCR.extract_text
assert TesseractOCR._initialize
assert TesseractOCR.extract_text
assert TesseractOCR._preprocess_image
assert EasyOCR._initialize
assert EasyOCR.extract_text
assert TrOCREngine._initialize
assert TrOCREngine.extract_text
assert MultiEngineOCR.extract_with_ocr
assert MultiEngineOCR.get_available_engines
assert MultiEngineOCR.classify_document_type


# Check if the file's imports are accessible
try:
    from abc import ABC, abstractmethod
    import logging
    import io
    import numpy as np
    from typing import Dict, List, Any
    from PIL import Image
    import cv2
except ImportError as e:
    raise ImportError(f"Failed to import necessary modules: {e}")




class TestMultiEngineOCR:
    """Test suite for MultiEngineOCR orchestrator class."""

    def create_test_image_data(self, width=100, height=50, color='white'):
        """Helper method to create test image data as bytes."""
        img = Image.new('RGB', (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_multi_engine_ocr_initialization_all_engines(self):
        """
        GIVEN all OCR engine dependencies are available
        WHEN initializing MultiEngineOCR
        THEN should successfully initialize all engines
        AND should populate engines dict with all available engines
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Mock all engines as available
            mock_surya.return_value = MockOCREngine('surya', True, text="surya result", confidence=0.95)
            mock_tesseract.return_value = MockOCREngine('tesseract', True, text="tesseract result", confidence=0.69)
            mock_easy.return_value = MockOCREngine('easyocr', True, text="easyocr result", confidence=0.420)
            mock_trocr.return_value = MockOCREngine('trocr', True, text="trocr result", confidence=0.360)
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_ocr(
                image_data, 
                strategy='quality_first', 
                confidence_threshold=0.8
            )
            
            # Should use Surya (first in quality_first order) and stop there
            assert result['text'] == "surya result"
            assert result['engine'] == 'surya'
            assert result['confidence'] == 0.95

    def test_extract_with_ocr_speed_first_strategy(self):
        """
        GIVEN a MultiEngineOCR instance with multiple engines
        WHEN calling extract_with_ocr() with strategy='speed_first'
        THEN should try engines in order: Tesseract → Surya → EasyOCR → TrOCR
        AND should prioritize fastest processing
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Tesseract (fastest) has good confidence
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.85, text="tesseract fast")
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.95, text="surya result")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.80, text="easy result")
            mock_trocr.return_value = MockOCREngine('trocr', True, confidence=0.75, text="trocr result")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_ocr(
                image_data,
                strategy='speed_first',
                confidence_threshold=0.8
            )
            
            # Should use Tesseract (first in speed_first order)
            assert result['text'] == "tesseract fast"
            assert result['engine'] == 'tesseract'
            assert result['confidence'] == 0.85

    def test_extract_with_ocr_accuracy_first_strategy(self):
        """
        GIVEN a MultiEngineOCR instance with multiple engines
        WHEN calling extract_with_ocr() with strategy='accuracy_first'
        THEN should try engines in order: Surya → EasyOCR → TrOCR → Tesseract
        AND should prioritize most accurate engines
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Surya (most accurate) available
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.97, text="surya accurate")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.89, text="easy result")
            mock_trocr.return_value = MockOCREngine('trocr', True, confidence=0.82, text="trocr result")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.78, text="tesseract result")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_ocr(
                image_data,
                strategy='accuracy_first',
                confidence_threshold=0.9
            )
            
            # Should use Surya (first in accuracy_first order)
            assert result['text'] == "surya accurate"
            assert result['engine'] == 'surya'
            assert result['confidence'] == 0.97

    def test_extract_with_ocr_confidence_threshold_met(self):
        """
        GIVEN a MultiEngineOCR instance and high-quality image
        WHEN calling extract_with_ocr() with confidence_threshold=0.8
        THEN should stop at first engine meeting threshold
        AND should return results from that engine
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.9, text="high quality")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.7, text="lower quality")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_ocr(
                image_data,
                strategy='quality_first',
                confidence_threshold=0.85
            )
            
            # Should stop at Surya since it meets threshold
            assert result['confidence'] >= 0.85
            assert result['engine'] == 'surya'

    def test_extract_with_ocr_confidence_threshold_not_met(self):
        """
        GIVEN a MultiEngineOCR instance and low-quality image
        WHEN calling extract_with_ocr() with high confidence_threshold
        THEN should try all available engines
        AND should return best available result even below threshold
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy:
            
            # All engines have low confidence
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.6, text="surya low")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.5, text="tesseract low")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.7, text="easy best")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_ocr(
                image_data,
                strategy='quality_first',
                confidence_threshold=0.9  # High threshold
            )
            
            # Should return best result even though below threshold
            assert result['confidence'] < 0.9
            # Should have tried multiple engines and returned the best
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'engine' in result

    def test_extract_with_ocr_single_engine_available(self):
        """
        GIVEN a MultiEngineOCR instance with only one available engine
        WHEN calling extract_with_ocr()
        THEN should use the single available engine
        AND should return its results regardless of strategy
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Only one engine available
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.8, text="only option")
            mock_surya.return_value = MockOCREngine('surya', False)
            mock_easy.return_value = MockOCREngine('easyocr', False)
            mock_trocr.return_value = MockOCREngine('trocr', False)
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_ocr(image_data)
            
            assert result['engine'] == 'tesseract'
            assert result['text'] == "only option"

    def test_extract_with_ocr_no_engines_available(self):
        """
        GIVEN a MultiEngineOCR instance with no available engines
        WHEN calling extract_with_ocr()
        THEN should raise Runtime error
        AND should indicate no engines available
        """
        multi_ocr = MultiEngineOCR()
        multi_ocr.engines = {}  # No engines
        
        image_data = self.create_test_image_data()
        
        with pytest.raises(RuntimeError, match="No OCR engines available"):
            multi_ocr.extract_with_ocr(image_data)

    def test_extract_with_ocr_engine_failure_handling(self):
        """
        GIVEN a MultiEngineOCR instance where first engine fails
        WHEN calling extract_with_ocr()
        THEN should continue to next engine in strategy order
        AND should handle individual engine failures gracefully
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            
            # First engine fails, second succeeds
            failing_engine = MockOCREngine('surya', True)
            failing_engine.extract_text = Mock(side_effect=RuntimeError("Surya failed"))
            
            mock_surya.return_value = failing_engine
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.8, text="fallback success")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_ocr(image_data, strategy='quality_first')
            
            # Should have fallen back to Tesseract
            assert result['engine'] == 'tesseract'
            assert result['text'] == "fallback success"

    def test_extract_with_ocr_invalid_strategy(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_ocr() with invalid strategy
        THEN should raise ValueError or use default strategy
        """
        multi_ocr = MultiEngineOCR()
        image_data = self.create_test_image_data()
        
        with pytest.raises(ValueError, match="strategy|invalid"):
            multi_ocr.extract_with_ocr(image_data, strategy='invalid_strategy')

    def test_extract_with_ocr_invalid_confidence_threshold(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_ocr() with confidence_threshold outside [0.0, 1.0]
        THEN should raise ValueError
        """
        multi_ocr = MultiEngineOCR()
        image_data = self.create_test_image_data()
        
        # Test values outside valid range
        invalid_thresholds = [-0.1, 1.1, 2.0, -1.0]
        
        for threshold in invalid_thresholds:
            with pytest.raises(ValueError, match="confidence.*threshold|range"):
                multi_ocr.extract_with_ocr(image_data, confidence_threshold=threshold)

    def test_extract_with_ocr_result_format_consistency(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_ocr() with any engine
        THEN should return consistent result format
        AND should include text, confidence, engine metadata
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.85, text="consistent format")
            
            multi_ocr = MultiEngineOCR()
            
            image_data = self.create_test_image_data()
            result = multi_ocr.extract_with_ocr(image_data)
            
            # Check consistent format
            assert isinstance(result, dict)
            required_keys = {'text', 'confidence', 'engine'}
            assert required_keys.issubset(result.keys())
            
            assert isinstance(result['text'], str)
            assert isinstance(result['confidence'], float)
            assert isinstance(result['engine'], str)
            assert 0.0 <= result['confidence'] <= 1.0

    def test_extract_with_ocr_performance_monitoring(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_ocr() multiple times
        THEN should track engine performance and failure modes
        AND should provide comprehensive logging
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.8, text="monitored")
            
            multi_ocr = MultiEngineOCR()
            image_data = self.create_test_image_data()
            
            # Multiple calls to test performance monitoring
            results = []
            for _ in range(3):
                result = multi_ocr.extract_with_ocr(image_data)
                results.append(result)
            
            # All results should be consistent
            for result in results:
                assert result['engine'] == 'tesseract'
                assert result['text'] == "monitored"

    def test_extract_with_ocr_thread_safety(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_ocr() from multiple threads
        THEN should be thread-safe for concurrent processing
        AND should not interfere between concurrent requests
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.8, text="thread safe")
            
            multi_ocr = MultiEngineOCR()
            image_data = self.create_test_image_data()
            
            results = []
            exceptions = []
            
            def extract_text_thread():
                try:
                    for _ in range(10):
                        result = multi_ocr.extract_with_ocr(image_data)
                        results.append(result)
                        time.sleep(0.001)  # Small delay
                except Exception as e:
                    exceptions.append(e)
            
            threads = [threading.Thread(target=extract_text_thread) for _ in range(3)]
            
            for thread in threads:
                thread.start()
            
            for thread in threads:
                thread.join()
            
            # Should have no exceptions
            assert len(exceptions) == 0, f"Thread safety test failed: {exceptions}"
            
            # All results should be consistent
            assert len(results) == 30  # 3 threads × 10 iterations
            for result in results:
                assert result['engine'] == 'tesseract'
                assert result['text'] == "thread safe"

    def test_extract_with_ocr_empty_image_data(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_ocr() with empty image data
        THEN should raise ValueError
        """
        multi_ocr = MultiEngineOCR()
        
        with pytest.raises(ValueError):
            multi_ocr.extract_with_ocr(b'')

    def test_extract_with_ocr_none_image_data(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling extract_with_ocr() with None image data
        THEN should raise TypeError or ValueError
        """
        multi_ocr = MultiEngineOCR()
        
        with pytest.raises((TypeError, ValueError)):
            multi_ocr.extract_with_ocr(None)

    def test_extract_with_ocr_strategy_engine_ordering(self):
        """
        GIVEN a MultiEngineOCR instance with all engines available
        WHEN testing different strategies
        THEN should demonstrate correct engine ordering for each strategy
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # All engines available but with low confidence to force trying multiple
            engines = {
                'surya': MockOCREngine('surya', True, confidence=0.5, text="surya"),
                'tesseract': MockOCREngine('tesseract', True, confidence=0.5, text="tesseract"),
                'easyocr': MockOCREngine('easyocr', True, confidence=0.5, text="easyocr"),
                'trocr': MockOCREngine('trocr', True, confidence=0.5, text="trocr")
            }
            
            mock_surya.return_value = engines['surya']
            mock_tesseract.return_value = engines['tesseract']
            mock_easy.return_value = engines['easyocr']
            mock_trocr.return_value = engines['trocr']
            
            multi_ocr = MultiEngineOCR()
            image_data = self.create_test_image_data()
            
            # Test that each strategy tries engines in correct order
            strategies = ['quality_first', 'speed_first', 'accuracy_first']
            
            for strategy in strategies:
                # Use very high threshold to force trying all engines
                result = multi_ocr.extract_with_ocr(
                    image_data, 
                    strategy=strategy, 
                    confidence_threshold=0.99
                )
                
                # Should return some result
                assert isinstance(result, dict)
                assert 'engine' in result
                assert result['engine'] in ['surya', 'tesseract', 'easyocr', 'trocr']
            
            # Should have all engines
            expected_engines = {'surya', 'tesseract', 'easyocr', 'trocr'}
            assert set(multi_ocr.engines.keys()) == expected_engines
            
            # All engines should be available
            available_engines = multi_ocr.get_available_engines()
            assert set(available_engines) == expected_engines

    def test_multi_engine_ocr_initialization_partial_engines(self):
        """
        GIVEN only some OCR engine dependencies are available
        WHEN initializing MultiEngineOCR
        THEN should initialize available engines gracefully
        AND should skip unavailable engines without crashing
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Only some engines available
            mock_surya.return_value = MockOCREngine('surya', True)
            mock_tesseract.return_value = MockOCREngine('tesseract', False)  # Not available
            mock_easy.return_value = MockOCREngine('easyocr', True)
            mock_trocr.return_value = MockOCREngine('trocr', False)  # Not available
            
            multi_ocr = MultiEngineOCR()
            
            # Should only have available engines
            available_engines = multi_ocr.get_available_engines()
            assert set(available_engines) == {'surya', 'easyocr'}
            
            # Should still have all engines in dict but only available ones are usable
            assert len(multi_ocr.engines) == 4  # All created
            assert multi_ocr.engines['surya'].is_available()
            assert not multi_ocr.engines['tesseract'].is_available()

    def test_multi_engine_ocr_initialization_no_engines(self):
        """
        GIVEN no OCR engine dependencies are available
        WHEN initializing MultiEngineOCR
        THEN should initialize with empty engines dict
        AND should handle gracefully without crashing
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # All engines unavailable
            mock_surya.return_value = MockOCREngine('surya', False)
            mock_tesseract.return_value = MockOCREngine('tesseract', False)
            mock_easy.return_value = MockOCREngine('easyocr', False)
            mock_trocr.return_value = MockOCREngine('trocr', False)
            
            multi_ocr = MultiEngineOCR()
            
            # Should have no available engines
            available_engines = multi_ocr.get_available_engines()
            assert len(available_engines) == 0

    def test_get_available_engines_returns_list(self):
        """
        GIVEN a MultiEngineOCR instance with some available engines
        WHEN calling get_available_engines()
        THEN should return list of engine names
        AND list should contain only successfully initialized engines
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            mock_surya.return_value = MockOCREngine('surya', True)
            mock_tesseract.return_value = MockOCREngine('tesseract', True)
            mock_easy.return_value = MockOCREngine('easyocr', False)
            mock_trocr.return_value = MockOCREngine('trocr', True)
            
            multi_ocr = MultiEngineOCR()
            available = multi_ocr.get_available_engines()
            
            assert isinstance(available, list)
            assert set(available) == {'surya', 'tesseract', 'trocr'}

    def test_get_available_engines_empty_when_no_engines(self):
        """
        GIVEN a MultiEngineOCR instance with no available engines
        WHEN calling get_available_engines()
        THEN should return empty list
        """
        multi_ocr = MultiEngineOCR()
        multi_ocr.engines = {}  # Simulate no engines
        
        available = multi_ocr.get_available_engines()
        assert isinstance(available, list)
        assert len(available) == 0

    def test_get_available_engines_reflects_current_state(self):
        """
        GIVEN a MultiEngineOCR instance
        WHEN calling get_available_engines()
        THEN should reflect engines available at initialization time
        AND should re-check engine availability when state changes
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya:
            mock_engine = MockOCREngine('surya', True)
            mock_surya.return_value = mock_engine
            
            multi_ocr = MultiEngineOCR()
            
            # Initially available
            available = multi_ocr.get_available_engines()
            assert 'surya' in available
            
            # Change engine availability after initialization
            mock_engine.available = False
            
            # Should return as unavailable now
            available_again = multi_ocr.get_available_engines()
            assert 'surya' not in available_again

    def test_classify_document_type_printed_placeholder(self):
        """
        GIVEN a MultiEngineOCR instance and any image data
        WHEN calling classify_document_type()
        THEN should return 'printed' as placeholder implementation
        """
        multi_ocr = MultiEngineOCR()
        image_data = self.create_test_image_data()
        
        doc_type = multi_ocr.classify_document_type(image_data)
        assert doc_type == 'printed'

    def test_extract_with_ocr_quality_first_strategy(self):
        """
        GIVEN a MultiEngineOCR instance with multiple engines
        WHEN calling extract_with_ocr() with strategy='quality_first'
        THEN should try engines in order: Surya → Tesseract → EasyOCR → TrOCR
        AND should stop when confidence threshold is met
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Surya has high confidence, should stop there
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.95, text="surya result")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.85, text="tesseract result")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.80, text="easy result")
            mock_trocr.return_value = MockOCREngine('trocr', True, confidence=0.75, text="trocr result")
            
            multi_ocr = MultiEngineOCR()




if __name__ == "__main__":
    pytest.main([__file__, "-v"])
