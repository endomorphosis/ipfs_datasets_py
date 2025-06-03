import logging
from typing import TypeVar, TypeAlias

from configs import _Configs

DatabaseConnection = TypeVar('DatabaseConnection')

Dependency = TypeVar('Dependency')

Configs: TypeAlias = _Configs

Logger: TypeAlias = logging.Logger