"""
Use a function in this folder as an MCP tool.

Hacky way to get around MCP's 129 tool limit.
"""
from typing import Any, Callable

def _call_function_and_return_results(
    function_name: str,
    function: Callable,
    args_dict: dict[str, Any] = None,
    kwargs_dict: dict[str, Any] = None,
    ) -> dict[str, Any]:
    """Call a function with the provided arguments and return the result."""
    if kwargs_dict and args_dict:
        result = function(*args_dict.values(), **kwargs_dict)
    else:
        if args_dict:
            # If only args_dict is provided, call the function with positional arguments
            result = function(*args_dict.values())
        elif kwargs_dict:
            # If only kwargs_dict is provided, call the function with keyword arguments
            result = function(**kwargs_dict)
        else:
            result = function()
    return {
        'name': function_name,
        'result': result
    }

def _verify_tool_call(
        function_name: str, 
        functions_docstring: str
        ) -> None:
    """
    Verify that the function exists in the tools directory and that its docstring matches the provided docstring.
        This is to make sure the LLM didn't hallucinate the function or its docstring.
    """
    from .list_tools_in_functions_dir import list_tools_in_functions_dir
    tools = list_tools_in_functions_dir(get_docstring=True)
    # Make sure the LLM didn't hallucinate the function.
    tool = [
        tool for tool in tools if tool['name'] == function_name
    ]
    if tool is None or not tool:
        raise FileNotFoundError(f"Function '{function_name}' not found in tools directory.")
    # Make sure the LLM didn't hallucinate the docstring.
    if tool[0]['docstring'] != functions_docstring:
        raise ValueError(f"Function '{function_name}' does not match the provided docstring. Please check it and try again.")

def use_function_as_tool(
        function_name: str, 
        functions_docstring: str,
        args_dict: dict[str, Any] = None, 
        kwargs_dict: dict[str, Any] = None,
        ) -> dict[str, Any]:
    """
    Use a function in this folder as a tool.

    Args:
        function_name (str): The name of the function to use as a tool.
        functions_docstring (str): The docstring of the function to use as a tool.
        args_dict (dict[str, Any]): A dictionary of positional arguments to pass to the function.
            The order of the keys must match the order of the function's arguments.
        kwargs_dict (dict[str, Any]): A dictionary of keyword arguments to pass to the function.

    Returns:
        dict: A dictionary with the following:
            - The name of the function.
            - The result of the function call, if any.
    Raises:
        FileNotFoundError: If the function is not found in the tools directory.
        ImportError: If the module for the function cannot be imported.
        AttributeError: If the function isn't in the module or isn't callable.
        ValueError: If there is an error calling the function.
    """
    import importlib
    _verify_tool_call(function_name, functions_docstring)

    try:
        module = importlib.import_module(f'ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.functions.{function_name}')
        function = getattr(module, function_name)
    except (ModuleNotFoundError, ImportError) as e:
        raise ImportError(f"Could not import module for function '{function_name}': {e}")
    except AttributeError:
        raise AttributeError(f"Function '{function_name}' not found in module 'ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.functions.{function_name}'.")

    assert callable(function), f"Function '{function_name}' is not callable."
    try:
        return _call_function_and_return_results(
            function_name=function_name,
            function=function,
            args_dict=args_dict,
            kwargs_dict=kwargs_dict
        )
    except Exception as e:
        raise ValueError(f"Error calling function '{function_name}': {e}") from e