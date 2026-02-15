"""
Processor interfaces and implementations for format handlers.

This module provides the base interfaces and implementations for processors
that handle specific file formats using the strategy pattern for inversion of control.

Available processors:
- BaseProcessor: Base interface for all processors
- DocumentProcessor: Interface for document processors
- PDF Processor: Implementation using PyPDF2
- DOCX Processor: Implementation using python-docx
- XLSX Processor: Implementation using openpyxl
- Audio Processor: Implementation using Whisper for speech-to-text
- Image Processor: Interface for image processors
- OCR Processor: Implementation using PyTesseract for OCR
- Video Processor: Implementation for video thumbnail extraction and frame processing
"""
from .processor_factory import make_processors

__all__ = [
    "make_processors",
]