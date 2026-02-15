

import contextlib
import zipfile
import tempfile
import tarfile
import os


from configs import configs
from logger import logger
from types_ import Any, Callable, Optional


from ._archive_security import ArchiveSecurity
from ._document_security import DocumentSecurity
from ._image_security import ImageSecurity
from ._video_security import VideoSecurity
from ._audio_security import AudioSecurity


def make_archive_security(mock_dict: Optional[dict[str, Any]] = None) -> ArchiveSecurity:
    """Factory function to create an archive security check instance.

    Args:
        mock_dict (Optional[dict[str, Any]]): Optional dictionary for mocking dependencies.

    Returns:
        ArchiveSecurity: An instance of ArchiveSecurity.
    """
    resources = {
        "zipfile": zipfile,
        "logger": logger,
        "closing": contextlib.closing,
        "tempfile": tempfile,
        "tarfile": tarfile,
        "os": os,
    }
    if isinstance(mock_dict, dict):
        resources.update(mock_dict)

    return ArchiveSecurity(resources=resources, configs=configs)


def make_document_security(mock_dict: Optional[dict[str, Any]] = None) -> DocumentSecurity:
    """Factory function to create a document security check instance.

    Args:
        mock_dict (Optional[dict[str, Any]]): Optional dictionary for mocking dependencies.

    Returns:
        DocumentSecurity: An instance of DocumentSecurity.
    """
    resources = {
        "logger": logger,
    }
    if isinstance(mock_dict, dict):
        resources.update(mock_dict)

    return DocumentSecurity(resources=resources, configs=configs)

def make_image_security(mock_dict: Optional[dict[str, Any]] = None) -> ImageSecurity:
    """Factory function to create an image security check instance.

    Args:
        mock_dict (Optional[dict[str, Any]]): Optional dictionary for mocking dependencies.

    Returns:
        ImageSecurity: An instance of ImageSecurity.
    """
    resources = {
        "logger": logger,
    }
    if isinstance(mock_dict, dict):
        resources.update(mock_dict)

    return ImageSecurity(resources=resources, configs=configs)

def make_video_security(mock_dict: Optional[dict[str, Any]] = None) -> VideoSecurity:
    """Factory function to create a video security check instance.

    Args:
        mock_dict (Optional[dict[str, Any]]): Optional dictionary for mocking dependencies.

    Returns:
        VideoSecurity: An instance of VideoSecurity.
    """
    resources = {
        "logger": logger,
    }
    if isinstance(mock_dict, dict):
        resources.update(mock_dict)

    return VideoSecurity(resources=resources, configs=configs)

def make_audio_security(mock_dict: Optional[dict[str, Any]] = None) -> AudioSecurity:
    """Factory function to create an audio security check instance.

    Args:
        mock_dict (Optional[dict[str, Any]]): Optional dictionary for mocking dependencies.

    Returns:
        Callable: An instance of AudioSecurity.
    """
    resources = {
        "logger": logger,
    }
    if isinstance(mock_dict, dict):
        resources.update(mock_dict)

    return AudioSecurity(resources=resources, configs=configs)

