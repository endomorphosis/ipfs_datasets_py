"""
Unified File Converter for IPFS Datasets Python

Phase 1: Import and wrap existing libraries (omni_converter_mk2, convert_to_txt_based_on_mime_type)
Phase 2+: Gradual native reimplementation

This module provides a single, clean API for file conversion while allowing
gradual migration from external libraries to native implementation.
"""

from .converter import FileConverter, ConversionResult

__all__ = ['FileConverter', 'ConversionResult']

__version__ = '0.1.0'  # Phase 1 - Import & Wrap
