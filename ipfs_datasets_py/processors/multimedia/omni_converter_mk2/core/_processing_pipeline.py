"""
Processing pipeline module for the Omni-Converter.

This module provides the ProcessingPipeline class for orchestrating the conversion
of files to plaintext.
"""
from __future__ import annotations


from ._pipeline_status import PipelineStatus
from ._processing_result import ProcessingResult
from types_ import (
    Any,
    Callable,
    Configs,
    ContentExtractor,
    ContentSanitizer,
    FileFormatDetector,
    FileValidator,
    Logger,
    ModuleType,
    Optional,
    OutputFormatter,
    SecurityMonitor,
    StatusListenerFunc,
    TextNormalizer,
)


class ProcessingPipeline:
    """
    Processing pipeline for the Omni-Converter.
    
    This class orchestrates the conversion of files to plaintext, using various
    components like the format detector, validator, content extractor, text normalizer,
    and output formatter.

    Attributes:
        configs: A pydantic model containing configuration settings.
        resources: A dictionary of callable classes and functions for the class to use.

    Private Attributes:
        _format_detector: An instance of FileFormatDetector for detecting file formats.
        _file_validator: An instance of FileValidator for validating files.
        _content_extractor: An instance of ContentExtractor for extracting content from files.
        _text_normalizer: An instance of TextNormalizer for normalizing extracted text.
        _output_formatter: An instance of OutputFormatter for formatting the output.
        _processing_result: An instance of ProcessingResult for storing processing results.
        _logger: An instance of Logger for logging messages.
        _status: An instance of PipelineStatus for tracking the processing status.
        _hashlib: The hashlib module for generating content hashes.
        _listeners: A list of status listener functions to notify about processing events.
    """
    def __init__(
        self,
        resources: dict[str, Callable] = None,
        configs: Configs = None,
    ) -> None:
        """
        Initialize a processing pipeline.
        
        Args:
            configs: A pydantic model containing configuration settings.
            resources: A dictionary of callable classes and functions for the class to use.
        """
        self.configs = configs
        self.resources = resources

        self._format_detector:   'FileFormatDetector' = self.resources['file_format_detector']
        self._file_validator:    'FileValidator'      = self.resources['file_validator']
        self._content_extractor: 'ContentExtractor'   = self.resources['content_extractor']
        self._text_normalizer:   'TextNormalizer'     = self.resources['text_normalizer']
        self._output_formatter:  'OutputFormatter'    = self.resources['output_formatter']
        self._content_sanitizer: 'ContentSanitizer'   = self.resources['content_sanitizer']
        self._security_monitor:  'SecurityMonitor'    = self.resources['security_monitor']

        self._processing_result: ProcessingResult = self.resources['processing_result']
        self._logger:            Logger           = self.resources['logger']
        self._status:            PipelineStatus   = self.resources['pipeline_status']
        self._hashlib:           ModuleType       = self.resources['hashlib']

        self._listeners:         list[StatusListenerFunc] = []

    def process_file(
        self,
        file_path: str,
        *,
        output_format: str = 'txt',
        output_path: Optional[str] = None,
        normalizers: Optional[list[str]] = None,
    ) -> ProcessingResult:
        """
        Process a single file.

        Args:
            file_path: The path to the file to process.
            output_format: The format to convert the file to. Supported formats are: 'txt', 'md'. Defaults to 'txt'.
            output_path: The path to write the output to.
            - If it's a file path, the output will be written to that file.
            - If it's a directory, the output will be written to a file in that directory. 
                The name will be the same as the input file's. 
                Any extension will be removed and replaced with the one specified in output_format.
            - If None, the text is still extracted but written to a file in the temp directory.
                The name will be the same as the input file's, with the extension replaced by the one specified in output_format.
                If a file already exists at that path, the first 4 characters of the content_hash will be appended to the filename to avoid overwriting.
            normalizers: A list of normalizers to apply to the text post-extraction.
            - If None, extracted text will return as-is.

        Returns:
            ProcessingResult: A dataclass detailing the result of processing the file.
            The dataclass contains the following fields:
                - success (bool): Whether the processing was successful.
                - file_path (str): The path to the input file.
                - output_path (str): The path to the output file.
                - format (str): The detected format of the input file.
                - errors (list[str]): list of errors encountered during processing.
                - metadata (dict[str, Any]): Metadata about the processing.
                - content_hash (str): Hash of the content for verification.
                - timestamp (datetime): Time when the processing was completed.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file cannot be read.
            ValueError: If the file format is not supported.
        """
        # Initialize options
        options = {
            'output_format': output_format,
            'output_path': output_path,
            'normalizers': normalizers,
        }

        # Update status
        self._status.is_processing = True
        self._status.current_file = file_path
        self._status.total_files += 1
        self._notify_listeners("processing_started", {'file_path': file_path})
        errors: list[str] = []

        try:
            # Detect format
            self._logger.debug(f"Detecting format for '{file_path}'")
            format_name, category = self._format_detector.detect_format(file_path)
            if not format_name:
                errors.append(f"Unable to detect format for '{file_path}'")
            if category is None:
                errors.append(f"Format '{format_name}' is not in any supported category for file: {file_path}")

            self._logger.info(f"Detected format: {format_name} ({category})", {'file_path': file_path})

            # Validate file
            # NOTE This is NOT a security check. It's meant to ensure the file doesn't immediately crash the pipeline
            # Or cause the program to halt.
            self._logger.debug(f"Validating file '{file_path}'")
            validation_result = self._file_validator.validate_file(file_path, format_name)
            if not validation_result.is_valid:
                errors.extend(validation_result.errors)
                return self._make_failure_result(
                    file_path=file_path,
                    output_path=output_path,
                    format_name=format_name,
                    errors=errors
                )

            # Perform security validation
            security_result = self._security_monitor.validate_security(file_path)
            if not security_result.is_safe:
                # Handle security issues
                error_message = f"Security validation failed: {', '.join(security_result.issues)}"
                self._logger.warning(error_message, {'file_path': file_path})
                return self._make_failure_result(
                    file_path=file_path,
                    output_path=output_path,
                    format_name=format_name if 'format_name' in locals() else None,
                    errors=errors
                )

            # Extract content
            self._logger.debug(f"File is valid. Extracting content from '{file_path}' with format '{format_name}'")
            content = self._content_extractor.extract_content(file_path, format_name, options)

            # Normalize text in content
            # TODO This needs to be skipped if it's a storage/archive format.
            self._logger.debug(f"Normalizing text from '{file_path}'")
            normalized_content = self._text_normalizer.normalize_text(content, normalizers)

            # Sanitize content (after it's been converted to text).
            sanitized_content = self._content_sanitizer.sanitize(normalized_content.content)

            # Format output
            self._logger.debug(f"Formatting output for '{file_path}'")
            try:
                formatted_output = self._output_formatter.format_output(
                    sanitized_content.content,
                    output_format,
                    options,
                    output_path
                )
            except Exception as e:
                if self._logger.level == 10: # If debug level is set
                    self._logger.exception(f"Error formatting output for '{file_path}': {e}")
                else:
                    self._logger.warning(f"Format error: {e}, falling back to txt format")
                formatted_output = self._output_formatter.format_output(
                    normalized_content.content,
                    'txt',
                    options,
                    output_path
                )

            # Calculate content hash for verification # TODO Change to IPFS CID
            content_hash = self._hashlib.md5(formatted_output.content.encode('utf-8')).hexdigest()

            # Write output to file if output_path is provided
            if output_path:
                self._logger.debug(f"Writing output to {output_path}")
            else:
                # Get rid of the extension and replace it with the output format
                output_path = f"{file_path.rsplit('.', 1)[0]}_{content_hash[:3]}.{output_format}"
                formatted_output.write_to_file(output_path)

            # Create success result
            result = self._processing_result(
                success=True,
                file_path=file_path,
                output_path=output_path,
                format=format_name,
                metadata={
                    'category': category,
                    'normalized_by': normalized_content.normalized_by,
                    'output_format': output_format,
                    'content_size': len(formatted_output.content)
                },
                content_hash=content_hash
            )
            self._status.successful_files += 1
            self._notify_listeners("processing_succeeded", {
                'file_path': file_path,
                'output_path': output_path,
                'format': format_name
            })
            self._logger.debug(f"result: {result.to_dict()}")

            return result

        except Exception as e:
            self._logger.exception(f"Error processing '{file_path}': {e}")
            errors.append(str(e))
            return self._make_failure_result(
                file_path=file_path,
                output_path=output_path,
                format_name=format_name if 'format_name' in locals() else None,
                errors=errors
            )
        finally:
            # Reset status
            self._status.reset()
            self._notify_listeners("processing_completed", {'file_path': file_path})


    def _make_failure_result(self, 
                               file_path: str, 
                               output_path: str, 
                               format_name: str, 
                               errors: list[Any]
                               ) -> ProcessingResult:
            str_errors = [str(e) for e in errors if isinstance(e, Exception)]

            self._logger.error(f"Processing failed: {','.join(str_errors)}", {'file_path': file_path})
            result = self._processing_result(
                success=False,
                file_path=file_path,
                output_path=output_path,
                format=format_name,
                errors=errors
            )
            self._status.failed_files += 1
            self._notify_listeners("processing_failed", {
                'file_path': file_path,
                'error': ','.join(str_errors)
            })
            return result

    @property
    def status(self) -> dict[str, Any]:
        """
        Get the current status of the pipeline.
        
        Returns:
            The current pipeline status as a dictionary.
        """
        return self._status.to_dict()
    
    def register_listener(self, listener: StatusListenerFunc) -> None:
        """
        Register a status listener.
        
        Args:
            listener: The listener function to register.
        """
        if listener not in self._listeners:
            self._listeners.append(listener)

    def _notify_listeners(self, event: str, data: dict[str, Any]) -> None:
        """
        Notify all registered listeners of an event.
        
        Args:
            event: The event type.
            data: The event data.
        """
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception as e:
                self._logger.exception(f"Error in listener: {e}")
