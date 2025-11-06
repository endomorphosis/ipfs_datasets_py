#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Error Monitor

This script wraps Docker container entrypoints to monitor for errors
and automatically report them as GitHub issues.
"""

import os
import sys
import subprocess
import signal
import logging
from typing import List, Optional

# Add parent directory to path to import error_reporting
sys.path.insert(0, '/app')

try:
    from ipfs_datasets_py.error_reporting import (
        get_global_error_reporter,
        install_error_handlers
    )
    ERROR_REPORTING_AVAILABLE = True
except ImportError:
    ERROR_REPORTING_AVAILABLE = False
    print("Warning: Error reporting module not available")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DockerErrorMonitor:
    """Monitor and report Docker container errors."""
    
    def __init__(self):
        self.reporter = None
        if ERROR_REPORTING_AVAILABLE:
            # Install global error handlers
            install_error_handlers()
            self.reporter = get_global_error_reporter()
            
            if self.reporter.enabled:
                logger.info("Docker error monitoring enabled")
            else:
                logger.info("Docker error monitoring disabled (set ERROR_REPORTING_ENABLED=true to enable)")
    
    def run_command(self, command: List[str]) -> int:
        """
        Run a command and monitor for errors.
        
        Args:
            command: Command and arguments to run
            
        Returns:
            Exit code of the command
        """
        try:
            logger.info(f"Starting command: {' '.join(command)}")
            
            # Run the command
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Stream output
            exit_code = None
            stderr_buffer = []
            
            # Set up signal handlers to forward signals to child process
            def signal_handler(signum, frame):
                process.send_signal(signum)
            
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
            
            # Read output
            while True:
                # Check if process has finished
                if process.poll() is not None:
                    exit_code = process.returncode
                    break
                
                # Read stderr line by line
                line = process.stderr.readline()
                if line:
                    stderr_buffer.append(line)
                    # Print to actual stderr
                    sys.stderr.write(line)
                    sys.stderr.flush()
                
                # Read stdout line by line
                line = process.stdout.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
            
            # Read any remaining output
            stdout, stderr = process.communicate()
            if stdout:
                sys.stdout.write(stdout)
                sys.stdout.flush()
            if stderr:
                stderr_buffer.append(stderr)
                sys.stderr.write(stderr)
                sys.stderr.flush()
            
            # Check for errors
            if exit_code != 0:
                logger.error(f"Command failed with exit code {exit_code}")
                
                # Report error if enabled
                if self.reporter and self.reporter.enabled:
                    stderr_text = ''.join(stderr_buffer)
                    self._report_docker_error(command, exit_code, stderr_text)
            
            return exit_code
            
        except Exception as e:
            logger.error(f"Error running command: {e}")
            
            # Report exception
            if self.reporter and self.reporter.enabled:
                self.reporter.report_exception(
                    e,
                    source="docker",
                    context={
                        'command': command,
                        'monitor': 'docker_error_monitor'
                    }
                )
            
            return 1
    
    def _report_docker_error(self, command: List[str], exit_code: int, stderr: str):
        """
        Report a Docker command error.
        
        Args:
            command: Command that failed
            exit_code: Exit code
            stderr: Standard error output
        """
        try:
            # Extract error type and message from stderr
            error_message = stderr.strip() if stderr else f"Command exited with code {exit_code}"
            
            # Truncate very long error messages
            if len(error_message) > 500:
                error_message = error_message[:500] + "..."
            
            self.reporter.report_error(
                error_type="DockerCommandError",
                error_message=error_message,
                source="docker",
                error_location=f"command: {' '.join(command)}",
                stack_trace=stderr,
                context={
                    'command': command,
                    'exit_code': exit_code,
                    'container_id': os.environ.get('HOSTNAME', 'unknown'),
                    'image': os.environ.get('IMAGE_NAME', 'unknown')
                }
            )
        except Exception as e:
            logger.error(f"Failed to report Docker error: {e}")


def main():
    """Main entrypoint for Docker error monitor."""
    if len(sys.argv) < 2:
        print("Usage: docker_error_monitor.py <command> [args...]")
        sys.exit(1)
    
    command = sys.argv[1:]
    
    monitor = DockerErrorMonitor()
    exit_code = monitor.run_command(command)
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
