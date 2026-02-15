import os

from configs import configs
from logger import logger
from supported_formats import SupportedFormats
from utils.filesystem import FileSystem
from ._file_format_detector import FileFormatDetector


def make_file_format_detector():
    """
    Factory function to create a FileFormatDetector instance with proper dependencies.
    
    Returns:
        An instance of FileFormatDetector with all required dependencies injected.
    """
    resources = {
        'abspath': os.path.abspath,
        'get_file_info': FileSystem.get_file_info,
        'format_registry': SupportedFormats.FORMAT_REGISTRY, # -> dict[str, set[str]]
        'format_signatures': SupportedFormats.FORMAT_SIGNATURES,
        'format_extensions': SupportedFormats.FORMAT_EXTENSIONS,
        'logger': logger,
    }
    return FileFormatDetector(resources=resources, configs=configs)