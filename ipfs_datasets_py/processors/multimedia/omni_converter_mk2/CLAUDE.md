# CLAUDE.md

## Jobs Available
- [ ] 1: Fallback processors for `core/content_extractor/processors/fallbacks`
- [ ] 2: Unit Tests for functions in `core/content_extractor/processors/fallbacks`
- [ ] 3: Mime-type specific processors for `core/content_extractor/processors/by_mime_type`
- [ ] 4: Unit Tests for functions in `core/content_extractor/processors/by_mime_type`
- [ ] 5: Dependency-specific functions in `core/content_extractor/processors/by_dependency`
- [ ] 6: Unit Tests for functions in `core/content_extractor/processors/by_dependency`
- [ ] 7: Ability-specific processors for `core/content_extractor/processors/by_ability`
- [ ] 8: Unit Tests for processors in `core/content_extractor/processors/by_ability`


## Project Rules
- You will be assigned a designation number and the directory it is assigned to.
- Only work in your designated directory. Every directory and file outside it is to be considered a black box that you cannot modify or access.
- You will produce 1 function for export. The function has no arguments and constructs a single object.
- The object must have a series of pre-specified characteristics and meet pre-specified evaluation metrics. These characteristics and metrics will be specified in that directory's README.md file.
- Document all actions taken in your directory's CHANGELOG.md
- Document all actions that need to be do be dne in your directory's TODO.md
- Document your software architecture decisions in your directory's ARCHITECTURE.md
- Read all the documents first. If you cannot find one, ask for it before looking for it.

## Module Setup
- Python version: 3.12+.
- You have access to the following read-only objects: `logger`, `configs`, and `dependencies`.
- These files are to be considered black boxes, and you should not look at them or modify them.
- All third-party dependencies are permitted, but must be accessed as attributes from `dependencies.py`. These must be accessed directly.
- All configs must be accessed as attributes through the `configs` object from `configs.py`. These must be accessed directly.
- All logging must be done through the `logger` object from `logger.py`.

## Template Module File
```python
# my_module.py

class SomeClass:

    def __init__(self, resources=None, configs=None):
        self.resources = resources
        self.configs = configs

        self._some_utility_function = resources['some_utility']

    def some_method(self):
        logger.info("Executing some_method")
        result = some_utility_function(self.configs.some_setting)
        return result

# factory.py
from configs import configs
from logger import logger
from utils import utils
import dependencies import dependencies

from some_class import SomeClass

def make_some_class():

    resources = {
        'logger': logger,
        'some_utility': utils.some_utility_function,
        'another_utility': utils.another_utility_function,
        'third_part_dependency': dependencies.third_part_dependency
    }
    return SomeClass(resources=resources, configs=configs)
```

## Code Style Guidelines
- **Imports**: Standard library first, third-party next, local modules last (alphabetically)
- **Docstrings**: Google style docstrings required for all functions/methods/classes
- **Type Hints**: Required for all function parameters and return values
- **Naming**: snake_case for variables/functions, CamelCase for classes, UPPER_CASE for constants
- **Error Handling**: Use specific exceptions with helpful error messages
