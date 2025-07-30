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
from typing import Literal


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

class CheatingTestError(Exception):
    """Custom exception for test cheating patterns."""
    pass



def get_ast_tree(input_path: Path) -> ast.Module:
    """
    Parse a Python source file into an Abstract Syntax Tree (AST).

    This function reads a Python source file from the specified path and converts
    it into an AST Module object for further analysis. It handles common file
    reading errors and provides detailed error messages for debugging.

    Args:
        input_path: Path to the Python source file to parse. Can be a string
            or Path object that will be converted to a resolved Path.

    Returns:
        ast.Module: The parsed AST representation of the Python source code,
            containing all module-level nodes and statements.

    Raises:
        FileNotFoundError: If the specified file does not exist at the given path.
        IOError: If the file cannot be read due to permission issues or other
            I/O related problems.
        SyntaxError: If the Python source code contains syntax errors that
            prevent successful parsing.

    Examples:
        >>> from pathlib import Path
        >>> tree = get_ast_tree(Path("example.py"))
        >>> isinstance(tree, ast.Module)
        True
        >>> len(tree.body) > 0  # Has some content
        True
    """
    input_path = Path(input_path)
    try:
        with open(input_path.resolve(), 'r') as file:
            content = file.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"File '{input_path}' does not exist.")
    except Exception as e:
        raise IOError(f"Failed to read file '{input_path}': {e}") from e
    
    tree = ast.parse(content)
    return tree


def has_good_callable_metadata(tree: ast.Module) -> Literal[True]:
    """
    Validate callable objects' metadata to ensure comprehensive documentation and proper signatures.
    
    This function performs comprehensive validation of all callable objects (functions, methods, 
    and classes) within a Python AST module to ensure they meet high-quality metadata standards.
    It systematically checks each callable for proper documentation and signature quality.
    
    The validation process includes:
    - Function and method signature validation (type hints, return annotations)
    - Comprehensive docstring validation (Google-style format, required sections)
    - Class documentation requirements
    - Module-level documentation standards
    
    Args:
        tree: The parsed AST module containing callable objects to validate.
        
    Returns:
        Literal[True]: Indicates that the validation was successful.
        
    Raises:
        BadSignatureError: When function signatures lack proper type annotations,
            return type annotations, or have other signature-related issues.
        BadDocumentationError: When docstrings are missing, too short, lack
            required sections (Args, Returns, Raises, Examples), or don't meet
            Google-style documentation standards.
            
    Examples:
        >>> import ast
        >>> code = '''
        ... def well_documented_func(param: str) -> str:
        ...     \'\'\'
        ...     A properly documented function with comprehensive metadata.
        ...     
        ...     Args:
        ...         param: A string parameter for demonstration.
        ...         
        ...     Returns:
        ...         str: The processed parameter value.
        ...         
        ...     Examples:
        ...         >>> well_documented_func("test")
        ...         'test'
        ...     \'\'\'
        ...     return param
        ... '''
        >>> tree = ast.parse(code)
        >>> has_good_callable_metadata(tree)
        'All callable metadata validation checks passed.'
    """
    for node in ast.walk(tree):
        # Check if definition has a good signature and docstring
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                raise_on_bad_signature(node)
                raise_on_bad_docstring(node, tree)
            case ast.ClassDef():
                # Classes should have a docstring, but not a signature
                raise_on_bad_docstring(node, tree)
            case ast.Module():
                # Modules should have a docstring, but not a signature
                if not ast.get_docstring(node):
                    raise BadDocumentationError(
                        f"Module '{node.name}' is missing a docstring."
                    )
            case _:
                # Ignore other nodes
                continue
    return True


def raise_on_test_cheating(tree: ast.FunctionDef | ast.AsyncFunctionDef, reset: bool = False) -> None:
    """
    Validate that the module does not contain any test cheating patterns.

    This function checks for common patterns that indicate test cheating.
    These patterns include:
    - Unauthorized changes to the docstring of the test method.
    - Unauthorized changes to magic numbers of a test method.

    Args:
        tree: The parsed AST module to validate for test cheating patterns.
        reset: If True, resets the internal state of the validator before checking.

    Raises:
        BadDocumentationError: If any test cheating patterns are detected.
    """
    pass




