from typing import Any
from unittest.mock import MagicMock, Mock


def is_mock(obj: Any) -> bool:
    """Check if the object is a mock object. 

    Args:
        obj: The object to check.

    Returns:
        bool: True if it is a mock, False otherwise.
    """
    return isinstance(obj, (MagicMock, Mock))
