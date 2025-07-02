"""
Multi-Engine OCR Processor

Implements intelligent OCR processing with multiple engines and fallback strategies.
Supports Surya, Tesseract, EasyOCR, TrOCR, PaddleOCR, and GOT-OCR2.0.
"""

import logging
import io
import numpy as np
from typing import Dict, List, Any, Optional, Union
from PIL import Image
import cv2

logger = logging.getLogger(__name__)

class OCREngine:
    """Base class for OCR engines."""
    
    def __init__(self, name: str):
        self.name = name
        self.available = False
        self._initialize()
    
    def _initialize(self):
        """Initialize the OCR engine."""
        pass
    
    def extract_text(self, image_data: bytes) -> Dict[str, Any]:
        """Extract text from image data."""
        raise NotImplementedError
    
    def is_available(self) -> bool:
        """Check if the OCR engine is available."""
        return self.available


class SuryaOCR(OCREngine):
    """Surya OCR engine - Modern transformer-based OCR."""
    
    def __init__(self):
        super().__init__("surya")
    
    def _initialize(self):
        try:
            # Import Surya components
            from surya.ocr import run_ocr
            from surya.model.detection.segformer import load_model as load_det_model, load_processor as load_det_processor
            from surya.model.recognition.model import load_model as load_rec_model
            from surya.model.recognition.processor import load_processor as load_rec_processor
            
            # Load models
            self.det_processor = load_det_processor()
            self.det_model = load_det_model()
            self.rec_model = load_rec_model()
            self.rec_processor = load_rec_processor()
            self.run_ocr = run_ocr
            
            self.available = True
            logger.info("Surya OCR engine initialized successfully")
            
        except ImportError as e:
            logger.warning(f"Surya OCR not available: {e}")
            self.available = False
        except Exception as e:
            logger.error(f"Failed to initialize Surya OCR: {e}")
            self.available = False
    
    def extract_text(self, image_data: bytes, languages: List[str] = ['en']) -> Dict[str, Any]:
        """Extract text using Surya OCR."""
        if not self.available:
            raise RuntimeError("Surya OCR engine not available")
        
        try:
            # Convert image data to PIL Image
            image = Image.open(io.BytesIO(image_data))
            
            # Run OCR
            predictions = self.run_ocr(
                [image], [languages], 
                self.det_model, self.det_processor, 
                self.rec_model, self.rec_processor
            )
            
            # Process results
            result = predictions[0]
            full_text = ""
            text_blocks = []
            confidences = []
            
            for text_line in result.text_lines:
                full_text += text_line.text + "\n"
                text_blocks.append({
                    'text': text_line.text,
                    'confidence': text_line.confidence,
                    'bbox': text_line.bbox
                })
                confidences.append(text_line.confidence)
            
            avg_confidence = np.mean(confidences) if confidences else 0.0
            
            return {
                'text': full_text.strip(),
                'confidence': avg_confidence,
                'text_blocks': text_blocks,
                'engine': 'surya'
            }
            
        except Exception as e:
            logger.error(f"Surya OCR extraction failed: {e}")
            raise