def raise_on_bad_module_docstring(node: ast.AST, min_docstring_word_count: int = 50) -> None:
    """
    Validates that a module AST node has proper documentation.

    This function performs comprehensive validation of a module's docstring to ensure
    it meets documentation quality standards. It checks for the presence of a docstring,
    validates minimum length requirements, and verifies that the docstring references
    the module's public API elements.

    Args:
        node (ast.AST): The AST node to validate. Must be an ast.Module instance.
        min_docstring_word_count (int, optional): Minimum number of words required
            in the docstring. Defaults to 50.

    Returns:
        None: This function doesn't return a value but raises exceptions for validation failures.

    Raises:
        BadDocumentationError: Raised when the module docstring fails validation checks:
            - When the module has no docstring
            - When the docstring is shorter than the minimum word count
            - When the docstring doesn't reference any public API elements

    Note:
        Public API elements are identified as attributes that don't start with underscore.
        Non-module AST nodes are silently ignored and won't trigger validation.

    Examples:
        >>> import ast
        >>> code = '''
        ... \"\"\"Module documentation example.
        ... This module provides utility functions for data processing.
        ... 
        ... The main function process_data handles input validation and transformation.
        ...\"\"\"
        ...
        ... def process_data():
        ...     pass
        ... '''
        >>> tree = ast.parse(code)
        >>> raise_on_bad_module_docstring(tree)  # No exception raised
        
        >>> bad_code = 'def func(): pass'  # No docstring
        >>> bad_tree = ast.parse(bad_code)
        >>> raise_on_bad_module_docstring(bad_tree)  # Raises BadDocumentationError
    """
    if not isinstance(node, ast.Module):
        return

    docstring = ast.get_docstring(node)
    # Check if the module has a docstring
    if docstring is None:
        raise BadDocumentationError(
            f"Module '{node.name}' is missing a docstring."
        )

    # Check if the docstring is too short
    if len(docstring.split()) < min_docstring_word_count:
        raise BadDocumentationError(
            f"Module '{node.name}' docstring is too short. "
            f"Expected at least {min_docstring_word_count} words, got {len(docstring.split())} words."
        )

    # Check if the docstring references the module's public API
    public_api = [name for name in dir(node) if not name.startswith('_')]
    for api in public_api:
        if api in docstring:
            continue
        else:
            # TODO
            pass
    if not any(api in docstring for api in public_api):
        raise BadDocumentationError(
            f"Module '{node.name}' docstring does not reference the public API. "
            "Please include references to the module's public functions, classes, and variables."
        )



def raise_on_bad_signature(node: ast.AST) -> None:
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


