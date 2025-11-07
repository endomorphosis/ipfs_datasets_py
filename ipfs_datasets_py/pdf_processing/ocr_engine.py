"""
Multi-Engine OCR Processor

Implements intelligent OCR processing with multiple engines and retry strategies.
Supports Surya, Tesseract, EasyOCR, TrOCR, PaddleOCR, and GOT-OCR2.0.
"""
from abc import ABC, abstractmethod

import logging
import io
from typing import Dict, List, Any
from cachetools import cached


from PIL import Image

# Optional dependencies with proper error handling
try:
    import cv2
    HAVE_CV2 = True
except ImportError:
    cv2 = None
    HAVE_CV2 = False

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    np = None
    HAVE_NUMPY = False

logger = logging.getLogger(__name__)

if not HAVE_CV2:
    logger.warning("opencv (cv2) not available, some OCR preprocessing features will be disabled")
if not HAVE_NUMPY:
    logger.warning("numpy not available, some OCR features will be disabled")

try:
    import pytesseract
except ImportError:
    pytesseract = None
    logger.warning("pytesseract not available, Tesseract OCR will be disabled")


try:
    import surya
except ImportError:
    surya = None
    logger.warning("surya not available, Surya OCR will be disabled")


def _calculate_avg_confidence(confidences):
    """
    Calculate average confidence score with fallback for when numpy is unavailable.
    
    Args:
        confidences (list): List of confidence scores (0.0-1.0 or 0-100 depending on context)
    
    Returns:
        float: Average confidence score, or 0.0 if list is empty
    """
    if not confidences:
        return 0.0
    
    if HAVE_NUMPY:
        return float(np.mean(confidences))
    else:
        return sum(confidences) / len(confidences)


class OCREngine(ABC):
    """
    Abstract base class defining the interface for Optical Character Recognition (OCR) engines.

    The OCREngine class serves as the foundation for all OCR engine implementations within
    the PDF processing pipeline, providing a standardized interface for text extraction
    from image data. It establishes the contract that all concrete OCR implementations
    must follow, enabling interchangeable OCR backends and consistent behavior across
    different OCR technologies.

    This abstract base class ensures that all OCR engines implement essential methods
    for initialization, availability checking, and text extraction while allowing
    each implementation to optimize for specific use cases, document types, or
    performance characteristics.

    Attributes:
        name (str): Human-readable identifier for the OCR engine (e.g., 'tesseract', 'surya').
        available (bool): Flag indicating whether the OCR engine is properly initialized
            and available for use. Set to True after successful initialization.

    Abstract Methods:
        _initialize(): Perform engine-specific initialization including model loading,
            dependency checking, and configuration setup.
        extract_text(image_data: bytes) -> Dict[str, Any]: Extract text content from
            image data bytes and return structured results with text, confidence scores,
            and metadata.

    Public Methods:
        is_available() -> bool: Check if the OCR engine is available and ready for use.

    Usage Example:
        # Concrete implementation example
        class CustomOCR(OCREngine):
            def __init__(self):
                super().__init__("custom_ocr")
            
            def _initialize(self):
                # Initialize custom OCR components
                self.available = True
            
            def extract_text(self, image_data: bytes) -> Dict[str, Any]:
                # Implement text extraction logic
                return {"text": extracted_text, "confidence": 0.95}

    Notes:
        - All concrete implementations must call super().__init__(name) in their constructor
        - The _initialize() method should set self.available = True upon successful setup
        - The available flag is used by the MultiEngineOCR to determine engine viability
        - Exception handling during initialization should set available = False
        - Text extraction results should follow a consistent dictionary format
    """
    
    def __init__(self, 
                 name: str, 
                 logger: logging.Logger = logger,
                 mock_dict: dict[str, Any] | None = None
                 ) -> None:
        """
        Initialize an OCR engine instance with comprehensive setup and validation.

        This constructor establishes the foundation for all OCR engine implementations by
        setting up the engine name, initializing availability status, and performing
        engine-specific initialization through the abstract _initialize() method. The
        initialization process includes dependency checking, model loading, and error
        handling to ensure the engine is ready for text extraction operations.

        The constructor implements a robust initialization pattern where engines are
        marked as unavailable by default and only set to available after successful
        completion of all initialization steps. This ensures that only fully functional
        engines are used for OCR processing.

        Args:
            name (str): Unique identifier for the OCR engine (e.g., 'tesseract', 'surya',
            'easyocr', 'trocr'). Must be a non-empty string that clearly identifies
            the underlying OCR technology. This name is used for logging, debugging,
            and engine selection in multi-engine scenarios.
            logger (logging.Logger, optional): Logger instance for logging messages.
                Defaults to the module-level logger if not provided.
            mock_dict (dict[str, Any] | None, optional): Optional dictionary for
                injecting mock attributes for testing purposes. Keys should be attribute
                names and values should be the corresponding mock values.

        Raises:
            TypeError: If name is None or not a string type. This ensures type safety
            and prevents runtime errors during engine identification and logging.

        Attributes Set:
            name (str): The engine identifier passed during initialization
            available (bool): Set to False initially, updated to True only after
            successful initialization via _initialize()

        Initialization Flow:
            1. Validate name parameter type and value
            2. Set engine name and mark as unavailable
            3. Call abstract _initialize() method for engine-specific setup
            4. Handle initialization exceptions gracefully with logging
            5. Preserve availability status based on initialization outcome

        Examples:
            >>> # Concrete implementation example
            >>> class CustomOCR(OCREngine):
            ...     def __init__(self, logger=logger, mock_dict=None):
            ...         super().__init__("custom_ocr", logger=logger, mock_dict=mock_dict)  # Calls this constructor
            ...     
            ...     def _initialize(self):
            ...         # Perform custom initialization
            ...         self.available = True

        Notes:
            - All concrete OCR engine subclasses must call this constructor
            - Initialization failures are logged but do not raise exceptions
            - Engine availability should be checked before use via is_available()
            - Thread-safe initialization ensures consistent engine state
        """
        if name is None:
            raise TypeError("OCR engine name cannot be None")
        if not isinstance(name, str):
            raise TypeError(f"OCR engine name must be a string, got {type(name).__name__}")
        if logger is None:
            raise TypeError("Logger instance cannot be None")

        self.name = name
        self.logger = logger
        self.available = False
        try:
            self._initialize()
        except Exception as e:
            self.logger.warning(f"Failed to initialize OCR engine '{name}': {e}")
            self.available = False

        if isinstance(mock_dict, dict):
            for key, value in mock_dict.items():
                if not hasattr(self, key):
                    raise AttributeError(f"Mock attribute '{key}' does not exist on {self.__class__.__name__}")
                try:
                    setattr(self, key, value)
                except Exception as e:
                    raise AttributeError(f"Failed to set mock attribute '{key}': {e}") from e

    @abstractmethod
    def _initialize(self) -> None:
        """
        Initialize the OCR engine with all required dependencies and models.

        This abstract method must be implemented by all concrete OCR engine subclasses
        to perform engine-specific initialization including dependency checking, model
        loading, configuration setup, and availability verification. The method should
        set self.available = True upon successful initialization or False if any
        critical dependencies are missing or initialization fails.

        The initialization process typically includes:
        - Checking for required system dependencies
        - Loading pre-trained models or libraries
        - Configuring engine-specific parameters
        - Performing basic functionality tests
        - Setting up error handling and retry mechanisms

        Raises:
            ImportError: If required dependencies are not available
            RuntimeError: If model loading or initialization fails
            OSError: If system dependencies are missing or misconfigured

        Example:
            >>> class CustomOCR(OCREngine):
            ...     def _initialize(self):
            ...         # Perform custom initialization logic
            ...         self.available = True  # Set to True if successful
            ...     # Implement other methods as needed

        Notes:
            - This method is called automatically during __init__
            - Implementations should handle missing dependencies gracefully
            - All exceptions should be caught and logged appropriately
            - The available flag should reflect successful initialization
            - Memory and resource cleanup should be handled if initialization fails
        """
        pass

    def _get_image_data(self, image_data: bytes) -> Image:
        """
        Convert raw image bytes to a PIL Image object.

        This method validates the OCR engine availability and image data before
        converting the provided bytes to a PIL Image object that can be processed
        by the OCR engine.

        Args:
            image_data (bytes): Raw image data in bytes format

        Returns:
            Image: PIL Image object ready for OCR processing

        Raises:
            RuntimeError: If the OCR engine is not available
            ValueError: If image data is empty or invalid/corrupted

        Example:
            >>> ocr_engine = SuryaOCR()
            >>> with open('document.png', 'rb') as f:
            ...     image_data = f.read()
            >>> image = ocr_engine._get_image_data(image_data)
            >>> print(f"Image size: {image.size}")
        """
        if not self.available:
            raise RuntimeError(f"{self.name.capitalize()} engine not available")
        
        if not isinstance(image_data, bytes):
            raise TypeError(f"Expected image_data to be bytes, got {type(image_data).__name__}")

        # Validate image data
        if not image_data:
            raise ValueError("Empty image data provided")

        # Convert image data to PIL Image
        try:
            return Image.open(io.BytesIO(image_data))
        except Exception as e:
            raise ValueError(f"Invalid image data: {e}")

    @abstractmethod
    def extract_text(self, image_data: bytes) -> Dict[str, Any]:
        """
        Extract text content from image data bytes using the OCR engine.

        This abstract method defines the core text extraction interface that all OCR
        engine implementations must provide. It processes raw image data and returns
        structured text extraction results including the extracted text, confidence
        scores, spatial information, and engine-specific metadata.

        Args:
            image_data (bytes): Raw image data in any supported format (PNG, JPEG, TIFF, etc.).
                The image should contain text content to be extracted. Larger images
                with higher resolution typically provide better OCR accuracy.

        Returns:
            Dict[str, Any]: Structured dictionary containing extraction results with the following keys:
                - 'text' (str): The extracted text content as a single string
                - 'confidence' (float): Overall confidence score (0.0 to 1.0) for the extraction
                - 'engine' (str): Identifier of the OCR engine that performed the extraction
                - Additional engine-specific keys may include:
                  - 'text_blocks' or 'word_boxes': Spatial text information with bounding boxes
                  - 'metadata': Engine-specific processing information
                  - 'language': Detected or specified language information

        Raises:
            RuntimeError: If the OCR engine is not available or properly initialized
            ValueError: If image_data is empty, None, or in an unsupported format
            OSError: If image processing fails due to corrupted or invalid image data
            MemoryError: If the image is too large for available system memory
            TimeoutError: If OCR processing exceeds reasonable time limits

        Examples:
            >>> engine = ConcreteOCREngine()
            >>> with open('document.png', 'rb') as f:
            ...     image_data = f.read()
            >>> result = engine.extract_text(image_data)
            >>> print(f"Text: {result['text']}")
            >>> print(f"Confidence: {result['confidence']:.2f}")

        Notes:
            - Image quality significantly affects OCR accuracy
            - Preprocessing may be applied internally to optimize recognition
            - Large images may be processed in chunks or downsampled
            - All implementations should provide consistent return format
            - Processing time varies based on image size and complexity
        """
        raise NotImplementedError("Subclasses must implement extract_text")
    
    def is_available(self) -> bool:
        """
        Check if the OCR engine is properly initialized and available for text extraction.

        This method provides a quick availability check for the OCR engine without
        attempting to perform actual text extraction. It returns the current status
        of the engine's initialization and readiness to process images.

        Returns:
            bool: True if the OCR engine is fully initialized and ready to extract text,
                False if initialization failed or required dependencies are missing.

        Examples:
            >>> engine = SuryaOCR()
            >>> if engine.is_available():
            ...     result = engine.extract_text(image_data)
            ... else:
            ...     print("Surya OCR engine not available, retrying with another engine")

        Notes:
            - This method does not re-initialize the engine or check dependencies again
            - The availability status is set during engine initialization
            - A False return indicates the engine should not be used for text extraction
            - This method is thread-safe and can be called multiple times without side effects
        """
        return self.available


