"""
GitHub API Counter Helper Module

This module provides drop-in replacements for subprocess calls to track GitHub API usage.

Usage in existing scripts:
    # Instead of:
    # import subprocess
    # result = subprocess.run(['gh', 'pr', 'list'], ...)
    
    # Use:
    from github_api_counter_helper import tracked_subprocess
    result = tracked_subprocess.run(['gh', 'pr', 'list'], ...)
    
    # Or use the context manager:
    from github_api_counter_helper import get_counter
    with get_counter() as counter:
        counter.run_gh_command(['gh', 'pr', 'list'])
"""

import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

# Import the main counter
try:
    from .github_api_counter import GitHubAPICounter
except ImportError:
    # Try absolute import
    try:
        from github_api_counter import GitHubAPICounter
    except ImportError:
        # Fallback: counter not available
        GitHubAPICounter = None


# Global counter instance
_global_counter: Optional[GitHubAPICounter] = None


def get_counter() -> Optional[GitHubAPICounter]:
    """Get or create the global counter instance."""
    global _global_counter
    if _global_counter is None and GitHubAPICounter is not None:
        _global_counter = GitHubAPICounter()
    return _global_counter


def save_metrics():
    """Save metrics from the global counter."""
    counter = get_counter()
    if counter:
        counter.save_metrics()


class TrackedSubprocess:
    """
    Drop-in replacement for subprocess that tracks GitHub API calls.
    
    Usage:
        tracked_subprocess.run(['gh', 'pr', 'list'])
    """
    
    @staticmethod
    def run(args: List[str], **kwargs) -> subprocess.CompletedProcess:
        """
        Run a command, tracking it if it's a GitHub CLI command.
        
        Args:
            args: Command and arguments
            **kwargs: Additional arguments for subprocess.run
        
        Returns:
            CompletedProcess instance
        """
        # Check if this is a gh command
        if len(args) > 0 and args[0] in ['gh', 'gh.exe']:
            counter = get_counter()
            if counter:
                # Use the counter to run the command
                return counter.run_gh_command(args, **kwargs)
        
        # Not a gh command or counter not available, run normally
        return subprocess.run(args, **kwargs)
    
    @staticmethod
    def check_output(args: List[str], **kwargs) -> bytes:
        """
        Run command and return output, tracking if it's a GitHub CLI command.
        
        Args:
            args: Command and arguments
            **kwargs: Additional arguments for subprocess.check_output
        
        Returns:
            Command output as bytes
        """
        # For gh commands, use run() and extract stdout
        if len(args) > 0 and args[0] in ['gh', 'gh.exe']:
            counter = get_counter()
            if counter:
                # Ensure capture_output or stdout is set
                kwargs['capture_output'] = True
                kwargs.pop('stdout', None)  # Remove stdout if present
                kwargs.pop('stderr', None)  # Remove stderr if present
                result = counter.run_gh_command(args, **kwargs)
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode, args, result.stdout, result.stderr
                    )
                return result.stdout.encode() if isinstance(result.stdout, str) else result.stdout
        
        return subprocess.check_output(args, **kwargs)
    
    @staticmethod
    def check_call(args: List[str], **kwargs) -> int:
        """
        Run command and check return code, tracking if it's a GitHub CLI command.
        
        Args:
            args: Command and arguments
            **kwargs: Additional arguments for subprocess.check_call
        
        Returns:
            Return code (always 0 for successful calls)
        """
        result = TrackedSubprocess.run(args, check=True, **kwargs)
        return result.returncode


# Create a module-level instance for convenience
tracked_subprocess = TrackedSubprocess()


# Monkey-patch helper
def patch_subprocess():
    """
    Monkey-patch subprocess module to automatically track GitHub CLI calls.
    
    Usage:
        from github_api_counter_helper import patch_subprocess
        patch_subprocess()
        
        # Now all subprocess calls are tracked
        import subprocess
        subprocess.run(['gh', 'pr', 'list'])
    """
    import subprocess as sp
    
    # Save original functions
    original_run = sp.run
    original_check_output = sp.check_output
    original_check_call = sp.check_call
    
    def patched_run(args, **kwargs):
        if len(args) > 0 and args[0] in ['gh', 'gh.exe']:
            return tracked_subprocess.run(args, **kwargs)
        return original_run(args, **kwargs)
    
    def patched_check_output(args, **kwargs):
        if len(args) > 0 and args[0] in ['gh', 'gh.exe']:
            return tracked_subprocess.check_output(args, **kwargs)
        return original_check_output(args, **kwargs)
    
    def patched_check_call(args, **kwargs):
        if len(args) > 0 and args[0] in ['gh', 'gh.exe']:
            return tracked_subprocess.check_call(args, **kwargs)
        return original_check_call(args, **kwargs)
    
    sp.run = patched_run
    sp.check_output = patched_check_output
    sp.check_call = patched_check_call


# Auto-save metrics on exit
import atexit

def _auto_save_on_exit():
    """Automatically save metrics when the script exits."""
    counter = get_counter()
    if counter and counter.get_total_calls() > 0:
        counter.save_metrics()

atexit.register(_auto_save_on_exit)
