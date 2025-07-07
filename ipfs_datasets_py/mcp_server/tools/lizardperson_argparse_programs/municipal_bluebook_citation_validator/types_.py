"""
Module to centralize access built-in types, custom type aliases, and custom type variables.
"""

import logging
from typing import Any, Callable, TypeVar, TypeAlias, TYPE_CHECKING

if TYPE_CHECKING:
    from .configs import _Configs

DatabaseConnection = TypeVar('DatabaseConnection')
DatabaseCursor = TypeVar('DatabaseCursor')

ProgressBar = TypeVar('ProgressBar', bound=Callable[..., Any])

Dependency = TypeVar('Dependency')

Configs = TypeVar('Configs')

Logger: TypeAlias = logging.Logger
