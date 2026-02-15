"""
Configuration manager for the Omni-Converter.

This module provides a configuration manager that handles loading, saving, and validating
configuration settings for the Omni-Converter.
"""
from pathlib import Path
from typing import Any, Union

try:
    from pydantic import (
        BaseModel, 
        DirectoryPath, 
        FilePath, 
        Field, 
        PositiveInt, 
        PositiveFloat, 
        ValidationError
    )
    import psutil
    import yaml
except ImportError as e:
    raise ImportError("Required libraries are not installed. Please install pydantic, psutil, and pyyaml.")


from __version__ import __version__


def _get_cpu_cores(minus: int) -> int:
    """
    Get the number of CPU cores.

    Returns:
        Number of CPU cores.
    """
    return psutil.cpu_count(logical=False) - minus


class _PathsBaseModel(BaseModel):
    """
    Paths for important files and directories.

    Attributes:
        THIS_FILE: DirectoryPath: The path to this file (configs.py)
        THIS_DIR: DirectoryPath: The directory containing this file (utils).
        ROOT_DIR: DirectoryPath: The root directory of the project.
        CONFIG_PATH: DirectoryPath: The path to the configuration file (configs.yaml).
    """
    THIS_FILE: DirectoryPath = Path(__file__).resolve()
    THIS_DIR: DirectoryPath = THIS_FILE.parent
    ROOT_DIR: DirectoryPath = THIS_DIR
    CONFIG_PATH: FilePath = ROOT_DIR / 'configs.yaml'
    NORMALIZER_FUNCTIONS_DIR: DirectoryPath = ROOT_DIR / 'core' / 'text_normalizer' / 'default_normalizers'
    PLUGINS_DIR: DirectoryPath = ROOT_DIR / 'plugins'
    PROCESSORS_DIR: DirectoryPath = ROOT_DIR / 'core' / 'content_extractor' / 'processors'


def name(e: Exception) -> str:
    """Get the string name of the error."""
    return type(e).__name__

def getitem(self, key: str) -> Union[str, int, float]:
    try:
        return getattr(self, key)
    except AttributeError as e:
        raise KeyError(f"Key '{key}' not found in configuration: {e}") from e

def setitem(self, key: str, value: Any) -> None:
    try:
        setattr(self, key, value)
        self.model_validate()
    except ValidationError as e:
        raise ValueError(f"Invalid value for key '{key}': {value}") from e
    except TypeError as e:
        raise TypeError(f"Invalid type for key '{key}': {type(value)}") from e
    except AttributeError as e:
        raise KeyError(f"Key '{key}' not found in configuration") from e

class _Resources(BaseModel):
    memory_limit_gb: PositiveFloat = Field(default=6, description="RAM limit in GB")
    cpu_limit_percent: PositiveFloat = Field(default=80, description="CPU utilization limit percentage")
    timeout_seconds: PositiveFloat = Field(default=3600, description="Timeout in seconds")
    max_batch_size: PositiveInt = Field(default=100, description="Maximum number of files to process in one batch")
    max_threads: PositiveInt = Field(default_factory = lambda x: _get_cpu_cores(1), description="Maximum number of worker threads.")
    monitoring_interval_seconds: PositiveFloat = Field(default=1.0, description="Monitoring interval in seconds")
    force_mocks: bool = Field(default=False, description="Force use of mocks, even if libraries are available")

    @property
    def memory_limit_mb(self) -> float:
        """
        Get the memory limit in MB.
        
        Returns:
            Memory limit in MB.
        """
        return self.memory_limit_gb * 1024

class _Formats(BaseModel):
    text: list[str] = Field(default=["html", "xml", "plain", "calendar", "csv"])
    image: list[str] = Field(default=["jpeg", "png", "gif", "webp", "svg"])
    audio: list[str] = Field(default=["mp3", "wav", "ogg", "flac", "aac"])
    video: list[str] = Field(default=["mp4", "webm", "avi", "mkv", "mov"])
    application: list[str] = Field(default=["pdf", "json", "zip", "docx", "xlsx"])

class _Security(BaseModel):
    max_file_size_mb: PositiveFloat = Field(default=100, description="Maximum file size in MB")
    sandbox_enabled: bool = Field(default=True, description="Enable sandbox for file processing")
    allowed_formats: list[str] = Field(default=[], description="Empty list means all formats are allowed")
    sanitize_output: bool = Field(default=True, description="Sanitize output to remove potential security risks")

class _Processing(BaseModel):
    continue_on_error: bool = Field(default=True, description="Continue processing batch even if some files fail")
    extract_metadata: bool = Field(default=True, description="Extract metadata from files")
    normalize_text: bool = Field(default=True, description="Normalize extracted text")
    quality_threshold: PositiveFloat = Field(default=0.9, description="Minimum quality score for text extraction")
    # TODO Add custom validators for whisper and tesseract models
    transcription_model: str = Field(default="base", description="Model to use for audio transcription.")
    transcription_whisper_language: str = Field(default="en", description="Language for audio transcription model.")
    ocr_model: str = Field(default="eng", description="Model to use for OCR")
    llm_api_key: str = Field(default="", description="API key for external services, if required")
    suppress_errors: bool = Field(default=False, description="Suppress errors during processing")

