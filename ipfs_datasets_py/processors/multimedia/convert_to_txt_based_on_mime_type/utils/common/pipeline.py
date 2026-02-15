"""
Common pipeline utilities for multimedia text conversion.

This module defines a minimal, reusable pipeline executor that can be used
by MIME-type specific converters to compose processing steps in a linear
fashion. It is intentionally generic and has no external dependencies so it
can be imported safely from any part of the multimedia processing stack.
"""

from collections.abc import Callable, Iterable
from typing import Any, Protocol, TypeVar

T_co = TypeVar("T_co", covariant=True)
U_co = TypeVar("U_co", covariant=True)


class PipelineStep(Protocol[T_co, U_co]):
    """
    Protocol for a single step in a processing pipeline.

    A pipeline step is any callable that accepts an input value and returns
    a transformed value. Concrete implementations can perform tasks such as
    decoding, normalisation, filtering, or text extraction.
    """

    def __call__(self, data: T_co) -> U_co:
        """
        Process the given data and return the transformed result.

        Args:
            data: The input value to be processed by this step.

        Returns:
            The transformed value produced by this step.
        """
        ...


def run_pipeline(initial: Any, steps: Iterable[Callable[[Any], Any]]) -> Any:
    """
    Execute a simple linear processing pipeline.

    Each step is called in sequence, with the output of one step becoming
    the input to the next. The final result is returned to the caller.

    This helper is deliberately unopinionated about the types flowing through
    the pipeline so it can be reused across different media and MIME-type
    specific converters.

    Args:
        initial: The initial value to feed into the pipeline.
        steps: An iterable of callables. Each callable should accept the
            output of the previous step (or the initial value for the first
            step) and return a new value.

    Returns:
        The final value produced after all steps have been applied.
    """
    result: Any = initial
    for step in steps:
        result = step(result)
    return result
