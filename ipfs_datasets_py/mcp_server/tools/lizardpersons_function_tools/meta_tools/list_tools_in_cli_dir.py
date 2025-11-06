import ast
import logging
import os
from pathlib import Path


# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create file handler
log_file = os.path.join(os.path.dirname(__file__), 'list_tools_in_cli_dir.log')
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Add handler to logger
logger.addHandler(file_handler)


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


def _get_name_and_help_menu(
    file: Path,
    run_as_module: bool = False,
    timeout: int = 10 # seconds
    ) -> tuple[str, str]:
    import subprocess
    venv_python = Path.cwd() / '.venv/bin/python' # NOTE This is the server's venv.
    python_cmd = str(venv_python.resolve()) if venv_python.is_file() else 'python'
    cwd = None  # Default to current directory
    
    if run_as_module:
        # Change to the parent directory of the module
        cwd = file.parent
        module_name = file.stem
        cmd_list = [python_cmd, '-m', module_name, '--help']
    else:
        cwd = None  # Use current directory
        cmd_list = [python_cmd, str(file.resolve()), '--help']

    logger.debug(f"Running command: {' '.join(cmd_list)} in {cwd if cwd else 'current directory'}")
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
            cwd=cwd  # Set working directory
        )
        help_menu = result.stdout.strip()
        return _get_program_name_from(help_menu), help_menu
    except subprocess.CalledProcessError as e:
        raise Exception(f"Error running {file.name} with --help: {e.stderr.strip()}")
    except Exception as e:
        raise Exception(f"A {type(e).__name__} occurred while getting help menu for {file.name}: {e}") from e


def _has_argparse_parser(content: str) -> bool:
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    if (hasattr(node.value.func, 'attr') and 
                        node.value.func.attr == 'ArgumentParser'):
                        return True
            # Also check for direct calls without assignment
            elif isinstance(node, ast.Call):
                if (hasattr(node.func, 'attr') and 
                    node.func.attr == 'ArgumentParser'):
                    return True
    except:
        return False
    return False

def _find_program_entry_point(entrance_dir: Path) -> list[dict]:
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
    # Keep this path hardcoded so that we aren't running argparse tools we haven't vetted.
    tools_dir = Path(__file__).parent.parent
    cli_tools_dir = tools_dir / 'cli'
    python_files = []

    for tool_dir in cli_tools_dir.iterdir():
        if not tool_dir.is_dir() or tool_dir.name.startswith('_') or tool_dir.name.startswith('.'):
            # Skip non-directory files, hidden directories, and directories starting with an underscore
            continue
        if '__pycache__' in tool_dir.parts or 'tests' in tool_dir.parts:
            continue
        program_name: str = None
        target_path: Path = None
        run_as_module = False
        help_menu = "Could not get tool to run with --help. Please check the tool's code for errors."
        entry_point_candidates = _find_program_entry_point(tool_dir)
        # Check for __main__.py file first
        for entry_point in entry_point_candidates:
            entry_point: dict
            if entry_point["is_runnable_module"]:
                # If the entry point is a runnable module, we can use it as the name.
                target_path = entry_point["path"]
                program_name = entry_point["path"].parent.stem
                run_as_module = True
                break
        # Then check for a file with "if __name__ == "__main__":" block
        if target_path is None:
            for entry_point in entry_point_candidates:
                if entry_point["is_entry"]:
                    target_path = entry_point["path"]
                    program_name = entry_point["path"].parent.stem
                    run_as_module = True
                    break
        # If we still don't have a target path, check for a parser
        if target_path is None:
            for entry_point in entry_point_candidates:
                if entry_point["has_parser"]:
                    # If the entry point has a parser, we can use it as the name.
                    target_path = entry_point["path"]
                    break
        if target_path is None:
            # If we can't find a runnable module or parser, it's probably not a valid tool.
            logger.warning(f"No valid entry point found in {tool_dir}. Skipping.")
            continue
        try:
            name, help_menu = _get_name_and_help_menu(target_path, run_as_module=run_as_module)
        except Exception as e:
            # If we can't get the help menu, it's probably not a valid tool either.
            logger.error(f"Error getting name and help menu for {target_path}: {e}")
            name = target_path.stem

        file_dict = {
            'name': program_name if program_name is not None else name,  # Get the name without the .py extension
        }
        if get_help_menu is True:
            file_dict['help_menu'] = help_menu
        python_files.append(file_dict)
    if not python_files:
        return [] # Sort by name for consistent ordering
    return sorted(python_files, key=lambda x: x['name'])