class _Output(BaseModel):
    default_format: str = Field(default="txt", description="Default output format")
    include_metadata: bool = Field(default=True, description="Include metadata in output")
    preserve_structure: bool = Field(default=True, description="Attempt to preserve document structure")
    encoding: str = Field(default="utf-8", description="Output file encoding")
    verbose: bool = Field(default=False, description="Enable verbose output for debugging") # NOTE This should activate the logger's debug mode

class Configs(BaseModel):
    """
    Configurations for the Omni-Converter.
    Unlike options, these configurations are 
    
    Attributes:
        resources: Resource limits and settings.
            - memory_limit_gb: Memory limit in GB. Defaults to 6 GB.
            - memory_limit_mb: Memory limit in MB (calculated from memory_limit_gb).
            - cpu_limit_percent: CPU utilization limit percentage. Defaults to 80%.
            - timeout_seconds: Timeout in seconds. Defaults to 3600 seconds (1 hour).
            - max_batch_size: Maximum number of files to process in one batch. Defaults to 100.
            - max_threads: Maximum number of worker threads.
            - monitoring_interval_seconds: Monitoring interval in seconds.
            - force_mocks: Force use of mocks, even if libraries are available.
        formats: Supported file formats.
            - text: List of supported text formats.
            - image: List of supported image formats.
            - audio: List of supported audio formats.
            - video: List of supported video formats.
            - application: List of supported application formats.
        security: Security settings for file processing.
            - max_file_size_mb: Maximum file size in MB.
            - sandbox_enabled: Enable sandbox for file processing.
            - allowed_formats: List of allowed formats (empty means all formats are allowed).
            - sanitize_output: Sanitize output to remove potential security risks.
        processing: Processing options for files.
            - continue_on_error: Continue processing batch even if some files fail. Defaults to True.
            - extract_metadata: Extract metadata from files. Defaults to True.
            - normalize_text: Normalize extracted text. Defaults to True.
            - quality_threshold: Minimum quality score for text extraction. Defaults to 0.9.
            - whisper_model: Whisper model to use for audio processing. Defaults to "base".
            - whisper_language: Language for Whisper model. Defaults to "en".
            - tesseract_language: Tesseract model for OCR. Defaults to "eng".
        output: Output settings for processed files.
            - default_format: Default output format. Defaults to "txt".
            - include_metadata: Include metadata in output. Defaults to True.
            - preserve_structure: Attempt to preserve document structure. Defaults to True.
            - encoding: Output file encoding. Defaults to "utf-8".

    Properties:
        - version: str: The version of the Omni-Converter.
        - paths: Paths for important files and directories.

    Methods:
        get_config_value(key: str, default: Any) -> Any:
            Get a configuration value by key, using dot notation for nested keys.
        set_config_value(key: str, value: Any) -> None:
            Set a configuration value by key, using dot notation for nested keys.
    """
    resources: _Resources = Field(default_factory=_Resources)
    formats: _Formats = Field(default_factory=_Formats)
    security: _Security = Field(default_factory=_Security)
    processing: _Processing = Field(default_factory=_Processing)
    output: _Output = Field(default_factory=_Output)

    @property
    def paths(self) -> _PathsBaseModel:
        """
        Get the paths for important files and directories.
        
        Returns:
            _PathsBaseModel object containing important file and directory paths.
        """
        return _PathsBaseModel()
    
    @property
    def version(self) -> str:
        """
        Get the version of the Omni-Converter.
        
        Returns:
            The version of the Omni-Converter.
        """
        return __version__

    def get_config_value(self, key: str, default: Any) -> Any:
        """
        Get a configuration value by key.
        
        Args:
            key: The key to get the value for, using dot notation for nested keys.
            default: The default value to return if the key is not found.
            
        Returns:
            The configuration value, or the default if the key is not found.
        """
        keys = key.split('.')
        value = self
        try:
            for k in keys:
                value = getattr(value, k)
            return value.model_dump() if isinstance(value, BaseModel) else value
        except AttributeError as e:
            print(f"Key '{key}' not found in configuration: {e}")
            return default

    def set_config_value(self, key: str, value: Any) -> None:
        """
        Set a configuration value by key.
        
        Args:
            key: The key to set the value for, using dot notation for nested keys.
            value: The value to set.
            
        Raises:
            KeyError: If the key is not found in the configuration.
            ValueError: If the value is invalid for the specified key.
        """
        keys = key.split('.')
        config = self
        try:
            for k in keys[:-1]:
                config = getattr(config, k)
            setattr(config, keys[-1], value)
            config.model_validate()
        except AttributeError as e:
            raise KeyError(f"Key '{key}' not found in configuration") from e
        except ValidationError as e:
            raise ValueError(f"Invalid value for key '{key}': {value}") from e

_PATH = _PathsBaseModel()

try:
    with open(_PATH.CONFIG_PATH.resolve(), 'r') as file:
        config_dict = yaml.safe_load(file)
    configs = Configs().model_validate(config_dict)
    print(f"Configuration loaded from {_PATH.CONFIG_PATH}")
except (FileNotFoundError, yaml.YAMLError, ValidationError) as e:
    print(f"{name(e)}: {e}\nUsing default configuration.")
    configs = Configs()

# Function injections for dictionary-like access.
for cls in [Configs, _Resources, _Formats, _Security, _Processing, _Output]:
    cls.__getitem__ = getitem
    cls.__setitem__ = setitem
    cls.items = classmethod(lambda cls: cls.__dict__.items())
