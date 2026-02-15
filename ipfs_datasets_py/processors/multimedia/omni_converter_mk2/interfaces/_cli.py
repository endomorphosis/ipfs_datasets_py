# -*- coding: utf-8 -*-
"""
Omni-Converter: Convert various file formats to plaintext.

This is the main entry point for the Omni-Converter application.
"""
from __future__ import annotations
import argparse
import glob
import os
import sys
import threading


from types_ import (
    Any, Callable, Optional,
    BaseModel,
    BatchProcessor,
    BatchResult,
    Dependency,
    ResourceMonitor,
    Logger,
    ProcessingPipeline,
    ProgressCallback,
    ProcessingResult,
    ErrorMonitor,
    SecurityMonitor,
    #Options,
)
from configs import Configs
from .options import Options

class CLI:
    """
    Command Line Interface for the Omni-Converter.

    Attributes:
        resources (dict[str, Callable]): Dictionary of callable functions and classes.
        configs (Configs): A pydantic mode of settings to use across the program.

    Private Attributes:
        _batch_processor (BatchProcessor): Handles batch processing of files.
        _progress_callback (ProgressCallback): Callback for progress updates.
        _processing_pipeline (ProcessingPipeline): Pipeline for processing files.
        _list_normalizers (Callable): Function to list available text normalizers.
        _list_output_formats (Callable): Function to list available output formats.
        _list_supported_formats (Callable): Function to list supported input formats.
        _show_version (Callable): Function to display version information.
        _logger (Logger): Logger instance for logging messages.
        _tqdm (Dependency): Dependency for progress bar functionality.
        _resource_monitor (ResourceMonitor): Monitors system resources during processing.
        _error_monitor (ErrorMonitor): Monitors errors during processing.
        _security_monitor (SecurityMonitor): Monitors security issues during processing.

    Methods:
        make_parser_from_options_basemodel() -> argparse.Namespace:
            Parses command line arguments and returns them as a Namespace object.
        process_file(input_path: str, output_path: Optional[str] = None,
                     output_dir: Optional[str] = None, format: str = "txt",
                     include_metadata: bool = True, extract_metadata: bool = True,
                     normalize_text: bool = True, quality_threshold: float = 0.9,
                     continue_on_error: bool = True, max_batch_size: int = 100,
                     parallel: bool = False, max_threads: int = 4,
                     sanitize: bool = True, max_cpu: int = 80,
                     max_memory: int = 6144, show_progress: bool = False,
                     options: Optional[dict[str, Any]] = None) -> bool:
            Processes a single file and converts it to the specified format.
            Returns True if successful, False otherwise.
        process_directory(dir_path: str, output_dir: Optional[str] = None,
                          options: Optional[dict[str, Any]] = None,
                          show_progress: bool = True, recursive: bool = False) -> BatchResult:
            Processes all files in a directory and returns a BatchResult object with processing results.
        main() -> int:
            Main entry point for the CLI. Parses arguments and processes input files or directories.
            Returns an exit code: 0 for success, 1 for failure.
    """

    def __init__(
        self,
        resources: dict[str, Callable] = None,
        configs: Configs = None,
    ):
        """
        Initialize the argparse CLI.
        
        Args:
            resources: Dictionary of resource providers for interfaces
            configs: Configuration settings to use across interfaces.
                If None, default configs will be used.
        """
        self.configs = configs
        self.resources = resources

        # Batch processing components
        self._batch_processor:     BatchProcessor     = self.resources['batch_processor']
        self._progress_callback:   ProgressCallback   = self.resources['progress_callback']
        self._processing_pipeline: ProcessingPipeline = self.resources['processing_pipeline']
        self._options:             Options            = self.resources['options']

        # Information and listing functions
        self._list_normalizers:       Callable = self.resources['list_normalizers']
        self._list_output_formats:    Callable = self.resources['list_output_formats']
        self._list_supported_formats: Callable = self.resources['list_supported_formats']
        self._show_version:           Callable = self.resources['show_version']

        # System and utility components
        self._logger:                      Logger = self.resources['logger']
        self._tqdm:                        Dependency = self.resources['tqdm']

        # Initialize monitors
        self._resource_monitor: ResourceMonitor = self.resources['resource_monitor']
        self._error_monitor:    ErrorMonitor    = self.resources['error_monitor']
        self._security_monitor: SecurityMonitor = self.resources['security_monitor']


    def make_parser_from_options_basemodel(self) -> argparse.Namespace:
        """Parse command line arguments.

        Returns:
            argparse.Namespace: The parsed arguments.
        """
        default_options = self._options.print_options(type_='argparse')

        description = f"""
        Parse command line arguments for the file conversion utility.
        This function sets up the argument parser with various options for controlling
        the input sources, output format, processing behavior, and resource utilization.
        {default_options}
        """
        parser = argparse.ArgumentParser(description=description)
        parser = self._options.add_arguments_to_parser(parser)
        return parser.parse_args()


    def process_file(self, 
                     input_path: str, 
                     output_path: Optional[str] = None, 
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
                    options: Optional[BaseModel | dict[str, Any]] = None
                    ) -> bool:
        """
        Process a single file.
        
        Args:
            input_path: The path to the input file.
            options: A pydantic model of optional processing options. If None, default options are used.
            Currently supported options:


            output_path: The path to the output file. If None, print to stdout.
            output_dir: The directory to write output files to. If None, prints content to stdout.
            format: The output format (e.g., "txt", "json", "md"). Default is "txt".
            include_metadata: Whether to include metadata in the output. Default is True.
            extract_metadata: Whether to extract metadata from the input file. Default is True.
            normalize_text: Whether to normalize the text during processing. Default is True.
            quality_threshold: The quality threshold for processing (0.0 to 1.0). Default is 0.9.
            continue_on_error: Whether to continue processing if an error occurs. Default is True.
            max_batch_size: The maximum number of files to process in a batch. Default is 100.
            parallel: Whether to enable parallel processing. Default is False.
            max_threads: The maximum number of worker threads for parallel processing. Default is 4.
            sanitize: Whether to sanitize the content during processing. Default is True.
            max_cpu: The maximum CPU usage percentage (0-100). Default is 80.
            max_memory: The maximum memory usage in MB. Default is 6144 (6GB).
            show_progress: Whether to show a progress bar during processing. Default is False.
            options: Additional processing options. If None, default options are used.

        Returns:
            True if successful, False otherwise.
        """
        # Get defaults options if not provided
        options = self._options(input=input_path) if options is None else options

        try:
            # Get output format from args, config, or default to txt
            output_format = output_path.split('.')[-1] if output_path and '.' in output_path else None
            if not output_format:
                output_format = self.configs.get_config_value('output.default_format', 'txt')

            # Set default options if not provided
            if 'format' not in options.keys():
                options['format'] = output_format
            if 'verbose' not in options.keys():
                options['verbose'] = self.configs.get_config_value('output.verbose', False)

            # Process the file using the processing pipeline
            result = None
            try:
                result = self._processing_pipeline.process_file(
                    input_path, 
                    output_path=output_path,
                    output_format=output_format, 
                    normalizers=['whitespace', 'line_endings', 'empty_lines', 'unicode'] # TODO Un-hardcode this.
                    )
            except Exception as e:
                self._logger.exception(f"Error processing {input_path}: {e}")
                print(f"Error processing {input_path}: {e}", file=sys.stderr)
                return False

            # Handle the processing result
            if result.success:
                if output_path:
                    print(f"Converted {input_path} to {output_path}")
                else:
                    # If no output path was provided, print the content to stdout
                    print(f"=== Raw Content from {input_path} ({result.format}) ===")
                    try:
                        with open(input_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            print(content)
                    except Exception as e:
                        self._logger.error(f"Error reading {input_path}: {e}")
                        print(f"Error reading {input_path}: {e}", file=sys.stderr)
                        return False

                    print("=== End of content ===")

                # Log processing metadata if verbose
                if options.get('verbose'):
                    print("Processing metadata:")
                    for key, value in result.metadata.items():
                        print(f"  {key}: {value}")
                
                return True
            else:
                self._logger.error(f"Error processing {input_path}", {'errors': result.errors})
                print(f"Error processing {input_path}:", file=sys.stderr)
                for error in result.errors:
                    print(f"  - {error}", file=sys.stderr)
                
                return True

        except Exception as e:
            self._logger.exception(f"Error processing {input_path}: {e}")
            print(f"Error processing {input_path}: {e}", file=sys.stderr)
            return True

    def process_directory(
        self,
        dir_path: str, 
        output_dir: Optional[str] = None, 
        options: Optional[BaseModel | dict[str, Any]] = None,
        show_progress: bool = True,
        recursive: bool = False
    ) -> 'BatchResult':
        """
        Process all files in a directory.
        
        Args:
            dir_path: The path to the directory to process.
            output_dir: The directory to write output files to. If None, prints content to stdout.
            options: Processing options. If None, default options are used.
            show_progress: Whether to show a progress bar.
            recursive: Whether to process directories recursively.
            
        Returns:
            BatchResult object with processing results.
        """
        # Get defaults options if not provided
        options = self._options(input=dir_path) if options is None else options

        # Configure batch processor
        self._batch_processor.set_max_batch_size(options.get('max_batch_size', 100))
        self._batch_processor.set_continue_on_error(options.get('continue_on_error', True))
        self._batch_processor.set_max_threads(options.get('max_threads', 4) if options.get('parallel', False) else 1)
        
        # Create progress callback
        pbar = None
        callback = None
        
        if show_progress:
            def _callback(current, total, current_file):
                self._progress_callback(current, total, current_file, pbar)
            callback = _callback
        
        # Process batch
        try:
            # Start processing
            self._logger.info(f"Processing directory: {dir_path}")
            
            # Setup progress bar if requested
            estimated_file_count = sum(1 for _ in os.walk(dir_path) for _ in os.listdir(_[0])) if recursive else len(os.listdir(dir_path))
            if show_progress and estimated_file_count > 0:
                pbar = self._tqdm.tqdm(total=estimated_file_count, unit="file")
            
            # Process files
            result = self._batch_processor.process_batch(
                file_paths=dir_path, 
                output_dir=output_dir,
                **options,
                progress_callback=callback
            )
            
            return result
        
        finally:
            # Clean up progress bar
            if pbar is not None:
                pbar.close()

    def main(self) -> int:
        """
        Main entry point.
        
        Returns:
            Exit code. 0 for success, 1 for failure.
        """
        # Parse arguments
        _args: argparse.Namespace = self.make_parser_from_options_basemodel()

        # Validate arguments.
        try:
            args: Options = Options(**vars(_args))  # Convert Namespace to Options instance
        except Exception as e:
            print(f"Error parsing arguments: {e}", file=sys.stderr)
            return 1

        # Set verbose logging if requested
        if args.verbose:
            self._logger.level = 10 # DEBUG

        # Show information if requested
        if args.version:
            self._show_version()
            return 0

        if args.show_options:
            self._options.print_options(type_='defaults')
            return 0

        if args.list_formats:
            self._list_supported_formats()
            return 0

        if args.list_normalizers:
            self._list_normalizers()
            return 0

        if args.list_output_formats:
            self._list_output_formats()
            return 0

        # Check for input file or directory
        if not args.input:
            print("Error: No input file or directory specified", file=sys.stderr)
            return 1

        # Set configuration based on command-line arguments
        if args.format:
            self.configs.set_config_value('output.default_format', args.format)

        if args.verbose:
            self.configs.set_config_value('output.verbose', True)

        # Configure resource limits if specified
        if args.max_cpu is not None:
            self._resource_monitor.set_max_cpu_percent(args.max_cpu)
        if args.max_memory is not None:
            self._resource_monitor.set_max_memory_mb(args.max_memory)

        # Prepare processing options
        options = {
            'format': args.format,
            'verbose': args.verbose,
            'sanitize': args.sanitize,
            'max_batch_size': args.max_batch_size,
            'continue_on_error': args.continue_on_error,
            'max_threads': args.max_threads,
            'parallel': args.parallel,
            'security_checks': args.security_checks,
        }
        
        # Handle normalizers
        if args.no_normalize:
            options['normalizers'] = []
        elif args.normalizers:
            options['normalizers'] = args.normalizers.split(',')
        
        # Store options in config for other components to access
        for key, value in options.items():
            self.configs.set_config_value(f'processing.{key}', value)
        
        # Process input based on type
        if os.path.isfile(args.input):
            # Process a single file
            output_path = args.output
            
            # Process the file
            success = self.process_file(args.input, output_path, options)
            
            if not success:
                # Try a test run with different format if original failed
                self._logger.debug("Attempting to process with default format")
                try_options = options.copy()
                try_options['format'] = 'txt'  # Use plain text as fallback
                success = self.process_file(args.input, None, try_options)  # Output to stdout
            
            return 0 if success else 1
        
        elif os.path.isdir(args.input):
            # Process a directory
            self._logger.info(f"Processing directory: {args.input}")
            
            # Validate output directory
            output_dir = args.output
            if output_dir and not os.path.isdir(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    self._logger.info(f"Created output directory: {output_dir}")
                except Exception as e:
                    self._logger.error(f"Failed to create output directory: {e}")
                    print(f"Error: Failed to create output directory {output_dir}: {e}", 
                        file=sys.stderr)
                    return 1
            
            # Process the directory
            result = self.process_directory(
                dir_path=args.input,
                output_dir=output_dir,
                **options,
                show_progress=not args.no_progress,
                recursive=args.recursive
            )
            
            # Print summary
            print("\nBatch Processing Summary:")
            print(f"Total files: {result.total_files}")
            print(f"Successful: {result.successful_files}")
            print(f"Failed: {result.failed_files}")
            print(f"Success rate: {(result.successful_files / result.total_files * 100) if result.total_files > 0 else 0:.1f}%")
            print(f"Processing time: {result.processing_time_seconds:.2f} seconds")
            
            # Print average processing time per file if available
            if result.total_files > 0:
                avg_time = result.processing_time_seconds / result.total_files
                print(f"Average processing time per file: {avg_time:.3f} seconds")
            
            # Print resource usage if verbose
            if args.verbose:
                usage = self._resource_monitor.current_resource_usage
                print("\nResource Usage:")
                print(f"CPU: {usage.get('cpu_percent', 'N/A')}%")
                print(f"Memory: {usage.get('memory_mb', 'N/A')} MB")
            
            # Return success if at least one file was processed successfully
            return 0 if result.successful_files > 0 else 1
        
        else:
            # Handle glob patterns and wildcards
            matches = glob.glob(args.input, recursive=args.recursive)
            if matches:
                if len(matches) == 1 and os.path.isfile(matches[0]):
                    # Process as a single file
                    return self.process_file(matches[0], args.output, options)
                else:
                    # Process as a batch
                    self._logger.info(f"Processing {len(matches)} files matching pattern: {args.input}")
                    
                    # Process using batch processor
                    result = self._batch_processor.process_batch(
                        file_paths=matches,
                        output_dir=args.output,
                        options=options,
                        progress_callback=None if args.no_progress else lambda c, t, f: self._progress_callback(c, t, f)
                    )
                    
                    # Print summary
                    print("\nBatch Processing Summary:")
                    print(f"Total files: {result.total_files}")
                    print(f"Successful: {result.successful_files}")
                    print(f"Failed: {result.failed_files}")
                    
                    return 0 if result.successful_files > 0 else 1
            else:
                print(f"Error: {args.input} does not exist", file=sys.stderr)
                return 1