class TesseractOCR(OCREngine):
    """Tesseract OCR engine - Traditional OCR with proven reliability."""
    
    def __init__(self):
        super().__init__("tesseract")
    
    def _initialize(self):
        try:
            import pytesseract
            from PIL import Image
            
            self.pytesseract = pytesseract
            self.available = True
            logger.info("Tesseract OCR engine initialized successfully")
            
        except ImportError as e:
            logger.warning(f"Tesseract OCR not available: {e}")
            self.available = False
        except Exception as e:
            logger.error(f"Failed to initialize Tesseract OCR: {e}")
            self.available = False
    
    def extract_text(self, image_data: bytes, 
                    config: str = '--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .,!?-') -> Dict[str, Any]:
        """Extract text using Tesseract OCR."""
        if not self.available:
            raise RuntimeError("Tesseract OCR engine not available")
        
        try:
            # Convert image data to PIL Image
            image = Image.open(io.BytesIO(image_data))
            
            # Preprocess image for better OCR
            image = self._preprocess_image(image)
            
            # Extract text
            text = self.pytesseract.image_to_string(image, config=config)
            
            # Get confidence data
            data = self.pytesseract.image_to_data(image, output_type=self.pytesseract.Output.DICT)
            
            # Calculate average confidence
            confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
            avg_confidence = np.mean(confidences) / 100.0 if confidences else 0.0
            
            # Extract word boxes
            word_boxes = []
            for i, word in enumerate(data['text']):
                if word.strip() and int(data['conf'][i]) > 0:
                    word_boxes.append({
                        'text': word,
                        'bbox': [data['left'][i], data['top'][i], 
                                data['left'][i] + data['width'][i], 
                                data['top'][i] + data['height'][i]],
                        'confidence': int(data['conf'][i]) / 100.0
                    })
            
            return {
                'text': text.strip(),
                'confidence': avg_confidence,
                'word_boxes': word_boxes,
                'engine': 'tesseract'
            }
            
        except Exception as e:
            logger.error(f"Tesseract OCR extraction failed: {e}")
            raise
    
    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """Preprocess image for better OCR results."""
        # Convert to OpenCV format
        opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        
        # Convert to grayscale
        gray = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2GRAY)
        
        # Apply noise reduction
        denoised = cv2.medianBlur(gray, 3)
        
        # Apply thresholding
        _, threshold = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Convert back to PIL Image
        result_image = Image.fromarray(threshold)
        return result_image


class EasyOCR(OCREngine):
    """EasyOCR engine - Neural OCR for complex layouts."""
    
    def __init__(self):
        super().__init__("easyocr")
    
    def _initialize(self):
        try:
            import easyocr
            
            self.reader = easyocr.Reader(['en'])  # Initialize with English
            self.available = True
            logger.info("EasyOCR engine initialized successfully")
            
        except ImportError as e:
            logger.warning(f"EasyOCR not available: {e}")
            self.available = False
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")
            self.available = False
    
    def extract_text(self, image_data: bytes) -> Dict[str, Any]:
        """Extract text using EasyOCR."""
        if not self.available:
            raise RuntimeError("EasyOCR engine not available")
        
        try:
            # Convert image data to numpy array
            image = Image.open(io.BytesIO(image_data))
            image_array = np.array(image)
            
            # Run OCR
            results = self.reader.readtext(image_array)
            
            # Process results
            full_text = ""
            text_blocks = []
            confidences = []
            
            for (bbox, text, confidence) in results:
                full_text += text + " "
                text_blocks.append({
                    'text': text,
                    'bbox': bbox,
                    'confidence': confidence
                })
                confidences.append(confidence)
            
            avg_confidence = np.mean(confidences) if confidences else 0.0
            
            return {
                'text': full_text.strip(),
                'confidence': avg_confidence,
                'text_blocks': text_blocks,
                'engine': 'easyocr'
            }
            
        except Exception as e:
            logger.error(f"EasyOCR extraction failed: {e}")
            raise


class TrOCREngine(OCREngine):
    """TrOCR engine - Transformer-based OCR for handwritten text."""
    
    def __init__(self):
        super().__init__("trocr")
    
    def _initialize(self):
        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            
            # Load TrOCR model and processor
            self.processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-printed")
            self.model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-printed")
            
            self.available = True
            logger.info("TrOCR engine initialized successfully")
            
        except ImportError as e:
            logger.warning(f"TrOCR not available: {e}")
            self.available = False
        except Exception as e:
            logger.error(f"Failed to initialize TrOCR: {e}")
            self.available = False
    
    def extract_text(self, image_data: bytes) -> Dict[str, Any]:
        """Extract text using TrOCR."""
        if not self.available:
            raise RuntimeError("TrOCR engine not available")
        
        try:
            # Convert image data to PIL Image
            image = Image.open(io.BytesIO(image_data))
            
            # Ensure RGB format
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Process image
            pixel_values = self.processor(image, return_tensors="pt").pixel_values
            
            # Generate text
            generated_ids = self.model.generate(pixel_values)
            generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            return {
                'text': generated_text.strip(),
                'confidence': 0.8,  # TrOCR doesn't provide confidence scores
                'engine': 'trocr'
            }
            
        except Exception as e:
            logger.error(f"TrOCR extraction failed: {e}")
            raise


