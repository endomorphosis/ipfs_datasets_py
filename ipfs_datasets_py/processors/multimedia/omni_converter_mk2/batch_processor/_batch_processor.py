"""
Batch processor module for the Omni-Converter.

This module provides the BatchProcessor class for processing multiple files in batches.
"""
from __future__ import annotations
from enum import StrEnum


from types_ import (
    Any,
    BatchResult,
    Callable,
    Configs,
    ErrorMonitor,
    Logger,
    Optional,
    ProcessingPipeline,
    ProcessingResult,
    RLock,
    ResourceMonitor,
    SecurityMonitor
)



class Counter(object):
    def __init__(self, manager, init_val: int = 0) -> None:
        self.val = manager.Value('i', init_val)
        self.lock = manager.Lock()

    def increment(self):
        with self.lock:
            self.val.value += 1

    def value(self):
        with self.lock:
            return self.val.value


class _BatchState(StrEnum):
    """
    Enum for batch processing states.
    
    Attributes:
        IDLE: No processing is currently happening.
        PROCESSING: Files are being processed.
        CANCELLING: Processing is being cancelled.
        COMPLETED: Processing has completed.
    """
    IDLE = 'idle'
    PROCESSING = 'processing'
    CANCELLING = 'cancelling'
    COMPLETED = 'completed'

