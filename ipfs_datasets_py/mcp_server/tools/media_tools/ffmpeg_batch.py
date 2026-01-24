# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_batch.py
"""
FFmpeg batch processing tool for the MCP server.

This tool provides batch processing capabilities for multiple media files using FFmpeg,
supporting parallel processing, queue management, and progress tracking.
"""
import anyio
import json
from typing import Dict, Any, Optional, Union, List
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ipfs_datasets_py.mcp_server.logger import logger
from .ffmpeg_utils import ffmpeg_utils, FFmpegError

async def ffmpeg_batch_process(
    input_files: Union[List[str], Dict[str, Any]],
    output_directory: str,
    operation: str = "convert",
    operation_params: Optional[Dict[str, Any]] = None,
    max_parallel: int = 2,
    save_progress: bool = True,
    resume_from_checkpoint: bool = True,
    timeout_per_file: int = 600
) -> Dict[str, Any]:
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
    try:
        start_time = time.time()
        
        # Handle different input types
        if isinstance(input_files, dict):
            # Extract file paths from dataset
            if "files" in input_files:
                file_list = input_files["files"]
            elif "file_paths" in input_files:
                file_list = input_files["file_paths"]
            elif isinstance(input_files.get("data"), list):
                file_list = input_files["data"]
            else:
                return {
                    "status": "error",
                    "error": "Invalid input: dataset must contain 'files', 'file_paths', or 'data' field",
                    "input_files": input_files,
                    "output_directory": output_directory
                }
        else:
            file_list = input_files
        
        # Validate input files list
        if not isinstance(file_list, list) or len(file_list) == 0:
            return {
                "status": "error",
                "error": "Input must be a non-empty list of file paths",
                "input_files": input_files,
                "output_directory": output_directory
            }
        
        # Create output directory if it doesn't exist
        output_path = Path(output_directory)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Set default operation parameters
        if operation_params is None:
            operation_params = {}
        
        # Checkpoint file for progress saving
        checkpoint_file = output_path / f"batch_progress_{int(time.time())}.json"
        
        # Load previous checkpoint if resuming
        processed_files_set = set()
        if resume_from_checkpoint and save_progress:
            checkpoint_pattern = output_path.glob("batch_progress_*.json")
            latest_checkpoint = None
            latest_time = 0
            
            for cp_file in checkpoint_pattern:
                if cp_file.stat().st_mtime > latest_time:
                    latest_time = cp_file.stat().st_mtime
                    latest_checkpoint = cp_file
            
            if latest_checkpoint and latest_checkpoint.exists():
                try:
                    with open(latest_checkpoint, 'r') as f:
                        checkpoint_data = json.load(f)
                    processed_files_set = set(checkpoint_data.get("processed_files", []))
                    logger.info(f"Resuming from checkpoint: {len(processed_files_set)} files already processed")
                except Exception as e:
                    logger.warning(f"Could not load checkpoint: {e}")
        
        # Filter files to process (skip already processed if resuming)
        files_to_process = [f for f in file_list if f not in processed_files_set]
        
        results = []
        processed_count = len(processed_files_set)  # Start with already processed count
        failed_count = 0
        skipped_count = len(processed_files_set)
        
        # Batch processing with parallel execution
        async def process_single_file(file_path: str) -> Dict[str, Any]:
            """Process a single file with the specified operation."""
            try:
                # Validate input file
                if not ffmpeg_utils.validate_input_file(file_path):
                    return {
                        "status": "error",
                        "input_file": file_path,
                        "error": f"File not found or not accessible: {file_path}"
                    }
                
                # Generate output filename
                input_path = Path(file_path)
                output_file = output_path / f"{input_path.stem}_processed{input_path.suffix}"
                
                # Perform the specified operation
                if operation == "convert":
                    from .ffmpeg_convert import ffmpeg_convert
                    result = await ffmpeg_convert(
                        input_file=file_path,
                        output_file=str(output_file),
                        timeout=timeout_per_file,
                        **operation_params
                    )
                elif operation == "filter":
                    from .ffmpeg_filters import ffmpeg_apply_filters
                    result = await ffmpeg_apply_filters(
                        input_file=file_path,
                        output_file=str(output_file),
                        timeout=timeout_per_file,
                        **operation_params
                    )
                elif operation == "extract_audio":
                    from .ffmpeg_convert import ffmpeg_convert
                    audio_params = {
                        "video_codec": None,  # Remove video stream
                        "audio_codec": operation_params.get("audio_codec", "mp3"),
                        **operation_params
                    }
                    # Change extension for audio-only output
                    audio_output = output_path / f"{input_path.stem}.{operation_params.get('audio_codec', 'mp3')}"
                    result = await ffmpeg_convert(
                        input_file=file_path,
                        output_file=str(audio_output),
                        timeout=timeout_per_file,
                        **audio_params
                    )
                else:
                    return {
                        "status": "error",
                        "input_file": file_path,
                        "error": f"Unsupported operation: {operation}"
                    }
                
                # Add file path to result for tracking
                result["input_file"] = file_path
                return result
                
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")
                return {
                    "status": "error",
                    "input_file": file_path,
                    "error": str(e)
                }
        
        # Process files in parallel with limited concurrency
        semaphore = anyio.Semaphore(max_parallel)
        
        async def bounded_process(file_path: str) -> Dict[str, Any]:
            async with semaphore:
                return await process_single_file(file_path)
        
        # Execute batch processing
        logger.info(f"Starting batch processing of {len(files_to_process)} files with {max_parallel} parallel workers")
        
        tasks = [bounded_process(file_path) for file_path in files_to_process]
        
        # Process with progress tracking
        for i, task in enumerate(asyncio.as_completed(tasks)):
            result = await task
            results.append(result)
            
            if result["status"] == "success":
                processed_count += 1
                # Add to processed files set for checkpoint
                processed_files_set.add(result["input_file"])
            else:
                failed_count += 1
            
            # Progress tracking (logged instead of callback)
            # Log progress
            if (i + 1) % 5 == 0 or i == len(tasks) - 1:  # Log every 5 files or on completion
                logger.info(f"Batch progress: {i + 1}/{len(files_to_process)} files processed, {processed_count} succeeded, {failed_count} failed")
            
            # Save checkpoint periodically
            if save_progress and (i + 1) % 10 == 0:  # Save every 10 files
                checkpoint_data = {
                    "total_files": len(file_list),
                    "processed_files": list(processed_files_set),
                    "operation": operation,
                    "operation_params": operation_params,
                    "timestamp": time.time()
                }
                try:
                    with open(checkpoint_file, 'w') as f:
                        json.dump(checkpoint_data, f, indent=2)
                except Exception as e:
                    logger.warning(f"Could not save checkpoint: {e}")
        
        # Calculate final statistics
        end_time = time.time()
        total_duration = end_time - start_time
        
        # Determine overall status
        if failed_count == 0:
            status = "success"
        elif processed_count > 0:
            status = "partial"
        else:
            status = "error"
        
        # Save final checkpoint
        if save_progress:
            final_checkpoint = {
                "total_files": len(file_list),
                "processed_files": list(processed_files_set),
                "operation": operation,
                "operation_params": operation_params,
                "timestamp": time.time(),
                "completed": True
            }
            try:
                with open(checkpoint_file, 'w') as f:
                    json.dump(final_checkpoint, f, indent=2)
            except Exception as e:
                logger.warning(f"Could not save final checkpoint: {e}")
        
        return {
            "status": status,
            "total_files": len(file_list),
            "processed_files": processed_count,
            "failed_files": failed_count,
            "skipped_files": skipped_count,
            "results": results,
            "duration": total_duration,
            "average_time_per_file": total_duration / len(files_to_process) if len(files_to_process) > 0 else 0,
            "checkpoint_file": str(checkpoint_file) if save_progress else None,
            "operation": operation,
            "operation_params": operation_params,
            "message": f"Batch processing completed: {processed_count} success, {failed_count} failed"
        }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_batch_process: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_files": input_files,
            "output_directory": output_directory
        }

