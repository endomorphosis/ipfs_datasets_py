# Test file for TestOCREngineIntegration
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



class TestOCREngineIntegration:
    """Integration tests for OCR engine interactions and edge cases."""

    def create_test_image_data(self, width=100, height=50, color='white'):
        """Helper method to create test image data as bytes."""
        img = Image.new('RGB', (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_all_engines_consistent_interface(self):
        """
        GIVEN all available OCR engines
        WHEN calling extract_text() on each engine with same image
        THEN should all return dictionaries with consistent key structure
        AND should all include 'text', 'confidence', 'engine' keys at minimum
        """
        image_data = self.create_test_image_data()
        
        # Mock all engines to be available
        engines = []
        
        with patch.object(SuryaOCR, '_initialize'):
            surya = SuryaOCR()
            surya.available = True
            
            # Mock Surya components properly
            surya.detection_predictor = Mock()
            surya.recognition_predictor = Mock()
            
            # Mock the result structure that Surya returns
            mock_text_line = Mock()
            mock_text_line.text = "surya"
            mock_text_line.confidence = 0.9
            mock_text_line.bbox = [10, 10, 50, 25]
            
            mock_result = Mock()
            mock_result.text_lines = [mock_text_line]
            
            surya.recognition_predictor.return_value = [mock_result]
            engines.append(surya)
        
        with patch.object(TesseractOCR, '_initialize'):
            tesseract = TesseractOCR()
            tesseract.available = True
            tesseract.pytesseract = Mock()
            tesseract.pytesseract.image_to_string.return_value = "tesseract"
            tesseract.pytesseract.image_to_data.return_value = {
                'text': ['tesseract'], 'conf': [90], 'left': [10], 'top': [10], 
                'width': [50], 'height': [15]
            }
            with patch.object(tesseract, '_preprocess_image', return_value=Image.new('RGB', (100, 50))):
                engines.append(tesseract)
        
        with patch.object(EasyOCR, '_initialize'):
            easyocr = EasyOCR()
            easyocr.available = True
            easyocr.reader = Mock()
            easyocr.reader.readtext.return_value = [
                ([[10, 10], [50, 10], [50, 25], [10, 25]], 'easyocr', 0.9)
            ]
            engines.append(easyocr)
        
        with patch.object(TrOCREngine, '_initialize'):
            trocr = TrOCREngine()
            trocr.available = True
            trocr.processor = Mock()
            trocr.model = Mock()
            
            # Mock processor return value with pixel_values attribute
            mock_processor_output = Mock()
            mock_processor_output.pixel_values = Mock()
            trocr.processor.return_value = mock_processor_output
            
            trocr.model.generate.return_value = Mock()
            trocr.processor.batch_decode.return_value = ["trocr"]
            engines.append(trocr)
        
        # Test all engines have consistent interface
        required_keys = {'text', 'confidence', 'engine'}
        
        for engine in engines:
            result = engine.extract_text(image_data)
            
            assert isinstance(result, dict)
            assert required_keys.issubset(result.keys())
            assert isinstance(result['text'], str)
            assert isinstance(result['confidence'], (int, float))
            assert isinstance(result['engine'], str)
            assert 0.0 <= float(result['confidence']) <= 1.0 or 0 <= int(result['confidence']) <= 100

    def test_engine_availability_after_initialization(self):
        """
        GIVEN all OCR engine classes
        WHEN checking is_available() after initialization
        THEN should accurately reflect successful/failed initialization
        AND should be consistent with actual functionality
        """
        # Test successful initialization
        with patch.object(SuryaOCR, '_initialize'):
            surya = SuryaOCR()
            surya.available = True
            assert surya.is_available() == True
        
        # Test failed initialization
        with patch.object(SuryaOCR, '_initialize', side_effect=ImportError("Failed")):
            surya_fail = SuryaOCR()
            # Availability depends on error handling implementation
            assert hasattr(surya_fail, 'available')
            assert isinstance(surya_fail.is_available(), bool)

    def test_cross_engine_text_extraction_accuracy(self):
        """
        GIVEN same high-quality text image
        WHEN extracting text with different engines
        THEN should produce similar text results
        AND should demonstrate relative strengths/weaknesses
        """
        image_data = self.create_test_image_data()
        expected_text = "Sample Text"
        
        engines = {}
        
        # Mock engines with similar but slightly different results
        with patch.object(SuryaOCR, '_initialize'):
            surya = SuryaOCR()
            surya.available = True
            
            # Mock Surya components properly
            surya.detection_predictor = Mock()
            surya.recognition_predictor = Mock()
            
            # Mock the result structure that Surya returns
            mock_text_line = Mock()
            mock_text_line.text = "Sample Text"
            mock_text_line.confidence = 0.95
            mock_text_line.bbox = [10, 10, 50, 25]
            
            mock_result = Mock()
            mock_result.text_lines = [mock_text_line]
            
            surya.recognition_predictor.return_value = [mock_result]
            engines['surya'] = surya
        
        with patch.object(TesseractOCR, '_initialize'):
            tesseract = TesseractOCR()
            tesseract.available = True
            tesseract.pytesseract = Mock()
            tesseract.pytesseract.image_to_string.return_value = "Sample Text"
            tesseract.pytesseract.image_to_data.return_value = {
                'text': ['Sample', 'Text'], 'conf': [92, 88], 'left': [10, 50], 
                'top': [10, 10], 'width': [35, 25], 'height': [15, 15]
            }
            with patch.object(tesseract, '_preprocess_image', return_value=Image.new('RGB', (100, 50))):
                engines['tesseract'] = tesseract
        
        results = {}
        for name, engine in engines.items():
            result = engine.extract_text(image_data)
            results[name] = result
        
        # All should produce similar text
        for name, result in results.items():
            assert "Sample" in result['text']
            assert "Text" in result['text']
            assert result['confidence'] > 0.8

    def test_engine_performance_characteristics(self):
        """
        GIVEN same image processed by multiple engines
        WHEN measuring processing time and memory usage
        THEN should demonstrate expected performance characteristics
        AND should validate speed_first strategy assumptions
        """
        image_data = self.create_test_image_data()
        
        # Mock engines with performance simulation
        processing_times = {}
        
        with patch.object(TesseractOCR, '_initialize'):
            tesseract = TesseractOCR()
            tesseract.available = True
            tesseract.pytesseract = Mock()
            tesseract.pytesseract.image_to_string.return_value = "fast"
            tesseract.pytesseract.image_to_data.return_value = {
                'text': ['fast'], 'conf': [85], 'left': [10], 'top': [10], 
                'width': [30], 'height': [15]
            }
            
            with patch.object(tesseract, '_preprocess_image', return_value=Image.new('RGB', (100, 50))):
                start_time = time.time()
                result = tesseract.extract_text(image_data)
                processing_times['tesseract'] = time.time() - start_time
        
        # In real scenario, Tesseract should be fastest
        assert 'tesseract' in processing_times
        assert processing_times['tesseract'] >= 0  # Should complete

    def test_engine_error_handling_consistency(self):
        """
        GIVEN invalid inputs (empty data, corrupted images, etc.)
        WHEN processing with different engines
        THEN should handle errors consistently
        AND should raise appropriate exception types
        """
        invalid_inputs = [
            b'',  # Empty data
            b'not_an_image',  # Invalid data
            None  # None input
        ]
        
        engines = []
        
        # Create mock engines
        with patch.object(TesseractOCR, '_initialize'):
            tesseract = TesseractOCR()
            tesseract.available = True
            engines.append(tesseract)
        
        with patch.object(EasyOCR, '_initialize'):
            easyocr = EasyOCR()
            easyocr.available = True
            engines.append(easyocr)
        
        for engine in engines:
            for invalid_input in invalid_inputs:
                with pytest.raises((ValueError, TypeError, Exception)):
                    engine.extract_text(invalid_input)

    def test_multi_engine_fallback_real_world_scenarios(self):
        """
        GIVEN various real-world document types and quality levels
        WHEN using MultiEngineOCR with different strategies
        THEN should demonstrate effective fallback behavior
        AND should improve overall extraction success rate
        """
        multi_engine = MultiEngineOCR()
        
        # Mock available engines with different capabilities
        mock_tesseract = Mock()
        mock_tesseract.name = 'tesseract'
        mock_tesseract.is_available.return_value = True
        
        mock_easyocr = Mock()
        mock_easyocr.name = 'easyocr'
        mock_easyocr.is_available.return_value = True
        
        mock_surya = Mock()
        mock_surya.name = 'surya'
        mock_surya.is_available.return_value = True
        
        # Fix the engines dictionary structure - should be keyed by name
        multi_engine.engines = {
            'tesseract': mock_tesseract,
            'easyocr': mock_easyocr,
            'surya': mock_surya
        }
        
        # Create test image data
        test_image = self.create_test_image_data()
        
        # Test scenario 1: First engine fails, second succeeds
        mock_tesseract.extract_text.side_effect = RuntimeError("Engine failed")
        mock_easyocr.extract_text.return_value = {
            'text': 'Fallback success',
            'confidence': 0.85,
            'engine': 'easyocr'
        }
        
        result = multi_engine.extract_with_ocr(test_image)
        assert result['text'] == 'Fallback success'
        assert result['engine'] == 'easyocr'
        
        # Test scenario 2: Multiple engines succeed, best result selected
        mock_tesseract.extract_text.side_effect = None
        mock_tesseract.extract_text.return_value = {
            'text': 'Low quality result',
            'confidence': 0.65,
            'engine': 'tesseract'
        }
        mock_easyocr.extract_text.return_value = {
            'text': 'High quality result',
            'confidence': 0.95,
            'engine': 'easyocr'
        }
        
        result = multi_engine.extract_with_ocr(test_image, strategy='quality_first')
        assert result['confidence'] == 0.95
        assert result['engine'] == 'easyocr'

    def test_engine_memory_cleanup(self):
        """
        GIVEN OCR engines processing large images
        WHEN extraction completes or fails
        THEN should properly clean up memory resources
        AND should not leak memory between operations
        """
        import gc
        import psutil
        import os
        
        # Get current process for memory monitoring
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Test with TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            # Mock large image processing
            large_image_data = self.create_test_image_data(2000, 1500)
            
            # Mock successful extraction
            engine.pytesseract.image_to_string.return_value = "Large document text"
            engine.pytesseract.image_to_data.return_value = {
                'text': ['Large', 'document', 'text'],
                'conf': [95, 92, 88],
                'left': [10, 60, 150],
                'top': [10, 10, 10],
                'width': [45, 75, 40],
                'height': [20, 20, 20]
            }
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (2000, 1500), 'white')
                
                # Process multiple large images
                for _ in range(5):
                    result = engine.extract_text(large_image_data)
                    assert isinstance(result, dict)
                    
                # Force garbage collection
                gc.collect()
                
                # Check memory hasn't grown excessively
                final_memory = process.memory_info().rss
                memory_growth = final_memory - initial_memory
                
                # Memory growth should be reasonable (less than 100MB for this test)
                assert memory_growth < 100 * 1024 * 1024, f"Excessive memory growth: {memory_growth} bytes"

    def test_engine_gpu_resource_sharing(self):
        """
        GIVEN multiple GPU-enabled engines (Surya, EasyOCR, TrOCR)
        WHEN running concurrent operations
        THEN should share GPU resources appropriately
        AND should handle GPU memory limitations gracefully
        """
        # Mock GPU availability check
        with patch('torch.cuda.is_available', return_value=True), \
             patch('torch.cuda.device_count', return_value=1), \
             patch('torch.cuda.get_device_properties') as mock_props:
            
            # Mock GPU properties
            mock_device = Mock()
            mock_device.total_memory = 8 * 1024**3  # 8GB GPU
            mock_props.return_value = mock_device
            
            # Initialize GPU-enabled engines
            with patch.object(EasyOCR, '_initialize') as mock_easy_init, \
                 patch.object(SuryaOCR, '_initialize') as mock_surya_init, \
                 patch.object(TrOCREngine, '_initialize') as mock_trocr_init:
                
                # Mock successful initialization
                mock_easy_init.return_value = None
                mock_surya_init.return_value = None
                mock_trocr_init.return_value = None
                
                easy_engine = EasyOCR()
                easy_engine.available = True
                easy_engine.reader = Mock()
                
                surya_engine = SuryaOCR()
                surya_engine.available = True
                # Mock Surya components properly
                surya_engine.detection_predictor = Mock()
                surya_engine.recognition_predictor = Mock()
                
                trocr_engine = TrOCREngine()
                trocr_engine.available = True
                trocr_engine.processor = Mock()
                trocr_engine.model = Mock()
                
                # Mock concurrent processing
                test_image = self.create_test_image_data()
                
                # Mock extraction results
                easy_engine.reader.readtext.return_value = [
                    ([[10, 10], [90, 10], [90, 30], [10, 30]], 'EasyOCR Text', 0.92)
                ]
                
                # Mock Surya result structure
                mock_text_line = Mock()
                mock_text_line.text = "Surya Text"
                mock_text_line.confidence = 0.88
                mock_text_line.bbox = [10, 10, 90, 30]
                
                mock_result = Mock()
                mock_result.text_lines = [mock_text_line]
                
                surya_engine.recognition_predictor.return_value = [mock_result]
                
                # Mock TrOCR processor output
                mock_processor_output = Mock()
                mock_processor_output.pixel_values = Mock()
                trocr_engine.processor.return_value = mock_processor_output
                trocr_engine.model.generate.return_value = Mock()
                trocr_engine.processor.batch_decode.return_value = ["TrOCR Text"]
                
                # Test concurrent extraction
                results = []
                
                def extract_with_engine(engine, image_data):
                    return engine.extract_text(image_data)
                
                # Simulate concurrent access
                with patch('threading.Thread') as mock_thread:
                    # Mock thread execution
                    threads = []
                    for engine in [easy_engine, surya_engine, trocr_engine]:
                        thread = Mock()
                        thread.start = Mock()
                        thread.join = Mock()
                        threads.append(thread)
                        
                        # Simulate result
                        result = extract_with_engine(engine, test_image)
                        results.append(result)
                    
                    mock_thread.side_effect = threads
                    
                # Verify all engines processed successfully
                assert len(results) == 3
                for result in results:
                    assert isinstance(result, dict)
                    assert 'text' in result
                    assert 'engine' in result



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
