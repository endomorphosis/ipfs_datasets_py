from contextlib import contextmanager
from typing import Generator


import tqdm


class Tqdm:

    @staticmethod
    def get_progress_bar(total: int, unit: str = "file", desc: str = None) -> tqdm.tqdm:
        return tqdm.tqdm(total=total, unit=unit, desc=desc)

    @staticmethod
    def cleanup_progress_bar(pbar: tqdm.tqdm):
        if pbar is not None and isinstance(pbar, tqdm.tqdm):
            pbar.close()
    
    @staticmethod
    def update_progress_bar(pbar: tqdm.tqdm, unit: int = 1):
        if pbar is not None and isinstance(pbar, tqdm.tqdm):
            pbar.update(unit)

    @staticmethod
    def set_progress_bar_description(pbar: tqdm.tqdm, description: str = None):
        if pbar is not None and isinstance(pbar, tqdm.tqdm):
            if description:
                pbar.set_description(description)

    @contextmanager
    @staticmethod
    def progress_bar(
        total: int,
        unit: str = "file",
        desc: str = None,
    ) -> Generator[None, None, tqdm.tqdm]:
        """
        Context manager for a progress bar.
        
        Args:
            total: Total number of iterations.
            unit: Unit of measurement for the progress bar.
            desc: Description for the progress bar.

        Yields:
            A tqdm progress bar instance.
        """
        pbar = tqdm.tqdm(total=total, unit=unit, desc=desc)
        try:
            yield pbar
        finally:
            pbar.close()
            pbar = None