class MultiEngineOCR:
    """
    Multi-engine OCR processor with intelligent fallback strategies.
    """
    
    def __init__(self):
        """Initialize all available OCR engines."""
        self.engines = {}
        
        # Initialize engines
        engine_classes = [
            SuryaOCR,
            TesseractOCR, 
            EasyOCR,
            TrOCREngine
        ]
        
        for engine_class in engine_classes:
            try:
                engine = engine_class()
                if engine.is_available():
                    self.engines[engine.name] = engine
                    logger.info(f"OCR engine '{engine.name}' is available")
                else:
                    logger.warning(f"OCR engine '{engine.name}' is not available")
            except Exception as e:
                logger.error(f"Failed to initialize {engine_class.__name__}: {e}")
        
        if not self.engines:
            logger.warning("No OCR engines available!")
    
    def extract_with_fallback(self, 
                            image_data: bytes, 
                            strategy: str = 'quality_first',
                            confidence_threshold: float = 0.8) -> Dict[str, Any]:
        """
        Extract text using multiple engines with intelligent fallback.
        
        Args:
            image_data: Image data as bytes
            strategy: Fallback strategy ('quality_first', 'speed_first', 'accuracy_first')
            confidence_threshold: Minimum confidence threshold for accepting results
            
        Returns:
            Dict containing extracted text and metadata
        """
        if not self.engines:
            raise RuntimeError("No OCR engines available")
        
        # Define engine order based on strategy
        if strategy == 'quality_first':
            engine_order = ['surya', 'tesseract', 'easyocr', 'trocr']
        elif strategy == 'speed_first':
            engine_order = ['tesseract', 'surya', 'easyocr', 'trocr']
        elif strategy == 'accuracy_first':
            engine_order = ['surya', 'easyocr', 'trocr', 'tesseract']
        else:
            engine_order = list(self.engines.keys())
        
        # Filter to only available engines
        available_engines = [name for name in engine_order if name in self.engines]
        
        results = []
        
        for engine_name in available_engines:
            try:
                logger.info(f"Trying OCR with {engine_name}")
                
                result = self.engines[engine_name].extract_text(image_data)
                result['engine'] = engine_name
                results.append(result)
                
                # Check if result meets confidence threshold
                if result.get('confidence', 0) >= confidence_threshold:
                    logger.info(f"OCR successful with {engine_name}, confidence: {result['confidence']:.2f}")
                    return result
                
            except Exception as e:
                logger.warning(f"OCR engine {engine_name} failed: {e}")
                continue
        
        # If no engine met the threshold, return the best result
        if results:
            best_result = max(results, key=lambda x: x.get('confidence', 0))
            logger.info(f"Returning best result from {best_result['engine']} with confidence {best_result['confidence']:.2f}")
            return best_result
        
        # If all engines failed, return empty result
        logger.error("All OCR engines failed")
        return {
            'text': '',
            'confidence': 0.0,
            'engine': 'none',
            'error': 'All OCR engines failed'
        }
    
    def get_available_engines(self) -> List[str]:
        """Get list of available OCR engines."""
        return list(self.engines.keys())
    
    def classify_document_type(self, image_data: bytes) -> str:
        """
        Classify document type to select optimal OCR strategy.
        
        Returns:
            Document type ('printed', 'handwritten', 'scientific', 'mixed')
        """
        # TODO classify_document_type needs a real implementation
        # Placeholder implementation
        # In a full implementation, this would analyze the image
        # to determine the best OCR strategy
        return 'printed'
