

from typing import Any


def normalize_dict_keys_and_values(configs_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Converts dictionary keys and string values to lowercase and removes leading/trailing whitespace.

    This function processes a dictionary by converting all keys to lowercase and stripping
    whitespace. For string values, it also converts them to lowercase and strips whitespace.
    Non-string values are left unchanged. Duplicate keys are removed in the process.

    Args:
        configs_dict (dict[str, Any]): The input dictionary to process.
    Returns:
        dict[str, Any]: A new dictionary with processed keys and values.

    Raises:
        ValueError: If the input dictionary structure is invalid or cannot be processed.

    Note:
        This function modifies the structure of the input dictionary. Keys that become
        identical after processing will result in only the last occurrence being kept.
    """
    try:
        return {
            key.lower().strip(): value.lower().strip() if isinstance(value, str) else value
            for key, value in configs_dict.items()
        }
    except (AttributeError, ValueError) as e:
        raise ValueError(f"Invalid configuration structure: {e}")
