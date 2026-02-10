# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/configs.py'

Files last updated: 1750521329.7713337

Stub file last updated: 2025-07-07 02:35:43

## CONFIG_DIR

```python
@property
def CONFIG_DIR(self) -> Path:
    """
    The directory containing configuration files.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Configs

## Configs

```python
@dataclass
class Configs:
    """
    Configuration settings for the IPFS Datasets MCP server.

Attributes:
    verbose: Enable verbose output
    log_level: The log level for the server and logger
    host: Host for the server
    port: Port for the server
    reload: Enable auto-reload
    tool_timeout: Timeout for tool execution in seconds
    enabled_tool_categories: List of enabled tool categories
    transport: Transport protocol for the MCP server
    ipfs_kit_integration: Integration method for ipfs_kit_py ('direct' or 'mcp')
    ipfs_kit_mcp_url: URL of the ipfs_kit_py MCP server (if using 'mcp' integration)

Properties:
    ROOT_DIR: The root directory of the project
    PROJECT_NAME: The name of the project
    CONFIG_DIR: The directory containing configuration files
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PROJECT_NAME

```python
@property
def PROJECT_NAME(self) -> str:
    """
    The name of the project.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Configs

## ROOT_DIR

```python
@property
def ROOT_DIR(self) -> Path:
    """
    The root directory of the project.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Configs

## load_config_from_yaml

```python
def load_config_from_yaml(config_path: Optional[str] = None) -> Configs:
    """
    Load configuration from a YAML file.

Args:
    config_path: Path to the YAML configuration file

Returns:
    Configs: Configuration settings
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
