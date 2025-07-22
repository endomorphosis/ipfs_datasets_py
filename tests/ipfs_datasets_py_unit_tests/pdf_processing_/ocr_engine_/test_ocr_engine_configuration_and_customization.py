# Test file for TestOCREngineConfigurationAndCustomization
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
    raise_on_bad_callable_metadata,
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




class TestOCREngineConfigurationAndCustomization:
    """Test suite for configuration options and customization capabilities."""

    def create_test_image_data(self):
        """Create valid test image data as bytes"""
        img = Image.new('RGB', (300, 100), color='white')
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.text((20, 40), "Test Text 123", fill='black')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def create_test_image(self):
        """Create a test PIL Image object"""
        img = Image.new('RGB', (300, 100), color='white')
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.text((20, 40), "Test Text 123", fill='black')
        return img

    def test_tesseract_psm_configuration_impact(self):
        """
        GIVEN TesseractOCR with different PSM (Page Segmentation Mode) settings
        WHEN processing various document layouts
        THEN should demonstrate different behavior based on PSM mode
        AND should optimize for specified layout types
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            # Create a test image
            test_image_data = self.create_test_image_data()
            mock_image = self.create_test_image()
            
            with patch.object(engine, '_get_image_data', return_value=mock_image), \
                 patch.object(engine, '_preprocess_image', return_value=mock_image):
                
                # Test different PSM modes for different layout types
                layout_tests = [
                    # (PSM mode, expected config, layout description)
                    (3, '--psm 3', 'Fully automatic page segmentation'),
                    (6, '--psm 6', 'Uniform block of text'),
                    (7, '--psm 7', 'Single text line'),
                    (8, '--psm 8', 'Single word'),
                    (10, '--psm 10', 'Single character'),
                    (13, '--psm 13', 'Raw line fitting character')
                ]
                
                for psm_mode, config_str, description in layout_tests:
                    # Configure mock to return different results for different PSM modes
                    expected_output = f"OCR output for PSM {psm_mode} - {description}"
                    engine.pytesseract.image_to_string.return_value = expected_output
                    engine.pytesseract.image_to_data.return_value = {
                        'text': [expected_output],
                        'conf': [90],
                        'left': [10],
                        'top': [10],
                        'width': [100],
                        'height': [20]
                    }
                    
                    result = engine.extract_text(test_image_data, config=config_str)
                    
                    # Verify the call was made with correct PSM config
                    engine.pytesseract.image_to_string.assert_called()
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '') if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else ''
                    
                    assert config_str in config_used, \
                        f"PSM config '{config_str}' not found in: {config_used}"
                    assert result['text'] == expected_output
                
                # Test combined PSM with other Tesseract options
                complex_configs = [
                    '--psm 6 -c tessedit_char_whitelist=0123456789',
                    '--psm 7 --oem 3',
                    '--psm 8 -c preserve_interword_spaces=1'
                ]
                
                for complex_config in complex_configs:
                    engine.pytesseract.image_to_string.return_value = "Complex config result"
                    engine.pytesseract.image_to_data.return_value = {
                        'text': ["Complex config result"],
                        'conf': [95],
                        'left': [10],
                        'top': [10],
                        'width': [120],
                        'height': [20]
                    }
                    result = engine.extract_text(test_image_data, config=complex_config)
                    
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '') if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else ''
                    assert complex_config == config_used, \
                        f"Complex config not preserved: expected '{complex_config}', got '{config_used}'"
                
                # Test invalid PSM handling
                engine.pytesseract.image_to_string.side_effect = Exception("Invalid PSM mode")
                
                with pytest.raises(Exception):
                    engine.extract_text(test_image_data, config='--psm 99')  # Invalid PSM
                
                # Reset for remaining tests
                engine.pytesseract.image_to_string.side_effect = None
                
                # Test that different PSM modes can handle different content types
                content_scenarios = [
                    ('document_page', '--psm 1', 'Full page analysis'),
                    ('text_block', '--psm 6', 'Uniform text block'),
                    ('single_line', '--psm 7', 'Text line'),
                    ('word_only', '--psm 8', 'Single word'),
                    ('sparse_text', '--psm 11', 'Sparse text')
                ]
                
                for scenario, psm_config, expected_behavior in content_scenarios:
                    engine.pytesseract.image_to_string.return_value = f"Result for {scenario}"
                    engine.pytesseract.image_to_data.return_value = {
                        'text': [f"Result for {scenario}"],
                        'conf': [88],
                        'left': [10],
                        'top': [10],
                        'width': [100],
                        'height': [20]
                    }
                    result = engine.extract_text(test_image_data, config=psm_config)
                    
                    assert result['text'] == f"Result for {scenario}"
                    
                    # Verify config was applied
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '') if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else ''
                    assert psm_config in config_used
                
                # Test default behavior (no PSM specified)
                engine.pytesseract.image_to_string.return_value = "Default PSM result"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ["Default PSM result"],
                    'conf': [85],
                    'left': [10],
                    'top': [10],
                    'width': [100],
                    'height': [20]
                }
                result = engine.extract_text(test_image_data)
                assert result['text'] == "Default PSM result"

    def test_tesseract_language_configuration(self):
        """
        GIVEN TesseractOCR with different language configurations
        WHEN processing non-English text with actual language parameters
        THEN should pass correct language codes to tesseract
        AND should demonstrate language-specific OCR behavior
        """
        # Create test image with Spanish text
        def create_spanish_test_image():
            img = Image.new('RGB', (300, 80), color='white')
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)
            try:
                # Try to use a better font if available
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
            except (IOError, OSError):
                font = ImageFont.load_default()
            draw.text((20, 30), "Niño pequeño", font=font, fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        # Create test image with German text
        def create_german_test_image():
            img = Image.new('RGB', (300, 80), color='white')
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
            except (IOError, OSError):
                font = ImageFont.load_default()
            draw.text((20, 30), "Größe Mädchen", font=font, fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        
        spanish_image = create_spanish_test_image()
        german_image = create_german_test_image()
        
        # Test actual TesseractOCR instance (with mocked pytesseract calls)
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            # Mock only the pytesseract calls to verify correct parameters are passed
            with patch.object(engine, '_get_image_data') as mock_get_image, \
                 patch.object(engine, '_preprocess_image') as mock_preprocess:
                
                mock_get_image.return_value = self.create_test_image()
                mock_preprocess.return_value = self.create_test_image()
                
                # Configure mocks for Spanish
                engine.pytesseract.image_to_string.return_value = "Niño pequeño"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['Niño', 'pequeño'], 'conf': [92, 89], 
                    'left': [20, 80], 'top': [30, 30], 
                    'width': [50, 70], 'height': [20, 20]
                }
                
                # Test Spanish language parameter using config string
                result_spanish = engine.extract_text(spanish_image, config='--psm 6 -l spa')
                
                # Verify pytesseract was called with Spanish language
                engine.pytesseract.image_to_string.assert_called()
                call_args = engine.pytesseract.image_to_string.call_args
                config_used = call_args[1].get('config', '') if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else ''
                
                # Should contain Spanish language specification
                assert 'spa' in config_used, f"Spanish language config not found in: {config_used}"
                assert result_spanish['text'] == "Niño pequeño"
                assert result_spanish['engine'] == 'tesseract'
                
                # Reset mocks for German test
                engine.pytesseract.image_to_string.reset_mock()
                engine.pytesseract.image_to_data.reset_mock()
                
                # Configure mocks for German
                engine.pytesseract.image_to_string.return_value = "Größe Mädchen"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['Größe', 'Mädchen'], 'conf': [88, 91], 
                    'left': [20, 90], 'top': [30, 30], 
                    'width': [60, 80], 'height': [20, 20]
                }
                
                # Test German language parameter
                result_german = engine.extract_text(german_image, config='--psm 6 -l deu')
                
                # Verify pytesseract was called with German language
                engine.pytesseract.image_to_string.assert_called()
                call_args = engine.pytesseract.image_to_string.call_args
                config_used = call_args[1].get('config', '') if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else ''
                
                # Should contain German language specification
                assert 'deu' in config_used, f"German language config not found in: {config_used}"
                assert result_german['text'] == "Größe Mädchen"
                assert result_german['engine'] == 'tesseract'
                
                # Test multiple languages
                engine.pytesseract.image_to_string.reset_mock()
                engine.pytesseract.image_to_string.return_value = "Mixed español and English"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['Mixed', 'español', 'and', 'English'], 'conf': [85, 90, 88, 92], 
                    'left': [20, 60, 120, 150], 'top': [30, 30, 30, 30], 
                    'width': [40, 50, 30, 50], 'height': [20, 20, 20, 20]
                }
                
                result_multi = engine.extract_text(spanish_image, config='--psm 6 -l spa+eng')
                
                # Verify multiple language specification
                engine.pytesseract.image_to_string.assert_called()
                call_args = engine.pytesseract.image_to_string.call_args
                config_used = call_args[1].get('config', '') if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else ''
                
                # Should contain multiple language specification
                assert 'spa+eng' in config_used or ('spa' in config_used and 'eng' in config_used), \
                    f"Multi-language config not found in: {config_used}"
                assert result_multi['text'] == "Mixed español and English"

    def test_tesseract_character_whitelist_effectiveness(self):
        """
        GIVEN TesseractOCR with character whitelist configuration
        WHEN processing text with mixed character types
        THEN should filter output to whitelisted characters only
        AND should improve accuracy for domain-specific text
        """
        with patch.object(TesseractOCR, '_initialize'):
            engine = TesseractOCR()
            engine.available = True
            engine.pytesseract = Mock()
            
            def create_mixed_text_image():
                img = Image.new('RGB', (250, 100), color='white')
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                draw.text((20, 40), "ABC123!@#", fill='black')  # Mixed characters
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                return buf.getvalue()
            
            image_data = create_mixed_text_image()
            
            with patch.object(engine, '_get_image_data') as mock_get_image, \
                 patch.object(engine, '_preprocess_image') as mock_preprocess:
                
                mock_get_image.return_value = self.create_test_image()
                mock_preprocess.return_value = self.create_test_image()
                
                # Test without character whitelist (all characters)
                engine.pytesseract.image_to_string.return_value = "ABC123!@#"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['ABC123!@#'], 'conf': [78], 
                    'left': [20], 'top': [40], 
                    'width': [180], 'height': [20]
                }
                
                result_all_chars = engine.extract_text(image_data)
                assert isinstance(result_all_chars, dict)
                assert "ABC123!@#" in result_all_chars['text']
                
                # Test with numbers-only whitelist (simulate configuration)
                engine.pytesseract.image_to_string.return_value = "123"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['123'], 'conf': [95], 
                    'left': [65], 'top': [40], 
                    'width': [40], 'height': [20]
                }
                
                numbers_config = "--psm 6 -c tessedit_char_whitelist=0123456789"
                result_numbers_only = engine.extract_text(image_data, config=numbers_config)
                assert isinstance(result_numbers_only, dict)
                assert result_numbers_only['text'] == "123"
                
                # Whitelist should improve confidence for domain-specific text
                assert result_numbers_only['confidence'] > result_all_chars['confidence']
                
                # Test with letters-only whitelist
                engine.pytesseract.image_to_string.return_value = "ABC"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['ABC'], 'conf': [92], 
                    'left': [20], 'top': [40], 
                    'width': [45], 'height': [20]
                }
                
                letters_config = "--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                result_letters_only = engine.extract_text(image_data, config=letters_config)
                assert isinstance(result_letters_only, dict)
                assert result_letters_only['text'] == "ABC"
                assert result_letters_only['confidence'] > 0.9
                
                # Verify configurations were applied
                call_args = engine.pytesseract.image_to_string.call_args
                config_used = call_args[1].get('config', '') if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else ''
                assert "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ" in config_used

    def test_surya_language_specification_impact(self):
        """
        GIVEN SuryaOCR with different language specifications
        WHEN processing multilingual content
        THEN should adapt recognition based on specified languages
        AND should handle language switching within documents
        """
        with patch.object(SuryaOCR, '_initialize'):
            engine = SuryaOCR()
            engine.available = True
            engine.detection_predictor = Mock()
            engine.det_model = Mock()
            engine.rec_model = Mock()
            
            # Create mock text line objects
            mock_text_line_1 = Mock()
            mock_text_line_1.text = "Hello"
            mock_text_line_1.confidence = 0.95
            mock_text_line_1.bbox = [10, 10, 50, 30]
            
            mock_text_line_2 = Mock()
            mock_text_line_2.text = "Hola"
            mock_text_line_2.confidence = 0.92
            mock_text_line_2.bbox = [60, 10, 90, 30]
            
            mock_text_line_3 = Mock()
            mock_text_line_3.text = "Bonjour"
            mock_text_line_3.confidence = 0.89
            mock_text_line_3.bbox = [100, 10, 150, 30]
            
            mock_text_line_4 = Mock()
            mock_text_line_4.text = "你好"
            mock_text_line_4.confidence = 0.87
            mock_text_line_4.bbox = [160, 10, 190, 30]
            
            # Mock the recognition_predictor to return proper structure
            mock_result = Mock()
            mock_result.text_lines = [mock_text_line_1, mock_text_line_2, mock_text_line_3, mock_text_line_4]
            
            engine.recognition_predictor = Mock()
            engine.recognition_predictor.return_value = [mock_result]
            
            image_data = self.create_test_image_data()
            
            with patch.object(engine, '_get_image_data') as mock_get_image:
                mock_get_image.return_value = self.create_test_image()
                
                # Test multilingual content processing
                result = engine.extract_text(image_data)
                
                # Should have processed multilingual content
                assert result['engine'] == 'surya'
                text = result['text']
                assert 'Hello' in text
                assert 'Hola' in text
                assert 'Bonjour' in text
                assert '你好' in text
                
                # Verify the recognition_predictor was called
                engine.recognition_predictor.assert_called_once()
                
                # Check text blocks are included
                assert 'text_blocks' in result
                assert len(result['text_blocks']) == 4
                
                # Test single language specification - reset the mock
                engine.recognition_predictor.reset_mock()
                mock_text_line_single = Mock()
                mock_text_line_single.text = "English only"
                mock_text_line_single.confidence = 0.96
                mock_text_line_single.bbox = [10, 10, 100, 30]
                
                mock_result_single = Mock()
                mock_result_single.text_lines = [mock_text_line_single]
                engine.recognition_predictor.return_value = [mock_result_single]
                
                result_en = engine.extract_text(image_data)
                assert 'English only' in result_en['text']
                assert result_en['confidence'] == 0.96

    def test_multi_engine_strategy_customization(self):
        """
        GIVEN MultiEngineOCR with custom strategy definitions
        WHEN processing documents with known characteristics
        THEN should allow strategy customization beyond built-in options
        AND should support user-defined engine ordering
        """
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easy, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr:
            
            # Set up all engines
            mock_surya.return_value = MockOCREngine('surya', True, confidence=0.95, text="surya custom")
            mock_tesseract.return_value = MockOCREngine('tesseract', True, confidence=0.85, text="tesseract custom")
            mock_easy.return_value = MockOCREngine('easyocr', True, confidence=0.80, text="easy custom")
            mock_trocr.return_value = MockOCREngine('trocr', True, confidence=0.75, text="trocr custom")
            
            multi_ocr = MultiEngineOCR()
            image_data = self.create_test_image_data()
            
            # Test that different strategies exist and work
            strategies = ['quality_first', 'speed_first', 'accuracy_first']
            
            for strategy in strategies:
                result = multi_ocr.extract_with_ocr(
                    image_data, 
                    strategy=strategy, 
                    confidence_threshold=0.7
                )
                
                # Should return valid result
                assert isinstance(result, dict)
                assert 'engine' in result
                assert 'text' in result
                assert 'confidence' in result
                assert result['engine'] in ['surya', 'tesseract', 'easyocr', 'trocr']
                assert 'custom' in result['text']
            
            # Test invalid strategy handling
            with pytest.raises(ValueError):
                multi_ocr.extract_with_ocr(image_data, strategy='invalid_strategy')
                
            # Test custom strategy concept (if implemented)
            # For now, verify that we can at least specify the built-in strategies
            available_engines = multi_ocr.get_available_engines()
            assert len(available_engines) == 4
            assert set(available_engines) == {'surya', 'tesseract', 'easyocr', 'trocr'}

    def test_confidence_threshold_sensitivity_analysis(self):
        """
        GIVEN MultiEngineOCR with varying confidence thresholds
        WHEN processing documents of different quality levels
        THEN should demonstrate threshold impact on fallback behavior
        AND should help optimize threshold values for use cases
        """
        # Mock all engines as available
        with patch('ipfs_datasets_py.pdf_processing.ocr_engine.TesseractOCR') as mock_tesseract_cls, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.EasyOCR') as mock_easyocr_cls, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.SuryaOCR') as mock_surya_cls, \
             patch('ipfs_datasets_py.pdf_processing.ocr_engine.TrOCREngine') as mock_trocr_cls:
            
            # Set up mock engines with different confidence scenarios
            mock_tesseract = MockOCREngine('tesseract', True, confidence=0.85, text="Primary OCR result")
            mock_easyocr = MockOCREngine('easyocr', True, confidence=0.75, text="Fallback OCR result") 
            mock_surya = MockOCREngine('surya', True, confidence=0.95, text="High quality OCR result")
            mock_trocr = MockOCREngine('trocr', True, confidence=0.65, text="Low confidence OCR result")
            
            mock_tesseract_cls.return_value = mock_tesseract
            mock_easyocr_cls.return_value = mock_easyocr
            mock_surya_cls.return_value = mock_surya
            mock_trocr_cls.return_value = mock_trocr
            
            # Create test data
            test_image_data = self.create_test_image_data()
            
            # Test different confidence scenarios
            confidence_scenarios = [
                # (threshold, expected_engine, expected_behavior)
                (0.50, 'surya', "high_confidence_primary"),
                (0.70, 'tesseract', "fallback_better"),
                (0.80, 'tesseract', "both_medium_confidence"),
                (0.90, 'surya', "only_high_quality_accepted")
            ]
            
            for threshold, expected_engine, scenario in confidence_scenarios:
                multi_engine = MultiEngineOCR()
                
                # Call extract_with_ocr with threshold
                result = multi_engine.extract_with_ocr(
                    test_image_data, 
                    confidence_threshold=threshold
                )
                
                # Verify behavior based on threshold
                assert isinstance(result, dict)
                assert 'text' in result
                assert 'confidence' in result
                assert 'engine' in result
                
                # Verify that the engine with confidence >= threshold was used
                # or that the best available engine was used if none meet threshold
                assert result['confidence'] >= threshold or result['confidence'] == max(0.95, 0.85, 0.75, 0.65)
            
            # Test edge cases
            multi_engine = MultiEngineOCR()
            
            # Test with very high threshold (should use best available)
            result = multi_engine.extract_with_ocr(test_image_data, confidence_threshold=0.99)
            assert isinstance(result, dict)
            assert result['confidence'] > 0  # Should still return something
            
            # Test threshold of 0.0 (should accept any result)
            result = multi_engine.extract_with_ocr(test_image_data, confidence_threshold=0.0)
            assert isinstance(result, dict)
            assert result['confidence'] >= 0.0
            
            # Test that we get available engines
            available_engines = multi_engine.get_available_engines()
            assert len(available_engines) > 0
            assert isinstance(available_engines, list)



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
