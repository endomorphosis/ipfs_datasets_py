# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/batch_processor.py'

Files last updated: 1751886761.6533275

Stub file last updated: 2025-07-07 04:13:22

## BatchJobResult

```python
@dataclass
class BatchJobResult:
    """
    Comprehensive result container for individual PDF batch processing jobs.

This dataclass encapsulates the complete outcome of processing a single PDF document
within a batch operation, including success status, processing metrics, error information,
and links to generated outputs. It serves as the primary result object returned by
batch processing workers to track job completion and quality metrics.

Attributes:
    job_id (str): Unique identifier for the specific batch job that generated this result.
    status (str): Result status ('completed' or 'failed').
    processing_time (float): Total time in seconds required to process this document.
    document_id (Optional[str]): Identifier of the LLM document created from PDF.
        None if processing failed before document creation.
    knowledge_graph_id (Optional[str]): Identifier of the knowledge graph extracted.
        None if processing failed before knowledge graph creation.
    ipld_cid (Optional[str]): Content identifier if the result was stored in IPLD.
        None if not stored or processing failed.
    entity_count (int): Number of entities extracted from the document. 0 if failed.
    relationship_count (int): Number of relationships discovered. 0 if failed.
    chunk_count (int): Number of text chunks generated. 0 if failed.
    error_message (Optional[str]): Detailed error message if processing failed.
        None for successful jobs.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## BatchProcessor

```python
class BatchProcessor:
    """
    High-performance batch processing engine for large-scale PDF document processing operations.

The BatchProcessor class provides comprehensive functionality for processing multiple PDF documents
concurrently using worker threads, resource monitoring, and intelligent job scheduling. It handles
everything from job queue management to result aggregation, with built-in monitoring, audit logging,
and fault tolerance capabilities. This class is designed for production environments where
processing hundreds or thousands of PDF documents efficiently is critical.

The processor orchestrates the complete PDF processing pipeline including PDF decomposition,
OCR processing, LLM optimization, entity extraction, knowledge graph creation, and IPLD storage
for each document while maintaining optimal resource utilization and providing real-time progress
tracking and comprehensive error handling.

Key Features:
- Multi-threaded processing with configurable worker pools
- Memory usage monitoring and automatic throttling
- Job prioritization and intelligent scheduling
- Real-time progress tracking with callback support
- Comprehensive error handling and recovery
- Audit logging for compliance and debugging
- Export capabilities for batch results
- Resource usage statistics and performance metrics

Attributes:
    max_workers (int): Maximum number of concurrent worker threads for processing.
    max_memory_mb (int): Maximum memory usage threshold in MB before throttling.
    storage (IPLDStorage): IPLD storage instance for persistent data management.
    audit_logger (AuditLogger): Audit logging system for compliance tracking.
    monitoring (MonitoringSystem): Performance monitoring and metrics collection.
    pdf_processor (PDFProcessor): Core PDF processing component.
    llm_optimizer (LLMOptimizer): LLM optimization component.
    graphrag_integrator (GraphRAGIntegrator): Knowledge graph integration component.
    job_queue (Queue): Thread-safe queue containing pending processing jobs.
    completed_jobs (List[BatchJobResult]): List of successfully completed job results.
    failed_jobs (List[BatchJobResult]): List of failed job results with error information.
    active_batches (Dict[str, BatchStatus]): Dictionary tracking currently active batch operations.
    workers (List[Thread]): List of active worker thread instances.
    worker_pool (ProcessPoolExecutor): Process pool for CPU-intensive operations.
    is_processing (bool): Flag indicating whether processing is currently active.
    stop_event (Event): Threading event for coordinating worker shutdown.
    processing_stats (Dict[str, Any]): Accumulated statistics across all operations.

Usage Example:
    processor = BatchProcessor(
        max_workers=8,
        max_memory_mb=4096,
        enable_monitoring=True,
        enable_audit=True
    )
    
    # Process batch with progress callback
    def progress_callback(status):
        print(f"Progress: {status.completed_jobs}/{status.total_jobs}")
    
    batch_id = await processor.process_batch(
        pdf_paths=["/docs/paper1.pdf", "/docs/paper2.pdf"],
        priority=8,
        callback=progress_callback
    )
    
    # Monitor batch status
    status = await processor.get_batch_status(batch_id)
    
    # Export results when complete
    output_file = await processor.export_batch_results(batch_id, format="json")

Notes:
    - Worker threads are automatically managed based on system resources
    - Memory usage is monitored to prevent system overload
    - All batch operations are tracked with unique identifiers
    - Failed jobs are logged with detailed error information
    - Audit logs provide detailed information for compliance and debugging
    - The class is thread-safe and supports concurrent batch operations
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## BatchStatus

```python
@dataclass
class BatchStatus:
    """
    Comprehensive status tracking container for batch processing operations.

This dataclass provides real-time status information for ongoing batch processing operations,
including progress metrics, timing information, resource usage, and quality statistics.
It serves as the primary status object for monitoring batch operations and providing
feedback to users and automated systems.

Attributes:
    batch_id (str): Unique identifier for the batch processing operation.
    total_jobs (int): Total number of PDF documents queued for processing in this batch.
    completed_jobs (int): Number of documents that have completed processing successfully.
    failed_jobs (int): Number of documents that failed processing with unrecoverable errors.
    pending_jobs (int): Number of documents still waiting to be processed.
    processing_jobs (int): Number of documents currently being processed by workers.
    start_time (str): ISO timestamp when the batch processing operation began.
    end_time (Optional[str]): ISO timestamp when the batch completed. None if still running.
    total_processing_time (float): Cumulative processing time across all completed jobs.
    average_job_time (float): Average time per job processed so far.
    throughput (float): Documents processed per second for completed batches.
    resource_usage (Dict[str, Any]): Current resource usage statistics including
        memory, CPU, and worker thread information.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProcessingJob

