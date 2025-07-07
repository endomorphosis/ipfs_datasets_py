import ast
from pathlib import Path


class BadDocumentationError(Exception):
    """Custom exception for bad documentation."""
    pass


class BadSignatureError(Exception):
    """Custom exception for bad function signatures."""
    pass


def get_ast_tree(input_path: Path) -> ast.Module:
    """Read and parse the Python file for its AST tree."""
    try:
        with open(input_path.resolve(), 'r') as file:
            content = file.read()
    except Exception as e:
        raise IOError(f"Failed to read file {input_path}: {e}") from e
    
    tree = ast.parse(content)
    return tree


def raise_on_bad_callable_metadata(tree) -> str:
    """
    Ensure the quality of the metadata of callable objects (functions, methods, classes) in a Python module.
    """
    for node in ast.walk(tree):
        # Check if definition has a good signature and docstring
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
            raise_on_bad_signature(node, tree)
            raise_on_bad_docstring(node)


def raise_on_bad_signature(node) -> None:
    """
    Validate the signature of a callable object and raise errors for bad patterns.
    
    This function checks a callable's signature for common issues including:
    - Parameters with default values but no type annotations
    - Parameters without type annotations (excluding 'self' and 'cls')
    - Missing return type annotation
    
    Args:
        node: An AST node representing a callable object (function or method)
              that contains signature information including arguments and return type.

    Returns:
        None

    Raises:
        BadSignatureError: If any of the following signature issues are found:
            - A parameter has a default value but no type annotation
            - A parameter lacks a type annotation (except 'self' or 'cls')
            - The callable is missing a return type annotation
    """
    node_name = node.name

    # Check for default values in parameters
    for arg in node.args.args:
        if arg.annotation is None and arg.default is not None:
            raise BadSignatureError(
                f"Callable '{node_name}' has a parameter '{arg.arg}' with a default value but no type annotation."
            )

    # Check for type annotations in parameters
    for arg in node.args.args:
        if arg.annotation is None and arg.name not in ['self', 'cls']:
            raise BadSignatureError(
                f"Callable '{node_name}' has a parameter '{arg.arg}' without a type annotation."
            )

    # Check for return annotation
    if node.returns is None:
        raise BadSignatureError(
            f"Callable '{node_name}' does not have a return type annotation."
        )

    return


def raise_on_bad_docstring(node, tree: ast.Module) -> None:
    """
    Validate that a node has a proper docstring with required sections.
    
    Args:
        node: The AST node to check for docstring quality.
        tree: The full AST tree for context when checking for raises.
        
    Raises:
        BadDocumentationError: If the docstring is missing, too short, or lacks required sections.
    """
    char_length = 50
    node_name = node.name

    docstring = ast.get_docstring(node)
    if not docstring:
        raise BadDocumentationError(f"Docstring for '{node_name}' is empty or missing.")

    # Docstring is at least 50 characters long
    if len(docstring.split()) >= char_length:
        raise BadDocumentationError(
            f"Docstring for '{node_name}' is less than {char_length} characters long."
        )

    # Check the function body for exceptions
    raise_exists = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Raise):
                    raise_exists = True
                    break

    # Docstring contains "Raise:" or "Raises:" if they exist in the function body
    if any(keyword in docstring for keyword in ['Raises:', 'Raise:']):
        if raise_exists is True:
            raise BadDocumentationError(
                f"Docstring for '{node_name}' contains 'Raises:' or 'Raise:'"
                "but no exceptions are raised in the callable body."
            )

    # Docstring contains "Args:" if there are arguments
    # Remove "self" and "cls" from the args list for class methods
    node.args.args = [arg for arg in node.args.args if arg.arg not in ['self', 'cls']]

    if node.args.args:
        if 'Args:' not in docstring:
            raise BadDocumentationError(
                f"Docstring for '{node_name}' does not contain 'Args:' "
                "but the callable has arguments."
            )

    # Docstring contains 'Returns:', or 'Examples:'
    for keyword in ['Returns:', "Examples:"]:
        if keyword not in docstring:
            raise BadDocumentationError(f"Docstring for '{node_name}' does not contain '{keyword}'.")
    return


def raise_on_bad_callable_code_quality(path: Path) -> None:
    """
    Ensure the code quality by checking for placeholder or mock code that should be implemented.
    
    Args:
        path: Path to the Python file to analyze.
        
    Raises:
        NotImplementedError: If the file contains fake or mocked code that needs implementation.
    """
    with open(path.resolve(), 'r') as f:
        code = f.read()

    # NOTE We purposefully don't used `ast` here because it strips out comments.
    for fake_code in [
        "In a real implementation", "In a real scenario", "For testing purposes",
        "In production", "For now", "For demonstration", "In case",
    ]:
        if fake_code in code:
            raise NotImplementedError("This file contains fake code that needs to be removed or implemented.")

    for mocked_code in [
        "mock", "mocked", "mocking", "Mock", "Mocked",
        "Mocking", "Mocked code", "Mocking behavior",
        "Mocked function", "Mocked class", "Mocked method",
    ]:
        if mocked_code in code:
            raise NotImplementedError(
                "This file contains mocked code that needs to be replaced with actual implementations."
            )

