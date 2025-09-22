# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/ocr_engine.py'

Files last updated: 1753176664.2198107

Stub file last updated: 2025-07-22 02:32:39

## EasyOCR

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MultiEngineOCR

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OCREngine

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SuryaOCR

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TesseractOCR

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TrOCREngine

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, name: str) -> None:
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
    ...     def __init__(self):
    ...         super().__init__("custom_ocr")  # Calls this constructor
    ...     
    ...     def _initialize(self):
    ...         # Perform custom initialization
    ...         self.available = True

Notes:
    - All concrete OCR engine subclasses must call this constructor
    - Initialization failures are logged but do not raise exceptions
    - Engine availability should be checked before use via is_available()
    - The _initialize() method is responsible for setting available = True
    - Thread-safe initialization ensures consistent engine state
    """
```
* **Async:** False
* **Method:** True
* **Class:** OCREngine

## __init__

```python
def __init__(self) -> None:
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
```
* **Async:** False
* **Method:** True
* **Class:** SuryaOCR

## __init__

```python
def __init__(self) -> None:
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
```
* **Async:** False
* **Method:** True
* **Class:** TesseractOCR

## __init__

```python
def __init__(self) -> None:
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
```
* **Async:** False
* **Method:** True
* **Class:** EasyOCR

## __init__

```python
def __init__(self) -> None:
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
```
* **Async:** False
* **Method:** True
* **Class:** TrOCREngine

## __init__

```python
def __init__(self) -> None:
    """
    Initialize the OCR engine manager with all available OCR engines.

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
```
* **Async:** False
* **Method:** True
* **Class:** MultiEngineOCR

## classify_document_type

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** MultiEngineOCR

## extract_text

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** OCREngine

## extract_text

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SuryaOCR

## extract_text

```python
def extract_text(self, image_data: bytes, config: str = "--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .,!?-") -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** TesseractOCR

## extract_text

```python
def extract_text(self, image_data: bytes) -> Dict[str, Any]:
    """
    Extract text from image data using EasyOCR engine.

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
```
* **Async:** False
* **Method:** True
* **Class:** EasyOCR

## extract_text

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** TrOCREngine

## extract_with_ocr

```python
def extract_with_ocr(self, image_data: bytes, strategy: str = "quality_first", confidence_threshold: float = 0.8) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** MultiEngineOCR

## get_available_engines

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** MultiEngineOCR

## is_available

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** OCREngine
