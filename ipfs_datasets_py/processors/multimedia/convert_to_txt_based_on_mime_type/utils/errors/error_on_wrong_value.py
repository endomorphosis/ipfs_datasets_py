

from collections import Counter

from typing import Any, Optional

def error_on_wrong_value(this_value: Any,
                         equal_to_this_value: Optional[Any] = None,
                         not_equal_to_this_value: Optional[Any] = None,
                         greater_than_this: Optional[Any] = None,
                         less_than_this: Optional[Any] = None,
                         greater_than_or_equal_to_this: Optional[Any] = None,
                         less_than_or_equal_to_this: Optional[Any] = None,
                         raise_on_error: bool = False,
                         custom_error_message: Optional[str] = None
                        ) -> Any:
    """
    Checks if the given value meets specified conditions and raises or returns an error if not.

    Args:
        this_value (Any): The value to be checked.
        equal_to_this_value (Optional[Any]): Value that this_value should be equal to.
        not_equal_to_this_value (Optional[Any]): Value that this_value should not be equal to.
        greater_than_this (Optional[Any]): Value that this_value should be greater than.
        less_than_this (Optional[Any]): Value that this_value should be less than.
        greater_than_or_equal_to_this (Optional[Any]): Value that this_value should be greater than or equal to.
        less_than_or_equal_to_this (Optional[Any]): Value that this_value should be less than or equal to.
        raise_on_error (bool): If True, raises the error; if False, returns the error.

    Returns:
        Any: The value of this_value if all conditions are met, or a ValueError if not.

    Raises:
        ValueError: If any of the specified conditions are not met and raise_on_error is True.
    """
    conditions: tuple[bool, str] = [
        (equal_to_this_value is not None and this_value != equal_to_this_value,
         f'Expected {this_value} to be equal to {equal_to_this_value}'),
        (not_equal_to_this_value is not None and this_value == not_equal_to_this_value,
         f'Expected {this_value} to be not equal to {not_equal_to_this_value}'),
        (greater_than_this is not None and this_value <= greater_than_this,
         f'Expected {this_value} to be greater than {greater_than_this}'),
        (greater_than_or_equal_to_this is not None and this_value < greater_than_or_equal_to_this,
         f'Expected {this_value} to be greater than or equal to {greater_than_or_equal_to_this}'),
        (less_than_this is not None and this_value >= less_than_this,
         f'Expected {this_value} to be less than {less_than_this}'),
        (less_than_or_equal_to_this is not None and this_value > less_than_or_equal_to_this,
         f'Expected {this_value} to be less than or equal to {less_than_or_equal_to_this}'),
    ]

    # Check each condition and raise or return an error if any condition is not met
    for condition, error_message in conditions:
        if condition:
            error = ValueError(error_message) if custom_error_message is None else ValueError(custom_error_message)
            if raise_on_error:
                raise error
            return error

    return this_value
