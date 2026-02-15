"""
Processor Adapters - Wrap existing processors in ProcessorProtocol interface.

This module contains adapters that wrap existing processors to implement
the ProcessorProtocol interface, enabling them to work with UniversalProcessor.

Adapters provide a bridge between existing processor implementations and the new
unified interface from processors.core.

Auto-Registration:
    To automatically register all adapters, use:
    
    >>> from ipfs_datasets_py.processors.adapters import register_all_adapters
    >>> register_all_adapters()
    
    Or import and use individual adapters:
    
    >>> from ipfs_datasets_py.processors.adapters import PDFProcessorAdapter
    >>> from ipfs_datasets_py.processors.core import get_global_registry
    >>> registry = get_global_registry()
    >>> registry.register(PDFProcessorAdapter(), priority=10, name="PDFProcessor")
"""

from __future__ import annotations

# Auto-registration utilities
from .auto_register import (
    register_all_adapters,
    is_registered,
    get_available_adapters,
)

__all__ = [
    # Auto-registration
    'register_all_adapters',
    'is_registered',
    'get_available_adapters',
    # Adapter classes (optional imports)
    'PDFProcessorAdapter',
    'GraphRAGProcessorAdapter',
    'MultimediaProcessorAdapter',
    'FileConverterProcessorAdapter',
    'BatchProcessorAdapter',
    'IPFSProcessorAdapter',
    'WebArchiveProcessorAdapter',
    'SpecializedScraperAdapter',
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

try:
    from .web_archive_adapter import WebArchiveProcessorAdapter
except ImportError:
    WebArchiveProcessorAdapter = None

try:
    from .specialized_scraper_adapter import SpecializedScraperAdapter
except ImportError:
    SpecializedScraperAdapter = None


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

try:
    from .web_archive_adapter import WebArchiveProcessorAdapter
except ImportError:
    WebArchiveProcessorAdapter = None

try:
    from .specialized_scraper_adapter import SpecializedScraperAdapter
except ImportError:
    SpecializedScraperAdapter = None
