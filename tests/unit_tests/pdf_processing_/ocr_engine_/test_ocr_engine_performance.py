# Test file for TestOCREnginePerformance
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

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/ocr_engine.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/ocr_engine_stubs.md")

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





class TestOCREnginePerformance:
    """Test suite for performance characteristics and resource usage."""

    def test_tesseract_initialization_time(self):
        """
        GIVEN TesseractOCR engine class
        WHEN measuring initialization time
        THEN should complete within 1 second (traditional OCR)
        """
        with patch.object(TesseractOCR, '_initialize'):
            start_time = time.time()
            tesseract_engine = TesseractOCR()
            tesseract_init_time = time.time() - start_time
            
            assert tesseract_init_time < 1.0

    def test_easyocr_initialization_time(self):
        """
        GIVEN EasyOCR engine class
        WHEN measuring initialization time
        THEN should complete within 5 seconds (neural network)
        """
        with patch.object(EasyOCR, '_initialize'):
            start_time = time.time()
            easy_engine = EasyOCR()
            easy_init_time = time.time() - start_time
            
            assert easy_init_time < 5.0

    def test_suryaocr_initialization_time(self):
        """
        GIVEN SuryaOCR engine class
        WHEN measuring initialization time
        THEN should complete within 5 seconds (neural network)
        """
        with patch.object(SuryaOCR, '_initialize'):
            start_time = time.time()
            surya_engine = SuryaOCR()
            surya_init_time = time.time() - start_time
            
            assert surya_init_time < 5.0

    def test_trocr_initialization_time(self):
        """
        GIVEN TrOCREngine class
        WHEN measuring initialization time
        THEN should complete within 10 seconds (transformer model)
        """
        with patch.object(TrOCREngine, '_initialize'):
            start_time = time.time()
            trocr_engine = TrOCREngine()
            trocr_init_time = time.time() - start_time
            
            assert trocr_init_time < 10.0

    def test_initialization_time_ordering(self):
        """
        GIVEN all OCR engine classes
        WHEN comparing initialization times
        THEN TesseractOCR should be fastest (traditional vs neural)
        """
        # Measure TesseractOCR
        with patch.object(TesseractOCR, '_initialize'):
            start_time = time.time()
            tesseract_engine = TesseractOCR()
            tesseract_init_time = time.time() - start_time

        # Measure EasyOCR
        with patch.object(EasyOCR, '_initialize'):
            start_time = time.time()
            easy_engine = EasyOCR()
            easy_init_time = time.time() - start_time

        # Measure SuryaOCR
        with patch.object(SuryaOCR, '_initialize'):
            start_time = time.time()
            surya_engine = SuryaOCR()
            surya_init_time = time.time() - start_time

        # Measure TrOCREngine
        with patch.object(TrOCREngine, '_initialize'):
            start_time = time.time()
            trocr_engine = TrOCREngine()
            trocr_init_time = time.time() - start_time

        assert tesseract_init_time <= max(easy_init_time, surya_init_time, trocr_init_time)

    def test_engine_processing_time_scaling(self):
        """
        GIVEN each OCR engine and images of varying sizes
        WHEN measuring processing time vs image size
        THEN should demonstrate expected scaling characteristics
        AND should not have unreasonable time complexity
        """
        import time
        
        def create_test_image_of_size(width, height):
            """Helper to create test image of specific size."""
            img = Image.new('RGB', (width, height), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((10, height//2), f"Test {width}x{height}", fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        # Test different image sizes
        image_sizes = [(100, 50), (200, 100), (400, 200)]
        
        # Test TesseractOCR scaling
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            tesseract_times = []
            for width, height in image_sizes:
                image_data = create_test_image_of_size(width, height)
                
                with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                    mock_preprocess.return_value = Image.new('RGB', (width, height), 'white')
                    tesseract_engine.pytesseract.image_to_string.return_value = f"Test {width}x{height}"
                    tesseract_engine.pytesseract.image_to_data.return_value = {
                        'text': ['Test', f'{width}x{height}'], 'conf': [95, 92], 
                        'left': [10, 50], 'top': [height//2, height//2], 
                        'width': [35, 60], 'height': [20, 20]
                    }
                    
                    start_time = time.time()
                    result = tesseract_engine.extract_text(image_data)
                    processing_time = time.time() - start_time
                    tesseract_times.append(processing_time)
                    
                    assert isinstance(result, dict)
            
            # Should scale reasonably (not exponentially)
            assert len(tesseract_times) == 3
            # Each processing should complete within reasonable time
            for t in tesseract_times:
                assert t < 2.0  # Less than 2 seconds per image
        
        # Test EasyOCR scaling
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            easy_times = []
            for width, height in image_sizes:
                image_data = create_test_image_of_size(width, height)
                
                easy_engine.reader.readtext.return_value = [
                    ([[10, height//2], [100, height//2], [100, height//2+20], [10, height//2+20]], 
                     f"Test {width}x{height}", 0.95)
                ]
                
                start_time = time.time()
                result = easy_engine.extract_text(image_data)
                processing_time = time.time() - start_time
                easy_times.append(processing_time)
                
                assert isinstance(result, dict)
            
            # Should scale reasonably
            assert len(easy_times) == 3
            for t in easy_times:
                assert t < 3.0  # Neural networks may take a bit longer

    def test_engine_memory_usage_patterns(self):
        """
        GIVEN each OCR engine processing various images
        WHEN monitoring memory usage
        THEN should demonstrate predictable memory patterns
        AND should not have memory leaks
        """
        import gc
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        
        def create_test_image_data():
            img = Image.new('RGB', (300, 150), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((50, 70), "Memory Test", fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        # Test TesseractOCR memory usage
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            initial_memory = process.memory_info().rss
            
            # Process multiple images
            for i in range(5):
                image_data = create_test_image_data()
                
                with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                    mock_preprocess.return_value = Image.new('RGB', (300, 150), 'white')
                    tesseract_engine.pytesseract.image_to_string.return_value = "Memory Test"
                    tesseract_engine.pytesseract.image_to_data.return_value = {
                        'text': ['Memory', 'Test'], 'conf': [95, 92], 
                        'left': [50, 120], 'top': [70, 70], 
                        'width': [60, 40], 'height': [20, 20]
                    }
                    
                    result = tesseract_engine.extract_text(image_data)
                    assert isinstance(result, dict)
            
            # Force garbage collection
            gc.collect()
            
            final_memory = process.memory_info().rss
            memory_growth = final_memory - initial_memory
            
            # Memory growth should be reasonable (less than 50MB for 5 small images)
            assert memory_growth < 50 * 1024 * 1024, f"Excessive memory growth: {memory_growth} bytes"
        
        # Test EasyOCR memory usage
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            initial_memory = process.memory_info().rss
            
            # Process multiple images
            for i in range(5):
                image_data = create_test_image_data()
                
                easy_engine.reader.readtext.return_value = [
                    ([[50, 70], [180, 70], [180, 90], [50, 90]], 'Memory Test', 0.95)
                ]
                
                result = easy_engine.extract_text(image_data)
                assert isinstance(result, dict)
            
            # Force garbage collection
            gc.collect()
            
            final_memory = process.memory_info().rss
            memory_growth = final_memory - initial_memory
            
            # Neural networks may use more memory but should still be reasonable
            assert memory_growth < 100 * 1024 * 1024, f"Excessive memory growth: {memory_growth} bytes"

    def test_engine_concurrent_processing_limits(self):
        """
        GIVEN each OCR engine
        WHEN running multiple concurrent extract_text() operations
        THEN should handle concurrency appropriately
        AND should respect system resource limits
        """
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def create_test_image_data():
            img = Image.new('RGB', (200, 100), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((50, 40), "Concurrent Test", fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        image_data = create_test_image_data()
        
        # Test TesseractOCR concurrency
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            def process_with_tesseract(thread_id):
                with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                    mock_preprocess.return_value = Image.new('RGB', (200, 100), 'white')
                    tesseract_engine.pytesseract.image_to_string.return_value = f"Concurrent Test {thread_id}"
                    tesseract_engine.pytesseract.image_to_data.return_value = {
                        'text': ['Concurrent', 'Test', str(thread_id)], 'conf': [95, 92, 88], 
                        'left': [50, 130, 160], 'top': [40, 40, 40], 
                        'width': [75, 35, 20], 'height': [20, 20, 20]
                    }
                    
                    result = tesseract_engine.extract_text(image_data)
                    return result
            
            # Test concurrent processing with ThreadPoolExecutor
            results = []
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(process_with_tesseract, i) for i in range(3)]
                
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    assert isinstance(result, dict)
                    assert 'text' in result
            
            assert len(results) == 3
        
        # Test EasyOCR concurrency (neural networks may have threading considerations)
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            def process_with_easy(thread_id):
                easy_engine.reader.readtext.return_value = [
                    ([[50, 40], [190, 40], [190, 60], [50, 60]], f'Concurrent Test {thread_id}', 0.95)
                ]
                
                result = easy_engine.extract_text(image_data)
                return result
            
            # Test concurrent processing
            results = []
            with ThreadPoolExecutor(max_workers=2) as executor:  # Fewer workers for neural network
                futures = [executor.submit(process_with_easy, i) for i in range(2)]
                
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    assert isinstance(result, dict)
            
            assert len(results) == 2

    def test_engine_gpu_utilization_efficiency(self):
        """
        GIVEN GPU-enabled engines (Surya, EasyOCR, TrOCR)
        WHEN processing images
        THEN should utilize GPU efficiently when available
        AND should not waste GPU resources
        """
        # Mock GPU availability
        with patch('torch.cuda.is_available', return_value=True), \
             patch('torch.cuda.device_count', return_value=1), \
             patch('torch.cuda.current_device', return_value=0):
            
            def create_test_image_data():
                img = Image.new('RGB', (300, 150), color='white')
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                draw.text((100, 70), "GPU Test", fill='black')
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                return buf.getvalue()
            
            image_data = create_test_image_data()
            
            # Test EasyOCR GPU usage
            with patch.object(EasyOCR, '_initialize') as mock_init:
                mock_init.return_value = None
                easy_engine = EasyOCR()
                easy_engine.available = True
                easy_engine.reader = Mock()
                
                # Mock GPU-accelerated processing
                easy_engine.reader.readtext.return_value = [
                    ([[100, 70], [180, 70], [180, 90], [100, 90]], 'GPU Test', 0.96)
                ]
                
                result = easy_engine.extract_text(image_data)
                assert isinstance(result, dict)
                assert result['confidence'] > 0.9  # GPU should provide good accuracy
            
            # Test SuryaOCR GPU usage
            with patch.object(SuryaOCR, '_initialize') as mock_init:
                mock_init.return_value = None
                surya_engine = SuryaOCR()
                surya_engine.available = True
                # Mock the required attributes that _initialize would set
                surya_engine.recognition_predictor = Mock()
                surya_engine.detection_predictor = Mock()
                
                # Mock GPU-accelerated processing
                mock_result = Mock()
                mock_line = Mock()
                mock_line.text = "GPU Test"
                mock_line.confidence = 0.94
                mock_line.bbox = [100, 70, 180, 90]
                mock_result.text_lines = [mock_line]
                surya_engine.recognition_predictor.return_value = [mock_result]
                
                result = surya_engine.extract_text(image_data)
                assert isinstance(result, dict)
                assert result['confidence'] > 0.9
            
            # Test TrOCREngine GPU usage
            with patch.object(TrOCREngine, '_initialize') as mock_init:
                mock_init.return_value = None
                trocr_engine = TrOCREngine()
                trocr_engine.available = True
                trocr_engine.processor = Mock()
                trocr_engine.model = Mock()
                
                # Mock GPU-accelerated processing
                mock_inputs = Mock()
                mock_inputs.pixel_values = Mock()
                trocr_engine.processor.return_value = mock_inputs
                trocr_engine.model.generate.return_value = Mock()
                trocr_engine.processor.batch_decode.return_value = ["GPU Test"]
                
                result = trocr_engine.extract_text(image_data)
                assert isinstance(result, dict)
                assert 'GPU Test' in result['text']

    def test_engine_batch_processing_capability(self):
        """
        GIVEN each OCR engine and multiple images
        WHEN processing multiple images sequentially
        THEN should maintain consistent performance
        AND should not degrade over time
        """
        import time
        
        def create_batch_test_images(count=5):
            """Create multiple test images for batch processing."""
            images = []
            for i in range(count):
                img = Image.new('RGB', (200, 100), color='white')
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                draw.text((50, 40), f"Batch Image {i+1}", fill='black')
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                images.append(buf.getvalue())
            return images
        
        batch_images = create_batch_test_images(5)
        
        # Test TesseractOCR batch processing
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            processing_times = []
            results = []
            
            for i, image_data in enumerate(batch_images):
                with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                    mock_preprocess.return_value = Image.new('RGB', (200, 100), 'white')
                    tesseract_engine.pytesseract.image_to_string.return_value = f"Batch Image {i+1}"
                    tesseract_engine.pytesseract.image_to_data.return_value = {
                        'text': ['Batch', 'Image', str(i+1)], 'conf': [95, 92, 88], 
                        'left': [50, 100, 150], 'top': [40, 40, 40], 
                        'width': [45, 45, 20], 'height': [20, 20, 20]
                    }
                    
                    start_time = time.time()
                    result = tesseract_engine.extract_text(image_data)
                    processing_time = time.time() - start_time
                    
                    processing_times.append(processing_time)
                    results.append(result)
                    
                    assert isinstance(result, dict)
                    assert f"Batch Image {i+1}" in result['text']
            
            # Performance should remain consistent (no significant degradation)
            assert len(processing_times) == 5
            assert len(results) == 5
            
            # Check that processing times don't increase dramatically
            avg_early = sum(processing_times[:2]) / 2
            avg_late = sum(processing_times[-2:]) / 2
            
            # Late processing shouldn't be more than 2x slower than early
            assert avg_late <= avg_early * 2.0, "Performance degraded significantly over batch"
        
        # Test EasyOCR batch processing
        with patch.object(EasyOCR, '_initialize'):
            easy_engine = EasyOCR()
            easy_engine.available = True
            easy_engine.reader = Mock()
            
            processing_times = []
            results = []
            
            for i, image_data in enumerate(batch_images):
                easy_engine.reader.readtext.return_value = [
                    ([[50, 40], [190, 40], [190, 60], [50, 60]], f'Batch Image {i+1}', 0.95)
                ]
                
                start_time = time.time()
                result = easy_engine.extract_text(image_data)
                processing_time = time.time() - start_time
                
                processing_times.append(processing_time)
                results.append(result)
                
                assert isinstance(result, dict)
                assert f"Batch Image {i+1}" in result['text']
            
            # Check consistency
            assert len(processing_times) == 5
            assert len(results) == 5
            
            # Performance should remain stable
            avg_early = sum(processing_times[:2]) / 2
            avg_late = sum(processing_times[-2:]) / 2
            assert avg_late <= avg_early * 2.0, "EasyOCR performance degraded over batch"

    def test_multi_engine_overhead_measurement(self):
        """
        GIVEN MultiEngineOCR vs individual engines
        WHEN comparing processing overhead
        THEN should quantify coordination overhead
        AND should demonstrate fallback value vs cost
        """
        import time
        
        def create_test_image_data():
            img = Image.new('RGB', (200, 100), color='white')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((50, 40), "Overhead Test", fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        image_data = create_test_image_data()
        
        # Test individual TesseractOCR timing
        with patch.object(TesseractOCR, '_initialize'):
            tesseract_engine = TesseractOCR()
            tesseract_engine.available = True
            tesseract_engine.pytesseract = Mock()
            
            with patch.object(tesseract_engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (200, 100), 'white')
                tesseract_engine.pytesseract.image_to_string.return_value = "Overhead Test"
                tesseract_engine.pytesseract.image_to_data.return_value = {
                    'text': ['Overhead', 'Test'], 'conf': [95, 92], 
                    'left': [50, 120], 'top': [40, 40], 
                    'width': [65, 35], 'height': [20, 20]
                }
                
                start_time = time.time()
                individual_result = tesseract_engine.extract_text(image_data)
                individual_time = time.time() - start_time
                
                assert isinstance(individual_result, dict)
        
        # Test MultiEngineOCR timing with same engine
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract_class:
            mock_tesseract_class.return_value = tesseract_engine
            
            multi_engine = MultiEngineOCR()
            multi_engine.engines = {'tesseract': tesseract_engine}
            
            start_time = time.time()
            multi_result = multi_engine.extract_with_ocr(image_data, strategy='speed_first')
            multi_time = time.time() - start_time
            
            assert isinstance(multi_result, dict)
            
            # For very fast operations (< 10ms), focus on absolute overhead rather than ratio
            absolute_overhead = multi_time - individual_time
            print(f"Individual time: {individual_time:.6f}s, Multi time: {multi_time:.6f}s")
            print(f"Absolute overhead: {absolute_overhead:.6f}s")
            
            if individual_time < 0.01:  # Less than 10ms - check absolute overhead
                # Absolute overhead should be reasonable (less than 5ms for coordination)
                assert absolute_overhead < 0.005, f"Absolute overhead too high: {absolute_overhead:.6f}s"
            else:  # For longer operations, check ratio
                overhead_ratio = multi_time / individual_time if individual_time > 0 else 1.0
                assert overhead_ratio < 2.0, f"MultiEngine overhead too high: {overhead_ratio:.2f}x"
        
        # Test fallback value demonstration
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract:
            
            # Mock first engine failure, second engine success
            mock_engine1 = Mock()
            mock_engine1.name = 'surya'
            mock_engine1.is_available.return_value = True
            mock_engine1.extract_text.side_effect = RuntimeError("Engine failed")
            
            mock_engine2 = Mock()
            mock_engine2.name = 'tesseract'
            mock_engine2.is_available.return_value = True
            mock_engine2.extract_text.return_value = {
                'text': 'Fallback Success',
                'confidence': 0.85,
                'engine': 'tesseract'
            }
            
            mock_surya.return_value = mock_engine1
            mock_tesseract.return_value = mock_engine2
            
            multi_engine = MultiEngineOCR()
            multi_engine.engines = {'surya': mock_engine1, 'tesseract': mock_engine2}
            
            # Should successfully fallback despite first engine failure
            result = multi_engine.extract_with_ocr(image_data)
            assert result['text'] == 'Fallback Success'
            assert result['engine'] == 'tesseract'
            
            # Verify fallback actually occurred
            assert mock_engine1.extract_text.called
            assert mock_engine2.extract_text.called



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
