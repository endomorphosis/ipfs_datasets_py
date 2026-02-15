"""
Centralized type-shed for the program.
Includes built-in types, custom types, and type aliases.

Made because there are too many types to keep track of in the main codebase,
and I want to keep it clean, readable, and un-import-error-able.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, Mock
from threading import Thread
from types import ModuleType
from typing import (
    Any, Callable, Coroutine, Generator,
    Optional, Protocol, TYPE_CHECKING,
    Type, TypeAlias, TypedDict, 
    TypeVar, Union, NamedTuple,
    Pattern
)
from protocols import Processor

try:
    from pydantic import BaseModel
except ImportError:
    raise ImportError("Critical dependency Pydantic is not installed.")

if TYPE_CHECKING:
    pass # FIXME/TODO Figure out how to import these types without causing circular imports.
    # #from configs import Configs
    # from core._pipeline_status import PipelineStatus
    # from core._processing_pipeline import ProcessingPipeline
    # # from core._processing_result import ProcessingResult
    # #from core.content_extractor.content import Content # TODO
    # #from core.text_normalizer._normalized_content import _normalized_content
    # from dependencies import _Dependencies as Dependencies
    # from external_programs import ExternalPrograms
    # from file_format_detector._file_format_detector import FileFormatDetector
    # from monitors._resource_monitor import ResourceMonitor
    # from monitors.security_monitor._security_monitor import SecurityMonitor
    # #from monitors.security_monitor._security_result import SecurityResult
    # from supported_formats import SupportedFormats

# Convert imports to TypeVars
PipelineStatus = TypeVar('PipelineStatus')
ProcessingPipeline = TypeVar('ProcessingPipeline')
Dependencies = TypeVar('Dependencies')
ExternalPrograms = TypeVar('ExternalPrograms')
FileFormatDetector = TypeVar('FileFormatDetector')
ResourceMonitor = TypeVar('ResourceMonitor')
SecurityMonitor = TypeVar('SecurityMonitor')
SupportedFormats = TypeVar('SupportedFormats')
FormatRegistry = TypeVar('FormatRegistry')


Content = TypeVar('Content', bound=Callable[..., Any])
FormatterFunc: TypeAlias = Callable[[Content], str]
FormattedOutput: TypeAlias = Content
NormalizedContent = TypeVar('NormalizedContent', bound=Callable[..., Any])
FileFormatDetector = TypeVar('FileFormatDetector', bound=ModuleType)
SupportedFormats = TypeVar('SupportedFormats', bound=dict[str, Any])


Logger: TypeAlias = logging.Logger
Dependency: TypeAlias = ModuleType
BuiltinModule: TypeAlias = ModuleType
Configs: TypeAlias = BaseModel
FileInfo: TypeAlias = BaseModel


NormalizerFunc: TypeAlias = Callable[[str], str]
StatusListenerFunc: TypeAlias = Callable[[str], None]
ProgressCallback: TypeAlias = Callable[[int, int, str], None]
ProcessingResult: TypeAlias = Any # Dataclass
SecurityResult: TypeAlias = BaseModel
ProcessingPipeline: TypeAlias = Any # Dataclass
BatchResult = TypeVar("BatchResult", bound=dict[str, Any])
SanitizedContent = TypeVar("SanitizedContent", bound=Callable[..., Any])
BatchProcessor = TypeVar("BatchProcessor", bound=Callable[..., Any])
ContentExtractor = TypeVar("ContentExtractor", bound=Callable[..., Any])
ErrorMonitor = TypeVar("ErrorMonitor", bound=Callable[..., Any])
TextNormalizer = TypeVar("TextNormalizer", bound=Callable[..., Any])
FileValidator = TypeVar("FileValidator", bound=Callable[..., Any])
SecurityMonitor = TypeVar("SecurityMonitor", bound=Callable[..., Any])
OutputFormatter = TypeVar("OutputFormatter", bound=Callable[..., Any])
AbilityProcessor = TypeVar("AbilityProcessor", bound=Callable[..., Any])
ContentSanitizer = TypeVar("ContentSanitizer", bound=Callable[..., Any])

# NOTE This is placeholder used to represent objects that are specific to a dependency
# Ex: DataFrames from Pandas, or Numpy arrays
# We do this because we don't know which dependencies will be used for any given processor.
DependencySpecificObject = TypeVar("DependencyObject", bound=Callable[..., Any])

# Interfaces
PythonAPI = TypeVar('PythonAPI', bound=Callable[..., Any])
Cli = TypeVar('CLI')
Gui = TypeVar('GUI')
Options: TypeAlias = BaseModel
RLock = TypeVar('RLock', bound=Callable[..., Any])
