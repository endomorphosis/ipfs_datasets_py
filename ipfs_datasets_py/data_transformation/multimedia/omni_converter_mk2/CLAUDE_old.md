# CLAUDE.md - Project Guidelines

### Documentation
- [SAD.md](SAD.md) - Architecture Implementation Details, including flowchart and class diagrams.
- [PRD.md](PRD.md) - Product Requirements Document, including Minimum Viable Product specification.
- [PHASE16_README.md](PHASE16_README.md) - Details on the current status and future of the project.
- [TOOLS.md](claudes_toolbox/TOOLS.md) - CLI tools to help you when writing code.
- [TESTING.md](TESTING.md) - Guidelines and metrics for creating and running tests.
- [CHANGELOG](CHANGELOG.md) - Record of changes made to the program and to tests.


## Project Structure
- Main converter in root directory
- Extra command line utilities in `tools/`
- Tests in tests/ directory matching the module structure
- Documentation for modules and tests in `docs/` directory matching the module structure.

## Software Architecture Guidelines
- **Inversion of Control**: Use dependency injection for classes to allow for easier testing and flexibility. This should be done by writing framework classes that only take two keyword arguments in their constructor: `resources` and `configs`. The `resources` parameter is a dictionary of callable objects (functions, classes, dependencies, etc). The `configs` parameter is a nested Pydantic dataclass containing any configuration options or values. The framework classes methods should only contain the orchestration logic of the class, and should *not* contain any library-specific logic (e.g., `aiohttp`, `pandas`, etc) or configuration or resources management logic.
- **Separation of Concerns**: Each framework class should have a single responsibility and should not be responsible for managing its own dependencies. This includes method implementation, configuration management, and resource management.
- **Factory Pattern**: Use the function factory pattern to create instances of classes that require dependencies.
### Example Factory Pattern
```
def make_my_class() -> MyClass:
    """Factory function to create an instance of MyClass."""
    from some_library import SomeLibrary
    from configs import configs  # Assuming configs is a nested Pydantic dataclass
    from constants import Constants

    resources = {
        "outside_resource": SomeLibrary.some_math_function,
        "some_constant": Constants.SOME_CONSTANT,  # Property from Constants class.
    }
    return MyClass(resources=resources, configs=configs)
```

All class-specific dependencies, configurations, and resources should be imported inside function, and  that returns an instance of the class. The factory function should take no arguments, but it  The factory function should take no arguments, and all dependencies, configurations, and resources should be defined within the function. If defaults are required, these should be defined in the function itself. The factory function must return an instance of the class.


 defaults must be defined in the function, and the function must return an instance of the class.
- **Fail Fast with Missing Dependencies and Configs**: All classes must check for the presence of required dependencies in their `__init__` constructor. This is implemented via the `resources` parameter, where the dictionary must contain all the dependencies required by the class. Consequentially, `resources` should never be called outside the constructor, the `get` dictionary method must never be used when assigning resources, and defaults should be moved outside the class, either into the resources dictionary itself or into the factory function. This way, if a dependency is missing, a `KeyError` will be raised immediately that will prevent class instantiation. Similarly, the `configs` parameter must be a nested Pydantic dataclass, and all required configuration options must be defined before initialization. If a required configuration option is missing from `configs`, an `AttributeError` will be raised immediately.
- **Composition over Inheritance**: Use composition over inheritance to create classes that are flexible and easy to test. This means that classes should be composed of smaller classes that are responsible for specific tasks, rather than inheriting from a base class. Combine this with the factory pattern to create classes that are easy to test and maintain.

## Example Architecture
```python
from typing import Callable
from configs import Config # Assuming configs a nested Pydantic dataclass

class MyClass:
    def __init__(self, resources: dict[str, Callable], configs: Config):
        self.resources = resources
        self.configs = configs

        self._outside_resource: Callable = self.resources["outside_resource"]
        self._some_constant: str = self.resources["some_constant"]
        self._some_config = self.configs.some_config

    def my_method(self, x: int, y: int) -> int:
        """
        This method does something with x and y.
        """
        if x < 0 or y < 0:
            raise ValueError("Both inputs must be greater than 0")
        else:
            if self._some_config and self._some_constant:
                  return 0
            return self._outside_resource(x, y)

## factory.py
from typing import Callable
from my_class import MyClass # Assuming my_class is the module where MyClass is defined

from some_library import SomeLibrary
from configs import configs # Assuming configs a nested Pydantic dataclass
from constants import Constants

def factory_function_for_my_class() -> MyClass:
    """
    Factory function to create an instance of MyClass.
    """
    resources = {
        "outside_resource": SomeLibrary.some_math_function
        "some_constant": Constants.SOME_CONSTANT, # Property from Constants class.
    }

    return MyClass(resources=resources, configs=configs)

```

## Architecture Implementation Guidelines
- **Use of Pydantic**: Use pydantic for all external configuration and resource management. This allows for easy validation and serialization of configuration options, as well as easy management of dependencies.
- **Use of YAML files**: Use YAML files for all configuration options and for LLM prompts.
- **Use of MD files**: Use MD files for all documentation, including module and test documentation. This allows for easy generation of documentation using the `documentation_generator` tool.



