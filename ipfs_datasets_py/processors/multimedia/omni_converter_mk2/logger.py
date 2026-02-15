"""
Logging utility for the Omni-Converter.

This module provides logging functionality for the Omni-Converter.
"""
import logging
from functools import cached_property
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_logger(name: str,
                log_file_name: str = 'app.log',
                level: int = logging.INFO,
                max_size: int = 5*1024*1024,
                backup_count: int = 3
                ) -> logging.Logger:
    """Sets up a logger with both file and console handlers.

    Args:
        name: Name of the logger.
        log_file_name: Name of the log file. Defaults to 'app.log'.
        level: Logging level. Defaults to logging.INFO.
        max_size: Maximum size of the log file before it rotates. Defaults to 5MB.
        backup_count: Number of backup files to keep. Defaults to 3.

    Returns:
        Configured logger.

    Example:
        # Usage
        logger = get_logger(__name__)
    """
    # Create the logger itself.
    logger = logging.getLogger(name)

    # Set the default log level.
    logger.setLevel(level)
    logger.propagate = False # Prevent logs from being handled by parent loggers

    # Create 'logs' directory in the current working directory if it doesn't exist
    logs_dir = Path.cwd() / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = logs_dir / log_file_name

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')

    if not logger.handlers:
        # Create handlers (file and console)
        console_handler = logging.StreamHandler()
        file_handler = RotatingFileHandler(log_file_path.resolve(), maxBytes=max_size, backupCount=backup_count)

        # Set level for handlers
        file_handler.setLevel(logging.DEBUG) # We want to log everything to the file.
        console_handler.setLevel(level)

        # Create formatters and add it to handlers
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Add handlers to the logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    # # Create handlers
    # console_handler = logging.StreamHandler()

    # log_file_path = logs_dir / log_file_name
    # file_handler = RotatingFileHandler(log_file_path.resolve(), maxBytes=max_size, backupCount=backup_count)

    # # Create formatters and add it to handlers
    # formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
    # console_handler.setFormatter(formatter)
    # file_handler.setFormatter(formatter)

    # # Add handlers to the logger
    # logger.addHandler(console_handler)
    # logger.addHandler(file_handler)

    return logger

class _Logger:
    """Singleton class to manage logger instances."""
    
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.logger = get_logger(__name__)
        return cls._instance

    def __init__(self, resources=None, configs=None):
        pass

    @cached_property
    def logger(self):
        return self._instance.logger

# Global logger instances
logger = get_logger(__name__, log_file_name='app.log', level=logging.DEBUG)

test_logger = get_logger('tests', log_file_name='test.log', level=logging.DEBUG)
