"""
Test suite for batch_processor/_batch_processor.py converted from unittest to pytest.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock, call
import threading
import time
import os
from concurrent.futures import Future, TimeoutError
import concurrent.futures
import datetime
import glob
import tempfile
from pathlib import Path
import gc
import copy
from typing import Any, Callable, Optional, Union

from batch_processor._batch_processor import BatchProcessor, _BatchState
from batch_processor._batch_result import BatchResult
from batch_processor._get_output_path import get_output_path
from batch_processor._resolve_paths import resolve_paths

from logger import logger
from configs import configs, Configs, _Resources, _Formats, _Output, _Processing, _Security, _PathsBaseModel
from core import make_processing_pipeline
from monitors import make_error_monitor, make_resource_monitor, make_security_monitor
from monitors._error_monitor import ErrorMonitor
from monitors._resource_monitor import ResourceMonitor
from monitors.security_monitor._security_monitor import SecurityMonitor
from core._processing_pipeline import ProcessingPipeline
from core._processing_result import ProcessingResult
from types_ import Logger, TypedDict


def make_mock_resources() -> dict[str, Any]:
    """Create mock resources for BatchProcessor testing."""
    resources = {
        'processing_pipeline': MagicMock(spec=ProcessingPipeline),
        'error_monitor': MagicMock(spec=ErrorMonitor),
        'resource_monitor': MagicMock(spec=ResourceMonitor),
        'security_monitor': MagicMock(spec=SecurityMonitor),
        'logger': MagicMock(spec=Logger),
        'processing_result': MagicMock(spec=ProcessingResult),
        'batch_result': MagicMock(spec=BatchResult),
        "get_output_path": MagicMock(spec=get_output_path),
        "resolve_paths": MagicMock(spec=resolve_paths),
        "gc_collect": MagicMock(spec=gc.collect),
        'concurrent_futures_ThreadPoolExecutor': MagicMock(spec=concurrent.futures.ThreadPoolExecutor),
        'concurrent_futures_ProcessPoolExecutor': MagicMock(spec=concurrent.futures.ProcessPoolExecutor),
        'concurrent_futures_as_completed': MagicMock(spec=concurrent.futures.as_completed),
        'time_time': MagicMock(spec=time.time),
        'cf': MagicMock(spec=concurrent.futures),
        'glob_glob': MagicMock(spec=glob.glob),
        'os': MagicMock(spec=os),
        'os_path_exists': MagicMock(spec=os.path.exists),
        'os_makedirs': MagicMock(spec=os.makedirs),
        'os_path_join': MagicMock(spec=os.path.join),
        'os_path_isfile': MagicMock(spec=os.path.isfile),
        'os_path_isdir': MagicMock(spec=os.path.isdir),
        'os_path_abspath': MagicMock(spec=os.path.abspath),
        'os_path_realpath': MagicMock(spec=os.path.realpath),
        'os_path_split': MagicMock(spec=os.path.split),
        'os_walk': MagicMock(spec=os.walk),
        'os_path_islink': MagicMock(spec=os.path.islink),
        'os_path_getsize': MagicMock(spec=os.path.getsize),
        'os_path_basename': MagicMock(spec=os.path.basename),
        'os_path_dirname': MagicMock(spec=os.path.dirname),
        'threading_RLock': MagicMock(spec=threading.RLock),
    }
    return resources


def make_mock_configs() -> Any:
    """Create mock configs for BatchProcessor testing."""
    mock_configs = MagicMock(spec=Configs)
    mock_configs.resources = MagicMock(spec=_Resources)
    mock_configs.processing = MagicMock(spec=_Processing)
    mock_configs.security = MagicMock(spec=_Security)
    mock_configs.paths = MagicMock(spec=_PathsBaseModel)
    mock_configs.formats = MagicMock(spec=_Formats)
    mock_configs.output = MagicMock(spec=_Output)
    mock_configs.resources.max_batch_size = 100
    mock_configs.resources.max_threads = 4
    mock_configs.processing.continue_on_error = True
    return mock_configs


@pytest.fixture
def mock_resources():
    """Provide mock resources for testing."""
    return make_mock_resources()


@pytest.fixture 
def mock_configs():
    """Provide mock configs for testing."""
    return make_mock_configs()


@pytest.mark.unit
class TestBatchProcessorInitialization:
    """Test BatchProcessor initialization and configuration."""

    def test_init_with_all_parameters(self, mock_resources, mock_configs):
        """
        GIVEN valid configs and resources
        WHEN BatchProcessor is initialized
        THEN expect:
            - All attributes properly set from configs and resources
        """
        # Act
        processor = BatchProcessor(resources=mock_resources, configs=mock_configs)
        
        # Assert
        assert isinstance(processor, BatchProcessor)
        assert processor.configs == mock_configs
        assert processor.resources == mock_resources