"""
Processor Adapters - Wrap existing processors in ProcessorProtocol interface.

This module contains adapters that wrap existing processors to implement
the ProcessorProtocol interface, enabling them to work with UniversalProcessor.

Adapters provide a bridge between the old processor APIs and the new
unified interface.
"""

from __future__ import annotations

__all__ = [
    'PDFProcessorAdapter',
    'GraphRAGProcessorAdapter',
    'MultimediaProcessorAdapter',
    'FileConverterProcessorAdapter',
    'BatchProcessorAdapter',
    'IPFSProcessorAdapter',
]

# Optional imports with graceful fallback
try:
    from .pdf_adapter import PDFProcessorAdapter
except ImportError:
    PDFProcessorAdapter = None

try:
    from .graphrag_adapter import GraphRAGProcessorAdapter
except ImportError:
    GraphRAGProcessorAdapter = None

try:
    from .multimedia_adapter import MultimediaProcessorAdapter
except ImportError:
    MultimediaProcessorAdapter = None

try:
    from .file_converter_adapter import FileConverterProcessorAdapter
except ImportError:
    FileConverterProcessorAdapter = None

try:
    from .batch_adapter import BatchProcessorAdapter
except ImportError:
    BatchProcessorAdapter = None

try:
    from .ipfs_adapter import IPFSProcessorAdapter
except ImportError:
    IPFSProcessorAdapter = None
