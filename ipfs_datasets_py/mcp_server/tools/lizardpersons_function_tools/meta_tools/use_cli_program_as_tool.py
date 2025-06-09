import logging
import os
from pathlib import Path

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create file handler
log_file = os.path.join(os.path.dirname(__file__), 'use_cli_program_as_tool.log')
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Add handler to logger
logger.addHandler(file_handler)


def _normalize_program_name(program_name: str) -> str:
    """
    Normalize the program name to ensure consistent matching.
    """
    return program_name.lower().replace(' ', '_').replace('-', '_').removesuffix('.py')


def _get_program_name_from(help_output: str) -> str:
    import re
    # Extract program name from usage line.
    patterns = [
        r'usage:\s+(\S+)',  # Standard: "usage: program_name"
        r'Usage:\s+(\S+)',  # Capitalized: "Usage: program_name"
        r'^(\S+)\s+\[',     # Program name at start with options
        r'usage:\s+(\S+\.py)',  # Look for .py files specifically
        r'usage:\s+.*?(\w+\.py)',  # More flexible .py file matching
    ]
    program_name = None
    for pattern in patterns:
        match = re.search(pattern, help_output, re.MULTILINE)
        if match:
            program_name = match.group(1)
            break
    if program_name is None:
        raise ValueError("Could not extract program name from help output.")
    return program_name


def _has_argparse_parser(content: str) -> bool:
    import ast
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    if (hasattr(node.value.func, 'attr') and 
                        node.value.func.attr == 'ArgumentParser'):
                        return True
    except:
        return False
    return False


def _validate_program_name(program_name: str) -> None:
    """
    Validate the program name to ensure the LLM didn't put in anything unexpected.
    """
    # Prevent the LLM from putting in a file path instead of a program name.
    if Path(program_name).is_file():
        raise ValueError("The program_name argument should be the name of the program, not a file path.")

    # Prevent the LLM from putting in anything but valid python names.
    if '/' in program_name or '\\' in program_name or ' ' in program_name: # Catches "/this_program_name" or "this program name" or "this\program_name"
        raise ValueError("The program_name argument should not contain slashes, backslashes, or spaces.")

    if program_name.startswith('_') or program_name.endswith('_'): # Catches "_this_program_name" or "this_program_name_"
        raise ValueError("The program_name argument should not start or end with an underscore.")


def _run_python_command_or_module(
    target_path: Path,
    run_as_module: bool = False,
    python_cmd: str = 'python',
    cli_arguments: list[str] = [],
    timeout: int = 30  # Increased for documentation generation
) -> tuple[str, str]:
    import subprocess

    if run_as_module:
        # Change to the parent directory of the module
        cwd = target_path.parent
        module_name = target_path.stem
        cmd_list = [python_cmd, '-m', module_name]
    else:
        cwd = None  # Use current directory
        cmd_list = [python_cmd, str(target_path.resolve())]
    
    if cli_arguments:
        cmd_list.extend(cli_arguments)

    try:
        results = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
            cwd=cwd
        )
        logger.debug(f"Command results: {results}")
        
        # Help menu route
        if cli_arguments and cli_arguments[-1] == '--help':
            help_menu = results.stdout.strip()
            return _get_program_name_from(help_menu), help_menu
        # Actual program output route
        else:
            output = results.stdout.strip()
            if results.stderr.strip():
                output += f"\nStderr: {results.stderr.strip()}"
            if not output:
                output = """
Command completed successfully with return code 0, but gave no stdout or stderr output.
This may indicate that the program does not produce console output or that it was run with no arguments.
If you expected console output, please check the program's functionality or its arguments.
                """
            return target_path.stem, output

    except subprocess.CalledProcessError as e:
        error_string = e.stdout.strip() or "No output"
        if e.stderr:
            error_string += f"\nError output: {str(e.stderr).strip()}"
        raise Exception(f"CalledProcessError running {target_path.name}: {error_string}") from e
    except Exception as e:
        raise Exception(f"A {type(e).__name__} occurred while running {target_path.name}: {e}") from e


