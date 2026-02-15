import os


from types_ import Any, Callable, Processor, TypedDict
from configs import configs
from logger import logger
from supported_formats import SupportedFormats
from core.content_extractor.processors import make_processors


from ._text_handler import TextHandler
from ._application_handler import ApplicationHandler
from ._audio_handler import AudioHandler
from ._image_handler import ImageHandler
from ._video_handler import VideoHandler
from ._handler_capabilities import HandlerCapabilities
from utils.handlers import is_mock, can_handle, check_if_all_these_processors_are_mocks


def _create_text_handler(processors):
    """
    Factory function to create a TextHandler instance.
    
    Args:
        resources: Additional resources to provide.
        configs: Configuration settings.
        
    Returns:
        An instance of TextHandler.
    """
    resources = {
        "html_processor": processors["html_processor"],
        "xml_processor": processors["xml_processor"],
        "calendar_processor": processors["calendar_processor"],
        "text_processor": processors["text_processor"],
        "csv_processor": processors["csv_processor"],
        "format_extensions": SupportedFormats.TEXT_FORMAT_EXTENSIONS,
        "supported_formats": SupportedFormats.SUPPORTED_TEXT_FORMATS,
        "capabilities": HandlerCapabilities.TEXT_HANDLER_CAPABILITIES,
        "can_handle": can_handle,
        "logger": logger,
        "splitext": os.path.splitext,
    }

    # Create and return the TextHandler instance
    return TextHandler(resources=resources, configs=configs)


def _create_application_handler(processors) -> ApplicationHandler:
    """
    Factory function to create an ApplicationHandler instance.
    
    Returns:
        An instance of ApplicationHandler.
    """
    resources = {
        "pdf_processor": processors["pdf_processor"],
        "json_processor": processors["json_processor"],
        "docx_processor": processors["docx_processor"],
        "xlsx_processor": processors["xlsx_processor"],
        "zip_processor": processors["zip_processor"],
        "format_extensions": SupportedFormats.APPLICATION_FORMAT_EXTENSIONS,
        "supported_formats": SupportedFormats.SUPPORTED_APPLICATION_FORMATS,
        "capabilities": HandlerCapabilities.APPLICATION_HANDLER_CAPABILITIES,
        "logger": logger,
        "splitext": os.path.splitext,
    }
    return ApplicationHandler(resources=resources, configs=configs)


def _create_audio_handler(processors):
    """
    Factory function to create an AudioHandler instance.
    
    Returns:
        An instance of AudioHandler.
    """
    resources = {
        "audio_processor": processors["audio_processor"],
        "transcription_processor": processors["transcription_processor"],
        "format_extensions": SupportedFormats.AUDIO_FORMAT_EXTENSIONS,
        "supported_formats": SupportedFormats.SUPPORTED_AUDIO_FORMATS,
        "capabilities": HandlerCapabilities.AUDIO_HANDLER_CAPABILITIES,
        "logger": logger,
        "splitext": os.path.splitext,
    }
    
    # Create and return the AudioHandler instance
    return AudioHandler(resources=resources, configs=configs)


def _create_video_handler(processors):
    """
    Factory function to create a VideoHandler instance.

    Returns:
        An instance of VideoHandler.
    """
    resources = {
        "video_processor": processors["video_processor"],
        "transcription_processor": processors["transcription_processor"],
        "format_extensions": SupportedFormats.VIDEO_FORMAT_EXTENSIONS,
        "supported_formats": SupportedFormats.SUPPORTED_VIDEO_FORMATS,
        "capabilities": HandlerCapabilities.VIDEO_HANDLER_CAPABILITIES,
        "can_handle": can_handle,
        "logger": logger,
        "splitext": os.path.splitext,
    }
    # Create and return the VideoHandler instance
    return VideoHandler(resources=resources, configs=configs)


def _create_image_handler(processors):

    class ImageHandlerResources(TypedDict):
        raster_image_processor: Processor
        vector_image_processor: Processor
        ocr_processor: Processor
        format_extensions: dict[str, list[str]]
        supported_formats: set[str]
        capabilities: dict[str, Any]
        logger: Any
        splitext: Callable
        is_mock: bool

    # all_are_mocks = check_if_all_these_processors_are_mocks(
    #         "Image", ["raster_image_processor", "vector_image_processor"], processors
    #     )
    # if all_are_mocks:
    #     raise TypeError("Cannot instantiate Image handler as all processors are mocks.")

    resources: ImageHandlerResources = {
        "raster_image_processor": processors["raster_image_processor"],
        "vector_image_processor": processors["vector_image_processor"], 
        "ocr_processor": processors["ocr_processor"],
        "format_extensions": SupportedFormats.IMAGE_FORMAT_EXTENSIONS,
        "supported_formats": SupportedFormats.SUPPORTED_IMAGE_FORMATS,
        "vector_image_extensions": SupportedFormats.VECTOR_IMAGE_FORMAT_EXTENSIONS,
        "raster_image_extensions": SupportedFormats.RASTER_IMAGE_FORMAT_EXTENSIONS,
        "capabilities": HandlerCapabilities.IMAGE_HANDLER_CAPABILITIES,
        "logger": logger,
        "can_handle": can_handle,
        "is_mock": is_mock,
        "splitext": os.path.splitext,
    }
    return ImageHandler(resources=resources, configs=configs)

def make_all_handlers() -> dict[str, Callable]:
    """
    Create factory functions for all format handlers.
    
    Args:
        resources: Optional additional resources to provide to handlers.
        configs: Configuration settings.
        
    Returns:
        Dictionary mapping handler types to factory functions.
    """
    # Initialize processors for dependency injection
    processors = make_processors()
    handlers = {}

    # Create a dictionary of factory functions for each handler type
    for name, func in [
        ("audio", _create_audio_handler),
        ("image", _create_image_handler),
        ("text", _create_text_handler),
        ("video", _create_video_handler),
        ("application", _create_application_handler),
    ]:
        handlers[name] = func(processors)


    if not handlers:
        raise TypeError("Cannot instantiate any handlers, as all processors are mocks.")
    return handlers