class BatchProcessor:
    """
    Batch processor for the Omni-Converter.
    
    This class orchestrates the processing of multiple files in batches, handling
    resource management, error handling, and security validation.
    
    Attributes:
        pipeline: The processing pipeline to use.
        error_monitor: The error handler to use.
        resource_monitor: The resource monitor to use.
        security_monitor: The security manager to use.
        max_batch_size (int): Maximum number of files to process in a single batch.
        continue_on_error (bool): Whether to continue processing if errors occur.
        max_threads (int): Maximum number of worker threads for parallel processing.
        cancellation_requested (bool): Whether processing cancellation has been requested.
    """
    
    def __init__(
        self,
        configs: Configs = None,
        resources: dict[str, Callable] = None,
    ):
        """
        Initialize a batch processor.
        
        Args:
            configs: Configuration object containing processing settings.
            resources: Dictionary of resource objects and functions.
        """
        self.configs = configs
        self.resources = resources

        self.max_batch_size: int = self.configs.resources.max_batch_size
        self.max_threads: int = self.configs.resources.max_threads
        self.continue_on_error: bool = self.configs.processing.continue_on_error

        self._pipeline: ProcessingPipeline = self.resources['processing_pipeline']
        self._error_monitor: ErrorMonitor = self.resources['error_monitor']
        self._resource_monitor: ResourceMonitor = self.resources['resource_monitor']
        self._security_monitor: SecurityMonitor = self.resources['security_monitor']
        self._logger: Logger = self.resources['logger']
        self._processing_result: ProcessingResult = self.resources['processing_result']
        self._batch_result: BatchResult = self.resources['batch_result']

        self._get_output_path : Callable = self.resources['get_output_path']
        self._resolve_paths: Callable = self.resources['resolve_paths']

        # Builtins.
        # Because screw having a million patches for testing.
        self._exists: Callable = self.resources['os_path_exists']
        self._makedirs: Callable = self.resources['os_makedirs']
        self._time: Callable = self.resources['time_time']
        self._collect: Callable = self.resources['gc_collect']
        self._as_completed: Callable = self.resources['concurrent_futures_as_completed']
        self._ThreadPoolExecutor: Callable = self.resources['concurrent_futures_ThreadPoolExecutor']
        self._ProcessPoolExecutor: Callable = self.resources['concurrent_futures_ProcessPoolExecutor']

        self.cancellation_requested = False
        self._lock: RLock = self.resources['threading_RLock']()  # For thread safety

        # State tracking attributes
        self._current_batch_size: int = 0
        self._files_completed: int = 0
        self._files_remaining: int = 0
        self._active_threads:int = 0
        self._current_batch_start_time: float = 0
        self._progress_percent: float = 0.0
        self._last_batch_summary: dict[str, Any] = {}

        self._current_batch_processing_state: StrEnum = _BatchState.IDLE # 'idle', 'processing', 'cancelling', 'completed'

        # Create an running batch state for the processor.
        self._running_batch_results: BatchResult = self._batch_result(start_time=self._time())

    @staticmethod
    def _assert_positive_int(var: Any, name: str) -> None:
        if not isinstance(var, int):
            raise TypeError(f"{name} must be an int, got '{type(var).__name__}'")
        if var < 1:
            raise ValueError(f"{name} must be at least 1, got '{var}'")

    @property
    def eta(self) -> Optional[float]:
        """Calculate estimated time remaining for current batch."""
        if self._current_batch_processing_state != 'processing' or self._files_completed == 0:
            return None

        elapsed_time = self._time() - self._current_batch_start_time
        files_per_second = self._files_completed / elapsed_time
        
        if files_per_second > 0:
            return self._files_remaining / files_per_second
        return None

    @property
    def ongoing_batch_result(self):
        return self._running_batch_results

    def _safe_progress_callback(
        self, 
        progress_callback: Optional[Callable], 
        current: int, 
        total: int, 
        filename: str
    ) -> None:
        """Safely call progress callback with exception handling."""
        if progress_callback is not None:
            try:
                progress_callback(current, total, filename)
                print("DEBUG: Progress callback called with current:", current,)
            except Exception as e:
                error_message = f"Progress callback failed: {e}"
                self._logger.warning(error_message)
                print("DEBUG: Progress callback failed:", error_message)
                self._error_monitor.handle_error(error_message, {
                    'current': current,
                    'total': total, 
                    'filename': filename
                })

    def _safe_resource_check(self) -> tuple[bool, str]:
        """Safely check resource availability with exception handling."""
        try:
            return self._resource_monitor.are_resources_available
        except Exception as e:
            # Resource monitor failure - log error and continue with defaults
            error_message = f"Resource monitor communication failure: {e}"
            self._logger.warning(error_message)
            self._error_monitor.handle_error(error_message, {})
            return True, ""  # Default to available

    def process_batch(
        self,
        file_paths: list[str] | str,
        output_dir: Optional[str] = None,
        options: Optional[dict[str, Any]] = None,
        progress_callback: Optional[Callable] = None
    ) -> BatchResult:
        """
        Process a batch of files.
        
        Args:
            file_paths: list of file paths to process, or a directory path to
                recursively process all files within.
            output_dir: Directory to write output files to. If None, files will
                be processed but output will not be written to disk.
            options: Processing options to pass to the pipeline.
            progress_callback: Optional callback function for reporting progress.
                The function should accept current_count, total_count, and current_file.
                
        Returns:
            A BatchResult object with the results of the batch processing.
        """
        print(f"DEBUG: process_batch called with file_paths: {file_paths}, output_dir: {output_dir}")
        
        # Check if already processing and reject concurrent calls
        if self._current_batch_processing_state == _BatchState.PROCESSING:
            error_message = "BatchProcessor is already processing a batch"
            print(f"DEBUG: Already processing, returning error: {error_message}")
            self._logger.warning(error_message)
            batch_result = self._batch_result(start_time=self._time())
            batch_result.success = False
            batch_result.error = error_message
            return batch_result

        # Set processing state at the beginning
        self._current_batch_processing_state = _BatchState.PROCESSING
        
        # Reset relevant flags
        self.cancellation_requested = False
        resolve_paths_list: list[str] = []
        batch_result: BatchResult = None # Prevent unbounded local if processing fails.

        self._logger.debug(f"Processing batch of files")

        # Verify output directory if provided
        if output_dir and not self._exists(output_dir):
            print(f"DEBUG: Output directory {output_dir} doesn't exist, creating it")
            try:
                self._makedirs(output_dir, exist_ok=True)
                msg = f"Output directory {output_dir} created successfully"
                self._logger.debug(msg)
                print(f"DEBUG: {msg}")
            except Exception as e:
                error_message = f"Failed to create output directory {output_dir}: {e}"
                print(f"DEBUG: {error_message}")
                self._logger.error(error_message)
                self._error_monitor.handle_error(
                    error_message, {'output_dir': output_dir, 'resolve_paths_list': resolve_paths_list}
                )
                self._current_batch_processing_state = _BatchState.COMPLETED
                raise ValueError(error_message) from e

        try:
            # Start resource monitoring
            print("DEBUG: Starting resource monitoring")
            try:
                self._resource_monitor.start_monitoring()
                print("DEBUG: Resource monitoring started successfully")
            except Exception as e:
                print(f"DEBUG: Failed to start resource monitoring: {e}")
                self._logger.warning(f"Failed to start resource monitoring: {e}")
                raise RuntimeError(f"Failed to start resource monitoring: {e}") from e

            print("DEBUG: Initializing batch result and resolving paths")
            # Initialize batch result
            self._current_batch_start_time = self._time()
            batch_result = self._batch_result(start_time=self._current_batch_start_time)

            file_paths = file_paths if isinstance(file_paths, list) else [file_paths]
            print(f"DEBUG: Processing {len(file_paths)} input paths")

            for path in file_paths:
                print(f"DEBUG: Resolving path: {path}")
                try:
                    # Resolve and validate input file paths
                    # NOTE This checks that they exist, not that they're openable.
                    resolved_paths = self._resolve_paths(path)
                    resolve_paths_list.extend(resolved_paths)
                except Exception as e:
                    error_message = f"Failed to resolve paths for {path}: {e}"
                    self._logger.debug(error_message, {'file_paths': file_paths})
                    self._error_monitor.handle_error(error_message, {'file_paths': file_paths})
                    continue

            if len(resolve_paths_list) == 0:
                print("DEBUG: No file paths could be resolved")
                self._logger.warning("No file paths in batch could be resolved.")
                batch_result.mark_as_complete()
                return batch_result

            self._files_remaining = len_results_path_list = len(resolve_paths_list)
            self._current_batch_size = len_results_path_list

            print(f"DEBUG: Total files to process: {len_results_path_list}")
            self._logger.debug(f"Processing batch of {len_results_path_list} files")

            # Process files in chunks to manage memory usage
            print(f"DEBUG: Processing files in chunks of max size {self.max_batch_size}")
            for idx in range(0, len_results_path_list, self.max_batch_size):
                print(f"DEBUG: Processing chunk starting at index {idx}")
                
                if self.cancellation_requested:
                    print("DEBUG: Cancellation requested, breaking from chunk loop")
                    self._logger.info("Batch processing cancelled")
                    self.cancellation_requested = False
                    break

                # Get chunk of files to process
                chunk = resolve_paths_list[idx:idx + self.max_batch_size]
                print(f"DEBUG: Chunk size: {len(chunk)} files")

                # Check resource availability safely
                print("DEBUG: Checking resource availability")
                resources_available, reason = self._safe_resource_check()
                print(f"DEBUG: Resources available: {resources_available}, reason: {reason}")
                
                if not resources_available:
                    print(f"DEBUG: Insufficient resources, attempting cleanup")
                    self._logger.warning(f"Insufficient resources: {reason}")

                    # Force memory cleanup before continuing
                    self._collect(2)
                    print("DEBUG: Garbage collection performed")

                    # Check if resources are now available
                    resources_available, reason = self._safe_resource_check()
                    print(f"DEBUG: Resources after cleanup: {resources_available}")
                    
                    if resources_available:
                        self._logger.debug("Resource constraints resolved after garbage collection")
                        print("DEBUG: Resource constraints resolved after cleanup")
                    else:
                        # Still insufficient resources, reduce batch size
                        reduced_batch_size = max(1, len(chunk) // 2)
                        if reduced_batch_size < len(chunk):
                            print(f"DEBUG: Reducing chunk size from {len(chunk)} to {reduced_batch_size}")
                            self._logger.warning(f"Reducing batch size from {len(chunk)} to {reduced_batch_size} due to memory constraints")
                            chunk = chunk[:reduced_batch_size]

                # Process the chunk
                print(f"DEBUG: Processing chunk of {len(chunk)} files")
                chunk_results = self._process_chunk( # ->  list[ProcessingResult] 
                    chunk, 
                    output_dir, 
                    options, 
                    progress_callback,
                    total_count=len(resolve_paths_list),
                    current_index=idx
                )
                print(f"DEBUG: Chunk processing completed, got {len(chunk_results)} results")

                # Add results to batch result
                print("DEBUG: Adding chunk results to batch result")
                for result in chunk_results:
                    self._running_batch_results.add_result(result)
                    self._files_completed += 1
                    self._files_remaining -= 1
                print(f"DEBUG: Files completed: {self._files_completed}, remaining: {self._files_remaining}")

                # Perform explicit garbage collection after processing chunk
                self._collect(2)
                print(f"DEBUG: Garbage collection performed after chunk of {len(chunk)} files")
                self._logger.debug(f"Garbage collection performed after processing chunk of {len(chunk)} files")

                # Check if we should stop due to errors
                if not self.continue_on_error and self._running_batch_results.failed_files > 0:
                    print(f"DEBUG: Stopping due to errors (continue_on_error=False), failed files: {self._running_batch_results.failed_files}")
                    self._logger.warning("Stopping batch processing due to errors")
                    break

            # Mark batch as complete
            print("DEBUG: Marking batch as complete")
            batch_result.mark_as_complete()

            # Log final results
            final_message = f"Batch processing completed: {batch_result.successful_files} succeeded, {batch_result.failed_files} failed"
            print(f"DEBUG: {final_message}")
            self._logger.info(final_message)

            return batch_result

        finally:
            # Always reset processing state
            self._current_batch_processing_state = _BatchState.COMPLETED
            
            if batch_result is not None:
                # Update the running batch results
                self._running_batch_results.update(batch_result)
                self._last_batch_summary = batch_result.get_summary()


            # Reset relevant class variables
            self._current_batch_start_time = None

            # Stop resource monitoring safely
            try:
                self._resource_monitor.stop_monitoring()
                print("DEBUG: Resource monitoring stopped successfully")
            except Exception as e:
                self._logger.warning(f"Failed to stop resource monitoring: {e}")
                raise RuntimeError(f"Failed to stop resource monitoring: {e}") from e


    def _process_chunk(
        self,
        file_paths: list[str],
        output_dir: Optional[str],
        options: Optional[dict[str, Any]],
        progress_callback: Optional[Callable],
        total_count: int,
        current_index: int
    ) -> list['ProcessingResult']:
        """
        Process a chunk of files.
        
        Args:
            file_paths: list of file paths to process.
            output_dir: Directory to write output files to.
            options: Processing options.
            progress_callback: Progress callback function.
            total_count: Total number of files in the full batch.
            current_index: Current index in the full batch.
            
        Returns:
            List of ProcessingResult objects for the processed files.
        """
        print(f"DEBUG: _process_chunk called with {len(file_paths)} files, output_dir: {output_dir}")
        print(f"DEBUG: total_count: {total_count}, current_index: {current_index}")
        
        results = []
        options = options or {}
        print(f"DEBUG: options: {options}")
        
        # Determine processing mode (parallel or sequential)
        use_parallel = self.max_threads > 1 and len(file_paths) > 1
        print(f"DEBUG: max_threads: {self.max_threads}, file_paths count: {len(file_paths)}")
        print(f"DEBUG: use_parallel: {use_parallel}")
        
        if use_parallel:
            print("DEBUG: Processing files in parallel")
            # Process files in parallel
            results = self._process_files_parallel(
                file_paths, output_dir, options, progress_callback, 
                total_count, current_index
            )
        else:
            print("DEBUG: Processing files sequentially")
            # Process files sequentially
            results = self._process_files_sequential(
                file_paths, output_dir, options, progress_callback,
                total_count, current_index
            )
        
        print(f"DEBUG: _process_chunk completed, returning {len(results)} results")
        return results

    def _process_files_parallel(
        self,
        file_paths: list[str],
        output_dir: Optional[str],
        options: dict[str, Any],
        progress_callback: Optional[Callable],
        total_count: int,
        current_index: int
    ) -> list['ProcessingResult']:
        """Process files in parallel using a thread pool.
        
        Args:
            file_paths: list of file paths to process.
            output_dir: Directory to write output files to.
            options: Processing options.
            progress_callback: Progress callback function.
            total_count: Total number of files in the full batch.
            current_index: Current index in the full batch.
            
        Returns:
            List of ProcessingResult objects for the processed files.
        """
        results = []
        progress_counter = 0
        
        # Use cf.ThreadPoolExecutor for parallel processing
        # TODO Parallel processor should be dynamic. Needs to handle ProcessPoolExecutor for CPU-bound tasks, and Asyncio for IO-bound tasks.
        with self._ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            # Submit all tasks
            print(f"Processing {len(file_paths)} files in parallel with {self.max_threads} threads")
            future_to_path = {}
            for path in file_paths:
                if self.cancellation_requested:
                    self.cancellation_requested = False
                    break

                # Determine output path
                output_path = self._get_output_path(path, output_dir, options)

                # Submit task
                future = executor.submit(
                    self._process_single_file, path, output_path, options
                )
                future_to_path[future] = path

            # Check if we have any futures to process
            if not future_to_path:
                print("DEBUG: No futures to process. Returning empty results.")
                return results

            # Process results as they complete
            print(f"DEBUG: Waiting for {len(future_to_path)} futures to complete")
            for future in self._as_completed(future_to_path):
                print(f"DEBUG: Future completed: {future}")
                if self.cancellation_requested:
                    print("Cancellation requested, stopping processing")
                    self.cancellation_requested = False
                    break

                # Get file path
                file_path = future_to_path[future]

                try:
                    # Get result
                    result = future.result()
                    print(f"DEBUG: FUTURE RESULT: {result}")
                    results.append(result)

                    # Update progress safely
                    progress_counter += 1
                    self._safe_progress_callback(
                        progress_callback,
                        current_index + progress_counter, 
                        total_count, 
                        file_path
                    )

                except Exception as e:
                    # Handle errors
                    self._logger.error(f"Error processing {file_path}: {e}")
                    error_result = self._processing_result(
                        success=False,
                        file_path=file_path,
                        errors=[str(e)]
                    )
                    results.append(error_result)
                    print(f"Error processing {file_path}: {e}")
                    
                    # Call error monitor as expected by tests
                    self._error_monitor.handle_error(
                        str(e), {'file_path': path, 'output_path': output_path}
                    )

                    # Update progress safely
                    progress_counter += 1
                    self._safe_progress_callback(
                        progress_callback,
                        current_index + progress_counter, 
                        total_count, 
                        file_path
                    )

        # Check if we processed any results
        if not results and future_to_path:
            # We had futures but got no results - this indicates all futures failed
            raise RuntimeError("No files were processed, all futures failed or were cancelled.")

        return results

    def _process_files_sequential(
        self,
        file_paths: list[str],
        output_dir: Optional[str],
        options: dict[str, Any],
        progress_callback: Optional[Callable],
        total_count: int,
        current_index: int
    ) -> list[ProcessingResult]:
        """Process files sequentially.
        
        Args:
            file_paths: list of file paths to process.
            output_dir: Directory to write output files to.
            options: Processing options.
            progress_callback: Progress callback function.
            total_count: Total number of files in the full batch.
            current_index: Current index in the full batch.
            
        Returns:
            List of ProcessingResult objects for the processed files.
        """
        results = []

        for idx, path in enumerate(file_paths, start=1):
            # Check for cancellation BEFORE processing each file
            if self.cancellation_requested:
                # Don't reset cancellation_requested here - let it remain True
                # so tests can verify cancellation was detected
                break
            
            # Determine output path
            output_path = self._get_output_path(path, output_dir, options)

            try:
                # Process file
                result = self._process_single_file(path, output_path, options)
                results.append(result)

                # Update progress safely
                self._safe_progress_callback(
                    progress_callback,
                    current_index + idx, 
                    total_count, 
                    path
                )

            except Exception as e:
                # Handle errors using the error monitor
                self._logger.error(f"Error processing {path}: {e}")
                
                # Call error monitor as expected by tests
                self._error_monitor.handle_error(
                    str(e), {'file_path': path, 'output_path': output_path}
                )
                
                # Create error result
                error_result = self._processing_result(
                    success=False,
                    file_path=path,
                    output_path=output_path,
                    errors=[str(e)]
                )
                results.append(error_result)

                # Update progress safely
                self._safe_progress_callback(
                    progress_callback,
                    current_index + idx, 
                    total_count, 
                    path
                )
                
                # Check if we should continue based on continue_on_error setting
                if not self.continue_on_error:
                    break
        
        return results
        
    def _process_single_file(
        self,
        file_path: str,
        output_path: Optional[str],
        options: dict[str, Any]
    ) -> ProcessingResult:
        """Process a single file.
        
        Args:
            file_path: Path to the file to process.
            output_path: Path to write output to.
            options: Processing options.
            
        Returns:
            ProcessingResult object for the processed file.
        """
        try:
            # Check if resources are available safely
            resources_available, reason = self._safe_resource_check()
            if not resources_available:
                error_message = f"Insufficient system resources: {reason}"
                self._logger.warning(error_message, {'file_path': file_path})
                return self._processing_result(
                    success=False,
                    file_path=file_path,
                    output_path=output_path,
                    errors=[error_message]
                )

            # Process the file
            # NOTE Sanitization happens within the pipeline.
            result: ProcessingResult = self._pipeline.process_file(file_path, output_path, options)

            return result

        except Exception as e:
            # Use the error handler to handle and log the error
            self._error_monitor.handle_error(
                e, {'file_path': file_path, 'output_path': output_path}
            )
            # Create a failure result
            return self._processing_result(
                success=False,
                file_path=file_path,
                output_path=output_path,
                errors=[str(e)]
            )

    def cancel_processing(self) -> None:
        """Cancel ongoing batch processing."""
        self._logger.info("Cancellation requested for batch processing")
        with self._lock:
            self.cancellation_requested = True
            self._cancel_processing_was_called = True

    @property
    def processing_status(self) -> dict[str, Any]:
        """
        Get the current status of batch processing.
        
        Returns:
            A dictionary with the current status including both legacy and new format.
        """
        with self._lock:
            # Calculate progress percentage
            progress_percent = 0
            if self._current_batch_size > 0:
                progress_percent = (self._files_completed / self._current_batch_size) * 100

            is_processing = False

            # Determine values based on processing state.
            match self._current_batch_processing_state:
                case _BatchState.CANCELLING | _BatchState.PROCESSING:
                    is_processing = True
                case _BatchState.COMPLETED:
                    pass
                case  _BatchState.IDLE:
                    pass

            # Capture current cancellation state before potentially resetting it
            current_cancellation_requested = self.cancellation_requested
            
            # Only reset cancellation flag if we're not actively processing
            # During active processing, the flag should remain set until processing stops
            if self.cancellation_requested and not is_processing:
                self.cancellation_requested = False
                current_cancellation_requested = False

            return {
                # New unified format (expected by tests)
                'state': self._current_batch_processing_state,
                'is_processing': is_processing,
                'files_completed': self._files_completed,
                'total_files': self._current_batch_size,
                'files_processing': self._active_threads,
                'progress_percent': progress_percent,
                'active_threads': self._active_threads,
                'max_threads': self.max_threads,
                'cancellation_requested': current_cancellation_requested,
                'last_batch_summary': self._last_batch_summary,
                'estimated_time_remaining': self.eta,  # Get estimated time remaining
                'batch_start_time': self._current_batch_start_time,

                # Legacy detailed status (existing implementation)
                'pipeline_status': self._pipeline.status,
                'current_resource_usage': self._resource_monitor.current_resource_usage,
                'error_statistics': self._error_monitor.error_statistics,
            }

    def set_max_batch_size(self, size: int) -> None:
        """
        Set the maximum batch size.
        
        Args:
            size: Maximum number of files to process in a single batch.
        """
        self._assert_positive_int(size, "max_batch_size")
        self.max_batch_size = max(1, size)
        self._logger.info(f"Max batch size set to {self.max_batch_size}")

    def set_continue_on_error(self, flag: bool) -> None:
        """Set whether to continue processing if errors occur.
        
        Args:
            flag: Whether to continue processing if errors occur.
        """
        if not isinstance(flag, bool):
            raise TypeError(f"continue_on_error must bool, got '{type(flag).__name__}'")
        self.continue_on_error = flag
        self._logger.info(f"Continue on error set to {self.continue_on_error}")

    def set_max_threads(self, count: int) -> None:
        """Set the maximum number of worker threads for parallel processing.
        
        Args:
            count: Maximum number of worker threads.
        """
        self._assert_positive_int(count, "max_threads")

        total_cores = self._resource_monitor.current_resource_usage['cpu_count']
        if count > total_cores:
            raise ValueError(
                f"Cannot set max_threads to '{count}' as it exceeds the system's total CPU cores: {total_cores}"
            )
        self.max_threads = max(1, count)
        self._logger.info(f"max_threads set to '{self.max_threads}'")