```python
@dataclass
class ProcessingJob:
    """
    Individual PDF document processing job specification and tracking container.

This dataclass encapsulates all information needed to process a single PDF document
within a batch operation, including file information, processing parameters, priority
settings, and tracking metadata. It serves as the unit of work passed between
the job scheduler and worker threads.

Attributes:
    job_id (str): Unique identifier for this specific processing job within the batch.
    pdf_path (str): Path to the PDF file to be processed.
    metadata (Dict[str, Any]): Additional metadata about the document and processing:
        - 'batch_id': Identifier of the parent batch operation
        - 'batch_metadata': Metadata for the entire batch
        - 'job_index': Position of this job within the batch
    priority (int): Processing priority level (1-10, where 10 is highest priority).
        Defaults to 5.
    created_at (str): ISO timestamp when this job was created and queued.
    status (str): Current job status. Possible values:
        - 'pending': Job is queued but not yet started
        - 'processing': Job is currently being processed
        - 'completed': Job finished successfully
        - 'failed': Job failed with unrecoverable error
    error_message (Optional[str]): Detailed error description if job failed.
        None for successful or pending jobs.
    result (Optional[Dict[str, Any]]): Job processing results if completed successfully.
    processing_time (float): Time in seconds required to process this job.
        0.0 for jobs that haven't completed.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, max_workers: int = None, max_memory_mb: int = 4096, storage: Optional[IPLDStorage] = None, enable_monitoring: bool = False, enable_audit: bool = True):
    """
    Initialize the BatchProcessor with configuration for concurrent PDF processing operations.

This method sets up the complete batch processing environment including worker thread
management, resource monitoring, audit logging, and the underlying PDF processing pipeline.
It configures all necessary components for high-performance, fault-tolerant batch operations
while establishing proper resource limits and monitoring capabilities.

Args:
    max_workers (Optional[int], optional): Maximum number of concurrent worker threads.
        Defaults to min(cpu_count(), 8) if None. Higher values increase parallelism
        but may cause resource contention. Recommended range: 2-16 depending on system.
    max_memory_mb (int, optional): Maximum memory usage threshold in megabytes before
        processing throttling is applied. Defaults to 4096 MB. Used to prevent
        system overload during large batch operations.
    storage (Optional[IPLDStorage], optional): IPLD storage instance for persistent
        data management. Defaults to a new IPLDStorage instance if not provided.
        Must support async operations for knowledge graph storage.
    enable_monitoring (bool, optional): Enable comprehensive performance monitoring
        and metrics collection. Defaults to False. When enabled, creates detailed
        performance logs and Prometheus-compatible metrics.
    enable_audit (bool, optional): Enable audit logging for compliance and debugging.
        Defaults to True. Tracks all batch operations, job status changes, and errors
        for regulatory compliance and troubleshooting.

Attributes initialized:
    max_workers (int): Maximum number of concurrent worker threads for processing.
    max_memory_mb (int): Memory usage threshold for processing throttling.
    storage (IPLDStorage): IPLD storage instance for persistent data management.
    audit_logger (Optional[AuditLogger]): Audit logging system if enabled.
    monitoring (Optional[MonitoringSystem]): Performance monitoring system if enabled.
    pdf_processor (PDFProcessor): Core PDF processing component with OCR and decomposition.
    llm_optimizer (LLMOptimizer): Component for optimizing content for LLM processing.
    graphrag_integrator (GraphRAGIntegrator): Knowledge graph creation and integration.
    job_queue (Queue): Thread-safe queue for managing processing jobs.
    completed_jobs (List[BatchJobResult]): Storage for successfully completed job results.
    failed_jobs (List[BatchJobResult]): Storage for failed job results with error details.
    active_batches (Dict[str, BatchStatus]): Tracking dictionary for active batch operations.
    workers (List[Thread]): List of active worker thread instances.
    worker_pool (Optional[ProcessPoolExecutor]): Process pool for CPU-intensive operations.
    is_processing (bool): Flag indicating whether processing is currently active.
    stop_event (Event): Threading event for coordinating graceful worker shutdown.
    processing_stats (Dict[str, Any]): Accumulated performance statistics.

Raises:
    ImportError: If required monitoring dependencies are not available when monitoring is enabled.
    RuntimeError: If storage initialization fails or required system resources are unavailable.
    ValueError: If max_workers is less than 1 or max_memory_mb is less than 512.

Examples:
    >>> # Basic initialization with default settings
    >>> processor = BatchProcessor()
    
    >>> # High-performance setup with monitoring
    >>> processor = BatchProcessor(
    ...     max_workers=12,
    ...     max_memory_mb=8192,
    ...     enable_monitoring=True,
    ...     enable_audit=True
    ... )
    
    >>> # Custom storage with limited resources
    >>> custom_storage = IPLDStorage(config={'cache_size': '1GB'})
    >>> processor = BatchProcessor(
    ...     max_workers=4,
    ...     max_memory_mb=2048,
    ...     storage=custom_storage,
    ...     enable_monitoring=False
    ... )

Notes:
    - Worker threads are automatically managed and scaled based on system resources
    - Memory monitoring prevents system overload during large batch operations
    - Audit logging provides detailed compliance and debugging information
    - The processor is thread-safe and supports concurrent batch operations
    - All processing components are initialized with shared storage for consistency
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## __post_init__

```python
def __post_init__(self):
    """
    Initialize computed fields after dataclass instantiation.

This method is automatically called by the dataclass framework after object
creation to set default values for fields that require computation. It ensures
that the created_at timestamp is set to the current UTC time if not explicitly
provided during object creation.

Side Effects:
    - Sets created_at to current UTC timestamp in ISO format if empty
    - No other fields are modified

Examples:
    >>> # created_at is automatically set
    >>> job = ProcessingJob(job_id='job_1', pdf_path='/doc.pdf', metadata={})
    >>> print(job.created_at)  # Shows current timestamp
    
    >>> # created_at can be explicitly provided
    >>> job = ProcessingJob(
    ...     job_id='job_2',
    ...     pdf_path='/doc2.pdf',
    ...     metadata={},
    ...     created_at='2024-01-01T12:00:00'
    ... )
    >>> print(job.created_at)  # Shows '2024-01-01T12:00:00'

Notes:
    - Only sets created_at if it's empty or None
    - Uses UTC timezone for consistent timestamp handling
    - ISO format ensures consistent timestamp parsing
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingJob

## _get_resource_usage

```python
def _get_resource_usage(self) -> Dict[str, Any]:
    """
    Collect and return current system resource usage statistics for monitoring and throttling.

