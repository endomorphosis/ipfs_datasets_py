import os
from typing import Any, Callable, Optional


from logger import logger
from batch_processor import BatchResult, make_batch_processor
from utils.common.dependencies.tqdm import Tqdm
from utils.main_.progress_callback import progress_callback


get_progress_bar: Callable = Tqdm.get_progress_bar
cleanup_progress_bar: Callable = Tqdm.cleanup_progress_bar


def _estimate_file_count(dir_path: str, recursive: bool) -> int:
    return sum(
        1 for _ in os.walk(dir_path) for _ in os.listdir(_[0])
    ) if recursive else len(os.listdir(dir_path))


def process_directory(
    dir_path: str, 
    output_dir: Optional[str] = None, 
    options: Optional[dict[str, Any]] = None,
    show_progress: bool = True,
    recursive: bool = False
) -> BatchResult:
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
    batch_processor = make_batch_processor()

    # Configure batch processor
    batch_processor.set_max_batch_size(options.get('max_batch_size', 100))
    batch_processor.set_continue_on_error(options.get('continue_on_error', True))
    batch_processor.set_max_threads(options.get('max_threads', 4) if options.get('parallel', False) else 1)
    
    # Create progress callback
    pbar = None
    callback = None
    
    if show_progress:
        def _callback(current, total, current_file):
            progress_callback(current, total, current_file, pbar)
        callback = _callback
    
    # Process batch
    try:
        # Start processing
        logger.info(f"Processing directory: {dir_path}")
        
        # Setup progress bar if requested
        estimated_file_count = _estimate_file_count(dir_path, recursive)
        if show_progress and estimated_file_count > 0:
            pbar = get_progress_bar(total=estimated_file_count, unit="file")
        
        # Process files
        result = batch_processor.process_batch(
            file_paths=dir_path, 
            output_dir=output_dir,
            options=options,
            progress_callback=callback
        )
        
        return result
    
    finally:
        # Clean up progress bar
        if pbar:
            pbar.close()