"""
“Tests should be coupled to the behavior of code and decoupled from the structure of code” — Kent Beck

"""
import ast
from pathlib import Path
from typing import Generator, Optional
import sys


import pytest


try:
    import nltk
except ImportError:
    raise ImportError("nltk is required for this test suite. Please install it using 'pip install nltk'.")


_TEST_DIR = Path().cwd / "tests" / "unit_tests"


def _get_test_files_in_dir(dir_path) -> Generator[tuple[ast.AST, Path], None, None]:
    """
    Extracts the AST from a given Python file.
    
    Args:
        file_path (str): Path to the Python file.
    
    Returns:
        ast.AST: The abstract syntax tree of the file.
    """
    try:
        paths = Path(dir_path)
    except Exception as e:
        raise TypeError(f"Invalid path provided: {dir_path}. Error: {e}") from e

    if not paths.exists() or not paths.is_dir():
        raise ValueError(f"Provided path '{dir_path}' is not a valid directory.")

    for file in paths.rglob("*.py"):
        if file.is_file() and (file.name.startswith("__") or file.name == "main.py"):
            continue
        try:
            with open(file.resolve(), 'r') as f:
                code = f.read()

            if not code.strip():
                continue  # Skip empty files

            yield ast.parse(code), file.resolve()

        except SyntaxError as e:
            print(f"Syntax error in file {file.name}: {e}")
        except Exception as e:
            raise RuntimeError(f"Error processing file {file.name}: {e}") from e
    else:
        raise FileNotFoundError(f"No valid Python files found in directory: {dir_path}")


def _get_section_of_ast(
        tree: ast.AST, 
        section_name: Optional[str] = None,
        *, 
        type_: tuple[type,...],
        ) -> list[ast.AST]:

    nodes = [node for node in ast.walk(tree) if isinstance(node, type_)]
    if not section_name:
        return nodes

    nodes = [
        node for node in nodes 
        if hasattr(node, 'name') 
        and node.name == section_name
    ]
    return nodes


def _get_test_classes_from_ast(tree) -> list[ast.ClassDef]:
    """Extracts all classes from an AST.

    Args:
        tree (ast.AST): The abstract syntax tree to extract classes from.

    Returns:
        list: A list of class names found
    """
    return _get_section_of_ast(tree,type_=(ast.ClassDef,), section_name="Test")


def _get_test_functions_from_ast(tree) -> list[ast.FunctionDef]:
    """Extracts all test functions from an AST.

    Args:
        tree (ast.AST): The abstract syntax tree to extract functions from.

    Returns:
        list: A list of function names found
    """
    return _get_section_of_ast(tree,type_=(ast.FunctionDef, ast.AsyncFunctionDef), section_name="test_")


def _get_all_attributes_from_ast(tree) -> list[ast.Attribute]:
    """Extracts all attributes from an AST.

    Args:
        tree (ast.AST): The abstract syntax tree to extract attributes from.

    Returns:
        list: A list of attribute names found
    """
    return _get_section_of_ast(tree, type_=(ast.Attribute,))



def _get_test_file_components(dir_path, *, component_type: str) -> Generator[ast.AST]:

    def _these(tree, name, *args):
        if tree and component_type == name:
            for item in tree:
                yield item, *args, file

    for code, file in _get_test_files_in_dir(dir_path):
        file = file.resolve()
        test_classes = _get_test_classes_from_ast(code)
        yield from _these(test_classes, "test_classes", file)

        for class_ in test_classes:
            test_methods = _get_test_functions_from_ast(class_)
            yield from _these(test_methods, "test_methods", class_.name, file)

            for method in test_methods:
                test_method_attributes = _get_all_attributes_from_ast(method)
                yield from _these(test_method_attributes, "test_method_attributes", file, method.name, class_.name)


def assert_msg(method: ast.FunctionDef, cls_name: str, file_path: Path) -> str:
    """Generates a descriptive message for an assertion in a test method."""
    return f"{assert_msg(method, cls_name, file_path)} "


