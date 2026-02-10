# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_batch.py'

Files last updated: 1751408933.7564564

Stub file last updated: 2025-07-07 01:10:14

## bounded_process

```python
async def bounded_process(file_path: str) -> Dict[str, Any]:
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ffmpeg_batch_process

```python
async def ffmpeg_batch_process(input_files: Union[List[str], Dict[str, Any]], output_directory: str, operation: str = "convert", operation_params: Optional[Dict[str, Any]] = None, max_parallel: int = 2, save_progress: bool = True, resume_from_checkpoint: bool = True, timeout_per_file: int = 600) -> Dict[str, Any]:
    """
    Process multiple media files in batch using FFmpeg operations.

This tool supports comprehensive batch processing including:
- Parallel processing of multiple files
- Progress tracking and resumption
- Queue management and error handling
- Support for all FFmpeg operations (convert, filter, etc.)
- Checkpoint saving for long-running jobs

Args:
    input_files: List of input file paths or dataset containing file information
    output_directory: Directory where processed files will be saved
    operation: Type of operation ('convert', 'filter', 'extract_audio', etc.)
    operation_params: Parameters for the operation (codecs, filters, etc.)
    max_parallel: Maximum number of parallel processes
    save_progress: Whether to save progress to disk for resumption
    resume_from_checkpoint: Whether to resume from previous checkpoint
    timeout_per_file: Maximum processing time per file in seconds
    
Returns:
    Dict containing:
    - status: "success", "partial", or "error"
    - total_files: Total number of files to process
    - processed_files: Number of successfully processed files
    - failed_files: Number of failed files
    - skipped_files: Number of skipped files (if resuming)
    - results: List of individual file processing results
    - duration: Total processing duration in seconds
    - average_time_per_file: Average processing time per file
    - checkpoint_file: Path to checkpoint file (if saved)
    - message: Summary message
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_batch_status

```python
async def get_batch_status(checkpoint_file: str) -> Dict[str, Any]:
    """
    Get status of a batch processing job from checkpoint file.

Args:
    checkpoint_file: Path to checkpoint file
    
Returns:
    Dict containing batch job status information
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## main

```python
async def main() -> Dict[str, Any]:
    """
    Main function for MCP tool registration.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## process_single_file

```python
async def process_single_file(file_path: str) -> Dict[str, Any]:
    """
    Process a single file with the specified operation.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
