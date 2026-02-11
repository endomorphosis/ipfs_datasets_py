"""Compatibility shims for the legacy `ipfs_datasets_py.pdf_processing` package.

The active implementation lives under `ipfs_datasets_py.processors`.
This package keeps older imports working:
- `from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor`
"""

from .pdf_processor import PDFProcessor

__all__ = ["PDFProcessor"]
