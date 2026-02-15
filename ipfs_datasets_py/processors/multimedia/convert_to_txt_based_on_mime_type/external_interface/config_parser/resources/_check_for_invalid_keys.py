from typing import Any, Never


def _check_for_invalid_keys(configs_dict: dict[str, Any], keys_to_check: list[str]) -> Never:
    invalid_keys = []

    for key in keys_to_check:
        if key in configs_dict and isinstance(configs_dict[key], str):
            if " " in configs_dict[key].strip():
                invalid_keys.append(key)

    if invalid_keys:
        raise ValueError(f"Invalid whitespace present in values for: {', '.join(invalid_keys)}")
