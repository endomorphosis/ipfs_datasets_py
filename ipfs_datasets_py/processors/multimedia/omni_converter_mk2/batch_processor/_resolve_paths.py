import glob
import os


from types_ import Logger, Generator


def _resolve_path(str_path: str, logger: Logger)  -> Generator[str, None, None]:
    """Generator that yields resolved file paths."""
    # Check if path contains glob patterns
    if '*' in str_path or '?' in str_path or '[' in str_path:
        # Handle glob patterns
        glob_matches = glob.glob(str_path, recursive=True)
        for match in glob_matches:
            if os.path.isfile(match):
                yield os.path.abspath(match)

    elif os.path.isdir(str_path):
        # Recursively find files in directory
        for root, _, files in os.walk(str_path):
            for f in files:
                file_path = os.path.join(root, f)
                yield os.path.abspath(file_path)
    else:
        # Handle individual files (including symlinks)
        abs_path = os.path.abspath(str_path)

        # Resolve symlinks if present
        if os.path.islink(str_path):
            abs_path = os.path.realpath(str_path)

        # Check if file exists before adding
        if os.path.exists(abs_path):
            yield abs_path
        else:
            logger.warning(f"Path not found: {str_path}")


def resolve_paths(file_paths: list[str] | str, logger: Logger) -> list[str]:
    """Resolve file paths, expanding directories if necessary.
    
    Args:
        file_paths: list of file paths or a directory path.
        
    Returns:
        List of resolved file paths.
    """
    resolved = []
    
    # Handle input based on type
    if isinstance(file_paths, str):
        # Single path - consume the generator and extend the resolved list
        resolved.extend(_resolve_path(file_paths, logger))
    elif isinstance(file_paths, list):
        # Process each path in the list
        for path in file_paths:
            resolved.extend(_resolve_path(path, logger))
    else:
        raise ValueError("Invalid input type for file_paths. Must be a string or list of strings.")

    return resolved