This method gathers comprehensive resource utilization metrics including memory usage,
CPU utilization, worker thread status, and queue metrics. The data is used for
performance monitoring, resource-based throttling decisions, and system health tracking.
All metrics are collected in real-time to provide accurate current state information.

Returns:
    Dict[str, Any]: Comprehensive resource usage statistics:
        - 'memory_mb': Current memory usage in megabytes (RSS)
        - 'memory_percent': Memory usage as percentage of system total
        - 'cpu_percent': Current CPU utilization percentage
        - 'active_workers': Number of worker threads currently alive
        - 'queue_size': Number of jobs waiting in the processing queue
        - 'peak_memory_mb': Peak memory usage since processor initialization

Raises:
    ImportError: If psutil library is not available for resource monitoring.
    OSError: If system resource information cannot be accessed.
    PermissionError: If insufficient permissions to read system resource data.

Side Effects:
    - Updates peak_memory_usage in processing_stats if current usage is higher
    - No modification of system state or processing behavior

Examples:
    >>> # Check current resource usage
    >>> usage = processor._get_resource_usage()
    >>> print(f"Memory: {usage['memory_mb']:.1f} MB ({usage['memory_percent']:.1f}%)")
    >>> print(f"CPU: {usage['cpu_percent']:.1f}%")
    >>> print(f"Active workers: {usage['active_workers']}/{processor.max_workers}")
    
    >>> # Monitor queue backlog
    >>> usage = processor._get_resource_usage()
    >>> if usage['queue_size'] > 100:
    ...     print("Large queue backlog detected")
    
    >>> # Check for memory pressure
    >>> usage = processor._get_resource_usage()
    >>> if usage['memory_mb'] > processor.max_memory_mb:
    ...     print("Memory threshold exceeded")

Notes:
    - Memory measurements are based on Resident Set Size (RSS)
    - CPU percentage is calculated over recent time interval
    - Worker count includes only alive threads, not total created
    - Queue size reflects pending jobs across all batches
    - Peak memory tracking persists across batch operations
    - Method is called frequently during processing for real-time monitoring
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _monitor_batch_progress

```python
async def _monitor_batch_progress(self, batch_id: str, callback: Callable):
    """
    Continuously monitor batch processing progress and invoke callback function with status updates.

This method runs a monitoring loop that tracks batch progress in real-time and
periodically invokes a user-provided callback function with current batch status.
It supports both synchronous and asynchronous callback functions, handles callback
errors gracefully, and automatically terminates when the batch completes.

The monitoring loop polls batch status every 5 seconds and provides comprehensive
status information including job counts, timing metrics, and resource usage.
This enables real-time progress tracking, user interface updates, and integration
with external monitoring systems.

Args:
    batch_id (str): Unique identifier of the batch to monitor. Must correspond
        to an active batch in the active_batches dictionary.
    callback (Callable): Function to call with batch status updates. Can be
        synchronous or asynchronous function that accepts BatchStatus parameter.
        Callback errors are logged but don't affect batch processing.

Raises:
    ValueError: If batch_id does not correspond to an active batch.
    TypeError: If callback is not callable or has incorrect signature.

Side Effects:
    - Continuously polls batch status every 5 seconds until completion
    - Invokes callback function with current BatchStatus object
    - Logs callback errors without affecting batch processing
    - Automatically terminates when batch completes
    - Does not modify batch status or processing state

Examples:
    >>> # Synchronous progress callback
    >>> def print_progress(status):
    ...     print(f"Batch {status.batch_id}: {status.completed_jobs}/{status.total_jobs}")
    
    >>> await processor._monitor_batch_progress('batch_123', print_progress)
    
    >>> # Asynchronous progress callback with database updates
    >>> async def save_progress(status):
    ...     await database.update_batch_progress(status.batch_id, status.completed_jobs)
    
    >>> await processor._monitor_batch_progress('batch_456', save_progress)

Notes:
    - Method runs until batch completion (completed + failed >= total_jobs)
    - Callback errors are logged but don't interrupt monitoring
    - Both sync and async callbacks are automatically detected and handled
    - 5-second polling interval balances responsiveness with system load
    - Method is typically called as asyncio task for non-blocking operation
    - Monitoring automatically stops when batch is no longer in active_batches
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## _process_single_job

```python
async def _process_single_job(self, job: ProcessingJob, worker_name: str) -> BatchJobResult:
    """
    Process a single PDF document through the complete processing pipeline with comprehensive error handling.

This method orchestrates the end-to-end processing of a single PDF document including
PDF decomposition, OCR processing, LLM optimization, entity extraction, knowledge graph
creation, and IPLD storage. It provides detailed progress tracking, performance monitoring,
and audit logging for each processing stage while ensuring proper error handling and
resource cleanup.

The processing pipeline consists of three main stages: PDF processing (decomposition and OCR),
LLM optimization (content preparation for language models), and GraphRAG integration
(entity extraction and knowledge graph creation). Each stage is independently monitored
and any failure results in a detailed error report.

Args:
    job (ProcessingJob): Complete job specification containing PDF path, metadata,
        priority settings, and tracking information. Must have valid pdf_path
        pointing to readable PDF file.
    worker_name (str): Identifier of the worker thread processing this job.
        Used for logging, debugging, and performance attribution.

Returns:
    BatchJobResult: Comprehensive result object containing processing outcome,
        performance metrics, generated content identifiers, and entity/relationship
        counts. Status will be 'completed' for successful processing or 'failed'
        with detailed error information.

Raises:
    FileNotFoundError: If the PDF file specified in job.pdf_path cannot be found.
    PermissionError: If insufficient permissions to read PDF or write to storage.
    MemoryError: If document processing exceeds available system memory.
    ValueError: If PDF file is corrupted or cannot be processed.
    RuntimeError: If any processing component fails unexpectedly.

Side Effects:
    - Updates job.status to 'processing' at start
    - Records processing start time for performance tracking
    - Creates monitoring context if monitoring is enabled
    - Stores successful results in completed_jobs list
    - Stores failed results in failed_jobs list
    - Updates global processing statistics
    - Logs processing progress and completion status
    - Creates audit log entries for failures

Examples:
    >>> # Called automatically by worker threads
    >>> job = ProcessingJob(
    ...     job_id='batch_abc123_job_0001',
    ...     pdf_path='/docs/research_paper.pdf',
    ...     metadata={'batch_id': 'batch_abc123'}
    ... )
    >>> result = await processor._process_single_job(job, 'worker_1')
    >>> print(f"Status: {result.status}, Entities: {result.entity_count}")

Notes:
    - Processing time includes all stages from PDF loading to IPLD storage
    - Failed jobs include detailed error messages for debugging
    - Performance monitoring provides operation-level metrics
    - Each stage failure is logged with specific error context
    - Knowledge graph storage in IPLD enables persistent retrieval
    - Method is fully async to support concurrent processing
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## _start_workers

```python
async def _start_workers(self):
    """
    Initialize and start worker threads for concurrent batch processing operations.

