def list_tools_in_functions_dir(get_docstring: bool = True) -> list[dict[str, str]]:
    """
    Lists all function-based tool files in the tools directory, excluding itself.

    Args:
        get_docstring (bool): If True, gets the tool's docstring. Defaults to True.

    Returns:
        list[dict[str, str]]: List of dictionaries containing Python filenames (without .py extension).
            If `get_docstring` is True, each dictionary will also contain the tool's docstring.

    Raises:
        ValueError: If get_docstring is not a boolean.
    """
    from pathlib import Path
    import ast

    if not isinstance(get_docstring, bool):
        raise ValueError(f"get_docstring must be a boolean value, not {type(get_docstring)}.")

    this_dir = Path(__file__).parent
    python_files = []

    for file in this_dir.rglob('*.py'):
        if (not file.name.startswith('_') and
            file.name != 'list_tools_in_functions_dir.py'):
            
            file_dict = {
                'name': file.stem,  # Get the name without the .py extension
            }
            if get_docstring:
                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Parse the file to extract the first function's docstring
                    tree = ast.parse(content)
                    docstring = None
                    
                    for node in ast.walk(tree):
                        if (isinstance(node, ast.FunctionDef) and 
                            not node.name.startswith('_')):
                            # Get the first public function's docstring
                            if (node.body and 
                                isinstance(node.body[0], ast.Expr) and 
                                isinstance(node.body[0].value, ast.Constant) and 
                                isinstance(node.body[0].value.value, str)):
                                docstring = node.body[0].value.value.strip()
                                break
                    
                    file_dict['docstring'] = docstring
                    
                except Exception:
                    # If we can't read the file or parse it, set docstring to None
                    file_dict['docstring'] = None
            
            python_files.append(file_dict)

    # Sort by name for consistent ordering
    return sorted(python_files, key=lambda x: x['name'])