def _local_imports_from_file(file_path: Path) -> list[str]:
    """Extracts local imports from a Python file.

    Analyzes a Python source file and identifies imports that are local to the project,
    excluding built-in modules and external library imports.

    Args:
        file_path (Path): The path to the Python file to analyze.

    Returns:
        list[str]: A list of local import names found in the file. Each string
                   represents a module or package name that is imported locally
                   within the project structure.

    Raises:
        FileNotFoundError: If the specified file path does not exist.
        PermissionError: If the file cannot be read due to permission restrictions.
        SyntaxError: If the Python file contains invalid syntax that prevents parsing.

    Example:
        >>> from pathlib import Path
        >>> file_path = Path("src/my_module.py")
        >>> local_imports = _local_imports_from_file(file_path)
        >>> print(local_imports)
        ['utils.helpers', 'config.settings', 'models.user']
    """
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except PermissionError as e:
        raise PermissionError(f"Permission denied reading file: {file_path}") from e

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        raise SyntaxError(f"Syntax error in file {file_path}: {e}") from e

    local_imports = []

    def _is_local_import(module_name: str) -> bool:
        """Check if a module is a local import (not built-in or external library)."""
        if not module_name:
            return False
            
        # Get the top-level module name
        top_level = module_name.split('.')[0]
        
        # Check if it's a built-in module
        if top_level in sys.builtin_module_names:
            return False
            
        # Try to import and check if it's in site-packages (external library)
        try:
            __import__(top_level)
            module = sys.modules.get(top_level)
            if module and hasattr(module, '__file__') and module.__file__:
                return 'site-packages' not in str(module.__file__)
        except ImportError:
            # If import fails, assume it's a local module
            return True
            
        return True

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_local_import(alias.name):
                    local_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _is_local_import(node.module):
                local_imports.append(node.module)

    return list(set(local_imports))  # Remove duplicates





@pytest.mark.parametrize(
    "attr, method_name, cls_name, file_path",
    [tup for tup in _get_test_file_components(_TEST_DIR, component_type="test_method_attributes")],
)
def test_that_test_only_interacts_with_public_methods(attr, method_name, cls_name,  file_path):
    """All tests interact only with public methods"""
    attr_name: str = attr.attr
    assert not attr_name.startswith("_"), f"Test '{method_name}' in class '{cls_name}' in {file_path} accesses private attribute '{attr}'."


@pytest.mark.parametrize(
    "method, cls_name, file_path",
    [tup for tup in _get_test_file_components(_TEST_DIR, component_type="test_methods")],
)
class TestThatTestsDoNotRelyOnMockingAtTestTime:

    def test_that_test_does_not_call_patch(self, method, cls_name, file_path):
        """Tests that a test does not call 'patch' or its variants"""
        banned_string = "patch"
        assert banned_string not in ast.unparse(method), \
            f"{assert_msg(method, cls_name, file_path)} uses '{banned_string}' or variant."

    def test_that_test_does_not_call_assert_called(method, cls_name, file_path):
        """Tests that a test does not call 'assert_called' or its variants"""
        banned_string = "assert_called"
        assert banned_string not in ast.unparse(method), \
            f"{assert_msg(method, cls_name, file_path)} uses '{banned_string}' or variant."





@pytest.mark.parametrize(
    "method, cls_name, file_path",
    [tup for tup in _get_test_file_components(_TEST_DIR, component_type="test_methods")],
)
class TestThatTestsFollowBestPracticesWithAssertions:

    MAX_NUMBER_OF_CALLS = 1
    MIN_NUMBER_OF_CHARACTERS = 10

    @staticmethod
    def _get_assertions(method: ast.FunctionDef) -> list[ast.Assert]:
        """Extracts assertion calls from a test method."""
        return [
            node for node in ast.walk(method) if isinstance(node, ast.Assert) 
        ]


    def test_that_test_only_has_one_assertion(self, method, cls_name, file_path):
        """Test that a test method contains exactly one assertion."""
        assertion_calls = self._get_assertions(method)

        assert len(assertion_calls) == self.MAX_NUMBER_OF_CALLS, \
            f"{assert_msg(method, cls_name, file_path)} has multiple assertions. Split these into separate tests."


    def test_that_test_has_documented_assertions(self, method, cls_name, file_path):
        """Test that a test has assertions with descriptive messages (e.g. avoids 'test roulette')"""
        assertion = self._get_assertions(method)[0]

        assert assertion.msg is not None, \
            f"{assert_msg(method, cls_name, file_path)} has an assertion without a message at line {assertion.lineno}."


    def test_that_test_assertion_message_is_descriptive(self, method, cls_name, file_path):
        """Test that a test's assertion message is descriptive and not just 'assert True'."""
        assertion = self._get_assertions(method)[0]

        assert isinstance(assertion.msg, str), \
            f"{assert_msg(method, cls_name, file_path)} has an assertion with a non-string message at line {assertion.lineno}."


    def test_that_test_assertion_message_meets_minimum_length_requirement(self, method, cls_name, file_path):
        """Test that a test's assertion message is long enough to be descriptive."""
        assertion = self._get_assertions(method)[0]

        assert len(assertion.msg) > self.MIN_NUMBER_OF_CHARACTERS, \
            f"{assert_msg(method, cls_name, file_path)} has an assertion"\
            f"with a message less than {self.MIN_NUMBER_OF_CHARACTERS} at line {assertion.lineno}."


