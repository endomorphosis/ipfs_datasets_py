"""Canonical file conversion API surface.

Canonical import path:
    ipfs_datasets_py.processors.file_converter

This package is the canonical import location for the unified file conversion
pipeline and its related helpers.

It is intentionally import-safe: heavy/optional dependencies are only imported
when their specific functionality is accessed.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Tuple


__version__ = "0.7.0"  # Phase 7 - Package exports and MCP/CLI integration


_EXPORTS: Dict[str, Tuple[str, str]] = {
    # Core API
    "FileConverter": ("ipfs_datasets_py.processors.file_converter.converter", "FileConverter"),
    "ConversionResult": ("ipfs_datasets_py.processors.file_converter.converter", "ConversionResult"),

    # Pipeline API
    "Result": ("ipfs_datasets_py.processors.file_converter.pipeline", "Result"),
    "Error": ("ipfs_datasets_py.processors.file_converter.pipeline", "Error"),
    "ErrorType": ("ipfs_datasets_py.processors.file_converter.pipeline", "ErrorType"),
    "Outcome": ("ipfs_datasets_py.processors.file_converter.pipeline", "Outcome"),
    "ok": ("ipfs_datasets_py.processors.file_converter.pipeline", "ok"),
    "error": ("ipfs_datasets_py.processors.file_converter.pipeline", "error"),
    "wrap_exception": ("ipfs_datasets_py.processors.file_converter.pipeline", "wrap_exception"),
    "FileUnit": ("ipfs_datasets_py.processors.file_converter.pipeline", "FileUnit"),
    "Pipeline": ("ipfs_datasets_py.processors.file_converter.pipeline", "Pipeline"),
    "StreamProcessor": ("ipfs_datasets_py.processors.file_converter.pipeline", "StreamProcessor"),
    "validate_file_exists": ("ipfs_datasets_py.processors.file_converter.pipeline", "validate_file_exists"),
    "detect_format": ("ipfs_datasets_py.processors.file_converter.pipeline", "detect_format"),
    "extract_text": ("ipfs_datasets_py.processors.file_converter.pipeline", "extract_text"),

    # Native components
    "FormatDetector": ("ipfs_datasets_py.processors.file_converter.format_detector", "FormatDetector"),
    "detect_file_format": ("ipfs_datasets_py.processors.file_converter.format_detector", "detect_format"),
    "ExtractorRegistry": ("ipfs_datasets_py.processors.file_converter.text_extractors", "ExtractorRegistry"),
    "ExtractionResult": ("ipfs_datasets_py.processors.file_converter.text_extractors", "ExtractionResult"),
    "extract_file_text": ("ipfs_datasets_py.processors.file_converter.text_extractors", "extract_text"),

    # Errors
    "FileConversionError": ("ipfs_datasets_py.processors.file_converter.errors", "FileConversionError"),
    "ErrorHandler": ("ipfs_datasets_py.processors.file_converter.errors", "ErrorHandler"),
    "FallbackStrategy": ("ipfs_datasets_py.processors.file_converter.errors", "FallbackStrategy"),
    "with_fallback": ("ipfs_datasets_py.processors.file_converter.errors", "with_fallback"),
    "retry_with_backoff": ("ipfs_datasets_py.processors.file_converter.errors", "retry_with_backoff"),
    "ignore_errors": ("ipfs_datasets_py.processors.file_converter.errors", "ignore_errors"),
    "aggregate_errors": ("ipfs_datasets_py.processors.file_converter.errors", "aggregate_errors"),

    # IPFS integration
    "IPFSBackend": ("ipfs_datasets_py.processors.file_converter.backends.ipfs_backend", "IPFSBackend"),
    "get_ipfs_backend": ("ipfs_datasets_py.processors.file_converter.backends.ipfs_backend", "get_ipfs_backend"),
    "IPFS_AVAILABLE": ("ipfs_datasets_py.processors.file_converter.backends.ipfs_backend", "IPFS_AVAILABLE"),
    "IPFSAcceleratedConverter": (
        "ipfs_datasets_py.processors.file_converter.ipfs_accelerate_converter",
        "IPFSAcceleratedConverter",
    ),
    "IPFSConversionResult": (
        "ipfs_datasets_py.processors.file_converter.ipfs_accelerate_converter",
        "IPFSConversionResult",
    ),
    "create_converter": ("ipfs_datasets_py.processors.file_converter.ipfs_accelerate_converter", "create_converter"),

    # Advanced features
    "MetadataExtractor": ("ipfs_datasets_py.processors.file_converter.metadata_extractor", "MetadataExtractor"),
    "extract_metadata": ("ipfs_datasets_py.processors.file_converter.metadata_extractor", "extract_metadata"),
    "BatchProcessor": ("ipfs_datasets_py.processors.file_converter.batch_processor", "BatchProcessor"),
    "BatchProgress": ("ipfs_datasets_py.processors.file_converter.batch_processor", "BatchProgress"),
    "ResourceLimits": ("ipfs_datasets_py.processors.file_converter.batch_processor", "ResourceLimits"),
    "CacheManager": ("ipfs_datasets_py.processors.file_converter.batch_processor", "CacheManager"),
    "create_batch_processor": ("ipfs_datasets_py.processors.file_converter.batch_processor", "create_batch_processor"),

    # Deprecation utilities
    "warn_deprecated_backend": ("ipfs_datasets_py.processors.file_converter.deprecation", "warn_deprecated_backend"),
    "get_deprecation_info": ("ipfs_datasets_py.processors.file_converter.deprecation", "get_deprecation_info"),
    "is_deprecated": ("ipfs_datasets_py.processors.file_converter.deprecation", "is_deprecated"),
    "DEPRECATION_TIMELINE": ("ipfs_datasets_py.processors.file_converter.deprecation", "DEPRECATION_TIMELINE"),

    # Knowledge graph and summarization
    "UniversalKnowledgeGraphPipeline": (
        "ipfs_datasets_py.processors.file_converter.knowledge_graph_integration",
        "UniversalKnowledgeGraphPipeline",
    ),
    "TextSummarizationPipeline": (
        "ipfs_datasets_py.processors.file_converter.knowledge_graph_integration",
        "TextSummarizationPipeline",
    ),
    "BatchKnowledgeGraphProcessor": (
        "ipfs_datasets_py.processors.file_converter.knowledge_graph_integration",
        "BatchKnowledgeGraphProcessor",
    ),
    "KnowledgeGraphResult": (
        "ipfs_datasets_py.processors.file_converter.knowledge_graph_integration",
        "KnowledgeGraphResult",
    ),
    "TextSummaryResult": (
        "ipfs_datasets_py.processors.file_converter.knowledge_graph_integration",
        "TextSummaryResult",
    ),

    # Vector embeddings
    "VectorEmbeddingPipeline": (
        "ipfs_datasets_py.processors.file_converter.vector_embedding_integration",
        "VectorEmbeddingPipeline",
    ),
    "VectorEmbeddingResult": (
        "ipfs_datasets_py.processors.file_converter.vector_embedding_integration",
        "VectorEmbeddingResult",
    ),
    "SearchResult": ("ipfs_datasets_py.processors.file_converter.vector_embedding_integration", "SearchResult"),
    "create_vector_pipeline": (
        "ipfs_datasets_py.processors.file_converter.vector_embedding_integration",
        "create_vector_pipeline",
    ),

    # Archives
    "ArchiveHandler": ("ipfs_datasets_py.processors.file_converter.archive_handler", "ArchiveHandler"),
    "ArchiveExtractionResult": (
        "ipfs_datasets_py.processors.file_converter.archive_handler",
        "ArchiveExtractionResult",
    ),
    "extract_archive": ("ipfs_datasets_py.processors.file_converter.archive_handler", "extract_archive"),
    "is_archive": ("ipfs_datasets_py.processors.file_converter.archive_handler", "is_archive"),

    # Office formats
    "PowerPointExtractor": (
        "ipfs_datasets_py.processors.file_converter.office_format_extractors",
        "PowerPointExtractor",
    ),
    "ExcelLegacyExtractor": (
        "ipfs_datasets_py.processors.file_converter.office_format_extractors",
        "ExcelLegacyExtractor",
    ),
    "RTFExtractor": ("ipfs_datasets_py.processors.file_converter.office_format_extractors", "RTFExtractor"),
    "EPUBExtractor": ("ipfs_datasets_py.processors.file_converter.office_format_extractors", "EPUBExtractor"),
    "OpenDocumentExtractor": (
        "ipfs_datasets_py.processors.file_converter.office_format_extractors",
        "OpenDocumentExtractor",
    ),
    "extract_office_format": (
        "ipfs_datasets_py.processors.file_converter.office_format_extractors",
        "extract_office_format",
    ),
    "get_supported_office_formats": (
        "ipfs_datasets_py.processors.file_converter.office_format_extractors",
        "get_supported_office_formats",
    ),
    "is_office_format_supported": (
        "ipfs_datasets_py.processors.file_converter.office_format_extractors",
        "is_office_format_supported",
    ),
    "OfficeExtractionResult": (
        "ipfs_datasets_py.processors.file_converter.office_format_extractors",
        "OfficeExtractionResult",
    ),

    # URLs
    "URLHandler": ("ipfs_datasets_py.processors.file_converter.url_handler", "URLHandler"),
    "URLDownloadResult": ("ipfs_datasets_py.processors.file_converter.url_handler", "URLDownloadResult"),
    "download_from_url": ("ipfs_datasets_py.processors.file_converter.url_handler", "download_from_url"),
    "download_from_url_sync": (
        "ipfs_datasets_py.processors.file_converter.url_handler",
        "download_from_url_sync",
    ),
    "is_url": ("ipfs_datasets_py.processors.file_converter.url_handler", "is_url"),

    # CLI
    "cli_main": ("ipfs_datasets_py.processors.file_converter.cli", "main"),

    # Export helpers
    "convert_file": ("ipfs_datasets_py.processors.file_converter.exports", "convert_file"),
    "convert_file_sync": ("ipfs_datasets_py.processors.file_converter.exports", "convert_file_sync"),
    "batch_convert_files": ("ipfs_datasets_py.processors.file_converter.exports", "batch_convert_files"),
    "batch_convert_files_sync": (
        "ipfs_datasets_py.processors.file_converter.exports",
        "batch_convert_files_sync",
    ),
    "extract_knowledge_graph": ("ipfs_datasets_py.processors.file_converter.exports", "extract_knowledge_graph"),
    "extract_knowledge_graph_sync": (
        "ipfs_datasets_py.processors.file_converter.exports",
        "extract_knowledge_graph_sync",
    ),
    "generate_summary": ("ipfs_datasets_py.processors.file_converter.exports", "generate_summary"),
    "generate_summary_sync": ("ipfs_datasets_py.processors.file_converter.exports", "generate_summary_sync"),
    "generate_embeddings": ("ipfs_datasets_py.processors.file_converter.exports", "generate_embeddings"),
    "generate_embeddings_sync": (
        "ipfs_datasets_py.processors.file_converter.exports",
        "generate_embeddings_sync",
    ),
    "extract_archive_contents": (
        "ipfs_datasets_py.processors.file_converter.exports",
        "extract_archive_contents",
    ),
    "extract_archive_contents_sync": (
        "ipfs_datasets_py.processors.file_converter.exports",
        "extract_archive_contents_sync",
    ),
    "download_from_url_export": (
        "ipfs_datasets_py.processors.file_converter.exports",
        "download_from_url_export",
    ),
    "download_from_url_export_sync": (
        "ipfs_datasets_py.processors.file_converter.exports",
        "download_from_url_export_sync",
    ),
    "get_file_info": ("ipfs_datasets_py.processors.file_converter.exports", "get_file_info"),
    "get_file_info_sync": ("ipfs_datasets_py.processors.file_converter.exports", "get_file_info_sync"),
}


__all__ = ["__version__", *_EXPORTS.keys()]


def __getattr__(name: str) -> Any:
    if name == "__version__":
        globals()[name] = __version__
        return __version__

    target = _EXPORTS.get(name)
    if not target:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