This private method creates and launches the worker thread pool responsible for processing
PDF documents concurrently. It establishes both thread-based workers for I/O-bound operations
and a process pool for CPU-intensive tasks like OCR and text processing. Workers are created
with proper daemon status for clean shutdown and configured for optimal resource utilization.

The method ensures that only one worker pool is active at a time and properly manages
the transition from stopped to active processing state. Each worker thread runs independently
and pulls jobs from the shared job queue using a producer-consumer pattern.

Raises:
    RuntimeError: If workers are already running or system resources are insufficient.
    OSError: If thread or process creation fails due to system limitations.
    PermissionError: If insufficient permissions to create worker processes.

Side Effects:
    - Sets is_processing flag to True
    - Clears the stop_event threading event
    - Creates max_workers worker threads in daemon mode
    - Initializes ProcessPoolExecutor for CPU-intensive operations
    - Updates workers list with active thread references
    - Logs worker startup information

Examples:
    >>> # Called automatically by process_batch, but can be called manually
    >>> await processor._start_workers()
    >>> # Worker threads are now running and ready to process jobs

Notes:
    - This method is idempotent - calling it multiple times has no additional effect
    - Worker threads automatically terminate when stop_event is set
    - Process pool size is limited to min(max_workers, cpu_count) for optimal performance
    - All worker threads are created as daemon threads for proper cleanup
    - Method logs the number of workers started for monitoring purposes
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## _update_batch_status

