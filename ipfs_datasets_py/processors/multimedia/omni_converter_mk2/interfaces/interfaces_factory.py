"""
Interface Factory for the Omni-Converter.

This module provides a factory for creating interface instances, such as the CLI and Python API.
This allows for centralized configuration and management of interfaces.
"""
from batch_processor import make_batch_processor
from monitors import make_resource_monitor, make_error_monitor, make_security_monitor
from core import make_processing_pipeline
from supported_formats import SupportedFormats

from interfaces._python_api import PythonAPI
from interfaces._cli import CLI

from configs import configs
from logger import logger
from dependencies import dependencies
from .options import Options

def make_cli() -> CLI:
    """
    Create a Python API for the Omni-Converter.
    """
    from utils.main_ import (
        list_normalizers, 
        list_output_formats, 
        show_version, 
        progress_callback, 
        list_supported_formats
    )
    resource_monitor = make_resource_monitor()
    error_monitor = make_error_monitor()
    security_monitor = make_security_monitor()

    resources = {
        'supported_formats': SupportedFormats.SUPPORTED_FORMATS,
        'processing_pipeline': make_processing_pipeline(),
        'batch_processor': make_batch_processor(),
        'security_monitor': security_monitor,
        'resource_monitor': resource_monitor,
        'error_monitor': error_monitor,
        'list_supported_formats': list_supported_formats,
        'list_normalizers': list_normalizers,
        'list_output_formats': list_output_formats,
        'processing_pipeline': make_processing_pipeline(),
        'show_version': show_version,
        'progress_callback': progress_callback,
        'tqdm': dependencies.tqdm,
        'logger': logger,
        'options': Options,
    }
    return CLI(resources=resources, configs=configs)

def make_api() -> PythonAPI:
    """
    Create a Python API for the Omni-Converter.
    """
    resources = {
        'supported_formats': SupportedFormats.SUPPORTED_FORMATS,
        'processing_pipeline': make_processing_pipeline(),
        'batch_processor': make_batch_processor(),
        'resource_monitor': make_resource_monitor(),
        'error_monitor': make_error_monitor(),
        'security_monitor': make_security_monitor(),
        'logger': logger,
    }
    return PythonAPI(resources=resources,configs=configs)

def make_gui() -> None:
    """
    Create a GUI interface for the Omni-Converter.

    This function initializes the GUI with necessary resources and configurations.
    Currently, the GUI is not implemented, but this function serves as a placeholder
    for future development.
    """
    raise NotImplementedError("GUI is not implemented yet. Please use CLI or API interfaces.")
