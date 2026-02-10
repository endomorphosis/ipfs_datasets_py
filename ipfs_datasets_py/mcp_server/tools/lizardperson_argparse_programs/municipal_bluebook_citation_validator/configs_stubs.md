# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardperson_argparse_programs/municipal_bluebook_citation_validator/configs.py'

Files last updated: 1751408933.7164564

Stub file last updated: 2025-07-07 01:10:14

## ROOT_DIR

```python
@property
def ROOT_DIR(self) -> Path:
    """
    Return the root directory of the project.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Configs

## _Configs

```python
class _Configs(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _MySqlConfig

```python
class _MySqlConfig(BaseModel):
    """
    Configuration model for MySQL database connection parameters.

Attributes:
    host (str): The hostname or IP address of the MySQL server.
    port (int): The port number on which the MySQL server is listening.
    user (SecretStr): The username for database authentication (stored securely).
    password (SecretStr): The password for database authentication (stored securely).
    database (SecretStr): The name of the database to connect to (stored securely).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __getitem__

```python
def __getitem__(self, key):
```
* **Async:** False
* **Method:** True
* **Class:** _Configs

## mysql_configs

```python
@property
def mysql_configs(self) -> dict:
    """
    Return MySQL configurations as a Pydantic model.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Configs

## mysql_configs

```python
@mysql_configs.setter
def mysql_configs(self, value: dict):
    """
    Set MySQL configurations from a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Configs

## to_dict

```python
def to_dict(self) -> dict:
    """
    Convert the configuration to a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _Configs
