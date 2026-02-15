"""
PDF Processing - Specialized PDF processing functionality.

This package provides comprehensive PDF processing capabilities:
- Text extraction from PDF documents
- OCR for scanned documents (multiple engines)
- Entity extraction and knowledge graph construction
- Metadata extraction
- Multi-format export

Main Classes:
- PDFProcessor: Main PDF processing class
- OCREngine: Abstract base for OCR engines
- MultiEngineOCR: Multi-engine OCR with fallback

Example:
    from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
    
    processor = PDFProcessor()
    result = processor.process("document.pdf")
"""

try:
    from .pdf_processor import PDFProcessor, InitializationError, DependencyError
    _pdf_processor_available = True
except ImportError as e:
    import warnings
    warnings.warn(f"PDF processor unavailable: {e}", ImportWarning)
    PDFProcessor = None
    InitializationError = Exception
    DependencyError = Exception
    _pdf_processor_available = False

try:
    from .ocr_engine import (
        OCREngine,
        SuryaOCR,
        TesseractOCR,
        EasyOCR,
        TrOCREngine,
        MultiEngineOCR
    )
    _ocr_available = True
except ImportError as e:
    import warnings
    warnings.warn(f"OCR engines unavailable: {e}", ImportWarning)
    OCREngine = None
    SuryaOCR = None
    TesseractOCR = None
    EasyOCR = None
    TrOCREngine = None
    MultiEngineOCR = None
    _ocr_available = False

__all__ = [
    'PDFProcessor',
    'InitializationError',
    'DependencyError',
    'OCREngine',
    'SuryaOCR',
    'TesseractOCR',
    'EasyOCR',
    'TrOCREngine',
    'MultiEngineOCR',
]
