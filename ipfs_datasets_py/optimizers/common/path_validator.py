"""Path validation utilities for CLI file inputs.

This module provides security validation for all file paths provided via CLI arguments,
preventing path traversal attacks, symlink exploits, and access to sensitive system files.

Security Features:
    - Path traversal prevention (../, ../../, etc.)
    - Absolute path validation
    - Symlink resolution and validation
    - Sensitive path blocking (/etc, /sys, /proc, etc.)
    - Directory whitelisting
    - Extension validation
    - Size limit enforcement

Usage:
    >>> from ipfs_datasets_py.optimizers.common.path_validator import validate_input_path
    >>> 
    >>> # Validate input file
    >>> safe_path = validate_input_path(
    ...     user_path="data/input.json",
    ...     base_dir="/home/user/project",
    ...     must_exist=True,
    ...     allowed_extensions=[".json", ".txt"]
    ... )
    >>> 
    >>> # Validate output file
    >>> from ipfs_datasets_py.optimizers.common.path_validator import validate_output_path
    >>> safe_path = validate_output_path(
    ...     user_path="results/output.json",
    ...     base_dir="/home/user/project",
    ...     allowed_extensions=[".json"]
    ... )

References:
    - OWASP Path Traversal: https://owasp.org/www-community/attacks/Path_Traversal
    - CWE-22: Improper Limitation of a Pathname to a Restricted Directory
    - Python pathlib security considerations
"""

import os
import pathlib
from pathlib import Path
from typing import List, Optional, Set, Union


# Sensitive system paths that should never be accessible
BLOCKED_PATHS = {
    "/etc",
    "/sys",
    "/proc",
    "/dev",
    "/boot",
    "/root",
    "/var/run",
    "/var/log",
    "/usr/bin",
    "/usr/sbin",
    "/sbin",
    "/bin",
}

# Common sensitive filenames
BLOCKED_FILENAMES = {
    "passwd",
    "shadow",
    "sudoers",
    "hosts",
    "ssh_config",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".env",
    ".git-credentials",
}


class PathValidationError(ValueError):
    """Raised when a path fails security validation."""
    pass


def validate_input_path(
    user_path: Union[str, Path],
    base_dir: Optional[Union[str, Path]] = None,
    must_exist: bool = True,
    allowed_extensions: Optional[List[str]] = None,
    max_size_bytes: Optional[int] = None,
    follow_symlinks: bool = False,
) -> Path:
    """Validate an input file path against security threats.
    
    Args:
        user_path: User-provided path (relative or absolute)
        base_dir: Base directory to restrict paths to (default: cwd)
        must_exist: Whether file must exist
        allowed_extensions: List of allowed extensions (e.g., [".json", ".txt"])
        max_size_bytes: Maximum allowed file size in bytes
        follow_symlinks: Whether to allow symlinks (default: False for security)
        
    Returns:
        Validated, resolved pathlib.Path object
        
    Raises:
        PathValidationError: If path fails any security validation
        
    Example:
        >>> safe_path = validate_input_path(
        ...     "data/input.json",
        ...     base_dir="/home/user/project",
        ...     must_exist=True,
        ...     allowed_extensions=[".json"]
        ... )
    """
    if not user_path:
        raise PathValidationError("Path cannot be empty")
    
    # Convert to Path object
    path = Path(user_path)
    
    # Set default base_dir to current working directory
    if base_dir is None:
        base_dir = Path.cwd()
    else:
        base_dir = Path(base_dir).resolve()
    
    # Resolve the path (follows symlinks and makes absolute)
    # If path is relative, resolve it relative to base_dir first
    try:
        if not path.is_absolute():
            resolved_path = (base_dir / path).resolve()
        else:
            resolved_path = path.resolve()
    except (OSError, RuntimeError) as e:
        raise PathValidationError(f"Cannot resolve path '{user_path}': {e}")
    
    # Check symlinks (before resolving, since resolve() follows symlinks)
    # Need to check the actual path before it was resolved
    actual_path = (base_dir / path) if not path.is_absolute() else path
    if not follow_symlinks and actual_path.exists() and actual_path.is_symlink():
        raise PathValidationError(f"Symlinks not allowed: {user_path}")
    
    # Check for path traversal attempts (should not escape base_dir)
    if not _is_subpath(resolved_path, base_dir):
        raise PathValidationError(
            f"Path '{user_path}' attempts to escape base directory '{base_dir}'"
        )
    
    # Check for blocked system paths
    _check_blocked_paths(resolved_path)
    
    # Check for blocked filenames
    _check_blocked_filenames(resolved_path)
    
    # Check existence
    if must_exist and not resolved_path.exists():
        raise PathValidationError(f"Path does not exist: {user_path}")
    
    # Check if it's a file (not directory)
    if must_exist and resolved_path.exists() and not resolved_path.is_file():
        raise PathValidationError(f"Path is not a file: {user_path}")
    
    # Check file extension
    if allowed_extensions is not None:
        if resolved_path.suffix.lower() not in [ext.lower() for ext in allowed_extensions]:
            raise PathValidationError(
                f"Invalid file extension '{resolved_path.suffix}'. "
                f"Allowed: {allowed_extensions}"
            )
    
    # Check file size
    if max_size_bytes is not None and resolved_path.exists():
        size = resolved_path.stat().st_size
        if size > max_size_bytes:
            raise PathValidationError(
                f"File too large: {size} bytes (max: {max_size_bytes} bytes)"
            )
    
    return resolved_path


