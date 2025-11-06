#!/usr/bin/env python3
"""
Docker container error wrapper.

This script wraps Python execution in the Docker container to catch and report
runtime errors to GitHub issues.
"""
import os
import sys
import traceback


def main():
    """Run Python command with error reporting."""
    # Check if error reporting is enabled
    error_reporting_enabled = os.getenv('ERROR_REPORTING_ENABLED', 'true').lower() == 'true'
    
    if not error_reporting_enabled:
        # Just run the command without error reporting
        import subprocess
        sys.exit(subprocess.call(sys.argv[1:]))
    
    # Import error reporting
    try:
        from ipfs_datasets_py.error_reporting import error_reporter, get_recent_logs
    except ImportError:
        print("Warning: Error reporting module not available", file=sys.stderr)
        import subprocess
        sys.exit(subprocess.call(sys.argv[1:]))
    
    # Get command to execute
    if len(sys.argv) < 2:
        print("Usage: docker_error_wrapper.py <command> [args...]", file=sys.stderr)
        sys.exit(1)
    
    cmd = sys.argv[1:]
    
    try:
        # Execute the command
        import subprocess
        result = subprocess.run(cmd, check=False)
        sys.exit(result.returncode)
    
    except Exception as e:
        # Report error
        try:
            logs = get_recent_logs()
            error_reporter.report_error(
                e,
                source=f"Docker Container: {' '.join(cmd)}",
                additional_info=f"Command: {' '.join(cmd)}\nWorking Directory: {os.getcwd()}",
                logs=logs,
            )
        except Exception as report_err:
            print(f"Failed to report error: {report_err}", file=sys.stderr)
        
        # Print error and exit
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