def _find_program_entry_point(entrance_dir: Path) -> list[dict]:
    """Same as in list_tools_in_cli_dir - you'll need to copy this function"""
    import ast
    files_list = []
    if entrance_dir.is_file():
        entrance_dir = entrance_dir.parent
    for file in entrance_dir.rglob('*.py'):
        if not file.name.startswith('_'):
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                logger.error(f"Error reading file {file}: {e}")
                continue
            _dict = {
                "has_parser": _has_argparse_parser(content),
                "is_entry": True if 'if __name__ == "__main__":' in content else False,
                "is_runnable_module": True if file.stem == '__main__' else False,
            }
            if any(_dict.values()):
                _dict['path'] = file
                files_list.append(_dict)
    return files_list


def use_cli_program_as_tool(
        program_name: str,
        cli_arguments: list[str] = [],
        ) -> dict[str, str]:
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
    _validate_program_name(program_name)

    # Keep this path hardcoded so that we aren't running argparse tools we haven't vetted.
    tools_dir = Path(__file__).parent.parent
    cli_tools_dir = tools_dir / 'cli'

    # Get the virtual environment python executable directly
    venv_python = Path.cwd() / '.venv/bin/python'
    python_cmd = str(venv_python.resolve()) if venv_python.is_file() else 'python'

    # First, try to find the program in tool directories (for modules like documentation_generator)
    for tool_dir in cli_tools_dir.iterdir():
        if not tool_dir.is_dir() or tool_dir.name.startswith('_') or tool_dir.name.startswith('.'):
            continue
        if '__pycache__' in tool_dir.parts or 'tests' in tool_dir.parts:
            continue
            
        # Check if this directory matches our program name
        normalized_dir_name = _normalize_program_name(tool_dir.name)
        normalized_program_name = _normalize_program_name(program_name)
        
        if normalized_dir_name == normalized_program_name:
            # Found matching directory, now find the entry point
            entry_point_candidates = _find_program_entry_point(tool_dir)
            target_path = None
            run_as_module = False
            
            # Check for __main__.py file first
            for entry_point in entry_point_candidates:
                if entry_point["is_runnable_module"]:
                    target_path = entry_point["path"]
                    run_as_module = True
                    break
            
            # Then check for a file with "if __name__ == "__main__":" block
            if target_path is None:
                for entry_point in entry_point_candidates:
                    if entry_point["is_entry"]:
                        target_path = entry_point["path"]
                        run_as_module = True
                        break
            
            # If we still don't have a target path, check for a parser
            if target_path is None:
                for entry_point in entry_point_candidates:
                    if entry_point["has_parser"]:
                        target_path = entry_point["path"]
                        break
                        
            if target_path:
                try:
                    # First verify we can get help
                    name, help_menu = _run_python_command_or_module(
                        target_path, run_as_module, python_cmd, ["--help"]
                    )
                    
                    # Now run with actual arguments
                    _, results = _run_python_command_or_module(
                        target_path, run_as_module, python_cmd, cli_arguments
                    )
                    return {
                        "name": program_name, 
                        "results": results
                    }
                except Exception as e:
                    return {
                        'name': program_name,
                        'path': str(target_path.resolve()),
                        'error': type(e).__name__,
                        'error_msg': str(e),
                        'help_menu': help_menu if 'help_menu' in locals() else "Could not get help menu"
                    }

    # Fallback: try the old method for standalone .py files
    help_menu = None
    for file in cli_tools_dir.rglob('*.py'):
        if not file.name.startswith('_'):
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                continue

            if not _has_argparse_parser(content):
                continue

            try:
                name, help_menu = _run_python_command_or_module(file, False, python_cmd, ["--help"])
            except Exception as e:
                continue

            normalized_name = _normalize_program_name(name)
            normalized_program_name = _normalize_program_name(program_name)
            if normalized_name != normalized_program_name:
                continue

            try:
                _, results = _run_python_command_or_module(file, False, python_cmd, cli_arguments)
                return {
                    "name": program_name, 
                    "results": results
                }
            except Exception as e:
                return {
                    'name': program_name,
                    'path': str(file.resolve()),
                    'error': type(e).__name__,
                    'error_msg': str(e),
                    'help_menu': help_menu
                }

    # If we get here, program wasn't found
    raise FileNotFoundError(f"Program '{program_name}' not found in cli tools directory '{cli_tools_dir.resolve()}'")