```python
def _update_batch_status(self, job: ProcessingJob, result: BatchJobResult):
    """
    Update batch-level status and metrics based on individual job completion results.

This method maintains real-time batch status information by processing individual
job results and updating aggregate statistics including completion counts, timing
metrics, and throughput calculations. It handles both successful and failed job
outcomes while ensuring accurate batch-level progress tracking and performance
measurement.

When all jobs in a batch are complete, the method automatically calculates final
batch metrics including total processing time, average job duration, and overall
throughput. It also determines batch completion status and sets end timestamps
for accurate duration measurement.

Args:
    job (ProcessingJob): The completed job specification containing batch
        identification and job metadata. Must have valid batch_id in metadata
        to update the correct batch status.
    result (BatchJobResult): The processing result containing status, timing,
        and error information. Status must be either 'completed' or 'failed'
        for proper batch accounting.

Raises:
    KeyError: If job metadata lacks required batch_id or batch not found in active_batches.
    ValueError: If result.status is not 'completed' or 'failed'.
    TypeError: If job or result parameters are not the expected dataclass types.

Side Effects:
    - Updates BatchStatus.completed_jobs count for successful results
    - Updates BatchStatus.failed_jobs count for failed results
    - Decrements BatchStatus.pending_jobs count
    - Accumulates total_processing_time across all jobs
    - Calculates and updates average_job_time for completed jobs
    - Sets end_time when all jobs are finished
    - Calculates final throughput (jobs per second) for completed batches
    - Logs batch completion information

Examples:
    >>> # Called automatically after each job completion
    >>> job = ProcessingJob(job_id='job_1', pdf_path='/doc.pdf',
    ...                    metadata={'batch_id': 'batch_123'})
    >>> result = BatchJobResult(job_id='job_1', status='completed',
    ...                        processing_time=45.2)
    >>> processor._update_batch_status(job, result)
    >>> # Batch status now reflects this job completion

Notes:
    - Method is thread-safe for concurrent job completion updates
    - Batch completion is detected when completed + failed >= total_jobs
    - Throughput calculation uses wall-clock time, not cumulative processing time
    - Final metrics are automatically calculated upon batch completion
    - Invalid batch_id in job metadata is silently ignored to prevent worker crashes
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _worker_loop

```python
def _worker_loop(self, worker_name: str):
    """
    Main execution loop for individual worker threads processing PDF documents from the job queue.

This method represents the core worker thread logic that continuously pulls jobs from
the shared job queue and processes them through the complete PDF processing pipeline.
Each worker operates independently, handling job retrieval, processing coordination,
result tracking, and error handling. The loop continues until a stop signal is received
or the worker encounters an unrecoverable error.

Workers implement a producer-consumer pattern with timeout-based queue polling to ensure
responsive shutdown behavior. Each job is processed completely by a single worker,
including all stages from PDF decomposition through knowledge graph creation.

Args:
    worker_name (str): Unique identifier for this worker thread instance.
        Used for logging, debugging, and performance tracking. Format typically
        'worker_{index}' where index is the worker number.

Raises:
    RuntimeError: If critical system resources become unavailable during processing.
    MemoryError: If system runs out of memory during document processing.
    KeyboardInterrupt: If process receives interrupt signal during processing.

Side Effects:
    - Continuously polls job_queue for new processing jobs
    - Processes jobs through _process_single_job method
    - Updates batch status for each completed or failed job
    - Marks queue tasks as done for proper queue management
    - Logs worker lifecycle events and processing progress
    - Handles graceful shutdown when stop_event is set

Examples:
    >>> # Called automatically by worker threads, not intended for direct use
    >>> # Worker lifecycle managed by _start_workers() and stop_processing()
    >>> worker_thread = Thread(target=self._worker_loop, args=('worker_1',))
    >>> worker_thread.start()

Notes:
    - Method runs in a continuous loop until stop_event is set
    - Uses 1-second timeout on queue.get() for responsive shutdown
    - Processes None jobs as shutdown signals
    - All exceptions are caught and logged to prevent worker crashes
    - Worker automatically handles job queue task completion
    - Processing is fully asynchronous using asyncio.run for each job
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## cancel_batch

```python
async def cancel_batch(self, batch_id: str) -> bool:
    """
    Cancel an active batch processing operation and remove pending jobs from the queue.

This method provides graceful cancellation of batch operations by removing all
pending jobs for the specified batch from the processing queue while allowing
currently processing jobs to complete. It updates batch status, logs cancellation
details, and provides audit trails for compliance tracking.

Jobs that are already being processed by worker threads will complete normally,
but no new jobs from the cancelled batch will be started. This ensures data
consistency and prevents partial document processing states.

Args:
    batch_id (str): Unique identifier of the batch to cancel. Must correspond
        to an existing batch in the active_batches dictionary.

Returns:
    bool: True if batch was successfully cancelled and pending jobs removed,
        False if batch_id was not found or batch was already complete.

Raises:
    ValueError: If batch_id is empty or invalid format.
    RuntimeError: If job queue manipulation fails due to system errors.

Side Effects:
    - Sets batch end_time to current timestamp
    - Removes all pending jobs for the batch from job_queue
    - Preserves jobs for other batches in the queue
    - Logs number of cancelled jobs for tracking
    - Creates audit log entry for cancellation event
    - Does not affect currently processing jobs

Examples:
    >>> # Cancel a specific batch
    >>> success = await processor.cancel_batch('batch_abc123')
    >>> if success:
    ...     print("Batch cancelled successfully")
    >>> else:
    ...     print("Batch not found or already complete")
    
    >>> # Cancel batch and check final status
    >>> await processor.cancel_batch(batch_id)
    >>> status = await processor.get_batch_status(batch_id)
    >>> if status and status['end_time']:
    ...     print(f"Cancelled with {status['completed_jobs']} completed jobs")

Notes:
    - Cancellation is immediate for pending jobs but graceful for active jobs
    - Currently processing jobs complete normally to maintain data consistency
    - Cancelled jobs are not marked as failed - they simply don't get processed
    - Audit logs provide detailed tracking for compliance and debugging
    - Method is safe to call multiple times on the same batch
    - Queue manipulation is atomic to prevent race conditions
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## export_batch_results

```python
async def export_batch_results(self, batch_id: str, format: str = "json", output_path: Optional[str] = None) -> str:
    """
    Export comprehensive batch processing results and metrics to a structured file format.

This method creates detailed exports of batch processing results including job outcomes,
performance metrics, error details, and batch metadata. It supports multiple output
formats for integration with different analysis tools and reporting systems. The export
includes both successful and failed job results with complete processing information.

Args:
    batch_id (str): Unique identifier of the batch to export. Must correspond
        to an existing batch in active_batches dictionary.
    format (str, optional): Output file format - 'json' or 'csv'. Defaults to 'json'.
        JSON format includes complete hierarchical data while CSV provides
        tabular results suitable for spreadsheet analysis.
    output_path (Optional[str], optional): Specific file path for export output.
        Defaults to None, which generates timestamped filename in current directory.
        Path should include appropriate file extension for the chosen format.

Returns:
    str: Absolute path to the created export file. File contains complete
        batch results and can be used for analysis, reporting, or archival.

Raises:
    ValueError: If batch_id is not found in active batches or format is unsupported.
    FileNotFoundError: If output_path directory does not exist.
    PermissionError: If insufficient permissions to write to output location.
    OSError: If file creation fails due to system limitations.

Side Effects:
    - Creates new file at specified or generated output path
    - Logs export completion with file path information
    - No modification of batch status or processing state

Examples:
    >>> # Export to default JSON file
    >>> export_path = await processor.export_batch_results('batch_abc123')
    >>> print(f"Results exported to: {export_path}")
    
    >>> # Export to specific CSV file for analysis
    >>> csv_path = await processor.export_batch_results(
    ...     batch_id='batch_abc123',
    ...     format='csv',
    ...     output_path='/reports/batch_analysis.csv'
    ... )
    
    >>> # Export with timestamp in filename
    >>> json_path = await processor.export_batch_results(
    ...     batch_id='batch_xyz789',
    ...     format='json',
    ...     output_path=f'/exports/batch_results_{datetime.now().strftime("%Y%m%d")}.json'
    ... )

Notes:
    - JSON exports include complete hierarchical batch and result data
    - CSV exports flatten result data for spreadsheet compatibility
    - Export includes both successful and failed job results
    - Timestamps are included for export traceability
    - Large batches may create substantial export files
    - Method supports both active and completed batches
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## get_batch_status

```python
async def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve current status and metrics for a specific batch processing operation.