async def get_batch_status(checkpoint_file: str) -> Dict[str, Any]:
    """
    Get status of a batch processing job from checkpoint file.
    
    Args:
        checkpoint_file: Path to checkpoint file
        
    Returns:
        Dict containing batch job status information
    """
    try:
        checkpoint_path = Path(checkpoint_file)
        
        if not checkpoint_path.exists():
            return {
                "status": "error",
                "error": f"Checkpoint file not found: {checkpoint_file}"
            }
        
        with open(checkpoint_path, 'r') as f:
            checkpoint_data = json.load(f)
        
        processed_count = len(checkpoint_data.get("processed_files", []))
        total_count = checkpoint_data.get("total_files", 0)
        
        progress_percentage = (processed_count / total_count * 100) if total_count > 0 else 0
        
        return {
            "status": "success",
            "checkpoint_file": checkpoint_file,
            "total_files": total_count,
            "processed_files": processed_count,
            "remaining_files": total_count - processed_count,
            "progress_percentage": progress_percentage,
            "operation": checkpoint_data.get("operation", "unknown"),
            "operation_params": checkpoint_data.get("operation_params", {}),
            "timestamp": checkpoint_data.get("timestamp", 0),
            "completed": checkpoint_data.get("completed", False)
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "checkpoint_file": checkpoint_file
        }

# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "FFmpeg batch processing tool initialized",
        "tool": "ffmpeg_batch_process",
        "description": "Process multiple media files in batch using FFmpeg operations",
        "supported_operations": [
            "convert",
            "filter", 
            "extract_audio",
            "custom"
        ],
        "capabilities": [
            "Parallel processing",
            "Progress tracking",
            "Checkpoint/resume functionality",
            "Error handling and recovery",
            "Customizable operations"
        ]
    }

if __name__ == "__main__":
    # Example usage
    test_files = ["input1.mp4", "input2.mp4", "input3.mp4"]
    test_result = anyio.run(ffmpeg_batch_process(
        input_files=test_files,
        output_directory="./batch_output",
        operation="convert",
        operation_params={
            "video_codec": "libx264",
            "audio_codec": "aac",
            "quality": "medium"
        },
        max_parallel=2
    ))
    print(f"Test result: {test_result}")