def validate_output_path(
    user_path: Union[str, Path],
    base_dir: Optional[Union[str, Path]] = None,
    allowed_extensions: Optional[List[str]] = None,
    allow_overwrite: bool = False,
) -> Path:
    """Validate an output file path against security threats.
    
    Args:
        user_path: User-provided path (relative or absolute)
        base_dir: Base directory to restrict paths to (default: cwd)
        allowed_extensions: List of allowed extensions (e.g., [".json", ".txt"])
        allow_overwrite: Whether to allow overwriting existing files
        
    Returns:
        Validated, resolved pathlib.Path object
        
    Raises:
        PathValidationError: If path fails any security validation
        
    Example:
        >>> safe_path = validate_output_path(
        ...     "results/output.json",
        ...     base_dir="/home/user/project",
        ...     allowed_extensions=[".json"],
        ...     allow_overwrite=True
        ... )
    """
    if not user_path:
        raise PathValidationError("Path cannot be empty")
    
    # Convert to Path object
    path = Path(user_path)
    
    # Set default base_dir to current working directory
    if base_dir is None:
        base_dir = Path.cwd()
    else:
        base_dir = Path(base_dir).resolve()
    
    # Resolve the path (but don't require it to exist)
    # If path is relative, resolve it relative to base_dir first
    try:
        if not path.is_absolute():
            # Relative path: resolve relative to base_dir
            full_path = base_dir / path
            if full_path.exists():
                resolved_path = full_path.resolve()
            else:
                # For non-existent paths, normalize using resolve(strict=False)
                # This resolves ../ and ./ without requiring the file to exist
                resolved_path = full_path.resolve(strict=False)
        else:
            # Absolute path
            if path.exists():
                resolved_path = path.resolve()
            else:
                # Normalize using resolve(strict=False)
                resolved_path = path.resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise PathValidationError(f"Cannot resolve path '{user_path}': {e}")
    
    # Check for path traversal attempts
    if not _is_subpath(resolved_path, base_dir):
        raise PathValidationError(
            f"Path '{user_path}' attempts to escape base directory '{base_dir}'"
        )
    
    # Check for blocked system paths
    _check_blocked_paths(resolved_path)
    
    # Check for blocked filenames
    _check_blocked_filenames(resolved_path)
    
    # Check if file already exists (overwrite protection)
    if not allow_overwrite and resolved_path.exists():
        raise PathValidationError(
            f"Output file already exists (use --force to overwrite): {user_path}"
        )
    
    # Check file extension
    if allowed_extensions is not None:
        if resolved_path.suffix.lower() not in [ext.lower() for ext in allowed_extensions]:
            raise PathValidationError(
                f"Invalid file extension '{resolved_path.suffix}'. "
                f"Allowed: {allowed_extensions}"
            )
    
    # Ensure parent directory is writable
    parent_dir = resolved_path.parent
    if parent_dir.exists() and not os.access(parent_dir, os.W_OK):
        raise PathValidationError(f"Parent directory not writable: {parent_dir}")
    
    return resolved_path


