"""
File Detection Tools for MCP Server

Tools for detecting file types using multiple methods including extension analysis,
magic bytes detection, and AI-powered Magika detection.
"""

from .detect_file_type import detect_file_type
from .batch_detect_file_types import batch_detect_file_types
from .analyze_detection_accuracy import analyze_detection_accuracy

__all__ = [
    'detect_file_type',
    'batch_detect_file_types',
    'analyze_detection_accuracy'
]
