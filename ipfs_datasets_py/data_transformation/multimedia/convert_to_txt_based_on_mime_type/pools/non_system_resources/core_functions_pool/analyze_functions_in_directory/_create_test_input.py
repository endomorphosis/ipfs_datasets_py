
from typing import Any, Optional

def _create_test_input(param_name: str, param_type: Optional[str]) -> Any:
    """
    Creates appropriate test input based on parameter name and type hint.
    """
    if param_type is None:
        # Guess based on parameter name
        if 'path' in param_name.lower():
            return 'test_path.txt'
        elif 'list' in param_name.lower():
            return []
        elif 'dict' in param_name.lower():
            return {}
        elif 'num' in param_name.lower() or 'count' in param_name.lower():
            return 0
        return None

    # Create based on type hint
    type_mapping = {
        'str': '',
        'int': 0,
        'float': 0.0,
        'bool': False,
        'list': [],
        'dict': {},
        'set': set(),
        'tuple': (),
    }
    return type_mapping.get(param_type, None)
