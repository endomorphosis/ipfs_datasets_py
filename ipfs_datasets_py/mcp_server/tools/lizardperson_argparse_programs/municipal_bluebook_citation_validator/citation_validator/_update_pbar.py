
from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.types_ import ProgressBar, Optional

def update_pbar(pbar: 'ProgressBar', by: int = 1) -> Optional['ProgressBar']:
    """
    Update the progress bar with the current progress.

    Args:
        pbar: The progress bar object to update.
        current (int): The current progress value.
        total (int): The total value for the progress bar.
    """
    if pbar is not None:
        pbar.update(by)
        return pbar 