def validate_directory_path(
    user_path: Union[str, Path],
    base_dir: Optional[Union[str, Path]] = None,
    must_exist: bool = True,
    must_be_empty: bool = False,
) -> Path:
    """Validate a directory path against security threats.
    
    Args:
        user_path: User-provided path (relative or absolute)
        base_dir: Base directory to restrict paths to (default: cwd)
        must_exist: Whether directory must exist
        must_be_empty: Whether directory must be empty (if it exists)
        
    Returns:
        Validated, resolved pathlib.Path object
        
    Raises:
        PathValidationError: If path fails any security validation
        
    Example:
        >>> safe_dir = validate_directory_path(
        ...     "data/inputs",
        ...     base_dir="/home/user/project",
        ...     must_exist=True
        ... )
    """
    if not user_path:
        raise PathValidationError("Path cannot be empty")
    
    # Convert to Path object
    path = Path(user_path)
    
    # Set default base_dir to current working directory
    if base_dir is None:
        base_dir = Path.cwd()
    else:
        base_dir = Path(base_dir).resolve()
    
    # Resolve the path
    # If path is relative, resolve it relative to base_dir first
    try:
        if not path.is_absolute():
            full_path = base_dir / path
            resolved_path = full_path.resolve() if full_path.exists() else full_path
        else:
            resolved_path = path.resolve() if path.exists() else path
    except (OSError, RuntimeError) as e:
        raise PathValidationError(f"Cannot resolve path '{user_path}': {e}")
    
    # Check for path traversal attempts
    if not _is_subpath(resolved_path, base_dir):
        raise PathValidationError(
            f"Path '{user_path}' attempts to escape base directory '{base_dir}'"
        )
    
    # Check for blocked system paths
    _check_blocked_paths(resolved_path)
    
    # Check existence
    if must_exist and not resolved_path.exists():
        raise PathValidationError(f"Directory does not exist: {user_path}")
    
    # Check if it's a directory (not file)
    if must_exist and resolved_path.exists() and not resolved_path.is_dir():
        raise PathValidationError(f"Path is not a directory: {user_path}")
    
    # Check if empty
    if must_be_empty and resolved_path.exists() and list(resolved_path.iterdir()):
        raise PathValidationError(f"Directory is not empty: {user_path}")
    
    return resolved_path


def _is_subpath(path: Path, base: Path) -> bool:
    """Check if path is a subpath of base directory.
    
    Args:
        path: Path to check
        base: Base directory
        
    Returns:
        True if path is under base, False otherwise
    """
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _check_blocked_paths(path: Path) -> None:
    """Check if path starts with any blocked system path.
    
    Args:
        path: Path to check
        
    Raises:
        PathValidationError: If path is in a blocked location
    """
    path_str = str(path)
    for blocked in BLOCKED_PATHS:
        if path_str.startswith(blocked):
            raise PathValidationError(
                f"Access to system path not allowed: {blocked}"
            )


def _check_blocked_filenames(path: Path) -> None:
    """Check if filename matches any blocked sensitive filename.
    
    Args:
        path: Path to check
        
    Raises:
        PathValidationError: If filename is blocked
    """
    filename = path.name.lower()
    for blocked in BLOCKED_FILENAMES:
        if blocked in filename:
            raise PathValidationError(
                f"Access to sensitive file not allowed: {blocked}"
            )


def safe_open(
    path: Union[str, Path],
    mode: str = 'r',
    **kwargs
) -> 'IOBase':
    """Safe wrapper around open() with path validation.
    
    Args:
        path: File path to open
        mode: File mode ('r', 'w', 'a', etc.)
        **kwargs: Additional arguments passed to open()
        
    Returns:
        File handle
        
    Raises:
        PathValidationError: If path fails security validation
        
    Example:
        >>> with safe_open("data/input.json", "r") as f:
        ...     data = json.load(f)
    """
    # Determine if reading or writing
    is_write = any(m in mode for m in ['w', 'a', 'x'])
    
    # Validate path
    if is_write:
        validated_path = validate_output_path(
            path,
            allow_overwrite=('w' in mode or 'a' in mode)
        )
    else:
        validated_path = validate_input_path(path, must_exist=True)
    
    # Open file
    return open(validated_path, mode, **kwargs)
