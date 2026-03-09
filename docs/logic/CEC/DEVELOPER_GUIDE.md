# CEC Developer Guide

**Version:** 1.0  
**Last Updated:** 2026-02-18  
**Target Audience:** Contributors and developers

> **Comprehensive guide** for developers working on the CEC (Cognitive Event Calculus) codebase.

---

## 📋 Table of Contents

1. [Getting Started](#getting-started)
2. [Development Environment](#development-environment)
3. [Code Organization](#code-organization)
4. [Architecture Overview](#architecture-overview)
5. [Testing Strategy](#testing-strategy)
6. [Code Style Guidelines](#code-style-guidelines)
7. [Contribution Workflow](#contribution-workflow)
8. [Building & Running](#building--running)
9. [Debugging Tips](#debugging-tips)
10. [Release Process](#release-process)
11. [Common Tasks](#common-tasks)
12. [FAQ](#faq)

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.12+** (required)
- **Git** (for version control)
- **pip** (package manager)
- **pytest** (testing framework)
- **IDE** (recommended: VSCode, PyCharm)

### Quick Setup

```bash
# 1. Clone repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# 2. Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# 3. Install in development mode
pip install -e ".[test]"

# 4. Run tests to verify
pytest tests/unit_tests/logic/CEC/ -v

# 5. You're ready to develop!
```

---

## 💻 Development Environment

### Recommended IDE Setup

#### VSCode

**Extensions:**
- Python (Microsoft)
- Pylance (type checking)
- Python Test Explorer
- GitLens
- Better Comments

**Settings (.vscode/settings.json):**
```json
{
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "python.linting.flake8Enabled": true,
    "python.formatting.provider": "black",
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": [
        "tests/unit_tests/logic/CEC/"
    ],
    "python.analysis.typeCheckingMode": "basic",
    "editor.formatOnSave": true
}
```

#### PyCharm

**Configuration:**
1. Open project root as PyCharm project
2. Configure Python interpreter (3.12+)
3. Enable pytest as test runner
4. Configure code style: PEP 8
5. Enable type checking

### Virtual Environment

**Always use a virtual environment:**

```bash
# Create virtual environment
python3.12 -m venv venv

# Activate (Linux/Mac)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -e ".[test]"

# Verify
python -c "from ipfs_datasets_py.logic.CEC.native import DCECContainer; print('✅ Setup complete!')"
```

### Dependencies

**Core dependencies:**
- Python 3.12+ standard library only
- Zero external runtime dependencies

**Development dependencies:**
```bash
pip install -e ".[test]"
```

Includes:
- pytest (testing)
- pytest-cov (coverage)
- pytest-xdist (parallel testing)
- mypy (type checking)
- flake8 (linting)
- black (formatting)
- isort (import sorting)

---

## 📁 Code Organization

### Directory Structure

```
ipfs_datasets_py/logic/CEC/
├── native/                           # Native Python 3 implementation
│   ├── __init__.py                   # Public API exports
│   ├── dcec_core.py                  # Core DCEC classes (430 lines)
│   ├── dcec_namespace.py             # Namespace management (350 lines)
│   ├── prover_core.py                # Theorem prover (4,245 lines) ⭐
│   ├── nl_converter.py               # NL ↔ DCEC (535 lines)
│   ├── grammar_engine.py             # Grammar engine (478 lines)
│   ├── dcec_english_grammar.py       # English grammar (759 lines)
│   ├── modal_tableaux.py             # Modal tableaux (578 lines)
│   ├── shadow_prover.py              # Shadow prover (776 lines)
│   ├── dcec_parsing.py               # Parser (435 lines)
│   ├── dcec_cleaning.py              # Cleaning utilities (221 lines)
│   ├── dcec_prototypes.py            # Prototypes (520 lines)
│   ├── dcec_integration.py           # Integration layer (428 lines)
│   └── problem_parser.py             # Problem file parser (244 lines)
│
├── wrappers/                         # Legacy submodule wrappers
│   ├── dcec_wrapper.py               # DCEC_Library wrapper
│   ├── eng_dcec_wrapper.py           # Eng-DCEC wrapper
│   ├── shadow_prover_wrapper.py      # ShadowProver wrapper
│   └── talos_wrapper.py              # Talos wrapper
│
├── tests/                            # Test suite
│   └── unit_tests/logic/CEC/native/  # 13 test files, 418+ tests
│
├── docs/                             # Documentation
│   ├── README.md                     # Main entry point
│   ├── STATUS.md                     # Implementation status ⭐
│   ├── QUICKSTART.md                 # 5-minute tutorial
│   ├── API_REFERENCE.md              # Complete API docs
│   ├── DEVELOPER_GUIDE.md            # This file ⭐
│   └── ... (planning documents)
│
└── __init__.py                       # Package init
```

### Module Responsibilities

| Module | Responsibility | LOC | Status |
|--------|---------------|-----|--------|
| **dcec_core.py** | Core DCEC data structures | 430 | ✅ Complete |
| **dcec_namespace.py** | Symbol management, containers | 350 | ✅ Complete |
| **prover_core.py** | Theorem proving (50+ rules) | 4,245 | ✅ Complete |
| **nl_converter.py** | Natural language conversion | 535 | ✅ Complete |
| **grammar_engine.py** | Grammar-based parsing | 478 | ✅ Complete |
| **dcec_english_grammar.py** | English grammar rules | 759 | ✅ Complete |
| **modal_tableaux.py** | Modal logic tableaux | 578 | ✅ Complete |
| **shadow_prover.py** | Shadow prover port | 776 | ✅ Complete |
| **dcec_parsing.py** | DCEC parser | 435 | ✅ Complete |
| **dcec_cleaning.py** | Expression cleaning | 221 | ✅ Complete |
| **dcec_prototypes.py** | Prototype definitions | 520 | ✅ Complete |
| **dcec_integration.py** | Integration utilities | 428 | ✅ Complete |
| **problem_parser.py** | Problem file parser | 244 | ✅ Complete |

---

## 🏗️ Architecture Overview

### Design Principles

1. **Pure Python 3** - No external dependencies
2. **Type Safety** - Comprehensive type hints
3. **Immutability** - Use frozen dataclasses where possible
4. **Composition** - Prefer composition over inheritance
5. **Testability** - Design for easy testing
6. **Performance** - Optimize hot paths, use caching

### Core Abstractions

#### 1. Formulas

```python
Formula (ABC)
├── AtomicFormula          # P(t1, t2, ...)
├── DeonticFormula         # O(φ), P(φ), F(φ)
├── CognitiveFormula       # B(a, φ), K(a, φ), I(a, φ)
├── TemporalFormula        # □(φ), ◊(φ)
├── ConnectiveFormula      # φ ∧ ψ, φ ∨ ψ, ¬φ, φ → ψ
└── QuantifiedFormula      # ∀x.φ, ∃x.φ
```

#### 2. Terms

```python
Term (ABC)
├── VariableTerm           # Variables: x, y, z
└── FunctionTerm           # Functions: f(t1, t2, ...)
```

#### 3. Namespace

```python
DCECNamespace
├── Sorts                  # Type definitions
├── Variables              # Typed variables
├── Functions              # Function symbols
└── Predicates             # Predicate symbols
```

#### 4. Container

```python
DCECContainer
├── Statements             # List of DCEC statements
├── Namespace              # Symbol management
└── Methods                # create_obligation(), create_belief(), etc.
```

#### 5. Prover

```python
TheoremProver
├── Axioms                 # Knowledge base
├── Proof Cache            # Cached proofs (100-20000x speedup)
├── Inference Engine       # 50+ inference rules
└── Proof Strategy         # Strategy management
```

### Data Flow

```
Natural Language → NL Converter → DCEC String → Parser → Formula Objects
                                                              ↓
                                                    Theorem Prover
                                                              ↓
                                                        Proof Result
```

---

## 🧪 Testing Strategy

### Test Organization

```
tests/unit_tests/logic/CEC/native/
├── test_dcec_core.py                 # Core classes (35+ tests)
├── test_dcec_namespace.py            # Namespace (30+ tests)
├── test_prover_core.py               # Theorem prover (80+ tests)
├── test_nl_converter.py              # NL conversion (45+ tests)
├── test_grammar_engine.py            # Grammar (40+ tests)
├── test_dcec_english_grammar.py      # English grammar (35+ tests)
├── test_modal_tableaux.py            # Modal logic (30+ tests)
├── test_shadow_prover.py             # Shadow prover (25+ tests)
├── test_dcec_parsing.py              # Parsing (30+ tests)
├── test_dcec_cleaning.py             # Cleaning (20+ tests)
├── test_dcec_prototypes.py           # Prototypes (25+ tests)
├── test_dcec_integration.py          # Integration (25+ tests)
└── test_problem_parser.py            # Problem parser (18+ tests)

Total: 418+ tests, ~80-85% coverage
```

### Running Tests

```bash
# Run all CEC tests
pytest tests/unit_tests/logic/CEC/ -v

# Run specific test file
pytest tests/unit_tests/logic/CEC/native/test_prover_core.py -v

# Run with coverage
pytest tests/unit_tests/logic/CEC/ --cov=ipfs_datasets_py.logic.CEC.native --cov-report=html

# Run in parallel (faster)
pytest tests/unit_tests/logic/CEC/ -n auto

# Run specific test
pytest tests/unit_tests/logic/CEC/native/test_prover_core.py::test_modus_ponens -v

# Run with verbose output
pytest tests/unit_tests/logic/CEC/ -vv
```

### Writing Tests

#### Test Structure

Follow the **GIVEN-WHEN-THEN** pattern:

```python
def test_obligation_creation():
    """Test creating an obligation formula."""
    # GIVEN: A container
    container = DCECContainer()
    
    # WHEN: Creating an obligation
    obligation = container.create_obligation("robot", "cleanRoom")
    
    # THEN: The obligation is correctly formatted
    assert obligation == "O(cleanRoom(robot))"
    assert obligation in container.get_statements()
```

#### Test Categories

1. **Unit Tests** - Test individual functions/classes
2. **Integration Tests** - Test component interactions
3. **Regression Tests** - Prevent known bugs from returning
4. **Performance Tests** - Ensure performance targets

#### Coverage Requirements

- **Target:** 90%+ coverage
- **Critical modules:** 95%+ coverage
- **Current:** ~80-85% coverage

### Test Fixtures

```python
import pytest
from ipfs_datasets_py.logic.CEC.native import DCECContainer, TheoremProver

@pytest.fixture
def container():
    """Provide a fresh DCEC container."""
    return DCECContainer()

@pytest.fixture
def prover():
    """Provide a fresh theorem prover."""
    return TheoremProver(enable_cache=False)  # Disable cache for tests

# Use in tests
def test_with_fixtures(container, prover):
    container.create_obligation("robot", "task")
    prover.add_axiom("O(task(robot))")
    # ...
```

---

## 🎨 Code Style Guidelines

### Python Style

Follow **PEP 8** with these conventions:

#### Naming Conventions

```python
# Classes: PascalCase
class DCECContainer:
    pass

# Functions/methods: snake_case
def create_obligation(agent: str, action: str) -> str:
    pass

# Constants: UPPER_SNAKE_CASE
MAX_PROOF_STEPS = 1000

# Private: leading underscore
def _internal_helper():
    pass

# Very private: double leading underscore
def __internal_only():
    pass
```

#### Type Hints

**Always use type hints:**

```python
from typing import List, Dict, Optional, Union, Set

def prove_theorem(
    axioms: List[str],
    goal: str,
    max_steps: int = 1000
) -> ProofResult:
    """Prove a theorem.
    
    Args:
        axioms: List of axiom formulas
        goal: Goal formula to prove
        max_steps: Maximum proof steps (default: 1000)
    
    Returns:
        ProofResult with is_proven, proof_steps, etc.
    
    Raises:
        ValueError: If goal is invalid
        ProofError: If proof fails unexpectedly
    """
    pass
```

#### Docstrings

Use **Google-style docstrings:**

```python
def create_belief(self, agent: str, proposition: str) -> str:
    """Create a belief formula.
    
    Creates a cognitive belief formula of the form B(agent, proposition).
    
    Args:
        agent: Name of the agent
        proposition: Proposition the agent believes
    
    Returns:
        Formatted belief formula string
    
    Example:
        >>> container = DCECContainer()
        >>> container.create_belief("robot", "taskComplete")
        'B(robot, taskComplete)'
    """
    return f"B({agent}, {proposition})"
```

### Code Formatting

#### Black

Use **black** for automatic formatting:

```bash
# Format a file
black ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Format all files
black ipfs_datasets_py/logic/CEC/native/

# Check without modifying
black --check ipfs_datasets_py/logic/CEC/native/
```

#### isort

Use **isort** for import sorting:

```bash
# Sort imports
isort ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Check without modifying
isort --check-only ipfs_datasets_py/logic/CEC/native/
```

### Linting

#### flake8

```bash
# Lint a file
flake8 ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Lint all files
flake8 ipfs_datasets_py/logic/CEC/native/

# Common flags
flake8 --max-line-length=100 --ignore=E203,W503 ipfs_datasets_py/logic/CEC/native/
```

#### mypy

```bash
# Type check
mypy ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Type check with strict mode
mypy --strict ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Check all files
mypy ipfs_datasets_py/logic/CEC/native/
```

### Pre-commit Hooks

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.1.0
    hooks:
      - id: black
        language_version: python3.12

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: ['--max-line-length=100']

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.0.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

Install:
```bash
pip install pre-commit
pre-commit install
```

---

## 🔄 Contribution Workflow

### 1. Find or Create an Issue

**Before starting work:**
1. Check existing issues
2. Create new issue if needed
3. Discuss approach in issue comments
4. Get approval from maintainers

### 2. Create a Branch

```bash
# Update main branch
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/add-new-operator

# Or bugfix branch
git checkout -b bugfix/fix-proof-caching
```

**Branch naming:**
- `feature/` - New features
- `bugfix/` - Bug fixes
- `refactor/` - Code refactoring
- `docs/` - Documentation changes
- `test/` - Test additions/improvements

### 3. Make Changes

**Development cycle:**

```bash
# 1. Make code changes
vim ipfs_datasets_py/logic/CEC/native/dcec_core.py

# 2. Run tests
pytest tests/unit_tests/logic/CEC/native/test_dcec_core.py -v

# 3. Check code style
black ipfs_datasets_py/logic/CEC/native/dcec_core.py
flake8 ipfs_datasets_py/logic/CEC/native/dcec_core.py
mypy ipfs_datasets_py/logic/CEC/native/dcec_core.py

# 4. Commit changes
git add ipfs_datasets_py/logic/CEC/native/dcec_core.py
git commit -m "Add new deontic operator LIBERTY"

# 5. Repeat
```

### 4. Commit Guidelines

**Commit message format:**

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Example:**

```
feat(dcec_core): Add LIBERTY deontic operator

- Add LIBERTY to DeonticOperator enum
- Add create_liberty() method to DCECContainer
- Add tests for LIBERTY operator
- Update documentation

Fixes #123
```

**Types:**
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation changes
- `test` - Test additions/changes
- `refactor` - Code refactoring
- `perf` - Performance improvements
- `chore` - Maintenance tasks

### 5. Push and Create PR

```bash
# Push branch
git push origin feature/add-new-operator

# Create pull request on GitHub
# - Title: Clear, descriptive
# - Description: What, why, how
# - Link to issue
# - Screenshots if UI changes
```

### 6. Code Review

**Address review comments:**

```bash
# Make requested changes
vim ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Add new tests
vim tests/unit_tests/logic/CEC/native/test_dcec_core.py

# Commit changes
git add .
git commit -m "Address review comments: Add edge case tests"

# Push updates
git push origin feature/add-new-operator
```

### 7. Merge

**After approval:**
1. Ensure CI passes
2. Squash and merge (usually)
3. Delete branch
4. Close related issue

---

## 🛠️ Building & Running

### Local Development

```bash
# Install in editable mode
pip install -e .

# Install with test dependencies
pip install -e ".[test]"

# Run interactive Python
python
>>> from ipfs_datasets_py.logic.CEC.native import DCECContainer
>>> container = DCECContainer()
>>> container.create_obligation("robot", "task")
'O(task(robot))'
```

### Running Examples

```bash
# Find example scripts
find ipfs_datasets_py/logic/CEC -name "*example*.py"
find ipfs_datasets_py/logic/CEC -name "*demo*.py"

# Run an example
python ipfs_datasets_py/logic/CEC/native/dcec_core.py
```

### Building Documentation

```bash
# Generate API documentation (if sphinx configured)
cd docs
make html

# View documentation
open _build/html/index.html
```

---

## 🐛 Debugging Tips

### Enable Debug Logging

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Or for specific module
logging.getLogger('ipfs_datasets_py.logic.CEC.native').setLevel(logging.DEBUG)

# Use in code
from ipfs_datasets_py.logic.CEC.native import TheoremProver

prover = TheoremProver(debug=True)  # Enable debug mode
result = prover.prove("B")

# View proof steps
for step in result.proof_steps:
    print(f"Step: {step}")
```

### Using Python Debugger

```python
# Add breakpoint
import pdb; pdb.set_trace()

# Or use built-in breakpoint() (Python 3.7+)
breakpoint()

# Debugger commands:
# n - next line
# s - step into
# c - continue
# p <var> - print variable
# l - list code
# q - quit
```

### Common Issues

#### Issue: Import Error

```python
# Error
ModuleNotFoundError: No module named 'ipfs_datasets_py'

# Solution
pip install -e .
```

#### Issue: Type Checking Errors

```python
# Error
mypy: Incompatible types in assignment

# Solution: Add type hints
def my_function(x: int) -> str:
    return str(x)
```

#### Issue: Test Failures

```bash
# Run single test with verbose output
pytest tests/unit_tests/logic/CEC/native/test_prover_core.py::test_modus_ponens -vv

# Enable print statements
pytest tests/unit_tests/logic/CEC/native/test_prover_core.py -s
```

---

## 📦 Release Process

### Version Numbering

Follow **Semantic Versioning** (semver):

- **Major** (1.0.0): Breaking changes
- **Minor** (1.1.0): New features, backward compatible
- **Patch** (1.1.1): Bug fixes

### Release Checklist

1. **Update version**
   - `__version__` in `__init__.py`
   - `setup.py`

2. **Update CHANGELOG**
   - Add new version section
   - List all changes

3. **Run full test suite**
   ```bash
   pytest tests/unit_tests/logic/CEC/ --cov
   ```

4. **Update documentation**
   - README.md
   - STATUS.md
   - API_REFERENCE.md

5. **Create git tag**
   ```bash
   git tag -a v1.1.0 -m "Release version 1.1.0"
   git push origin v1.1.0
   ```

6. **Create GitHub release**
   - Tag: v1.1.0
   - Title: "CEC v1.1.0"
   - Description: Changelog
   - Attach artifacts if needed

---

## 🎯 Common Tasks

### Adding a New Operator

```python
# 1. Add to enum (dcec_core.py)
class DeonticOperator(Enum):
    # ... existing operators
    LIBERTY = "L"  # New operator

# 2. Add formula class if needed
@dataclass
class LibertyFormula(Formula):
    inner_formula: Formula

# 3. Add container method (dcec_namespace.py)
class DCECContainer:
    def create_liberty(self, action: str) -> str:
        """Create liberty formula: L(action)"""
        formula = f"L({action})"
        self.add_statement(formula)
        return formula

# 4. Add tests
def test_liberty_creation():
    container = DCECContainer()
    liberty = container.create_liberty("vote")
    assert liberty == "L(vote)"

# 5. Update documentation
# - API_REFERENCE.md
# - QUICKSTART.md (if relevant)
```

### Adding a New Inference Rule

```python
# 1. Add to InferenceEngine (prover_core.py)
class InferenceEngine:
    def apply_liberty_rule(self, formula: str) -> Optional[str]:
        """Apply liberty inference rule: L(φ) ⊢ P(φ)"""
        # Parse formula
        # Apply rule logic
        # Return result

# 2. Register rule in TheoremProver
class TheoremProver:
    def __init__(self):
        self.inference_rules = [
            # ... existing rules
            self.engine.apply_liberty_rule,
        ]

# 3. Add tests
def test_liberty_inference():
    prover = TheoremProver()
    prover.add_axiom("L(vote)")
    result = prover.prove("P(vote)")
    assert result.is_proven

# 4. Update documentation
```

### Adding a New Conversion Pattern

```python
# 1. Add pattern (nl_converter.py)
class NaturalLanguageConverter:
    def __init__(self):
        self.patterns = [
            # ... existing patterns
            (r"it is permitted to (\w+)", r"P(\1)"),
            (r"(\w+) is free to (\w+)", r"L(\2(\1))"),
        ]

# 2. Add tests
def test_liberty_conversion():
    converter = NaturalLanguageConverter()
    dcec = converter.english_to_dcec("Alice is free to vote")
    assert dcec == "L(vote(Alice))"

# 3. Update documentation
```

---

## ❓ FAQ

### Q: Where do I start?

**A:** Read [QUICKSTART.md](./QUICKSTART.md), then this guide, then explore the code.

### Q: How do I add a new feature?

**A:** See [Adding a New Operator](#adding-a-new-operator) and [Contribution Workflow](#contribution-workflow).

### Q: What's the test coverage requirement?

**A:** 90%+ overall, 95%+ for critical modules.

### Q: How do I run tests?

**A:** `pytest tests/unit_tests/logic/CEC/ -v`

### Q: What Python version?

**A:** 3.12+ required.

### Q: Are there external dependencies?

**A:** No runtime dependencies. Only dev dependencies (pytest, mypy, etc.).

### Q: How do I update documentation?

**A:** Edit markdown files directly, ensure accuracy, commit with docs type.

### Q: What's the release schedule?

**A:** No fixed schedule. Releases when features/fixes are ready.

### Q: How do I report a bug?

**A:** Create a GitHub issue with:
- Clear description
- Steps to reproduce
- Expected vs actual behavior
- Python version, OS
- Minimal code example

### Q: Can I add external dependencies?

**A:** Generally no for runtime. Discuss with maintainers first.

---

## 📚 Additional Resources

### Internal Documentation

- **[README.md](./README.md)** - Main entry point
- **[STATUS.md](./STATUS.md)** - Implementation status
- **[QUICKSTART.md](./QUICKSTART.md)** - 5-minute tutorial
- **[API_REFERENCE.md](./API_REFERENCE.md)** - Complete API
- **[CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)** - Comprehensive guide

### External Resources

- **Python Style Guide:** [PEP 8](https://pep8.org/)
- **Type Hints:** [PEP 484](https://www.python.org/dev/peps/pep-0484/)
- **Docstrings:** [PEP 257](https://www.python.org/dev/peps/pep-0257/)
- **pytest:** [pytest.org](https://pytest.org/)

### Community

- **Issues:** [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Discussions:** [GitHub Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)
- **PRs:** [Pull Requests](https://github.com/endomorphosis/ipfs_datasets_py/pulls)

---

## 🙏 Thank You!

Thank you for contributing to CEC! Your work helps make formal reasoning accessible to everyone.

**Questions?** Open an issue or start a discussion.

**Happy coding!** 🚀

---

**Last Updated:** 2026-02-18  
**Version:** 1.0  
**Maintainers:** IPFS Datasets Team
