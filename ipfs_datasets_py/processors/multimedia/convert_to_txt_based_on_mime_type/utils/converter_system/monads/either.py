"""


"""
from __future__ import annotations
from typing import Callable, TypeVar


from .monad import Monad
from utils.common.logger import get_logger


logger = get_logger(__name__)

L = TypeVar('L')
R = TypeVar('R')
T = TypeVar('T')


class Either(Monad[T]):

    def __init__(self, value: L | R, is_left: bool = False):
        super().__init__(value)
        self.is_left = is_left
        self.is_right = not is_left

    @staticmethod
    def left(value: L) -> 'Either[L, R]':
        return Either(value, is_left=True)
    
    @staticmethod
    def right(value: R) -> 'Either[L, R]':
        return Either(value, is_left=False)
    
    @staticmethod
    def from_optional(value: L | None) -> 'Either[L, R]':
        if value is None:
            return Either.left(None)
        else:
            return Either.right(value)

    def bind(self, func: Callable[[R], 'Either[L, R]']) -> 'Either[L, R]' | Monad[L]:
        if self.is_left:
            return Either.left(self.value)
        else:
            return func(self.value)


