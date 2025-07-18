"""
Utility functions for testing the quality of Python code and its metadata.

These are meant so ensure the LLM-generated code has a unified style and quality,
making it easier for developers and other LLMs to understand, test, use, and maintain.

These functions check for:
- The quality of callable objects' metadata. This includes:
    - Detailed, Google-style docstrings.
    - Detailed signatures with type hints and return annotations.
- The quality of callable objects' code. This includes:
    - No intentionally fake or simplified code (e.g., "In a real implementation, ...")
    - No mocked objects or placeholders that are not explicitly marked as such.
    - Unnecessary fallbacks that clutters the codebase and make it harder to test and debug.
"""

import ast
from pathlib import Path


class FalsifiedCodeError(NotImplementedError):
    """Custom exception for falsified code."""
    pass

class UnlabeledMockError(NotImplementedError):
    """Custom exception for unlabeled mocks."""
    pass

class UnlabeledPlaceholderError(NotImplementedError):
    """Custom exception for unlabeled placeholders."""
    pass

class SilentlyIgnoredErrorsError(NotImplementedError):
    """Custom exception for code that silently ignores errors."""
    pass



class UnnecessaryFallbackError(Exception):
    """Custom exception for unnecessary fallback code."""
    pass

class BadDocumentationError(Exception):
    """Custom exception for bad documentation."""
    pass

class BadSignatureError(Exception):
    """Custom exception for bad function signatures."""
    pass




def get_ast_tree(input_path: Path) -> ast.Module:
    """Read and parse the Python file for its AST tree."""
    input_path = Path(input_path)
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
        if isinstance(node, ast.FunctionDef):
            raise_on_bad_signature(node)
            raise_on_bad_docstring(node, tree)
        elif isinstance(node, ast.ClassDef):
            raise_on_bad_docstring(node, tree)


def raise_on_bad_signature(node) -> None:
    """
    Validate the signature of a callable object and raise errors for bad patterns.
    
    This function checks a callable's signature for common issues including:
    - Parameters with default values but no type annotations
    - Parameters without type annotations (excluding 'self' and 'cls')
    - Missing return type annotation
    - Missing type annotations for keyword-only arguments
    - Missing type annotations for *args and **kwargs
    
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
            - A keyword-only argument lacks a type annotation
            - *args or **kwargs lack type annotations
    """
    node_name = node.name if hasattr(node, 'name') else 'module'

    # Check for default values in parameters
    # defaults list corresponds to the last len(defaults) parameters
    defaults = node.args.defaults
    args = node.args.args
    
    if defaults:
        # Map defaults to their corresponding arguments
        num_defaults = len(defaults)
        args_with_defaults = args[-num_defaults:]
        
        for arg in args_with_defaults:
            if arg.annotation is None:
                raise BadSignatureError(
                    f"Callable '{node_name}' has a parameter '{arg.arg}' with a default value but no type annotation."
                )

    # Check for default values in keyword-only parameters
    kw_defaults = node.args.kw_defaults
    kwonly_args = node.args.kwonlyargs
    
    if kw_defaults and kwonly_args:
        for i, (arg, default) in enumerate(zip(kwonly_args, kw_defaults)):
            if default is not None and arg.annotation is None:
                raise BadSignatureError(
                    f"Callable '{node_name}' has a keyword-only parameter '{arg.arg}' with a default value but no type annotation."
                )

    # Check for type annotations in regular parameters
    for arg in args:
        if arg.annotation is None and arg.arg not in ['self', 'cls']:
            raise BadSignatureError(
                f"Callable '{node_name}' has a parameter '{arg.arg}' without a type annotation."
            )

    # Check for type annotations in keyword-only parameters
    for arg in kwonly_args:
        if arg.annotation is None:
            raise BadSignatureError(
                f"Callable '{node_name}' has a keyword-only parameter '{arg.arg}' without a type annotation."
            )

    # Check for type annotation on *args
    if node.args.vararg and node.args.vararg.annotation is None:
        raise BadSignatureError(
            f"Callable '{node_name}' has *{node.args.vararg.arg} without a type annotation."
        )

    # Check for type annotation on **kwargs
    if node.args.kwarg and node.args.kwarg.annotation is None:
        raise BadSignatureError(
            f"Callable '{node_name}' has **{node.args.kwarg.arg} without a type annotation."
        )

    # Check for return annotation
    if node.returns is None:
        raise BadSignatureError(
            f"Callable '{node_name}' does not have a return type annotation."
        )

    return


