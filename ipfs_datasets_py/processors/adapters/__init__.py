"""
Processor Adapters - Wrap existing processors in ProcessorProtocol interface.

This module contains adapters that wrap existing processors to implement
the ProcessorProtocol interface, enabling them to work with UniversalProcessor.

Adapters provide a bridge between the old processor APIs and the new
unified interface.
"""

# Adapters will be implemented in separate files:
# - pdf_adapter.py - Wraps PDF processors
# - graphrag_adapter.py - Wraps GraphRAG processors  
# - multimedia_adapter.py - Wraps multimedia processors
# - file_converter_adapter.py - Wraps file converter
# - batch_adapter.py - Wraps batch processor

__all__ = []
