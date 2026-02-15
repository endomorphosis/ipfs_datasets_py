"""
Python API for the Omni-Converter.

This module provides a programmatic interface to the Omni-Converter functionality,
allowing Python applications to convert files to text without using the command-line interface.
"""
from functools import cached_property
import os
from pathlib import Path

from types_ import (
    Any, Callable, Optional,
    Configs, Logger, BatchProcessor, BatchResult, ProcessingResult, ProcessingPipeline, ResourceMonitor
)

class PythonAPI:
    """
    Python API for the Omni-Converter.
    
    This class provides methods for programmatically using the Omni-Converter functionality,
    including single file conversion, batch processing, and configuration management.
    
    Attributes:
        configs: The configuration manager to use.
        batch_processor: The batch processor to use.
        resource_monitor: The resource monitor to use.
    """

    def __init__(
        self,
        resources: dict[str, Callable] = None,
        configs: Configs = None,
    ):
        """Initialize the Python API."""
        self.configs = configs
        self.resources = resources

        self._api_timeout = self.configs.api_timeout

        self._batch_processor:     BatchProcessor     = self.resources['batch_processor']
        self._supported_formats:   set[str]           = self.resources['supported_formats']
        self._processing_pipeline: ProcessingPipeline = self.resources['processing_pipeline']
        self._logger:              Logger             = self.resources['logger']

        self._make_resource_monitor: Callable = self.resources['make_resource_monitor']
        self._make_error_monitor:    Callable = self.resources['error_monitor']
        self._make_security_monitor: Callable = self.resources['security_monitor']

        # Initialize monitors
        self._resource_monitor: ResourceMonitor = self._make_resource_monitor()
        self._error_monitor:    Callable        = self._make_error_monitor()
        self._security_monitor: Callable        = self._make_security_monitor()

    def convert_file(
        self,
        file_path: str,
        output_dir: Optional[str] = None,
        format: str = "txt",
        include_metadata: bool = True,
        extract_metadata: bool = True,
        normalize_text: bool = True,
        quality_threshold: float = 0.9,
        continue_on_error: bool = True,
        max_batch_size: int = 100,
        parallel: bool = False,
        max_threads: int = 4,
        sanitize: bool = True,
        max_cpu: int = 80,
        max_memory: int = 6144,  # 6GB in MB
        show_progress: bool = False,  # TODO Unused argument. Implement.
        output_path: Optional[str] = None,
    ) -> ProcessingResult:
        """
        Convert a single file to text.
        
        Args:
            - file_path: The path to the file to convert.
            - output_path: Optional path to write the output to.
            - output_dir: Optional[str] - Directory to write output files to.
            - format: str - Output format for the converted text (default: "txt").
            - include_metadata: bool - Whether to include file metadata in the output (default: True).
            - extract_metadata: bool - Whether to extract metadata from the data in the input files (default: True).
            - normalize_text: bool - Whether to normalize text (e.g., remove extra whitespace, convert to lowercase, etc.) (default: True).
            - quality_threshold: float - Arbitrary threshold for quality filtering (default: 0.9).
            - continue_on_error: bool - Whether to continue processing files even if some fail (default: True).
            - max_batch_size: int - Maximum number of files to process in a single batch (default: 100).
            - parallel: bool - Whether to process files in parallel (default: False).
            - max_threads: int - Maximum number of worker threads to use for parallel processing (default: 4).
            - sanitize: bool - Whether to sanitize output files (e.g. remove executable code, etc.) (default: True).
            - max_cpu: int - Maximum CPU usage percentage allowed (default: 80).
            - max_memory: int - Maximum memory usage in MB (default: 6144 i.e. 6GB).
            - show_progress: bool - Whether to show a progress bar (default: False, TODO: Unused argument. Implement).
        Returns:
            A ProcessingResult object with the result of the conversion.
            
        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is not valid for conversion.
        """
        # Validate file existence
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not os.path.isfile(file_path):
            raise ValueError(f"Not a file: {file_path}")
        
        # Prepare options from config if none provided
        if options is None:
            options = self._get_default_options()
        
        # Process the file using the processing pipeline
        result = self._processing_pipeline.process_file(file_path, output_path, options)
        
        return result
    
    def convert_batch(
        self,
        file_paths: list[str] | str,
        output_dir: Optional[str] = None,
        format: str = "txt",
        include_metadata: bool = True,
        extract_metadata: bool = True,
        normalize_text: bool = True,
        quality_threshold: float = 0.9,
        continue_on_error: bool = True,
        max_batch_size: int = 100,
        parallel: bool = False,
        max_threads: int = 4,
        sanitize: bool = True,
        max_cpu: int = 80,
        max_memory: int = 6144,  # 6GB in MB
        show_progress: bool = False  # TODO Unused argument. Implement.
    ) -> BatchResult:
        """
        Convert multiple files to text.
        
        Args:
            file_paths: list of file paths to convert, or a directory to recursively process.
            output_dir: Directory to write output files to. 
                If None, text is still extracted but not written to files.
            options: Conversion options. If None, default options are used.
            show_progress: Whether to show a progress bar (if in interactive environment). # TODO Implement.
            
        Returns:
            A BatchResult object with the results of the batch conversion.
        """
        # Prepare options from config if none provided
        if options is None:
            options = self._get_default_options()
        
        # Configure batch processor from options
        if "max_batch_size" in options:
            self._batch_processor.set_max_batch_size(options["max_batch_size"])
        
        if "continue_on_error" in options:
            self._batch_processor.set_continue_on_error(options["continue_on_error"])
        
        if "max_threads" in options and "parallel" in options and options["parallel"]:
            self._batch_processor.set_max_threads(options["max_threads"])
        else:
            self._batch_processor.set_max_threads(1)  # Sequential mode
        
        # Configure resource limits if specified
        if ("max_cpu" in options and options["max_cpu"] is not None) or \
           ("max_memory" in options and options["max_memory"] is not None):
            # Get memory limit in MB, ensure it's properly converted from GB if needed
            memory_limit = options.get("max_memory")
            if memory_limit is not None:
                # Verify it's a reasonable value (between 1024MB and 32GB) # TODO Magic numbers need to be checked and replaced with constants.
                if memory_limit < 1024:  # Less than 1GB, might be in GB units # TODO Check if this is correct.
                    memory_limit *= 1024  # Convert to MB
                
                # Cap at a reasonable maximum to prevent excessive values
                max_reasonable_memory = 32 * 1024  # 32GB # TODO Magic number needs to be checked and replaced with constants.
                if memory_limit > max_reasonable_memory:
                    self._logger.warning(f"Memory limit of {memory_limit}MB exceeds maximum reasonable value. "
                                  f"Capping at {max_reasonable_memory}MB")
                    memory_limit = max_reasonable_memory
            
            self._resource_monitor.set_resource_limits(
                cpu_limit_percent=options.get("max_cpu"),
                memory_limit=memory_limit
            )
        
        # Process the batch
        batch_result = self._batch_processor.process_batch(
            file_paths=file_paths,
            output_dir=output_dir,
            options=options,
            progress_callback=None  # Progress callback is not used by the API
        )
        
        return batch_result

    @cached_property
    def supported_formats(self) -> dict[str, list[str]]:
        """
        Get all supported formats, organized by category.
        
        Returns:
            A dictionary mapping format categories to lists of supported formats.
        """
        return self._supported_formats

    def set_config(self, config_dict: dict[str, Any]) -> bool:
        """
        Set multiple configuration values at once.
        
        Args:
            config_dict: A dictionary of configuration values to set.
                Keys can use dot notation for nested settings.
                
        Returns:
            True if the configuration was successfully set, False otherwise.
        """
        if not isinstance(config_dict, dict):
            raise TypeError("config_dict must be a dictionary")
        try:
            for key, value in config_dict.items():
                self.configs.set_config_value(key, value)
            return True
        except Exception:
            return False
    
    def get_config(self) -> dict[str, Any]:
        """
        Get the current configuration.
        
        Returns:
            The current configuration as a dictionary.
        """
        return self.configs.current_config
    
    def _get_default_options(self) -> dict[str, Any]:
        """
        Get default options from configuration.
        
        Returns:
            Default options as a dictionary.
        """
        options = { # TODO All these options should be set in the config file.
            # Output options
            "format": self.configs.get_config_value("output.default_format", "txt"),
            "include_metadata": self.configs.get_config_value("output.include_metadata", True),
            
            # Processing options
            "extract_metadata": self.configs.get_config_value("processing.extract_metadata", True),
            "normalize_text": self.configs.get_config_value("processing.normalize_text", True),
            "quality_threshold": self.configs.get_config_value("processing.quality_threshold", 0.9),
            
            # Batch processing options
            "continue_on_error": self.configs.get_config_value("processing.continue_on_error", True),
            "max_batch_size": self.configs.get_config_value("resources.max_batch_size", 100),
            "parallel": self.configs.get_config_value("resources.parallel", False),
            "max_threads": self.configs.get_config_value("resources.max_threads", 4),
            
            # Security options
            "sanitize": self.configs.get_config_value("security.sanitize_output", True),
            
            # Resource options
            "max_cpu": self.configs.get_config_value("resources.cpu_limit_percent", 80),
            "max_memory": self.configs.get_config_value("resources.memory_limit_gb", 6) * 1024  # Convert to MB
        }
        
        return options