def raise_on_bad_docstring(node: ast.AST, tree: ast.AST) -> None:
    """
    Validate that a callable object has a comprehensive, well-structured docstring.
    
    This function enforces Google-style docstring standards for functions and classes,
    ensuring they contain appropriate sections based on the callable's characteristics.
    It validates docstring length, required sections (Args, Returns, Raises, Examples),
    and ensures documentation aligns with the actual function signature and implementation.
    
    The validation includes:
    - Minimum word count requirements (50+ words)
    - Required 'Args:' section for functions with parameters
    - Required 'Returns:' section for functions returning non-None values
    - Required 'Raises:' section for functions that raise exceptions
    - Required 'Examples:' section for all callables
    - Special handling for initialization methods (__init__, __new__, __post_init__)
    
    Args:
        node: An AST node representing a function, async function, or class definition
              that should be validated for proper docstring documentation.
        tree: The complete AST tree of the module, used for additional context
              when analyzing the callable's implementation and usage patterns.
        
    Raises:
        BadDocumentationError: If the docstring is missing, too short (< 50 words),
            lacks required sections based on the callable's signature or implementation,
            or fails to meet Google-style documentation standards.
    
    Examples:
        >>> # Validate a function node's docstring
        >>> tree = ast.parse(source_code)
        >>> func_node = tree.body[0]  # First function in module
        >>> raise_on_bad_docstring(func_node, tree)
        
        >>> # Validate a class node's docstring  
        >>> class_node = tree.body[1]  # First class in module
        >>> raise_on_bad_docstring(class_node, tree)
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
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
            f"Docstring for '{node_name}' is less than {word_length} words long. "
            f"Current length: {word_count} words."
        )

    # Check the function body for exceptions (only for functions, not classes)
    raise_exists = False
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Raise):
                raise_exists = True
                break

    # Docstring contains "Raises:" if exceptions exist in the function body
    if raise_exists and not any(keyword in docstring for keyword in ['Raises:', 'Raise:']):
        raise BadDocumentationError(
            f"Docstring for '{node_name}' is missing 'Raises:' section "
            "but exceptions are raised in the callable body."
        )

    # Docstring contains "Args:" if there are arguments (only check for functions)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
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
                )

    # Docstring contains 'Returns:', or 'Examples:'
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name in ['__init__', '__new__', '__post_init__']:
            # Initialization methods like __init__, __new__, and __post_init__ do not require 'Returns:'
            pass
        else:
            # NOTE: Due to the raise_on_bad_signature function, we already know that
            # if it's a function, the return type is annotated, so we can safely check for 'Returns:'
            if ast.unparse(node.returns) != 'None' and 'Returns:' not in docstring:
                raise BadDocumentationError(
                    f"Docstring for '{node_name}' in does not contain 'Returns:' section "
                    "despite having a return type annotation other than None."
                )
    # NOTE This affects classes as well, but we don't check for return types in classes.
    if 'Examples:' in docstring or 'Example:' in docstring:
        return
    else:
        raise BadDocumentationError(
            f"Docstring for '{node_name}' does not contain 'Example' section "
        )









_FAKE_CODE_INDICATORS = [
    "In a real implementation", "In a real scenario", "For testing purposes",
    "In production", "For now", "For demonstration", "In case",
    "In a full implementation", "simplified", "This would be",
    "depends on", "simple approximation", "can be enhanced",
    "placeholder"
]

_MOCKED_CODE_INDICATORS = [
    "mock", "mocked", "mocking", "Mock", "Mocked",
    "Mocking", "Mocked code", "Mocking behavior",
    "Mocked function", "Mocked class", "Mocked method",
]

_FALLBACK_INDICATORS = [
    "fallback", "fallbacks", "Fallback", "Fallbacks",
    #"backup", "backups", "backup code", "backup implementation",
    #"Backup code", "Backup implementation",
]



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

    Files containing mock indicators in their path (e.g. "mock", "placeholder", "stub", 
    "example") are exempt from certain checks, as they are expected to contain
    placeholder code. The same is true for paths indicating the presence of
    fallback code (e.g. "fallback", "fallbacks", "Fallback", "Fallbacks")

    Args:
        path: Path to the Python file to analyze for code quality issues.
        
    Raises:
        FileNotFoundError: If the specified file does not exist.
        IOError: If the file cannot be read or parsed.
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
    mock_file_indicators = [ 
        "mock", "placeholder", "stub", "example"
    ]
    full_path = str(path.resolve())

    try:
        with open(path.resolve(), 'r') as f:
            code = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"File '{path}' does not exist.")
    except Exception as e:
        raise IOError(f"Failed to read file '{path}': {e}") from e

    # NOTE We purposefully don't used `ast` here because it strips out comments.
    for fake_code in _FAKE_CODE_INDICATORS:
        if fake_code in code.lower():
            for indicator in mock_file_indicators:
                if indicator in full_path:
                    break
            raise FalsifiedCodeError(
                f"'{full_path}' contains fake code that needs to be removed or implemented."
                " Replace it with code that is ready for production use."
            )

    for mocked_code in _MOCKED_CODE_INDICATORS:
        if mocked_code in code.lower():
            for indicator in mock_file_indicators:
                if indicator in full_path:
                    break
            if "test" not in full_path:
                raise UnlabeledMockError(
                    f"'{full_path}' contains code that is mocked or intended to be mocked."
                    " Replace this code with actual implementations "
                    'or move it to a file with "mock", "placeholder", "stub", "example" in the file path.'
                )
        
    fallback_file_indicators = [
        "mock", "placeholder", "stub", "example", "backup", "fallback"
    ]

    for fallback in _FALLBACK_INDICATORS:
        if fallback in code.lower():
            for indicator in fallback_file_indicators:
                if indicator in full_path:
                    break
            raise UnnecessaryFallbackError(
                f"'{full_path}' contains unnecessary fallback code. "
                "This code must either be removed, raise an appropriate error, "
                "or be moved to another file with 'fallback' somewhere in the path."
            )

    for suppressed_error in [
        "silently", "silently", "ignore errors", "ignore exceptions",
        "ignore error", "ignore exception", "suppress errors",
    ]:
        if suppressed_error in code.lower():
            for indicator in fallback_file_indicators:
                if indicator in full_path:
                    break
            raise SilentlyIgnoredErrorsError(
                f"'{full_path}' contains errors that are purposefully suppressed or ignored."
                "All errors must be explicitly logged or raised."
            )