This method provides comprehensive status information for a batch including job counts,
timing metrics, resource usage, and progress indicators. It returns real-time data
that can be used for monitoring, user interfaces, and automated batch management.
The status includes both static batch information and dynamic resource usage data.

Args:
    batch_id (str): Unique identifier of the batch to query. Must correspond
        to a batch that was created through process_batch method.

Returns:
    Optional[Dict[str, Any]]: Complete batch status information as dictionary,
        or None if batch_id is not found. Dictionary contains all BatchStatus
        fields plus current resource usage:
        - 'batch_id': Unique batch identifier
        - 'total_jobs': Total number of PDF documents in batch
        - 'completed_jobs': Number of successfully processed documents
        - 'failed_jobs': Number of documents that failed processing
        - 'pending_jobs': Number of documents awaiting processing
        - 'processing_jobs': Number of documents currently being processed
        - 'start_time': ISO timestamp when batch started
        - 'end_time': ISO timestamp when batch completed (None if running)
        - 'total_processing_time': Cumulative processing time across all jobs
        - 'average_job_time': Average time per completed job
        - 'throughput': Documents processed per second (for completed batches)
        - 'resource_usage': Current system resource utilization

Raises:
    TypeError: If batch_id is not a string.
    RuntimeError: If system resource monitoring fails.

Examples:
    >>> # Get status for active batch
    >>> status = await processor.get_batch_status('batch_abc123')
    >>> if status:
    ...     print(f"Progress: {status['completed_jobs']}/{status['total_jobs']}")
    ...     print(f"Memory usage: {status['resource_usage']['memory_mb']:.1f} MB")
    
    >>> # Check if batch is complete
    >>> status = await processor.get_batch_status(batch_id)
    >>> if status and status['end_time']:
    ...     print(f"Batch completed with {status['completed_jobs']} successful jobs")
    >>> else:
    ...     print("Batch still processing or not found")

Notes:
    - Returns None for non-existent batch IDs rather than raising exception
    - Resource usage data is collected in real-time when method is called
    - All timestamps are in ISO format for consistent parsing
    - Status data includes both completed and active batches
    - Method is safe to call frequently for real-time monitoring
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## get_processing_statistics