@pytest.mark.parametrize(
    "method, cls_name, file_path",
    [tup for tup in _get_test_file_components(_TEST_DIR, component_type="test_methods")],
)
class TestThatTestsFollowWhenThenFormat:
    """
    Tests that test methods follow the 'when_then' naming convention.
    
    NOTE: This is rather pedantic, but LLMs have a habit of finding every which way to NOT confirm to best practices
    if it goes against their training data.
    """

    REQUIRED_STRINGS = ["when", "then"]


    def _check_if_list_contains_required_string(self, method: ast.FunctionDef) -> list[str]:
        """Check if the method name contains the required string."""
        name_parts = method.name.split('_')
        return [s for s in self.REQUIRED_STRINGS if s not in name_parts]

    @staticmethod
    def _get_callable_under_test_from_method_body(method: ast.FunctionDef) -> Optional[str]:
        """Extract the name of the callable being tested from the method body."""
        # Look for function calls in the method body
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                match node.func:
                    case ast.Name():
                        # Direct function call: func_name()
                        return node.func.id.lower()
                    case ast.Attribute():
                        # Method call: obj.method_name()
                        attr_name = node.func.attr.lower()
                        return attr_name.split('.')[1] # Get the method name after the object
                    case _:
                        continue
        # If no function calls found, return None
        return None


    def _contains_callable_variations(self, callable_name: str) -> bool:
        """Check if the callable name contains variations of the callable."""
        callable_variations = [callable_name, callable_name.replace('_', ''),]
        return any(variation in callable_name for variation in callable_variations)


    def tests_that_test_has_when_in_its_name(self, method, cls_name, file_path):
        """Test that a test has 'when' in its name."""
        required_string = "when"
        name_parts = method.name.split('_')

        assert required_string in name_parts, \
            f"{assert_msg(method, cls_name, file_path)} does not contain 'when' in its name."\
            "Use 'when' to describe the condition being tested."


    def tests_that_test_has_then_in_its_name(self, method, cls_name, file_path):
        """Test that a test has 'then' in its name."""
        required_string = "then"
        name_parts = method.name.split('_')

        assert required_string in name_parts, \
            f"{assert_msg(method, cls_name, file_path)} does not contain 'then' in its name."\
            "Use 'then' to describe the expected outcome of the test."


    def test_that_test_has_when_and_then_in_its_name(self, method, cls_name, file_path):
        """Test that a test has both 'when' and 'then' in its name."""
    
        missing_strings = self._check_if_list_contains_required_string(method)

        assert not missing_strings, \
            f"{assert_msg(method, cls_name, file_path)} is missing {missing_strings} in its name. "\
            "Use 'when' to describe the condition being tested and 'then' to describe the expected outcome."


    def test_that_tests_name_does_not_end_with_when_or_then(self, method, cls_name, file_path):
        """Test that a test does not end with 'when' or 'then'."""
        forbidden_endings = ["when", "then"]
        name_parts = method.name.split('_')

        assert name_parts[-1] not in forbidden_endings, \
            f"{assert_msg(method, cls_name, file_path)} ends with '{name_parts[-1]}'. "\
            "Do not end test names with 'when' or 'then'. Use them to describe the condition and expected outcome."


    def test_that_tests_name_does_not_have_then_before_when(self, method, cls_name, file_path):
        """Test that a test has 'then' before 'when' in its name."""
        name_parts = method.name.split('_')
        when_index = name_parts.index("when")
        then_index = name_parts.index("then")

        assert then_index < when_index, \
            f"{assert_msg(method, cls_name, file_path)} has 'then' after 'when'. "\
            "Ensure 'then' comes before 'when' to maintain the correct order of conditions and outcomes."


    def test_that_tests_name_is_not_just_test_when_then(self, method, cls_name, file_path):
        """
        Test that a test's name is not just 'test_when_then'.
        
        Special test case to catch if the LLM is trying to game this test class.
        """
        test_when_then = "test_when_then"

        assert method.name != test_when_then, \
            f"{assert_msg(method, cls_name, file_path)} has the generic name '{test_when_then}'. "\
            "You are CLEARLY trying to game this test suite." \
            "\nListen to your User and write a test name in the fucking right format damnit!"


    def test_that_tests_name_contains_callables_name(self, method, cls_name, file_path):
        """Test that a test's name contains the name of the callable being tested."""
        callable_under_test = self._get_callable_under_test_from_method_body(method)

        assert self._contains_callable_variations(callable_under_test.lower()), \
            f"{assert_msg(method, cls_name, file_path)} does not contain " \
            f"the name of the callable being tested ('{callable_under_test}'). " \
            f"Test names must contain the name of the function/method they are testing."



