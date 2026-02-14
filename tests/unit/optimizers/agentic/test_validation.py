"""Test suite for validation framework."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open
import ast
import tempfile

from ipfs_datasets_py.optimizers.agentic.validation import (
    OptimizationValidator,
    SyntaxValidator,
    TypeValidator,
    TestValidator,
    PerformanceValidator,
    SecurityValidator,
    StyleValidator,
    ValidationLevel,
    DetailedValidationResult,
)
from ipfs_datasets_py.optimizers.agentic.base import ValidationResult


class TestValidationLevel:
    """Test ValidationLevel enum."""
    
    def test_levels(self):
        """Test all validation levels are defined."""
        assert ValidationLevel.BASIC.value == "basic"
        assert ValidationLevel.STANDARD.value == "standard"
        assert ValidationLevel.STRICT.value == "strict"
        assert ValidationLevel.PARANOID.value == "paranoid"


class TestDetailedValidationResult:
    """Test DetailedValidationResult dataclass."""
    
    def test_result_creation(self):
        """Test creating detailed result."""
        result = DetailedValidationResult(
            passed=True,
            level=ValidationLevel.STANDARD,
            syntax_passed=True,
            type_passed=True,
            test_passed=True,
            errors=[],
            warnings=["Minor style issue"],
        )
        assert result.passed is True
        assert result.level == ValidationLevel.STANDARD
        assert len(result.warnings) == 1


class TestSyntaxValidator:
    """Test SyntaxValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create syntax validator."""
        return SyntaxValidator()
    
    def test_validate_valid_code(self, validator):
        """Test validating syntactically correct code."""
        code = "def hello(): return 'world'"
        result = validator.validate(code)
        
        assert isinstance(result, ValidationResult)
        assert result.passed is True
        assert len(result.errors) == 0
    
    def test_validate_syntax_error(self, validator):
        """Test detecting syntax errors."""
        code = "def broken(: pass"  # Missing closing parenthesis
        result = validator.validate(code)
        
        assert result.passed is False
        assert len(result.errors) > 0
        assert "syntax" in result.errors[0].lower()
    
    def test_validate_indentation_error(self, validator):
        """Test detecting indentation errors."""
        code = """
def test():
return 42
"""  # Wrong indentation
        result = validator.validate(code)
        
        assert result.passed is False
        assert len(result.errors) > 0
    
    def test_validate_complex_code(self, validator):
        """Test validating complex code."""
        code = """
class MyClass:
    def __init__(self, value):
        self.value = value
    
    def process(self):
        return [x ** 2 for x in range(self.value)]
"""
        result = validator.validate(code)
        
        assert result.passed is True
    
    def test_count_nodes(self, validator):
        """Test AST node counting."""
        code = "def test(): return 1 + 2 + 3"
        tree = ast.parse(code)
        count = validator.count_nodes(tree)
        
        assert count > 0
        assert isinstance(count, int)
    
    def test_detect_undefined_names(self, validator):
        """Test detecting undefined names."""
        code = """
def test():
    return undefined_variable + 1
"""
        undefined = validator.detect_undefined_names(code)
        
        assert len(undefined) > 0
        assert "undefined_variable" in undefined


class TestTypeValidator:
    """Test TypeValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create type validator."""
        return TypeValidator(strict_mode=False)
    
    def test_init(self):
        """Test validator initialization."""
        validator = TypeValidator(strict_mode=True)
        assert validator.strict_mode is True
    
    def test_validate_with_types(self, validator, tmp_path):
        """Test validating code with type hints."""
        code = """
def add(a: int, b: int) -> int:
    return a + b
"""
        # Create temp file
        test_file = tmp_path / "test.py"
        test_file.write_text(code)
        
        result = validator.validate(str(test_file))
        
        # Type validation requires actual file
        assert isinstance(result, ValidationResult)
    
    def test_validate_without_mypy(self, validator):
        """Test graceful handling when mypy unavailable."""
        with patch('shutil.which', return_value=None):
            result = validator.validate("test.py")
            # Should return success when mypy not available
            assert isinstance(result, ValidationResult)


class TestTestValidator:
    """Test TestValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create test validator."""
        return TestValidator()
    
    def test_discover_tests(self, validator, tmp_path):
        """Test discovering test files."""
        # Create test files
        test1 = tmp_path / "test_one.py"
        test1.write_text("def test_something(): pass")
        test2 = tmp_path / "test_two.py"
        test2.write_text("def test_another(): pass")
        
        tests = validator.discover_tests(str(tmp_path))
        
        assert isinstance(tests, list)
        assert len(tests) >= 2
    
    def test_validate_with_tests(self, validator, tmp_path):
        """Test validation with test execution."""
        # Create simple passing test
        test_file = tmp_path / "test_simple.py"
        test_file.write_text("""
def test_pass():
    assert True
""")
        
        result = validator.validate(str(tmp_path))
        
        assert isinstance(result, ValidationResult)
        # Test execution might fail if pytest not available
    
    def test_validate_no_tests(self, validator, tmp_path):
        """Test validation with no tests found."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        
        result = validator.validate(str(empty_dir))
        
        # Should return result even with no tests
        assert isinstance(result, ValidationResult)


class TestPerformanceValidator:
    """Test PerformanceValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create performance validator."""
        return PerformanceValidator(min_improvement=5.0)
    
    def test_init(self):
        """Test validator initialization."""
        validator = PerformanceValidator(min_improvement=10.0)
        assert validator.min_improvement == 10.0
    
    def test_benchmark_code(self, validator):
        """Test benchmarking code execution."""
        code = """
def test():
    return sum(range(100))
"""
        metrics = validator.benchmark_code(code, iterations=10)
        
        assert isinstance(metrics, dict)
        assert "avg_time" in metrics
        assert "min_time" in metrics
        assert "max_time" in metrics
        assert metrics["avg_time"] > 0
    
    def test_benchmark_fast_code(self, validator):
        """Test benchmarking very fast code."""
        code = "result = 42"
        metrics = validator.benchmark_code(code, iterations=100)
        
        assert metrics["avg_time"] >= 0
        assert metrics["min_time"] <= metrics["avg_time"]
    
    def test_validate_improvement(self, validator):
        """Test validating performance improvement."""
        baseline = {"avg_time": 1.0}
        optimized = {"avg_time": 0.9}  # 10% improvement
        
        result = validator.validate_improvement(baseline, optimized)
        
        assert isinstance(result, ValidationResult)
        assert result.passed is True  # 10% > 5% minimum
    
    def test_validate_no_improvement(self, validator):
        """Test when there's no improvement."""
        baseline = {"avg_time": 1.0}
        optimized = {"avg_time": 1.0}  # No improvement
        
        result = validator.validate_improvement(baseline, optimized)
        
        assert result.passed is False
        assert len(result.errors) > 0


class TestSecurityValidator:
    """Test SecurityValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create security validator."""
        return SecurityValidator()
    
    def test_detect_dangerous_functions(self, validator):
        """Test detecting dangerous function calls."""
        code = "eval(user_input)"
        issues = validator.detect_dangerous_patterns(code)
        
        assert len(issues) > 0
        assert any("eval" in issue.lower() for issue in issues)
    
    def test_detect_exec(self, validator):
        """Test detecting exec calls."""
        code = "exec('print(1)')"
        issues = validator.detect_dangerous_patterns(code)
        
        assert len(issues) > 0
        assert any("exec" in issue.lower() for issue in issues)
    
    def test_detect_sql_injection(self, validator):
        """Test detecting potential SQL injection."""
        code = '''
query = "SELECT * FROM users WHERE id = " + user_id
cursor.execute(query)
'''
        issues = validator.detect_sql_injection_risks(code)
        
        assert len(issues) > 0
        assert any("sql" in issue.lower() or "injection" in issue.lower() for issue in issues)
    
    def test_detect_safe_sql(self, validator):
        """Test safe SQL doesn't trigger warnings."""
        code = '''
query = "SELECT * FROM users WHERE id = ?"
cursor.execute(query, (user_id,))
'''
        issues = validator.detect_sql_injection_risks(code)
        
        # Parameterized query should be safe
        assert len(issues) == 0
    
    def test_detect_hardcoded_secrets(self, validator):
        """Test detecting hardcoded secrets."""
        code = '''
API_KEY = "sk_live_1234567890abcdef"
password = "my_secret_password"
'''
        secrets = validator.detect_hardcoded_secrets(code)
        
        assert len(secrets) > 0
    
    def test_validate_secure_code(self, validator):
        """Test validating secure code."""
        code = """
def safe_function(data):
    if not isinstance(data, str):
        raise TypeError("Expected string")
    return data.lower()
"""
        result = validator.validate(code)
        
        assert isinstance(result, ValidationResult)
        # Secure code should pass


class TestStyleValidator:
    """Test StyleValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create style validator."""
        return StyleValidator()
    
    def test_check_docstrings(self, validator):
        """Test checking for docstrings."""
        code = """
def no_docstring():
    pass

def with_docstring():
    '''Has docstring.'''
    pass
"""
        score = validator.check_docstrings(code)
        
        assert isinstance(score, float)
        assert 0 <= score <= 100
        # Should be 50% (1 of 2 functions has docstring)
        assert score == 50.0
    
    def test_check_type_hints(self, validator):
        """Test checking for type hints."""
        code = """
def no_types(a, b):
    return a + b

def with_types(a: int, b: int) -> int:
    return a + b
"""
        score = validator.check_type_hints(code)
        
        assert isinstance(score, float)
        assert 0 <= score <= 100
        # Should be 50% (1 of 2 functions has hints)
        assert score == 50.0
    
    def test_check_naming_conventions(self, validator):
        """Test checking naming conventions."""
        good_code = """
def good_function_name():
    good_variable = 42
    return good_variable

class GoodClassName:
    pass
"""
        good_score = validator.check_naming_conventions(good_code)
        
        bad_code = """
def BadFunctionName():
    BadVariable = 42
    return BadVariable

class bad_class_name:
    pass
"""
        bad_score = validator.check_naming_conventions(bad_code)
        
        assert good_score > bad_score
    
    def test_validate_style(self, validator):
        """Test overall style validation."""
        code = """
def well_styled_function(value: int) -> int:
    '''This function has good style.
    
    Args:
        value: Input value
    
    Returns:
        Processed value
    '''
    result = value * 2
    return result
"""
        result = validator.validate(code)
        
        assert isinstance(result, ValidationResult)
        # Well-styled code should pass
        assert result.passed is True


class TestOptimizationValidator:
    """Test OptimizationValidator orchestrator."""
    
    @pytest.fixture
    def validator(self):
        """Create optimization validator."""
        return OptimizationValidator()
    
    def test_init(self):
        """Test validator initialization."""
        validator = OptimizationValidator()
        assert validator.syntax_validator is not None
        assert validator.type_validator is not None
        assert validator.test_validator is not None
    
    def test_validate_basic_level(self, validator):
        """Test validation at basic level."""
        code = "def test(): return 42"
        
        result = validator.validate(code, level=ValidationLevel.BASIC)
        
        assert isinstance(result, DetailedValidationResult)
        assert result.level == ValidationLevel.BASIC
        # Basic only checks syntax
        assert result.syntax_passed is not None
    
    def test_validate_standard_level(self, validator):
        """Test validation at standard level."""
        code = """
def add(a: int, b: int) -> int:
    return a + b
"""
        result = validator.validate(code, level=ValidationLevel.STANDARD)
        
        assert isinstance(result, DetailedValidationResult)
        assert result.level == ValidationLevel.STANDARD
        # Standard checks syntax + types + tests
    
    def test_validate_strict_level(self, validator):
        """Test validation at strict level."""
        code = "def fast(): return 42"
        baseline_metrics = {"avg_time": 1.0}
        optimized_metrics = {"avg_time": 0.5}
        
        result = validator.validate(
            code,
            level=ValidationLevel.STRICT,
            baseline_metrics=baseline_metrics,
            optimized_metrics=optimized_metrics,
        )
        
        assert isinstance(result, DetailedValidationResult)
        assert result.level == ValidationLevel.STRICT
    
    def test_validate_paranoid_level(self, validator):
        """Test validation at paranoid level."""
        code = """
def secure_function(data: str) -> str:
    '''Process data securely.'''
    if not isinstance(data, str):
        raise TypeError("Expected string")
    return data.lower()
"""
        result = validator.validate(code, level=ValidationLevel.PARANOID)
        
        assert isinstance(result, DetailedValidationResult)
        assert result.level == ValidationLevel.PARANOID
        # Paranoid checks everything
    
    def test_validate_parallel(self, validator):
        """Test parallel validation."""
        code = "def test(): return 42"
        
        result = validator.validate(code, parallel=True)
        
        assert isinstance(result, DetailedValidationResult)
    
    def test_validate_sequential(self, validator):
        """Test sequential validation."""
        code = "def test(): return 42"
        
        result = validator.validate(code, parallel=False)
        
        assert isinstance(result, DetailedValidationResult)
    
    def test_validate_with_timeout(self, validator):
        """Test validation with timeout."""
        code = "def test(): return 42"
        
        result = validator.validate(code, timeout=5)
        
        assert isinstance(result, DetailedValidationResult)
    
    def test_validate_async(self, validator):
        """Test async validation."""
        import asyncio
        
        code = "def test(): return 42"
        
        async def run_validation():
            return await validator.validate_async(code)
        
        # Run async validation
        result = asyncio.run(run_validation())
        
        assert isinstance(result, DetailedValidationResult)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