```python
async def get_processing_statistics(self) -> Dict[str, Any]:
    """
    Retrieve comprehensive processing statistics and performance metrics across all batch operations.

This method provides detailed analytics about the processor's performance including
job completion rates, timing metrics, resource utilization, and success rates.
The statistics cover all processing activity since processor initialization and
include real-time resource usage data for current system state assessment.

Returns:
    Dict[str, Any]: Comprehensive processing statistics:
        - 'total_processed': Total number of successfully processed documents
        - 'total_failed': Total number of documents that failed processing
        - 'total_jobs': Combined total of processed and failed documents
        - 'success_rate': Percentage of successful processing (0.0 to 1.0)
        - 'total_processing_time': Cumulative processing time across all jobs
        - 'average_job_time': Average processing time per successful document
        - 'active_batches': Number of currently active batch operations
        - 'completed_jobs_count': Number of entries in completed_jobs list
        - 'failed_jobs_count': Number of entries in failed_jobs list
        - 'resource_usage': Current real-time system resource utilization

Raises:
    RuntimeError: If resource usage collection fails.
    ZeroDivisionError: Should not occur due to built-in division safety checks.

Examples:
    >>> # Get comprehensive performance overview
    >>> stats = await processor.get_processing_statistics()
    >>> print(f"Success rate: {stats['success_rate']:.2%}")
    >>> print(f"Average job time: {stats['average_job_time']:.2f} seconds")
    >>> print(f"Total processed: {stats['total_processed']} documents")
    
    >>> # Monitor system performance
    >>> stats = await processor.get_processing_statistics()
    >>> throughput = stats['total_processed'] / (stats['total_processing_time'] / 3600)
    >>> print(f"Throughput: {throughput:.1f} documents/hour")
    
    >>> # Check processing quality
    >>> stats = await processor.get_processing_statistics()
    >>> if stats['success_rate'] < 0.95:
    ...     print(f"Warning: Low success rate ({stats['success_rate']:.2%})")
    
    >>> # System health check
    >>> stats = await processor.get_processing_statistics()
    >>> memory_usage = stats['resource_usage']['memory_mb']
    >>> if memory_usage > 4000:  # 4GB threshold
    ...     print(f"High memory usage: {memory_usage:.1f} MB")

Notes:
    - Statistics accumulate across all batch operations since initialization
    - Success rate calculation handles zero total jobs gracefully
    - Average job time only includes successfully completed jobs
    - Resource usage data is collected in real-time when method is called
    - All time measurements are in seconds for consistency
    - Method is safe to call frequently for monitoring dashboards
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## list_active_batches

```python
async def list_active_batches(self) -> List[Dict[str, Any]]:
    """
    Retrieve status information for all currently active (incomplete) batch processing operations.

This method provides a comprehensive overview of all batch operations that are
currently in progress, including detailed status metrics and resource usage for each.
It filters out completed batches and returns only those with pending or processing jobs,
making it ideal for monitoring dashboards and system administration.

Returns:
    List[Dict[str, Any]]: List of status dictionaries for active batches.
        Each dictionary contains the same information as get_batch_status()
        including job counts, timing metrics, and real-time resource usage.
        Empty list if no batches are currently active.
        Dictionary structure per batch:
        - 'batch_id': Unique batch identifier
        - 'total_jobs': Total number of PDF documents in batch
        - 'completed_jobs': Number of successfully processed documents
        - 'failed_jobs': Number of documents that failed processing
        - 'pending_jobs': Number of documents awaiting processing
        - 'processing_jobs': Number of documents currently being processed
        - 'start_time': ISO timestamp when batch started
        - 'total_processing_time': Cumulative processing time
        - 'average_job_time': Average time per completed job
        - 'resource_usage': Current system resource utilization

Raises:
    RuntimeError: If system resource monitoring fails for any batch.
    MemoryError: If system runs out of memory while collecting resource data.

Examples:
    >>> # Monitor all active batches
    >>> active_batches = await processor.list_active_batches()
    >>> for batch in active_batches:
    ...     progress = batch['completed_jobs'] / batch['total_jobs']
    ...     print(f"Batch {batch['batch_id']}: {progress:.1%} complete")
    
    >>> # Check system load across all batches
    >>> batches = await processor.list_active_batches()
    >>> total_jobs = sum(b['total_jobs'] for b in batches)
    >>> total_completed = sum(b['completed_jobs'] for b in batches)
    >>> print(f"System progress: {total_completed}/{total_jobs} jobs")
    
    >>> # Find oldest running batch
    >>> if active_batches:
    ...     oldest = min(active_batches, key=lambda b: b['start_time'])
    ...     print(f"Oldest batch: {oldest['batch_id']} started {oldest['start_time']}")

Notes:
    - Only returns batches with incomplete jobs (completed + failed < total_jobs)
    - Completed batches are automatically excluded from results
    - Resource usage is collected in real-time for each active batch
    - Method is efficient for frequent polling in monitoring systems
    - Results are ordered by batch_id for consistent iteration
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## process_batch

```python
async def process_batch(self, pdf_paths: List[Union[str, Path]], batch_metadata: Optional[Dict[str, Any]] = None, priority: int = 5, callback: Optional[Callable] = None) -> str:
    """
    Process a batch of PDF documents through the complete processing pipeline concurrently.

This method orchestrates the end-to-end processing of multiple PDF documents including
PDF decomposition, OCR processing, LLM optimization, entity extraction, knowledge graph
creation, and IPLD storage. It manages job creation, worker coordination, progress tracking,
and provides real-time status updates through optional callbacks. Each document is processed
independently with fault isolation to ensure batch resilience.

Args:
    pdf_paths (List[Union[str, Path]]): List of file paths to PDF documents for processing.
        Each path must point to a valid, readable PDF file. Both string paths and
        Path objects are supported. Empty list will return immediately.
    batch_metadata (Optional[Dict[str, Any]], optional): Additional metadata for the
        entire batch operation. Defaults to None. Common keys include:
        - 'project_id': Project identifier for organizational tracking
        - 'user_id': User who initiated the batch
        - 'tags': List of tags for categorization
        - 'description': Human-readable batch description
    priority (int, optional): Processing priority level from 1-10 where 10 is highest.
        Defaults to 5. Higher priority jobs are processed before lower priority ones
        within the same batch. Used for job scheduling and resource allocation.
    callback (Optional[Callable], optional): Function called periodically with batch
        status updates. Defaults to None. Can be sync or async function accepting
        BatchStatus parameter. Called approximately every 5 seconds during processing.

Returns:
    str: Unique batch identifier for tracking progress and retrieving results.
        Format: 'batch_{8_character_hex}'. Use with get_batch_status() and
        export_batch_results() methods.

Raises:
    FileNotFoundError: If any PDF file in pdf_paths does not exist or is not readable.
    ValueError: If pdf_paths is empty, priority is outside 1-10 range, or invalid paths provided.
    PermissionError: If insufficient permissions to read PDF files or write to storage.
    RuntimeError: If processing system is not properly initialized or resources unavailable.
    TypeError: If callback is provided but is not callable or has incorrect signature.

Examples:
    >>> # Basic batch processing
    >>> batch_id = await processor.process_batch([
    ...     '/docs/report1.pdf',
    ...     '/docs/report2.pdf',
    ...     '/docs/report3.pdf'
    ... ])
    
    >>> # High-priority batch with metadata and progress tracking
    >>> def progress_update(status):
    ...     print(f"Progress: {status.completed_jobs}/{status.total_jobs}")
    
    >>> batch_id = await processor.process_batch(
    ...     pdf_paths=[Path('/research/paper1.pdf'), Path('/research/paper2.pdf')],
    ...     batch_metadata={
    ...         'project_id': 'research_2024',
    ...         'user_id': 'researcher123',
    ...         'description': 'Academic paper analysis batch'
    ...     },
    ...     priority=8,
    ...     callback=progress_update
    ... )
    
    >>> # Async progress callback
    >>> async def async_progress(status):
    ...     await save_progress_to_db(status)
    
    >>> batch_id = await processor.process_batch(
    ...     pdf_paths=pdf_file_list,
    ...     callback=async_progress
    ... )

