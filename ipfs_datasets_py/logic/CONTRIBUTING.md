# Contributing to Logic Module

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Status:** Active Contribution Guide

---

## Table of Contents

- [Welcome](#welcome)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Adding New Converters](#adding-new-converters)
- [Adding External Provers](#adding-external-provers)
- [Adding Inference Rules](#adding-inference-rules)
- [Code Style and Standards](#code-style-and-standards)
- [Testing Guidelines](#testing-guidelines)
- [Documentation](#documentation)
- [Pull Request Process](#pull-request-process)

---

## Welcome

Thank you for your interest in contributing to the IPFS Datasets Logic Module! This guide will help you understand how to contribute effectively.

### What Can I Contribute?

- 🐛 **Bug Fixes** - Fix issues in existing code
- ✨ **New Features** - Add converters, provers, or inference rules
- 📝 **Documentation** - Improve guides and examples
- 🧪 **Tests** - Add test coverage
- 🎨 **Performance** - Optimize slow code paths
- 💡 **Ideas** - Suggest improvements via issues

### Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help newcomers learn
- Follow the coding standards
- Test your changes thoroughly

---

## Getting Started

### Prerequisites

- **Python 3.12+**
- **Git** for version control
- **GitHub account** for pull requests
- **Basic understanding** of first-order logic (FOL)

### Quick Start

```bash
# 1. Fork the repository on GitHub

# 2. Clone your fork
git clone https://github.com/YOUR_USERNAME/ipfs_datasets_py.git
cd ipfs_datasets_py

# 3. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 4. Install in development mode
pip install -e ".[all,test]"

# 5. Run tests
pytest tests/

# 6. Create a branch
git checkout -b feature/my-contribution

# 7. Make changes, commit, push
git add .
git commit -m "Add my contribution"
git push origin feature/my-contribution

# 8. Open a Pull Request on GitHub
```

---

## Development Setup

### Full Development Environment

```bash
# Install all dependencies
pip install -e ".[all,test,dev]"

# Install pre-commit hooks
pre-commit install

# Install external provers (optional)
# Z3
pip install z3-solver

# Lean (manual install)
# Follow: https://leanprover.github.io/lean4/doc/setup.html

# Coq (manual install)
# Follow: https://coq.inria.fr/download
```

### IDE Configuration

**VS Code:**
```json
// .vscode/settings.json
{
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": false,
  "python.linting.flake8Enabled": true,
  "python.formatting.provider": "black",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": [
    "tests/"
  ]
}
```

**PyCharm:**
- Enable pytest as test runner
- Configure Black as formatter
- Enable mypy for type checking
- Mark `ipfs_datasets_py` as sources root

---

## How to Contribute

### Reporting Bugs

**Before reporting:**
1. Check existing issues
2. Try the latest version
3. Search documentation

**Bug report should include:**
- Python version
- Operating system
- Minimal reproducible example
- Expected vs actual behavior
- Error messages and stack traces

**Template:**
```markdown
## Bug Description
Brief description of the bug

## To Reproduce
1. Step 1
2. Step 2
3. ...

## Expected Behavior
What you expected to happen

## Actual Behavior
What actually happened

## Environment
- Python version:
- OS:
- ipfs-datasets-py version:

## Additional Context
Any other relevant information
```

### Suggesting Features

**Feature requests should include:**
- Use case and motivation
- Proposed API design
- Example usage
- Alternatives considered

**Template:**
```markdown
## Feature Request

### Use Case
What problem does this solve?

### Proposed Solution
How should it work?

### Example Usage
```python
# Code example
```

### Alternatives
What other approaches did you consider?
```

---

## Adding New Converters

### Converter Template

```python
# ipfs_datasets_py/logic/converters/my_converter.py
from typing import Optional
from ipfs_datasets_py.logic.common import LogicConverter, ConversionResult

class MyLogicConverter(LogicConverter):
    """
    Convert natural language to My Logic System.
    
    Examples:
        >>> converter = MyLogicConverter()
        >>> result = converter.convert("All cats are animals")
        >>> print(result.fol)
        '∀x (Cat(x) → Animal(x))'
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        Initialize converter.
        
        Args:
            config: Optional configuration dictionary
        """
        super().__init__(config)
        self.system_name = "MyLogic"
    
    def convert(self, text: str, **kwargs) -> ConversionResult:
        """
        Convert text to MyLogic format.
        
        Args:
            text: Natural language text
            **kwargs: Additional options
        
        Returns:
            ConversionResult with success status and output
        
        Raises:
            ConversionError: If conversion fails
            ValidationError: If input is invalid
        """
        # Validate input
        self._validate_input(text)
        
        try:
            # Your conversion logic here
            formula = self._parse_and_convert(text)
            
            return ConversionResult(
                success=True,
                fol=formula,
                confidence=0.9,
                metadata={
                    "converter": self.system_name,
                    "method": "custom_parsing",
                }
            )
        
        except Exception as e:
            return ConversionResult(
                success=False,
                error=str(e),
                confidence=0.0,
            )
    
    def _parse_and_convert(self, text: str) -> str:
        """Internal conversion logic."""
        # Implement your conversion algorithm
        pass
    
    def _validate_input(self, text: str):
        """Validate input text."""
        if not text or not text.strip():
            raise ValueError("Empty input")
        
        if len(text) > self.max_input_size:
            raise ValueError(f"Input too large: {len(text)} > {self.max_input_size}")
```

### Testing Your Converter

```python
# tests/test_my_converter.py
import pytest
from ipfs_datasets_py.logic.converters.my_converter import MyLogicConverter

class TestMyLogicConverter:
    """Test suite for MyLogicConverter."""
    
    def test_simple_conversion(self):
        """
        GIVEN: Simple natural language statement
        WHEN: Converting to MyLogic
        THEN: Returns correct formula
        """
        converter = MyLogicConverter()
        result = converter.convert("All cats are animals")
        
        assert result.success
        assert "∀" in result.fol
        assert "Cat" in result.fol
        assert "Animal" in result.fol
    
    def test_complex_conversion(self):
        """Test complex statement conversion."""
        converter = MyLogicConverter()
        result = converter.convert(
            "If all cats are animals and Fluffy is a cat, then Fluffy is an animal"
        )
        
        assert result.success
        assert result.confidence > 0.7
    
    def test_invalid_input(self):
        """Test error handling for invalid input."""
        converter = MyLogicConverter()
        
        # Empty input
        result = converter.convert("")
        assert not result.success
        
        # Too long input
        long_text = "a" * 100_000
        with pytest.raises(ValueError):
            converter.convert(long_text)
```

### Registering Your Converter

```python
# ipfs_datasets_py/logic/__init__.py
from .converters.my_converter import MyLogicConverter

__all__ = [
    # ... existing exports
    'MyLogicConverter',
]
```

---

## Adding External Provers

### Prover Bridge Template

```python
# ipfs_datasets_py/logic/external_provers/my_prover_bridge.py
from typing import Optional
from ipfs_datasets_py.logic.integration.bridges import BaseProverBridge
from ipfs_datasets_py.logic.common import ProofResult, ProofStatus

class MyProverBridge(BaseProverBridge):
    """
    Bridge to My External Prover.
    
    Requires: my-prover binary in PATH
    Install: pip install my-prover
    """
    
    def __init__(self, config: Optional[dict] = None):
        """Initialize bridge."""
        super().__init__(config)
        self.prover_name = "MyProver"
        self._check_availability()
    
    def _check_availability(self):
        """Check if prover is available."""
        try:
            import subprocess
            result = subprocess.run(
                ["my-prover", "--version"],
                capture_output=True,
                timeout=5,
            )
            self.available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.available = False
    
    def prove(self, formula: str, assumptions: list = None, timeout: int = 30) -> ProofResult:
        """
        Prove formula using My Prover.
        
        Args:
            formula: Formula to prove
            assumptions: List of assumptions
            timeout: Timeout in seconds
        
        Returns:
            ProofResult with status and proof
        """
        if not self.available:
            return ProofResult(
                status=ProofStatus.ERROR,
                error="MyProver not available",
            )
        
        try:
            # Convert to prover format
            prover_input = self._format_for_prover(formula, assumptions)
            
            # Run prover
            import subprocess
            result = subprocess.run(
                ["my-prover", "--input", prover_input],
                capture_output=True,
                timeout=timeout,
                text=True,
            )
            
            # Parse result
            if "proved" in result.stdout.lower():
                return ProofResult(
                    status=ProofStatus.PROVED,
                    proof=result.stdout,
                    time_ms=1000,  # Parse from output
                )
            else:
                return ProofResult(
                    status=ProofStatus.UNPROVABLE,
                    proof=None,
                )
        
        except subprocess.TimeoutExpired:
            return ProofResult(
                status=ProofStatus.TIMEOUT,
                error=f"Timeout after {timeout}s",
            )
        except Exception as e:
            return ProofResult(
                status=ProofStatus.ERROR,
                error=str(e),
            )
    
    def _format_for_prover(self, formula: str, assumptions: list) -> str:
        """Convert to prover's input format."""
        # Implement format conversion
        pass
```

### Testing Your Prover Bridge

```python
# tests/test_my_prover_bridge.py
import pytest
from ipfs_datasets_py.logic.external_provers.my_prover_bridge import MyProverBridge
from ipfs_datasets_py.logic.common import ProofStatus

@pytest.mark.skipif(
    not MyProverBridge().available,
    reason="MyProver not installed"
)
class TestMyProverBridge:
    """Test suite for MyProverBridge."""
    
    def test_simple_proof(self):
        """
        GIVEN: Simple provable formula
        WHEN: Proving with MyProver
        THEN: Returns PROVED status
        """
        bridge = MyProverBridge()
        result = bridge.prove("P → Q", assumptions=["P", "P → Q"])
        
        assert result.status == ProofStatus.PROVED
        assert result.proof is not None
    
    def test_unprovable(self):
        """Test unprovable formula."""
        bridge = MyProverBridge()
        result = bridge.prove("Q", assumptions=["P"])
        
        assert result.status == ProofStatus.UNPROVABLE
    
    def test_timeout(self):
        """Test timeout handling."""
        bridge = MyProverBridge()
        result = bridge.prove("complex_formula", timeout=1)
        
        assert result.status == ProofStatus.TIMEOUT
```

---

## Adding Inference Rules

### Inference Rule Template

```python
# ipfs_datasets_py/logic/TDFOL/inference_rules/my_rule.py
from ipfs_datasets_py.logic.TDFOL.inference_rules import InferenceRule
from ipfs_datasets_py.logic.types import Formula

class MyInferenceRule(InferenceRule):
    """
    My custom inference rule.
    
    Pattern: A, A → B ⊢ B  (Modus Ponens example)
    
    Description:
        If we have A and A implies B, we can infer B.
    
    Examples:
        >>> rule = MyInferenceRule()
        >>> premises = [Formula("P"), Formula("P → Q")]
        >>> conclusion = rule.apply(premises)
        >>> print(conclusion)
        'Q'
    """
    
    def __init__(self):
        super().__init__(
            name="MyRule",
            description="My custom inference rule",
            pattern=["A", "A → B"],
            conclusion="B",
        )
    
    def is_applicable(self, premises: list) -> bool:
        """
        Check if rule can be applied to premises.
        
        Args:
            premises: List of premise formulas
        
        Returns:
            True if rule is applicable
        """
        # Check if we have right number and structure of premises
        if len(premises) != 2:
            return False
        
        # Check if one is implication and other is antecedent
        for prem in premises:
            if self._is_implication(prem):
                return self._check_structure(premises, prem)
        
        return False
    
    def apply(self, premises: list) -> Formula:
        """
        Apply rule to premises to derive conclusion.
        
        Args:
            premises: List of premise formulas
        
        Returns:
            Derived conclusion formula
        
        Raises:
            ValueError: If rule is not applicable
        """
        if not self.is_applicable(premises):
            raise ValueError(f"{self.name} not applicable to {premises}")
        
        # Extract conclusion
        for prem in premises:
            if self._is_implication(prem):
                return self._extract_consequent(prem)
        
        raise ValueError("No implication found")
    
    def _is_implication(self, formula: Formula) -> bool:
        """Check if formula is an implication."""
        return "→" in str(formula)
    
    def _check_structure(self, premises: list, implication: Formula) -> bool:
        """Check if structure matches rule pattern."""
        # Implementation depends on your formula representation
        pass
    
    def _extract_consequent(self, implication: Formula) -> Formula:
        """Extract consequent from implication."""
        # Implementation depends on your formula representation
        pass
```

### Testing Your Inference Rule

```python
# tests/test_my_rule.py
import pytest
from ipfs_datasets_py.logic.TDFOL.inference_rules.my_rule import MyInferenceRule
from ipfs_datasets_py.logic.types import Formula

class TestMyInferenceRule:
    """Test suite for MyInferenceRule."""
    
    def test_rule_application(self):
        """
        GIVEN: Premises matching rule pattern
        WHEN: Applying rule
        THEN: Derives correct conclusion
        """
        rule = MyInferenceRule()
        premises = [
            Formula("P"),
            Formula("P → Q"),
        ]
        
        conclusion = rule.apply(premises)
        assert str(conclusion) == "Q"
    
    def test_rule_not_applicable(self):
        """Test rule rejects invalid premises."""
        rule = MyInferenceRule()
        premises = [Formula("P"), Formula("R")]
        
        assert not rule.is_applicable(premises)
        
        with pytest.raises(ValueError):
            rule.apply(premises)
    
    def test_rule_commutativity(self):
        """Test rule works regardless of premise order."""
        rule = MyInferenceRule()
        premises1 = [Formula("P"), Formula("P → Q")]
        premises2 = [Formula("P → Q"), Formula("P")]
        
        result1 = rule.apply(premises1)
        result2 = rule.apply(premises2)
        
        assert str(result1) == str(result2)
```

### Registering Your Rule

```python
# ipfs_datasets_py/logic/TDFOL/inference_rules/__init__.py
from .my_rule import MyInferenceRule

# Add to rule registry
INFERENCE_RULES = [
    # ... existing rules
    MyInferenceRule(),
]
```

---

## Code Style and Standards

### Python Style

Follow PEP 8 and use Black formatter:

```bash
# Format code
black ipfs_datasets_py/

# Check style
flake8 ipfs_datasets_py/

# Type checking
mypy ipfs_datasets_py/
```

### Naming Conventions

- **Classes:** `PascalCase` (e.g., `FOLConverter`)
- **Functions/Methods:** `snake_case` (e.g., `convert_text`)
- **Constants:** `UPPER_SNAKE_CASE` (e.g., `MAX_INPUT_SIZE`)
- **Private:** `_prefix` (e.g., `_internal_method`)

### Type Hints

Always use type hints:

```python
from typing import List, Optional, Dict, Any

def convert_formula(
    text: str,
    options: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Convert text to formulas."""
    pass
```

### Docstrings

Follow Google style docstrings:

```python
def complex_function(param1: str, param2: int) -> Dict[str, Any]:
    """
    Brief description of function.
    
    Longer description explaining the function's behavior,
    edge cases, and important notes.
    
    Args:
        param1: Description of first parameter
        param2: Description of second parameter
    
    Returns:
        Dictionary containing:
            - key1: Description
            - key2: Description
    
    Raises:
        ValueError: If param2 is negative
        RuntimeError: If operation fails
    
    Examples:
        >>> result = complex_function("test", 42)
        >>> print(result['key1'])
        'value1'
    """
    pass
```

---

## Testing Guidelines

### Test Structure

Follow **GIVEN-WHEN-THEN** format:

```python
def test_conversion_with_quantifiers():
    """
    GIVEN: Text with universal quantifier
    WHEN: Converting to FOL
    THEN: Formula contains ∀ quantifier
    """
    # GIVEN
    converter = FOLConverter()
    text = "All cats are animals"
    
    # WHEN
    result = converter.convert(text)
    
    # THEN
    assert result.success
    assert "∀" in result.fol
    assert "Cat" in result.fol
    assert "Animal" in result.fol
```

### Test Coverage

Aim for >90% coverage:

```bash
# Run with coverage
pytest --cov=ipfs_datasets_py --cov-report=html

# View report
open htmlcov/index.html
```

### Test Categories

Use pytest markers:

```python
@pytest.mark.unit
def test_simple_case():
    """Unit test."""
    pass

@pytest.mark.integration
def test_end_to_end():
    """Integration test."""
    pass

@pytest.mark.slow
def test_performance():
    """Performance test."""
    pass

@pytest.mark.skipif(not DEPENDENCY_AVAILABLE, reason="Dependency not installed")
def test_with_optional_dependency():
    """Test requiring optional dependency."""
    pass
```

---

## Documentation

### Updating Docs

When adding features, update:

1. **API_REFERENCE.md** - API documentation
2. **README.md** - Overview if user-facing
3. **FEATURES.md** - Feature list
4. **Docstrings** - Inline documentation

### Writing Examples

Include runnable examples:

```python
"""
Examples:
    Basic usage:
    
    >>> from ipfs_datasets_py.logic.fol import FOLConverter
    >>> converter = FOLConverter()
    >>> result = converter.convert("All cats are animals")
    >>> print(result.fol)
    '∀x (Cat(x) → Animal(x))'
    
    Advanced usage with configuration:
    
    >>> config = {"max_depth": 10}
    >>> converter = FOLConverter(config=config)
    >>> result = converter.convert("Complex statement")
"""
```

---

## Pull Request Process

### Before Submitting

- [ ] Code follows style guidelines
- [ ] Tests added and passing
- [ ] Documentation updated
- [ ] Commits are atomic and well-described
- [ ] Branch is up to date with main
- [ ] No merge conflicts

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
How were these changes tested?

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] No breaking changes (or documented if needed)
```

### Review Process

1. **Automated Checks** - CI/CD must pass
2. **Code Review** - At least one approval required
3. **Testing** - Reviewer tests changes
4. **Documentation** - Docs reviewed for accuracy
5. **Merge** - Squash and merge when approved

---

## Additional Resources

**Documentation:**
- [README.md](./README.md) - Module overview
- [API_REFERENCE.md](./API_REFERENCE.md) - API documentation
- [ARCHITECTURE.md](./ARCHITECTURE.md) - Architecture guide
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Common issues

**Tools:**
- [Black](https://black.readthedocs.io/) - Code formatter
- [flake8](https://flake8.pycqa.org/) - Style checker
- [mypy](http://mypy-lang.org/) - Type checker
- [pytest](https://pytest.org/) - Testing framework

**Community:**
- [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues) - Bug reports and feature requests
- [GitHub Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions) - Questions and ideas
- [Pull Requests](https://github.com/endomorphosis/ipfs_datasets_py/pulls) - Code contributions

---

## Summary

**Getting Started:**
1. Fork repository
2. Install development dependencies
3. Create feature branch
4. Make changes with tests
5. Submit pull request

**Key Points:**
- Follow code style guidelines
- Add comprehensive tests
- Update documentation
- Get code review approval
- Maintain backward compatibility

**Thank you for contributing!** 🎉

---

**Document Status:** Active Contribution Guide  
**Maintained By:** Logic Module Maintainers  
**Review Frequency:** Quarterly
