from typing import Any, Literal


import pytest
from pydantic import BaseModel


def all_words_are_present_in_error_msg(
                                        exc_info: pytest.ExceptionInfo, 
                                        words: list[str]
                                        ) -> Literal[True]:
    """Helper to check if all strings in a list of strings are present in the error message."""
    error_msg = str(exc_info.value)
    for word in words:
        if word not in error_msg.lower():
            error_msg = f"Word '{word}' not found in error message \n'{error_msg}'"
            raise AssertionError(error_msg)
    return True


def field_values_exactly_match_dict_values(
        input_dict: dict[str, Any], 
        base_model: BaseModel
    ) -> Literal[True]:
    """    
    Helper to check if all values in a dictionary match the corresponding fields in a Pydantic model.
    """
    for field, value in input_dict.items():
        field_value = getattr(base_model, field)
        assert field_value == value, f"Field '{field}' should contain '{value}', got '{field_value}' instead."
    return True