@pytest.mark.parametrize(
    "method, cls_name, file_path",
    [tup for tup in _get_test_file_components(_TEST_DIR, component_type="test_methods")],
)
class TestThatTestsDoNotContainConditionalTestLogic:


    COMMAND_MSG =  "\nTests must not contain conditional logic. Move control logic into helper methods, or use different/parameterized tests."


    def _types_in_method(self, method: ast.FunctionDef) -> list[ast.If]:
        """Extracts ast classes from a test method."""
        return [node for node in ast.walk(method)]


    def test_that_test_does_not_contain_an_if_statement(self, method, cls_name, file_path):
        """Test that a test contains an if statement"""

        assert ast.If not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains an 'if' statement." + self.COMMAND_MSG


    def test_that_test_does_not_contain_a_try_except_block(self, method, cls_name, file_path):
        """Test that a test does not contain a try-except block."""

        assert ast.ExceptHandler not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains a 'try-except' block." + self.COMMAND_MSG


    def test_that_test_does_not_contain_a_for_loop(self, method, cls_name, file_path):
        """Test that a test does not contain a for loop."""

        assert ast.For not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains a 'for' loop." + self.COMMAND_MSG


    def test_that_test_does_not_contain_and_statements(self, method, cls_name, file_path):
        """Test that a test does not contain 'and' statements."""

        assert ast.And not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains and 'and' statement." + self.COMMAND_MSG


    def test_that_test_does_not_contain_or_statements(self, method, cls_name, file_path):
        """Test that a test does not contain 'or' statements."""

        assert ast.Or not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains an 'or' statement." + self.COMMAND_MSG


    def test_that_test_does_not_contain_match_cases(self, method, cls_name, file_path):
        """Test that a test does not contain match cases statements."""

        assert ast.Match not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains a 'match' statement." + self.COMMAND_MSG


    def test_that_test_does_not_contain_break_statements(self, method, cls_name, file_path):
        """Test that a test does not contain break statements."""

        assert ast.Break not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains a 'break' statement." + self.COMMAND_MSG


    def test_that_test_does_not_contain_continue_statements(self, method, cls_name, file_path):
        """Test that a test does not contain continue statements."""

        assert ast.Continue not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains an 'continue' statement." + self.COMMAND_MSG


    def test_that_test_does_not_contain_while_loops(self, method, cls_name, file_path):
        """Test that a test does not contain while loops."""

        assert ast.While not in self._types_in_method(method), \
            f"{assert_msg(method, cls_name, file_path)} contains an 'while' loop." + self.COMMAND_MSG



@pytest.mark.parametrize(
    "method, cls_name, file_path",
    [tup for tup in _get_test_file_components(_TEST_DIR, component_type="test_methods")],
)
class TestThatTestsDoNotContainMagicNumbersOrStrings:

    ASSERTION_MSG = f"Assign literals to named constants/variables and test against those instead for better readability and maintainability."

    def _contains_literals(self, method: ast.FunctionDef, types: tuple[type,...]) -> bool:
        """Extracts numeric literals from a test method."""
        literals = []
        for node in ast.walk(method):
            if isinstance(node, ast.Assert):
                literals.append(n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, types))
        return True if len(literals) else False

    def test_that_test_does_not_assert_against_string_literals(self, method, cls_name, file_path):
        """Test that a test does not test against string literals (e.g. magic strings)."""

        assert not self._contains_literals(method, (str,)), \
            f"{assert_msg(method, cls_name, file_path)} contains string literals. " + self.ASSERTION_MSG
            

    def test_that_test_does_not_assert_against_numeric_literals(self, method, cls_name, file_path):
        """Test that a test does not test against numeric literals (e.g. magic numbers)."""

        assert not self._contains_literals(method, (int, float, complex)), \
            f"{assert_msg(method, cls_name, file_path)} contains numeric literals. " + self.ASSERTION_MSG









if __name__ == "__main__":
    pytest.main([__file__, "-v"])
