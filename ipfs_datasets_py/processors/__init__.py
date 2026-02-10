"""Processor modules for IPFS Datasets Python."""

from __future__ import annotations

# NOTE:
# Keep this package initializer lightweight.
# Importing processor implementations can pull in optional dependencies
# and/or modules that may not exist in minimal environments.

__all__ = [
    'graphrag_processor',
    'enhanced_multimodal_processor',
    'website_graphrag_processor',
    'advanced_graphrag_website_processor',
    'advanced_media_processing',
    'advanced_web_archiving',
    'multimodal_processor',
    'geospatial_analysis',
    'patent_scraper',
    'patent_dataset_api',
    'wikipedia_x',

    # PDF processing public surface (lazy via __getattr__)
    'PDFProcessor',
    'MultiEngineOCR',
    'SuryaOCR',
    'TesseractOCR',
    'EasyOCR',
    'LLMOptimizer',
    'LLMDocument',
    'LLMChunk',
    'GraphRAGIntegrator',
    'KnowledgeGraph',
    'Entity',
    'Relationship',
    'QueryEngine',
    'QueryResult',
    'QueryResponse',
    'RelationshipAnalyzer',
    'BatchProcessor',
    'ProcessingJob',
    'BatchStatus',
]


_PDF_EXPORTS = {
    'PDFProcessor',
    'MultiEngineOCR',
    'SuryaOCR',
    'TesseractOCR',
    'EasyOCR',
    'LLMOptimizer',
    'LLMDocument',
    'LLMChunk',
    'GraphRAGIntegrator',
    'KnowledgeGraph',
    'Entity',
    'Relationship',
    'QueryEngine',
    'QueryResult',
    'QueryResponse',
    'RelationshipAnalyzer',
    'BatchProcessor',
    'ProcessingJob',
    'BatchStatus',
}


def __getattr__(name: str):
    if name in _PDF_EXPORTS:
        from importlib import import_module

        pdf_processing = import_module('ipfs_datasets_py.processors.pdf_processing')
        return getattr(pdf_processing, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals().keys()) | _PDF_EXPORTS)