Notes:
    - Each PDF is processed independently with fault isolation
    - Failed documents don't affect processing of other documents in the batch
    - Progress callbacks enable real-time monitoring and user feedback
    - Batch metadata is included in audit logs and available in results
    - Worker threads are automatically started if not already running
    - Large batches are automatically load-balanced across available workers
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor

## process_directory_batch

```python
async def process_directory_batch(directory_path: str, batch_processor: BatchProcessor, file_pattern: str = "*.pdf", max_files: Optional[int] = None) -> str:
    """
    Discover and process all PDF files in a directory as a single batch operation with automatic file discovery.

This utility function provides convenient batch processing for entire directories containing
PDF documents. It automatically discovers matching files, validates their existence,
and submits them for processing through the provided BatchProcessor instance. This is
ideal for processing document archives, research paper collections, or any organized
directory of PDF documents.

The function supports flexible file filtering through glob patterns and optional limits
on the number of files processed. It provides comprehensive error handling for common
directory processing scenarios including missing directories, permission issues, and
empty result sets.

Args:
    directory_path (str): Absolute or relative path to directory containing PDF files.
        Directory must exist and be readable. Supports both forward and backward
        slashes for cross-platform compatibility.
    batch_processor (BatchProcessor): Initialized BatchProcessor instance that will
        handle the actual document processing. Must be properly configured with
        storage, monitoring, and other required components.
    file_pattern (str, optional): Glob pattern for file matching. Defaults to "*.pdf".
        Supports standard glob syntax including wildcards and character classes.
        Examples: "*.pdf", "report_*.pdf", "*[0-9].pdf"
    max_files (Optional[int], optional): Maximum number of files to process from
        the discovered set. Defaults to None (process all matching files).
        Files are selected in the order returned by directory listing.

Returns:
    str: Unique batch identifier for tracking processing progress. Use with
        batch_processor.get_batch_status() and related methods to monitor
        the batch processing operation.

Raises:
    ValueError: If directory_path does not exist, no matching PDF files found,
        max_files is negative, or directory_path is empty.
    PermissionError: If insufficient permissions to read directory or PDF files.
    OSError: If directory access fails due to system limitations or network issues.
    TypeError: If batch_processor is not a valid BatchProcessor instance.

Examples:
    >>> # Process all PDFs in a research directory
    >>> processor = BatchProcessor(max_workers=8)
    >>> batch_id = await process_directory_batch(
    ...     directory_path='/research/papers',
    ...     batch_processor=processor
    ... )
    >>> print(f"Processing batch: {batch_id}")
    
    >>> # Process only report PDFs with file limit
    >>> batch_id = await process_directory_batch(
    ...     directory_path='/documents/reports',
    ...     batch_processor=processor,
    ...     file_pattern='report_*.pdf',
    ...     max_files=50
    ... )
    
    >>> # Process with specific pattern and monitoring
    >>> def progress_callback(status):
    ...     print(f"Processed {status.completed_jobs}/{status.total_jobs} files")
    >>> 
    >>> processor = BatchProcessor(enable_monitoring=True)
    >>> batch_id = await process_directory_batch(
    ...     directory_path=Path('/archives/documents'),
    ...     batch_processor=processor,
    ...     file_pattern='*.pdf'
    ... )

Notes:
    - File discovery uses pathlib.Path.glob() for cross-platform compatibility
    - Files are processed in the order returned by directory listing
    - Large directories may take time for initial file discovery
    - Batch metadata includes source directory and discovery information
    - Function validates directory existence before file discovery
    - max_files limit is applied after pattern matching for predictable results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## stop_processing

```python
async def stop_processing(self, timeout: float = 30.0):
    """
    Gracefully stop all batch processing operations and shutdown worker threads.

This method provides controlled shutdown of the entire batch processing system
including worker threads, process pools, and resource cleanup. It signals workers
to complete their current jobs and stop processing new ones, then waits for
graceful shutdown within the specified timeout period.

The shutdown process ensures that currently processing jobs complete properly
to maintain data consistency and prevent corruption. If workers don't complete
within the timeout, they are forcefully terminated.

Args:
    timeout (float, optional): Maximum time in seconds to wait for workers
        to complete current jobs and shutdown gracefully. Defaults to 30.0.
        Longer timeouts allow more jobs to complete but delay shutdown.

Raises:
    ValueError: If timeout is negative or zero.
    RuntimeError: If shutdown process encounters system-level errors.

Side Effects:
    - Sets stop_event to signal worker threads to terminate
    - Adds None jobs to queue to wake up waiting workers
    - Waits for all worker threads to complete with timeout
    - Shuts down ProcessPoolExecutor for CPU-intensive tasks
    - Clears worker thread list
    - Sets is_processing flag to False
    - Logs shutdown progress and completion

Examples:
    >>> # Graceful shutdown with default timeout
    >>> await processor.stop_processing()
    
    >>> # Quick shutdown for emergency situations
    >>> await processor.stop_processing(timeout=5.0)
    
    >>> # Patient shutdown allowing long jobs to complete
    >>> await processor.stop_processing(timeout=120.0)
    
    >>> # Shutdown and restart with new configuration
    >>> await processor.stop_processing()
    >>> processor = BatchProcessor(max_workers=16)

Notes:
    - Currently processing jobs are allowed to complete within timeout
    - Workers that don't respond within timeout are forcefully terminated
    - Process pool shutdown waits for CPU-intensive tasks to complete
    - Method is idempotent - safe to call multiple times
    - System can be restarted by calling process_batch after shutdown
    - All pending jobs remain in queue and can be processed after restart
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchProcessor
