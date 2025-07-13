#!/usr/bin/env python3
import pytest

import unittest
from unittest.mock import Mock, MagicMock, patch, mock_open
import sys
import os
import tempfile
from io import StringIO
from pathlib import Path

# Make sure the input file exists
assert os.path.exists('_extract_classes_from_python_files_stubs.py'), "_extract_classes_from_python_files_stubs.py does not exist at the specified directory."

# Import the function under test
from .._extract_classes_from_python_files_stubs import main
from .._extract_classes_from_python_files_stubs import ClassExtractor


class TestClassExtractorInitialization:
    """Test ClassExtractor initialization and configuration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "test_input.py")
        self.test_content = '''
class TestClass1:
    pass

class TestClass2:
    def method(self):
        pass
'''
        with open(self.test_file, 'w') as f:
            f.write(self.test_content)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_init_with_valid_input_file_and_default_output_dir(self):
        """
        GIVEN a valid input Python file path
        AND no output directory specified (None)
        WHEN ClassExtractor is initialized
        THEN expect:
            - Instance created successfully
            - input_file attribute set to provided path
            - output_dir attribute set to same directory as input file
            - No exceptions raised
        """
        # When
        extractor = ClassExtractor(self.test_file)
        
        # Then
        assert extractor.input_file == self.test_file
        assert extractor.output_dir == os.path.dirname(self.test_file)

    def test_init_with_valid_input_file_and_custom_output_dir(self):
        """
        GIVEN a valid input Python file path
        AND a custom output directory path
        WHEN ClassExtractor is initialized
        THEN expect:
            - Instance created successfully
            - input_file attribute set to provided input path
            - output_dir attribute set to provided output directory
            - No exceptions raised
        """
        # Given
        custom_output_dir = os.path.join(self.temp_dir, "custom_output")
        
        # When
        extractor = ClassExtractor(self.test_file, custom_output_dir)
        
        # Then
        assert extractor.input_file == self.test_file
        assert extractor.output_dir == custom_output_dir

    def test_init_with_nonexistent_input_file(self):
        """
        GIVEN a path to a file that does not exist
        WHEN ClassExtractor is initialized
        THEN expect FileNotFoundError to be raised
        AND error message should indicate file not found
        """
        # Given
        nonexistent_file = "/path/that/does/not/exist.py"
        
        # When/Then
        with pytest.raises(FileNotFoundError):
            ClassExtractor(nonexistent_file)

    def test_init_with_non_python_file_extension(self):
        """
        GIVEN a file path with non-Python extension (e.g., .txt, .js, .java)
        WHEN ClassExtractor is initialized
        THEN expect ValueError to be raised
        AND error message should indicate invalid Python file
        """
        # Given
        non_python_file = os.path.join(self.temp_dir, "test.txt")
        with open(non_python_file, 'w') as f:
            f.write("some content")
        
        # When/Then
        with pytest.raises(ValueError, match="not a Python file"):
            ClassExtractor(non_python_file)

    def test_init_with_directory_instead_of_file(self):
        """
        GIVEN a path that points to a directory instead of a file
        WHEN ClassExtractor is initialized
        THEN expect ValueError to be raised
        AND error message should indicate expected file, not directory
        """
        # When/Then
        with pytest.raises(ValueError, match="expected file, not directory"):
            ClassExtractor(self.temp_dir)

    def test_init_with_empty_string_input_file(self):
        """
        GIVEN an empty string as input_file
        WHEN ClassExtractor is initialized
        THEN expect ValueError to be raised
        AND error message should indicate invalid file path
        """
        # When/Then
        with pytest.raises(ValueError, match="invalid file path"):
            ClassExtractor("")

    def test_init_with_relative_path_input_file(self):
        """
        GIVEN a relative path to a valid Python file
        WHEN ClassExtractor is initialized
        THEN expect:
            - Instance created successfully
            - Path should be properly resolved
            - No exceptions raised
        """
        # Given
        # Create a test file in current directory
        relative_file = "test_relative.py"
        with open(relative_file, 'w') as f:
            f.write("class TestClass:\n    pass\n")
        
        try:
            # When
            extractor = ClassExtractor(relative_file)
            
            # Then
            assert os.path.exists(extractor.input_file)
            assert extractor.input_file.endswith(relative_file)
        finally:
            # Cleanup
            if os.path.exists(relative_file):
                os.remove(relative_file)

    def test_init_with_absolute_path_input_file(self):
        """
        GIVEN an absolute path to a valid Python file
        WHEN ClassExtractor is initialized
        THEN expect:
            - Instance created successfully
            - Path should be properly handled
            - No exceptions raised
        """
        # Given
        absolute_path = os.path.abspath(self.test_file)
        
        # When
        extractor = ClassExtractor(absolute_path)
        
        # Then
        assert extractor.input_file == absolute_path
        assert os.path.isabs(extractor.input_file)


class TestClassExtractorExtractClasses:
    """Test ClassExtractor extract_classes method functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "test_input.py")

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_extract_classes_from_file_with_single_class(self):
        """
        GIVEN a Python file containing exactly one class definition
        WHEN extract_classes is called
        THEN expect:
            - Dictionary returned with one entry
            - Key should be the class name
            - Value should be Path object pointing to created file
            - Created file should contain only that class and its dependencies
            - Created file should be valid Python syntax
        """
        # Given
        single_class_content = '''
class SingleClass:
    def __init__(self):
        self.value = 42
    
    def get_value(self):
        return self.value
'''
        with open(self.test_file, 'w') as f:
            f.write(single_class_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert isinstance(result, dict)
        assert len(result) == 1
        assert "SingleClass" in result
        assert isinstance(result["SingleClass"], Path)
        assert result["SingleClass"].exists()
        
        # Verify file content
        with open(result["SingleClass"], 'r') as f:
            content = f.read()
            assert "class SingleClass:" in content
            assert "def __init__(self):" in content
            assert "def get_value(self):" in content

    def test_extract_classes_from_file_with_multiple_classes(self):
        """
        GIVEN a Python file containing multiple class definitions
        WHEN extract_classes is called
        THEN expect:
            - Dictionary returned with entries for each class
            - Each key should be a class name
            - Each value should be Path object pointing to separate created file
            - Each created file should contain only its respective class
            - All created files should be valid Python syntax
        """
        # Given
        multiple_classes_content = '''
class FirstClass:
    def method_one(self):
        return "first"

class SecondClass:
    def method_two(self):
        return "second"

class ThirdClass:
    def __init__(self, value):
        self.value = value
'''
        with open(self.test_file, 'w') as f:
            f.write(multiple_classes_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert isinstance(result, dict)
        assert len(result) == 3
        assert "FirstClass" in result
        assert "SecondClass" in result
        assert "ThirdClass" in result
        
        # Verify each file exists and contains correct class
        for class_name, file_path in result.items():
            assert isinstance(file_path, Path)
            assert file_path.exists()
            
            with open(file_path, 'r') as f:
                content = f.read()
                assert f"class {class_name}:" in content

    def test_extract_classes_from_file_with_no_classes(self):
        """
        GIVEN a Python file containing no class definitions (only functions, variables, etc.)
        WHEN extract_classes is called
        THEN expect ValueError to be raised
        AND error message should indicate no classes found
        """
        # Given
        no_classes_content = '''
def some_function():
    return "not a class"

SOME_CONSTANT = 42

def another_function(x, y):
    return x + y
'''
        with open(self.test_file, 'w') as f:
            f.write(no_classes_content)
        
        # When/Then
        extractor = ClassExtractor(self.test_file)
        with pytest.raises(ValueError, match="no classes found"):
            extractor.extract_classes()

    def test_extract_classes_with_nested_classes(self):
        """
        GIVEN a Python file containing nested class definitions
        WHEN extract_classes is called
        THEN expect:
            - Dictionary returned with entries for outer classes
            - Nested classes should be included within their parent class file
            - Proper indentation and structure maintained
        """
        # Given
        nested_classes_content = '''
class OuterClass:
    def __init__(self):
        self.value = 1
    
    class InnerClass:
        def __init__(self):
            self.inner_value = 2
        
        def get_inner(self):
            return self.inner_value
    
    def get_outer(self):
        return self.value

class AnotherClass:
    pass
'''
        with open(self.test_file, 'w') as f:
            f.write(nested_classes_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert "OuterClass" in result
        assert "AnotherClass" in result
        
        # Verify nested class is included in outer class file
        with open(result["OuterClass"], 'r') as f:
            content = f.read()
            assert "class OuterClass:" in content
            assert "class InnerClass:" in content
            assert "def get_inner(self):" in content

    def test_extract_classes_with_class_dependencies(self):
        """
        GIVEN a Python file with classes that depend on imports, functions, or constants
        WHEN extract_classes is called
        THEN expect:
            - Each extracted class file includes necessary dependencies
            - Import statements preserved at top of file
            - Required functions and constants included
            - Files remain syntactically valid
        """
        # Given
        dependencies_content = '''
import os
import sys
from typing import List

GLOBAL_CONSTANT = 42

def helper_function(x):
    return x * 2

class DependentClass:
    def __init__(self):
        self.value = GLOBAL_CONSTANT
    
    def process(self, data: List[int]):
        return [helper_function(x) for x in data]
    
    def get_path(self):
        return os.getcwd()
'''
        with open(self.test_file, 'w') as f:
            f.write(dependencies_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert "DependentClass" in result
        
        with open(result["DependentClass"], 'r') as f:
            content = f.read()
            assert "import os" in content
            assert "import sys" in content
            assert "from typing import List" in content
            assert "GLOBAL_CONSTANT = 42" in content
            assert "def helper_function(x):" in content
            assert "class DependentClass:" in content

    def test_extract_classes_with_inheritance(self):
        """
        GIVEN a Python file with classes that inherit from other classes in the same file
        WHEN extract_classes is called
        THEN expect:
            - Base classes included in derived class files
            - Inheritance relationships preserved
            - All files remain syntactically valid
        """
        # Given
        inheritance_content = '''
class BaseClass:
    def __init__(self, name):
        self.name = name
    
    def get_name(self):
        return self.name

class DerivedClass(BaseClass):
    def __init__(self, name, value):
        super().__init__(name)
        self.value = value
    
    def get_value(self):
        return self.value

class AnotherDerived(BaseClass):
    def special_method(self):
        return f"Special: {self.name}"
'''
        with open(self.test_file, 'w') as f:
            f.write(inheritance_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert "BaseClass" in result
        assert "DerivedClass" in result
        assert "AnotherDerived" in result
        
        # Verify base class is included in derived class files
        with open(result["DerivedClass"], 'r') as f:
            content = f.read()
            assert "class BaseClass:" in content
            assert "class DerivedClass(BaseClass):" in content
            assert "super().__init__(name)" in content

    def test_extract_classes_with_decorators(self):
        """
        GIVEN a Python file with classes that have decorators
        WHEN extract_classes is called
        THEN expect:
            - Decorators preserved in extracted class files
            - Decorator dependencies included if local
            - Proper syntax maintained
        """
        # Given
        decorators_content = '''
from dataclasses import dataclass
from functools import wraps

def custom_decorator(cls):
    cls.decorated = True
    return cls

@dataclass
class DataClass:
    field1: str
    field2: int = 0

@custom_decorator
class DecoratedClass:
    def __init__(self):
        self.value = 1
'''
        with open(self.test_file, 'w') as f:
            f.write(decorators_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert "DataClass" in result
        assert "DecoratedClass" in result
        
        # Verify decorators are preserved
        with open(result["DataClass"], 'r') as f:
            content = f.read()
            assert "@dataclass" in content
            assert "from dataclasses import dataclass" in content
        
        with open(result["DecoratedClass"], 'r') as f:
            content = f.read()
            assert "@custom_decorator" in content
            assert "def custom_decorator(cls):" in content

    def test_extract_classes_with_class_methods_and_properties(self):
        """
        GIVEN a Python file with classes containing various method types (static, class, property)
        WHEN extract_classes is called
        THEN expect:
            - All method types preserved in extracted files
            - Method decorators maintained
            - Class structure intact
        """
        # Given
        methods_content = '''
class MethodClass:
    def __init__(self, value):
        self._value = value
    
    @staticmethod
    def static_method():
        return "static"
    
    @classmethod
    def class_method(cls):
        return "class"
    
    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, new_value):
        self._value = new_value
'''
        with open(self.test_file, 'w') as f:
            f.write(methods_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert "MethodClass" in result
        
        with open(result["MethodClass"], 'r') as f:
            content = f.read()
            assert "@staticmethod" in content
            assert "@classmethod" in content
            assert "@property" in content
            assert "@value.setter" in content

    def test_extract_classes_output_file_naming(self):
        """
        GIVEN a Python file with classes
        WHEN extract_classes is called
        THEN expect:
            - Output files named after their respective classes
            - File names are valid and safe for filesystem
            - File extensions are .py
            - No naming conflicts between files
        """
        # Given
        naming_content = '''
class SimpleClass:
    pass

class AnotherClass:
    pass
'''
        with open(self.test_file, 'w') as f:
            f.write(naming_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        for class_name, file_path in result.items():
            assert file_path.name == f"{class_name}.py"
            assert file_path.suffix == ".py"
            assert file_path.stem == class_name

    def test_extract_classes_with_invalid_python_syntax(self):
        """
        GIVEN a Python file with syntax errors
        WHEN extract_classes is called
        THEN expect SyntaxError to be raised
        AND error should indicate the syntax problem
        """
        # Given
        invalid_syntax_content = '''
class BrokenClass:
    def method(self)
        return "missing colon"
    
    def another_method(self):
        invalid syntax here!!!
'''
        with open(self.test_file, 'w') as f:
            f.write(invalid_syntax_content)
        
        # When/Then
        extractor = ClassExtractor(self.test_file)
        with pytest.raises(SyntaxError):
            extractor.extract_classes()

    def test_extract_classes_with_existing_output_files(self):
        """
        GIVEN output directory already contains files with same names as classes
        WHEN extract_classes is called
        THEN expect:
            - Existing files to be overwritten
            - New content written to files
        """
        # Given
        class_content = '''
class ExistingClass:
    def new_method(self):
        return "new content"
'''
        with open(self.test_file, 'w') as f:
            f.write(class_content)
        
        # Create existing file
        existing_file = os.path.join(self.temp_dir, "ExistingClass.py")
        with open(existing_file, 'w') as f:
            f.write("# old content")
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert "ExistingClass" in result
        with open(result["ExistingClass"], 'r') as f:
            content = f.read()
            assert "new_method" in content
            assert "old content" not in content

    def test_extract_classes_with_readonly_output_directory(self):
        """
        GIVEN output directory that is read-only
        WHEN extract_classes is called
        THEN expect PermissionError to be raised
        AND error should indicate permission problem
        """
        # Given
        class_content = '''
class TestClass:
    pass
'''
        with open(self.test_file, 'w') as f:
            f.write(class_content)
        
        readonly_dir = os.path.join(self.temp_dir, "readonly")
        os.makedirs(readonly_dir)
        os.chmod(readonly_dir, 0o444)  # Read-only
        
        try:
            # When/Then
            extractor = ClassExtractor(self.test_file, readonly_dir)
            with pytest.raises(PermissionError):
                extractor.extract_classes()
        finally:
            # Cleanup: restore permissions
            os.chmod(readonly_dir, 0o755)

    def test_extract_classes_return_value_structure(self):
        """
        GIVEN a valid Python file with classes
        WHEN extract_classes is called
        THEN expect:
            - Return value is a dictionary
            - Dictionary keys are strings (class names)
            - Dictionary values are Path objects
            - All Path objects point to existing files
        """
        # Given
        class_content = '''
class FirstClass:
    pass

class SecondClass:
    pass
'''
        with open(self.test_file, 'w') as f:
            f.write(class_content)
        
        # When
        extractor = ClassExtractor(self.test_file)
        result = extractor.extract_classes()
        
        # Then
        assert isinstance(result, dict)
        
        for class_name, file_path in result.items():
            assert isinstance(class_name, str)
            assert isinstance(file_path, Path)
            assert file_path.exists()
            assert file_path.is_file()



class TestMainFunction:
    """Test main function command-line interface and argument parsing."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "test_input.py")
        self.test_content = '''
class TestClass1:
    pass

class TestClass2:
    def method(self):
        pass
'''
        with open(self.test_file, 'w') as f:
            f.write(self.test_content)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_main_with_valid_input_file_only(self):
        """
        GIVEN command line arguments with only input file specified
        WHEN main function is called
        THEN expect:
            - ClassExtractor instantiated with input file and default output directory
            - extract_classes method called
            - Success message printed to stdout
            - Function exits with code 0
        """
        # Given
        test_args = ["script_name", self.test_file]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.return_value = {"TestClass1": Path("TestClass1.py")}
                mock_extractor.output_dir = self.temp_dir
                
                with patch('builtins.print') as mock_print:
                    main()
        
        # Then
        mock_extractor_class.assert_called_once_with(self.test_file, None)
        mock_extractor.extract_classes.assert_called_once()
        mock_print.assert_called()

    def test_main_with_input_file_and_output_directory(self):
        """
        GIVEN command line arguments with input file and output directory specified
        WHEN main function is called
        THEN expect:
            - ClassExtractor instantiated with specified input file and output directory
            - extract_classes method called
            - Success message printed to stdout
            - Function exits with code 0
        """
        # Given
        output_dir = os.path.join(self.temp_dir, "output")
        test_args = ["script_name", self.test_file, "-o", output_dir]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.return_value = {"TestClass1": Path("TestClass1.py")}
                mock_extractor.output_dir = output_dir
                
                with patch('builtins.print') as mock_print:
                    main()
        
        # Then
        mock_extractor_class.assert_called_once_with(self.test_file, output_dir)
        mock_extractor.extract_classes.assert_called_once()
        mock_print.assert_called()

    def test_main_with_verbose_flag(self):
        """
        GIVEN command line arguments with verbose flag enabled
        WHEN main function is called
        THEN expect:
            - Detailed output printed for each extracted class
            - Output includes class name and file path mapping
            - Success message includes count of extracted classes
        """
        # Given
        test_args = ["script_name", self.test_file, "-v"]
        created_files = {
            "TestClass1": Path("TestClass1.py"),
            "TestClass2": Path("TestClass2.py")
        }
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.return_value = created_files
                
                with patch('builtins.print') as mock_print:
                    main()
        
        # Then
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("Successfully extracted 2 classes" in call for call in print_calls)
        assert any("TestClass1 ->" in call for call in print_calls)
        assert any("TestClass2 ->" in call for call in print_calls)

    def test_main_with_no_verbose_flag(self):
        """
        GIVEN command line arguments without verbose flag
        WHEN main function is called
        THEN expect:
            - Brief summary output only
            - No detailed class-by-class information
            - Output includes count and output directory
        """
        # Given
        test_args = ["script_name", self.test_file]
        created_files = {"TestClass1": Path("TestClass1.py")}
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.return_value = created_files
                mock_extractor.output_dir = self.temp_dir
                
                with patch('builtins.print') as mock_print:
                    main()
        
        # Then
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("Extracted 1 classes to" in call for call in print_calls)
        assert not any("TestClass1 ->" in call for call in print_calls)

    def test_main_with_help_argument(self):
        """
        GIVEN command line arguments with --help or -h flag
        WHEN main function is called
        THEN expect:
            - Help message printed to stdout
            - Function exits with code 0
            - No ClassExtractor instantiated
        """
        # Given
        test_args = ["script_name", "--help"]
        
        # When/Then
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                with pytest.raises(SystemExit) as excinfo:
                    main()
                
                assert excinfo.value.code == 0
                mock_extractor_class.assert_not_called()

    def test_main_with_no_arguments(self):
        """
        GIVEN command line with no arguments (just script name)
        WHEN main function is called
        THEN expect:
            - ArgumentParser error raised or help message shown
            - Function exits with non-zero code
            - Error message indicates missing required argument
        """
        # Given
        test_args = ["script_name"]
        
        # When/Then
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit) as excinfo:
                main()
            
            assert excinfo.value.code != 0

    def test_main_with_invalid_input_file(self):
        """
        GIVEN command line arguments with non-existent input file
        WHEN main function is called
        THEN expect:
            - Error message printed to stderr
            - Function exits with code 1
            - Error message mentions the specific exception
        """
        # Given
        invalid_file = "/path/that/does/not/exist.py"
        test_args = ["script_name", invalid_file]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                with pytest.raises(SystemExit) as excinfo:
                    main()
        
        # Then
        assert excinfo.value.code == 1
        stderr_output = mock_stderr.getvalue()
        assert "Error:" in stderr_output

    def test_main_with_permission_error(self):
        """
        GIVEN command line arguments that would cause permission error
        WHEN main function is called
        THEN expect:
            - Error message printed to stderr indicating permission issue
            - Function exits with code 1
            - No partial files created
        """
        # Given
        test_args = ["script_name", self.test_file]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor_class.side_effect = PermissionError("Permission denied")
                
                with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                    with pytest.raises(SystemExit) as excinfo:
                        main()
        
        # Then
        assert excinfo.value.code == 1
        stderr_output = mock_stderr.getvalue()
        assert "Error:" in stderr_output
        assert "Permission denied" in stderr_output

    def test_main_with_file_not_found_error(self):
        """
        GIVEN command line arguments with input file that doesn't exist
        WHEN main function is called
        THEN expect:
            - Error message printed to stderr indicating file not found
            - Function exits with code 1
            - Error message includes the file path attempted
        """
        # Given
        nonexistent_file = "/nonexistent/file.py"
        test_args = ["script_name", nonexistent_file]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor_class.side_effect = FileNotFoundError(f"File not found: {nonexistent_file}")
                
                with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                    with pytest.raises(SystemExit) as excinfo:
                        main()
        
        # Then
        assert excinfo.value.code == 1
        stderr_output = mock_stderr.getvalue()
        assert "Error:" in stderr_output
        assert nonexistent_file in stderr_output

    def test_main_with_value_error_from_extractor(self):
        """
        GIVEN command line arguments that cause ClassExtractor to raise ValueError
        WHEN main function is called
        THEN expect:
            - Error message printed to stderr with ValueError details
            - Function exits with code 1
            - No output files created
        """
        # Given
        test_args = ["script_name", self.test_file]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.side_effect = ValueError("No classes found")
                
                with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                    with pytest.raises(SystemExit) as excinfo:
                        main()
        
        # Then
        assert excinfo.value.code == 1
        stderr_output = mock_stderr.getvalue()
        assert "Error:" in stderr_output
        assert "No classes found" in stderr_output

    def test_main_output_formatting_verbose(self):
        """
        GIVEN successful extraction with verbose flag
        WHEN main function is called
        THEN expect:
            - Output includes "Successfully extracted X classes from [filename]"
            - Each class listed with format "  ClassName -> /path/to/file"
            - Output is well-formatted and readable
        """
        # Given
        test_args = ["script_name", self.test_file, "--verbose"]
        created_files = {
            "TestClass1": Path("/output/TestClass1.py"),
            "TestClass2": Path("/output/TestClass2.py")
        }
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.return_value = created_files
                
                with patch('builtins.print') as mock_print:
                    main()
        
        # Then
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        
        # Check for success message
        success_msg = next((call for call in print_calls if "Successfully extracted 2 classes" in call), None)
        assert success_msg is not None
        assert self.test_file in success_msg
        
        # Check for class listings
        assert any("TestClass1 -> /output/TestClass1.py" in call for call in print_calls)
        assert any("TestClass2 -> /output/TestClass2.py" in call for call in print_calls)

    def test_main_output_formatting_brief(self):
        """
        GIVEN successful extraction without verbose flag
        WHEN main function is called
        THEN expect:
            - Output format: "Extracted X classes to [output_directory]"
            - No individual class details shown
            - Output is concise and informative
        """
        # Given
        test_args = ["script_name", self.test_file]
        created_files = {"TestClass1": Path("TestClass1.py")}
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.return_value = created_files
                mock_extractor.output_dir = self.temp_dir
                
                with patch('builtins.print') as mock_print:
                    main()
        
        # Then
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert len(print_calls) == 1
        assert f"Extracted 1 classes to {self.temp_dir}" in print_calls[0]

    def test_main_argument_parser_configuration(self):
        """
        GIVEN the argument parser is configured
        WHEN inspecting parser configuration
        THEN expect:
            - Required positional argument for input_file
            - Optional -o/--output-dir argument
            - Optional -v/--verbose flag argument
            - Proper help descriptions for all arguments
            - Proper argument types and validation
        """
        # This test verifies the parser configuration by testing argument parsing
        
        # Test required input_file argument
        test_args = ["script_name"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit):
                main()
        
        # Test optional arguments work
        test_args = ["script_name", self.test_file, "-o", "/tmp", "-v"]
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.return_value = {}
                
                with patch('builtins.print'):
                    main()
                
                mock_extractor_class.assert_called_once_with(self.test_file, "/tmp")

    def test_main_when_called_as_script(self):
        """
        GIVEN the script is run with __name__ == "__main__"
        WHEN the script is executed
        THEN expect:
            - main() function is called
            - No exceptions during normal module execution
        """
        # This test verifies the if __name__ == "__main__" block
        # We test this by importing the module and checking the structure
        import _extract_classes_from_python_files_stubs as module
        
        # Verify main function exists and is callable
        assert hasattr(module, 'main')
        assert callable(module.main)

    def test_main_exit_codes(self):
        """
        GIVEN various execution scenarios
        WHEN main function completes
        THEN expect:
            - Success scenarios: sys.exit(0) or normal return
            - Error scenarios: sys.exit(1)
            - Help scenarios: sys.exit(0)
        """
        # Test success scenario (normal return, no exit)
        test_args = ["script_name", self.test_file]
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor = MagicMock()
                mock_extractor_class.return_value = mock_extractor
                mock_extractor.extract_classes.return_value = {"TestClass": Path("TestClass.py")}
                mock_extractor.output_dir = self.temp_dir
                
                with patch('builtins.print'):
                    # Should complete without raising SystemExit
                    main()
        
        # Test error scenario
        test_args = ["script_name", "/nonexistent.py"]
        with patch.object(sys, 'argv', test_args):
            with patch('_extract_classes_from_python_files_stubs.ClassExtractor') as mock_extractor_class:
                mock_extractor_class.side_effect = FileNotFoundError()
                
                with patch('sys.stderr', new_callable=StringIO):
                    with pytest.raises(SystemExit) as excinfo:
                        main()
                    
                    assert excinfo.value.code == 1
        
        # Test help scenario
        test_args = ["script_name", "--help"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit) as excinfo:
                main()
            
            assert excinfo.value.code == 0


class TestMainFunctionIntegration:
    """Integration tests for main function with real file system operations."""

    def setup_method(self):
        """Set up test fixtures for integration tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "integration_test.py")
        self.complex_test_content = '''
"""Module with multiple classes for integration testing."""

import os
import sys
from typing import List, Optional

class BaseClass:
    """Base class for inheritance testing."""
    
    def __init__(self, name: str):
        self.name = name
    
    def get_name(self) -> str:
        return self.name

class DerivedClass(BaseClass):
    """Derived class for inheritance testing."""
    
    def __init__(self, name: str, value: int):
        super().__init__(name)
        self.value = value
    
    def get_value(self) -> int:
        return self.value

@dataclass
class DataClass:
    """Data class for decorator testing."""
    field1: str
    field2: int = 0

class UtilityClass:
    """Utility class with static and class methods."""
    
    @staticmethod
    def static_method() -> str:
        return "static"
    
    @classmethod
    def class_method(cls) -> str:
        return "class"
    
    @property
    def instance_property(self) -> str:
        return "property"
'''
        with open(self.test_file, 'w') as f:
            f.write(self.complex_test_content)

    def teardown_method(self):
        """Clean up integration test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_main_full_integration_with_complex_file(self):
        """
        GIVEN a complex Python file with multiple classes, inheritance, decorators, and various method types
        WHEN main function is called with this file
        THEN expect:
            - All classes successfully extracted to separate files
            - Each file contains proper dependencies and imports
            - All extracted files are syntactically valid Python
            - Output indicates correct number of classes extracted
            - All files can be imported without errors
        """
        # Given
        test_args = ["script_name", self.test_file, "--verbose"]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                main()
        
        # Then
        # Verify output files were created
        expected_files = ["BaseClass.py", "DerivedClass.py", "DataClass.py", "UtilityClass.py"]
        for expected_file in expected_files:
            file_path = os.path.join(self.temp_dir, expected_file)
            assert os.path.exists(file_path), f"Expected file {expected_file} was not created"
        
        # Verify verbose output
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("Successfully extracted 4 classes" in call for call in print_calls)
        
        # Verify each file contains the correct class
        base_class_file = os.path.join(self.temp_dir, "BaseClass.py")
        with open(base_class_file, 'r') as f:
            content = f.read()
            assert "class BaseClass:" in content
            assert "def get_name(self)" in content
        
        derived_class_file = os.path.join(self.temp_dir, "DerivedClass.py")
        with open(derived_class_file, 'r') as f:
            content = f.read()
            assert "class DerivedClass(BaseClass):" in content
            assert "class BaseClass:" in content  # Should include base class
            assert "super().__init__(name)" in content
        
        data_class_file = os.path.join(self.temp_dir, "DataClass.py")
        with open(data_class_file, 'r') as f:
            content = f.read()
            assert "@dataclass" in content
            assert "class DataClass:" in content
            assert "from dataclasses import dataclass" in content
        
        utility_class_file = os.path.join(self.temp_dir, "UtilityClass.py")
        with open(utility_class_file, 'r') as f:
            content = f.read()
            assert "class UtilityClass:" in content
            assert "@staticmethod" in content
            assert "@classmethod" in content
            assert "@property" in content
        
        # Verify syntax validity by attempting to compile each file
        for expected_file in expected_files:
            file_path = os.path.join(self.temp_dir, expected_file)
            with open(file_path, 'r') as f:
                content = f.read()
                try:
                    compile(content, file_path, 'exec')
                except SyntaxError as e:
                    pytest.fail(f"File {expected_file} has syntax errors: {e}")

    def test_main_integration_with_custom_output_directory(self):
        """
        GIVEN a valid input file and custom output directory
        WHEN main function is called
        THEN expect:
            - Output directory created if it doesn't exist
            - All class files written to specified directory
            - Correct file permissions set
            - Output directory structure matches expectations
        """
        # Given
        custom_output_dir = os.path.join(self.temp_dir, "custom_output", "nested")
        test_args = ["script_name", self.test_file, "-o", custom_output_dir]
        
        # Verify directory doesn't exist yet
        assert not os.path.exists(custom_output_dir)
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                main()
        
        # Then
        # Verify output directory was created
        assert os.path.exists(custom_output_dir)
        assert os.path.isdir(custom_output_dir)
        
        # Verify all files were created in the custom directory
        expected_files = ["BaseClass.py", "DerivedClass.py", "DataClass.py", "UtilityClass.py"]
        for expected_file in expected_files:
            file_path = os.path.join(custom_output_dir, expected_file)
            assert os.path.exists(file_path), f"Expected file {expected_file} was not created in custom directory"
            assert os.path.isfile(file_path)
        
        # Verify brief output format
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any(f"Extracted 4 classes to {custom_output_dir}" in call for call in print_calls)
        
        # Verify file permissions are readable
        for expected_file in expected_files:
            file_path = os.path.join(custom_output_dir, expected_file)
            assert os.access(file_path, os.R_OK), f"File {expected_file} is not readable"

    def test_main_integration_with_simple_file(self):
        """
        GIVEN a simple Python file with one class
        WHEN main function is called
        THEN expect:
            - Single class file created successfully
            - Correct output message
            - File contains complete class definition
        """
        # Given
        simple_file = os.path.join(self.temp_dir, "simple.py")
        simple_content = '''
class SimpleClass:
    """A simple test class."""
    
    def __init__(self, value):
        self.value = value
    
    def get_value(self):
        return self.value
'''
        with open(simple_file, 'w') as f:
            f.write(simple_content)
        
        test_args = ["script_name", simple_file]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                main()
        
        # Then
        output_file = os.path.join(self.temp_dir, "SimpleClass.py")
        assert os.path.exists(output_file)
        
        with open(output_file, 'r') as f:
            content = f.read()
            assert "class SimpleClass:" in content
            assert "def __init__(self, value):" in content
            assert "def get_value(self):" in content
        
        # Verify output message
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        assert any("Extracted 1 classes to" in call for call in print_calls)

    def test_main_integration_error_handling(self):
        """
        GIVEN various error conditions in integration scenarios
        WHEN main function is called
        THEN expect:
            - Appropriate error messages
            - Proper exit codes
            - No partial file creation on errors
        """
        # Test with file containing no classes
        no_classes_file = os.path.join(self.temp_dir, "no_classes.py")
        with open(no_classes_file, 'w') as f:
            f.write("def some_function():\n    return 42\n")
        
        test_args = ["script_name", no_classes_file]
        
        with patch.object(sys, 'argv', test_args):
            with patch('sys.stderr') as mock_stderr:
                with pytest.raises(SystemExit) as excinfo:
                    main()
                
                assert excinfo.value.code == 1
        
        # Verify no output files were created
        py_files = [f for f in os.listdir(self.temp_dir) if f.endswith('.py')]
        expected_files = ["integration_test.py", "no_classes.py"]  # Only input files
        assert len(py_files) == len(expected_files)

    def test_main_integration_with_existing_output_files(self):
        """
        GIVEN output directory with existing files that have same names as classes to be extracted
        WHEN main function is called
        THEN expect:
            - Existing files are overwritten with new content
            - All classes extracted successfully
            - New content replaces old content
        """
        # Given
        # Create existing file with different content
        existing_file = os.path.join(self.temp_dir, "BaseClass.py")
        with open(existing_file, 'w') as f:
            f.write("# This is old content that should be overwritten\n")
        
        test_args = ["script_name", self.test_file]
        
        # When
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print'):
                main()
        
        # Then
        # Verify old content was overwritten
        with open(existing_file, 'r') as f:
            content = f.read()
            assert "# This is old content" not in content
            assert "class BaseClass:" in content
            assert "def get_name(self)" in content

    def test_main_integration_file_permissions(self):
        """
        GIVEN various file permission scenarios
        WHEN main function is called
        THEN expect:
            - Proper handling of permission errors
            - Created files have correct permissions
        """
        # Test normal case - verify created files have correct permissions
        test_args = ["script_name", self.test_file]
        
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print'):
                main()
        
        # Verify created files are readable and writable by owner
        created_files = [f for f in os.listdir(self.temp_dir) if f.endswith('.py') and f != 'integration_test.py']
        
        for filename in created_files:
            filepath = os.path.join(self.temp_dir, filename)
            stat_info = os.stat(filepath)
            
            # Check that file is readable and writable by owner
            assert stat_info.st_mode & 0o400  # Owner read
            assert stat_info.st_mode & 0o200  # Owner write



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
