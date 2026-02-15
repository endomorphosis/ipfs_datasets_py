
from functools import wraps
from typing import Any, Callable, Coroutine, TypeVar


L = TypeVar('L')
R = TypeVar('R')
T = TypeVar('T')
U = TypeVar('U')
E = TypeVar('E')


from .monad import Monad
from .either import Either
from utils.common.logger import get_logger


logger = get_logger(__name__)


class ErrorMonad(Either[T]):
    """
    ErrorMonad: A specialized Either monad for handling exceptions and error flows.

    Key Behaviors:
    1. Chain computations that might fail
    2. Automatically catch and propagate exceptions
    3. Allow custom error handling
    4. Maintain the error state through the computation chain

    Example usage in pseudocode:
        result = (
            ErrorMonad.right(user_input)
            .bind(validate_input)
            .bind(process_data)
            .bind(save_to_database)
            .catch(handle_database_error)
        )
        results = ErrorMonad.right(user_input) >> validate_input >> process_data >> save_to_database >> handle_database_error
    """

    def __init__(self, 
                value: T | Exception, 
                handler: Callable[[Exception], T] | None = None,
                ):
        super().__init__(value)
        self._handler = handler
        self._caught = False


    @staticmethod
    def right(value: T) -> 'ErrorMonad[T]':
        """Create an ErrorMonad from a successful computation."""
        return ErrorMonad(value)


    @staticmethod
    def left(e: Exception) -> 'ErrorMonad[E]':
        """Create an ErrorMonad from a failed computation."""
        return ErrorMonad(e) # Propagate the error


    def bind(self, func: Callable[[T], 'ErrorMonad[U, E]':]) -> 'ErrorMonad[U, E]':
        if self.errored:
            return ErrorMonad(self.value) # Propagate the error
        try:
            return ErrorMonad(func(self.value))
        except Exception as e:
            return self.catch(e) if self._handler else self.throw(e)


    def throw(self, e: Exception) -> 'ErrorMonad[T]':
        """
        Throw an error into the computation chain. This will stop further computations.
        Also prints the error to the logger.
        """
        logger.error(f'Error Thrown: {e}')
        return self.left(e)


    def catch(self, handler: Callable[[E], T]) -> 'ErrorMonad[T]':
        """
        Handle any errors in the computation chain.

        Args:
            handler: Function to process the exception

        Returns:
            New ErrorMonad with handled error result
        """
        if not self.errored:
            logger.warning('No error to catch.')
            return self
        if not handler:
            logger.warning('No handler provided.')
            return self
        if not isinstance(handler, (Callable, Coroutine)):
            # If the handler isn't a callable or coroutine just pass it through.
            return ErrorMonad.right(result)
        try:
            logger.warning(f'Caught error')
            result = handler(self.value)
            logger.info(f'Caught and handled')
            self._caught = True
            return ErrorMonad.right(result)
        except Exception as e:
            logger.error(f"Handling failed: {e}")
            return ErrorMonad.left(e)


    @property
    def errored(self) -> bool:
        """Check if the monad contains an unhandled error."""
        if self._caught:
            return False
        return False if not isinstance(self._value, Exception) else True


    @property
    def caught(self) -> bool:
        """Check if the monad contains a handled error."""
        return self._caught


    def get_or_else(self, default: T) -> T:
        """
        Safely extract the value or return a default.
        
        Args:
            default: Value to return if an error exists
            
        Returns:
            The contained value or the default
        """
        return default if self.errored else self.value


    @staticmethod
    def lift(func: Callable[[T], U]) -> Callable[[T], 'ErrorMonad[U]']:
        """
        Convert a regular function into one that returns an ErrorMonad.
        
        Args:
            f: Function to lift into the ErrorMonad context
            
        Returns:
            Wrapped function that returns an ErrorMonad
        """
        @wraps(func)
        def wrapped(x: T) -> 'ErrorMonad[U, E]':
            try:
                return ErrorMonad.right(func(x))
            except Exception as e:
                return ErrorMonad.left(e)
        return wrapped


    def __rshift__(self, func: Callable[[T], U]) -> 'ErrorMonad[U, E]':
       return self.bind(func)


    def __lshift__(self, handler: Callable[[T], U]) -> 'ErrorMonad[T, E]':
        return self.catch(handler)





