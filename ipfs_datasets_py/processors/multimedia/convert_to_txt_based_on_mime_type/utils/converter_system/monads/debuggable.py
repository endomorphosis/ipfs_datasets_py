
from typing import Callable, TypeVar
import inspect


T = TypeVar('T')
U = TypeVar('U')


from .error import ErrorMonad

from utils.common.logger import get_logger
from utils.common.stopwatch import stopwatch


logger = get_logger(__name__)


class Debuggable(ErrorMonad[T]):
    """
    Debug a function by logging the arguments and result.
    """
    def __init__(self, value: T):
        super().__init__(value)

    def unit(self, value: T) -> 'Debuggable[T]':
        return Debuggable(value)

    def debug(self, func: Callable[[T], 'Debuggable[U]']) -> 'Debuggable[T]':
        # Get the args, kwargs, and their current values
        signature = inspect.signature(func)
        bound_args = signature.bind(self.value)
        bound_args.apply_defaults()

        args_info = []
        for param_name, param_value in bound_args.arguments.items():
            args_info.append(f"{param_name}: {param_value}")

        logger.debug(f"Debugging {func.__name__}:")
        logger.debug(f"Arguments: {', '.join(args_info)}")

        # Execute the function and capture the result
        try:
            result = stopwatch(func(self.value))
            logger.debug(f"Result: {result.value}") # Log the result.
            return Debuggable.right(result)
        except Exception as e:
            # NOTE Class inheritance means this should result in an ErrorMonad.
            logger.debug(f"Error: {result.value}") # Log the error.
            return Debuggable.left(e)

    def bind(self, func: Callable[[T], 'Debuggable[U]']) -> 'Debuggable[U]':
        return self.debug(func)

    def __lshift__(self, func: Callable[[T], 'Debuggable[U]']) -> 'Debuggable[U]':
        return self.bind(func)


