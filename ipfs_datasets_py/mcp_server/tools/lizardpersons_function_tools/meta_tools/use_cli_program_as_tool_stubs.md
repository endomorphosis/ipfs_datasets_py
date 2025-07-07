# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/meta_tools/use_cli_program_as_tool.py'

Files last updated: 1748926712.4231782

Stub file last updated: 2025-07-07 01:10:14

## _find_program_entry_point

```python
def _find_program_entry_point(entrance_dir: Path) -> list[dict]:
    """
    Same as in list_tools_in_cli_dir - you'll need to copy this function
    """
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

## _normalize_program_name

```python
def _normalize_program_name(program_name: str) -> str:
    """
    Normalize the program name to ensure consistent matching.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _run_python_command_or_module

```python
def _run_python_command_or_module(target_path: Path, run_as_module: bool = False, python_cmd: str = "python", cli_arguments: list[str] = [], timeout: int = 30) -> tuple[str, str]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _validate_program_name

```python
def _validate_program_name(program_name: str) -> None:
    """
    Validate the program name to ensure the LLM didn't put in anything unexpected.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## use_cli_program_as_tool

```python
def use_cli_program_as_tool(program_name: str, cli_arguments: list[str] = []) -> dict[str, str]:
    """
    Run a argparse-based CLI tool files in the tools/cli directory.
WARNING: This function does not validate the CLI program's authenticity, functionality, or security.
It is the user's and LLM's responsibility to ensure that the program is safe to run.

Args:
    program_name (str): The name of the program.
    cli_arguments (list[str], optional): Command-line arguments to pass to the tool, if it takes any.
        If not provided, defaults to an empty list, which is equivalent to running the tool without any arguments.
        e.g. 'python tools/cli/my_tool.py'.

Returns:
    dict[str, str]: A dictionary containing the following:
        - 'name': The program_name argument.
        - 'results': The output of the tool when run with the provided arguments.
    If an error occurs, the dictionary will contain:
        - 'name': The program_name argument.
        - 'path': The path to the tool file.
        - 'help_menu': The tool's help menu, if available.
        - 'error': The name of the error that occured.
        - 'error_msg': A string describing the error that occurred.
Raises:
    FileNotFoundError: If the program is not found in the tools directory.
    ValueError: If the program_name argument is invalid.
    Exception: If there is an error running the program or parsing its output.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
