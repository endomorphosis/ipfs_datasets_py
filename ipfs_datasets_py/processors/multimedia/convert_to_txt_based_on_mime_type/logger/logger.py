
import logging
import os
from pathlib import Path
import sys
import time
from typing import Callable, Optional, TypeAlias


from ._pydantic_file_handler import PydanticFileHandler, LogFile


def _pretty_format(message: str) -> str:
    """
    Format the message with a line of asterisks above and below it.
    The number of asterisks will have the same length as the input message, 
    with a maximum character length of 100.
    """
    asterisk = '*' * len(message)
    # Cut off the asterisk string at 50 characters to prevent wasted log space.
    if len(message) > 100:
        asterisk = asterisk[:100]
    return f"\n{asterisk}\n{message}\n{asterisk}\n"


class Logger:

    def __init__(self, 
                 name: str, 
                 level: int = logging.DEBUG, 
                 log_folder: Path = Path("logs"),
                 stacklevel: int = 2
                ):
        self.name = name
        self.level = level
        self.stacklevel = stacklevel
        self.log_folder = log_folder if isinstance(log_folder, Path) else Path(log_folder)
        self.logger = None
        self.log_file = None

        self._setup_log_folder()
        self._setup_logger()
        print(f"Logger '{self.name}' initialized with debug level '{self.level}' in log folder '{self.log_folder}'")

    def _setup_log_folder(self):

        # Initialize LogFile instance to store structured logs
        self.log_file = Path(os.getcwd()) / "logs" / f"{self.name}.log"

       # Ensure the log folder and file exist and are writable
        if not self.log_folder.parent.exists():
            self.log_folder.mkdir(parents=True, exist_ok=True)

        if not self.log_file.exists():
            self.log_file.touch()
            with self.log_file.open("w") as file:
                # Hacky way to make sure each can be turned into a JSON file.
                file.write('{\n    "entries": []\n}')
            print(f"Log file created at {self.log_file}")


    def _setup_logger(self):

        # Create the logger itself.
        self.logger = logging.getLogger(self.name)

         # Set the default log level.
        self.logger.setLevel(self.level)
        self.logger.propagate = False # Prevent logs from being handled by parent loggers

        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s: %(lineno)d - %(message)s')

        if not self.logger.handlers:
            # Create handlers (file and console)
            #self.filepath = self.log_folder / f"{self.name}.log"
            file_handler = PydanticFileHandler(self.log_file)
            console_handler = logging.StreamHandler()

            # Set level for handlers
            file_handler.setLevel(logging.DEBUG) # We want to log everything to the file.
            console_handler.setLevel(self.level)

            # Create formatters and add it to handlers
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            # Add handlers to the logger
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)


    def _message_template(self, message: str, method: Callable, f: bool, t: float, off: bool) -> None:
        """
        Args:
            f: Format the message with asterisk for easy viewing. These will not be saved to the log file.
            t: Pause the program by a specified number of seconds after the message has been printed to console.
            off: Turns off the logger for this message. Logs will still be saved to the log file
        """
        if not off:
            if not f: # We move up the stack by 1 because it's a nested method.
                method(message, stacklevel=self.stacklevel+1)
            else:
                method(_pretty_format(message), stacklevel=self.stacklevel+1)
            if t:
                time.sleep(t)
            return

    def info(self, message, f: bool=False, t: float=None, off: bool=False) -> None:
        """
        Args:
            f: Format the message with asterisk for easy viewing. These will not be saved to the log file.
            t: Pause the program by a specified number of seconds after the message has been printed to console.
            off: Turns off the logger for this message. Logs will still be saved to the log file
        """
        self._message_template(message, self.logger.info, f, t, off)

    def debug(self, message, f: bool=False, t: float=None, off: bool=False) -> None:
        """
        Args:
            f: Format the message with asterisk for easy viewing. These will not be saved to the log file.
            t: Pause the program by a specified number of seconds after the message has been printed to console.
            off: Turns off the logger for this message. Logs will still be saved to the log file
        """
        self._message_template(message, self.logger.debug, f, t, off)

    def warning(self, message, f: bool=False, t: float=None, off: bool=False) -> None:
        """
        Args:
            f: Format the message with asterisk for easy viewing. These will not be saved to the log file.
            t: Pause the program by a specified number of seconds after the message has been printed to console.
            off: Turns off the logger for this message. Logs will still be saved to the log file
        """
        self._message_template(message, self.logger.warning, f, t, off)

    def error(self, message, f: bool=False, t: float=None, off: bool=False) -> None:
        """
        Args:
            f: Format the message with asterisk for easy viewing. These will not be saved to the log file.
            t: Pause the program by a specified number of seconds after the message has been printed to console.
            off: Turns off the logger for this message. Logs will still be saved to the log file
        """
        self._message_template(message, self.logger.error, f, t, off)

    def critical(self, message, f: bool=False, t: float=None, off: bool=False) -> None:
        """
        Args:
            f: Format the message with asterisk for easy viewing. These will not be saved to the log file.
            t: Pause the program by a specified number of seconds after the message has been printed to console.
            off: Turns off the logger for this message. Logs will still be saved to the log file
        """
        self._message_template(message, self.logger.critical, f, t, off)

    def exception(self, message, f: bool=False, t: float=None, off: bool=False) -> None:
        """
        Args:
            f: Format the message with asterisk for easy viewing. These will not be saved to the log file.
            t: Pause the program by a specified number of seconds after the message has been printed to console.
            off: Turns off the logger for this message. Logs will still be saved to the log file
        """
        self._message_template(message, self.logger.exception, f, t, off)