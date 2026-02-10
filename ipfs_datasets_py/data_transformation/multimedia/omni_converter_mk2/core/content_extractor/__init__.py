"""
Format Handlers for the Omni-Converter.

This package provides format-specific handlers for extracting content from different file types.
Format handlers are responsible for processing files of specific formats and extracting
human-readable text from them.

Modules:
    base_handler: Base classes and interfaces for format handlers.
    text_handler: Handlers for text-based formats (HTML, XML, plain text, etc.).
    image_handler: Handlers for image formats (JPEG, PNG, GIF, etc.).
    application_handler: Handlers for application formats (PDF, JSON, ZIP, etc.).
    audio_handler: Handlers for audio formats (MP3, WAV, OGG, etc.).
    video_handler: Handlers for video formats (MP4, WEBM, AVI, etc.).
    
Implementation Status:
    - Base Handler Interface: ✅ Complete
    - Text Handlers: ✅ Complete
    - Image Handlers: ✅ Complete
    - Application Handlers: ✅ Complete 
    - Audio Handlers: ✅ Complete
    - Video Handlers: ✅ Complete
"""
from .content_extractor_factory import make_content_extractor
from ._content_extractor import ContentExtractor
from ._content import Content

extractor = make_content_extractor()

__all__ = [
    'make_content_extractor',
    'ContentExtractor',
    'ContentExtractor',
]
