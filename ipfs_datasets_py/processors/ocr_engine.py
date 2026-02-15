"""
DEPRECATED: OCR Engine module.

This module has been deprecated and moved to processors.specialized.pdf.

.. deprecated:: 1.9.0
   This module is deprecated. Use OCR engines from 
   processors.specialized.pdf instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.ocr_engine import OCREngine, MultiEngineOCR
    
    NEW:
        from ipfs_datasets_py.processors.specialized.pdf import OCREngine, MultiEngineOCR

For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.ocr_engine is deprecated. "
    "Use processors.specialized.pdf OCR classes instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.pdf import (
        OCREngine,
        SuryaOCR,
        TesseractOCR,
        EasyOCR,
        TrOCREngine,
        MultiEngineOCR,
    )
except ImportError:
    # If specialized.pdf is not available, create stubs
    OCREngine = None
    SuryaOCR = None
    TesseractOCR = None
    EasyOCR = None
    TrOCREngine = None
    MultiEngineOCR = None

__all__ = [
    'OCREngine',
    'SuryaOCR',
    'TesseractOCR',
    'EasyOCR',
    'TrOCREngine',
    'MultiEngineOCR',
]
