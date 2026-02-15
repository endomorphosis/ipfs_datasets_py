"""
Factory module for creating format handlers and registries.

This module provides factory functions for creating format handlers and assembling
them into a format registry. It centralizes the creation of these components
and manages their dependencies.
"""
import os
from types_ import Any, Callable, Logger, TypedDict

from configs import configs
from logger import logger

from core.content_extractor._content import Content
from ._content_extractor import ContentExtractor
from ._map_extension_to_format import map_extension_to_format
from .handlers import make_all_handlers
from .processors import make_processors
from file_format_detector import make_file_format_detector 
from supported_formats import SupportedFormats
from utils.filesystem import FileSystem


class _ContentExtractorResources(TypedDict):
    handlers: dict[str, Any]
    file_format_detector: str
    supported_formats: dict[str, frozenset[tuple[str]]]
    map_extension_to_format: Callable
    read_file: Callable
    splitext: Callable
    logger: Logger
    content: Content


def make_content_extractor() -> ContentExtractor:

    handlers = make_all_handlers()
    processors = make_processors()

    resources: _ContentExtractorResources = {
        "capabilities": {
            "application": handlers["application"],
            "text": handlers["text"],
            "audio": handlers["audio"],
            "video": handlers["video"],
            "image": handlers["image"],
        },
        "processors": processors,
        "file_format_detector": make_file_format_detector(),
        "supported_formats": SupportedFormats,
        "map_extension_to_format": map_extension_to_format,
        "read_file": FileSystem.read_file,
        "splitext": os.path.splitext,
        "file_exists": FileSystem.file_exists,
        "logger": logger,
        "content": Content, 
    }
    return ContentExtractor(resources=resources, configs=configs)
