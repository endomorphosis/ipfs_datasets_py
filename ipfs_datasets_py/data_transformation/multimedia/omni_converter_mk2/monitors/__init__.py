"""
Managers for the Omni-Converter.

This package provides manager classes for orchestrating and monitoring the conversion process,
including batch processing, resource monitoring, error handling, and security validation.

Modules:
    batch_processor: Orchestrates batch processing of multiple files.
    resource_monitor: Monitors and manages system resources during conversion.
    error_monitor: Centralizes error handling and reporting.
    security_monitor: Validates file security and implements content sanitization.
    batch_result: Tracks and reports results of batch processing operations.

Implementation Status:
    - BatchProcessor: ✅ Complete
    - ResourceMonitor: ✅ Complete
    - ErrorMonitor: ✅ Complete
    - SecurityMonitor: ✅ Complete
    - BatchResult: ✅ Complete
"""
from .monitors_factory import (
    make_resource_monitor, 
    make_error_monitor, 
    make_security_monitor
)
from ._resource_monitor import ResourceMonitor
from ._error_monitor import ErrorMonitor
from .security_monitor import SecurityMonitor, SecurityResult

__all__ = [
    "make_resource_monitor",
    "make_error_monitor",
    "make_security_monitor",
    "ResourceMonitor",
    "ErrorMonitor",
    "SecurityMonitor",
    "SecurityResult",
]