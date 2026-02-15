from datetime import datetime
from pathlib import Path
import logging
import threading


from pydantic import BaseModel, ConfigDict, Field, field_serializer,  model_serializer, ValidationError
from pydantic_core import to_jsonable_python 


def get_current_datetime_in_iso_8601_() -> str:
    """
    Returns the current datetime in ISO 8601 format.
    
    The format is: YYYY-MM-DDTHH:MM:SS.mmmmmm+HH:MM
    
    Returns:
        str: Current datetime in ISO 8601 format
    """
    return datetime.now().isoformat()


class LogEntry(BaseModel):
    """
    A log entry with a message, level, line number, and a timestamp.
    """
    message: str = Field(..., description="The log message")
    filename: str = Field(..., description="The filename where the log entry was created")
    func_name: str = Field(..., description="The function name where the log entry was created")
    level: int = Field(..., description="The log level")
    lineno: int = Field(..., description="The line number where the log entry was created")
    timestamp: str = Field(..., description="The timestamp of the log entry")

    def __init__(self, **data):
        super().__init__(**data)


class LogFile(BaseModel):
    entries: list[LogEntry] = Field(default_factory=list, description="The log entries in the log file")


class PydanticFileHandler(logging.FileHandler):
    """
    A handler class which sends log messages to a Pydantic class for storage.
    """

    def __init__(self, 
                 filename: Path, 
                 mode: str = 'a', 
                 encoding: str = 'utf-8', 
                 newline: str = '\n', 
                 log_entry_model: BaseModel = None,
                 delay: bool = False,
                 errors: str | None = None,
                 ):
        """
        Initialize the handler.
        """
        # Check if we got pydantic installed
        try:
            import pydantic
        except ModuleNotFoundError:
            raise RuntimeError("Pydantic is not installed. Please install it using pip install pydantic")

        self.mode = mode
        self.encoding = encoding
        self.newline = newline
        self.log_entry_model = log_entry_model

        super().__init__(filename, mode=mode, encoding=encoding, delay=delay, errors=errors)

        self.rlock = threading.RLock()
        self.level = logging.DEBUG
        self.on_same_line = False
        self.stream.write(',{\n    "entries": [\n')


    def _make_log_entry(self, record: logging.LogRecord) -> LogEntry:
        """
        Make a structured log entry based on a pydantic model.
        """
        if self.log_entry_model is None:
                log_entry = LogEntry(
                    message=record.getMessage(), # NOTE It's NOT message, it's msg. FML
                    filename=record.filename,
                    func_name=record.funcName,
                    level=record.levelno,
                    lineno=record.lineno,
                    timestamp=get_current_datetime_in_iso_8601_()
                )
        else:
            record_dict = {
                key: value for key, value in record.__dict__.items()
                if key in self.log_entry_model.model_fields()
            }
            log_entry = self.log_entry_model(**record_dict)
        return log_entry


    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a record by writing it to the file in JSON format.
        
        Args:
            record: LogRecord to emit
        """
        try:
            with self.rlock:

                # Convert the log record to a JSON string
                log_entry = self._make_log_entry(record)
                json_str = log_entry.model_dump_json()

                # Write to the stream
                self.stream.write(f'        {json_str},\n')

                # Handle same-line logging if needed
                same_line = getattr(record, 'same_line', False)
                if self.on_same_line and not same_line:
                    self.stream.write(self.newline)

                self.flush()
                self.on_same_line = same_line

        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def close(self) -> None:
        """
        Close the handler and the associated file.
        """
        if self.stream:
            try:
                # Delete the last comma and newline, then close the JSON array and object
                self.stream.seek(self.stream.tell() - 1)
                self.stream.tell()

                self.stream.write('    ]\n}')
                self.flush()
                if hasattr(self.stream, "fileno"):
                    self.stream.close()
            except (OSError, ValueError):
                pass
            finally:
                self.stream = None