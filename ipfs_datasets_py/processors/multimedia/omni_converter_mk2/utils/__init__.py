"""
Omni-Converter Utilities

This package provides core utility functions and classes that form the foundation of the
Omni-Converter application. These utilities handle configuration management, file system
operations, format detection, validation, and logging.

Modules:
    config: Configuration management with support for nested keys and default values.
        - Configs: Handles loading, saving, and validating configuration settings.
        
    filesystem: File system operations, metadata, and content extraction.
        - FileSystem: Utilities for file reading, writing, and information retrieval.
        - FileInfo: Information about files including size, type, and permissions.
        - FileContent: Container for file content with encoding support.
        
    file_format_detector: MIME type and extension-based format detection.
        - FileFormatDetector: Detects file formats based on content and extension.
        
    logger: Structured logging with multiple output targets.
        - Logger: Logging functionality with configurable levels and outputs.
        - LogRecord: Detailed log entries with context and metadata.
        
    validator: File validation with configurable rules.
        - FileValidator: Validates files for processing with security checks.
        - ValidationResult: Contains validation status, errors, and metadata.

Implementation Status:
    These modules implement functionality described in the following class groups from the
    System Architecture Document:
    - Storage Class Group (FileSystem, Logger): 🔄 In Progress
    - Interface Class Group (Configs): 🔄 In Progress
    - Core Processing Class Group (FileFormatDetector, FileValidator): 🔄 In Progress
    - Managers Class Group: ❌ Not Started
    - Format Handlers Class Group: ❌ Not Started
"""

# from utils.common.try_except_decorator import try_except
# from utils.common.dependencies.tqdm import Tqdm
# from utils.llm import make_llm_components
# from utils.main_ import (
#     make_content_extractor,
#     make_ocr_processor,
#     make_text_processor,
#     make_image_processor,
#     make_audio_processor,
#     make_video_processor,
#     make_application_processor,
#     make_text_extractor,
#     make_image_extractor,
#     make_audio_extractor,
#     make_video_extractor,
#     make_application_extractor,
# )

from .filesystem import FileSystem, FileInfo, FileContent
from .hardware import Hardware

__all__ = [
    "FileSystem",
    "FileInfo",
    "FileContent",
    "Hardware",
]