def raise_on_bad_docstring(node, tree: ast.AST) -> None:
    """
    Validate that a node has a proper docstring with required sections.
    
    Args:
        node: The AST node to check for docstring quality.
        tree: The full AST tree for context when checking for raises.
        
    Raises:
        BadDocumentationError: If the docstring is missing, too short, or lacks required sections.
    """
    if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return

    word_length = 50
    node_name = node.name

    docstring = ast.get_docstring(node)
    if not docstring:
        raise BadDocumentationError(f"Docstring for '{node_name}' is empty or missing.")

    # Docstring is at least 50 words long
    word_count = len(docstring.split())
    if word_count <= word_length:
        raise BadDocumentationError(
            f"Docstring for '{node_name}' is less than {word_length} words long. Current length: {word_count} words."
        )

    # Check the function body for exceptions (only for functions, not classes)
    raise_exists = False
    if isinstance(node, ast.FunctionDef):
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Raise):
                raise_exists = True
                break

    # Docstring contains "Raises:" if exceptions exist in the function body
    if raise_exists and not any(keyword in docstring for keyword in ['Raises:', 'Raise:']):
        raise BadDocumentationError(
            f"Docstring for '{node_name}' is missing 'Raises:' section "
            "but exceptions are raised in the callable body."
            f"{docstring}"
        )

    # Docstring contains "Args:" if there are arguments (only check for functions)
    if isinstance(node, ast.FunctionDef):
        # Create a copy of args list and remove "self" and "cls" from consideration
        filtered_args = [arg for arg in node.args.args if arg.arg not in ['self', 'cls']]
        kwonly_args = node.args.kwonlyargs
        has_vararg = node.args.vararg is not None
        has_kwarg = node.args.kwarg is not None
        
        # Check if function has any arguments that should be documented
        has_documentable_args = bool(filtered_args or kwonly_args or has_vararg or has_kwarg)

        if has_documentable_args:
            if 'Args:' not in docstring:
                raise BadDocumentationError(
                    f"Docstring for '{node_name}' does not contain 'Args:' "
                    "but the callable has arguments."
                    "{docstring}"
                )

    # Docstring contains 'Returns:', or 'Examples:'
    if isinstance(node, ast.FunctionDef):
        if node.name in ['__init__', '__new__', '__post_init__']:
            # Initialization methods like __init__, __new__, and __post_init__ do not require 'Returns:'
            pass

        # NOTE: Due to the raise_on_bad_signature function, we already know that
        # if it's a function, the return type is annotated, so we can safely check for 'Returns:'
        if node.returns.id != 'None' and 'Returns:' not in docstring:
            raise BadDocumentationError(
                f"Docstring for '{node_name}' in does not contain 'Returns:' section "
                f"{docstring}"
            )
    # NOTE This affects classes as well, but we don't check for return types in classes.
    if 'Examples:' in docstring or 'Example:' in docstring:
        return
    else:
        raise BadDocumentationError(
            f"Docstring for '{node_name}' does not contain 'Example' section "
            f"{docstring}"
        )

def raise_on_bad_callable_code_quality(path: Path) -> None:
    """
    Validate code quality by detecting placeholder, mock, or falsified implementations.

    This function analyzes Python source code to identify patterns that indicate
    incomplete, fake, or production-unready code. It checks for specific phrases
    and patterns commonly used in LLM-generated code that signal placeholder
    implementations, mock objects, or simplified code that needs replacement.

    The function performs several quality checks:
    - Detects falsified code patterns (e.g., "In a real implementation")
    - Identifies unlabeled mock code outside of test contexts
    - Finds unnecessary fallback implementations
    - Catches silently suppressed errors

    Files containing mock indicators in their path ("mock", "placeholder", "stub", 
    "example") are exempt from certain checks, as they are expected to contain
    placeholder code.

    Args:
        path: Path to the Python file to analyze for code quality issues.
        
    Raises:
        FalsifiedCodeError: If the file contains fake or simplified code patterns
            that indicate incomplete implementation.
        UnlabeledMockError: If the file contains mock code outside of test files
            or files with mock indicators in their path.
        UnnecessaryFallbackError: If the file contains unnecessary fallback code
            that should be removed or raise appropriate errors.
        SilentlyIgnoredErrorsError: If the file contains code that purposefully
            suppresses or ignores errors without proper logging or handling.

    Examples:
        >>> # Check a production file for code quality issues
        >>> raise_on_bad_callable_code_quality(Path("src/module.py"))
        
        >>> # Mock files are exempt from certain checks
        >>> raise_on_bad_callable_code_quality(Path("tests/mock_data.py"))
    """
    path = Path(path)
    # NOTE We purposefully don't include "tests" here, 
    # as test implementations can be faked as well.
    mock_indicators = [ 
        "mock", "placeholder", "stub", "example"
    ]
    full_path = str(path.resolve())

    with open(path.resolve(), 'r') as f:
        code = f.read()

    # NOTE We purposefully don't used `ast` here because it strips out comments.
    for fake_code in [
        "In a real implementation", "In a real scenario", "For testing purposes",
        "In production", "For now", "For demonstration", "In case",
        "In a full implementation", "simplified", "This would be",
        "depends on", "can be"
    ]:
        if fake_code in code:
            for indicator in mock_indicators:
                if indicator in full_path:
                    break
            raise FalsifiedCodeError(
                "This file contains fake code that needs to be removed or implemented."
                "Replace it with code that is ready for production use."
            )

    for mocked_code in [
        "mock", "mocked", "mocking", "Mock", "Mocked",
        "Mocking", "Mocked code", "Mocking behavior",
        "Mocked function", "Mocked class", "Mocked method",
    ]:
        if mocked_code in code:
            for indicator in mock_indicators:
                if indicator in full_path:
                    break
            if "test" not in full_path:
                raise UnlabeledMockError(
                    "This file contains code that is mocked or intended to be mocked."
                    "Replace this code with actual implementations"
                    'or move it to a file with "mock", "placeholder", "stub", "example" in the file path.'
                )
        
    fallback_indicators = [
        "mock", "placeholder", "stub", "example", "backup", "fallback"
    ]

    for fallback in [
        "fallback", "fallbacks", "Fallback", "Fallbacks",
        #"backup", "backups", "backup code", "backup implementation",
        #"Backup code", "Backup implementation",
    ]:
        if fallback in code:
            for indicator in fallback_indicators:
                if indicator in full_path:
                    break
            raise UnnecessaryFallbackError(
                "This file contains unnecessary fallback code."
                "This code must be removed or raise an appropriate error."
            )
        
    for suppressed_error in [
        "silently", "silently", "ignore errors", "ignore exceptions",
        "ignore error", "ignore exception", "suppress errors",
    ]:
        if suppressed_error in code:
            for indicator in fallback_indicators:
                if indicator in full_path:
                    break
            raise SilentlyIgnoredErrorsError(
                "This file contains errors that are purposefully suppressed or ignored."
                "All errors must be explicitly logged or raised."
            )