import os
import sys
from typing import Callable, Optional, TypeVar


P = TypeVar('P')


from utils.common.dependencies.tqdm import Tqdm


# Inject tqdm functions for progress bar management
update_progress_bar: Callable = Tqdm.update_progress_bar
set_progress_bar_description : Callable= Tqdm.set_progress_bar_description


def progress_callback(current: int, total: int, current_file: str, pbar: Optional[P] = None) -> None:
    """
    Callback function for progress reporting.

    Args:
        current: Current file number.
        total: Total number of files.
        current_file: Path to the current file being processed.
        pbar: Optional progress bar instance. Current library is tqdm.
    """
    if pbar:
        update_progress_bar(pbar, unit=1)
        set_progress_bar_description(pbar, f"Processing {os.path.basename(current_file)}")
    else:
        # Calculate percentage
        percent = (current / total) * 100 if total > 0 else 0
        # Simple progress output
        sys.stdout.write(f"\rProcessing {current}/{total} files ({percent:.1f}%): {os.path.basename(current_file)}")
        sys.stdout.flush()
