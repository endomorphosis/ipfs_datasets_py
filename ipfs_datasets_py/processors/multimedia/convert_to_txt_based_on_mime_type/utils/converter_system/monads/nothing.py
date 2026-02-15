
from typing import TypeVar
from .monad import Monad

T = TypeVar('T')
U = TypeVar('U')


class Nothing(Monad[T]):
    """
    The Nothing Monad.
    Always returns None, no matter the value put into it.
    """
    def __init__(self, value: T = None):
        super().__init__(None)

    @staticmethod
    def unit(value: T) -> 'Nothing[T]':
        return Nothing(value)

    def bind(self, func):
        return self