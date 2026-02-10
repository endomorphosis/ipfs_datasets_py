# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/development_tools/config.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 01:10:13

## CodebaseSearchConfig

```python
@dataclass
class CodebaseSearchConfig:
    """
    Configuration for codebase search tool.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DevelopmentToolsConfig

```python
@dataclass
class DevelopmentToolsConfig:
    """
    Main configuration for all development tools.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DocumentationGeneratorConfig

```python
@dataclass
class DocumentationGeneratorConfig:
    """
    Configuration for documentation generator tool.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LintingToolsConfig

```python
@dataclass
class LintingToolsConfig:
    """
    Configuration for linting tools.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TestGeneratorConfig

```python
@dataclass
class TestGeneratorConfig:
    """
    Configuration for test generator tool.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TestRunnerConfig

```python
@dataclass
class TestRunnerConfig:
    """
    Configuration for test runner tool.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __post_init__

```python
def __post_init__(self):
    """
    Post-initialization validation and setup.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DevelopmentToolsConfig

## config

```python
async def config():
    """
    Development tools configuration manager.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## from_dict

```python
@classmethod
def from_dict(cls, config_dict: Dict[str, Any]) -> "DevelopmentToolsConfig":
    """
    Create configuration from dictionary.

Args:
    config_dict: Configuration dictionary

Returns:
    DevelopmentToolsConfig instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** DevelopmentToolsConfig

## from_file

```python
@classmethod
def from_file(cls, config_path: str) -> "DevelopmentToolsConfig":
    """
    Load configuration from a file.

Args:
    config_path: Path to configuration file (JSON or YAML)

Returns:
    DevelopmentToolsConfig instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** DevelopmentToolsConfig

## get_config

```python
def get_config() -> DevelopmentToolsConfig:
    """
    Get the global development tools configuration.

Returns:
    DevelopmentToolsConfig instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## reset_config

```python
def reset_config() -> None:
    """
    Reset the global configuration to None (forces reload).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## save_to_file

```python
def save_to_file(self, config_path: str) -> None:
    """
    Save configuration to file.

Args:
    config_path: Path to save configuration file
    """
```
* **Async:** False
* **Method:** True
* **Class:** DevelopmentToolsConfig

## set_config

```python
def set_config(config: DevelopmentToolsConfig) -> None:
    """
    Set the global development tools configuration.

Args:
    config: DevelopmentToolsConfig instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert configuration to dictionary.

Returns:
    Configuration dictionary
    """
```
* **Async:** False
* **Method:** True
* **Class:** DevelopmentToolsConfig
