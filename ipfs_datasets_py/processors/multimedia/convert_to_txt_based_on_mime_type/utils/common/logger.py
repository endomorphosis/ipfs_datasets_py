import logging
from logging.handlers import RotatingFileHandler
import os


def get_logger(name: str,
                log_file: str = 'app.log',
                level: int = logging.DEBUG,
                max_size: int = 5*1024*1024,
                backup_count: int = 3
                ) -> logging.Logger:
    """Sets up a logger with both file and console handlers.

    Args:
        name: Name of the logger.
        log_file: Name of the log file. Defaults to 'app.log'.
        level: Logging level. Defaults to logging.DEBUG.
        max_size: Maximum size of the log file before it rotates. Defaults to 5MB.
        backup_count: Number of backup files to keep. Defaults to 3.

    Returns:
        Configured logger.

    Example:
        # Usage
        logger = setup_logger(__name__)
    """
    # Create a custom logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Create handlers
    console_handler = logging.StreamHandler()

    # Create 'logs' directory in the current working directory if it doesn't exist
    logs_dir = os.path.join(os.getcwd(), 'logs')
    os.makedirs(logs_dir, exist_ok=True)

    log_file_path = os.path.join(logs_dir, log_file)
    file_handler = RotatingFileHandler(log_file_path, maxBytes=max_size, backupCount=backup_count)

    # Create formatters and add it to handlers
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    formatter = logging.Formatter(log_format)
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # Add handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger