# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/ocr_engine.py'

Files last updated: 1751885541.8540742

Stub file last updated: 2025-07-07 21:47:52

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
    Intelligent multi-engine OCR orchestrator with adaptive fallback strategies and quality optimization.

The MultiEngineOCR class provides a sophisticated approach to optical character recognition
by coordinating multiple OCR engines and implementing intelligent fallback mechanisms.
It automatically selects the most appropriate OCR engine based on document characteristics,
quality requirements, and performance strategies while providing comprehensive error handling
and result optimization across different OCR technologies.

This orchestrator serves as the primary interface for OCR operations within the PDF processing
pipeline, abstracting the complexity of managing multiple OCR engines and providing consistent,
high-quality text extraction regardless of document type or characteristics.

Key Features:
- Multi-engine coordination with automatic fallback capabilities
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
    extract_with_fallback(image_data, strategy, confidence_threshold) -> Dict[str, Any]:
        Extract text using multiple engines with intelligent fallback based on confidence scores
        and processing strategy.
    get_available_engines() -> List[str]: Get list of successfully initialized OCR engines.
    classify_document_type(image_data) -> str: Classify document type to optimize engine selection.

Usage Example:
    multi_ocr = MultiEngineOCR()
    
    # High-quality extraction with fallback
    result = multi_ocr.extract_with_fallback(
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
    - Fallback continues until confidence threshold is met or all engines are exhausted
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
    det_processor: Surya detection processor for text detection preprocessing
    det_model: Loaded Surya detection model for identifying text regions
    rec_model: Loaded Surya recognition model for character recognition
    rec_processor: Surya recognition processor for text recognition preprocessing
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

TesseractOCR provides a robust, well-established approach to optical character recognition
using the widely-adopted Tesseract engine. Known for its reliability, extensive language
support, and proven performance across diverse document types, Tesseract serves as an
excellent fallback option and primary choice for many text extraction scenarios.

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
def __init__(self, name: str):
```
* **Async:** False
* **Method:** True
* **Class:** OCREngine

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** SuryaOCR

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** TesseractOCR

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** EasyOCR

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** TrOCREngine

## __init__

```python
def __init__(self):
    """
    Initialize all available OCR engines.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiEngineOCR

## _initialize

```python
@abstractmethod
def _initialize(self):
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
- Setting up error handling and fallback mechanisms

Raises:
    ImportError: If required dependencies are not available
    RuntimeError: If model loading or initialization fails
    OSError: If system dependencies are missing or misconfigured

Notes:
    - This method is called automatically during __init__
    - Implementations should handle missing dependencies gracefully
    - All exceptions should be caught and logged appropriately
    - The available flag should reflect successful initialization
    - Memory and resource cleanup should be handled if initialization fails
    """
```
* **Async:** False
* **Method:** True
* **Class:** OCREngine

## _initialize

```python
def _initialize(self):
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

Notes:
    - First initialization requires internet connection to download models
    - Models are cached locally (~1-2GB total size) for offline use
    - GPU acceleration is automatically used if CUDA is available
    - Initialization may take 30-60 seconds on first run
    - Subsequent initializations are much faster using cached models
    """
```
* **Async:** False
* **Method:** True
* **Class:** SuryaOCR

## _initialize

```python
def _initialize(self):
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

Notes:
    - Tesseract OCR must be installed separately as a system dependency
    - The method only verifies import capability, not full functionality
    - Language data packages are loaded on-demand during extraction
    - No GPU acceleration setup required as Tesseract is CPU-based
    - Initialization is very fast compared to neural OCR engines
    """
```
* **Async:** False
* **Method:** True
* **Class:** TesseractOCR

## _initialize

```python
def _initialize(self):
    """
    Initialize the EasyOCR engine by loading neural models and setting up the reader.

This method sets up the EasyOCR engine by importing the EasyOCR framework and
initializing a Reader instance with English language support. The initialization
process downloads pre-trained neural models on first use and caches them locally
for future runs. The models include both text detection and recognition networks.

The initialization creates:
- Text detection model: CRAFT (Character Region Awareness for Text detection)
- Text recognition model: CRNN (Convolutional Recurrent Neural Network)
- Language support: Initially configured for English, expandable to 80+ languages

Raises:
    ImportError: If the EasyOCR library is not installed
    RuntimeError: If model downloading or loading fails
    MemoryError: If insufficient memory to load neural models
    OSError: If insufficient disk space for model caching

Notes:
    - First initialization requires internet connection to download models (~40-100MB)
    - Models are cached in ~/.EasyOCR/ directory for offline use
    - GPU acceleration is automatically used if CUDA is available
    - Initialization may take 15-30 seconds on first run
    - Reader supports on-demand language switching without reinitialization
    """
```
* **Async:** False
* **Method:** True
* **Class:** EasyOCR

## _initialize

```python
def _initialize(self):
    """
    Initialize the TrOCR engine by loading transformer models and processor components.

This method sets up the TrOCR engine by loading Microsoft's transformer-based OCR
models from Hugging Face Hub. The initialization process downloads the pre-trained
Vision-Encoder-Decoder model and processor, which are specifically designed for
optical character recognition tasks using transformer architectures.

The method loads:
- TrOCR Processor: Handles image preprocessing and text postprocessing
- VisionEncoderDecoderModel: The core transformer model for text recognition
- Model variant: microsoft/trocr-base-printed (optimized for printed text)

Raises:
    ImportError: If the transformers library is not installed
    RuntimeError: If model downloading from Hugging Face Hub fails
    MemoryError: If insufficient memory to load transformer models
    OSError: If insufficient disk space for model caching or network issues
    HTTPError: If model repository is inaccessible or authentication fails

Notes:
    - First initialization requires internet connection to download models (~300MB)
    - Models are cached in ~/.cache/huggingface/ for offline use
    - GPU acceleration is automatically used if PyTorch detects CUDA
    - Initialization may take 30-90 seconds on first run depending on connection
    - Alternative models (trocr-base-handwritten, trocr-large-*) can be substituted
    """
```
* **Async:** False
* **Method:** True
* **Class:** TrOCREngine

## _preprocess_image

```python
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
        - Grayscale conversion for simplified processing
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
```
* **Async:** False
* **Method:** True
* **Class:** TesseractOCR

## classify_document_type

```python
def classify_document_type(self, image_data: bytes) -> str:
    """
    Classify document type to select optimal OCR strategy and engine selection.

This method analyzes image characteristics to determine the document type, which
can be used to optimize OCR engine selection and processing strategies. The
classification helps choose the most appropriate OCR approach for different
types of text content and document layouts.

Args:
    image_data (bytes): Raw image data to analyze for document type classification.
        The image should contain the document content to be classified.

Returns:
    str: Document type classification. Possible values:
        - 'printed': Clean printed text with standard fonts
        - 'handwritten': Handwritten or cursive text content
        - 'scientific': Mathematical formulas, equations, or technical diagrams
        - 'mixed': Combination of multiple text types or complex layouts

Classification Logic (Future Implementation):
    - Analyze text density and distribution patterns
    - Detect presence of mathematical symbols or formulas
    - Identify handwriting characteristics vs printed text
    - Assess document layout complexity and structure
    - Use computer vision techniques for feature extraction

Examples:
    >>> multi_ocr = MultiEngineOCR()
    >>> with open('research_paper.png', 'rb') as f:
    ...     image_data = f.read()
    >>> doc_type = multi_ocr.classify_document_type(image_data)
    >>> print(f"Document type: {doc_type}")
    >>> 
    >>> # Optimize strategy based on document type
    >>> if doc_type == 'handwritten':
    ...     strategy = 'accuracy_first'  # Prefer TrOCR for handwriting
    >>> elif doc_type == 'scientific':
    ...     strategy = 'quality_first'   # Use best available for formulas
    >>> else:
    ...     strategy = 'speed_first'     # Standard printed text

Notes:
    - Current implementation returns 'printed' as placeholder
    - Future versions will implement computer vision-based classification
    - Classification results can guide OCR strategy selection
    - Improves overall OCR accuracy by matching engines to content types
    - Useful for automated document processing workflows
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
def extract_text(self, image_data: bytes, languages: List[str] = ['en']) -> Dict[str, Any]:
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
    languages (List[str], optional): List of language codes for text recognition.
        Supported languages include 'en' (English), 'es' (Spanish), 'fr' (French),
        'de' (German), and many others. Defaults to ['en'].

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
    >>> result = surya_engine.extract_text(image_data, languages=['en', 'es'])
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
    Extract text from image data using EasyOCR's neural network-based approach.

This method processes image data through EasyOCR's complete neural pipeline including
CRAFT-based text detection and CRNN-based text recognition. The engine excels at
handling complex layouts, rotated text, and challenging document structures that
traditional OCR engines struggle with.

Args:
    image_data (bytes): Raw image data in any supported format (PNG, JPEG, TIFF, etc.).
        The image should contain text content to be extracted. EasyOCR handles
        various text orientations and layouts effectively.

Returns:
    Dict[str, Any]: Comprehensive extraction results containing:
        - 'text' (str): Complete extracted text with spaces between detected blocks
        - 'confidence' (float): Average confidence score across all text blocks (0.0-1.0)
        - 'text_blocks' (List[Dict]): Detailed information for each detected text block:
          - 'text': Individual text block content
          - 'bbox': Bounding box as list of 4 corner points [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
          - 'confidence': Per-block confidence score (0.0-1.0)
        - 'engine' (str): Engine identifier ('easyocr')

Raises:
    RuntimeError: If the EasyOCR engine is not properly initialized
    ValueError: If image_data is empty or in an unsupported format
    PIL.UnidentifiedImageError: If the image format cannot be determined
    MemoryError: If the image is too large for available system memory
    Exception: For any other processing errors during OCR extraction

Examples:
    >>> easyocr_engine = EasyOCR()
    >>> with open('complex_layout.png', 'rb') as f:
    ...     image_data = f.read()
    >>> result = easyocr_engine.extract_text(image_data)
    >>> print(f"Extracted text: {result['text']}")
    >>> for block in result['text_blocks']:
    ...     print(f"Block: {block['text']}, Confidence: {block['confidence']:.2f}")
    ...     print(f"Corners: {block['bbox']}")

Notes:
    - Bounding boxes are returned as 4-point polygons for rotated text support
    - Automatically detects and handles text orientation without configuration
    - Processing time scales with image complexity and number of text regions
    - Confidence scores are inherently provided by the neural recognition model
    - Excellent performance on curved, rotated, or stylized text
    """
```
* **Async:** False
* **Method:** True
* **Class:** EasyOCR

## extract_text

```python
def extract_text(self, image_data: bytes) -> Dict[str, Any]:
    """
    Extract text from image data using TrOCR's transformer-based recognition approach.

This method processes image data through the complete TrOCR pipeline using a
Vision-Encoder-Decoder transformer architecture. The approach treats OCR as a
sequence-to-sequence task, generating text tokens from visual features without
requiring separate text detection stages.

Args:
    image_data (bytes): Raw image data in any PIL-supported format (PNG, JPEG, TIFF, etc.).
        The image should contain text content to be extracted. TrOCR works best with
        single lines or small text blocks rather than full document pages.

Returns:
    Dict[str, Any]: Extraction results containing:
        - 'text' (str): Generated text content from the transformer model
        - 'confidence' (float): Fixed confidence score (0.8) as TrOCR doesn't provide
          native confidence estimation
        - 'engine' (str): Engine identifier ('trocr')

Raises:
    RuntimeError: If the TrOCR engine is not properly initialized
    ValueError: If image_data is empty or in an unsupported format
    PIL.UnidentifiedImageError: If the image format cannot be determined
    torch.cuda.OutOfMemoryError: If GPU memory is insufficient for processing
    Exception: For any other processing errors during text generation

Processing Pipeline:
    1. Convert image data to PIL Image and ensure RGB format
    2. Preprocess image using TrOCR processor (resize, normalize, tensorize)
    3. Encode visual features using the vision encoder
    4. Generate text tokens using the decoder with attention mechanisms
    5. Decode tokens to final text string

Examples:
    >>> trocr_engine = TrOCREngine()
    >>> with open('handwritten_note.png', 'rb') as f:
    ...     image_data = f.read()
    >>> result = trocr_engine.extract_text(image_data)
    >>> print(f"Recognized text: {result['text']}")
    >>> print(f"Confidence: {result['confidence']}")

Notes:
    - Best suited for single-line text or small text regions
    - Excellent performance on handwritten and stylized text
    - Does not provide spatial information or bounding boxes
    - Fixed confidence score due to transformer architecture limitations
    - Processing time varies with image size and model complexity
    - May require text detection preprocessing for multi-line documents
    """
```
* **Async:** False
* **Method:** True
* **Class:** TrOCREngine

## extract_with_fallback

```python
def extract_with_fallback(self, image_data: bytes, strategy: str = "quality_first", confidence_threshold: float = 0.8) -> Dict[str, Any]:
    """
    Extract text using multiple engines with intelligent fallback.

Args:
    image_data: Image data as bytes
    strategy: Fallback strategy ('quality_first', 'speed_first', 'accuracy_first')
    confidence_threshold: Minimum confidence threshold for accepting results
    
Returns:
    Dict containing extracted text and metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiEngineOCR

## get_available_engines

```python
def get_available_engines(self) -> List[str]:
    """
    Get a list of all successfully initialized and available OCR engines.

This method returns the names of all OCR engines that were successfully initialized
during the MultiEngineOCR constructor and are currently available for text extraction.
The list reflects the actual engines that can be used by extract_with_fallback()
and other processing methods.

Returns:
    List[str]: List of available OCR engine names. Possible values include:
        - 'surya': Surya transformer-based OCR
        - 'tesseract': Traditional Tesseract OCR
        - 'easyocr': EasyOCR neural network-based OCR
        - 'trocr': TrOCR transformer-based OCR
        Empty list if no engines are available.

Examples:
    >>> multi_ocr = MultiEngineOCR()
    >>> available = multi_ocr.get_available_engines()
    >>> print(f"Available engines: {available}")
    >>> if 'surya' in available:
    ...     print("Surya OCR is ready for use")
    >>> if not available:
    ...     print("No OCR engines available - check dependencies")

Notes:
    - The list reflects engines available at initialization time
    - Engine availability is determined during object construction
    - Engines are not re-checked for availability in this method
    - Useful for conditional logic based on available OCR capabilities
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
    ...     print("OCR engine not available, trying fallback")

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