## Build & Run Commands
```bash
# Setup environment and install dependencies
./install.sh

# Run the main program
./start.sh

# Run unit tests
source venv/bin/activate && python -m unittest discover -s tests

# Run a specific test file
source venv/bin/activate && python -m unittest tests/test_filename.py

# Run a specific test case
source venv/bin/activate && python -m unittest tests.test_filename.TestClassName.test_method_name

# Run a tool
source venv/bin/activate && python -m tools.tool_name
```

## Available Tools in /claudes_toolbox
- documentation_generator:  A command-line utility that automatically extracts code structure, docstrings, and type annotations from Python source code to produce comprehensive documentation in Markdown format. It supports multiple docstring styles (Google, NumPy, and reStructuredText) and preserves type hints from source code annotations.

## Code Style Guidelines
- **Docstrings**: Verbose, Google-style docstrings with types, parameters, returns, and examples. This includes tests.
- **Types**: Use type hints for function parameters and return values
- **Imports**: Group standard library, third-party, and local imports; alphabetize within groups
- **Naming**:
  - Classes: PascalCase
  - Functions/methods: snake_case
  - Constants: UPPER_SNAKE_CASE
  - Variables: snake_case
- **Error handling**: Use explicit exception types with descriptive messages
- **Line length**: 100 characters maximum
- **File organization**: Module docstring first, imports second, constants third, then classes/functions

## General Testing Approach
- Implement basic CI for automated testing with streamlined test suites
- Include focused regression tests for critical functionality
- Conduct limited user acceptance testing with internal stakeholders
- Document all test results for analysis and future enhancement
- Docstrings for all tests must be verbose.
- Label files with skeleton tests or integration test scaffolds as `test_skeleton_{test_name}.py`
- Document all placeholder implementations in the files docstring.

## Feature Implementation Guidelines
- **NEVER REMOVE FEATURES**: Once a feature has been implemented, NEVER remove it, even if it causes test failures. Instead, modify the code and/or tests to ensure both the feature and tests work correctly together.
- **Maintain compatibility**: When updating code, ensure backward compatibility is maintained by never deleting files. Instead, write new files that implement the new functionality and leave the old files in place. This allows for easy rollback if needed. Once the new functionality is confirmed to work, the old files will be moved to a `deprecated/` directory.
- **Test adaptation**: When a feature or capability changes, adapt tests to match the new functionality rather than removing the feature to match existing tests.

# Restrictions
## Git Usage Restrictions
- NEVER run git commands (commit, push, pull, etc.)
- Do NOT make git commits or create pull requests
- Do NOT use git to view repository history
- The user will handle all git operations manually

## Critical Working Guidelines
### NEVER Delete or Overwrite User Work
- **NEVER** delete or overwrite existing content in CHANGELOGs, TODOs, or documentation
- **ALWAYS** add to existing content, never replace it
- When updating files, ADD new sections/entries, don't rewrite existing ones
- If you accidentally overwrite something, the user will be justifiably furious

### Follow Established Patterns Exactly
- When the user establishes a pattern (like processor initialization), follow it EXACTLY
- Do NOT try to "improve" or "optimize" established patterns unless you are given explicit permission to do so.
- Do NOT make assumptions about what functions exist - READ the actual code
- If the user says "follow this pattern," copy it precisely for all similar cases.

### Handler Refactoring Pattern (CRITICAL)
**Current State**: We are in the middle of converting handlers to IoC framework classes

**Template to Follow**: `extractors/text_handler.py` is the EXACT pattern for all handlers
- Framework classes with `__init__(self, resources: dict[str, Callable], configs: Configs)`
- Fail-fast extraction of processors in constructor
- Only orchestration logic in methods - NO library-specific code
- All processing delegated to injected processors via `processor(file_path, options)`
- Factory functions named `create_[type]_handler()` 

**Critical Rules**:
- NO fallback logic in handlers (handled in processors)
- NO direct library imports (everything via dependency injection)  
- NO hardcoded values (use constants or configs)
- Follow text_handler.py template EXACTLY - do not deviate

### Read Before Assuming
- **ALWAYS** read existing code before making changes
- Do NOT hallucinate functions, classes, or modules that don't exist
- Use Read, Grep, and Glob tools to understand what's actually there
- Check imports and dependencies in the actual codebase

### Understand the Architecture Before Acting
- Take time to understand WHY the user designed something a particular way
- Ask clarifying questions if the architecture isn't clear or if you notice a flaw.
- Don't redesign - implement what the user has specified
- The user has thought through the design; your job is implementation

### Testing and Completion
- **NEVER** mark things as complete until they are tested and working
- Architecture implementation ≠ completion
- Always clearly indicate when something needs testing before being considered done
- Use warning indicators (⚠️) for untested implementations

### Action Over Analysis
- When given a clear pattern or instruction, implement it immediately
- Don't endlessly discuss - DO the work
- Save questions for when the pattern is genuinely unclear
- The user wants results, not extensive planning discussions
