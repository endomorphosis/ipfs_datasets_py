

from typing import Any, Callable, Type, TypeVar, Generic


T = TypeVar('T')
U = TypeVar('U')


class Monad(Generic[T]):
    """
    Base class for Monads.

    Useful for:
        - Constructing and editing long, complex data processing pipelines.
        - Handling side effects predictably across every function in them.
        - Running these pipelines in parallel, asynchronously, or both.
        - Producing side effects (logging, error handling, file saving, etc) without modifying the function itself. 
        \nThis makes it great for adapting legacy code or third party libraries.
        - Highly Robust: ANY error in the pipeline can be caught, handled, and reported.
        - Highly Extensible, as you can add new operations to the pipeline easily.
        - Highly Testable, as you can test each operation in isolation.

    Attributes:
        _value: The value contained in the monad. Value can be anything, 
            but it's usually an input/output of a function, a function, or another Monad.

    Methods:
    - make_a_monad_with_this(Any): Wrap an input value in a monad.
        This is a static method, so you can instantiate the class without explicitly calling the constructor.
    - unit(Any): Alias for make_a_monad_with_this.
    - lift(Callable[[T], U]): Wrap a function into the monad,
    - bind(Callable[[T], Monad[U]]): Apply the function to current monad's value, and return the result in a new monad.
    - NOTE: That function can be coroutines as well

    Properties:
        - value: Read-only access to the value contained in the monad. 
        This is to prevent accidental modification during the pipeline process. 

    Example usage:
        >>> def add_one(x):
            return x + 1
        
        >>> def multiply_by_two(x):
            return x * 2

        >>> result = start(5, Monad) >> add_one >> multiply_by_two >> stop
        >>> result.value
        12
    """

    def __init__(self, value: T):
        if isinstance(value, Monad): # NOTE Remember to always unwrap the Monad!
            self._value = value._value
        else:
            self._value = value

    @property
    def value(self):
        return self._value

    @staticmethod
    def make_a_monad_with_this(value: T) -> 'Monad[T]':
        """
        Wrap the input value in a monad.
        """
        # If it's an instance of itself, return a copy of it with the input Monad's value.
        return Monad(value)

    @staticmethod
    def unit(value: T) -> 'Monad[T]':
        """
        Wrap the input value in a monad.
        """
        return Monad(value)

    def lift(self, func: Callable[[T], U], monad_type: Type['Monad[U]'] = None) -> 'Monad[U]':
        pass

    def bind(self, func: Callable[[T], 'Monad[U]']) -> 'Monad[U]':
        """
        Wrap a function that takes a value of type T and returns a monad of type U.
        This allows for function chaining in a controlled fashion.

        Args:
            func: Function to apply to the monad's value.

        Returns:
            A new monad with the result of the function applied to the value.

        """
        return self.make_a_monad_with_this(func(self.value))

    def flat_map(self, func: Callable[[T], 'Monad[U]']) -> 'Monad[U]':
        """
        Alias for bind.
        """
        return self.bind(func)

    def and_then(self, func: Callable[[T], 'Monad[U]']) -> 'Monad[U]':
        """
        Alias for bind.
        """
        return self.bind(func)

    def __rshift__(self, func: Callable[[T], 'Monad[U]']) -> 'Monad[U]':
        """
        Alias for bind. The symbol for it is the '>>' operator.


        Example: 
        >>> result = Monad(5) >> add_one >> multiply_by_two
        """
        return self.bind(func)

    def __call__(self, *args, **kwargs) -> 'Monad[T]':
        """
        Used when a Monad is called as a decorator or function.
        """
        return self.bind(lambda func: self.make_a_monad_with_this(func(*args, **kwargs)))

from functools import wraps, partial

def enter(x: Any) -> Monad[T]:
    """
    Return the input as a generic Monad
    """
    return Monad(x)

def multiply_by_two(x):
    return x * 2


import asyncio

class Async(Monad[T]):
    
    def __init__(self, value: T):
        super().__init__(value)
        self._loop = asyncio.get_event_loop()
        self._future = None 

    @staticmethod
    def unit(value: T):
        return Async(value)

    def bind(self, func: Callable[[T], 'Async[U]']) -> 'Async[U]':
        if callable(func):
            return Async(func(self.value))
        if asyncio.iscoroutinefunction(func): # TODO
            return Async(func(self.value))

    def __rshift__(self, func: Callable[[T], 'Monad[U]']) -> 'Async[U]':
        self.bind(func)

    @property
    def future(self):
        return self._future


def async_(func=None):
    return lambda x: Async(func(x))

from pydantic import BaseModel

class Resource(BaseModel):
    
    def save(self):
        pass

    def convert(self):
        pass

    def load(self):
        pass

resource = Resource()

save = partial(Resource.save)
load = partial(Resource.load)
convert = partial(Resource.convert)

def emit(x, resource):
    pass


pipeline = Monad(
            enter(resource)
        ).and_then(
            async_(load)
        ).and_then(
            async_(convert)
        ).and_then(
            async_(save)
        )
data = None
pipeline = Monad(data) >> async_(load) >> async_(convert)

def test_monad_as_decorator():
    # Test case 1: Using Monad as a decorator
    @Monad
    def add_one(x):
        return x + 1

    result = add_one(5)
    assert isinstance(result, Monad)
    assert result.value == 6

def test_monad_as_function():
    # Test case 2: Using Monad as a function
    def multiply_by_two(x):
        return x * 2

    monad_instance = Monad(multiply_by_two)
    result = monad_instance(3)
    assert isinstance(result, Monad)
    assert result.value == 6

    # Test case 3: Using Monad with keyword arguments
    @Monad
    def monad_greet(name, greeting="Hello"):
        return f"{greeting}, {name}!"

    result = monad_greet(name="Alice", greeting="Hi")
    assert isinstance(result, Monad)
    assert result.value == "Hi, Alice!"

    # Test case 4: Chaining Monad calls
    @Monad
    def add(x, y):
        return x + y

    @Monad
    def square(x):
        return x * x

    result = add(3, 4) >> square
    assert isinstance(result, Monad)
    assert result.value == 49

    # Test case 5: Error handling
    @Monad
    def divide(x, y):
        return x / y

def log(x):
    print(f"Logging: {x}")
    return x

def add_one(x):
    return x + 1

