
from types_ import Logger, Processor
from ._is_mock import is_mock
from logger import logger

def check_if_all_these_processors_are_mocks(
        name: str, 
        keys: list[str], 
        processors: dict[str, Processor]
    ) -> bool:
    """Check if all specified processors are mock objects.

    Args:
        name (str): The name of the handler being checked (used for logging context).
        keys (list[str]): List of processor keys to check in the processors dictionary.
        processors (dict[str, Processor]): Dictionary mapping processor names to Processor instances.
        logger (Logger): Logger instance for recording warnings about mock processors.

    Returns:
        bool: True if all specified processors are mocks, False otherwise.
        NOTE:  If only some are mocks, it logs a warning for each mocked processor, then returns False.
    """
    if all(is_mock(processors[key]) for key in keys):
        return True
    else:
        for key in keys:
            if is_mock(processors[key]):
                logger.warning(f"'{key}' processor in {name} handler is a mock. Some functionality may be limited.")
        return False