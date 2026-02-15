"""
Factory module for creating ProcessingPipeline instances.

This module provides the factory function for creating ProcessingPipeline instances
following the IoC pattern.
"""
import hashlib

from configs import configs
from logger import logger
from file_format_detector import make_file_format_detector

from types_ import Callable, Logger, TypedDict, ModuleType

from ._processing_pipeline import ProcessingPipeline
from ._pipeline_status import PipelineStatus
from ._processing_result import ProcessingResult
from .file_validator import make_file_validator
from .text_normalizer import make_text_normalizer
from .output_formatter import make_output_formatter
from .content_extractor import make_content_extractor
from .content_sanitizer import make_content_sanitizer, ContentSanitizer
from monitors import make_security_monitor, SecurityMonitor
from .output_formatter import OutputFormatter
from .output_formatter import FormattedOutput


def make_processing_pipeline() -> ProcessingPipeline:
    """
    Factory function to create a ProcessingPipeline instance.
    
    Returns:
        An instance of ProcessingPipeline configured with proper dependencies.
    """
    class _ProcessingPipelineResources(TypedDict):
        file_format_detector: Callable
        file_validator: Callable
        content_extractor: Callable
        text_normalizer: Callable
        output_formatter: Callable
        processing_result: ProcessingResult
        pipeline_status: PipelineStatus
        content_sanitizer: ContentSanitizer
        security_monitor: SecurityMonitor
        logger: Logger
        hashlib: ModuleType

    resources: _ProcessingPipelineResources = {
        "file_format_detector": make_file_format_detector(),
        "file_validator": make_file_validator(),
        "content_extractor": make_content_extractor(),
        "text_normalizer": make_text_normalizer(),
        "output_formatter": make_output_formatter(),
        "content_sanitizer": make_content_sanitizer(),
        "security_monitor": make_security_monitor(),
        "processing_result": ProcessingResult,
        "pipeline_status": PipelineStatus(),
        "logger": logger,
        "hashlib": hashlib
    }
    return ProcessingPipeline(resources=resources, configs=configs)
