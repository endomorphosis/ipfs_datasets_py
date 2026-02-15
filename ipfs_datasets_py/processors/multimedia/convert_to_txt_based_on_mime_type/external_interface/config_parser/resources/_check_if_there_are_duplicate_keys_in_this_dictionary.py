

from typing import Never


def _check_if_there_are_duplicate_keys_in_this_dictionary(configs_dict: dict) -> Never:
    """
    Check if there are multiple keys with the same name in the YAML file.

    This function analyzes the given dictionary (presumably parsed from a YAML file)
    to detect any duplicate keys. If duplicates are found, it raises a ValueError.

    Args:
        configs_dict (dict): A dictionary containing the configuration data parsed from a YAML file.

    Raises:
        ValueError: If any duplicate keys are found in the configuration dictionary.

    Returns:
        Never: This function never returns normally; it either raises an exception or the program continues.
    """
    key_counts = {}
    for key in configs_dict.keys():
        if key in key_counts:
            key_counts[key] += 1
        else:
            key_counts[key] = 1

    duplicate_keys = [k for k, v in key_counts.items() if v > 1]
    print(f"duplicate_keys: {duplicate_keys}")
    if len(duplicate_keys) != 0:
        raise ValueError(f"Multiple keys with the same name found in config file: {', '.join(duplicate_keys)}")
