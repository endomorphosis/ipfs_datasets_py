

from .monad import Monad
from typing import Callable, TypeVar

T = TypeVar('T')
U = TypeVar('U')


class Just(Monad[T]):
    """
    Wraps the function as a Monad, without any side effects.
    Functionally equivalent to the generic Monad.
    """

    def __init__(self, value):
        super().__init__(value)

    @staticmethod
    def unit(value: T) -> 'Just[T]':
        return Just(value)

    def bind(self, func: Callable[[T], Monad[U]]) -> Monad[U]:
        return Just(func(self._value))