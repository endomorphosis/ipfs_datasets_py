import atexit
from configs import configs
from logger import logger
from utils.hardware import Hardware

from typing import Any, Callable, Optional

from ._resource_monitor import ResourceMonitor
from .security_monitor import SecurityMonitor, SecurityResult
from ._error_monitor import ErrorMonitor

from monitors.security_monitor.specific_checks import (
    make_archive_security, 
    make_document_security,
    make_image_security,
    make_video_security,
    make_audio_security,
)

from ._constants import Constants

import datetime
import traceback


def make_resource_monitor(mock_dict: Optional[dict[str, Any]] = None) -> ResourceMonitor:
    """Factory function to create and configure a ResourceMonitor instance.

    Returns:
        ResourceMonitor: A configured monitor instance with hardware resource
            tracking functions, logger, and system configurations.
    """
    resources = {
        "get_cpu_usage_in_percent": Hardware.get_cpu_usage_in_percent,
        "get_virtual_memory_in_percent": Hardware.get_virtual_memory_in_percent,
        "get_memory_info": Hardware.get_memory_info,
        "get_memory_rss_usage_in_mb": Hardware.get_memory_rss_usage_in_mb,
        "get_memory_vms_usage_in_mb": Hardware.get_memory_vms_usage_in_mb,
        "get_disk_usage": Hardware.get_disk_usage_in_percent,
        "get_open_files": Hardware.get_num_open_files,
        "get_shared_memory_usage_in_mb": Hardware.get_shared_memory_usage_in_mb,
        "get_num_cpu_cores": Hardware.get_num_cpu_cores,
        "get_vram_info": Hardware.get_vram_info,
        "get_cpu_info": Hardware.get_cpu_info,
        "get_gpu_info": Hardware.get_gpu_info,
        "logger": logger,
    }

    if isinstance(mock_dict, dict):
        resources.update(mock_dict)

    return ResourceMonitor(resources=resources,configs=configs)


def make_error_monitor(mock_dict: Optional[dict[str, Any]] = None) -> ErrorMonitor:
    """Create an ErrorMonitor instance.

    Returns:
        ErrorMonitor: A configured ErrorMonitor instance ready for use.
    """
    resources = {
        "logger": logger,
        "traceback": traceback,
        "datetime": datetime,
    }
    if isinstance(mock_dict, dict):
        resources.update(mock_dict)

    error_monitor = ErrorMonitor(resources=resources, configs=configs)

    # Register core_dump function to run on an unexpected exit.
    atexit.register(error_monitor.core_dump)
    return error_monitor


def make_security_monitor(mock_dict: Optional[dict[str, Any]] = None) -> SecurityMonitor:
    """Create a security monitor instance.

    Returns:
        An instance of SecurityMonitor.
    """
    archive_security = make_archive_security()
    document_security = make_document_security()
    image_security = make_image_security()
    video_security = make_video_security()
    audio_security = make_audio_security()

    resources = {
        "dangerous_patterns": Constants.SecurityMonitor.DANGEROUS_PATTERNS_REGEX,
        "executable_extensions": Constants.SecurityMonitor.EXECUTABLE_EXTENSIONS,
        "file_size_limits_in_bytes": Constants.SecurityMonitor.FILE_SIZE_LIMITS_IN_BYTES,
        "format_names": Constants.SecurityMonitor.FORMAT_NAMES,
        "pii_detection_regex": Constants.SecurityMonitor.PII_DETECTION_REGEX,
        "remove_active_content_regex": Constants.SecurityMonitor.REMOVE_ACTIVE_CONTENT_REGEX,
        "remove_scripts_regex": Constants.SecurityMonitor.REMOVE_SCRIPTS_REGEX,
        "security_rules": Constants.SecurityMonitor.SECURITY_RULES,
        "sensitive_keys": Constants.SecurityMonitor.SENSITIVE_KEYS,
        "security_result": SecurityResult,
        "logger": logger,
        "check_archive_security": archive_security.check_archive_security,
        "check_document_security": document_security.check_document_security,
        "check_image_security": image_security.check_image_security,
        "check_video_security": video_security.check_video_security,
        "check_audio_security": audio_security.check_audio_security,
    }

    if isinstance(mock_dict, dict):
        resources.update(mock_dict)

    return SecurityMonitor(resources=resources, configs=configs)
