"""
Multimodal Processing - Specialized multimodal content processing.

This package provides comprehensive multimodal processing capabilities:
- Text, image, audio, video processing
- Quality metrics and validation
- Batch processing with parallel execution
- Context-aware processing
- Multi-format support

Main Classes:
- EnhancedMultiModalProcessor: Enhanced multimodal processor with quality metrics
- MultiModalContentProcessor: Basic multimodal content processor
- ProcessedContent: Processed content data structure
- ProcessingContext: Processing context and configuration

Example:
    from ipfs_datasets_py.processors.specialized.multimodal import EnhancedMultiModalProcessor
    
    processor = EnhancedMultiModalProcessor()
    result = await processor.process_content(content)
"""

try:
    from .processor import (
        EnhancedMultiModalProcessor,
        ContentQualityMetrics,
        ProcessingContext,
    )
    _enhanced_available = True
except ImportError as e:
    import warnings
    warnings.warn(f"Enhanced multimodal processor unavailable: {e}", ImportWarning)
    EnhancedMultiModalProcessor = None
    ContentQualityMetrics = None
    ProcessingContext = None
    _enhanced_available = False

try:
    from .multimodal_processor import (
        MultiModalContentProcessor,
        ProcessedContent,
        ProcessedContentBatch,
    )
    _basic_available = True
except ImportError as e:
    import warnings
    warnings.warn(f"Basic multimodal processor unavailable: {e}", ImportWarning)
    MultiModalContentProcessor = None
    ProcessedContent = None
    ProcessedContentBatch = None
    _basic_available = False

__all__ = [
    'EnhancedMultiModalProcessor',
    'ContentQualityMetrics',
    'ProcessingContext',
    'MultiModalContentProcessor',
    'ProcessedContent',
    'ProcessedContentBatch',
]
