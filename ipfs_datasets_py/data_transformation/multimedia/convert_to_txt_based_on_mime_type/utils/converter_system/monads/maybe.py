


from __future__ import annotations
from typing import TypeVar


T = TypeVar('T')
U = TypeVar('U')


from .monad import Monad
from .nothing import Nothing


class Maybe(Monad[T]):

    def __init__(self, value):
        super().__init__(value)

    @property
    def value(self):
        return self._value

    @staticmethod
    def unit(value):
        return Maybe(value)

    def bind(self, func):
        if self._value is None:
            return Nothing(None)
        else:
            return Maybe(func(self._value))
        
    def __rshift__(self, func):
        return self.bind(func)

    def orElse(self, default):
        if self._value is None:
            return Maybe(default)
        else:
            return self

    def unwrap(self):
        return self._value

    def __or__(self, other):
        return Maybe(self._value or other._value)

    def __str__(self):
        if self._value is None:
            return 'Nothing'
        else:
            return 'Just {}'.format(self._value)

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        if isinstance(other, Maybe):
            return self._value == other._value
        else:
            return False

    def __ne__(self, other):
        return not (self == other)

    def __bool__(self):
        return self._value is not None