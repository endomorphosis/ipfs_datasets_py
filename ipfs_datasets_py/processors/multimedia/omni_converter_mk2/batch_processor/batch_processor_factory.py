import concurrent.futures
import gc
import glob
import os
import threading
import time


from logger import logger
from configs import configs
from core import make_processing_pipeline
from monitors import make_error_monitor, make_resource_monitor, make_security_monitor
from monitors._error_monitor import ErrorMonitor
from monitors._resource_monitor import ResourceMonitor
from monitors.security_monitor._security_monitor import SecurityMonitor
from core._processing_pipeline import ProcessingPipeline
from core._processing_result import ProcessingResult


from ._async_batch_processor import AsyncBatchProcessor
from ._batch_processor import BatchProcessor
from ._batch_result import BatchResult
from ._get_output_path import get_output_path
from ._resolve_paths import resolve_paths


from types_ import Logger, TypedDict


class _BatchProcessorResources(TypedDict):
    """
    TypedDict for BatchProcessor resources.
    
    Attributes:
        processing_pipeline: Instance of ProcessingPipeline.
        error_monitor: Instance of ErrorMonitor.
        resource_monitor: Instance of ResourceMonitor.
        security_monitor: Instance of SecurityMonitor.
        logger: Logger instance.
    """
    processing_pipeline: ProcessingPipeline
    error_monitor: ErrorMonitor
    resource_monitor: ResourceMonitor
    security_monitor: SecurityMonitor
    logger: Logger
    processing_result: ProcessingResult
    batch_result: BatchResult
    gc: gc
    threading: threading
    cf: concurrent.futures
    glob: glob
    os: os


def make_async_batch_processor() -> AsyncBatchProcessor:
    pass


def make_batch_processor() -> BatchProcessor:
    """Make a BatchProcessor instance.

    Returns:
        An instance of BatchProcessor.
    """



    resources: _BatchProcessorResources = {
        'processing_pipeline': make_processing_pipeline(),
        'error_monitor': make_error_monitor(),
        'resource_monitor': make_resource_monitor(),
        'security_monitor': make_security_monitor(),
        "logger": logger,
        "processing_result": ProcessingResult,
        "batch_result": BatchResult,
        "get_output_path": get_output_path,
        "resolve_paths": resolve_paths,

        # Builtins
        "gc_collect": gc.collect,
        "concurrent_futures_ThreadPoolExecutor": concurrent.futures.ThreadPoolExecutor,
        "concurrent_futures_ProcessPoolExecutor": concurrent.futures.ProcessPoolExecutor,
        "concurrent_futures_as_completed": concurrent.futures.as_completed,
        "time_time": time.time,
        "cf": concurrent.futures,
        "glob_glob": glob.glob,
        "os": os,
        "os_path_exists": os.path.exists,
        "os_makedirs": os.makedirs,
        "os_path_join": os.path.join,
        "os_path_isfile": os.path.isfile,
        "os_path_isdir": os.path.isdir,
        "os_path_abspath": os.path.abspath,
        "os_path_realpath": os.path.realpath,
        "os_path_split": os.path.split,
        "os_walk": os.walk,
        "os_path_islink": os.path.islink,
        "os_path_getsize": os.path.getsize,
        "os_path_basename": os.path.basename,
        "os_path_dirname": os.path.dirname,
        "threading_RLock": threading.RLock,
    }
    return BatchProcessor(configs=configs, resources=resources)