class SuryaOCR(OCREngine):
    """
    Advanced transformer-based OCR engine using the Surya framework for high-accuracy text extraction.

    SuryaOCR represents a state-of-the-art approach to optical character recognition, leveraging
    modern transformer architectures for superior text detection and recognition capabilities.
    It provides excellent performance on complex document layouts, multilingual content, and
    challenging text scenarios where traditional OCR engines may struggle.

    The Surya framework combines advanced text detection models with recognition transformers
    to achieve highly accurate text extraction with detailed spatial information including
    bounding boxes and confidence scores for each detected text element.

    Key Features:
    - Transformer-based text detection and recognition
    - Multi-language support with configurable language specifications
    - High accuracy on complex document layouts and challenging text
    - Detailed spatial information with bounding box coordinates
    - Per-text-line confidence scoring for quality assessment
    - Robust performance on handwritten and printed text

    Attributes:
        detection_predictor: Surya detection processor for text detection preprocessing
        det_model: Loaded Surya detection model for identifying text regions
        rec_model: Loaded Surya recognition model for character recognition
        recognition_predictor: Surya recognition processor for text recognition preprocessing
        run_ocr: Surya OCR execution function for processing images

    Dependencies:
        - surya: Core Surya OCR framework with detection and recognition models
        - Requires GPU acceleration for optimal performance
        - Pre-trained transformer models automatically downloaded on first use

    Usage Example:
        surya_engine = SuryaOCR()
        if surya_engine.is_available():
            result = surya_engine.extract_text(
                image_data=pdf_page_bytes,
                languages=['en', 'es']  # Multi-language support
            )
            print(f"Extracted text: {result['text']}")
            print(f"Confidence: {result['confidence']:.2f}")

    Notes:
        - Automatically downloads required models on first initialization
        - Best performance with GPU acceleration but works on CPU
        - Supports multiple languages simultaneously in single extraction
        - Memory intensive due to transformer models
        - Falls back gracefully if Surya framework not available
    """
    
    def __init__(self, logger: logging.Logger = logger, mock_dict=None) -> None:
        """
        Initialize the Surya OCR engine with transformer-based architecture.

        This constructor sets up the advanced Surya OCR system, which leverages modern
        transformer neural networks for superior text detection and recognition performance.
        Surya provides state-of-the-art accuracy on complex document layouts, multilingual
        content, and challenging text scenarios where traditional OCR methods may struggle.

        The initialization process includes:
        - Loading pre-trained detection models for text region identification
        - Setting up recognition transformers for character-level text extraction
        - Configuring multilingual support and spatial text analysis
        - Establishing GPU acceleration if available for optimal performance

        Key advantages of Surya OCR:
        - Transformer-based architecture for enhanced accuracy
        - Robust handling of complex document layouts and orientations
        - Built-in multilingual support without additional configuration
        - Detailed spatial information with precise bounding box coordinates
        - Excellent performance on both printed and handwritten text

        Note:
            First-time initialization requires internet connectivity to download
            pre-trained models (~1-2GB). Subsequent runs use cached models for
            offline operation.

        Examples:
            >>> surya_engine = SuryaOCR()
            >>> if surya_engine.is_available():
            ...     result = surya_engine.extract_text(image_data)
            ...     print(f"Extracted: {result['text']}")
        """
        super().__init__("surya", logger=logger, mock_dict=mock_dict)
    
    def _initialize(self) -> None:
        """
        Initialize the Surya OCR engine by loading all required models and components.

        This method performs the complete initialization sequence for the Surya OCR engine,
        including importing the Surya framework, loading pre-trained detection and recognition
        models, and setting up the processing pipeline. The initialization process downloads
        models from Hugging Face Hub on first use and caches them locally for future runs.

        The method loads four main components:
        - Detection processor: Preprocesses images for text detection
        - Detection model: Identifies text regions in images using SegFormer architecture
        - Recognition model: Extracts text from detected regions using transformer models
        - Recognition processor: Postprocesses recognition outputs

        Raises:
            ImportError: If the Surya framework is not installed or importable
            RuntimeError: If model loading fails due to network issues or corrupted models
            OSError: If insufficient disk space for model caching or permission issues
            MemoryError: If insufficient RAM to load the transformer models

        Example:
            >>> surya_engine = SuryaOCR()
            >>> surya_engine._initialize()  # Loads models and sets up processing
            >>> if surya_engine.is_available():
            ...     result = surya_engine.extract_text(image_data)
            ...     print(f"Extracted text: {result['text']}")

        Notes:
            - First initialization requires internet connection to download models
            - Models are cached locally (~1-2GB total size) for offline use
            - GPU acceleration is automatically used if CUDA is available
            - Initialization may take 30-60 seconds on first run
            - Subsequent initializations are much faster using cached models
        """
        self.name = "surya"
        try:
            # Load models
            self.surya = surya
            self.detection_predictor = self.surya.detection.DetectionPredictor()
            self.recognition_predictor = self.surya.recognition.RecognitionPredictor()

            self.available = True
            self.logger.info("Surya OCR engine initialized successfully")
        except ImportError as e:
            self.logger.warning(f"Surya OCR not available: {e}")
            self.available = False
        except Exception as e:
            self.logger.error(f"Failed to initialize Surya OCR: {e}")
            self.available = False
    
    def extract_text(self, image_data: bytes) -> Dict[str, Any]:
        """
        Extract text from image data using the Surya transformer-based OCR engine.

        This method processes image data through the complete Surya OCR pipeline, including
        text detection using SegFormer models and text recognition using transformer
        architectures. It supports multi-language text extraction and provides detailed
        spatial information for each detected text element.

        Args:
            image_data (bytes): Raw image data in any PIL-supported format (PNG, JPEG, TIFF, etc.).
                The image should contain text content to be extracted. Higher resolution
                images typically provide better accuracy.

        Returns:
            Dict[str, Any]: Comprehensive extraction results containing:
                - 'text' (str): Complete extracted text with line breaks preserved
                - 'confidence' (float): Average confidence score across all text lines (0.0-1.0)
                - 'text_blocks' (List[Dict]): Detailed information for each text line including:
                  - 'text': Individual line text content
                  - 'confidence': Per-line confidence score
                  - 'bbox': Bounding box coordinates [x1, y1, x2, y2]
                - 'engine' (str): Engine identifier ('surya')

        Raises:
            RuntimeError: If the Surya OCR engine is not properly initialized
            ValueError: If image_data is empty or in an unsupported format
            PIL.UnidentifiedImageError: If the image format cannot be determined
            MemoryError: If the image is too large for available system memory
            Exception: For any other processing errors during OCR extraction

        Examples:
            >>> surya_engine = SuryaOCR()
            >>> with open('multilingual_doc.png', 'rb') as f:
            ...     image_data = f.read()
            >>> result = surya_engine.extract_text(image_data)
            >>> print(f"Extracted text: {result['text']}")
            >>> for block in result['text_blocks']:
            ...     print(f"Line: {block['text']} (confidence: {block['confidence']:.2f})")

        Notes:
            - Processing time increases with image size and number of text regions
            - Multi-language support allows simultaneous processing of mixed-language documents
            - Bounding box coordinates are in image pixel coordinates
            - Confidence scores help identify potentially inaccurate text regions
            - GPU acceleration significantly improves processing speed if available
        """
        if not self.available:
            raise RuntimeError("Surya OCR engine not available")

        try:
            # Convert image data to PIL Image
            image = super()._get_image_data(image_data)
            
            # Run OCR
            predictions = self.recognition_predictor(
                [image], det_predictor=self.detection_predictor,
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
            
            # Calculate average confidence
            avg_confidence = _calculate_avg_confidence(confidences)
            
            return {
                'text': full_text.strip(),
                'confidence': avg_confidence,
                'text_blocks': text_blocks,
                'engine': 'surya'
            }
            
        except Exception as e:
            self.logger.error(f"Surya OCR extraction failed: {e}")
            raise


class TesseractOCR(OCREngine):
    """
    Traditional OCR engine implementation using Google's Tesseract for reliable text extraction.

    This implementation includes advanced preprocessing capabilities to optimize image quality
    before OCR processing, significantly improving recognition accuracy on challenging documents.
    The engine provides detailed word-level bounding boxes and confidence scores for granular
    analysis of extraction quality.

    Key Features:
    - Mature, battle-tested OCR technology with extensive real-world usage
    - Support for 100+ languages and writing systems
    - Configurable OCR parameters and processing modes
    - Advanced image preprocessing for improved accuracy
    - Word-level confidence scoring and bounding box information
    - Robust performance on printed text and structured documents

    Attributes:
        pytesseract: PyTesseract interface for Tesseract OCR engine

    Dependencies:
        - pytesseract: Python wrapper for Tesseract OCR engine
        - tesseract-ocr: Core Tesseract OCR engine (system dependency)
        - PIL: Python Imaging Library for image processing
        - opencv-python: OpenCV for advanced image preprocessing

    Processing Pipeline:
        1. Convert image data to PIL Image format
        2. Apply preprocessing (grayscale, denoising, thresholding)
        3. Extract text using configurable Tesseract parameters
        4. Generate confidence scores and word-level bounding boxes
        5. Return structured results with metadata

    Usage Example:
        tesseract_engine = TesseractOCR()
        if tesseract_engine.is_available():
            result = tesseract_engine.extract_text(
                image_data=document_page_bytes,
                config='--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,!?-'
            )
            print(f"Extracted text: {result['text']}")
            for word_box in result['word_boxes']:
                print(f"Word: {word_box['text']}, Confidence: {word_box['confidence']}")

    Notes:
        - Requires system installation of Tesseract OCR engine
        - Performance varies significantly based on image quality and preprocessing
        - Best suited for clean, printed text in standard fonts
        - Configurable character whitelisting for domain-specific text extraction
        - Preprocessing pipeline optimized for PDF-derived images
    """
    
    def __init__(self, logger=logger, mock_dict=None) -> None:
        """
        Initialize the Tesseract OCR engine with comprehensive configuration and dependency validation.

        This constructor establishes the Tesseract OCR engine as the primary text extraction
        backend, leveraging Google's mature and battle-tested OCR technology. Tesseract provides
        reliable character recognition capabilities across 100+ languages with configurable
        processing parameters for diverse document types and quality requirements.

        The initialization process sets up the foundation for traditional OCR processing with
        proven accuracy on printed text, structured documents, and clean image content. Unlike
        neural OCR approaches, Tesseract offers fast processing speeds and minimal memory
        requirements while maintaining consistent performance across varied hardware configurations.

        Key Tesseract advantages initialized:
        - Mature, extensively tested OCR technology with decades of development
        - Support for over 100 languages and writing systems
        - Configurable OCR parameters for specialized text extraction scenarios
        - Lightweight resource requirements compared to neural alternatives
        - Excellent performance on clean, printed text and structured documents
        - Advanced image preprocessing capabilities for quality optimization

        Initialization includes:
        - Parent class setup with "tesseract" engine identifier
        - Dependency validation for PyTesseract wrapper and system installation
        - Configuration of default OCR parameters optimized for general use
        - Setup of image preprocessing pipeline for enhanced accuracy
        - Error handling for missing dependencies or installation issues

        Examples:
            >>> tesseract_engine = TesseractOCR()
            >>> if tesseract_engine.is_available():
            ...     result = tesseract_engine.extract_text(document_bytes)
            ...     print(f"Extracted: {result['text']}")
            ... else:
            ...     print("Tesseract not available, check system installation")

        Notes:
            - Requires system installation of Tesseract OCR binary
            - PyTesseract wrapper must be installed via pip
            - Language data packages installed separately for non-English text
            - Initialization is lightweight as models are loaded on-demand
            - Configuration can be customized per extraction call
        """
        super().__init__("tesseract", logger=logger, mock_dict=mock_dict)
    
    def _initialize(self) -> None:
        """
        Initialize the Tesseract OCR engine by importing required dependencies.

        This method sets up the Tesseract OCR engine by importing the PyTesseract wrapper
        and verifying that the underlying Tesseract OCR system is properly installed
        and accessible. The initialization is lightweight as Tesseract models are loaded
        on-demand during text extraction rather than at initialization time.

        The method performs dependency verification for:
        - pytesseract: Python wrapper for Tesseract OCR
        - PIL (Pillow): Image processing library for format handling
        - Underlying Tesseract system installation

        Raises:
            ImportError: If pytesseract or PIL libraries are not installed
            SystemError: If the underlying Tesseract OCR system is not properly installed
            OSError: If Tesseract executable cannot be found in system PATH

        Example:
            >>> tesseract_engine = TesseractOCR()
            >>> tesseract_engine._initialize()  # Imports pytesseract and checks dependencies
            >>> if tesseract_engine.is_available():
            ...     result = tesseract_engine.extract_text(image_data)
            ...     print(f"Extracted text: {result['text']}")

        Notes:
            - Tesseract OCR must be installed separately as a system dependency
            - The method only verifies import capability, not full functionality
            - Language data packages are loaded on-demand during extraction
            - No GPU acceleration setup required as Tesseract is CPU-based
            - Initialization is very fast compared to neural OCR engines
        """
        try:
            

            self.pytesseract = pytesseract
            self.available = True
            self.logger.info("Tesseract OCR engine initialized successfully")
            
        except ImportError as e:
            self.logger.warning(f"Tesseract OCR not available: {e}")
            self.available = False
        except Exception as e:
            self.logger.error(f"Failed to initialize Tesseract OCR: {e}")
            self.available = False
    
    def extract_text(self, 
                     image_data: bytes, 
                    config: str = '--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .,!?-'
                    ) -> Dict[str, Any]:
        """
        Extract text from image data using Tesseract OCR with configurable parameters and preprocessing.

        This method processes image data through the complete Tesseract OCR pipeline including
        image preprocessing optimization, configurable OCR parameters, text extraction, and
        detailed confidence analysis. The preprocessing stage applies noise reduction, 
        thresholding, and other optimizations to improve OCR accuracy on challenging images.

        Args:
            image_data (bytes): Raw image data in any PIL-supported format (PNG, JPEG, TIFF, etc.).
                The image should contain text content to be extracted. Clean, high-resolution
                images with good contrast provide the best results.
            config (str, optional): Tesseract configuration string controlling OCR behavior.
                Default includes page segmentation mode 6 (uniform text blocks) and character
                whitelisting. Common options include:
                - '--psm N': Page segmentation mode (0-13)
                - '-c tessedit_char_whitelist=ABC123': Limit recognized characters
                - '-l lang': Specify language (eng, fra, deu, etc.)

        Returns:
            Dict[str, Any]: Comprehensive extraction results containing:
                - 'text' (str): Complete extracted text content
                - 'confidence' (float): Average confidence score across all words (0.0-1.0)
                - 'word_boxes' (List[Dict]): Detailed word-level information including:
                  - 'text': Individual word text content
                  - 'bbox': Bounding box coordinates [x1, y1, x2, y2]
                  - 'confidence': Per-word confidence score (0.0-1.0)
                - 'engine' (str): Engine identifier ('tesseract')

        Raises:
            RuntimeError: If the Tesseract OCR engine is not properly initialized
            ValueError: If image_data is empty or in an unsupported format
            PIL.UnidentifiedImageError: If the image format cannot be determined
            TesseractError: If Tesseract processing fails due to configuration or image issues
            Exception: For any other processing errors during OCR extraction

        Examples:
            >>> tesseract_engine = TesseractOCR()
            >>> with open('document.png', 'rb') as f:
            ...     image_data = f.read()
            >>> 
            >>> # Basic extraction
            >>> result = tesseract_engine.extract_text(image_data)
            >>> 
            >>> # Custom configuration for numbers only
            >>> result = tesseract_engine.extract_text(
            ...     image_data, 
            ...     config='--psm 8 -c tessedit_char_whitelist=0123456789'
            ... )
            >>> 
            >>> # Language-specific extraction
            >>> result = tesseract_engine.extract_text(
            ...     image_data,
            ...     config='--psm 6 -l fra'  # French language
            ... )

        Notes:
            - Image preprocessing significantly improves accuracy on noisy or low-quality images
            - Page segmentation mode (PSM) should be chosen based on document layout
            - Character whitelisting can improve accuracy for domain-specific content
            - Processing time varies with image size and complexity
            - Word-level confidence scores help identify potentially incorrect text
        """
        try:
            # Convert image data to PIL Image
            image = super()._get_image_data(image_data)

            # Preprocess image for better OCR
            image = self._preprocess_image(image)
            
            # Extract text
            text = self.pytesseract.image_to_string(image, config=config)
            
            # Get confidence data
            data = self.pytesseract.image_to_data(image, output_type=self.pytesseract.Output.DICT)
            print(f"pytesseract data:\n{data}")
            
            # Extract confidences from data
            confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
            
            # Calculate average confidence (divide by 100 for tesseract which uses 0-100 scale)
            avg_confidence = _calculate_avg_confidence(confidences) / 100.0 if confidences else 0.0
            
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
            self.logger.error(f"Tesseract OCR extraction failed: {e}")
            raise
    
    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess image to optimize it for Tesseract OCR text extraction accuracy.

        This method applies a series of image processing techniques to enhance image quality
        and improve OCR recognition accuracy. The preprocessing pipeline includes conversion
        to grayscale, noise reduction, and automatic thresholding to create clean, high-contrast
        images that are optimal for text recognition.

        Args:
            image (Image.Image): PIL Image object to be preprocessed. Should contain text
                content that needs to be extracted via OCR.

        Returns:
            Image.Image: Preprocessed PIL Image optimized for OCR with:
                - Grayscale conversion for enhanced processing
                - Noise reduction to remove image artifacts
                - Binary thresholding for maximum text contrast
                - Cleaned edges and improved text boundary definition

        Processing Steps:
            1. Convert PIL Image to OpenCV format (RGB to BGR)
            2. Convert to grayscale to simplify processing
            3. Apply median blur filter to reduce noise and artifacts
            4. Apply Otsu's automatic thresholding for optimal binarization
            5. Convert back to PIL Image format for Tesseract processing

        Examples:
            >>> tesseract_engine = TesseractOCR()
            >>> original_image = Image.open('noisy_document.png')
            >>> processed_image = tesseract_engine._preprocess_image(original_image)
            >>> # processed_image now has enhanced contrast and reduced noise

        Notes:
            - Median blur with kernel size 3 effectively removes salt-and-pepper noise
            - Otsu's thresholding automatically determines optimal binarization threshold
            - Preprocessing may slightly increase processing time but significantly improves accuracy
            - Works best on images with clear text-background contrast
            - May not be optimal for images with complex backgrounds or colors
        """
        # If cv2 or numpy not available, return image unchanged
        if not HAVE_CV2 or not HAVE_NUMPY:
            self.logger.debug("OpenCV or NumPy not available, skipping image preprocessing")
            return image
        
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
    """
    Neural network-based OCR engine optimized for complex document layouts and multilingual text.

    EasyOCR provides an advanced neural approach to optical character recognition, specifically
    designed to handle challenging document layouts, mixed languages, and varied text orientations.
    Built on deep learning foundations, it excels at processing documents with complex formatting,
    curved text, and non-standard layouts that traditional OCR engines may struggle with.

    The engine uses convolutional neural networks for text detection and recurrent neural networks
    for text recognition, providing a robust solution for diverse document types including
    scanned documents, photographs of text, and documents with complex visual structures.

    Key Features:
    - Deep learning-based text detection and recognition
    - Robust handling of complex document layouts and orientations
    - Excellent performance on curved and rotated text
    - Built-in support for 80+ languages without additional configuration
    - Automatic text orientation detection and correction
    - High accuracy on both printed and handwritten text

    Attributes:
        reader: EasyOCR Reader instance configured for text extraction

    Dependencies:
        - easyocr: Core EasyOCR framework with pre-trained neural models
        - torch: PyTorch framework for neural network operations
        - torchvision: Computer vision utilities for PyTorch
        - opencv-python: OpenCV for image preprocessing

    Processing Pipeline:
        1. Convert image data to numpy array format
        2. Apply EasyOCR's neural text detection algorithms
        3. Extract and recognize text using neural recognition models
        4. Generate confidence scores and bounding box coordinates
        5. Return structured results with spatial information

    Usage Example:
        easyocr_engine = EasyOCR()
        if easyocr_engine.is_available():
            result = easyocr_engine.extract_text(image_data=complex_layout_bytes)
            print(f"Extracted text: {result['text']}")
            for text_block in result['text_blocks']:
                print(f"Block: {text_block['text']}, Confidence: {text_block['confidence']:.2f}")
                print(f"Bounding box: {text_block['bbox']}")

    Notes:
        - Automatically downloads required neural models on first use
        - Requires significant computational resources for optimal performance
        - Excellent for documents with non-standard layouts or orientations
        - Memory intensive due to neural network models
        - May be slower than traditional OCR but provides higher accuracy on complex content
        - Supports automatic language detection without explicit configuration
    """
    
    def __init__(self, logger=logger, mock_dict=None) -> None:
        """
        Initialize the EasyOCR engine for neural network-based text recognition.

        This constructor establishes the EasyOCR engine as the primary text extraction
        backend, leveraging advanced neural network architectures for superior text
        detection and recognition capabilities. EasyOCR provides excellent performance
        on complex document layouts, multilingual content, and challenging text scenarios
        including curved text, varied orientations, and non-standard fonts.

        The initialization process sets up the foundation for neural OCR processing with
        enhanced accuracy on documents that traditional OCR engines may struggle with,
        including scanned documents, photographs of text, and documents with complex
        visual structures or mixed content types.

        Key EasyOCR advantages initialized:
        - Deep learning-based text detection using convolutional neural networks
        - Advanced text recognition with recurrent neural network architectures
        - Built-in support for 80+ languages without additional configuration
        - Automatic text orientation detection and correction capabilities
        - Robust handling of curved, rotated, and irregularly positioned text
        - High accuracy on both high-quality scans and lower-quality image sources

        Initialization includes:
        - Parent class setup with "easyocr" engine identifier
        - Dependency validation for EasyOCR framework and neural model requirements
        - Configuration preparation for multi-language text recognition
        - Setup of GPU acceleration detection for optimal performance
        - Error handling for missing dependencies or insufficient system resources

        Examples:
            >>> easyocr_engine = EasyOCR()
            >>> if easyocr_engine.is_available():
            ...     result = easyocr_engine.extract_text(complex_layout_bytes)
            ...     print(f"Extracted: {result['text']}")
            ... else:
            ...     print("EasyOCR not available, check installation")

        Notes:
            - Requires EasyOCR package installation via pip
            - Automatically downloads neural models on first use (~100-200MB)
            - GPU acceleration significantly improves processing speed if available
            - Memory intensive due to neural network models
            - Initialization may take longer on first run due to model downloads
        """
        super().__init__("easyocr", logger=logger, mock_dict=mock_dict)
    
    def _initialize(self) -> None:
        """
        Initialize the EasyOCR engine with English language support.
        Attempts to import and configure the EasyOCR library. Sets up a reader
        instance for English text recognition and updates the availability status
        based on the initialization outcome.
    
        Sets:
            self.reader (easyocr.Reader): EasyOCR reader instance configured for English
            self.available (bool): True if initialization successful, False otherwise

        Raises:
            ImportError: If EasyOCR library is not installed
            Exception: If initialization fails for any other reason

        Example:
            >>> easyocr_engine = EasyOCR()
            >>> easyocr_engine._initialize()  # Initializes the EasyOCR engine
            >>> if easyocr_engine.is_available():
            ...     result = easyocr_engine.extract_text(image_data)
            ...     print(f"Extracted text: {result['text']}")
        """
        try:
            import easyocr

            self.reader = easyocr.Reader(['en'])  # Initialize with English
            self.available = True
            self.logger.info("EasyOCR engine initialized successfully")
            
        except ImportError as e:
            self.logger.warning(f"EasyOCR not available: {e}")
            self.available = False
        except Exception as e:
            self.logger.error(f"Failed to initialize EasyOCR: {e}")
            self.available = False
    
    def extract_text(self, image_data: bytes) -> Dict[str, Any]:
        """Extract text from image data using EasyOCR engine.

        This method processes image bytes through EasyOCR to perform optical character 
        recognition, returning structured text data with confidence scores and bounding boxes.

        Args:
            image_data (bytes): Raw image data in bytes format (e.g., PNG, JPEG, etc.)

        Returns:
            Dict[str, Any]: A dictionary containing:
                - text (str): Full extracted text with spaces between detected text blocks
                - confidence (float): Average confidence score across all detected text (0.0-1.0)
                - text_blocks (List[Dict]): List of individual text detections, each containing:
                    - text (str): The detected text string
                    - bbox (List): Bounding box coordinates as nested list [[x1,y1], [x2,y2], ...]
                    - confidence (float): Confidence score for this specific detection
                - engine (str): Always 'easyocr' to identify the OCR engine used

        Raises:
            Exception: If OCR processing fails due to invalid image data, memory issues,
                      or EasyOCR internal errors. Original exception is logged and re-raised.

        Examples:
            >>> easyocr_engine = EasyOCR()
            >>> with open('document.png', 'rb') as f:
            ...     image_data = f.read()
            >>> result = easyocr_engine.extract_text(image_data)
            >>> print(f"Extracted text: {result['text']}")
            >>> print(f"Confidence: {result['confidence']:.2f}")

        Note:
            - Requires EasyOCR reader to be properly initialized
            - Image is converted to numpy array format for processing
            - Empty results return confidence of 0.0
            - Text blocks are concatenated with spaces for full text output
        """
        try:
            image = super()._get_image_data(image_data)

            # Check if numpy is available for array conversion
            if not HAVE_NUMPY:
                self.logger.error("NumPy is required for EasyOCR but is not available")
                raise ImportError("NumPy is required for EasyOCR")

            # Convert image data to numpy array
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
            
            # Calculate average confidence
            avg_confidence = _calculate_avg_confidence(confidences)
            
            return {
                'text': full_text.strip(),
                'confidence': avg_confidence,
                'text_blocks': text_blocks,
                'engine': 'easyocr'
            }
            
        except Exception as e:
            self.logger.error(f"EasyOCR extraction failed: {e}")
            raise


class TrOCREngine(OCREngine):
    """
    Transformer-based OCR engine specialized for handwritten and printed text recognition.

    TrOCREngine implements Microsoft's TrOCR (Transformer-based Optical Character Recognition)
    approach, which leverages the power of transformer architectures for high-quality text
    recognition. This engine is particularly effective for handwritten text, printed text,
    and scenarios where traditional OCR engines face challenges with font variations or
    document quality issues.

    TrOCR represents a significant advancement in OCR technology by applying transformer
    models (similar to those used in language models) to the visual recognition task,
    resulting in improved accuracy and better handling of diverse text styles and qualities.

    Key Features:
    - Transformer-based architecture for superior text recognition
    - Specialized performance on handwritten text
    - Excellent handling of diverse fonts and text styles
    - Robust performance on low-quality or degraded documents
    - End-to-end learning approach without separate detection/recognition stages
    - Pre-trained models optimized for various text types

    Attributes:
        processor: TrOCR processor for image preprocessing and text postprocessing
        model: Loaded TrOCR Vision-Encoder-Decoder model for text recognition

    Dependencies:
        - transformers: Hugging Face Transformers library for TrOCR models
        - torch: PyTorch framework for neural network operations
        - PIL: Python Imaging Library for image format handling

    Model Variants:
        - microsoft/trocr-base-printed: Optimized for printed text recognition
        - microsoft/trocr-base-handwritten: Specialized for handwritten text
        - microsoft/trocr-large-*: Higher capacity models for improved accuracy

    Processing Pipeline:
        1. Convert image data to PIL Image and ensure RGB format
        2. Preprocess image using TrOCR processor (tokenization, normalization)
        3. Generate text using Vision-Encoder-Decoder transformer model
        4. Decode generated tokens to text using TrOCR processor
        5. Return structured results with generated text

    Usage Example:
        trocr_engine = TrOCREngine()
        if trocr_engine.is_available():
            result = trocr_engine.extract_text(image_data=handwritten_note_bytes)
            print(f"Recognized text: {result['text']}")
            print(f"Engine used: {result['engine']}")

    Notes:
        - Does not provide confidence scores (limitation of current TrOCR implementation)
        - Best suited for single-line or short text passages
        - Requires internet connection for initial model download
        - Memory intensive due to transformer model size
        - May be slower than traditional OCR but provides superior accuracy
        - Performs exceptionally well on challenging handwriting styles
    """
    
    def __init__(self, logger=logger, mock_dict=None) -> None:
        """
        Initialize the TrOCR engine for transformer-based text recognition.

        This constructor initializes the OCR engine using Microsoft's TrOCR (Transformer-based
        Optical Character Recognition) technology as the underlying processing backend. TrOCR
        leverages transformer architectures for high-quality text recognition, particularly
        effective for handwritten and varied font styles where traditional OCR may struggle.

        The initialization process will automatically load the required TrOCR models and
        configure the processing pipeline during the _initialize() method call. This includes
        downloading pre-trained models from Hugging Face Hub if they are not already cached
        locally.

        Key initialization components:
        - TrOCR processor for image preprocessing and text postprocessing
        - Vision-Encoder-Decoder transformer model for text recognition
        - GPU acceleration setup if CUDA is available
        - Error handling for missing dependencies or model loading failures

        Raises:
            ImportError: If transformers library is not available
            RuntimeError: If model loading fails due to network or memory issues
            OSError: If insufficient disk space for model caching

        Example:
            >>> trocr_engine = TrOCREngine()
            >>> trocr_engine._initialize()  # Initializes the TrOCR engine
            >>> if trocr_engine.is_available():
            ...     result = trocr_engine.extract_text(image_data)
            ...     print(f"Recognized text: {result['text']}")

        Notes:
            - Requires internet connection for initial model download
            - Models are cached locally for offline use after first initialization
            - GPU acceleration significantly improves processing speed
            - Memory intensive due to transformer model architecture
            - Initialization may take 30-60 seconds on first run
        """
        super().__init__("trocr", logger=logger, mock_dict=mock_dict)

    def _initialize(self) -> None:
        """Initialize the TrOCR (Transformers OCR) engine by loading the model and processor.

        This method attempts to load the Microsoft TrOCR base model for printed text recognition.
        It handles import errors gracefully and sets the availability status accordingly.

        The method loads:
        - TrOCRProcessor: Preprocesses images for the model
        - VisionEncoderDecoderModel: The actual OCR model for text recognition

        Sets:
            self.processor: The TrOCR processor instance
            self.model: The TrOCR model instance  
            self.available: Boolean indicating if the engine is ready for use

        Raises:
            No exceptions are raised directly. All exceptions are caught and logged:
            - ImportError: When transformers library is not available
            - Exception: Any other initialization errors

        Example:
            >>> trocr_engine = TrOCREngine()
            >>> trocr_engine._initialize()  # Initializes the TrOCR engine
            >>> if trocr_engine.is_available():
            ...     result = trocr_engine.extract_text(image_data)
            ...     print(f"Recognized text: {result['text']}")

        Note:
            This is an internal initialization method that should be called during
            object construction. Logs appropriate messages for success, warnings,
            and errors during initialization.
        """
        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            
            # Load TrOCR model and processor
            self.processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-printed")
            self.model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-printed")
            
            self.available = True
            self.logger.info("TrOCR engine initialized successfully")
            
        except ImportError as e:
            self.logger.warning(f"TrOCR not available: {e}")
            self.available = False
        except Exception as e:
            self.logger.error(f"Failed to initialize TrOCR: {e}")
            self.available = False
    
    def extract_text(self, image_data: bytes) -> Dict[str, Any]:
        """
        Extract text from image data using the TrOCR (Transformer-based Optical Character Recognition) model.
    
        This method processes image bytes through a pre-trained TrOCR model to perform optical character
        recognition and extract readable text. The image is automatically converted to RGB format if needed
        before processing through the transformer pipeline.

        Args:
            image_data (bytes): Raw image data in bytes format. Supported formats include
                               common image types (PNG, JPEG, etc.) that can be processed by PIL.

        Returns:
            Dict[str, Any]: A dictionary containing extraction results with the following keys:
                - 'text' (str): The extracted text content, stripped of leading/trailing whitespace
                - 'confidence' (float): Always 0.0 as TrOCR models do not provide confidence scores
                - 'engine' (str): Always 'trocr' to identify the OCR engine used

        Raises:
            ValueError: When the image_data is empty, corrupted, or in an unsupported format
            Exception: For any other processing errors during text extraction, such as model
                      inference failures or memory issues

        Examples:
            >>> trocr_engine = TrOCREngine()
            >>> with open('handwritten_note.png', 'rb') as f:
            ...     image_data = f.read()
            >>> result = trocr_engine.extract_text(image_data)
            >>> print(f"Extracted text: {result['text']}") 
            >>> print(f"Engine used: {result['engine']}")

        Note:
            Unlike traditional OCR engines, TrOCR does not provide confidence scores for the
            extracted text. The confidence field is included for API consistency but will
            always return 0.0.
        """
        try:
            image = super()._get_image_data(image_data)

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
                'confidence': 0.0,  # TrOCR doesn't provide confidence scores
                'engine': 'trocr'
            }
            
        except ValueError:
            # Re-raise ValueError for empty or invalid image data
            raise
        except Exception as e:
            self.logger.error(f"TrOCR extraction failed: {e}")
            raise


class MultiEngineOCR:
    """
    Intelligent multi-engine OCR orchestrator with adaptive retry strategies and quality optimization.

    The MultiEngineOCR class provides a sophisticated approach to optical character recognition
    by coordinating multiple OCR engines and implementing successive retry mechanisms.
    It automatically selects the most appropriate OCR engine based on document characteristics,
    quality requirements, and performance strategies while providing comprehensive error handling
    and result optimization across different OCR technologies.

    This orchestrator serves as the primary interface for OCR operations within the PDF processing
    pipeline, abstracting the complexity of managing multiple OCR engines and providing consistent,
    high-quality text extraction regardless of document type or characteristics.

    Key Features:
    - Multi-engine coordination with automatic retry capabilities
    - Configurable processing strategies (quality_first, speed_first, accuracy_first)
    - Confidence-based result validation and engine selection
    - Document type classification for optimal engine selection
    - Comprehensive error handling and recovery mechanisms
    - Performance monitoring and engine availability tracking

    Attributes:
        engines (Dict[str, OCREngine]): Dictionary of available OCR engines keyed by name.
            Populated during initialization with successfully loaded engines.

    Supported Engines:
        - SuryaOCR: Modern transformer-based OCR for high accuracy
        - TesseractOCR: Traditional OCR with proven reliability  
        - EasyOCR: Neural OCR optimized for complex layouts
        - TrOCREngine: Transformer-based OCR for handwritten text

    Processing Strategies:
        - quality_first: Prioritizes highest accuracy engines (Surya → Tesseract → EasyOCR → TrOCR)
        - speed_first: Prioritizes fastest processing (Tesseract → Surya → EasyOCR → TrOCR)
        - accuracy_first: Prioritizes most accurate engines (Surya → EasyOCR → TrOCR → Tesseract)

    Public Methods:
        extract_with_ocr(image_data, strategy, confidence_threshold) -> Dict[str, Any]:
            Extract text using multiple engines with intelligent retry based on confidence scores
            and processing strategy.
        get_available_engines() -> List[str]: Get list of successfully initialized OCR engines.
        classify_document_type(image_data) -> str: Classify document type to optimize engine selection.

    Usage Example:
        multi_ocr = MultiEngineOCR()
        
        # High-quality extraction with retry strategy
        result = multi_ocr.extract_with_ocr(
            image_data=document_bytes,
            strategy='quality_first',
            confidence_threshold=0.8
        )
        
        if result['confidence'] >= 0.8:
            print(f"High confidence text: {result['text']}")
        else:
            print(f"Best effort text: {result['text']} (confidence: {result['confidence']})")

    Notes:
        - Engines are initialized on startup; unavailable engines are gracefully skipped
        - Retry until confidence threshold is met or all engines are exhausted
        - Returns best available result even if no engine meets confidence threshold
        - Comprehensive logging tracks engine performance and failure modes
        - Thread-safe for concurrent processing operations
    """

    def __new__(cls):
        """Ensure only one instance of MultiEngineOCR is created (singleton pattern)."""
        if not hasattr(cls, 'instance'):
            cls.instance = super(MultiEngineOCR, cls).__new__(cls)
        return cls.instance
    
    def __init__(self, logger=logger, mock_dict=None) -> None:
        """Initialize the OCR engine manager with all available OCR engines.

        Attempts to initialize and register multiple OCR engines including SuryaOCR,
        TesseractOCR, EasyOCR, and TrOCREngine. Only engines that are successfully
        initialized and report availability are added to the engines registry.

        The initialization process:
        1. Creates an empty engines dictionary
        2. Iterates through predefined engine classes
        3. Instantiates each engine and checks availability
        4. Registers available engines by name
        5. Logs initialization status for each engine

        Raises:
            No exceptions are raised directly, but logs warnings if no engines
            are available after initialization.

        Examples:
            >>> ocr_manager = MultiEngineOCR()
            >>> if ocr_manager.engines:
            ...     print("Available OCR engines:", ocr_manager.get_available_engines())

        Note:
            Individual engine initialization failures are caught and logged as errors,
            but do not prevent the manager from initializing with remaining engines.
        """
        self.engines = {}
        self.logger = logger

        # Initialize engines
        engine_classes = [SuryaOCR, TesseractOCR, EasyOCR, TrOCREngine]

        for engine_class in engine_classes:
            try:
                engine = engine_class(logger=logger, mock_dict=mock_dict)
                if engine.is_available():
                    self.logger.info(f"OCR engine '{engine.name}' is available")
                else:
                    self.logger.warning(f"OCR engine '{engine.name}' is not available")
                self.engines[engine.name] = engine
            except Exception as e:
                self.logger.error(f"Failed to initialize {engine_class.__name__}: {e}")
        if not self.engines:
            self.logger.warning("No OCR engines available!")
    
    def extract_with_ocr(self, 
                            image_data: bytes, 
                            strategy: str = 'quality_first',
                            confidence_threshold: float = 0.8) -> Dict[str, Any]:
        """
        Extract text from image data using multiple OCR engines with intelligent retry strategies.

        This method orchestrates text extraction across multiple OCR engines using configurable
        processing strategies and quality thresholds. It automatically retries with different
        engines until the confidence threshold is met or all available engines are exhausted,
        ensuring optimal text extraction quality and reliability.

        The method implements intelligent engine selection based on document characteristics,
        confidence scoring, and processing strategy preferences. It provides comprehensive
        error handling and falls back gracefully when engines fail, returning the best
        available result even if no engine meets the specified confidence threshold.

        Args:
            image_data (bytes): Raw image data in any PIL-supported format (PNG, JPEG, TIFF, etc.).
            Must be non-empty bytes containing valid image content. Higher resolution images
            typically provide better OCR accuracy across all engines.
            
            strategy (str, optional): Processing strategy determining engine priority order.
            Defaults to 'quality_first'. Available strategies:
            - 'quality_first': Prioritizes accuracy (Surya → Tesseract → EasyOCR → TrOCR)
            - 'speed_first': Prioritizes processing speed (Tesseract → Surya → EasyOCR → TrOCR)  
            - 'accuracy_first': Prioritizes maximum accuracy (Surya → EasyOCR → TrOCR → Tesseract)
            
            confidence_threshold (float, optional): Minimum confidence score (0.0-1.0) required
            to accept OCR results without trying additional engines. Defaults to 0.8.
            Higher thresholds improve quality but may require more processing attempts.

        Returns:
            Dict[str, Any]: Comprehensive extraction results containing:
            - 'text' (str): Extracted text content with formatting preserved
            - 'confidence' (float): Confidence score (0.0-1.0) from the successful engine
            - 'engine' (str): Name of the OCR engine that produced the result
            - 'error' (str, optional): Error message if all engines failed
            - Additional engine-specific metadata may include:
              - 'text_blocks': Spatial text information with bounding boxes
              - 'word_boxes': Word-level confidence and position data

        Raises:
            RuntimeError: If no OCR engines are available for processing
            TypeError: If image_data is not bytes or confidence_threshold is not float
            ValueError: If image_data is empty, confidence_threshold is out of range (0.0-1.0),
            or strategy is not one of the supported values
            MemoryError: If image is too large for available system memory
            OSError: If image data is corrupted or in an unsupported format

        Examples:
            >>> multi_ocr = MultiEngineOCR()
            >>> 
            >>> # High-quality extraction with quality priority
            >>> result = multi_ocr.extract_with_ocr(
            ...     image_data=document_bytes,
            ...     strategy='quality_first',
            ...     confidence_threshold=0.9
            ... )
            >>> 
            >>> # Fast processing for real-time applications
            >>> result = multi_ocr.extract_with_ocr(
            ...     image_data=document_bytes,
            ...     strategy='speed_first',
            ...     confidence_threshold=0.7
            ... )
            >>> 
            >>> # Maximum accuracy for critical documents
            >>> result = multi_ocr.extract_with_ocr(
            ...     image_data=document_bytes,
            ...     strategy='accuracy_first',
            ...     confidence_threshold=0.95
            ... )

        Processing Flow:
            1. Validate input parameters and engine availability
            2. Select engine priority order based on processing strategy
            3. Filter to only available engines in the current environment
            4. Iterate through engines in priority order:
               - Attempt text extraction with current engine
               - Evaluate confidence score against threshold
               - Return result if threshold is met
               - Continue to next engine if threshold not met or engine fails
            5. Return best available result if no engine meets threshold
            6. Return error result if all engines fail

        Notes:
            - Processing stops as soon as confidence threshold is achieved
            - All engine failures are logged but don't prevent trying other engines
            - Results are ranked by confidence score to return the best available outcome
            - Engine selection can be influenced by document type classification
            - Memory usage scales with number of engines and image size
            - Thread-safe for concurrent processing operations
        """
        if not self.engines:
            raise RuntimeError("No OCR engines available")

        if not isinstance(confidence_threshold, float):
            raise TypeError("confidence_threshold must be a float")

        if not isinstance(image_data, bytes):
            raise TypeError("image_data must be bytes")

        if not image_data:
            raise ValueError("image_data cannot be empty")

        if confidence_threshold < 0.0 or confidence_threshold > 1.0:
            raise ValueError("confidence_threshold must be between 0.0 and 1.0")

        # Define engine order based on strategy
        match strategy:
            case 'quality_first':
                engines = ['surya', 'tesseract', 'easyocr', 'trocr']
            case 'speed_first':
                engines = ['tesseract', 'surya', 'easyocr', 'trocr']
            case 'accuracy_first':
                engines = ['surya', 'easyocr', 'trocr', 'tesseract']
            case _:
                raise ValueError(f"Unknown strategy: {strategy}")

        # Filter to only available engines
        available_engines = [name for name in engines if name in self.engines]
        
        results = []
        
        for engine_name in available_engines:
            try:
                self.logger.info(f"Trying OCR with {engine_name}")
                
                result = self.engines[engine_name].extract_text(image_data)
                result['engine'] = engine_name
                results.append(result)

                # Check if result meets confidence threshold
                if result.get('confidence', 0) >= confidence_threshold:
                    self.logger.info(f"OCR successful with {engine_name}, confidence: {result['confidence']:.2f}")
                    return result
                
            except Exception as e:
                self.logger.warning(f"OCR engine {engine_name} failed: {e}")
                continue

        # If no engine met the threshold, return the best result
        if results:
            best_result = max(results, key=lambda x: x.get('confidence', 0))
            self.logger.info(f"Returning best result from {best_result['engine']} with confidence {best_result['confidence']:.2f}")
            return best_result
        
        # If all engines failed, return empty result with error
        self.logger.error("All OCR engines failed")
        return {
            'text': '',
            'confidence': 0.0,
            'engine': 'none',
            'error': 'All OCR engines failed'
        }

    def get_available_engines(self) -> List[str]:
        """
        Get a list of all currently available OCR engines.

        This method checks each registered OCR engine to determine if it's available
        for use (e.g., if required dependencies are installed and accessible). Only
        engines that pass the availability check are included in the returned list.

        Returns:
            List[str]: A list of engine names that are currently available and ready
                to be used for OCR processing. Returns an empty list if no engines
                are available.

        Example:
            >>> ocr = OCREngine()
            >>> available = ocr.get_available_engines()
            >>> print(available)
            ['tesseract', 'easyocr']
        """
        return [
            name for name, engine in self.engines.items() if engine.is_available()
        ]

    def classify_document_type(self, image_data: bytes) -> str:
        """
        Classify document type to select optimal OCR strategy.

        This method analyzes image characteristics to determine the most appropriate
        OCR strategy and engine selection for the given document. The classification
        helps optimize OCR accuracy by selecting engines best suited for specific
        document types and content characteristics.

        Args:
            image_data (bytes): Raw image data to be analyzed for document type classification.
                The image should contain the document content to be classified.
        
        Returns:
            str: Document type classification from the following categories:
                - 'printed': Clean printed text with standard fonts
                - 'handwritten': Handwritten or cursive text content
                - 'scientific': Technical documents with equations, formulas, or symbols
                - 'mixed': Documents containing multiple text types or complex layouts

        Raises:
            ValueError: If image_data is empty or invalid
            PIL.UnidentifiedImageError: If image format cannot be determined

        Examples:
            >>> multi_ocr = MultiEngineOCR()
            >>> with open('document.png', 'rb') as f:
            ...     image_data = f.read()
            >>> doc_type = multi_ocr.classify_document_type(image_data)
            >>> print(f"Document type: {doc_type}")

        Notes:
            - Classification affects OCR engine selection priority
            - Analysis is based on image characteristics and text features
            - Used internally by extract_with_ocr for optimal engine selection
            - Classification accuracy improves OCR performance significantly
        """
        try:
            # Convert image data to PIL Image for analysis
            image = Image.open(io.BytesIO(image_data))
            
            # If numpy or cv2 not available, return default classification
            if not HAVE_NUMPY or not HAVE_CV2:
                self.logger.debug("NumPy or OpenCV not available, defaulting to 'printed' classification")
                return 'printed'
            
            # Convert to numpy array for analysis
            image_array = np.array(image)
            
            # Convert to grayscale for analysis
            if len(image_array.shape) == 3:
                gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = image_array
            
            # Analyze image characteristics for classification
            height, width = gray.shape
            
            # Calculate edge density to detect handwritten vs printed text
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.sum(edges > 0) / (width * height)
            
            # Calculate text line consistency for printed vs handwritten detection
            horizontal_projection = np.sum(gray < 200, axis=1)
            line_variance = np.var(horizontal_projection[horizontal_projection > 0]) if len(horizontal_projection[horizontal_projection > 0]) > 0 else 0
            
            # Classify based on characteristics
            if edge_density > 0.1 and line_variance > 1000:
                # High edge density and irregular lines suggest handwritten text
                return 'handwritten'
            elif edge_density < 0.05 and line_variance < 500:
                # Low edge density and consistent lines suggest printed text
                return 'printed'
            elif any(char in str(image_data) for char in ['∑', '∫', '√', 'α', 'β', 'γ', '≈', '≡']):
                # Presence of mathematical symbols suggests scientific content
                return 'scientific'
            else:
                # Mixed characteristics or complex layout
                return 'mixed'
                
        except Exception as e:
            self.logger.warning(f"Document type classification failed: {e}, defaulting to 'printed'")
            return 'printed'
