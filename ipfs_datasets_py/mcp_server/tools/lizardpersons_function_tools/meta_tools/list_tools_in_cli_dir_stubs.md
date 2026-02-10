# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/meta_tools/list_tools_in_cli_dir.py'

Files last updated: 1748926729.5524101

Stub file last updated: 2025-07-07 01:10:14

## _find_program_entry_point

```python
def _find_program_entry_point(entrance_dir: Path) -> list[dict]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _get_name_and_help_menu

```python
def _get_name_and_help_menu(file: Path, run_as_module: bool = False, timeout: int = 10) -> tuple[str, str]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _get_program_name_from

```python
def _get_program_name_from(help_output: str) -> str:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _has_argparse_parser

```python
def _has_argparse_parser(content: str) -> bool:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## list_tools_in_cli_dir

```python
def list_tools_in_cli_dir(get_help_menu: bool = True) -> list[dict[str, str]]:
    """
    Lists all working argparse-based CLI tool files in the tools/cli directory.

Args:
    get_help_menu (bool): If True, gets the tool's docstring. Defaults to True.

Returns:
    list[dict[str, str]]: List of dictionaries containing Python filenames (without .py extension).
        If `get_help_menu` is True, each dictionary will also contain the tool's help menu.
    If no working tools are found, returns an empty list.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
