"""Advanced media processing package.

This package provides comprehensive audio and video processing capabilities
for the GraphRAG system, including transcription, frame extraction, subtitle
handling, and multimedia analysis.
"""

from .advanced_processing import (
    AdvancedMediaProcessor,
    MediaContent,
    TranscriptionResult,
)

__all__ = [
    'AdvancedMediaProcessor',
    'MediaContent',
    'TranscriptionResult',
]
