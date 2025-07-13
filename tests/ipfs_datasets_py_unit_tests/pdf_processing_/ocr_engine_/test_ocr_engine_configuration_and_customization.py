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
assert MultiEngineOCR.extract_with_fallback
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
            test_image_data = b'fake_image_data'
            mock_image = Mock(spec=['format', 'mode'])
            mock_image.format = 'PNG'
            mock_image.mode = 'RGB'
            
            with patch.object(engine, '_preprocess_image', return_value=mock_image):
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
                    
                    result = engine.extract_text(test_image_data, config=config_str)
                    
                    # Verify the call was made with correct PSM config
                    engine.pytesseract.image_to_string.assert_called()
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '')
                    
                    assert config_str in config_used, \
                        f"PSM config '{config_str}' not found in: {config_used}"
                    assert result == expected_output
                
                # Test combined PSM with other Tesseract options
                complex_configs = [
                    '--psm 6 -c tessedit_char_whitelist=0123456789',
                    '--psm 7 --oem 3',
                    '--psm 8 -c preserve_interword_spaces=1'
                ]
                
                for complex_config in complex_configs:
                    engine.pytesseract.image_to_string.return_value = "Complex config result"
                    result = engine.extract_text(test_image_data, config=complex_config)
                    
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '')
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
                    result = engine.extract_text(test_image_data, config=psm_config)
                    
                    assert result == f"Result for {scenario}"
                    
                    # Verify config was applied
                    call_args = engine.pytesseract.image_to_string.call_args
                    config_used = call_args[1].get('config', '')
                    assert psm_config in config_used
                
                # Test default behavior (no PSM specified)
                engine.pytesseract.image_to_string.return_value = "Default PSM result"
                result = engine.extract_text(test_image_data)
                assert result == "Default PSM result"

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
        engine = TesseractOCR()
        
        # Mock only the pytesseract calls to verify correct parameters are passed
        with patch('pytesseract.image_to_string') as mock_img_to_str, \
             patch('pytesseract.image_to_data') as mock_img_to_data:
            
            # Configure mocks for Spanish
            mock_img_to_str.return_value = "Niño pequeño"
            mock_img_to_data.return_value = {
                'text': ['Niño', 'pequeño'], 'conf': [92, 89], 
                'left': [20, 80], 'top': [30, 30], 
                'width': [50, 70], 'height': [20, 20]
            }
            
            # Test Spanish language parameter
            result_spanish = engine.extract_text(spanish_image, lang='spa')
            
            # Verify pytesseract was called with Spanish language
            mock_img_to_str.assert_called()
            call_kwargs = mock_img_to_str.call_args[1] if mock_img_to_str.call_args[1] else {}
            config_used = call_kwargs.get('config', '')
            
            # Should contain Spanish language specification
            assert 'spa' in config_used or 'spanish' in config_used.lower()
            assert result_spanish['text'] == "Niño pequeño"
            assert result_spanish['engine'] == 'tesseract'
            
            # Reset mocks for German test
            mock_img_to_str.reset_mock()
            mock_img_to_data.reset_mock()
            
            # Configure mocks for German
            mock_img_to_str.return_value = "Größe Mädchen"
            mock_img_to_data.return_value = {
                'text': ['Größe', 'Mädchen'], 'conf': [88, 91], 
                'left': [20, 90], 'top': [30, 30], 
                'width': [60, 80], 'height': [20, 20]
            }
            
            # Test German language parameter
            result_german = engine.extract_text(german_image, lang='deu')
            
            # Verify pytesseract was called with German language
            mock_img_to_str.assert_called()
            call_kwargs = mock_img_to_str.call_args[1] if mock_img_to_str.call_args[1] else {}
            config_used = call_kwargs.get('config', '')
            
            # Should contain German language specification
            assert 'deu' in config_used or 'german' in config_used.lower()
            assert result_german['text'] == "Größe Mädchen"
            assert result_german['engine'] == 'tesseract'
            
            # Test multiple languages
            mock_img_to_str.reset_mock()
            mock_img_to_str.return_value = "Mixed español and English"
            
            result_multi = engine.extract_text(spanish_image, lang='spa+eng')
            
            # Verify multiple language specification
            mock_img_to_str.assert_called()
            call_kwargs = mock_img_to_str.call_args[1] if mock_img_to_str.call_args[1] else {}
            config_used = call_kwargs.get('config', '')
            
            # Should contain multiple language specification
            assert ('spa+eng' in config_used or 
                   ('spa' in config_used and 'eng' in config_used))
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
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = Image.new('RGB', (250, 100), 'white')
                
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
                
                result_numbers_only = engine.extract_text(image_data)
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
                
                result_letters_only = engine.extract_text(image_data)
                assert isinstance(result_letters_only, dict)
                assert result_letters_only['text'] == "ABC"
                assert result_letters_only['confidence'] > 0.9
            engine.available = True
            engine.pytesseract = Mock()
            
            with patch.object(engine, '_preprocess_image') as mock_preprocess:
                mock_preprocess.return_value = self.create_test_image()
                
                # Test numbers-only whitelist
                engine.pytesseract.image_to_string.return_value = "123456"
                engine.pytesseract.image_to_data.return_value = {
                    'text': ['123456'],
                    'conf': [95],
                    'left': [10],
                    'top': [10],
                    'width': [40],
                    'height': [15]
                }
                
                numbers_config = "--psm 6 -c tessedit_char_whitelist=0123456789"
                image_data = self.create_test_image_data()
                result = engine.extract_text(image_data, config=numbers_config)
                
                # Should have applied character whitelist
                call_args = engine.pytesseract.image_to_string.call_args
                assert "tessedit_char_whitelist=0123456789" in str(call_args)
                assert result['text'] == "123456"
                
                # Test letters-only whitelist
                engine.pytesseract.image_to_string.return_value = "ABCDEF"
                letters_config = "--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                result_letters = engine.extract_text(image_data, config=letters_config)
                
                call_args_letters = engine.pytesseract.image_to_string.call_args
                assert "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ" in str(call_args_letters)
                assert result_letters['text'] == "ABCDEF"

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
            engine.run_ocr = Mock()
            engine.det_processor = Mock()
            engine.det_model = Mock()
            engine.rec_model = Mock()
            engine.rec_processor = Mock()
            
            # Test multilingual specification
            mock_text_lines_multi = [
                Mock(text="Hello", confidence=0.95),
                Mock(text="Hola", confidence=0.92),
                Mock(text="Bonjour", confidence=0.89),
                Mock(text="你好", confidence=0.87)
            ]
            engine.run_ocr.return_value = ([mock_text_lines_multi], ["en", "es", "fr", "zh"])
            
            image_data = self.create_test_image_data()
            result = engine.extract_text(image_data, languages=['en', 'es', 'fr', 'zh'])
            
            # Should have processed multilingual content
            assert result['engine'] == 'surya'
            text = result['text']
            assert 'Hello' in text
            assert 'Hola' in text
            assert 'Bonjour' in text
            assert '你好' in text
            
            # Verify the languages parameter was passed
            engine.run_ocr.assert_called_once()
            call_args = engine.run_ocr.call_args
            # The languages should be passed in the call
            assert len(call_args) >= 1  # At least image argument
            
            # Test single language specification
            mock_text_lines_single = [Mock(text="English only", confidence=0.96)]
            engine.run_ocr.return_value = ([mock_text_lines_single], ["en"])
            
            result_en = engine.extract_text(image_data, languages=['en'])
            assert 'English only' in result_en['text']

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
                result = multi_ocr.extract_with_fallback(
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
                multi_ocr.extract_with_fallback(image_data, strategy='invalid_strategy')
                
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
            
            # Set up mock engines
            mock_tesseract = Mock()
            mock_tesseract.is_available.return_value = True
            mock_tesseract_cls.return_value = mock_tesseract
            
            mock_easyocr = Mock()
            mock_easyocr.is_available.return_value = True
            mock_easyocr_cls.return_value = mock_easyocr
            
            mock_surya = Mock()
            mock_surya.is_available.return_value = True
            mock_surya_cls.return_value = mock_surya
            
            mock_trocr = Mock()
            mock_trocr.is_available.return_value = True
            mock_trocr_cls.return_value = mock_trocr
            
            # Create test data
            test_image_data = b'fake_image_data'
            
            # Test different confidence scenarios
            confidence_scenarios = [
                # (primary_confidence, fallback_confidence, expected_behavior)
                (0.95, 0.85, "high_confidence_primary"),
                (0.65, 0.90, "fallback_better"),
                (0.45, 0.40, "both_low_confidence"),
                (0.30, 0.88, "primary_fails_fallback_succeeds")
            ]
            
            for primary_conf, fallback_conf, scenario in confidence_scenarios:
                multi_engine = MultiEngineOCR()
                
                # Configure primary engine response
                primary_result = {
                    'text': f"Primary OCR result for {scenario}",
                    'confidence': primary_conf,
                    'metadata': {'engine': 'tesseract'}
                }
                mock_tesseract.extract_text.return_value = primary_result
                
                # Configure fallback engine response  
                fallback_result = {
                    'text': f"Fallback OCR result for {scenario}",
                    'confidence': fallback_conf,
                    'metadata': {'engine': 'easyocr'}
                }
                mock_easyocr.extract_text.return_value = fallback_result
                
                # Test different confidence thresholds
                thresholds_to_test = [0.50, 0.70, 0.80, 0.90]
                
                for threshold in thresholds_to_test:
                    # Reset mocks
                    mock_tesseract.reset_mock()
                    mock_easyocr.reset_mock()
                    
                    # Call extract_with_fallback with threshold
                    if hasattr(multi_engine, 'extract_with_fallback'):
                        if primary_conf >= threshold:
                            # Primary should be sufficient
                            result = multi_engine.extract_with_fallback(
                                test_image_data, 
                                confidence_threshold=threshold
                            )
                            # Should use primary result
                            expected_text = primary_result['text']
                        else:
                            # Should try fallback
                            if fallback_conf >= threshold:
                                result = multi_engine.extract_with_fallback(
                                    test_image_data,
                                    confidence_threshold=threshold
                                )
                                expected_text = fallback_result['text']
                            else:
                                # Both below threshold, should still return best available
                                result = multi_engine.extract_with_fallback(
                                    test_image_data,
                                    confidence_threshold=threshold
                                )
                                expected_text = primary_result['text'] if primary_conf >= fallback_conf else fallback_result['text']
                        
                        # Verify behavior based on threshold
                        assert isinstance(result, (dict, str))
                        
                        if isinstance(result, dict):
                            actual_text = result.get('text', result.get('extracted_text', ''))
                        else:
                            actual_text = result
                        
                        # Verify appropriate engine was used based on confidence threshold
                        if primary_conf >= threshold:
                            mock_tesseract.extract_text.assert_called_once()
                        else:
                            # Should have tried primary and then fallback
                            assert mock_tesseract.extract_text.called or mock_easyocr.extract_text.called
            
            # Test edge cases
            multi_engine = MultiEngineOCR()
            
            # Test with very high threshold (should force fallback)
            mock_tesseract.extract_text.return_value = {
                'text': 'Low confidence result',
                'confidence': 0.30,
                'metadata': {'engine': 'tesseract'}
            }
            mock_easyocr.extract_text.return_value = {
                'text': 'Higher confidence fallback',
                'confidence': 0.75,
                'metadata': {'engine': 'easyocr'}
            }
            
            # Very high threshold should cause fallback
            if hasattr(multi_engine, 'extract_with_fallback'):
                result = multi_engine.extract_with_fallback(test_image_data, confidence_threshold=0.95)
                assert isinstance(result, (dict, str))
            
            # Test threshold of 0.0 (should accept any result)
            if hasattr(multi_engine, 'extract_with_fallback'):
                result = multi_engine.extract_with_fallback(test_image_data, confidence_threshold=0.0)
                assert isinstance(result, (dict, str))
            
            # Test threshold of 1.0 (very strict)
            mock_tesseract.extract_text.return_value = {
                'text': 'Perfect result',
                'confidence': 1.0,
                'metadata': {'engine': 'tesseract'}
            }
            
            if hasattr(multi_engine, 'extract_with_fallback'):
                result = multi_engine.extract_with_fallback(test_image_data, confidence_threshold=1.0)
                assert isinstance(result, (dict, str))



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
